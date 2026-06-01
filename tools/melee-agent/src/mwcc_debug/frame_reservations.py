"""Diagnose implicit stack frame reservation ranges from pcdump/asm."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .parser import Function, Instruction, Pass, parse_pcdump


_FRAME_RE = re.compile(
    r"\br1\s*,\s*(-?(?:0x[0-9A-Fa-f]+|\d+))\s*\(\s*r1\s*\)"
)
_STACK_REF_RE = re.compile(
    r"(?<![@\w])(?P<offset>-?(?:0x[0-9A-Fa-f]+|\d+))\s*\(\s*r1\s*\)"
)
_SYMBOLIC_STACK_REF_RE = re.compile(
    r"(?P<symbol>@[A-Za-z0-9_]\w*(?:[+-]\d+)?)\s*\(\s*r1\s*\)"
)
_REG_OPERAND_RE = re.compile(r"\b(?P<class>[rf])(?P<num>\d+)\b")
_ASM_COMMENT_RE = re.compile(r"^\s*/\*.*?\*/\s*")
_ASM_OFFSET_BYTES_RE = re.compile(
    r"^\s*[+-]?[0-9A-Fa-f]+:\s+(?:(?:[0-9A-Fa-f]{2})\s+)*"
)


@dataclass(frozen=True)
class _AsmInstruction:
    opcode: str
    operands: str
    pass_name: str
    block_idx: int | None
    instr_idx: int


def analyze_frame_reservations(
    pcdump_text: str,
    function: str,
    *,
    expected_asm_text: str | None = None,
    current_asm_text: str | None = None,
) -> dict:
    """Return a JSON-friendly stack frame reservation report.

    The current side comes from the final pcdump pass. The optional expected
    side may be target assembly from `extract get --full`. Ranges are expressed
    as half-open offsets from the post-prologue r1 value.
    """
    functions = parse_pcdump(pcdump_text, function=function)
    if not functions:
        raise ValueError(f"{function} not found in pcdump")
    current_instructions = _final_instructions(functions[0])
    symbolic_offsets = _resolve_symbolic_stack_homes(
        current_instructions,
        _parse_expected_asm(current_asm_text),
    )
    current = _analyze_instructions(
        current_instructions,
        symbolic_offsets=symbolic_offsets,
    )
    expected = (
        _analyze_instructions(_parse_expected_asm(expected_asm_text))
        if expected_asm_text
        else None
    )

    frame_delta = None
    if expected and expected["frame_size"] is not None and current["frame_size"] is not None:
        frame_delta = expected["frame_size"] - current["frame_size"]

    extra = (
        _extra_low_frame_reservation(current, expected)
        if expected is not None
        else None
    )
    summary = _summary(function, current, expected, frame_delta, extra)
    report = {
        "function": function,
        "current": current,
        "expected": expected,
        "frame_delta": frame_delta,
        "extra_low_frame_reservation": extra,
        "summary": summary,
    }
    return report


def _select_final_pass(fn: Function) -> Pass | None:
    preferred = (
        "FINAL CODE AFTER INSTRUCTION SCHEDULING",
        "AFTER PEEPHOLE OPTIMIZATION",
        "AFTER MERGING EPILOGUE, PROLOGUE",
        "AFTER GENERATING EPILOGUE, PROLOGUE",
    )
    by_name = {p.name: p for p in fn.passes}
    for name in preferred:
        if name in by_name:
            return by_name[name]
    return fn.passes[-1] if fn.passes else None


def _final_instructions(fn: Function) -> list[_AsmInstruction]:
    selected = _select_final_pass(fn)
    if selected is None:
        return []
    out: list[_AsmInstruction] = []
    ordinal = 0
    for block in selected.blocks:
        for instr_idx, instr in enumerate(block.instructions):
            out.append(_from_parser_instruction(
                instr,
                pass_name=selected.name,
                block_idx=block.index,
                instr_idx=instr_idx,
                ordinal=ordinal,
            ))
            ordinal += 1
    return out


def _from_parser_instruction(
    instr: Instruction,
    *,
    pass_name: str,
    block_idx: int | None,
    instr_idx: int,
    ordinal: int,
) -> _AsmInstruction:
    return _AsmInstruction(
        opcode=instr.opcode,
        operands=instr.operands,
        pass_name=pass_name,
        block_idx=block_idx,
        instr_idx=ordinal if block_idx is None else instr_idx,
    )


def _parse_expected_asm(text: str | None) -> list[_AsmInstruction]:
    if not text:
        return []
    out: list[_AsmInstruction] = []
    for line in text.splitlines():
        line = _ASM_COMMENT_RE.sub("", line).strip()
        line = _ASM_OFFSET_BYTES_RE.sub("", line).strip()
        if not line or line.startswith(".") or line.endswith(":"):
            continue
        parts = line.split(None, 1)
        if not parts:
            continue
        opcode = parts[0]
        operands = parts[1].strip() if len(parts) > 1 else ""
        if opcode.startswith("."):
            continue
        out.append(_AsmInstruction(
            opcode=opcode,
            operands=operands,
            pass_name="expected asm",
            block_idx=None,
            instr_idx=len(out),
        ))
    return out


def _analyze_instructions(
    instructions: list[_AsmInstruction],
    *,
    symbolic_offsets: dict[str, int] | None = None,
) -> dict:
    frame_size = _frame_size(instructions)
    access_ranges: dict[tuple[int, int, str], dict] = {}
    access_traces: list[dict] = []
    unresolved_symbolic_homes: list[dict] = []
    frame_seen = False
    symbolic_offsets = symbolic_offsets or {}

    for instr in instructions:
        if _is_frame_alloc(instr):
            frame_seen = True
            continue
        if _is_stack_pointer_restore(instr):
            continue
        symbolic_home = _symbolic_stack_home(instr.operands)
        original_operands = None
        if symbolic_home is not None:
            offset = symbolic_offsets.get(symbolic_home)
            if offset is None:
                unresolved_symbolic_homes.append({
                    "symbol": symbolic_home,
                    "opcode": instr.opcode,
                    "operands": instr.operands,
                    "pass": instr.pass_name,
                    "block_idx": instr.block_idx,
                    "instr_idx": instr.instr_idx,
                })
                continue
            original_operands = instr.operands
        else:
            offset = _stack_offset(instr.operands)
        if offset is None:
            continue
        size = _access_size(instr)
        if size is None:
            continue
        kind = _access_kind(instr)
        trace = {
            "offset": offset,
            "size": size,
            "kind": kind,
            "opcode": instr.opcode,
            "operands": instr.operands,
            "pass": instr.pass_name,
            "block_idx": instr.block_idx,
            "instr_idx": instr.instr_idx,
            "pre_frame": not frame_seen,
        }
        if original_operands is not None:
            trace["original_operands"] = original_operands
            trace["resolved_operands"] = _replace_symbolic_stack_home(
                original_operands,
                symbolic_home,
                offset,
            )
            trace["symbolic_home"] = symbolic_home
        access_traces.append(trace)
        if not frame_seen:
            continue
        if frame_size is not None and not (0 <= offset < frame_size):
            continue
        start = max(0, offset)
        end = offset + size
        if frame_size is not None:
            end = min(end, frame_size)
        if end <= start:
            continue
        access_ranges[(start, end, kind)] = {
            "start": start,
            "end": end,
            "size": end - start,
            "kind": kind,
        }

    used = list(access_ranges.values())
    implicit = []
    if frame_size is not None and frame_size >= 8:
        implicit.append({"start": 0, "end": 8, "size": 8, "kind": "abi-header"})
    unused = _unused_ranges(frame_size, [*used, *implicit])

    return {
        "frame_size": frame_size,
        "access_ranges": sorted(
            used,
            key=lambda item: (item["start"], item["end"], item["kind"]),
        ),
        "accesses": access_traces,
        "unused_ranges": unused,
        "symbolic_home_map": [
            {"symbol": symbol, "offset": offset}
            for symbol, offset in sorted(symbolic_offsets.items())
        ],
        "unresolved_symbolic_homes": unresolved_symbolic_homes,
    }


def _resolve_symbolic_stack_homes(
    symbolic_instructions: list[_AsmInstruction],
    concrete_instructions: list[_AsmInstruction],
) -> dict[str, int]:
    if not concrete_instructions:
        return {}
    resolved: dict[str, int] = {}
    concrete_cursor = 0
    for instr in symbolic_instructions:
        symbol = _symbolic_stack_home(instr.operands)
        if symbol is None:
            continue
        match_idx = _find_concrete_stack_match(
            instr,
            concrete_instructions,
            start=concrete_cursor,
        )
        if match_idx is None:
            continue
        concrete_cursor = match_idx + 1
        offset = _stack_offset(concrete_instructions[match_idx].operands)
        if offset is None:
            continue
        prior = resolved.get(symbol)
        if prior is None:
            resolved[symbol] = offset
        elif prior != offset:
            resolved.pop(symbol, None)
    return resolved


def _find_concrete_stack_match(
    symbolic: _AsmInstruction,
    concrete_instructions: list[_AsmInstruction],
    *,
    start: int,
) -> int | None:
    signature = _stack_match_signature(symbolic)
    if signature is None:
        return None
    for idx in range(start, len(concrete_instructions)):
        concrete = concrete_instructions[idx]
        if _stack_offset(concrete.operands) is None:
            continue
        if _stack_match_signature(concrete) == signature:
            return idx
    for idx, concrete in enumerate(concrete_instructions):
        if _stack_offset(concrete.operands) is None:
            continue
        if _stack_match_signature(concrete) == signature:
            return idx
    return None


def _stack_match_signature(
    instr: _AsmInstruction,
) -> tuple[str, tuple[str, int] | None] | None:
    if _access_size(instr) is None:
        return None
    return instr.opcode, _first_reg(instr.operands)


def _frame_size(instructions: Iterable[_AsmInstruction]) -> int | None:
    for instr in instructions:
        if not _is_frame_alloc(instr):
            continue
        match = _FRAME_RE.search(instr.operands)
        if match:
            return abs(int(match.group(1), 0))
    return None


def _is_frame_alloc(instr: _AsmInstruction) -> bool:
    return instr.opcode == "stwu" and instr.operands.replace(" ", "").startswith("r1,")


def _is_stack_pointer_restore(instr: _AsmInstruction) -> bool:
    return instr.opcode == "addi" and instr.operands.replace(" ", "").startswith("r1,r1,")


def _stack_offset(operands: str) -> int | None:
    match = _STACK_REF_RE.search(operands)
    if match is None:
        return None
    return int(match.group("offset"), 0)


def _symbolic_stack_home(operands: str) -> str | None:
    match = _SYMBOLIC_STACK_REF_RE.search(operands)
    if match is None:
        return None
    return match.group("symbol")


def _replace_symbolic_stack_home(operands: str, symbol: str, offset: int) -> str:
    return operands.replace(f"{symbol}(r1)", f"{offset}(r1)", 1)


def _access_size(instr: _AsmInstruction) -> int | None:
    opcode = instr.opcode
    if opcode in {"lbz", "stb", "lha", "lhz", "sth"}:
        return 1 if opcode in {"lbz", "stb"} else 2
    if opcode in {"lwz", "stw", "lfs", "stfs"}:
        return 4
    if opcode in {"lfd", "stfd", "psq_l", "psq_st"}:
        return 8
    if opcode in {"lmw", "stmw"}:
        reg = _first_reg(instr.operands)
        if reg is None or reg[0] != "r":
            return None
        return max(0, 32 - reg[1]) * 4
    return None


def _access_kind(instr: _AsmInstruction) -> str:
    first = _first_reg(instr.operands)
    if instr.opcode in {"lmw", "stmw"}:
        return "callee-save-gpr"
    if instr.opcode in {"lfd", "stfd"} and first and first[0] == "f" and first[1] >= 14:
        return "callee-save-fpr"
    if instr.opcode in {"lwz", "stw"} and first == ("r", 0):
        return "link-register-save"
    return "local-or-temporary"


def _first_reg(operands: str) -> tuple[str, int] | None:
    match = _REG_OPERAND_RE.search(operands)
    if match is None:
        return None
    return (match.group("class"), int(match.group("num")))


def _unused_ranges(frame_size: int | None, ranges: list[dict]) -> list[dict]:
    if frame_size is None:
        return []
    intervals = sorted(
        (max(0, item["start"]), min(frame_size, item["end"]))
        for item in ranges
        if item["end"] > 0 and item["start"] < frame_size
    )
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    out: list[dict] = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            out.append({"start": cursor, "end": start, "size": start - cursor})
        cursor = max(cursor, end)
    if cursor < frame_size:
        out.append({"start": cursor, "end": frame_size, "size": frame_size - cursor})
    return out


def _first_non_abi_access_offset(side: dict) -> int | None:
    starts = [
        item["start"]
        for item in side.get("access_ranges", [])
        if item.get("start", 0) >= 8
    ]
    return min(starts) if starts else None


def _extra_low_frame_reservation(current: dict, expected: dict | None) -> dict | None:
    if expected is None:
        return None
    cur_first = _first_non_abi_access_offset(current)
    exp_first = _first_non_abi_access_offset(expected)
    if cur_first is None or exp_first is None or exp_first <= cur_first:
        return None
    accesses = [
        item
        for item in current.get("accesses", [])
        if not item.get("pre_frame") and cur_first <= item["offset"] < exp_first
        and (
            current.get("frame_size") is None
            or item["offset"] < current["frame_size"]
        )
        and item.get("kind") not in {
            "callee-save-gpr",
            "callee-save-fpr",
            "link-register-save",
        }
    ]
    return {
        "start": cur_first,
        "end": exp_first,
        "size": exp_first - cur_first,
        "origin": "implicit-frame-reservation",
        "current_accesses_in_range": accesses,
    }


def _summary(
    function: str,
    current: dict,
    expected: dict | None,
    frame_delta: int | None,
    extra: dict | None,
) -> str:
    cur_frame = current.get("frame_size")
    if expected is None or expected.get("frame_size") is None:
        return f"{function}: current frame={cur_frame}; expected frame unavailable"
    exp_frame = expected.get("frame_size")
    if frame_delta == 0:
        return f"{function}: current and expected frames both reserve {cur_frame} bytes"
    if extra is not None and not extra["current_accesses_in_range"]:
        return (
            f"{function}: expected frame={exp_frame}, current frame={cur_frame}; "
            f"target reserves {extra['size']} extra low-frame bytes "
            f"(0x{extra['start']:x}-0x{extra['end']:x}) before the first "
            "callee/local stack access, with no current pcode stack access "
            "origin in that range"
        )
    return (
        f"{function}: expected frame={exp_frame}, current frame={cur_frame}; "
        f"frame delta={frame_delta}"
    )
