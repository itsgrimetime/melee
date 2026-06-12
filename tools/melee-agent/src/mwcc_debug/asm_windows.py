"""Explain small scheduler windows from checkdiff asm code offsets."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class AsmInstruction:
    index: int
    offset: int | None
    line: str
    opcode: str
    operands: str


@dataclass(frozen=True)
class AsmWindowCandidate:
    role: str
    opcode: str
    operands: str
    code_offset: int | None
    current_index: int
    target_index: int | None
    instruction_class: str


@dataclass(frozen=True)
class AsmWindowResult:
    status: str
    window_gap: int | None
    rationale: str
    candidates: tuple[AsmWindowCandidate, ...]
    source_shape_verdict: str
    heuristic_verdict: str
    forceability: str


_PLUS_OFFSET_RE = re.compile(r"^(?P<offset>[0-9A-Fa-f]+):\s*(?P<body>.*)$")
_COMMENT_OFFSET_RE = re.compile(
    r"^/\*\s*(?P<offset>[0-9A-Fa-f]+)\s*\*/\s*(?P<body>.*)$"
)
_BYTE_PREFIX_RE = re.compile(
    r"^(?:(?:[0-9A-Fa-f]{2}|[0-9A-Fa-f]{8})\s+){1,8}(?P<asm>[A-Za-z_.].*)$"
)
_MEMORY_LOAD_OPCODES = {
    "lbz", "lbzu", "lbzx", "lbzux",
    "lha", "lhau", "lhax", "lhaux",
    "lhz", "lhzu", "lhzx", "lhzux",
    "lmw",
    "lwarx",
    "lwz", "lwzu", "lwzx", "lwzux",
    "lfs", "lfsu", "lfsx", "lfsux",
    "lfd", "lfdu", "lfdx", "lfdux",
}


def parse_asm_lines(lines: Sequence[str]) -> list[AsmInstruction]:
    instructions: list[AsmInstruction] = []
    for raw in lines:
        parsed = _parse_asm_line(raw, len(instructions))
        if parsed is not None:
            instructions.append(parsed)
    return instructions


def is_memory_load_opcode(opcode: str) -> bool:
    return opcode.lower() in _MEMORY_LOAD_OPCODES


def explain_code_offset_window(
    rule,
    target_asm: Sequence[str],
    current_asm: Sequence[str],
    source_text: str | None = None,
    source_file: str | None = None,
) -> AsmWindowResult | None:
    _ = (source_text, source_file)
    target = parse_asm_lines(target_asm)
    current = parse_asm_lines(current_asm)
    if not target or not current:
        return None

    before = _single_by_offset(current, rule.before_offset)
    after = _single_by_offset(current, rule.after_offset)
    if before is None or after is None:
        return _missing(
            "current asm does not contain unique instructions at both "
            "rule code offsets"
        )
    if before.opcode != rule.opcode or after.opcode != rule.opcode:
        return _missing(
            "current code offsets do not both name instructions with "
            f"opcode {rule.opcode}"
        )

    low = min(before.index, after.index)
    high = max(before.index, after.index)
    gap = high - low - 1
    if gap > 1:
        return _missing(
            "current code-offset pair is not adjacent or "
            "one-instruction-straddled"
        )
    middle = current[low + 1:high]
    target_pattern = (before, *middle, after)
    target_windows = _matching_target_windows(target, target_pattern)
    if not target_windows:
        return _missing(
            "target asm does not contain a local-order window with the "
            "rule-before instruction before the rule-after instruction"
        )
    if len(target_windows) != 1:
        return AsmWindowResult(
            status="ambiguous",
            window_gap=None,
            rationale=(
                "rule code offsets map to instruction bodies whose local "
                "target order is not unique"
            ),
            candidates=(),
            source_shape_verdict="backend-ceiling-candidate",
            heuristic_verdict="BACKEND_CEILING_CANDIDATE",
            forceability="not-forceable-by-current-hook",
        )
    target_indices_by_current_index = {
        pattern_inst.index: target_inst.index
        for pattern_inst, target_inst in zip(target_pattern, target_windows[0])
    }

    if before.index < after.index:
        status = "already-target"
        ordered = [before, *middle, after]
        roles = [
            "target-first",
            *("intervening" for _ in ordered[1:-1]),
            "target-second",
        ]
        rationale = (
            "target order is already present in current asm for this "
            "checkdiff code-offset window"
        )
    else:
        status = "matched"
        ordered = [after, *middle, before]
        roles = [
            "observed-first",
            *("intervening" for _ in ordered[1:-1]),
            "target-first",
        ]
        rationale = (
            "checkdiff asm maps the non-load rule offsets to a small current "
            "code-order window whose target order is reversed"
        )

    candidates = tuple(
        _candidate(
            role=role,
            inst=inst,
            target_index=target_indices_by_current_index.get(inst.index),
        )
        for role, inst in zip(roles, ordered)
    )
    classes = {candidates[0].instruction_class, candidates[-1].instruction_class}
    if {"local-address-materialization", "counter-increment"} <= classes:
        source_shape_verdict = "source-shape-controllable"
        heuristic_verdict = "SOURCE_SHAPE_CONTROLLABLE"
    else:
        source_shape_verdict = "backend-ceiling-candidate"
        heuristic_verdict = "BACKEND_CEILING_CANDIDATE"

    return AsmWindowResult(
        status=status,
        window_gap=gap,
        rationale=rationale,
        candidates=candidates,
        source_shape_verdict=source_shape_verdict,
        heuristic_verdict=heuristic_verdict,
        forceability="not-forceable-by-current-hook",
    )


def _parse_asm_line(raw: str, index: int) -> AsmInstruction | None:
    stripped = raw.strip()
    if not stripped:
        return None
    if stripped.startswith(("+", "-")):
        stripped = stripped[1:].lstrip()
    if not stripped or stripped.endswith(":") or stripped.startswith("<"):
        return None

    offset: int | None = None
    body = stripped
    match = _PLUS_OFFSET_RE.match(stripped)
    if match:
        offset = int(match.group("offset"), 16)
        body = match.group("body")
    else:
        match = _COMMENT_OFFSET_RE.match(stripped)
        if match:
            offset = int(match.group("offset"), 16)
            body = match.group("body")

    asm = body.split("\t")[-1].strip()
    byte_match = _BYTE_PREFIX_RE.match(asm)
    if byte_match:
        asm = byte_match.group("asm").strip()
    if not asm or asm.endswith(":"):
        return None
    parts = asm.split(None, 1)
    opcode = parts[0]
    operands = parts[1].strip() if len(parts) > 1 else ""
    if (
        asm.startswith((".", "#"))
        or opcode.upper().startswith("R_")
        or opcode.lower().startswith("reloc")
    ):
        return None
    if not opcode or not re.match(r"^[A-Za-z_.][A-Za-z0-9_.]*$", opcode):
        return None
    return AsmInstruction(
        index=index,
        offset=offset,
        line=raw,
        opcode=opcode,
        operands=operands,
    )


def _classify_instruction(opcode: str, operands: str) -> str:
    op = opcode.lower()
    if op == "addi":
        parts = [part.strip() for part in operands.split(",")]
        if len(parts) == 3:
            dst, base, imm = parts
            if base == "r1" and dst != "r1":
                return "local-address-materialization"
            if dst == base and _parse_int(imm) in {1, -1}:
                return "counter-increment"
    if is_memory_load_opcode(op):
        return "memory-load"
    if op.startswith("st"):
        return "memory-store"
    return "other"


def _parse_int(value: str) -> int | None:
    try:
        return int(value, 0)
    except ValueError:
        return None


def _single_by_offset(
    instructions: Sequence[AsmInstruction],
    offset: int,
) -> AsmInstruction | None:
    matches = [inst for inst in instructions if inst.offset == offset]
    return matches[0] if len(matches) == 1 else None


def _instruction_signature(inst: AsmInstruction) -> tuple[str, str]:
    return inst.opcode, inst.operands


def _matching_target_windows(
    instructions: Sequence[AsmInstruction],
    pattern: Sequence[AsmInstruction],
) -> list[tuple[AsmInstruction, ...]]:
    pattern_signatures = tuple(_instruction_signature(inst) for inst in pattern)
    width = len(pattern_signatures)
    windows: list[tuple[AsmInstruction, ...]] = []
    for start in range(0, len(instructions) - width + 1):
        window = tuple(instructions[start:start + width])
        if tuple(_instruction_signature(inst) for inst in window) == pattern_signatures:
            windows.append(window)
    return windows


def _candidate(
    *,
    role: str,
    inst: AsmInstruction,
    target_index: int | None,
) -> AsmWindowCandidate:
    return AsmWindowCandidate(
        role=role,
        opcode=inst.opcode,
        operands=inst.operands,
        code_offset=inst.offset,
        current_index=inst.index,
        target_index=target_index,
        instruction_class=_classify_instruction(inst.opcode, inst.operands),
    )


def _missing(rationale: str) -> AsmWindowResult:
    return AsmWindowResult(
        status="missing",
        window_gap=None,
        rationale=rationale,
        candidates=(),
        source_shape_verdict="backend-ceiling-candidate",
        heuristic_verdict="BACKEND_CEILING_CANDIDATE",
        forceability="not-forceable-by-current-hook",
    )
