"""Debug commands - introspect MWCC compiler internals via remote Windows host.

The MWCC compiler's verbose-debug code path crashes under macOS+wibo+Rosetta but
works natively on Windows. This subcommand bridges that gap: it SSHs into the
configured Windows host and runs the mwcc_debug DLL hook there, streaming the
resulting pcdump.txt back over SSH.

See docs/mwcc-debug.md for one-time setup of the Windows side.
"""

from __future__ import annotations

from contextlib import contextmanager
import dataclasses
import difflib
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Callable, Iterator, Mapping, NoReturn, Optional

import typer

from ._common import DEFAULT_MELEE_ROOT, console
from ..mwcc_debug import (
    FunctionEvents,
    analyze_function,
    derive_target_from_function,
    find_function,
    format_suggestions,
    parse_hook_events,
    parse_pcdump,
    score_function,
    simulate_function,
    suggest,
)
from ..mwcc_debug import candidate_audit
from ..mwcc_debug import cache as pcdump_cache
from ..mwcc_debug import permuter_remote
from ..mwcc_debug.cast_audit import (
    audit_function_casts,
    crossref_with_asm,
    detect_signedness_mismatches,
    find_call_sites,
)
from ..mwcc_debug.patterns import (
    PATTERNS,
    list_patterns,
)
from ..mwcc_debug.source_patch import (
    explain_decl_reorder_skip,
    extract_function,
    find_function as find_source_function,
    find_function_definitions,
    get_decl_names_by_scope,
    reorder_decls_in_function_scope,
    transfer_candidate,
)
from ..mwcc_debug.asm_parser import (
    AsmInstruction,
    extract_function as asm_extract_function,
    find_first_def as asm_find_first_def,
    parse_prologue_end as asm_parse_prologue_end,
)
from ..mwcc_debug.iter_match import (
    MatchResult,
    instr_signature,
    match_virtual_for_expected_def,
)
from ..mwcc_debug.diff_capture import (
    CompileFailure,
    _kill_process_tree,
    _run_with_process_group_timeout,
    read_inspect_input_if_available,
    read_or_compile_input,
    resolve_diff_input,
)
from ..mwcc_debug.diff_report import (
    compare_function_dumps,
    render_text_report,
)
from ..mwcc_debug.frame_reservations import (
    analyze_frame_from_asm_text,
    analyze_frame_from_function,
    analyze_frame_reservations,
    evaluate_frame_transform_probe_results,
    evaluate_stack_home_probe_results,
)
from ..mwcc_debug.value_numbering import detect_divide_rematerialization_ceiling


@dataclasses.dataclass(frozen=True)
class _MatchIterFirstReg:
    kind: str
    number: int

    @property
    def name(self) -> str:
        return f"{self.kind}{self.number}"


_MATCH_ITER_RANGE_RE = re.compile(r"^([rf])(\d+)(?:-|\.\.)([rf])?(\d+)$")
_MATCH_ITER_ALIASES: dict[str, tuple[_MatchIterFirstReg, ...]] = {
    "gpr-callee": tuple(_MatchIterFirstReg("r", n) for n in range(31, 24, -1)),
    "callee-gpr": tuple(_MatchIterFirstReg("r", n) for n in range(31, 24, -1)),
    "gpr-volatile": tuple(_MatchIterFirstReg("r", n) for n in range(3, 13)),
    "volatile-gpr": tuple(_MatchIterFirstReg("r", n) for n in range(3, 13)),
    "fpr-callee": tuple(_MatchIterFirstReg("f", n) for n in range(31, 23, -1)),
    "callee-fpr": tuple(_MatchIterFirstReg("f", n) for n in range(31, 23, -1)),
    "fpr-volatile": tuple(_MatchIterFirstReg("f", n) for n in range(0, 14)),
    "volatile-fpr": tuple(_MatchIterFirstReg("f", n) for n in range(0, 14)),
}


def _parse_match_iter_first_regs(regs: str) -> list[_MatchIterFirstReg]:
    parsed: list[_MatchIterFirstReg] = []
    for token in regs.split(","):
        token = token.strip()
        if not token:
            continue
        alias = _MATCH_ITER_ALIASES.get(token.lower())
        if alias is not None:
            parsed.extend(alias)
            continue
        range_match = _MATCH_ITER_RANGE_RE.match(token.lower())
        if range_match:
            kind = range_match.group(1)
            end_kind = range_match.group(3)
            if end_kind is not None and end_kind != kind:
                raise ValueError(f"invalid mixed-kind reg range: {token}")
            start = int(range_match.group(2))
            end = int(range_match.group(4))
            step = -1 if start > end else 1
            parsed.extend(
                _MatchIterFirstReg(kind=kind, number=n)
                for n in range(start, end + step, step)
            )
            continue
        if len(token) < 2 or token[0] not in {"r", "f"}:
            raise ValueError(f"invalid reg token: {token}")
        try:
            number = int(token[1:])
        except ValueError as exc:
            raise ValueError(f"invalid reg token: {token}") from exc
        parsed.append(_MatchIterFirstReg(kind=token[0], number=number))
    return parsed


def _match_iter_first_class_id(kind: str) -> int | None:
    if kind == "r":
        return 0
    if kind == "f":
        return 1
    return None


def _build_match_iter_first_target_vector(
    results: list[dict],
    events: FunctionEvents | None,
) -> dict:
    """Build the full vector that should be tested as one iter-first probe."""
    current_by_class_ig: dict[tuple[int, int], int] = {}
    if events is not None:
        for section in events.colorgraph_sections:
            for decision in section.decisions:
                current_by_class_ig[
                    (section.class_id, decision.ig_idx)
                ] = decision.assigned_reg

    targets: list[dict] = []
    for result in results:
        if result.get("status") != "ok":
            continue
        kind = str(result.get("kind", "r"))
        reg = int(result["reg"])
        ig_idx = int(result["ig_idx"])
        class_id = _match_iter_first_class_id(kind)
        current_reg = (
            current_by_class_ig.get((class_id, ig_idx))
            if class_id is not None else None
        )
        force_phys_unscoped = f"{ig_idx}:{reg}"
        if class_id is not None:
            force_phys_entry = f"{class_id}:{ig_idx}:{reg}"
            force_vector_entry = f"class{class_id}:ig{ig_idx}:phys={kind}{reg}"
        else:
            force_phys_entry = force_phys_unscoped
            force_vector_entry = f"ig{ig_idx}:phys={kind}{reg}"
        targets.append({
            "target_reg": reg,
            "target_reg_name": str(result.get("reg_name") or f"{kind}{reg}"),
            "kind": kind,
            "class_id": class_id,
            "ig_idx": ig_idx,
            "current_reg": current_reg,
            "current_reg_name": (
                f"{kind}{current_reg}"
                if isinstance(current_reg, int) and current_reg >= 0 else None
            ),
            "already_target": (
                current_reg == reg if isinstance(current_reg, int) else None
            ),
            "force_phys_entry": force_phys_entry,
            "force_vector_entry": force_vector_entry,
        })

    phys_by_key: dict[tuple[int | None, int], list[dict]] = {}
    for target in targets:
        key = (target.get("class_id"), int(target["ig_idx"]))
        bucket = phys_by_key.setdefault(key, [])
        if not any(item["target_reg"] == target["target_reg"] for item in bucket):
            bucket.append(target)

    conflict_by_key: dict[tuple[int | None, int], dict] = {}
    for key, bucket in phys_by_key.items():
        if len(bucket) <= 1:
            continue
        class_id, ig_idx = key
        conflict_by_key[key] = {
            "class_id": class_id,
            "ig_idx": ig_idx,
            "target_regs": [int(item["target_reg"]) for item in bucket],
            "target_reg_names": [
                str(item.get("target_reg_name") or item["target_reg"])
                for item in bucket
            ],
        }

    force_iter_first: list[int] = []
    seen_iter_first: set[int] = set()
    force_phys: dict[str, int] = {}
    force_phys_csv_parts: list[str] = []
    force_phys_unscoped_csv_parts: list[str] = []
    force_vector_parts: list[str] = []
    seen_force_keys: set[tuple[int | None, int]] = set()
    for target in targets:
        ig_idx = int(target["ig_idx"])
        if ig_idx not in seen_iter_first:
            force_iter_first.append(ig_idx)
            seen_iter_first.add(ig_idx)
        key = (target.get("class_id"), ig_idx)
        conflict = conflict_by_key.get(key)
        runnable = conflict is None
        target["force_vector_runnable"] = runnable
        if conflict is not None:
            target["force_vector_conflict"] = conflict
            continue
        if key in seen_force_keys:
            continue
        seen_force_keys.add(key)
        force_phys[str(ig_idx)] = int(target["target_reg"])
        force_phys_csv_parts.append(str(target["force_phys_entry"]))
        force_phys_unscoped_csv_parts.append(f"{ig_idx}:{target['target_reg']}")
        force_vector_parts.append(str(target["force_vector_entry"]))

    conflicts = list(conflict_by_key.values())
    return {
        "force_iter_first": force_iter_first,
        "force_iter_first_csv": ",".join(str(i) for i in force_iter_first),
        "force_phys": force_phys,
        "force_phys_unscoped_csv": ",".join(force_phys_unscoped_csv_parts),
        "force_phys_csv": ",".join(force_phys_csv_parts),
        "force_vector": ",".join(force_vector_parts),
        "force_vector_runnable": not conflicts,
        "conflicts": conflicts,
        "targets": targets,
    }


_CHECKDIFF_ASM_REG_RE = re.compile(r"\b([rf])(\d+)\b")
_CHECKDIFF_STWU_FRAME_RE = re.compile(r"\bstwu\s+r1,\s*(-?\d+)\(r1\)")
_CHECKDIFF_STACK_SLOT_RE = re.compile(
    r"(?P<offset>-?(?:0x[0-9a-fA-F]+|\d+))(?P<suffix>\s*\(\s*r1\s*\))"
)


def _checkdiff_asm_body(line: str) -> str:
    if line.startswith("<"):
        return line
    if ":" in line:
        line = line.split(":", 1)[1]
    line = line.strip()
    line = re.sub(r"^(?:[0-9a-fA-F]{2}\s+){4}", "", line)
    line = re.sub(r"^[0-9a-fA-F]{8}\s+", "", line)
    return line.strip()


def _parse_checkdiff_asm_instruction(line: str) -> AsmInstruction | None:
    body = _checkdiff_asm_body(line)
    if not body or body.startswith("<") or body.startswith("."):
        return None
    parts = body.split(None, 1)
    if not parts:
        return None
    opcode = parts[0].rstrip(".")
    operands = parts[1] if len(parts) > 1 else ""
    regs = [
        (kind, int(number))
        for kind, number in _CHECKDIFF_ASM_REG_RE.findall(operands)
    ]
    return AsmInstruction(opcode=opcode, operands=operands, regs=regs)


def _checkdiff_frame_size(lines: list[str]) -> int | None:
    for line in lines:
        body = _checkdiff_asm_body(line)
        match = _CHECKDIFF_STWU_FRAME_RE.search(body)
        if match is None:
            continue
        offset = int(match.group(1), 10)
        if offset < 0:
            return -offset
    return None


def _adjust_checkdiff_stack_slots(operands: str, delta: int) -> str:
    if delta == 0:
        return operands

    def repl(match: re.Match[str]) -> str:
        raw_offset = match.group("offset")
        base = 16 if raw_offset.lower().startswith("0x") else 10
        value = int(raw_offset, base) + delta
        rendered = hex(value) if base == 16 else str(value)
        return f"{rendered}{match.group('suffix')}"

    return _CHECKDIFF_STACK_SLOT_RE.sub(repl, operands)


def _checkdiff_instruction_signature(
    instruction: AsmInstruction,
    *,
    stack_delta: int = 0,
) -> tuple[str, str]:
    operands = _adjust_checkdiff_stack_slots(instruction.operands, stack_delta)
    return instr_signature(instruction.opcode, operands)


def _asm_instruction_destination(
    instruction: AsmInstruction | None,
) -> tuple[str, int] | None:
    if instruction is None or not instruction.regs:
        return None
    opcode = instruction.opcode
    if (
        opcode.startswith("st")
        or opcode.startswith("psq_st")
        or opcode.startswith("b")
        or opcode.startswith("cmp")
    ):
        return None
    kind, number = instruction.regs[0]
    if number > 31:
        return None
    return kind, number


def _current_colorgraph_reg(
    events: FunctionEvents | None,
    *,
    class_id: int,
    ig_idx: int,
) -> int | None:
    if events is None:
        return None
    for section in events.colorgraph_sections:
        if section.class_id != class_id:
            continue
        for decision in section.decisions:
            if decision.ig_idx == ig_idx:
                return decision.assigned_reg
    return None


def _prepass_destination_virtual(instruction, reg_kind: str) -> int | None:
    if not instruction.regs:
        return None
    kind, number = instruction.regs[0]
    if kind != reg_kind or number < 32:
        return None
    return number


def _match_virtual_for_register_diff(
    *,
    expected_ist: AsmInstruction,
    expected_position: int,
    pre_pass,
    reg_kind: str,
    current_phys: int,
    events: FunctionEvents | None,
) -> MatchResult | None:
    target_sig = instr_signature(expected_ist.opcode, expected_ist.operands)
    candidates: list[tuple[int, Any, int, int | None]] = []
    linear_index = 0
    for block in pre_pass.blocks:
        for instruction in block.instructions:
            if instr_signature(instruction.opcode, instruction.operands) != target_sig:
                linear_index += 1
                continue
            virtual = _prepass_destination_virtual(instruction, reg_kind)
            if virtual is None:
                linear_index += 1
                continue
            class_id = _match_iter_first_class_id(reg_kind)
            assigned = (
                None if class_id is None else _current_colorgraph_reg(
                    events,
                    class_id=class_id,
                    ig_idx=virtual,
                )
            )
            candidates.append((linear_index, instruction, virtual, assigned))
            linear_index += 1
    if not candidates:
        return None

    current_matches = [
        candidate for candidate in candidates
        if candidate[3] == current_phys
    ]
    ranked = current_matches or candidates
    ranked.sort(key=lambda item: abs(item[0] - expected_position))
    best_i, _best_instruction, virtual, _assigned = ranked[0]
    if len(candidates) == 1:
        confidence = "exact"
    elif len(current_matches) == 1:
        confidence = "current-reg"
    else:
        confidence = "ambiguous"
    return MatchResult(
        virtual=virtual,
        ig_idx=virtual,
        instruction_index=best_i,
        confidence=confidence,
    )


def _derive_force_phys_from_register_diff_lines(
    target_asm: list[str],
    current_asm: list[str],
    pre_pass,
    events: FunctionEvents | None,
) -> dict:
    target_instructions: list[AsmInstruction] = []
    target_by_line: dict[int, tuple[int, AsmInstruction]] = {}
    target_entries: list[tuple[int, int, AsmInstruction, str]] = []
    for line_index, line in enumerate(target_asm):
        instruction = _parse_checkdiff_asm_instruction(line)
        if instruction is None:
            continue
        target_by_line[line_index] = (len(target_instructions), instruction)
        target_entries.append((
            line_index,
            len(target_instructions),
            instruction,
            line,
        ))
        target_instructions.append(instruction)

    current_entries: list[tuple[int, int, AsmInstruction, str]] = []
    for line_index, line in enumerate(current_asm):
        instruction = _parse_checkdiff_asm_instruction(line)
        if instruction is None:
            continue
        current_entries.append((
            line_index,
            len(current_entries),
            instruction,
            line,
        ))

    prologue_end = asm_parse_prologue_end(target_instructions)
    target_frame_size = _checkdiff_frame_size(target_asm)
    current_frame_size = _checkdiff_frame_size(current_asm)
    frame_delta = (
        target_frame_size - current_frame_size
        if target_frame_size is not None and current_frame_size is not None
        else None
    )
    current_stack_delta = frame_delta or 0
    use_frame_alignment = current_stack_delta != 0
    paired_lines: list[
        tuple[int, str, str, AsmInstruction, AsmInstruction, int]
    ] = []

    if use_frame_alignment:
        unused_current = list(current_entries)
        for (
            target_line_index,
            target_instruction_index,
            target_instruction,
            target_line,
        ) in target_entries:
            target_sig = _checkdiff_instruction_signature(target_instruction)
            ranked: list[
                tuple[int, int, str, AsmInstruction, int]
            ] = []
            for current_pos, (
                current_line_index,
                current_instruction_index,
                current_instruction,
                current_line,
            ) in enumerate(unused_current):
                current_sig = _checkdiff_instruction_signature(
                    current_instruction,
                    stack_delta=current_stack_delta,
                )
                if current_sig != target_sig:
                    continue
                ranked.append((
                    abs(current_instruction_index - target_instruction_index),
                    current_pos,
                    current_line,
                    current_instruction,
                    current_instruction_index,
                ))
            if not ranked:
                continue
            (
                _distance,
                current_pos,
                current_line,
                current_instruction,
                _current_instruction_index,
            ) = sorted(ranked, key=lambda item: (item[0], item[1]))[0]
            unused_current.pop(current_pos)
            paired_lines.append((
                target_line_index,
                target_line,
                current_line,
                target_instruction,
                current_instruction,
                target_instruction_index,
            ))
    else:
        for line_index, (target_line, current_line) in enumerate(
            zip(target_asm, current_asm)
        ):
            target_instruction = _parse_checkdiff_asm_instruction(target_line)
            current_instruction = _parse_checkdiff_asm_instruction(current_line)
            if target_instruction is None or current_instruction is None:
                continue
            target_position = target_by_line.get(line_index)
            if target_position is None:
                continue
            instruction_index, _ = target_position
            paired_lines.append((
                line_index,
                target_line,
                current_line,
                target_instruction,
                current_instruction,
                instruction_index,
            ))

    target_order: list[tuple[int, str, int, int]] = []
    target_data: dict[tuple[int, str, int, int], dict] = {}
    conflicts: list[dict] = []

    for (
        line_index,
        target_line,
        current_line,
        target_instruction,
        current_instruction,
        instruction_index,
    ) in paired_lines:
        if target_line == current_line:
            continue
        if _checkdiff_instruction_signature(
            target_instruction,
        ) != _checkdiff_instruction_signature(
            current_instruction,
            stack_delta=current_stack_delta,
        ):
            continue
        target_dest = _asm_instruction_destination(target_instruction)
        current_dest = _asm_instruction_destination(current_instruction)
        if target_dest is None or target_dest == current_dest:
            continue
        kind, phys = target_dest
        class_id = _match_iter_first_class_id(kind)
        if class_id is None:
            continue
        if instruction_index < prologue_end:
            continue
        current_kind, current_phys = current_dest
        if current_kind != kind:
            continue
        match = _match_virtual_for_register_diff(
            expected_ist=target_instruction,
            expected_position=instruction_index - prologue_end,
            pre_pass=pre_pass,
            reg_kind=kind,
            current_phys=current_phys,
            events=events,
        )
        if match is None:
            continue

        conflict_key = (class_id, kind, match.ig_idx)
        existing_for_ig = [
            key for key in target_order
            if key[:3] == conflict_key and key[3] != phys
        ]
        if existing_for_ig:
            conflicts.append({
                "class_id": class_id,
                "kind": kind,
                "ig_idx": match.ig_idx,
                "existing_phys": existing_for_ig[0][3],
                "conflicting_phys": phys,
                "line_index": line_index,
                "target_asm": target_line,
                "current_asm": current_line,
            })
            continue

        key = (class_id, kind, match.ig_idx, phys)
        if key not in target_data:
            current_reg = _current_colorgraph_reg(
                events,
                class_id=class_id,
                ig_idx=match.ig_idx,
            )
            force_phys_entry = f"{class_id}:{match.ig_idx}:{phys}"
            force_vector_entry = (
                f"class{class_id}:ig{match.ig_idx}:phys={kind}{phys}"
            )
            target_data[key] = {
                "class_id": class_id,
                "kind": kind,
                "ig_idx": match.ig_idx,
                "target_reg": phys,
                "target_reg_name": f"{kind}{phys}",
                "current_reg": current_reg,
                "current_reg_name": (
                    f"{kind}{current_reg}"
                    if isinstance(current_reg, int) else None
                ),
                "already_target": (
                    current_reg == phys if isinstance(current_reg, int) else None
                ),
                "force_phys_entry": force_phys_entry,
                "force_vector_entry": force_vector_entry,
                "occurrences": [],
            }
            target_order.append(key)
        target_data[key]["occurrences"].append({
            "line_index": line_index,
            "target_asm": target_line,
            "current_asm": current_line,
            "opcode": target_instruction.opcode,
            "operands": target_instruction.operands,
            "instruction_index": match.instruction_index,
            "confidence": match.confidence,
        })

    targets: list[dict] = []
    for key in target_order:
        target = dict(target_data[key])
        occurrences = target["occurrences"]
        target["occurrence_count"] = len(occurrences)
        occurrence_confidences = {
            item["confidence"] for item in occurrences
        }
        if "ambiguous" in occurrence_confidences:
            target["confidence"] = "ambiguous"
        elif "current-reg" in occurrence_confidences:
            target["confidence"] = "current-reg"
        else:
            target["confidence"] = "exact"
        targets.append(target)

    conflict_keys = {
        (
            int(conflict["class_id"]),
            str(conflict["kind"]),
            int(conflict["ig_idx"]),
        )
        for conflict in conflicts
    }
    for target in targets:
        conflict_key = (
            int(target["class_id"]),
            str(target["kind"]),
            int(target["ig_idx"]),
        )
        target["force_vector_runnable"] = conflict_key not in conflict_keys

    runnable_targets = [
        target for target in targets if target["force_vector_runnable"]
    ]

    return {
        "force_phys": {
            str(target["ig_idx"]): target["target_reg"]
            for target in runnable_targets
        },
        "force_phys_csv": ",".join(
            target["force_phys_entry"] for target in runnable_targets
        ),
        "force_vector": ",".join(
            target["force_vector_entry"] for target in runnable_targets
        ),
        "targets": targets,
        "conflicts": conflicts,
        "register_only_target_count": sum(
            target["occurrence_count"] for target in targets
        ),
        "frame_alignment": {
            "target_frame_size": target_frame_size,
            "current_frame_size": current_frame_size,
            "frame_delta": frame_delta,
            "applied": use_frame_alignment,
        },
    }


def _read_force_phys_checkdiff_payload(
    *,
    function: str,
    melee_root: Path,
    checkdiff_json: Path | None,
    checkdiff_timeout: float,
) -> tuple[dict, str]:
    if checkdiff_json is not None:
        try:
            return json.loads(checkdiff_json.read_text()), str(checkdiff_json)
        except json.JSONDecodeError as exc:
            typer.echo(
                f"checkdiff JSON could not be parsed: {exc}",
                err=True,
            )
            raise typer.Exit(2) from exc
        except OSError as exc:
            typer.echo(f"checkdiff JSON could not be read: {exc}", err=True)
            raise typer.Exit(2) from exc

    cmd = [
        "python",
        "tools/checkdiff.py",
        function,
        "--format",
        "json",
        "--no-build",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=checkdiff_timeout,
            env=_checkdiff_env_without_fingerprint(),
        )
    except subprocess.TimeoutExpired as exc:
        typer.echo(
            f"checkdiff timed out after {checkdiff_timeout:g}s",
            err=True,
        )
        raise typer.Exit(3) from exc
    except OSError as exc:
        typer.echo(f"failed to run checkdiff: {exc}", err=True)
        raise typer.Exit(3) from exc

    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        if proc.stderr:
            typer.echo(proc.stderr.rstrip(), err=True)
        if proc.stdout:
            typer.echo(proc.stdout.rstrip(), err=True)
        raise typer.Exit(proc.returncode or 3)
    try:
        return json.loads(proc.stdout), "checkdiff"
    except json.JSONDecodeError as exc:
        if proc.stderr:
            typer.echo(proc.stderr.rstrip(), err=True)
        typer.echo(f"checkdiff did not emit JSON: {exc}", err=True)
        raise typer.Exit(3) from exc


def _checkdiff_asm_lines(payload: dict, key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(
        isinstance(line, str) for line in value
    ):
        typer.echo(f"checkdiff JSON did not include {key} lines", err=True)
        raise typer.Exit(2)
    return value


def _force_phys_target_spec(function: str, vector: dict) -> dict:
    return {
        "function": function,
        "virtuals": vector.get("force_phys", {}),
    }


@dataclasses.dataclass(frozen=True)
class _ForceVectorEntry:
    raw: str
    kind: str
    ig_idx: int | None = None
    phys: int | None = None
    root: int | None = None
    class_id: int | None = None
    iter_idx: int | None = None

    def to_payload(self) -> dict:
        payload: dict = {"raw": self.raw, "kind": self.kind}
        for key in ("ig_idx", "phys", "root", "class_id", "iter_idx"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        return payload


_FORCE_VECTOR_CLASS_NAMES = {
    "gpr": 0,
    "int": 0,
    "r": 0,
    "class0": 0,
    "fp": 1,
    "fpr": 1,
    "f": 1,
    "class1": 1,
}


def _parse_force_vector_int(raw: str, *, prefix: str = "") -> int:
    value = raw.strip().lower()
    if prefix and value.startswith(prefix):
        value = value[len(prefix):]
    if not value:
        raise ValueError(f"expected integer in {raw!r}")
    return int(value, 0)


def _parse_force_vector_phys(raw: str) -> int:
    value = raw.strip().lower()
    if value.startswith(("r", "f")):
        value = value[1:]
    if not value:
        raise ValueError(f"expected physical register in {raw!r}")
    return int(value, 0)


_FORCE_SELECT_ACTIONS = {
    "select-first",
    "select_first",
    "select-order",
    "select_order",
    "select",
}


def _parse_force_vector(raw: str) -> list[_ForceVectorEntry]:
    """Parse composed force specs for one diagnostic auto-verify run.

    Supported entries:
      - ``ig40:phys=r30`` or ``40:phys=30`` -> ``--force-phys 40:30``
      - ``class0:ig40:phys=r29`` -> ``--force-phys 0:40:29``
      - ``class0:iter5:phys=r31`` -> ``--force-phys-iter 0:5:31``
      - ``ig42:coalesce=38`` / ``ig42:root=38`` / ``42=38`` -> coalesce
      - ``ig50:iter-first`` -> ``--force-iter-first 50``
      - ``class1:ig50:iter-first`` -> scoped ``--force-iter-first 50``
      - ``class1:iter4:iter-first`` -> ``--force-iter-first-iter 1:4``
      - ``class0:ig40:select-first`` -> ``--force-select-order 40``
    """
    if any(c in raw for c in '"\';\r\n&|<>'):
        raise ValueError(
            "--force-vector must not contain quotes, semicolons, newlines, "
            "or shell metacharacters"
        )

    entries: list[_ForceVectorEntry] = []
    for item in raw.split(","):
        spec = item.strip()
        if not spec:
            continue
        lower = spec.lower()
        try:
            parts = spec.split(":")
            if len(parts) == 2 and parts[1].lower() in {
                "iter-first", "iter_first", "first",
            }:
                entries.append(_ForceVectorEntry(
                    raw=spec,
                    kind="force_iter_first",
                    ig_idx=_parse_force_vector_int(parts[0], prefix="ig"),
                ))
                continue

            if len(parts) == 2 and parts[1].lower() in _FORCE_SELECT_ACTIONS:
                entries.append(_ForceVectorEntry(
                    raw=spec,
                    kind="force_select_order",
                    ig_idx=_parse_force_vector_int(parts[0], prefix="ig"),
                ))
                continue

            if len(parts) == 2 and parts[1].lower().startswith("phys="):
                entries.append(_ForceVectorEntry(
                    raw=spec,
                    kind="force_phys",
                    ig_idx=_parse_force_vector_int(parts[0], prefix="ig"),
                    phys=_parse_force_vector_phys(parts[1].split("=", 1)[1]),
                ))
                continue

            if len(parts) == 2 and (
                parts[1].lower().startswith("coalesce=")
                or parts[1].lower().startswith("root=")
            ):
                entries.append(_ForceVectorEntry(
                    raw=spec,
                    kind="force_coalesce",
                    ig_idx=_parse_force_vector_int(parts[0], prefix="ig"),
                    root=_parse_force_vector_int(parts[1].split("=", 1)[1], prefix="ig"),
                ))
                continue

            if len(parts) == 3 and parts[2].lower().startswith("phys="):
                class_name = parts[0].lower()
                if class_name not in _FORCE_VECTOR_CLASS_NAMES:
                    raise ValueError(f"unknown force-vector class {parts[0]!r}")
                class_id = _FORCE_VECTOR_CLASS_NAMES[class_name]
                middle = parts[1].lower()
                if middle.startswith("iter"):
                    entries.append(_ForceVectorEntry(
                        raw=spec,
                        kind="force_phys_iter",
                        class_id=class_id,
                        iter_idx=_parse_force_vector_int(parts[1], prefix="iter"),
                        phys=_parse_force_vector_phys(parts[2].split("=", 1)[1]),
                    ))
                else:
                    entries.append(_ForceVectorEntry(
                        raw=spec,
                        kind="force_phys",
                        class_id=class_id,
                        ig_idx=_parse_force_vector_int(parts[1], prefix="ig"),
                        phys=_parse_force_vector_phys(parts[2].split("=", 1)[1]),
                    ))
                continue

            if len(parts) == 3 and parts[2].lower() in {
                "iter-first", "iter_first", "first",
            }:
                class_name = parts[0].lower()
                if class_name not in _FORCE_VECTOR_CLASS_NAMES:
                    raise ValueError(f"unknown force-vector class {parts[0]!r}")
                class_id = _FORCE_VECTOR_CLASS_NAMES[class_name]
                middle = parts[1].lower()
                if middle.startswith("iter"):
                    entries.append(_ForceVectorEntry(
                        raw=spec,
                        kind="force_iter_first_iter",
                        class_id=class_id,
                        iter_idx=_parse_force_vector_int(parts[1], prefix="iter"),
                    ))
                else:
                    entries.append(_ForceVectorEntry(
                        raw=spec,
                        kind="force_iter_first",
                        class_id=class_id,
                        ig_idx=_parse_force_vector_int(parts[1], prefix="ig"),
                    ))
                continue

            if len(parts) == 3 and parts[2].lower() in _FORCE_SELECT_ACTIONS:
                class_name = parts[0].lower()
                if class_name not in _FORCE_VECTOR_CLASS_NAMES:
                    raise ValueError(f"unknown force-vector class {parts[0]!r}")
                class_id = _FORCE_VECTOR_CLASS_NAMES[class_name]
                middle = parts[1].lower()
                if middle.startswith("iter"):
                    raise ValueError(
                        "select-order entries must target an ig_idx, not an iter"
                    )
                entries.append(_ForceVectorEntry(
                    raw=spec,
                    kind="force_select_order",
                    class_id=class_id,
                    ig_idx=_parse_force_vector_int(parts[1], prefix="ig"),
                ))
                continue

            if "=" in lower and ":" not in lower:
                lhs, rhs = spec.split("=", 1)
                entries.append(_ForceVectorEntry(
                    raw=spec,
                    kind="force_coalesce",
                    ig_idx=_parse_force_vector_int(lhs, prefix="ig"),
                    root=_parse_force_vector_int(rhs, prefix="ig"),
                ))
                continue
        except ValueError as exc:
            raise ValueError(f"invalid --force-vector entry {spec!r}: {exc}") from exc

        raise ValueError(
            f"invalid --force-vector entry {spec!r}; expected forms like "
            "ig40:phys=r30, ig42:coalesce=38, "
            "class0:ig40:phys=r29, class0:iter5:phys=r31, "
            "class1:ig50:iter-first, "
            "class1:iter4:iter-first, class0:ig40:select-first, "
            "or ig50:iter-first"
        )

    if not entries:
        raise ValueError("--force-vector did not contain any entries")
    return entries


def _force_vector_dump_args(
    entries: list[_ForceVectorEntry],
    *,
    function: str,
) -> tuple[list[str], dict]:
    force_phys = [
        (
            f"{entry.class_id}:{entry.ig_idx}:{entry.phys}"
            if entry.class_id is not None
            else f"{entry.ig_idx}:{entry.phys}"
        )
        for entry in entries
        if entry.kind == "force_phys"
        and entry.ig_idx is not None
        and entry.phys is not None
    ]
    force_phys_iter = [
        f"{entry.class_id}:{entry.iter_idx}:{entry.phys}"
        for entry in entries
        if entry.kind == "force_phys_iter"
        and entry.class_id is not None
        and entry.iter_idx is not None
        and entry.phys is not None
    ]
    force_coalesce = [
        f"{entry.ig_idx}={entry.root}"
        for entry in entries
        if entry.kind == "force_coalesce"
        and entry.ig_idx is not None
        and entry.root is not None
    ]
    force_iter_first_unscoped = [
        str(entry.ig_idx)
        for entry in entries
        if entry.kind == "force_iter_first"
        and entry.class_id is None
        and entry.ig_idx is not None
    ]
    force_iter_first_scoped = [
        entry
        for entry in entries
        if entry.kind == "force_iter_first"
        and entry.class_id is not None
        and entry.ig_idx is not None
    ]
    force_iter_first_iter = [
        f"{entry.class_id}:{entry.iter_idx}"
        for entry in entries
        if entry.kind == "force_iter_first_iter"
        and entry.class_id is not None
        and entry.iter_idx is not None
    ]
    force_select_order_unscoped = [
        str(entry.ig_idx)
        for entry in entries
        if entry.kind == "force_select_order"
        and entry.class_id is None
        and entry.ig_idx is not None
    ]
    force_select_order_scoped = [
        entry
        for entry in entries
        if entry.kind == "force_select_order"
        and entry.class_id is not None
        and entry.ig_idx is not None
    ]
    if force_iter_first_unscoped and force_iter_first_scoped:
        raise ValueError(
            "--force-vector cannot mix unscoped and class-scoped iter-first "
            "entries in one probe"
        )
    iter_first_classes = {
        entry.class_id for entry in force_iter_first_scoped
        if entry.class_id is not None
    }
    if len(iter_first_classes) > 1:
        raise ValueError(
            "--force-vector class-scoped iter-first entries must use one "
            "class per probe"
        )
    force_iter_first = force_iter_first_unscoped or [
        str(entry.ig_idx) for entry in force_iter_first_scoped
        if entry.ig_idx is not None
    ]
    force_iter_first_class = (
        str(next(iter(iter_first_classes))) if iter_first_classes else ""
    )
    if (force_iter_first_unscoped or force_iter_first_scoped
            or force_iter_first_iter) and (
                force_select_order_unscoped or force_select_order_scoped):
        raise ValueError(
            "--force-vector cannot mix iter-first and select-order entries "
            "in one probe"
        )
    if force_select_order_unscoped and force_select_order_scoped:
        raise ValueError(
            "--force-vector cannot mix unscoped and class-scoped select-order "
            "entries in one probe"
        )
    select_order_classes = {
        entry.class_id for entry in force_select_order_scoped
        if entry.class_id is not None
    }
    if len(select_order_classes) > 1:
        raise ValueError(
            "--force-vector class-scoped select-order entries must use one "
            "class per probe"
        )
    force_select_order = force_select_order_unscoped or [
        str(entry.ig_idx) for entry in force_select_order_scoped
        if entry.ig_idx is not None
    ]
    force_select_order_class = (
        str(next(iter(select_order_classes))) if select_order_classes else ""
    )

    args: list[str] = []
    summary = {
        "force_phys_csv": ",".join(force_phys),
        "force_phys_iter_csv": ",".join(force_phys_iter),
        "force_coalesce_csv": ",".join(force_coalesce),
        "force_iter_first_csv": ",".join(force_iter_first),
        "force_iter_first_class": force_iter_first_class,
        "force_iter_first_iter_csv": ",".join(force_iter_first_iter),
        "force_select_order_csv": ",".join(force_select_order),
        "force_select_order_class": force_select_order_class,
    }
    if force_phys or force_phys_iter:
        needs_force_phys_scope = True
    else:
        needs_force_phys_scope = False

    if force_phys:
        args.extend(["--force-phys", summary["force_phys_csv"]])
    if force_phys_iter:
        args.extend(["--force-phys-iter", summary["force_phys_iter_csv"]])
    if needs_force_phys_scope:
        args.extend(["--force-phys-fn", function])
    if force_coalesce:
        args.extend(["--force-coalesce", summary["force_coalesce_csv"]])
        args.extend(["--force-coalesce-fn", function])
    if force_iter_first:
        args.extend(["--force-iter-first", summary["force_iter_first_csv"]])
        if force_iter_first_class:
            args.extend(["--force-iter-first-class", force_iter_first_class])
    if force_iter_first_iter:
        args.extend([
            "--force-iter-first-iter",
            summary["force_iter_first_iter_csv"],
        ])
    if force_iter_first or force_iter_first_iter:
        args.extend(["--force-iter-first-fn", function])
    if force_select_order:
        args.extend(["--force-select-order", summary["force_select_order_csv"]])
        if force_select_order_class:
            args.extend(["--force-select-order-class", force_select_order_class])
        args.extend(["--force-select-order-fn", function])
    return args, summary


def _build_force_vector_auto_verify_cmd(
    *,
    src_path: Path,
    function: str,
    entries: list[_ForceVectorEntry],
    output_path: Optional[Path] = None,
    checkdiff_timeout: float = 60.0,
) -> list[str]:
    if output_path is None:
        output_path = (
            src_path.parent
            / f".{function}.force-vector.{os.getpid()}.{int(time.time() * 1000)}.pcdump.txt"
        )
    force_args, _summary = _force_vector_dump_args(entries, function=function)
    return [
        sys.executable, "-m", "src.cli", "debug", "dump", "local", str(src_path),
        *force_args,
        "--function", function,
        "--diff",
        "--checkdiff-timeout", f"{checkdiff_timeout:g}",
        "-o", str(output_path),
    ]


def _force_vector_probe_groups(
    entries: list[_ForceVectorEntry],
    *,
    include_diagnostic_probes: bool,
) -> list[tuple[str, list[_ForceVectorEntry], int | None]]:
    groups: list[tuple[str, list[_ForceVectorEntry], int | None]] = [
        ("union", entries, None)
    ]
    if not include_diagnostic_probes:
        return groups
    for index, entry in enumerate(entries, start=1):
        groups.append((f"single[{index}]", [entry], index))
    for end in range(2, len(entries)):
        groups.append((f"prefix[1..{end}]", entries[:end], end))
    return groups


def _force_vector_probe_payload(
    *,
    label: str,
    entries: list[_ForceVectorEntry],
    proc: subprocess.CompletedProcess[str],
    output_path: Path,
    ordinal: int | None,
) -> dict:
    _args, summary = _force_vector_dump_args(entries, function="<fn>")
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    match = "[diff] MATCH" in stdout
    return {
        "label": label,
        "ordinal": ordinal,
        "entries": [entry.to_payload() for entry in entries],
        "force_phys_csv": summary["force_phys_csv"],
        "force_phys_iter_csv": summary["force_phys_iter_csv"],
        "force_coalesce_csv": summary["force_coalesce_csv"],
        "force_iter_first_csv": summary["force_iter_first_csv"],
        "force_iter_first_class": summary["force_iter_first_class"],
        "force_iter_first_iter_csv": summary["force_iter_first_iter_csv"],
        "force_select_order_csv": summary["force_select_order_csv"],
        "force_select_order_class": summary["force_select_order_class"],
        "returncode": proc.returncode,
        "match": match,
        "status": (
            "match" if match else
            "no_match" if proc.returncode == 0 else
            "failed"
        ),
        "pcdump": str(output_path),
        "stdout_tail": "\n".join(stdout.splitlines()[-8:]),
        "stderr_tail": "\n".join(stderr.splitlines()[-8:]),
    }


def _run_force_vector_auto_verify(
    *,
    src_path: Path,
    function: str,
    entries: list[_ForceVectorEntry],
    melee_root: Path,
    checkdiff_timeout: float = 60.0,
    run_diagnostic_probes: bool = True,
) -> dict:
    groups = _force_vector_probe_groups(
        entries,
        include_diagnostic_probes=run_diagnostic_probes,
    )
    payload: dict = {
        "entries": [entry.to_payload() for entry in entries],
        "probe_count": len(groups),
        "probes": [],
    }
    for label, group_entries, ordinal in groups:
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip(".-")
        output_path = (
            src_path.parent
            / f".{function}.force-vector.{safe_label}.{os.getpid()}.{int(time.time() * 1000)}.pcdump.txt"
        )
        cmd = _build_force_vector_auto_verify_cmd(
            src_path=src_path,
            function=function,
            entries=group_entries,
            output_path=output_path,
            checkdiff_timeout=checkdiff_timeout,
        )
        proc = _run_auto_verify_command_with_status(
            cmd,
            cwd=melee_root / "tools" / "melee-agent",
            status_label=f"force-vector {label}",
        )
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass
        probe = _force_vector_probe_payload(
            label=label,
            entries=group_entries,
            proc=proc,
            output_path=output_path,
            ordinal=ordinal,
        )
        if label == "union":
            payload["union"] = probe
        else:
            payload["probes"].append(probe)
    return payload


def _checkdiff_env_without_fingerprint() -> dict[str, str]:
    env = os.environ.copy()
    env["CHECKDIFF_NO_FINGERPRINT"] = "1"
    return env


def _checkdiff_env_for_locked_child(*, disable_fingerprint: bool) -> dict[str, str]:
    env = (
        _checkdiff_env_without_fingerprint()
        if disable_fingerprint
        else os.environ.copy()
    )
    env["CHECKDIFF_NO_LOCK"] = "1"
    return env


@contextmanager
def _acquire_checkdiff_repo_lock(
    melee_root: Path,
    *,
    label: str = "checkdiff build/report",
):
    """Acquire the same repo-wide lock used by tools/checkdiff.py."""
    if os.environ.get("CHECKDIFF_NO_LOCK"):
        yield
        return

    try:
        import fcntl
    except ImportError:
        yield
        return

    lock_dir = Path(tempfile.gettempdir()) / "melee-checkdiff-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(str(melee_root.resolve()).encode()).hexdigest()[:12]
    lock_path = lock_dir / f"repo.{digest}.lock"
    lock_file = lock_path.open("w")
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"waiting for repo-wide {label} lock", file=sys.stderr)
            start = time.monotonic()
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            elapsed = time.monotonic() - start
            print(f"acquired {label} lock after {elapsed:.1f}s", file=sys.stderr)
        yield
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


@contextmanager
def _acquire_source_score_repo_lock(melee_root: Path):
    with _acquire_checkdiff_repo_lock(melee_root, label="source-scoring"):
        yield


def _format_source_diff(
    before: str,
    after: str,
    *,
    fromfile: str = "before",
    tofile: str = "after",
    context: int = 3,
) -> str:
    """Return a focused unified diff for source-preview commands."""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
            n=context,
        )
    )


debug_app = typer.Typer(
    help="MWCC debugging workflow for dumps, inspection, target scoring, "
         "source suggestions, focused mutations, and permuter triage."
)
dump_app = typer.Typer(
    help="Collect pcdumps and manage local mwcc_debug setup."
)
inspect_app = typer.Typer(
    help="Read, compare, and explain MWCC pcdumps."
)
target_app = typer.Typer(
    help="Define and score allocator targets."
)
suggest_app = typer.Typer(
    help="Suggest source-shape and mismatch fixes."
)
mutate_app = typer.Typer(
    help="Apply focused source mutations on specific variables or decls."
)
intervene_app = typer.Typer(
    help="Run backend-backed allocator interventions and report allocator deltas."
)
permute_app = typer.Typer(
    help="Run, verify, and triage decomp-permuter candidates."
)
remote_app = typer.Typer(
    help="Run decomp-permuter jobs on configured SSH remotes."
)
util_app = typer.Typer(
    help="Low-level helpers outside the main mwcc-debug loop."
)

debug_app.add_typer(dump_app, name="dump")
debug_app.add_typer(inspect_app, name="inspect")
debug_app.add_typer(target_app, name="target")
debug_app.add_typer(suggest_app, name="suggest")
debug_app.add_typer(mutate_app, name="mutate")
debug_app.add_typer(intervene_app, name="intervene")
debug_app.add_typer(permute_app, name="permute")
debug_app.add_typer(util_app, name="util")
permute_app.add_typer(remote_app, name="remote")

from src.search.cli import search_app as _search_app  # noqa: E402
debug_app.add_typer(_search_app, name="search")


def _resolve_src_relative(c_file: str) -> str:
    """Resolve a .c file path to one relative to the melee repo root.

    Accepts:
      - Absolute path: /Users/mike/code/melee/src/melee/lb/lbarq.c
      - Repo-relative: src/melee/lb/lbarq.c
      - CWD-relative when run from inside repo

    Returns the path with forward slashes (POSIX style — easier for remote PS).
    """
    p = Path(c_file).resolve()
    repo = DEFAULT_MELEE_ROOT.resolve()
    try:
        rel = p.relative_to(repo)
    except ValueError:
        raise typer.BadParameter(
            f"{c_file} is not inside the melee repo ({repo})"
        )
    if not p.exists():
        raise typer.BadParameter(f"file not found: {p}")
    if p.suffix != ".c":
        raise typer.BadParameter(f"expected .c file, got: {p.name}")
    return str(rel).replace("\\", "/")


def _resolve_existing_cli_file(
    path: Path,
    *,
    melee_root: Path = DEFAULT_MELEE_ROOT,
    label: str = "file",
) -> Path:
    """Resolve a CLI path from cwd first, then from the repo root."""
    expanded = path.expanduser()
    if expanded.is_absolute():
        resolved = expanded.resolve()
        if resolved.is_file():
            return resolved
        raise typer.BadParameter(f"{label} not found: {resolved}")

    candidates = [
        (Path.cwd() / expanded).resolve(),
        (melee_root / expanded).resolve(),
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            return candidate
    raise typer.BadParameter(f"{label} not found: {candidates[0]}")


@dump_app.command("remote")
def pcdump(
    c_file: Annotated[
        str,
        typer.Argument(help="Path to a .c file in the melee repo"),
    ],
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Output path for the dump. Default: cache it under "
                 "build/mwcc_debug_cache/<unit>.txt so follow-up commands "
                 "can auto-resolve it. Use '-' to force stdout instead.",
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout", "-t",
            help="Per-compile timeout in seconds (passed to remote)",
        ),
    ] = 60,
    host: Annotated[
        str,
        typer.Option(
            help="SSH host alias for the Windows debug machine",
            envvar="MWCC_DEBUG_HOST",
        ),
    ] = "nzxt-local",
    remote_script: Annotated[
        str,
        typer.Option(
            help="Path to run_pcdump.ps1 on the remote host",
            envvar="MWCC_DEBUG_REMOTE_SCRIPT",
        ),
    ] = r"C:\Users\mikes\code\mwcc_debug\run_pcdump.ps1",
    no_pull: Annotated[
        bool,
        typer.Option(
            "--no-pull",
            help="Skip 'git pull' on the remote side (test stale code)",
        ),
    ] = False,
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help="Tier 5: bias the allocator. Format 'virtIdx:physReg[,...]' "
                 "or 'class:virtIdx:physReg[,...]' (class: gpr, fp, fpr, int). "
                 "E.g. '36:31' or 'gpr:36:31'. Class-scoped entries are "
                 "passed through to the DLL and only apply to that register "
                 "class. "
                 "EXPERIMENTAL — may produce broken code if interferences "
                 "are violated.",
        ),
    ] = None,
    force_phys_iter: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys-iter",
            help="Tier 5: bias by colorgraph iter position "
                 "(class:iter:phys[,...]). Use for nodes that lack an "
                 "addressable ig_idx. EXPERIMENTAL.",
        ),
    ] = None,
    force_phys_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys-fn",
            help="Scope --force-phys and --force-phys-iter to one function. "
                 "EXPERIMENTAL.",
        ),
    ] = None,
    branch: Annotated[
        Optional[str],
        typer.Option(
            "--branch",
            help="Compile against this branch on the remote. If omitted, "
                 "auto-detects from the local repo's current branch. The "
                 "remote maintains a worktree per branch so concurrent "
                 "pcdumps on different branches don't clobber each other.",
            envvar="MWCC_DEBUG_BRANCH",
        ),
    ] = None,
    force_iter_first: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first",
            help="Tier 6: reorder the simplification list so named virtuals "
                 "are popped first by colorgraph. Format 'virtIdx[,virtIdx]*'. "
                 "E.g. '32' promotes virtual r32 to the head of the "
                 "simplification stack — it gets first crack at the top-down "
                 "callee-save dispense (r31). Addresses the param-iter-ceiling "
                 "pattern. EXPERIMENTAL — produces DLL-patched binary, NOT "
                 "what real MWCC would emit from any C source.",
        ),
    ] = None,
    force_iter_first_class: Annotated[
        Optional[int],
        typer.Option(
            "--force-iter-first-class",
            help=(
                "Scope --force-iter-first IG indices to one register class "
                "(0=GPR, 1=FPR). Use when the same ig_idx exists in multiple "
                "classes and an FPR/GPR-only hypothesis must avoid disturbing "
                "the other allocator pass."
            ),
        ),
    ] = None,
    force_iter_first_iter: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first-iter",
            help=(
                "Tier 6: reorder simplification list by class and current "
                "iteration position. Format 'class:iter[,class:iter]*'. "
                "Useful for split/spill nodes that lack a stable ig_idx."
            ),
        ),
    ] = None,
    force_iter_first_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first-fn",
            help="Scope --force-iter-first to one function in the TU. Other "
                 "functions compile with their natural simplification order.",
        ),
    ] = None,
    force_select_order: Annotated[
        Optional[str],
        typer.Option(
            "--force-select-order",
            help="Tier 6: explicit alias for --force-iter-first when testing "
                 "allocator selection order. Format 'virtIdx[,virtIdx]*'; "
                 "the first listed node gets first selection priority.",
        ),
    ] = None,
    force_select_order_class: Annotated[
        Optional[int],
        typer.Option(
            "--force-select-order-class",
            help="Scope --force-select-order IG indices to one register class "
                 "(0=GPR, 1=FPR).",
        ),
    ] = None,
    force_select_order_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-select-order-fn",
            help="Scope --force-select-order to one function in the TU.",
        ),
    ] = None,
    force_coalesce: Annotated[
        Optional[str],
        typer.Option(
            "--force-coalesce",
            help="Tier 6: override the conservative coalescer. Format "
                 "'virt=root[,virt=root]*'. E.g. '42=38' forces virtual 42 "
                 "to coalesce into 38; '42=42' un-coalesces 42 back to its "
                 "own root. EXPERIMENTAL.",
        ),
    ] = None,
    force_coalesce_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-coalesce-fn",
            help="Scope --force-coalesce to a single function name in "
                 "the TU. Other functions compile naturally. EXPERIMENTAL.",
        ),
    ] = None,
    force_schedule: Annotated[
        Optional[str],
        typer.Option(
            "--force-schedule",
            help="Tier 7: pin adjacent same-base load order after MWCC's "
                 "instruction scheduler. Format 'op:beforeOffset>afterOffset"
                 "[,...]'. E.g. 'lwz:0x74>0x70' forces a same-base lwz pair "
                 "at offsets 0x70/0x74 to appear 0x74 first. EXPERIMENTAL.",
        ),
    ] = None,
    force_schedule_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-schedule-fn",
            help="Scope --force-schedule to a single function name in the TU. "
                 "Other functions compile naturally. EXPERIMENTAL.",
        ),
    ] = None,
):
    """Dump MWCC's internal IR + codegen for a TU and emit pcdump.txt to stdout.

    Compiles the given .c file on a remote Windows host under the mwcc_debug
    patched lmgr326b.dll, which unlocks MWCC's normally-disabled `debuglisting`
    output. The dump shows per-function basic-block structure, every pass of
    the IR optimizer with virtual registers, and the AFTER REGISTER COLORING
    pass with physical-register assignments — useful when diagnosing
    register-allocation mismatches that mismatch-db / opseq / ghidra haven't
    explained.

    On success, the raw pcdump.txt is written to the cache at
    build/mwcc_debug_cache/<unit>.txt by default. Use --output PATH for
    a custom location, or --output - for stdout. Follow-up commands like
    `debug inspect analyze -f FN` auto-resolve the cached pcdump by TU.
    All diagnostics go to stderr. Exit code matches the remote compile's
    exit code (0 = success).

    Setup: see docs/mwcc-debug.md. Requires SSH access to a Windows machine
    that has run_pcdump.ps1 and the patched lmgr326b.dll installed.
    """
    src_rel = _resolve_src_relative(c_file)

    # Resolve the branch. If not provided, auto-detect from local git
    # (the agent's typical case: they're on `wip/<topic>` locally and
    # want to compile that branch on the remote without thinking about
    # it). master/main use the legacy single-checkout path on the remote.
    if branch is None:
        try:
            r = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=DEFAULT_MELEE_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if r.returncode == 0:
                branch = r.stdout.strip() or None
        except Exception:
            branch = None
    # Reject anything that looks dangerous to pass through cmd.exe.
    if branch is not None and any(c in branch for c in '"\'; \t&|<>'):
        raise typer.BadParameter(
            f"branch name must not contain shell metacharacters: {branch!r}"
        )

    # Build the SSH command. Quoted `set "VAR=value"` avoids cmd.exe
    # including separator whitespace in the value before `&&`.
    # The cmd line is:
    #   set "MWCC_DEBUG_TIMEOUT_SECS=N" && [set "MWCC_DEBUG_NO_PULL=1" &&]
    #   powershell -NoProfile -ExecutionPolicy Bypass -File <script> <src>
    cmd_parts = [_cmd_set_env("MWCC_DEBUG_TIMEOUT_SECS", str(timeout))]
    if no_pull:
        cmd_parts.append(_cmd_set_env("MWCC_DEBUG_NO_PULL", "1"))
    if force_phys:
        # Reject embedded quotes/spaces to keep the cmd-line safe, then
        # normalize (strips optional class prefix, emits ambiguity warning).
        if any(c in force_phys for c in '"\'; \t'):
            raise typer.BadParameter(
                "--force-phys must not contain quotes, semicolons, or whitespace"
            )
        force_phys_dll, fp_warnings = _normalize_force_phys(force_phys)
        for w in fp_warnings:
            print(w, file=sys.stderr)
        cmd_parts.append(_cmd_set_env("MWCC_DEBUG_FORCE_PHYS", force_phys_dll))
    if force_phys_iter:
        if any(c in force_phys_iter for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-phys-iter must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(_cmd_set_env(
            "MWCC_DEBUG_FORCE_PHYS_ITER",
            force_phys_iter,
        ))
    if force_phys_fn:
        if any(c in force_phys_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-phys-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(_cmd_set_env(
            "MWCC_DEBUG_FORCE_PHYS_FUNCTION",
            force_phys_fn,
        ))
    if branch and branch not in ("master", "main"):
        # Non-default branch — remote will use a worktree.
        cmd_parts.append(_cmd_set_env("MWCC_DEBUG_BRANCH", branch))
    if force_iter_first and force_select_order:
        raise typer.BadParameter(
            "--force-select-order and --force-iter-first target the same "
            "selection-order hook; use one spelling per run"
        )
    iter_first_value = force_iter_first or force_select_order
    iter_first_class = (
        force_iter_first_class
        if force_iter_first is not None
        else force_select_order_class
    )
    iter_first_fn = force_iter_first_fn or force_select_order_fn

    if iter_first_value:
        if any(c in iter_first_value for c in '"\'; \t'):
            raise typer.BadParameter(
                "--force-iter-first/--force-select-order must not contain quotes, semicolons, "
                "or whitespace"
            )
        cmd_parts.append(_cmd_set_env(
            "MWCC_DEBUG_FORCE_ITER_FIRST",
            iter_first_value,
        ))
    if iter_first_class is not None:
        if not iter_first_value:
            raise typer.BadParameter(
                "--force-iter-first-class/--force-select-order-class requires "
                "--force-iter-first or --force-select-order"
            )
        cmd_parts.append(_cmd_set_env(
            "MWCC_DEBUG_FORCE_ITER_FIRST_CLASS",
            str(iter_first_class),
        ))
    if force_iter_first_iter:
        if any(c in force_iter_first_iter for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-iter-first-iter must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(_cmd_set_env(
            "MWCC_DEBUG_FORCE_ITER_FIRST_ITER",
            force_iter_first_iter,
        ))
    if iter_first_fn:
        if any(c in iter_first_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-iter-first-fn/--force-select-order-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(
            _cmd_set_env(
                "MWCC_DEBUG_FORCE_ITER_FIRST_FUNCTION",
                iter_first_fn,
            )
        )
    if force_coalesce:
        if any(c in force_coalesce for c in '"\'; \t'):
            raise typer.BadParameter(
                "--force-coalesce must not contain quotes, semicolons, "
                "or whitespace"
            )
        cmd_parts.append(_cmd_set_env(
            "MWCC_DEBUG_FORCE_COALESCE",
            force_coalesce,
        ))
    if force_coalesce_fn:
        if any(c in force_coalesce_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-coalesce-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(
            _cmd_set_env(
                "MWCC_DEBUG_FORCE_COALESCE_FUNCTION",
                force_coalesce_fn,
            )
        )
    if force_schedule:
        force_schedule = _validate_force_schedule(force_schedule)
        cmd_parts.append(_cmd_set_env("MWCC_DEBUG_FORCE_SCHEDULE", force_schedule))
    if force_schedule_fn:
        if any(c in force_schedule_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-schedule-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(
            _cmd_set_env(
                "MWCC_DEBUG_FORCE_SCHEDULE_FUNCTION",
                force_schedule_fn,
            )
        )
    cmd_parts.append(
        f"powershell -NoProfile -ExecutionPolicy Bypass "
        f"-File {remote_script} {src_rel}"
    )
    remote_cmd = " && ".join(cmd_parts)

    # SSH on Windows defaults to cmd as the user's login shell typically.
    # We pass a single command string to be invoked there.
    ssh_cmd = ["ssh", host, remote_cmd]

    branch_label = (f" branch={branch}"
                    if branch and branch not in ("master", "main") else "")
    print(f"[mwcc_debug] ssh {host} run_pcdump.ps1 {src_rel}{branch_label}",
          file=sys.stderr)

    # Decide where stdout goes. Default behavior changed in H2: if no
    # --output is given, save to the project pcdump cache instead of
    # stdout. This lets follow-up `debug inspect analyze`,
    # `debug inspect guide`, or `debug target score-dump` find the
    # dump automatically without the agent threading file paths.
    # Explicit `--output -` forces stdout (old default).
    use_cache = output is None
    if str(output) == "-":
        stdout_dest = sys.stdout.buffer
        out_path_for_msg = "stdout"
        cache_path_used: Optional[Path] = None
    elif use_cache:
        # Strip the `src/` prefix and `.c` suffix to get the unit key.
        unit = src_rel
        if unit.startswith("src/"):
            unit = unit[len("src/"):]
        if unit.endswith(".c"):
            unit = unit[:-2]
        pcdump_cache.ensure_cache_dir(DEFAULT_MELEE_ROOT)
        cache_path_used = pcdump_cache.cache_path(DEFAULT_MELEE_ROOT, unit)
        cache_path_used.parent.mkdir(parents=True, exist_ok=True)
        stdout_dest = open(cache_path_used, "wb")
        out_path_for_msg = str(cache_path_used)
    else:
        cache_path_used = None
        stdout_dest = open(output, "wb")
        out_path_for_msg = str(output)

    try:
        # Use Popen so we can stream large dumps without buffering everything
        proc = subprocess.Popen(
            ssh_cmd,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,  # forward remote diagnostics to local stderr
        )
        assert proc.stdout is not None
        total = 0
        while True:
            chunk = proc.stdout.read(8192)
            if not chunk:
                break
            stdout_dest.write(chunk)
            total += len(chunk)
        exit_code = proc.wait()
    finally:
        if str(output) != "-":
            stdout_dest.close()

    if exit_code == 0:
        print(
            f"[mwcc_debug] wrote {total} bytes to {out_path_for_msg}",
            file=sys.stderr,
        )
        if cache_path_used is not None:
            # Write the content-hash sidecar so follow-up commands can
            # detect freshness by content rather than mtime.  Commands
            # like enumerate-decl-orders and tier3-search restore the
            # source after patching, updating mtime even when unchanged;
            # the sidecar avoids false "stale" warnings after restore.
            try:
                src_file = DEFAULT_MELEE_ROOT / src_rel
                pcdump_cache.write_hash_sidecar(cache_path_used, src_file)
            except OSError:
                pass  # sidecar is best-effort; fall back to mtime on next lookup
            print(
                f"[mwcc_debug] cached — follow-up commands "
                f"(`inspect analyze`, `inspect guide`, "
                f"`target score-dump`, etc.) will auto-resolve "
                f"this dump by function name.",
                file=sys.stderr,
            )
    else:
        print(
            f"[mwcc_debug] remote exited {exit_code}; {total} bytes captured",
            file=sys.stderr,
        )

    raise typer.Exit(code=exit_code)


_FORCE_PHYS_CLASS_NAMES = {
    "gpr": 0,
    "int": 0,
    "r": 0,
    "class0": 0,
    "fp": 1,
    "fpr": 1,
    "f": 1,
    "class1": 1,
}
"""Recognized class-prefix names for the ``class:ig_idx:phys`` form.

``gpr`` / ``int`` → GPR class; ``fp`` / ``fpr`` → FP class.
Numeric class IDs are also accepted and passed through to the DLL.
"""


def _parse_force_phys_class(raw: str) -> int:
    class_s = raw.strip().lower()
    if class_s in _FORCE_PHYS_CLASS_NAMES:
        return _FORCE_PHYS_CLASS_NAMES[class_s]
    try:
        class_id = int(class_s, 0)
    except ValueError as exc:
        raise typer.BadParameter(
            f"--force-phys class {raw!r} is invalid. Expected one of "
            "{gpr, fp, fpr, int, class0, class1} or a numeric class ID."
        ) from exc
    if class_id < 0:
        raise typer.BadParameter("--force-phys class ID must be non-negative")
    return class_id


def _validate_force_schedule(raw: str, *, option: str = "--force-schedule") -> str:
    if any(c in raw for c in '"\'; \t\r\n&|<^'):
        raise typer.BadParameter(
            f"{option} must not contain quotes, semicolons, whitespace, "
            "or shell metacharacters other than '>'"
        )
    return raw


def _cmd_set_env(name: str, value: str) -> str:
    """Build a cmd.exe env assignment without leaking separator whitespace."""
    if any(c in value for c in '"\r\n'):
        raise typer.BadParameter(
            f"{name} value must not contain quotes or newlines"
        )
    return f'set "{name}={value}"'


def _normalize_force_phys(raw: str) -> tuple[str, list[str]]:
    """Parse and normalize a ``--force-phys`` value.

    Accepts two forms per spec:
      - Legacy: ``ig_idx:phys[,ig_idx:phys]*``
      - Class-scoped: ``class:ig_idx:phys[,class:ig_idx:phys]*``
        where class is one of ``gpr``, ``fp``, ``fpr``, ``int`` or a
        numeric class ID.

    Returns ``(dll_value, warnings)`` where:
      - ``dll_value`` is the force-phys string to pass to the DLL. Bare
        entries remain ``ig_idx:phys``; scoped entries become
        ``class_id:ig_idx:phys``.
      - ``warnings`` is a list of human-readable warning strings
        (empty when input is unambiguous).

    Raises ``typer.BadParameter`` on malformed input.
    """
    parts = raw.split(",")
    dll_parts: list[str] = []
    warnings: list[str] = []
    seen_bare: list[str] = []  # bare ig_idx values, to detect later if wanted

    for spec in parts:
        spec = spec.strip()
        if not spec:
            continue
        tokens = spec.split(":")
        if len(tokens) == 3:
            class_s, ig_idx_s, phys_s = tokens
            class_id = _parse_force_phys_class(class_s)
            dll_parts.append(f"{class_id}:{ig_idx_s}:{phys_s}")
        elif len(tokens) == 2:
            # Bare ig_idx:phys form. The DLL accepts this but it matches
            # all IG classes (GPR, FP, etc.) with that ig_idx, which can
            # be ambiguous when a GPR and an FP node share the same ig_idx.
            dll_parts.append(spec)
            seen_bare.append(tokens[0])
        else:
            raise typer.BadParameter(
                f"--force-phys spec {spec!r} is invalid. "
                f"Expected 'ig_idx:physReg' or 'class:ig_idx:physReg' "
                f"(class in {{gpr, fp, fpr, int, class0, class1}} or numeric). "
                f"E.g. '36:31' or 'gpr:36:31'."
            )

    if seen_bare:
        warnings.append(
            f"[force-phys] bare ig_idx form used ({', '.join(seen_bare)}): "
            f"the DLL will force ALL IG classes (GPR, FP, …) that have a "
            f"node with that ig_idx. If this matches multiple classes, "
            f"use 'class:ig_idx:phys' (e.g. 'gpr:{seen_bare[0]}:N') to "
            f"scope to one class and avoid unintended FP register overrides."
        )

    return ",".join(dll_parts), warnings


# PowerPC EABI register conventions for GPR. The first 8 args go in r3..r10;
# return value is in r3. Floats use f1..f13 / f1 return. We only annotate
# the GPR convention here — most matching investigations are GPR-bound.
PPC_ABI_GPR = {
    1: "SP",
    2: "TOC",
    3: "arg0 / ret",
    4: "arg1",
    5: "arg2",
    6: "arg3",
    7: "arg4",
    8: "arg5",
    9: "arg6",
    10: "arg7",
}


def _abi_hint(physical: Optional[int], reg_kind: str = "r") -> str:
    """Return a short ABI hint for a physical register, or empty string."""
    if physical is None:
        return ""
    if reg_kind == "f":
        if physical >= 14:
            return "callee-save FPR"
        return "caller-save FPR"
    if physical == 0:
        return "scratch"  # r0 has special semantics in some PPC instructions
    if physical in PPC_ABI_GPR:
        return PPC_ABI_GPR[physical]
    if 11 <= physical <= 12:
        return "caller-save"
    if 13 <= physical <= 31:
        return "callee-save"
    return ""


def _virtreg_to_dict(info) -> dict:
    """Serialize a VirtualRegInfo for JSON output."""
    reg_kind = getattr(info, "reg_kind", "r")
    return {
        "reg_kind": reg_kind,
        "virtual": info.virtual,
        "physical": info.physical,
        "physical_class": info.physical_class,
        "abi_hint": _abi_hint(info.physical, reg_kind),
        "first_use": info.first_use,
        "last_use": info.last_use,
        "use_count": info.use_count,
        "interferes_with": sorted(info.interferes_with),
        "candidates": sorted(info.candidates),
    }


@inspect_app.command("analyze")
def analyze(
    dump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to a pcdump.txt produced by 'debug dump remote'. "
                 "If omitted, auto-resolves via --function from the "
                 "cache at build/mwcc_debug_cache/.",
        ),
    ] = None,
    function: Annotated[
        Optional[str],
        typer.Option(
            "--function", "-f",
            help="Show only this function (default: list all). Also "
                 "used to auto-resolve the pcdump path when not given.",
        ),
    ] = None,
    show_candidates: Annotated[
        bool,
        typer.Option(
            "--candidates",
            help="Show the set of physicals each virtual could have been "
                 "assigned (based on interferer constraints).",
        ),
    ] = True,
    json_out: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit structured JSON instead of human-readable text.",
        ),
    ] = False,
):
    """Summarize a pcdump.txt: per-virtual register live ranges, use counts,
    interferences, and 'could have been' candidate sets.

    Without --function, lists all functions with brief summary. With --function,
    prints a detailed coloring-decision table for that function — the kind of
    output that tells you whether a register-cascade question is constrained
    by interferences or is a free allocator choice.

    The 'Candidates' column shows physicals not used by interfering virtuals.
    If a virtual got a physical that's NOT the lowest-numbered candidate, that
    asymmetry is the kind of allocator-preference question worth digging into.
    """
    dump = _resolve_pcdump_path(dump, function)

    text = dump.read_text()
    funcs = parse_pcdump(text)

    if not funcs:
        print(f"No functions found in {dump}", file=sys.stderr)
        raise typer.Exit(code=1)

    if function is None:
        # List all functions, brief summary
        if json_out:
            payload = [
                {
                    "name": fn.name,
                    "n_passes": len(fn.passes),
                    "has_coloring": fn.get_pass("AFTER REGISTER COLORING") is not None,
                }
                for fn in funcs
            ]
            print(json.dumps({"dump": str(dump), "functions": payload}, indent=2))
            return
        print(f"Functions in {dump.name}:")
        for fn in funcs:
            n_passes = len(fn.passes)
            has_color = fn.get_pass("AFTER REGISTER COLORING") is not None
            color_note = "" if has_color else " (no coloring pass — truncated dump?)"
            print(f"  {fn.name}: {n_passes} passes{color_note}")
        return

    # Find the requested function
    target = next((fn for fn in funcs if fn.name == function), None)
    if target is None:
        avail = ", ".join(fn.name for fn in funcs)
        raise typer.BadParameter(
            f"function '{function}' not in dump. Available: {avail}"
        )

    if target.get_pass("AFTER REGISTER COLORING") is None:
        print(
            f"WARNING: {function} has no AFTER REGISTER COLORING pass — "
            "dump may be truncated. Analysis skipped.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    pre = target.last_precolor_pass()
    post = target.get_pass("AFTER REGISTER COLORING")
    if not json_out:
        print(f"Function: {target.name}")
        print(f"Pre-coloring pass: {pre.name if pre else '<none>'}")
        print(f"Post-coloring pass: {post.name}")
        print()

    infos = analyze_function(target)
    if not infos:
        if json_out:
            print(json.dumps({"function": target.name, "virtuals": [], "warning": "no virtual registers found"}, indent=2))
            return
        print("No virtual registers found (or pass alignment failed).")
        return

    if json_out:
        payload = {
            "function": target.name,
            "pre_coloring_pass": pre.name if pre else None,
            "post_coloring_pass": post.name,
            "virtuals": [_virtreg_to_dict(info) for info in infos],
        }
        print(json.dumps(payload, indent=2))
        return

    # PowerPC EABI reminder
    print("ABI: r3=arg0/ret, r4=arg1, r5=arg2, ..., r10=arg7; "
          "r13-r31=callee-save; r0=scratch.")
    print()

    # Column widths
    print(f"{'Virtual':>8}  {'Phys':>5}  {'Class':<8}  {'ABI':<14}  {'Live[first..last]':<18}  {'Uses':>5}  Interferes")
    print(f"{'-' * 8:>8}  {'-' * 5:>5}  {'-' * 8:<8}  {'-' * 14:<14}  {'-' * 18:<18}  {'-' * 5:>5}  ----------")
    for info in infos:
        reg_kind = getattr(info, "reg_kind", "r")
        phys = f"{reg_kind}{info.physical}" if info.physical is not None else "?"
        live = f"{info.first_use}..{info.last_use}"
        abi = _abi_hint(info.physical, reg_kind)
        # Format interferes_with as a compact list
        if info.interferes_with:
            interferers = ",".join(
                f"{reg_kind}{v}" for v in sorted(info.interferes_with)
            )
        else:
            interferers = "-"
        print(
            f"     {reg_kind}{info.virtual:<3}  {phys:>5}  {info.physical_class:<8}  "
            f"{abi:<14}  {live:<18}  {info.use_count:>5}  {interferers}"
        )

    if show_candidates:
        print()
        print("Coloring decisions. Verified algorithm (Tier 2 binary-hook data):")
        print("  1. Compute workingMask = volatile-regs (r3..r12, r0 excluded)")
        print("     minus regs used by interferers.")
        print("  2. If workingMask non-empty: pick LOWEST set bit.")
        print("  3. Else call obtain_nonvolatile_register(), which dispenses")
        print("     TOP-DOWN: r31, r30, r29, r28, r27, then r26, r25, ...")
        print("     (Once dispensed, reg is added to volatile-regs pool and")
        print("     can be reused for non-interfering virtuals.)")
        print("Run 'debug inspect simulate' to see what the allocator would pick + why.")
        print("For exact iteration order + per-decision data, see the")
        print("'COLORGRAPH DECISIONS' sections in the raw pcdump.")
        for info in infos:
            if info.physical is None or not info.candidates:
                continue
            cands = sorted(info.candidates)
            reg_kind = getattr(info, "reg_kind", "r")
            cand_str = "{" + ",".join(f"{reg_kind}{c}" for c in cands) + "}"
            abi = _abi_hint(info.physical, reg_kind)
            abi_note = f"  [{abi}]" if abi else ""
            print(
                f"  {reg_kind}{info.virtual} → {reg_kind}{info.physical}"
                f"{abi_note}.  Candidates: {cand_str}"
            )


@inspect_app.command("simulate")
def simulate(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to simulate (required)",
        ),
    ],
    dump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to a pcdump.txt produced by 'debug dump remote'. "
                 "If omitted, auto-resolves via --function from cache."
        ),
    ] = None,
    show_all: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Show every decision, even when prediction matches actual.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit simulation results as JSON."),
    ] = False,
):
    """Simulate MWCC's coloring algorithm on a function and diff against actuals.

    Re-implements the register-coloring loop from MWCC's source (extracted from
    the 7.0 decompilation at git.wuffs.org/MWCC). For each virtual register,
    the simulator predicts what physical the allocator would have picked and
    why. Compares against the actual choice from the pcdump.

    Matches confirm our understanding of the algorithm. Mismatches highlight
    cases where our model is wrong — usually due to factors we don't see in
    pcdump (caller-save kill at call sites, argument-passing ABI pinning, or
    nonvolatile-allocation-order edge cases).

    See docs/mwcc-debug-future-ideas.md for the long-term plan to replace
    this simulator with a real hook into mwcceppc.exe's allocator.
    """
    dump = _resolve_pcdump_path(dump, function)
    text = dump.read_text()
    funcs = parse_pcdump(text)
    target = next((fn for fn in funcs if fn.name == function), None)
    if target is None:
        _abort_function_not_in_dump(function, [fn.name for fn in funcs])

    decisions = simulate_function(target)
    if not decisions:
        infos = analyze_function(target)
        has_fpr_virtuals = any(
            getattr(info, "reg_kind", "r") == "f" for info in infos
        )
        has_gpr_virtuals = any(
            getattr(info, "reg_kind", "r") == "r" for info in infos
        )
        if has_fpr_virtuals and not has_gpr_virtuals:
            message = (
                "FPR virtual registers found, but simulate is GPR-only; "
                "use `debug inspect analyze` for FPR mapping details."
            )
            if json_out:
                print(json.dumps({
                    "function": function,
                    "error": "fpr-virtuals-unsupported-by-gpr-simulator",
                    "message": message,
                }))
            else:
                print(message)
            return
        if json_out:
            print(json.dumps({"function": function, "error":
                              "no virtual registers found (or pass alignment failed)"}))
        else:
            print("No virtual registers found (or pass alignment failed).")
        raise typer.Exit(code=1)

    matches = sum(1 for d in decisions if d.actual_physical == d.predicted_physical)
    mismatches = len(decisions) - matches

    if json_out:
        print(json.dumps({
            "function": target.name,
            "summary": {
                "matches": matches,
                "mismatches": mismatches,
                "total": len(decisions),
            },
            "decisions": [{
                "virtual": d.virtual,
                "actual_physical": d.actual_physical,
                "predicted_physical": d.predicted_physical,
                "match": d.actual_physical == d.predicted_physical,
                "reasoning": d.reasoning,
            } for d in decisions],
        }, indent=2))
        return

    print(f"Function: {target.name}")
    print(f"Algorithm: MWCC-style greedy coloring (per 7.0 source). Iteration")
    print(f"order: ascending interferer count.")
    print()
    print(f"{'Virtual':>8}  {'Actual':>7}  {'Predicted':>9}  {'Match':>5}  Reasoning")
    print(f"{'-' * 8:>8}  {'-' * 7:>7}  {'-' * 9:>9}  {'-' * 5:>5}  ---------")

    for d in decisions:
        actual = f"r{d.actual_physical}" if d.actual_physical is not None else "?"
        predicted = f"r{d.predicted_physical}" if d.predicted_physical is not None else "SPILL"
        is_match = d.actual_physical == d.predicted_physical
        match_marker = "✓" if is_match else "✗"
        if show_all or not is_match:
            print(
                f"     r{d.virtual:<3}  {actual:>7}  {predicted:>9}  "
                f"{match_marker:>5}  {d.reasoning}"
            )

    print()
    print(f"Summary: {matches} match, {mismatches} mismatch "
          f"(out of {len(decisions)} virtuals)")

    if mismatches and not show_all:
        print("Use --all to see matching decisions too.")


@inspect_app.command("first-divergence")
def first_divergence_cmd(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name"),
    ],
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help=(
                "Target coloring as ig:phys[,ig:phys] (the map KEYS are the "
                "target node set). Required unless --frame is used."
            ),
        ),
    ] = None,
    dump: Annotated[
        Optional[Path],
        typer.Argument(help="pcdump (auto-resolved if omitted)"),
    ] = None,
    class_id: Annotated[
        int,
        typer.Option("--class", help="Register class (0=GPR, 1=FPR)"),
    ] = 0,
    source: Annotated[
        bool,
        typer.Option("--source", help="Attach advisory source ideas"),
    ] = False,
    frame: Annotated[
        bool,
        typer.Option(
            "--frame",
            help=(
                "Explain the first stack-frame/local-area divergence instead "
                "of allocator force-phys divergence."
            ),
        ),
    ] = False,
    expected_asm: Annotated[
        Optional[Path],
        typer.Option(
            "--expected-asm",
            help=(
                "Expected target asm for --frame. Omit to extract via "
                "`melee-agent extract get <function> --full`."
            ),
        ),
    ] = None,
    no_expected: Annotated[
        bool,
        typer.Option(
            "--no-expected",
            help="For --frame, inspect only the current pcdump without target asm.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable output."),
    ] = False,
):
    """Find the earliest allocator decision diverging from a same-source target.

    Gated allocator facts are derived mechanically from the recorded colorgraph;
    --source adds a NON-gated advisory layer (heuristic symbol-bridge mapping).
    """
    if frame:
        if source:
            typer.echo(
                "--source is only valid for allocator --force-phys mode; "
                "frame mode emits source levers directly.",
                err=True,
            )
            raise typer.Exit(2)
        report = _first_divergence_frame_report(
            function,
            dump=dump,
            expected_asm=expected_asm,
            no_expected=no_expected,
        )
        if json_out:
            print(json.dumps(report, indent=2))
        else:
            print(_format_first_divergence_frame_report(report))
        return

    if force_phys is None:
        raise typer.BadParameter("--force-phys is required unless --frame is used")
    if expected_asm is not None or no_expected:
        raise typer.BadParameter("--expected-asm/--no-expected require --frame")
    if json_out:
        raise typer.BadParameter("--json is currently only supported with --frame")

    from ..mwcc_debug import first_divergence as fd
    from ..mwcc_debug.colorgraph_parser import parse_hook_events, find_function

    dump_path = _resolve_pcdump_path(dump, function)
    text = dump_path.read_text()
    events = parse_hook_events(text)
    fev = find_function(events, function)
    if fev is None:
        raise typer.BadParameter(f"function {function!r} not found in dump")
    try:
        fp_map = fd.parse_force_phys_arg(force_phys)
    except ValueError as exc:
        raise typer.BadParameter(str(exc))
    target = fd.TargetColoring(class_id=class_id, force_phys=fp_map)
    try:
        report = fd.analyze_first_divergence(fev, target)
    except ValueError as exc:
        raise typer.BadParameter(str(exc))
    if source:
        # Advisory (non-gated): resolve the unit source + pre-coloring pass the
        # same way `virtual-to-var` does, then attach symbol-bridge ideas.
        # Degrades to structural-only ideas on any resolution failure.
        src_text, pre = "", None
        try:
            fn = next((f for f in parse_pcdump(text) if f.name == function), None)
            if fn is not None:
                pre = fn.last_precolor_pass()
            unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
            if unit is not None:
                src_text = (DEFAULT_MELEE_ROOT / "src" / f"{unit}.c").read_text()
        except Exception:
            src_text, pre = "", None
        report = fd.FirstDivergenceReport(
            fact=report.fact,
            source=fd.attach_source_ideas(report.fact, src_text, function, pre),
        )
    typer.echo(fd.format_report(report))


def _first_divergence_frame_case(report: dict) -> str:
    if report.get("expected") is None:
        return "frame-current-only"
    if report.get("current_low_frame_expansion") is not None:
        return "frame-unused-low-home"
    if report.get("extra_low_frame_reservation") is not None:
        return "frame-missing-low-reservation"
    if report.get("frame_delta"):
        return "frame-size"
    return "none"


def _first_divergence_frame_local_target(case: str, residual: dict | None) -> str:
    if case == "frame-unused-low-home":
        text = (
            "suppress the unused low local home by changing the source shape "
            "that created it; for held-FP constants, try splitting the constant "
            "lifetime or using the literal/global expression at the final FP call"
        )
        if residual and residual.get("alignment_growth_bytes"):
            text += (
                ", then reduce the downstream 8-byte alignment growth from the "
                "int-to-float scratch slot"
            )
        return text
    if case == "frame-missing-low-reservation":
        return (
            "introduce the target's low-frame reservation naturally, or use "
            "frame patch/probe verification to confirm the expected frame is reachable"
        )
    if case == "frame-size":
        return (
            "derive a frame target from checkdiff and rank source candidates by "
            "frame-size and unused-range distance"
        )
    if case == "none":
        return "no frame/local-area divergence detected"
    return "inspect the current frame without a target frame comparison"


def _frame_residual_for_case(report: dict, case: str) -> dict | None:
    if case == "frame-unused-low-home":
        return report.get("current_low_frame_expansion")
    if case == "frame-missing-low-reservation":
        return report.get("extra_low_frame_reservation")
    return None


def _first_divergence_frame_report(
    function: str,
    *,
    dump: Path | None,
    expected_asm: Path | None,
    no_expected: bool,
) -> dict:
    melee_root = DEFAULT_MELEE_ROOT
    dump_path = _resolve_pcdump_path(dump, function, melee_root)
    pcdump_text = dump_path.read_text()
    expected_text = _read_frame_reservation_expected_asm(
        function,
        expected_asm=expected_asm,
        no_expected=no_expected,
        melee_root=melee_root,
    )
    current_text = (
        _read_frame_reservation_current_asm(function, melee_root=melee_root)
        if _pcdump_has_symbolic_stack_homes(pcdump_text)
        else None
    )
    try:
        frame_report = analyze_frame_reservations(
            pcdump_text,
            function,
            expected_asm_text=expected_text,
            current_asm_text=current_text,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    case = _first_divergence_frame_case(frame_report)
    residual = _frame_residual_for_case(frame_report, case)
    unit = _find_unit_for_function(function, melee_root)
    suggestions = _frame_source_suggestions_from_report(frame_report, unit=unit)
    next_steps = [
        f"melee-agent debug inspect frame-reservations -f {function}",
        f"melee-agent debug suggest frame -f {function}",
    ]
    for suggestion in suggestions:
        for command in suggestion.get("commands") or []:
            if command not in next_steps:
                next_steps.append(command)

    residual_payload = None
    if isinstance(residual, dict):
        residual_payload = {
            "range": {
                "start": residual.get("start"),
                "end": residual.get("end"),
                "size": residual.get("size"),
            },
            "origin": residual.get("origin"),
            "frame_growth_bytes": residual.get("frame_growth_bytes"),
            "alignment_growth_bytes": residual.get("alignment_growth_bytes"),
            "current_accesses_in_range": residual.get("current_accesses_in_range", []),
        }

    current = frame_report.get("current") or {}
    expected = frame_report.get("expected") or {}
    return {
        "kind": "frame-local-area",
        "function": function,
        "case": case,
        "summary": frame_report.get("summary"),
        "current_frame": current.get("frame_size"),
        "target_frame": expected.get("frame_size"),
        "frame_delta": frame_report.get("frame_delta"),
        "residual": residual_payload,
        "local_target": _first_divergence_frame_local_target(case, residual),
        "next_steps": next_steps,
        "suggestions": suggestions,
        "frame": frame_report,
    }


def _format_first_divergence_frame_report(report: dict) -> str:
    lines = ["=== FRAME/LOCAL-AREA FACTS (gated) ==="]
    lines.append(
        "First divergence: frame/local-area "
        f"Case {report['case']}"
    )
    lines.append(f"  current frame: {report.get('current_frame')}")
    lines.append(f"  target frame: {report.get('target_frame')}")
    lines.append(f"  frame delta: {report.get('frame_delta')}")
    residual = report.get("residual")
    if residual is not None:
        range_info = residual["range"]
        if range_info.get("start") is not None:
            lines.append(
                "  residual range: "
                + _format_stack_range({
                    "start": range_info["start"],
                    "end": range_info["end"],
                    "size": range_info["size"],
                })
            )
        if residual.get("origin"):
            lines.append(f"  origin: {residual['origin']}")
        if residual.get("frame_growth_bytes") is not None:
            lines.append(f"  frame growth bytes: {residual['frame_growth_bytes']}")
        if residual.get("alignment_growth_bytes") is not None:
            lines.append(
                f"  alignment growth bytes: {residual['alignment_growth_bytes']}"
            )
    lines.append(f"  local target: {report['local_target']}")
    lines.append("")
    lines.append("=== SOURCE IDEAS (ADVISORY, not validated) ===")
    suggestions = report.get("suggestions") or []
    if suggestions:
        for suggestion in suggestions:
            lines.append(f"  {suggestion['rank']}. {suggestion['kind']}")
            lines.append(f"     {suggestion['description']}")
    else:
        lines.append("  (no frame source suggestions available)")
    lines.append("")
    lines.append("=== NEXT STEPS ===")
    for step in report.get("next_steps") or []:
        lines.append(f"  {step}")
    return "\n".join(lines)


@inspect_app.command("diff")
def diff(
    input_a: Annotated[
        str,
        typer.Argument(help="First source or pcdump file"),
    ],
    input_b: Annotated[
        str,
        typer.Argument(help="Second source or pcdump file"),
    ],
    function: Annotated[
        Optional[str],
        typer.Option(
            "--fn",
            "--function",
            "-f",
            help="Function to diff. Required for MVP.",
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            "-t",
            help="Per-source `debug dump local` timeout in seconds.",
        ),
    ] = 90,
    inspect_a: Annotated[
        Optional[Path],
        typer.Option(
            "--inspect-a",
            help="mwcc-inspect output for the first input. Requires --inspect-b.",
        ),
    ] = None,
    inspect_b: Annotated[
        Optional[Path],
        typer.Option(
            "--inspect-b",
            help="mwcc-inspect output for the second input. Requires --inspect-a.",
        ),
    ] = None,
    source_inspect: Annotated[
        bool,
        typer.Option(
            "--source-inspect",
            help=(
                "Also run tools/workflow/mwcc-inspect.sh for .c inputs. "
                "Default source mode is local pcdump-only."
            ),
        ),
    ] = False,
):
    """Compare two source or pcdump inputs through the mwcc-debug pipeline.

    Existing `.txt` inputs are treated as already-captured pcdumps. `.c`
    inputs are compiled with `debug dump local --no-cache-sync`, then the
    resulting pass snapshots are compared in pipeline order without running
    the heavier mwcc-inspect front-end workflow. Pass `--source-inspect` to
    run mwcc-inspect for `.c` inputs, or pass `--inspect-a/--inspect-b` to
    include pre-captured front-end snapshots in the same staged lowering
    report.
    """
    if function is None:
        typer.echo("--fn/--function is required for mwcc-debug diff MVP.", err=True)
        raise typer.Exit(2)
    if (inspect_a is None) != (inspect_b is None):
        typer.echo("--inspect-a and --inspect-b must be passed together.", err=True)
        raise typer.Exit(2)
    if inspect_a is not None and not inspect_a.is_file():
        typer.echo(f"--inspect-a not found: {inspect_a}", err=True)
        raise typer.Exit(2)
    if inspect_b is not None and not inspect_b.is_file():
        typer.echo(f"--inspect-b not found: {inspect_b}", err=True)
        raise typer.Exit(2)

    melee_root = DEFAULT_MELEE_ROOT
    try:
        resolved_a = resolve_diff_input("A", input_a, function=function, melee_root=melee_root)
        resolved_b = resolve_diff_input("B", input_b, function=function, melee_root=melee_root)
        text_a = read_or_compile_input(
            resolved_a,
            function=function,
            melee_root=melee_root,
            timeout=timeout,
        )
        text_b = read_or_compile_input(
            resolved_b,
            function=function,
            melee_root=melee_root,
            timeout=timeout,
        )
        if inspect_a is not None and inspect_b is not None:
            inspect_text_a = inspect_a.read_text(encoding="utf-8", errors="replace")
            inspect_text_b = inspect_b.read_text(encoding="utf-8", errors="replace")
        elif source_inspect:
            inspect_text_a = read_inspect_input_if_available(
                resolved_a,
                function=function,
                melee_root=melee_root,
                timeout=timeout,
            )
            inspect_text_b = read_inspect_input_if_available(
                resolved_b,
                function=function,
                melee_root=melee_root,
                timeout=timeout,
            )
        else:
            if resolved_a.kind == "source" or resolved_b.kind == "source":
                typer.echo(
                    "[mwcc-debug] source inputs are using local pcdump-only diff; "
                    "pass --source-inspect or --inspect-a/--inspect-b to include "
                    "mwcc-inspect front-end snapshots.",
                    err=True,
                )
            inspect_text_a = None
            inspect_text_b = None
        if (inspect_text_a is None) != (inspect_text_b is None):
            typer.echo(
                "[mwcc-debug] mwcc-inspect snapshot unavailable for one side; "
                "comparing backend pcdump passes only.",
                err=True,
            )
            inspect_text_a = None
            inspect_text_b = None
        report = compare_function_dumps(
            text_a,
            text_b,
            function=function,
            label_a=resolved_a.label if resolved_a.label != "A" else input_a,
            label_b=resolved_b.label if resolved_b.label != "B" else input_b,
            inspect_text_a=inspect_text_a,
            inspect_text_b=inspect_text_b,
        )
    except CompileFailure as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(e.returncode or 1)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2)

    typer.echo(render_text_report(report))


def _load_target_spec(path: Path) -> dict:
    """Load a target spec from YAML or JSON.

    Both are accepted; JSON is a strict subset so we can fall back to it
    when PyYAML isn't installed. The spec shape is documented in
    src/mwcc_debug/scoring.py.

    Validates the basic shape of the loaded spec and emits a helpful
    error if it's malformed.
    """
    if not path.exists():
        typer.echo(f"target spec file not found: {path}", err=True)
        typer.echo(
            "Generate one with `melee-agent debug target derive -f FN`.",
            err=True,
        )
        raise typer.Exit(2)
    text = path.read_text()
    try:
        if path.suffix in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
            except ImportError:
                typer.echo(
                    f"PyYAML not installed but target file {path.name} "
                    f"has YAML extension.\n"
                    f"Either `pip install PyYAML` or convert the file to "
                    f"JSON (use `debug target derive --format json` "
                    f"to regenerate).",
                    err=True,
                )
                raise typer.Exit(2)
            spec = yaml.safe_load(text)
        else:
            spec = json.loads(text)
    except json.JSONDecodeError as e:
        typer.echo(
            f"failed to parse {path} as JSON: {e}\n"
            f"Expected shape:\n"
            f'  {{ "function": "fn_name", "virtuals": {{"32": 26, ...}} }}',
            err=True,
        )
        raise typer.Exit(2)
    except Exception as e:
        typer.echo(f"failed to parse target spec {path}: {e}", err=True)
        raise typer.Exit(2)

    # Basic shape validation
    if not isinstance(spec, dict):
        typer.echo(
            f"target spec {path} must be an object/dict at top level, "
            f"got {type(spec).__name__}.",
            err=True,
        )
        raise typer.Exit(2)
    if "virtuals" not in spec:
        typer.echo(
            f"target spec {path} is missing the 'virtuals' key.\n"
            f"Expected shape:\n"
            f'  {{ "function": "fn_name", "virtuals": {{"32": 26, ...}} }}\n'
            f"Generate a valid one with `melee-agent debug target derive "
            f"-f FN`.",
            err=True,
        )
        raise typer.Exit(2)
    return spec


@target_app.command(name="score-dump")
def score(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to score (required)"),
    ],
    target: Annotated[
        Path,
        typer.Option(
            "--target", "-t",
            help="Target spec file (YAML or JSON, required). See "
                 "src/mwcc_debug/scoring.py for format.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    breakdown: Annotated[
        bool,
        typer.Option(
            "--breakdown",
            help="Print the score components in addition to the total.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit score as JSON."),
    ] = False,
) -> None:
    """Tier 4: score a pcdump's coloring decisions against a target spec.

    Lower scores are better (perfect match = 0). Designed to be called by
    decomp-permuter as a custom scorer.
    """
    pcdump = _resolve_pcdump_path(pcdump, function)
    text = pcdump.read_text()
    spec = _load_target_spec(target)
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])

    events_list = parse_hook_events(text)
    events = find_function(events_list, function)

    result = score_function(fn, spec, events=events)

    if json_out:
        print(json.dumps({
            "function": function,
            "score": result.total,
            "matched": result.matched,
            "targeted": result.targeted,
            "virtual_distance": result.virtual_distance,
            "spill_unexpected": result.spill_unexpected,
            "spill_missing": result.spill_missing,
            "interferer_distance": result.interferer_distance,
            "frame_targeted": result.frame_targeted,
            "frame_size_actual": result.frame_size_actual,
            "frame_size_target": result.frame_size_target,
            "frame_size_distance": result.frame_size_distance,
            "frame_unused_distance": result.frame_unused_distance,
            "frame_penalty": result.frame_penalty,
        }))
        return

    if breakdown:
        print(f"Function:           {function}")
        print(f"Score:              {result.total:.2f}")
        print(f"Matched:            {result.matched} / {result.targeted}")
        print(f"Virtual penalty:    {result.virtual_penalty:.2f} "
              f"({result.virtual_distance} wrong)")
        print(f"Spill penalty:      {result.spill_penalty:.2f} "
              f"(unexpected={len(result.spill_unexpected)} "
              f"missing={len(result.spill_missing)})")
        print(f"Interferer penalty: {result.interferer_penalty:.2f} "
              f"(sum |Δdeg| = {result.interferer_distance})")
        if result.frame_targeted:
            print(f"Frame penalty:      {result.frame_penalty:.2f} "
                  f"(size {result.frame_size_actual} → "
                  f"{result.frame_size_target}, "
                  f"unused-range Δ={result.frame_unused_distance})")
    else:
        print(f"{result.total:.2f}")


@target_app.command(name="dtk-objdump")
def target_dtk_objdump(
    o_file: Annotated[
        Path,
        typer.Argument(help="Object file to disassemble for decomp-permuter scoring."),
    ],
    melee_root: Annotated[
        Optional[Path],
        typer.Option(
            "--melee-root",
            help="Melee repo root containing build/tools/dtk. Auto-detected by default.",
        ),
    ] = None,
    object_root: Annotated[
        Optional[Path],
        typer.Option(
            "--object-root",
            help=(
                "Root used to resolve relative object paths appended by "
                "decomp-permuter, for example a remote decomp-permuter checkout."
            ),
        ),
    ] = None,
    name_magic: Annotated[
        bool,
        typer.Option(
            "--name-magic/--no-name-magic",
            help=(
                "Apply checkdiff-style anonymous @N relocation renames "
                "against the matching target.o before disassembly."
            ),
        ),
    ] = True,
) -> None:
    """Emit GNU objdump-shaped PPC disassembly using the project dtk binary."""
    from ..mwcc_debug.dtk_objdump import DtkObjdumpError, disassemble_object

    try:
        sys.stdout.write(disassemble_object(
            o_file,
            melee_root=melee_root,
            object_root=object_root,
            name_magic=name_magic,
        ))
    except DtkObjdumpError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


def _get_asm_hunks(
    function: str, melee_root: Path, top_n: int = 5,
) -> Optional[list[list[str]]]:
    """Run checkdiff in JSON mode and group its unified-diff lines into
    hunks of consecutive +/- changes. Each hunk gets a small context
    window around it for readability.

    Returns:
        list of hunks (each a list of lines), or None if checkdiff
        couldn't run / produce JSON / find a meaningful diff.

    The 'top N' selection is by hunk size — longest hunks first, since
    those tend to encode the most informative differences.
    """
    try:
        proc = subprocess.run(
            ["python", "tools/checkdiff.py", function,
             "--format", "json", "--no-build"],
            cwd=melee_root, capture_output=True, text=True, timeout=60,
            env=_checkdiff_env_without_fingerprint(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    # checkdiff returns 1 when there's a mismatch (expected for stuck fns)
    if proc.returncode not in (0, 1) or not proc.stdout:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    diff_lines = data.get("diff", [])
    if not diff_lines:
        return None

    # Group lines into hunks. A hunk = a span containing +/- lines with
    # up to 1 line of intermediate context. checkdiff produces unified-
    # diff format, so context lines start with ' ' and change lines
    # start with '+'/'-'. The first 3 lines are the file header.
    body = diff_lines[3:] if len(diff_lines) >= 3 else diff_lines
    hunks: list[list[str]] = []
    cur: list[str] = []
    blank_run = 0
    for line in body:
        if line.startswith("@@"):
            # objdiff hunk header — boundary
            if cur:
                hunks.append(cur)
                cur = []
            blank_run = 0
            continue
        if line.startswith("+") or line.startswith("-"):
            cur.append(line)
            blank_run = 0
        elif cur:
            # Context line inside a hunk — keep tightly bound (one line
            # of slack), then close on the next.
            cur.append(line)
            blank_run += 1
            if blank_run >= 2:
                hunks.append(cur[:-1])  # drop the trailing context lines
                cur = []
                blank_run = 0
    if cur:
        hunks.append(cur)

    if not hunks:
        return None
    # Score by number of change lines (longer = more interesting)
    def _score(h: list[str]) -> int:
        return sum(1 for l in h if l.startswith("+") or l.startswith("-"))
    hunks.sort(key=_score, reverse=True)
    return hunks[:top_n]


def _get_checkdiff_classification(
    function: str,
    melee_root: Path,
) -> dict | None:
    try:
        proc = subprocess.run(
            [
                "python",
                "tools/checkdiff.py",
                function,
                "--format",
                "json",
                "--no-build",
                "--no-name-magic",
                "--no-fingerprint",
            ],
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=60,
            env=_checkdiff_env_without_fingerprint(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1) or not proc.stdout:
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    classification = payload.get("classification")
    return classification if isinstance(classification, dict) else None


def _frame_residual_hint_from_checkdiff_classification(
    function: str,
    classification: dict | None,
    *,
    unit: str | None,
) -> dict | None:
    if not classification:
        return None
    primary = classification.get("primary")
    reasons = classification.get("reasons") or []
    reason_text = "\n".join(str(reason).lower() for reason in reasons)
    src_arg = f"src/{unit}.c" if unit else "<source.c>"

    if primary == "stack-layout" and (
        "frame reservation gap" in reason_text
        or "pad_stack" in reason_text
        or "frame size" in reason_text
    ):
        return {
            "kind": "frame-size",
            "origin": "checkdiff-classification",
            "subcategory": (
                "frame-too-small" if "too small" in reason_text
                else "frame-too-large" if "too large" in reason_text
                else "frame-size-delta"
            ),
            "message": (
                f"{function}: checkdiff reports a stack frame-size residual. "
                "Decl-order probes can move local slots but cannot change the "
                "reserved frame size, so prefer frame-reservation tools first."
            ),
            "summary": "frame-size residual from checkdiff classification",
            "next_steps": [
                f"melee-agent debug inspect frame-reservations -f {function}",
                f"melee-agent debug suggest frame -f {function}",
                (
                    f"melee-agent debug dump local {src_arg} -f {function} "
                    "--diff --force-frame-from-diff"
                ),
            ],
        }

    if primary == "stack-slot-layout":
        return {
            "kind": "same-frame-stack-slot-placement",
            "origin": "checkdiff-classification",
            "subcategory": "same-frame-stack-slot-placement",
            "message": (
                f"{function}: checkdiff reports same-frame stack-slot "
                "placement differences. Inspect the stack-home assignment "
                "order first, then use lifetime/layout probes; decl-order "
                "search is usually neutral on this class."
            ),
            "summary": "same-frame stack-slot residual from checkdiff classification",
            "next_steps": [
                f"melee-agent debug inspect frame-reservations -f {function}",
                (
                    f"melee-agent debug mutate lifetime-layout -f {function} "
                    "--compile-probes"
                ),
            ],
        }
    return None


def _format_asm_hunks(hunks: list[list[str]], max_lines_per_hunk: int = 12) -> str:
    """Render hunks compactly: cap each hunk at max_lines_per_hunk
    (with a '...(N more)' footer if truncated). Returns the formatted
    block, ready to print after a header.
    """
    out: list[str] = []
    for i, hunk in enumerate(hunks):
        if i > 0:
            out.append("  ---")
        n_show = min(len(hunk), max_lines_per_hunk)
        for line in hunk[:n_show]:
            out.append(f"  {line}")
        if len(hunk) > n_show:
            out.append(f"  ...({len(hunk) - n_show} more lines)")
    return "\n".join(out)


@inspect_app.command("asm")
def inspect_asm(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to disassemble"),
    ],
    no_build: Annotated[
        bool,
        typer.Option(
            "--no-build",
            help="Skip rebuilding and show the current compiled .o as-is.",
        ),
    ] = False,
    build_timeout: Annotated[
        float,
        typer.Option(
            "--build-timeout",
            help="Timeout in seconds for each checkdiff build/report step.",
        ),
    ] = 60.0,
) -> None:
    """Show the current compiled assembly for a function."""
    cmd = [
        "python",
        "tools/checkdiff.py",
        function,
        "--format",
        "json",
    ]
    if no_build:
        cmd.append("--no-build")
    else:
        cmd.extend(["--build-timeout", f"{build_timeout:g}"])

    proc = subprocess.run(
        cmd,
        cwd=DEFAULT_MELEE_ROOT,
        capture_output=True,
        text=True,
        env=_checkdiff_env_without_fingerprint(),
    )
    if proc.returncode not in (0, 1):
        if proc.stderr:
            typer.echo(proc.stderr.rstrip(), err=True)
        if proc.stdout:
            typer.echo(proc.stdout.rstrip(), err=True)
        raise typer.Exit(proc.returncode)

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        typer.echo(f"checkdiff did not emit JSON: {exc}", err=True)
        if proc.stderr:
            typer.echo(proc.stderr.rstrip(), err=True)
        raise typer.Exit(2)

    current_asm = payload.get("current_asm")
    if not isinstance(current_asm, list) or not all(
        isinstance(line, str) for line in current_asm
    ):
        typer.echo("checkdiff JSON did not include current_asm lines", err=True)
        raise typer.Exit(2)
    typer.echo("\n".join(current_asm))


def _read_frame_reservation_expected_asm(
    function: str,
    *,
    expected_asm: Optional[Path],
    no_expected: bool,
    melee_root: Path,
) -> str | None:
    if no_expected:
        return None
    if expected_asm is not None:
        if not expected_asm.exists():
            typer.echo(f"expected asm not found: {expected_asm}", err=True)
            raise typer.Exit(2)
        return expected_asm.read_text()

    asm_path = _tmp_asm_path_for_function(function)
    extract_cmd = [
        "melee-agent",
        "extract",
        "get",
        function,
        "--full",
        "--output",
        str(asm_path),
    ]
    proc = subprocess.run(
        extract_cmd,
        cwd=melee_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        typer.echo(proc.stderr or proc.stdout, err=True)
        raise typer.Exit(proc.returncode or 1)
    return asm_path.read_text()


def _read_frame_reservation_current_asm(
    function: str,
    *,
    melee_root: Path,
) -> str | None:
    proc = subprocess.run(
        [
            sys.executable,
            "tools/checkdiff.py",
            function,
            "--format",
            "json",
            "--no-build",
        ],
        cwd=melee_root,
        capture_output=True,
        text=True,
        env=_checkdiff_env_without_fingerprint(),
    )
    if proc.returncode not in (0, 1):
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    current_asm = payload.get("current_asm")
    if not isinstance(current_asm, list) or not all(
        isinstance(line, str) for line in current_asm
    ):
        return None
    return "\n".join(current_asm)


def _read_stack_home_probe_results_json(
    path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not path.exists():
        raise typer.BadParameter(f"probe results JSON not found: {path}")
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"invalid probe results JSON: {exc}") from exc
    metadata: dict[str, Any] = {}
    if isinstance(payload, list):
        variants = payload
    elif isinstance(payload, dict):
        variants = payload.get("variants")
        if variants is None:
            evaluation = payload.get("stack_home_probe_evaluation")
            if isinstance(evaluation, dict):
                variants = evaluation.get("variants")
        semantic_status = payload.get("semantic_lever_status")
        if not isinstance(semantic_status, Mapping):
            frame_report = payload.get("frame_report")
            if isinstance(frame_report, Mapping):
                semantic_status = frame_report.get("semantic_lever_status")
        if isinstance(semantic_status, Mapping):
            metadata["semantic_lever_status"] = dict(semantic_status)
    else:
        variants = None
    if not isinstance(variants, list):
        raise typer.BadParameter(
            "probe results JSON must be a variants array or an object with variants"
        )
    return [
        dict(item) for item in variants
        if isinstance(item, Mapping)
    ], metadata


def _frame_spec_from_checkdiff_target(checkdiff_json: Path) -> dict:
    if not checkdiff_json.exists():
        raise typer.BadParameter(
            f"checkdiff JSON not found: {checkdiff_json}"
        )
    try:
        payload = json.loads(checkdiff_json.read_text())
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"checkdiff JSON could not be parsed: {exc}"
        ) from exc
    except OSError as exc:
        raise typer.BadParameter(
            f"checkdiff JSON could not be read: {exc}"
        ) from exc

    target_asm = payload.get("target_asm") or payload.get("reference_asm")
    if not isinstance(target_asm, list) or not all(
        isinstance(line, str) for line in target_asm
    ):
        raise typer.BadParameter(
            "checkdiff JSON must contain target_asm or reference_asm lines"
        )

    frame = analyze_frame_from_asm_text("\n".join(target_asm))
    if frame.get("frame_size") is None:
        raise typer.BadParameter(
            "checkdiff target asm did not contain a stack-frame allocation"
        )
    return {
        "frame_size": frame["frame_size"],
        "access_ranges": frame.get("access_ranges", []),
        "unused_ranges": frame.get("unused_ranges", []),
        "symbolic_home_map": frame.get("symbolic_home_map", []),
    }


def _pcdump_has_symbolic_stack_homes(pcdump_text: str) -> bool:
    return bool(re.search(
        r"(?<![@\w])(?:@[A-Za-z0-9_]\w*|[A-Za-z_]\w*)"
        r"(?:[+-](?:0x[0-9A-Fa-f]+|\d+))?\s*\(\s*r1\s*\)",
        pcdump_text,
    ))


def _format_stack_range(item: Mapping[str, object]) -> str:
    start = int(item["start"])
    end = int(item["end"])
    size = int(item["size"])
    return f"0x{start:x}-0x{end:x} ({size} bytes)"


def _print_unused_ranges(label: str, ranges: list[dict]) -> None:
    print(f"{label} unused ranges:")
    if not ranges:
        print("  none")
        return
    for item in ranges:
        print(f"  {_format_stack_range(item)}")


def _print_stack_home_order_summary(current: Mapping[str, object]) -> None:
    summary = current.get("stack_home_order_summary")
    if not isinstance(summary, Mapping) or summary.get("status") != "computed":
        return
    assignments = summary.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        return
    status = "mismatch" if summary.get("has_order_mismatch") else "matches offsets"
    print()
    print(f"stack-home assignment order: {status}")
    print(
        "assignments: "
        f"{summary.get('assignment_count')}, "
        f"max order delta: {summary.get('max_abs_order_delta')}"
    )
    ranked = sorted(
        (item for item in assignments if isinstance(item, Mapping)),
        key=lambda item: (
            abs(int(item.get("order_delta") or 0)),
            -int(item.get("assignment_order") or 0),
        ),
        reverse=True,
    )
    for item in ranked[:5]:
        delta = int(item.get("order_delta") or 0)
        sign = "+" if delta > 0 else ""
        offset = item.get("offset")
        offset_text = "?" if offset is None else f"0x{int(offset):x}"
        print(
            f"  {item.get('symbol')}: "
            f"assign #{item.get('assignment_order')}, "
            f"offset #{item.get('offset_order')}, "
            f"delta {sign}{delta}, "
            f"offset {offset_text}"
        )
    expected_summary = current.get("stack_home_expected_order_summary")
    if (
        isinstance(expected_summary, Mapping)
        and expected_summary.get("status") == "computed"
    ):
        expected_assignments = expected_summary.get("assignments")
        if isinstance(expected_assignments, list) and expected_assignments:
            target_status = (
                "mismatch"
                if expected_summary.get("has_expected_offset_mismatch")
                else "matches target"
            )
            print(f"target stack-home offsets: {target_status}")
            print(
                "target assignments: "
                f"{expected_summary.get('assignment_count')}, "
                "max target order delta: "
                f"{expected_summary.get('max_abs_expected_order_delta')}, "
                "max offset delta: "
                f"{expected_summary.get('max_abs_offset_delta')}"
            )
            target_ranked = sorted(
                (
                    item for item in expected_assignments
                    if isinstance(item, Mapping)
                ),
                key=lambda item: (
                    abs(int(item.get("offset_delta") or 0)),
                    abs(int(item.get("expected_order_delta") or 0)),
                    -int(item.get("assignment_order") or 0),
                ),
                reverse=True,
            )
            for item in target_ranked[:5]:
                offset_delta = int(item.get("offset_delta") or 0)
                order_delta = int(item.get("expected_order_delta") or 0)
                offset_sign = "+" if offset_delta > 0 else ""
                order_sign = "+" if order_delta > 0 else ""
                current_offset = item.get("offset")
                expected_offset = item.get("expected_offset")
                current_text = (
                    "?" if current_offset is None else f"0x{int(current_offset):x}"
                )
                expected_text = (
                    "?" if expected_offset is None else f"0x{int(expected_offset):x}"
                )
                print(
                    f"  {item.get('symbol')}: "
                    f"assign #{item.get('assignment_order')}, "
                    f"target offset #{item.get('expected_offset_order')}, "
                    f"target order delta {order_sign}{order_delta}, "
                    f"offset {current_text} -> {expected_text} "
                    f"({offset_sign}{offset_delta})"
                )
            permutation = current.get("stack_home_target_permutation")
            if (
                isinstance(permutation, Mapping)
                and permutation.get("status") == "computed"
                and permutation.get("needs_permutation")
            ):
                current_order = permutation.get("current_offset_order")
                expected_order = permutation.get("expected_offset_order")
                if isinstance(current_order, list) and isinstance(expected_order, list):
                    print(
                        "target permutation: "
                        f"{', '.join(str(item) for item in current_order)} -> "
                        f"{', '.join(str(item) for item in expected_order)}"
                    )
                cycles = permutation.get("cycles")
                if isinstance(cycles, list):
                    for cycle in cycles[:3]:
                        if not isinstance(cycle, Mapping):
                            continue
                        symbols = cycle.get("symbols")
                        if isinstance(symbols, list) and symbols:
                            print(
                                "  cycle: "
                                + " -> ".join(str(symbol) for symbol in symbols)
                            )
    guidance = current.get("stack_home_reorder_guidance")
    if not isinstance(guidance, Mapping):
        return
    verdict = guidance.get("verdict")
    if verdict:
        print(f"reorder verdict: {verdict}")
    validated_verdict = guidance.get("validated_verdict")
    if isinstance(validated_verdict, Mapping) and validated_verdict.get("status"):
        print(
            "validated reorder verdict: "
            f"{validated_verdict.get('status')} - "
            f"{validated_verdict.get('reason')}"
        )
    probe_plan = guidance.get("probe_plan")
    if isinstance(probe_plan, Mapping):
        operators = probe_plan.get("operator_priority")
        if isinstance(operators, list) and operators:
            print(
                "probe operators: "
                + ", ".join(str(operator) for operator in operators)
            )
        commands = probe_plan.get("suggested_commands")
        if isinstance(commands, list):
            for command_item in commands:
                if not isinstance(command_item, Mapping):
                    continue
                command = command_item.get("command")
                if command:
                    print(f"next probe: {command}")
                    break
    levers = guidance.get("candidate_levers")
    if isinstance(levers, list) and levers:
        kinds = [
            str(item.get("kind"))
            for item in levers
            if isinstance(item, Mapping) and item.get("kind")
        ]
        if kinds:
            print(f"candidate reorder levers: {', '.join(kinds)}")


def _print_frame_reservation_report(report: dict) -> None:
    print(report["summary"])
    current = report["current"]
    expected = report.get("expected")
    print(f"current frame: {current.get('frame_size')}")
    if expected is not None:
        print(f"expected frame: {expected.get('frame_size')}")
        print(f"frame delta: {report.get('frame_delta')}")
    timeline = report.get("pass_frame_timeline")
    if isinstance(timeline, Mapping):
        print(f"frame pass timeline: {timeline.get('pass_count')} pass(es)")
        first_change = timeline.get("first_change")
        if isinstance(first_change, Mapping):
            status = first_change.get("status")
            if status == "changed":
                print(
                    "first frame-model change: "
                    f"{first_change.get('previous_pass')} -> "
                    f"{first_change.get('pass')} "
                    f"({first_change.get('reason')})"
                )
            elif status:
                print(f"first frame-model change: {status}")
    _print_frame_allocation_trace_summary(current.get("frame_allocation_trace"))
    _print_unused_ranges("current", current.get("unused_ranges", []))
    if expected is not None:
        _print_unused_ranges("expected", expected.get("unused_ranges", []))
    _print_stack_home_order_summary(current)
    probe_evaluation = report.get("stack_home_probe_evaluation")
    if isinstance(probe_evaluation, Mapping):
        print()
        print(f"stack-home probe verdict: {probe_evaluation.get('verdict')}")
        stop_condition = probe_evaluation.get("stop_condition")
        if isinstance(stop_condition, Mapping):
            print(
                "stop condition: "
                f"{stop_condition.get('status')} "
                f"({stop_condition.get('kind')})"
            )
        best = probe_evaluation.get("best_variant")
        if isinstance(best, Mapping):
            print(
                "best probe: "
                f"{best.get('label')} [{best.get('operator')}] "
                f"fixed {best.get('fixed_count')}/{best.get('target_count')}"
            )
    frame_evaluation = report.get("frame_transform_probe_evaluation")
    if isinstance(frame_evaluation, Mapping):
        print()
        print(f"frame-transform probe verdict: {frame_evaluation.get('verdict')}")
        stop_condition = frame_evaluation.get("stop_condition")
        if isinstance(stop_condition, Mapping):
            print(
                "frame stop condition: "
                f"{stop_condition.get('status')} "
                f"({stop_condition.get('kind')})"
            )
        best = frame_evaluation.get("best_variant")
        if isinstance(best, Mapping):
            print(
                "best frame probe: "
                f"{best.get('label')} [{best.get('operator')}] "
                f"frame={best.get('candidate_frame_size')} "
                f"remaining_delta={best.get('remaining_frame_delta')}"
            )

    first_divergence = report.get("frame_first_divergence")
    if first_divergence:
        print()
        print(f"first frame divergence: {first_divergence.get('status')}")
        reason = first_divergence.get("reason")
        if reason:
            print(f"reason: {reason}")
        cause = first_divergence.get("cause_hypothesis") or {}
        if isinstance(cause, Mapping) and cause.get("kind"):
            confidence = cause.get("confidence")
            suffix = f" ({confidence})" if confidence else ""
            print(f"cause: {cause.get('kind')}{suffix}")
        attribution = first_divergence.get("source_attribution")
        if isinstance(attribution, Mapping):
            primary = attribution.get("primary_source_object")
            if isinstance(primary, Mapping) and primary.get("symbol"):
                current_offset = primary.get("current_offset")
                expected_offset = primary.get("expected_offset")
                current_text = (
                    "?" if current_offset is None else f"0x{int(current_offset):x}"
                )
                expected_text = (
                    "?" if expected_offset is None else f"0x{int(expected_offset):x}"
                )
                print(
                    "source object: "
                    f"{primary.get('symbol')} "
                    f"({attribution.get('confidence')}, "
                    f"{primary.get('kind')}, "
                    f"{current_text}->{expected_text})"
                )
            elif attribution.get("status"):
                print(
                    "source object: "
                    f"{attribution.get('status')} "
                    f"({attribution.get('unresolved_dependency')})"
                )
        probe_plan = first_divergence.get("frame_transform_probe_plan") or {}
        if isinstance(probe_plan, Mapping):
            operators = [
                str(operator)
                for operator in probe_plan.get("operator_priority") or []
                if operator
            ]
            if operators:
                print(f"frame probe operators: {', '.join(operators)}")
            commands = probe_plan.get("suggested_commands") or []
            first_command = next(
                (
                    item.get("command")
                    for item in commands
                    if isinstance(item, Mapping)
                    and isinstance(item.get("command"), str)
                ),
                None,
            )
            if first_command:
                print(f"next frame probe: {first_command}")
        current_obj = first_divergence.get("current")
        expected_obj = first_divergence.get("expected")
        if current_obj:
            print(
                "current object: "
                f"{current_obj.get('kind')} "
                f"{_format_stack_range(current_obj)}"
            )
        if expected_obj:
            print(
                "expected object: "
                f"{expected_obj.get('kind')} "
                f"{_format_stack_range(expected_obj)}"
            )
        verdict = first_divergence.get("verdict") or {}
        if verdict.get("status"):
            print(f"verdict: {verdict.get('status')} - {verdict.get('reason')}")
        validated_verdict = first_divergence.get("validated_verdict") or {}
        if validated_verdict.get("status"):
            print(
                "validated verdict: "
                f"{validated_verdict.get('status')} - "
                f"{validated_verdict.get('reason')}"
            )

    current_low = report.get("current_low_frame_expansion")
    if current_low is not None:
        print()
        print(f"current low-frame expansion: {_format_stack_range(current_low)}")
        print(f"origin: {current_low.get('origin')}")
        print(f"frame growth bytes: {current_low.get('frame_growth_bytes')}")
        print(f"alignment growth bytes: {current_low.get('alignment_growth_bytes')}")
        accesses = current_low.get("current_accesses_in_range") or []
        if not accesses:
            print("current non-save stack accesses in range: none")
        else:
            print("current non-save stack accesses in range:")
            for access in accesses:
                print(
                    f"  {access.get('opcode')} {access.get('operands')} "
                    f"at 0x{int(access['offset']):x} "
                    f"({access.get('kind')})"
                )

    extra = report.get("extra_low_frame_reservation")
    if extra is None:
        return
    print()
    print(f"extra low-frame reservation: {_format_stack_range(extra)}")
    print(f"origin: {extra.get('origin')}")
    accesses = extra.get("current_accesses_in_range") or []
    if not accesses:
        print("current non-save stack accesses in range: none")
        return
    print("current non-save stack accesses in range:")
    for access in accesses:
        print(
            f"  {access.get('opcode')} {access.get('operands')} "
            f"at 0x{int(access['offset']):x} "
            f"({access.get('kind')})"
        )


def _print_frame_allocation_trace_summary(trace: object) -> None:
    if not isinstance(trace, Mapping):
        return
    status = trace.get("status")
    object_count = trace.get("object_count")
    count_text = (
        f" ({object_count} object(s))"
        if isinstance(object_count, int)
        else ""
    )
    print(f"frame allocation trace: {status}{count_text}")
    allocator_status = trace.get("allocator_pass_status")
    if allocator_status:
        print(f"allocator pass: {allocator_status}")
    validation = trace.get("validation")
    if isinstance(validation, Mapping):
        frame_status = (
            "ok" if validation.get("frame_size_matches") is True else "mismatch"
        )
        full_layout_status = (
            "ok"
            if validation.get("full_interval_coverage_matches") is True
            else "mismatch"
        )
        non_overlap_status = (
            "ok"
            if validation.get("object_non_overlap_matches") is True
            else "mismatch"
        )
        access_status = (
            "ok"
            if validation.get("r1_access_coverage_matches") is True
            else "mismatch"
        )
        print(
            "frame allocation validation: "
            f"frame-size {frame_status}, full-layout {full_layout_status}, "
            f"non-overlap {non_overlap_status}, "
            f"r1-access coverage {access_status}"
        )
    objects = trace.get("objects")
    if not isinstance(objects, list):
        return
    for obj in objects[:6]:
        if not isinstance(obj, Mapping):
            continue
        layout_order = obj.get("layout_order")
        origin_tag = obj.get("origin_tag")
        label = obj.get("symbol") or obj.get("kind")
        print(
            f"  #{layout_order} {origin_tag} "
            f"{_format_stack_range(obj)} {label}"
        )


@inspect_app.command(name="frame-reservations")
def frame_reservations(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to inspect"),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    expected_asm: Annotated[
        Optional[Path],
        typer.Option(
            "--expected-asm",
            help="Path to expected target asm. Omit to extract via "
                 "`melee-agent extract get <function> --full`.",
        ),
    ] = None,
    no_expected: Annotated[
        bool,
        typer.Option(
            "--no-expected",
            help="Inspect only the current pcdump without extracting target asm.",
        ),
    ] = False,
    probe_results_json: Annotated[
        Optional[Path],
        typer.Option(
            "--probe-results-json",
            help=(
                "Path to lifetime-layout --json output or a variants array. "
                "Attaches stack-home and frame-transform validation."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit the report as JSON."),
    ] = False,
) -> None:
    """Inspect stack-frame gaps and implicit reserved ranges."""
    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    pcdump_text = pcdump_path.read_text()
    expected_text = _read_frame_reservation_expected_asm(
        function,
        expected_asm=expected_asm,
        no_expected=no_expected,
        melee_root=melee_root,
    )
    current_text = (
        _read_frame_reservation_current_asm(function, melee_root=melee_root)
        if _pcdump_has_symbolic_stack_homes(pcdump_text)
        else None
    )
    try:
        report = analyze_frame_reservations(
            pcdump_text,
            function,
            expected_asm_text=expected_text,
            current_asm_text=current_text,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    if probe_results_json is not None:
        variants, probe_metadata = _read_stack_home_probe_results_json(
            probe_results_json
        )
        semantic_status = probe_metadata.get("semantic_lever_status")
        if isinstance(semantic_status, Mapping):
            report["semantic_lever_status"] = dict(semantic_status)
        report["stack_home_probe_evaluation"] = evaluate_stack_home_probe_results(
            report,
            variants,
        )
        _attach_stack_home_validated_verdict(report)
        report["frame_transform_probe_evaluation"] = (
            evaluate_frame_transform_probe_results(report, variants)
        )
        _attach_frame_transform_validated_verdict(report)

    if json_out:
        print(json.dumps(report, indent=2))
        return
    _print_frame_reservation_report(report)


def _attach_stack_home_validated_verdict(report: dict) -> None:
    current = report.get("current")
    evaluation = report.get("stack_home_probe_evaluation")
    if not isinstance(current, dict) or not isinstance(evaluation, Mapping):
        return
    guidance = current.get("stack_home_reorder_guidance")
    if not isinstance(guidance, dict):
        return
    verdict = evaluation.get("verdict")
    stop_condition = evaluation.get("stop_condition")
    if verdict == "source-reachable-reorder":
        guidance["validated_verdict"] = {
            "status": "source-reachable-reorder",
            "confidence": "high",
            "probe_verdict": verdict,
            "reason": (
                "stack-home probe evidence validates a source-reachable reorder"
            ),
            "stop_condition": stop_condition,
        }
    elif verdict == "partial-source-reachable-reorder":
        guidance["validated_verdict"] = {
            "status": "partial-source-reachable-reorder",
            "confidence": "medium",
            "probe_verdict": verdict,
            "reason": (
                "stack-home probe evidence partially reorders target homes"
            ),
            "stop_condition": stop_condition,
        }
    elif verdict == "internal-tiebreak-ceiling-candidate":
        guidance["validated_verdict"] = {
            "status": "internal-tiebreak-ceiling-candidate",
            "confidence": "medium",
            "probe_verdict": verdict,
            "reason": (
                "bounded stack-home reorder probes left target placement unchanged"
            ),
            "stop_condition": stop_condition,
        }


def _attach_frame_transform_validated_verdict(report: dict) -> None:
    first_divergence = report.get("frame_first_divergence")
    evaluation = report.get("frame_transform_probe_evaluation")
    if not isinstance(first_divergence, dict) or not isinstance(evaluation, Mapping):
        return
    verdict = evaluation.get("verdict")
    stop_condition = evaluation.get("stop_condition")
    if verdict == "source-reachable-frame-transform":
        first_divergence["validated_verdict"] = {
            "status": "source-reachable-validated",
            "confidence": "high",
            "probe_verdict": verdict,
            "reason": (
                "frame transform probe evidence validates a source-reachable "
                "change for the first frame divergence"
            ),
            "stop_condition": stop_condition,
        }
    elif verdict == "partial-source-reachable-frame-transform":
        first_divergence["validated_verdict"] = {
            "status": "partial-source-reachable-validated",
            "confidence": "medium",
            "probe_verdict": verdict,
            "reason": (
                "frame transform probe evidence partially reduces the first "
                "frame divergence"
            ),
            "stop_condition": stop_condition,
        }
    elif verdict == "frame-transform-ceiling-candidate":
        attribution = first_divergence.get("source_attribution")
        source_object = (
            attribution.get("primary_source_object")
            if isinstance(attribution, Mapping)
            else None
        )
        if isinstance(source_object, Mapping) and source_object.get("symbol"):
            first_divergence["validated_verdict"] = {
                "status": "attributed-frame-unchanged",
                "confidence": "medium",
                "probe_verdict": verdict,
                "reason": (
                    "bounded frame-size transform probes left the frame delta "
                    "unchanged for an attributed source-object divergence"
                ),
                "source_object_symbol": source_object.get("symbol"),
                "stop_condition": stop_condition,
            }
        else:
            unresolved_dependency = (
                attribution.get("unresolved_dependency")
                if isinstance(attribution, Mapping)
                else "mwcc-stack-home-origin-tags"
            )
            first_divergence["validated_verdict"] = {
                "status": "internal-tiebreak-ceiling",
                "confidence": "medium",
                "probe_verdict": verdict,
                "reason": (
                    "bounded frame transform probes left an unattributed "
                    "divergence unchanged; likely compiler-internal layout "
                    "tiebreak or missing stack-home origin instrumentation"
                ),
                "unresolved_dependency": unresolved_dependency,
                "stop_condition": stop_condition,
            }


def _frame_residual_hint_from_report(
    report: dict,
    *,
    unit: str | None = None,
) -> dict | None:
    """Return next-step guidance for frame-only/local-area residuals."""
    function = report.get("function")
    if not function:
        return None
    low_expansion = report.get("current_low_frame_expansion")
    extra_reservation = report.get("extra_low_frame_reservation")
    residual = None
    if isinstance(low_expansion, dict):
        residual = low_expansion
    elif isinstance(extra_reservation, dict):
        residual = extra_reservation
    if residual is None:
        return None
    if residual.get("current_accesses_in_range"):
        return None

    summary = report.get("summary") or (
        f"{function}: frame/local-area reservation differs from target"
    )
    src_arg = f"src/{unit}.c" if unit else "<source.c>"
    message = (
        f"{summary}; this residual is frame/local-area, not register "
        "allocation. Prefer frame-reservation inspection or a frame patch "
        "before register allocator tools."
    )
    return {
        "kind": "frame-local-area",
        "message": message,
        "summary": summary,
        "next_steps": [
            f"melee-agent debug inspect frame-reservations -f {function}",
            (
                f"melee-agent debug dump local {src_arg} -f {function} "
                "--diff --force-frame-from-diff"
            ),
        ],
    }


def _detect_frame_residual_hint(
    function: str,
    *,
    unit: str | None,
    melee_root: Path,
    pcdump_path: Path,
) -> dict | None:
    try:
        pcdump_text = pcdump_path.read_text()
        expected_text = _read_frame_reservation_expected_asm(
            function,
            expected_asm=None,
            no_expected=False,
            melee_root=melee_root,
        )
        current_text = (
            _read_frame_reservation_current_asm(function, melee_root=melee_root)
            if _pcdump_has_symbolic_stack_homes(pcdump_text)
            else None
        )
        report = analyze_frame_reservations(
            pcdump_text,
            function,
            expected_asm_text=expected_text,
            current_asm_text=current_text,
        )
    except Exception:
        return None
    return _frame_residual_hint_from_report(report, unit=unit)


def _frame_source_suggestions_from_report(
    report: dict,
    *,
    unit: str | None = None,
) -> list[dict]:
    function = report.get("function") or "<function>"
    src_rel = f"src/{unit}.c" if unit else "<source.c>"
    frame_target = f"{function}.frame-target.json"
    checkdiff_target = f"{function}.checkdiff.json"
    suggestions: list[dict] = []

    current_low = report.get("current_low_frame_expansion")
    if isinstance(current_low, dict):
        range_text = _format_stack_range(current_low)
        commands = [
            (
                f"python tools/checkdiff.py {function} --format json "
                f"--no-build > {checkdiff_target}"
            ),
            (
                f"melee-agent debug target derive -f {function} "
                f"--frame-from-checkdiff {checkdiff_target} --format json "
                f"> {frame_target}"
            ),
            (
                f"melee-agent debug target score-source {src_rel} "
                f"-f {function} --target {frame_target}"
            ),
            (
                f"melee-agent debug dump local {src_rel} -f {function} "
                "--diff --force-frame-from-diff"
            ),
        ]
        suggestions.append({
            "rank": 1,
            "kind": "suppress-unused-local-home",
            "origin": current_low.get("origin"),
            "range": {
                "start": current_low.get("start"),
                "end": current_low.get("end"),
                "size": current_low.get("size"),
            },
            "description": (
                f"Current source reserves an unused low local home at "
                f"{range_text}. For gm_801A9DD0-style cases this commonly "
                "comes from a held FP constant whose mutable local form gets "
                "a DLOCAL stack home. Try source shapes that keep the held FP "
                "constant live without a named mutable local home: split the "
                "constant lifetime, use direct literal/global expression at "
                "the final FP call, or compare against a matched sibling with "
                "the same SetNear/SetFar idiom."
            ),
            "commands": commands,
            "score_target": {
                "frame_size": report.get("expected", {}).get("frame_size")
                if isinstance(report.get("expected"), dict) else None,
                "score_command": commands[1],
            },
        })
        if current_low.get("alignment_growth_bytes"):
            suggestions.append({
                "rank": 2,
                "kind": "reduce-alignment-growth",
                "origin": current_low.get("origin"),
                "description": (
                    "The unused low home also changes the next 8-byte-aligned "
                    "scratch slot. Probe source variants that move int-to-float "
                    "magic-double scratch lifetimes away from the held FP "
                    "constant, then rank them with the frame target scorer."
                ),
                "commands": [commands[1]],
            })

    extra = report.get("extra_low_frame_reservation")
    if isinstance(extra, dict):
        commands = [
            (
                f"melee-agent debug target score-source {src_rel} "
                f"-f {function} --target {frame_target}"
            ),
            (
                f"melee-agent debug mutate lifetime-layout -f {function} "
                f"--frame-reservation-bytes {extra.get('size')}"
            ),
        ]
        suggestions.append({
            "rank": len(suggestions) + 1,
            "kind": "add-low-frame-reservation",
            "origin": extra.get("origin"),
            "range": {
                "start": extra.get("start"),
                "end": extra.get("end"),
                "size": extra.get("size"),
            },
            "description": (
                "The target reserves low-frame bytes before the first current "
                "callee/local stack access. Try explicit reservation probes or "
                "source lifetime changes that introduce a natural low local."
            ),
            "commands": commands,
        })

    if not suggestions:
        suggestions.append({
            "rank": 1,
            "kind": "derive-frame-target",
            "origin": "frame-size",
            "description": (
                "No unused-home signature was detected. Derive a frame target "
                "from checkdiff's expected/reference asm and use score-source to rank "
                "source candidates by frame-size and unused-range distance."
            ),
            "commands": [
                (
                    f"python tools/checkdiff.py {function} --format json "
                    f"--no-build > {checkdiff_target}"
                ),
                (
                    f"melee-agent debug target derive -f {function} "
                    f"--frame-from-checkdiff {checkdiff_target} "
                    f"--format json > {frame_target}"
                ),
                (
                    f"melee-agent debug target score-source {src_rel} "
                    f"-f {function} --target {frame_target}"
                ),
            ],
        })
    return suggestions


def _print_frame_suggestions(report: dict, suggestions: list[dict]) -> None:
    print(report["summary"])
    print()
    print("Frame source suggestions:")
    for suggestion in suggestions:
        print(f"{suggestion['rank']}. {suggestion['kind']}")
        print(f"   {suggestion['description']}")
        commands = suggestion.get("commands") or []
        if commands:
            print("   Commands:")
            for command in commands:
                print(f"     {command}")


@suggest_app.command(name="frame")
def suggest_frame_cmd(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to inspect"),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function.",
        ),
    ] = None,
    expected_asm: Annotated[
        Optional[Path],
        typer.Option(
            "--expected-asm",
            help="Expected target asm. Omit to extract via `extract get --full`.",
        ),
    ] = None,
    no_expected: Annotated[
        bool,
        typer.Option(
            "--no-expected",
            help="Do not compare against target asm; emit generic frame levers.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Suggest source/probe levers for stack-frame/local-area residuals."""
    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    pcdump_text = pcdump_path.read_text()
    expected_text = _read_frame_reservation_expected_asm(
        function,
        expected_asm=expected_asm,
        no_expected=no_expected,
        melee_root=melee_root,
    )
    current_text = (
        _read_frame_reservation_current_asm(function, melee_root=melee_root)
        if _pcdump_has_symbolic_stack_homes(pcdump_text)
        else None
    )
    try:
        report = analyze_frame_reservations(
            pcdump_text,
            function,
            expected_asm_text=expected_text,
            current_asm_text=current_text,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    unit = _find_unit_for_function(function, melee_root)
    suggestions = _frame_source_suggestions_from_report(report, unit=unit)
    if json_out:
        print(json.dumps({
            "function": function,
            "frame": report,
            "suggestions": suggestions,
        }, indent=2))
        return
    _print_frame_suggestions(report, suggestions)


@inspect_app.command("guide")
def guide(
    function: Annotated[
        str,
        typer.Option("--function", "-f",
                     help="Function name to analyze (required)"),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Target spec file (YAML or JSON). If omitted, all virtuals "
                 "currently mapped to non-target physicals are shown.",
        ),
    ] = None,
    asm_hunks: Annotated[
        int,
        typer.Option(
            "--asm-hunks",
            help="Also show the top N asm-diff hunks from checkdiff. "
                 "0 (default) omits. Useful when an allocator suggestion "
                 "is hard to interpret without seeing the actual text-"
                 "level diff (e.g. unexpected clrlwi from a missing "
                 "cast). Caps each hunk at ~12 lines for readability.",
        ),
    ] = 0,
) -> None:
    """Tier 4: human-readable diagnostic for stuck-function debugging.

    Reports which virtuals are at the wrong physical, why (interference,
    spill, iteration order), and suggests directions for C-source nudges.
    Hints, not guarantees — interpret in source context.

    Pass --asm-hunks N to also dump the top N asm-diff hunks from
    checkdiff. Saves switching tools when allocator-only analysis
    doesn't explain the mismatch (e.g. text diffs from a stray cast).
    """
    pcdump = _resolve_pcdump_path(pcdump, function)
    text = pcdump.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])

    events_list = parse_hook_events(text)
    events = find_function(events_list, function)

    if target is None:
        # No target — score against an empty target spec, just to surface
        # SPILLED markers and other red flags.
        spec: dict = {"virtuals": {}}
    else:
        spec = _load_target_spec(target)

    result = score_function(fn, spec, events=events)
    suggestions = suggest(fn, result, events=events)

    print(f"Function: {function}")
    print(f"Targeted virtuals: {result.targeted}")
    print(f"  Matched: {result.matched}")
    print(f"  Wrong:   {result.virtual_distance}")
    if result.spill_unexpected:
        print(f"  Unexpected SPILLED: r{', r'.join(str(v) for v in result.spill_unexpected)}")
    if result.spill_missing:
        print(f"  Expected-but-missing SPILLED: r{', r'.join(str(v) for v in result.spill_missing)}")
    print()
    no_target = target is None and result.targeted == 0
    target_matches_current = (
        target is not None
        and result.targeted > 0
        and result.virtual_distance == 0
        and not result.spill_unexpected
        and not result.spill_missing
    )
    if no_target:
        print(
            "No target spec was provided, so this guide cannot determine whether "
            "the current coloring matches a reference or forced allocation."
        )
        print(
            "Actionable flow: "
            "pass a reference/forced target spec with --target, or first run "
            f"`melee-agent debug inspect diagnose {function}` to test whether "
            "force-phys can reach a useful target."
        )
        print(
            "Do not derive a target from this same current pcdump as the "
            "next step; that only captures the current allocation and usually "
            "produces no diagnostic signal."
        )
        print()
    elif target_matches_current:
        print(
            "Target spec currently matches this pcdump. If the function is "
            "still nonmatching, this target was probably derived from the "
            "current source rather than from reference or a forced-allocation "
            "probe."
        )
        print(
            "Pass a reference/forced target spec before using guide output to "
            "diagnose allocator mismatch."
        )
        print()
    print("Suggestions (highest severity first):")
    if no_target and not suggestions:
        print("No allocator issues can be ranked without a target spec.")
    else:
        print(format_suggestions(suggestions))

    if asm_hunks > 0:
        print()
        hunks = _get_asm_hunks(function, DEFAULT_MELEE_ROOT, top_n=asm_hunks)
        if hunks is None:
            print(f"== asm hunks ==")
            print("  (checkdiff didn't produce a diff — either the .o "
                  "isn't built yet, the function matches, or checkdiff "
                  "errored. Run `tools/checkdiff.py {fn}` for details.)"
                  .replace("{fn}", function))
        elif not hunks:
            print(f"== asm hunks ==")
            print("  (no diff)")
        else:
            print(f"== top {len(hunks)} asm hunks (by diff size) ==")
            print(_format_asm_hunks(hunks))


@target_app.command(name="derive")
def derive_target(
    function: Annotated[
        str,
        typer.Option("--function", "-f",
                     help="Function name to extract (required)"),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Output format: yaml (default) or json.",
            click_type=typer.Choice(["yaml", "json"], case_sensitive=False)
            if False  # typer.Choice not available pre-0.12; fall back to str
            else None,
        ),
    ] = "yaml",
    force_phys_safe: Annotated[
        bool,
        typer.Option(
            "--force-phys-safe",
            help="Build `virtuals` from the raw COLORGRAPH DECISIONS (the "
                 "representation the first-divergence analyzer consumes) instead "
                 "of the analyze_function reconstruction. Excludes r0, spilled "
                 "nodes, and coalesced aliases, so the map round-trips cleanly as "
                 "a same-source force-phys target. Scope with --class.",
        ),
    ] = False,
    frame_from_checkdiff: Annotated[
        Optional[Path],
        typer.Option(
            "--frame-from-checkdiff",
            help=(
                "Override the frame target with target_asm/reference_asm from "
                "a `tools/checkdiff.py <function> --format json` payload. "
                "Use this when the current pcdump frame differs from the "
                "expected object frame."
            ),
        ),
    ] = None,
    class_id: Annotated[
        int,
        typer.Option("--class", help="Register class for --force-phys-safe "
                                     "(0=GPR, 1=FPR)."),
    ] = 0,
) -> None:
    """Tier 4: extract the current virtual→physical mapping as a target spec.

    Useful for capturing a known-good (or known-experimental) target to
    use later as input to `target score-dump` or `inspect guide`. Especially useful with
    Tier 5 force-phys: force the desired mapping, run pcdump, capture
    the result with this command, then save the spec and use it to
    score subsequent natural-source attempts.
    """
    pcdump = _resolve_pcdump_path(pcdump, function)
    text = pcdump.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])

    events_list = parse_hook_events(text)
    events = find_function(events_list, function)

    if force_phys_safe:
        if events is None:
            raise typer.BadParameter(
                f"--force-phys-safe needs COLORGRAPH DECISIONS, but no hook "
                f"events were found for {function!r} in {pcdump}"
            )
        from ..mwcc_debug import first_divergence as fd
        virtuals = fd.decision_coloring(events, class_id)
        spilled = sorted({
            e.ig_idx for s in events.simplify_sections if s.class_id == class_id
            for e in s.entries if e.spilled and e.ig_idx >= 0
        })
        spec = {"function": function, "virtuals": virtuals, "spilled": spilled}
    else:
        spec = derive_target_from_function(fn, events=events)

    if frame_from_checkdiff is not None:
        spec["frame"] = _frame_spec_from_checkdiff_target(frame_from_checkdiff)

    fmt = (output_format or "yaml").lower()
    if fmt == "json":
        print(json.dumps(spec, indent=2))
    else:
        # Render as YAML manually (avoid PyYAML dependency for output)
        print(f"function: {spec['function']}")
        print(f"virtuals:")
        for v in sorted(spec["virtuals"]):
            print(f"  {v}: {spec['virtuals'][v]}")
        if spec.get("spilled"):
            print(f"spilled:")
            for v in spec["spilled"]:
                print(f"  - {v}")
        if spec.get("frame"):
            frame = spec["frame"]
            print("frame:")
            print(f"  frame_size: {frame.get('frame_size')}")
            access_ranges = frame.get("access_ranges") or []
            if access_ranges:
                print("  access_ranges:")
                for item in access_ranges:
                    print(
                        f"    - start: {item.get('start')}\n"
                        f"      end: {item.get('end')}\n"
                        f"      size: {item.get('size')}\n"
                        f"      kind: {item.get('kind')}"
                    )
            unused_ranges = frame.get("unused_ranges") or []
            if unused_ranges:
                print("  unused_ranges:")
                for item in unused_ranges:
                    print(
                        f"    - start: {item.get('start')}\n"
                        f"      end: {item.get('end')}\n"
                        f"      size: {item.get('size')}"
                    )
    typer.echo(
        "Hint: save stdout to a target file, then run "
        f"`melee-agent debug inspect guide -f {function} --target <file>`.",
        err=True,
    )


@target_app.command(name="reanchor")
def reanchor_target(
    target_json: Annotated[Path, typer.Argument(help="Saved TargetSpec JSON (from build_target_spec.save_json).")],
    pcdump: Annotated[Optional[Path], typer.Argument(help="New compile's pcdump. Auto-resolves via -f if omitted.")] = None,
    function: Annotated[str, typer.Option("--function", "-f", help="Function name.")] = "",
    class_id: Annotated[int, typer.Option("--class", help="Register class (0=GPR).")] = 0,
    output_format: Annotated[str, typer.Option("--format", help="yaml|json.")] = "yaml",
) -> None:
    """Express a saved TargetSpec in a new compile's ig-numbering (Unit 3).

    Runs the role matcher (forward + inverse round-trip) and prints the
    force-phys-safe target spec {function, virtuals, spilled} for the new compile
    on stdout; per-role diagnostics (gone/merged/split/ambiguous/unstable_identity/
    no_descriptor — all EXCLUDED from the map) go to stderr. Feed stdout to
    `inspect first-divergence` as the --force-phys target.
    """
    if class_id != 0:
        typer.echo("reanchor supports only class 0 (GPR) at this time.", err=True)
        raise typer.Exit(2)
    from ..mwcc_debug import role_descriptor as rd_mod
    from ..mwcc_debug import role_reanchor as rr
    target = rd_mod.TargetSpec.load_json(target_json)
    fn = function or target.function
    pcdump = _resolve_pcdump_path(pcdump, fn)
    new_c = rd_mod.Compile.from_text(pcdump.read_text(), fn, "")
    res = rr.reanchor(target, new_c, class_id=class_id)
    spilled = sorted({e.ig_idx for s in new_c.fev.simplify_sections if s.class_id == class_id
                      for e in s.entries if e.spilled and e.ig_idx >= 0}) if new_c.fev else []
    spec = rr.reanchor_to_target_spec(res, fn, spilled=spilled)
    for ig, status in sorted(res.diagnostics.items()):
        print(f"[reanchor] role {ig}: {status} (excluded)", file=sys.stderr)
    print(f"[reanchor] {len(spec['virtuals'])} matched -> force-phys, "
          f"{len(res.diagnostics)} excluded", file=sys.stderr)
    if (output_format or "yaml").lower() == "json":
        print(json.dumps(spec, indent=2))
    else:
        print(f"function: {spec['function']}")
        print("virtuals:")
        for v in sorted(spec["virtuals"]):
            print(f"  {v}: {spec['virtuals'][v]}")
        if spec["spilled"]:
            print("spilled:")
            for v in spec["spilled"]:
                print(f"  - {v}")


def _count_function_defs(source: str) -> int:
    """Coarse count of function definitions in a C TU. Used as a safety
    heuristic for the --force-coalesce / --force-phys multi-fn guard:
    when N>=2, force-* without -fn is risky enough to refuse.

    Heuristic: count lines that look like `<retval> <name>(...)` at the
    top of the file (column 0), excluding obvious non-definitions
    (statements, declarations ending in `;`). Strings + comments are
    stripped first. Not exact — `static inline` definitions and
    K&R prototypes can over- or under-count — but good enough for a
    "are there multiple functions in this TU" gate.
    """
    # Strip strings + comments crudely (newline-preserving)
    cleaned = re.sub(r'/\*.*?\*/', '', source, flags=re.DOTALL)
    cleaned = re.sub(r'//[^\n]*', '', cleaned)
    cleaned = re.sub(r'"[^"\n]*"', '""', cleaned)
    # Function-definition heuristic: at column 0, a line that has
    # `name(...)` followed (eventually) by `{` not `;`. Count by
    # searching for `^<type-or-attr-tokens>+<name>(...)` followed by
    # `{` somewhere within a few hundred chars (allows multiline
    # parameter lists).
    pattern = re.compile(
        r'^[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\([^)]*\)\s*'
        r'(?:[A-Za-z_]\w*\s*)*\{',
        re.MULTILINE,
    )
    return len(pattern.findall(cleaned))


def _find_unit_for_function(func_name: str, melee_root: Path) -> Optional[str]:
    """Locate the unit (source path without .c) containing func_name via
    report.json. Mirrors tools/checkdiff.py's find_unit_for_function."""
    report_path = melee_root / "build" / "GALE01" / "report.json"
    if not report_path.exists():
        return None
    with report_path.open("r") as f:
        for unit in json.load(f).get("units", []):
            for function in unit.get("functions", []):
                if function.get("name") == func_name:
                    return unit.get("name", "").removeprefix("main/")
    return None


def _looks_like_melee_root(path: Path) -> bool:
    return (path / "src" / "melee").is_dir()


def _package_melee_root() -> Path:
    # src/cli/debug.py -> src -> melee-agent -> tools -> repo root
    return Path(__file__).resolve().parents[4]


def _source_file_melee_root(source_file: Path) -> Path | None:
    source_file = source_file.expanduser()
    source_path = source_file.resolve() if source_file.exists() else source_file
    for candidate in (source_path.parent, *source_path.parents):
        if _looks_like_melee_root(candidate):
            return candidate
    return None


def _bootstrap_melee_root_candidates(source_file: Path | None) -> list[Path]:
    candidates: list[Path] = []
    env_root = os.environ.get("MELEE_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    if source_file is not None:
        source_root = _source_file_melee_root(source_file)
        if source_root is not None:
            candidates.append(source_root)
    candidates.append(DEFAULT_MELEE_ROOT)
    cwd = Path.cwd()
    candidates.extend([cwd, *cwd.parents])
    candidates.append(_package_melee_root())

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            resolved = candidate.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def _resolve_bootstrap_melee_root(
    function: str,
    *,
    source_file: Path | None,
    melee_root: Path | None,
) -> Path:
    if melee_root is not None:
        root = melee_root.expanduser().resolve()
        if not _looks_like_melee_root(root):
            raise typer.BadParameter(
                f"--melee-root does not look like a Melee checkout: {root}"
            )
        return root

    fallback: Path | None = None
    for candidate in _bootstrap_melee_root_candidates(source_file):
        if not _looks_like_melee_root(candidate):
            continue
        if fallback is None:
            fallback = candidate
        if _find_unit_for_function(function, candidate) is not None:
            return candidate
    return fallback or DEFAULT_MELEE_ROOT


def _tmp_asm_path_for_function(function: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", function)
    return Path("/tmp") / f"{safe_name}.s"


_PERMUTER_DEFAULT_PRESERVE_MACROS = r"PAD_STACK|FORCE_PAD_STACK(?:_[0-9]+)?"


@contextmanager
def _staged_permuter_import_source(
    repo_source: Path,
    source_file: Path | None,
) -> Iterator[tuple[Path, bool]]:
    if source_file is None:
        yield repo_source, False
        return

    source_file = source_file.expanduser()
    if not source_file.is_file():
        raise typer.BadParameter(f"source file not found: {source_file}")
    if source_file.resolve() == repo_source.resolve():
        yield repo_source, False
        return

    original = repo_source.read_bytes()
    replacement = source_file.read_bytes()
    try:
        repo_source.write_bytes(replacement)
        yield repo_source, True
    finally:
        repo_source.write_bytes(original)


def _resolve_permuter_function_dir(
    function: str,
    *,
    perm_root: Path,
    melee_root: Path,
) -> Path:
    """Find a decomp-permuter function dir in either supported location."""
    perm_dir = perm_root / "nonmatchings" / function
    if perm_dir.exists():
        return perm_dir

    worktree_dir = melee_root / "nonmatchings" / function
    if worktree_dir.exists():
        return worktree_dir

    return perm_dir


def _permuter_import_dirs(
    function: str,
    *,
    perm_root: Path,
    melee_root: Path,
) -> set[Path]:
    pattern = re.compile(rf"^{re.escape(function)}(?:-\d+)?$")
    roots = {perm_root, melee_root}
    dirs: set[Path] = set()
    for root in roots:
        nonmatchings = root / "nonmatchings"
        if not nonmatchings.is_dir():
            continue
        for child in nonmatchings.iterdir():
            if child.is_dir() and pattern.match(child.name):
                dirs.add(child)
    return dirs


def _detect_new_permuter_import_dir(
    function: str,
    before: set[Path],
    *,
    perm_root: Path,
    melee_root: Path,
) -> Optional[Path]:
    new_dirs = _permuter_import_dirs(
        function,
        perm_root=perm_root,
        melee_root=melee_root,
    ) - before
    if not new_dirs:
        return None
    return max(new_dirs, key=lambda path: path.stat().st_mtime)


def _replace_path_from(src: Path, dst: Path) -> None:
    if dst.exists():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    shutil.move(str(src), str(dst))


def _promote_permuter_import_dir(
    imported_dir: Path,
    *,
    function: str,
    perm_root: Path,
    keep_existing_settings: bool,
) -> Path:
    """Move fresh import.py output into <perm_root>/nonmatchings/<function>.

    decomp-permuter's import.py chooses the output root from the imported source
    path, so importing a Melee source normally writes to the matcher worktree's
    nonmatchings directory. Normalize the fresh import into the decomp-permuter
    checkout and refresh generated files without deleting existing output-* dirs.
    """
    dest_dir = perm_root / "nonmatchings" / function
    if imported_dir.resolve() == dest_dir.resolve():
        return dest_dir

    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    if not dest_dir.exists():
        shutil.move(str(imported_dir), str(dest_dir))
        return dest_dir

    for child in imported_dir.iterdir():
        if (
            child.name == "settings.toml"
            and keep_existing_settings
            and (dest_dir / child.name).exists()
        ):
            continue
        _replace_path_from(child, dest_dir / child.name)
    shutil.rmtree(imported_dir, ignore_errors=True)
    return dest_dir


def _looks_like_decomp_permuter_root(path: Path) -> bool:
    return (path / "permuter.py").is_file() and (path / "src" / "compiler.py").is_file()


def _resolve_decomp_permuter_root(requested_root: Path) -> Path:
    """Resolve the checkout that provides decomp-permuter's Python modules.

    `--perm-root` is also used to locate candidate trees, and some matcher
    worktrees carry `nonmatchings/<fn>` without being decomp-permuter clones.
    Running the blended wrapper with such a tree on PYTHONPATH shadows the real
    package and fails with `ModuleNotFoundError: src.compiler`.
    """
    requested_root = requested_root.expanduser()
    if _looks_like_decomp_permuter_root(requested_root):
        return requested_root

    candidates: list[Path] = []
    env_root = os.environ.get("MELEE_DECOMP_PERMUTER_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.extend([
        Path("~/code/decomp-permuter").expanduser(),
        Path("~/code/melee-harness/decomp-permuter").expanduser(),
    ])
    for candidate in candidates:
        if candidate != requested_root and _looks_like_decomp_permuter_root(candidate):
            return candidate

    raise typer.BadParameter(
        f"{requested_root} does not look like a decomp-permuter checkout "
        "(missing permuter.py or src/compiler.py). Pass a decomp-permuter "
        "checkout via --perm-root, or set MELEE_DECOMP_PERMUTER_ROOT while "
        "using a separate matcher worktree for nonmatchings."
    )


def _bootstrap_permuter_dir(
    function: str,
    *,
    perm_root: Path,
    source_file: Optional[Path],
    melee_root: Optional[Path],
    preserve_macros: str,
    force: bool,
) -> dict:
    """Bootstrap a decomp-permuter function dir and return action metadata."""
    from ..mwcc_debug.fix_perm_compile import fix_perm_dir
    from ..mwcc_debug.permuter_config import build_spec, write_settings_toml

    melee_root = _resolve_bootstrap_melee_root(
        function,
        source_file=source_file,
        melee_root=melee_root,
    )
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"could not find {function!r} in report.json. "
            "Rebuild report.json and retry.",
            err=True,
        )
        raise typer.Exit(2)
    src_path = melee_root / "src" / f"{unit}.c"
    if not src_path.exists():
        typer.echo(f"source not found: {src_path}", err=True)
        raise typer.Exit(2)
    if not perm_root.exists():
        typer.echo(f"--perm-root does not exist: {perm_root}", err=True)
        raise typer.Exit(2)
    import_py = perm_root / "import.py"
    if not import_py.exists():
        typer.echo(f"decomp-permuter import.py not found: {import_py}", err=True)
        raise typer.Exit(2)

    before_import_dirs = _permuter_import_dirs(
        function,
        perm_root=perm_root,
        melee_root=melee_root,
    )
    asm_path = _tmp_asm_path_for_function(function)
    extract_cmd = [
        "melee-agent",
        "extract",
        "get",
        function,
        "--full",
        "--output",
        str(asm_path),
    ]
    extract_proc = subprocess.run(
        extract_cmd,
        cwd=melee_root,
        capture_output=True,
        text=True,
    )
    if extract_proc.returncode != 0:
        typer.echo(extract_proc.stderr or extract_proc.stdout, err=True)
        raise typer.Exit(extract_proc.returncode or 1)

    python_bin = perm_root / ".venv" / "bin" / "python"
    if not python_bin.exists():
        python_bin = Path(sys.executable)
    requested_source = source_file.expanduser() if source_file is not None else src_path
    with _staged_permuter_import_source(src_path, source_file) as (
        import_source,
        source_staged,
    ):
        import_cmd = [
            str(python_bin),
            str(import_py),
            str(import_source),
            str(asm_path),
            "--function",
            function,
        ]
        if preserve_macros is not None:
            import_cmd.extend(["--preserve-macros", preserve_macros])
        import_proc = subprocess.run(
            import_cmd,
            cwd=perm_root,
            capture_output=True,
            text=True,
        )
    if import_proc.returncode != 0:
        typer.echo(import_proc.stderr or import_proc.stdout, err=True)
        raise typer.Exit(import_proc.returncode or 1)

    imported_dir = _detect_new_permuter_import_dir(
        function,
        before_import_dirs,
        perm_root=perm_root,
        melee_root=melee_root,
    )
    if imported_dir is None:
        imported_dir = _resolve_permuter_function_dir(
            function,
            perm_root=perm_root,
            melee_root=melee_root,
        )
    fn_dir = _promote_permuter_import_dir(
        imported_dir,
        function=function,
        perm_root=perm_root,
        keep_existing_settings=not force,
    )
    if not fn_dir.exists():
        typer.echo(
            f"import.py completed but function dir was not found: {fn_dir}",
            err=True,
        )
        raise typer.Exit(1)

    fix_result = fix_perm_dir(fn_dir)
    settings_path = fn_dir / "settings.toml"
    settings_action = "kept"
    if force or not settings_path.exists():
        write_settings_toml(build_spec(function, pattern=None), settings_path)
        settings_action = "written"

    return {
        "function": function,
        "unit": unit,
        "source": str(requested_source),
        "import_source": str(src_path),
        "source_staged": source_staged,
        "asm": str(asm_path),
        "perm_root": str(perm_root),
        "function_dir": str(fn_dir),
        "extract_command": extract_cmd,
        "import_command": import_cmd,
        "fix_compile": {
            "path": str(fix_result.path),
            "action": fix_result.action,
            "reason": fix_result.reason,
        },
        "settings": {
            "path": str(settings_path),
            "action": settings_action,
        },
    }


def _permuter_import_hint(
    function: str,
    *,
    perm_root: Path,
    melee_root: Path,
    unit: Optional[str] = None,
) -> str:
    unit = unit or _find_unit_for_function(function, melee_root)
    if unit is None:
        return (
            "Run `melee-agent debug permute bootstrap` first. Could not locate the "
            f"source unit for {function!r}; regenerate report.json and retry."
        )

    perm_dir = _resolve_permuter_function_dir(
        function, perm_root=perm_root, melee_root=melee_root)
    return "\n".join([
        "Bootstrap the decomp-permuter function dir first:",
        f"  melee-agent debug permute bootstrap -f {shlex.quote(function)} "
        f"--perm-root {shlex.quote(str(perm_root))}",
        "  # bootstrap extracts target asm, invokes import.py, fixes compile.sh, "
        "and writes stock settings.toml.",
        f"  melee-agent debug permute fix-compile {shlex.quote(str(perm_dir))}",
    ])


def _permuter_doctor_checks(
    function: str,
    *,
    perm_root: Path,
    melee_root: Path,
) -> tuple[list[tuple[str, bool, str]], Path]:
    fn_dir = _resolve_permuter_function_dir(
        function,
        perm_root=perm_root,
        melee_root=melee_root,
    )
    checks: list[tuple[str, bool, str]] = []
    checks.append((
        "perm-root",
        perm_root.exists(),
        str(perm_root) if perm_root.exists() else f"missing: {perm_root}",
    ))
    checks.append((
        "function dir",
        fn_dir.exists(),
        str(fn_dir) if fn_dir.exists() else f"missing: {fn_dir}",
    ))
    for label, filename in (
        ("base.c", "base.c"),
        ("compile.sh", "compile.sh"),
        ("target.o", "target.o"),
        ("settings.toml", "settings.toml"),
    ):
        path = fn_dir / filename
        checks.append((
            label,
            path.exists(),
            str(path) if path.exists() else f"missing: {path}",
        ))
    return checks, fn_dir


@permute_app.command(name="doctor")
def permute_doctor(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to inspect"),
    ],
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit check results as JSON."),
    ] = False,
) -> None:
    """Validate local decomp-permuter paths before run/config/verify."""
    melee_root = DEFAULT_MELEE_ROOT
    checks, fn_dir = _permuter_doctor_checks(
        function,
        perm_root=perm_root,
        melee_root=melee_root,
    )
    failures = [check for check in checks if not check[1]]
    if json_out:
        print(json.dumps({
            "function": function,
            "perm_root": str(perm_root),
            "function_dir": str(fn_dir),
            "ok": not failures,
            "checks": [
                {"label": label, "ok": ok, "detail": detail}
                for label, ok, detail in checks
            ],
        }, indent=2))
        if failures:
            raise typer.Exit(2)
        return

    for label, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}\t{label}\t{detail}")
    if failures:
        print()
        print(_permuter_import_hint(
            function,
            perm_root=perm_root,
            melee_root=melee_root,
        ))
        raise typer.Exit(2)
    print("OK\tready for `melee-agent debug permute run`")


@permute_app.command(name="bootstrap")
def permute_bootstrap(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to import"),
    ],
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "Import this edited source instead of the repo TU. The file is "
                "temporarily staged over the real TU so decomp-permuter still "
                "uses the correct Melee build settings."
            ),
        ),
    ] = None,
    melee_root: Annotated[
        Optional[Path],
        typer.Option(
            "--melee-root",
            help=(
                "Melee repo/worktree root. Defaults to MELEE_ROOT, "
                "--source-file/cwd detection, then the installed package repo."
            ),
        ),
    ] = None,
    preserve_macros: Annotated[
        str,
        typer.Option(
            "--preserve-macros",
            help=(
                "Regex of source macros decomp-permuter should keep in base.c. "
                "Use an empty string to disable."
            ),
        ),
    ] = _PERMUTER_DEFAULT_PRESERVE_MACROS,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite stock settings.toml if present."),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit action summary as JSON."),
    ] = False,
) -> None:
    """Bootstrap a decomp-permuter function dir from the current repo source."""
    payload = _bootstrap_permuter_dir(
        function,
        perm_root=perm_root,
        source_file=source_file,
        melee_root=melee_root,
        preserve_macros=preserve_macros,
        force=force,
    )
    if json_out:
        print(json.dumps(payload, indent=2))
        return

    src_path = Path(payload["import_source"])
    fn_dir = Path(payload["function_dir"])
    asm_path = Path(payload["asm"])
    fix_result = payload["fix_compile"]
    settings_action = payload["settings"]["action"]
    print(f"Wrote/imported {fn_dir}")
    print(f"  source: {src_path}")
    print(f"  target asm: {asm_path}")
    print(
        f"  compile.sh: {fix_result['action']}"
        + (f" ({fix_result['reason']})" if fix_result["reason"] else "")
    )
    print(f"  settings.toml: {settings_action}")
    print()
    print("Next:")
    rel_dir = fn_dir.relative_to(perm_root) if perm_root in fn_dir.parents else fn_dir
    print(f"  cd {perm_root}")
    print(f"  ./permuter.py {rel_dir}")


def _remote_error(exc: Exception) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(2)


def _remote_load_targets() -> dict[str, permuter_remote.RemoteTarget]:
    return permuter_remote.load_targets(permuter_remote.CONFIG_PATH)


def _remote_read_job(job_id: str) -> permuter_remote.RemoteJob:
    return permuter_remote.read_job(job_id, permuter_remote.JOBS_DIR)


def _remote_stream_runner(
    argv: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> permuter_remote.CommandResult:
    completed = subprocess.run(argv, cwd=cwd)
    result = permuter_remote.CommandResult(
        returncode=completed.returncode,
        stdout="",
        stderr="",
    )
    if check and result.returncode != 0:
        raise permuter_remote.RemoteJobError(
            f"Command failed ({result.returncode}): {shlex.join(argv)}"
        )
    return result


@remote_app.command(name="targets")
def remote_targets() -> None:
    """List configured remote permuter targets."""
    try:
        targets = _remote_load_targets()
    except permuter_remote.RemoteConfigError as exc:
        _remote_error(exc)

    for target in targets.values():
        print(
            f"{target.name}\t{target.ssh}\t{target.remote_perm_root}\t"
            f"{target.remote_melee_root}\t{target.threads}"
        )


@remote_app.command(name="doctor")
def remote_doctor(
    target_name: Annotated[
        str,
        typer.Option("--target", help="Configured remote target name."),
    ],
    function: Annotated[
        Optional[str],
        typer.Option("--function", "-f", help="Also check this local permuter function dir."),
    ] = None,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help=(
                "Root containing nonmatchings/<function>. If this is a matcher "
                "worktree, repair resolves the decomp-permuter code checkout "
                "from $MELEE_DECOMP_PERMUTER_ROOT or ~/code/decomp-permuter."
            ),
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    repair: Annotated[
        bool,
        typer.Option("--repair", help="Bootstrap/repair project-owned remote tooling before checking."),
    ] = False,
) -> None:
    """Check whether a remote target is ready to run decomp-permuter."""
    try:
        targets = _remote_load_targets()
        target = targets.get(target_name)
        if target is None:
            available = ", ".join(sorted(targets)) or "(none)"
            raise permuter_remote.RemoteConfigError(
                f"Remote permuter target not found: {target_name}\n"
                f"Available targets: {available}"
            )
        local_perm_dir = None
        if function is not None:
            local_perm_dir = _resolve_permuter_function_dir(
                function,
                perm_root=perm_root,
                melee_root=DEFAULT_MELEE_ROOT,
            )
        if repair:
            repair_perm_root = _resolve_decomp_permuter_root(perm_root)
            repair_report = permuter_remote.repair_target(
                target,
                local_melee_root=DEFAULT_MELEE_ROOT,
                local_perm_root=repair_perm_root,
                function=function,
                local_perm_dir=local_perm_dir,
            )
            for action in repair_report.actions:
                print(f"REPAIR\t{action}")
        report = permuter_remote.doctor_target(
            target,
            local_perm_dir=local_perm_dir,
        )
    except (permuter_remote.RemoteConfigError, permuter_remote.RemoteJobError) as exc:
        _remote_error(exc)

    for check in report.checks:
        status = "PASS" if check.ok else "FAIL"
        requirement = "required" if check.required else "optional"
        detail = f" - {check.detail}" if check.detail else ""
        print(f"{status}\t{check.name}\t{requirement}{detail}")
    if not report.ok:
        raise typer.Exit(2)


@remote_app.command(name="submit")
def remote_submit(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function to run remotely."),
    ],
    target_name: Annotated[
        str,
        typer.Option("--target", help="Configured remote target name."),
    ],
    threads: Annotated[
        Optional[int],
        typer.Option("--threads", "-j", help="Override target thread count."),
    ] = None,
    mode: Annotated[
        str,
        typer.Option("--mode", help="Remote permuter mode."),
    ] = "stock",
    perm_root: Annotated[
        Path,
        typer.Option("--perm-root", help="Root of decomp-permuter clone."),
    ] = Path("~/code/decomp-permuter").expanduser(),
) -> None:
    """Submit a local decomp-permuter function directory to a remote target."""
    melee_root = DEFAULT_MELEE_ROOT
    perm_dir = _resolve_permuter_function_dir(
        function, perm_root=perm_root, melee_root=melee_root)
    if not perm_dir.exists():
        typer.echo(
            f"{perm_dir} not found.\n"
            + _permuter_import_hint(
                function,
                perm_root=perm_root,
                melee_root=melee_root,
            ),
            err=True,
        )
        raise typer.Exit(2)

    targets: dict[str, permuter_remote.RemoteTarget] = {}
    target: permuter_remote.RemoteTarget | None = None
    try:
        targets = _remote_load_targets()
        target = targets.get(target_name)
        if target is None:
            available = ", ".join(sorted(targets)) or "(none)"
            raise permuter_remote.RemoteConfigError(
                f"Remote permuter target not found: {target_name}\n"
                f"Available targets: {available}"
            )
        job = permuter_remote.submit_job(
            function=function,
            target=target,
            local_perm_dir=perm_dir,
            jobs_dir=permuter_remote.JOBS_DIR,
            threads=threads,
            mode=mode,
            local_melee_root=melee_root,
            local_perm_root=_resolve_decomp_permuter_root(perm_root),
        )
    except (permuter_remote.RemoteConfigError, permuter_remote.RemoteJobError) as exc:
        if (
            isinstance(exc, permuter_remote.RemoteJobError)
            and target is not None
            and "remote preflight failed" in str(exc)
        ):
            suggestions = permuter_remote.suggest_ready_targets(
                targets,
                failed_target_name=target.name,
                local_perm_dir=perm_dir,
            )
            if suggestions:
                retry = suggestions[0]
                exc = permuter_remote.RemoteJobError(
                    f"{exc}\n"
                    f"Healthy configured target(s): {', '.join(suggestions)}\n"
                    f"Retry with --target {retry}."
                )
        _remote_error(exc)

    print(f"Job: {job.job_id}")
    print(f"Remote path: {job.remote_perm_dir}")
    print(f"Log path: {job.remote_run_dir}/permuter.log")


@remote_app.command(name="list")
def remote_list() -> None:
    """List local remote permuter job metadata."""
    try:
        jobs = permuter_remote.list_jobs(permuter_remote.JOBS_DIR)
    except permuter_remote.RemoteJobError as exc:
        _remote_error(exc)

    for job in jobs:
        print(
            f"{job.job_id}\t{job.function}\t{job.target}\t"
            f"{job.threads}\t{job.created_at}"
        )


@remote_app.command(name="status")
def remote_status(
    job_id: Annotated[str, typer.Argument(help="Remote permuter job id.")],
    stale_hours: Annotated[
        float,
        typer.Option(
            "--stale-hours",
            help="Recommend stopping active jobs older than this many wall hours.",
        ),
    ] = 24.0,
    idle_hours: Annotated[
        float,
        typer.Option(
            "--idle-hours",
            help="Recommend stopping active jobs whose log is idle this many hours.",
        ),
    ] = 12.0,
) -> None:
    """Show remote permuter job activity and stale cleanup guidance."""
    try:
        job = _remote_read_job(job_id)
        status = permuter_remote.status_job(job)
        log_status = permuter_remote.remote_log_status(job)
    except (permuter_remote.RemoteConfigError, permuter_remote.RemoteJobError) as exc:
        _remote_error(exc)

    print(f"{status.job_id}: {status.state}")
    now = permuter_remote.utcnow()
    try:
        created_at = permuter_remote.parse_timestamp(job.created_at)
    except ValueError:
        created_at = None
    if created_at is not None:
        wall_age_h = max(0.0, (now - created_at).total_seconds() / 3600.0)
        print(f"wall age: {wall_age_h:.1f}h")
    else:
        wall_age_h = None
        print(f"wall age: unknown ({job.created_at})")
    print(f"function: {job.function}")
    print(f"target: {job.target} ({job.ssh})")
    print(f"remote path: {job.remote_perm_dir}")
    if log_status.exists and log_status.modified_at is not None:
        idle_h = max(0.0, (now - log_status.modified_at).total_seconds() / 3600.0)
        print(f"log idle: {idle_h:.1f}h")
    else:
        idle_h = None
        detail = f" - {log_status.detail}" if log_status.detail else ""
        print(f"log idle: unknown{detail}")
    if log_status.best_score:
        print(f"best score: {log_status.best_score}")
    reasons: list[str] = []
    if status.state == "active":
        if wall_age_h is not None and wall_age_h >= stale_hours:
            reasons.append(f"wall age >= {stale_hours:g}h")
        if idle_h is not None and idle_h >= idle_hours:
            reasons.append(f"log idle >= {idle_hours:g}h")
    if reasons:
        print(f"recommendation: stop ({'; '.join(reasons)})")
        print(f"cleanup: melee-agent debug permute remote stop {job.job_id}")
    elif status.state == "active":
        print("recommendation: keep")
    else:
        print("recommendation: stopped")
    if status.detail:
        typer.echo(status.detail, err=True)


@remote_app.command(name="fetch")
def remote_fetch(
    job_id: Annotated[str, typer.Argument(help="Remote permuter job id.")],
    triage: Annotated[
        bool,
        typer.Option("--triage", help="Print the follow-up triage command."),
    ] = False,
) -> None:
    """Fetch remote permuter outputs into the local permuter directory."""
    try:
        job = _remote_read_job(job_id)
        fetched = permuter_remote.fetch_job(job)
    except (permuter_remote.RemoteConfigError, permuter_remote.RemoteJobError) as exc:
        _remote_error(exc)

    print(f"Fetched: {fetched}")
    if triage:
        print(
            "Triage manually with: "
            f"melee-agent debug permute triage {shlex.quote(str(fetched))} "
            f"--function {shlex.quote(job.function)}"
        )


@remote_app.command(name="tail")
def remote_tail(
    job_id: Annotated[str, typer.Argument(help="Remote permuter job id.")],
    lines: Annotated[
        int,
        typer.Option("--lines", "-n", help="Number of log lines to print."),
    ] = 80,
    follow: Annotated[
        bool,
        typer.Option(
            "--follow/--no-follow",
            help="Keep streaming the remote permuter log after the snapshot.",
        ),
    ] = False,
) -> None:
    """Print a remote permuter job log snapshot."""
    try:
        job = _remote_read_job(job_id)
        result = permuter_remote.tail_job(
            job,
            runner=_remote_stream_runner if follow else permuter_remote.run_command,
            lines=lines,
            follow=follow,
        )
    except (permuter_remote.RemoteConfigError, permuter_remote.RemoteJobError) as exc:
        _remote_error(exc)

    if result.stdout:
        stdout = (
            result.stdout if follow
            else permuter_remote.sanitize_log_tail(result.stdout, lines=lines)
        )
        typer.echo(stdout, nl=False)
    if result.stderr:
        typer.echo(result.stderr, err=True, nl=False)
    if result.returncode != 0:
        raise typer.Exit(2)


@permute_app.command(name="local-orphans")
def permute_local_orphans() -> None:
    """Detect orphaned local wibo/MWCC compile processes."""
    orphans = permuter_remote.detect_orphaned_wibo_processes()
    if not orphans:
        print("No orphaned local wibo/MWCC processes detected.")
        return
    print("Orphaned local wibo/MWCC processes:")
    for proc in orphans:
        state_note = (
            " uninterruptible; kill may not work, restart host if it blocks builds"
            if "U" in proc.stat
            else ""
        )
        print(
            f"PID={proc.pid}\tPPID={proc.ppid}\tSTAT={proc.stat}\t"
            f"ELAPSED={proc.elapsed}{state_note}"
        )
        print(f"  {proc.command}")
    raise typer.Exit(1)


@remote_app.command(name="stop")
def remote_stop(
    job_id: Annotated[str, typer.Argument(help="Remote permuter job id.")],
) -> None:
    """Stop a remote permuter tmux session."""
    try:
        job = _remote_read_job(job_id)
        result = permuter_remote.stop_job(job)
    except (permuter_remote.RemoteConfigError, permuter_remote.RemoteJobError) as exc:
        _remote_error(exc)

    if result.returncode == 0:
        print("Stopped")
        return
    if result.stderr:
        typer.echo(result.stderr, err=True, nl=False)
    raise typer.Exit(2)


def _parse_force_coalesce_pairs(force_coalesce: str) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for raw in force_coalesce.split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            lhs, rhs = item.split("=", 1)
            pairs.append((
                int(lhs.strip().removeprefix("r").removeprefix("R")),
                int(rhs.strip().removeprefix("r").removeprefix("R")),
            ))
        except ValueError:
            raise typer.BadParameter(
                f"invalid --force-coalesce pair {item!r}; expected virt=root"
            )
    return pairs


def _force_coalesce_preflight_report(
    *,
    function: str,
    pair: tuple[int, int],
    pcdump_text: str,
    source_text: str,
):
    from ..mwcc_debug.suggest_coalesce import run

    return run(
        function=function,
        pair=pair,
        pcdump_text=pcdump_text,
        source_text=source_text,
    )


def _reject_unsafe_force_coalesce(
    *,
    force_coalesce: str,
    function: str,
    melee_root: Path,
) -> None:
    pairs = _parse_force_coalesce_pairs(force_coalesce)
    pairs = [(lhs, rhs) for lhs, rhs in pairs if lhs != rhs]
    if not pairs:
        return

    unit = _find_unit_for_function(function, melee_root)
    source_text = ""
    if unit is not None:
        src_path = melee_root / "src" / f"{unit}.c"
        if src_path.exists():
            source_text = src_path.read_text()

    try:
        pcdump_path = _resolve_pcdump_path(
            None, function, melee_root, require_fresh=True,
        )
    except typer.Exit:
        dump_hint = (
            f"src/{unit}.c" if unit is not None else "<source.c>"
        )
        typer.echo(
            "[debug dump local] refusing --force-coalesce: fresh cached pcdump "
            f"required for {function}. Run `melee-agent debug dump local "
            f"{dump_hint}` without force options first, then retry the scoped "
            "force-coalesce.",
            err=True,
        )
        raise typer.Exit(2)

    pcdump_text = pcdump_path.read_text()
    unsafe: list[tuple[int, int, list[str]]] = []
    for pair in pairs:
        try:
            report = _force_coalesce_preflight_report(
                function=function,
                pair=pair,
                pcdump_text=pcdump_text,
                source_text=source_text,
            )
        except Exception as exc:
            typer.echo(
                f"[debug dump local] force-coalesce preflight skipped for "
                f"r{pair[0]}=r{pair[1]}: {type(exc).__name__}: {exc}",
                err=True,
            )
            continue
        preflight = report.pairs[0].preflight if report.pairs else None
        if preflight is not None and not preflight.safe:
            unsafe.append((pair[0], pair[1], list(preflight.reasons)))

    if not unsafe:
        return

    typer.echo(
        "[debug dump local] refusing unsafe --force-coalesce before invoking "
        "wibo. Use `debug suggest coalesce` for source-shape leads instead.",
        err=True,
    )
    for lhs, rhs, reasons in unsafe:
        typer.echo(f"  r{lhs}=r{rhs}:", err=True)
        for reason in reasons:
            typer.echo(f"    - {reason}", err=True)
    raise typer.Exit(2)


_FIRST_DIAGNOSTIC_RE = re.compile(
    # GCC/Clang/MWCC standard: "path/to/file.c:42:7: error: ..."
    # Allow Windows-style backslashes in paths (wibo translates these).
    r"^(?P<path>[^\s:][^\s:]*?):(?P<line>\d+)(?::(?P<col>\d+))?:\s*"
    r"(?P<level>error|fatal|warning|note):\s*(?P<msg>.+)$"
)


def _extract_first_diagnostic(stdout: str, stderr: str) -> Optional[str]:
    """Find the first compiler diagnostic with `filename:line: error:` shape.

    This is the actual informative diagnostic — distinct from the caret
    pointer line that follows it. ninja/wibo output often interleaves
    progress lines around it, so we scan the full combined output and
    return the first match. Returns None if no such line is found.

    Handles MWCC's `# Error: …` block format too: when stderr looks like
    a multi-line `# File:` / `# Line:` / `# Error:` block, synthesize a
    `path:line: error: msg` line so callers see one usable diagnostic.
    """
    lines = (stdout + "\n" + stderr).splitlines()
    # First pass: standard `filename:line: error:` shape.
    for line in lines:
        m = _FIRST_DIAGNOSTIC_RE.match(line.strip())
        if m and m.group("level").lower() in ("error", "fatal"):
            return line.strip()

    # Second pass: MWCC's pretty-printed multi-line diagnostic block.
    # Look for `# File:` followed (within a few lines) by `# Line:` and
    # `# Error:` markers.
    path: Optional[str] = None
    lineno: Optional[str] = None
    for raw in lines:
        s = raw.strip()
        m = re.match(r"#\s*File:\s*(.*)$", s)
        if m:
            path = m.group(1).strip() or None
            continue
        m = re.match(r"#\s*Line:\s*(.*)$", s)
        if m:
            lineno = m.group(1).strip() or None
            continue
        m = re.match(r"#\s*Error:\s*(.*)$", s)
        if m:
            msg = m.group(1).strip()
            if msg:
                if not any(ch.isalnum() for ch in msg):
                    continue
                p = path or "(unknown)"
                ln = lineno or "?"
                return f"{p}:{ln}: error: {msg}"
    return None


def _extract_ninja_error(stdout: str, stderr: str, max_lines: int = 8) -> str:
    """Pull the relevant error lines out of a ninja failure dump.

    ninja's full output is mostly progress lines (`[N/M] ...`) that
    aren't useful. The actual error lives in lines containing 'error:',
    'FAILED:', or compiler diagnostics. Return at most `max_lines`.

    To make sure the first informative diagnostic isn't trimmed away by
    `max_lines` when there are many warnings, the result is prefixed
    with the first `filename:line: error:` diagnostic we find.
    """
    lines = (stdout + "\n" + stderr).splitlines()
    relevant_indexes: list[int] = []
    for idx, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        if any(marker in s.lower() for marker in (
            "error:", "failed:", "fatal:", "warning:",
            "undefined reference", "implicit declaration",
            "no such file", "cannot find",
        )):
            relevant_indexes.append(idx)
        elif s.startswith(("/", "src/", "include/", "tools/")) and ":" in s:
            # File:line:col-style references — likely the diagnostic location
            relevant_indexes.append(idx)
        elif re.match(r"#\s*(File|Line|Code|Error):", s):
            relevant_indexes.append(idx)
    context_indexes: set[int] = set(relevant_indexes)
    for idx in relevant_indexes:
        stripped = lines[idx].strip()
        if stripped.startswith("#"):
            for nearby in range(max(0, idx - 4), min(len(lines), idx + 3)):
                if lines[nearby].strip():
                    context_indexes.add(nearby)
        for nearby in range(idx + 1, min(len(lines), idx + 5)):
            nearby_stripped = lines[nearby].strip()
            if not nearby_stripped:
                continue
            if re.match(r"^\[\d+/\d+\]", nearby_stripped):
                break
            context_indexes.add(nearby)
    relevant = [lines[idx] for idx in sorted(context_indexes)]
    if not relevant:
        # Fall back to last few non-empty stderr lines
        tail_stderr = [l for l in stderr.splitlines() if l.strip()][-max_lines:]
        relevant = tail_stderr or ["(no error lines captured)"]

    # Promote the first FULL diagnostic (filename:line: error: …) to the
    # top of the result, so it isn't lost when many warnings precede the
    # real error and we hit max_lines. If we already have it in relevant,
    # this just guarantees ordering.
    first_diag = _extract_first_diagnostic(stdout, stderr)
    trimmed = relevant[:max_lines]
    if first_diag and first_diag not in trimmed:
        trimmed = [first_diag, *trimmed[: max_lines - 1]]
    return "\n".join(trimmed)


def _suggest_similar_functions(target: str, available: list[str], n: int = 5) -> list[str]:
    """Return up to `n` available function names that look similar to `target`.

    Uses Python's difflib for fuzzy ranking. Common typos (e.g. wrong
    case, missing underscore, trailing digit drift) are surfaced this way.
    """
    import difflib
    return difflib.get_close_matches(target, available, n=n, cutoff=0.5)


def _abort_function_not_in_dump(function: str, available_names: list[str]) -> None:
    """Emit a rich error message + exit. Used by every command that
    fails to find a function in a pcdump.
    """
    _emit_function_not_in_dump(function, available_names)
    raise typer.Exit(3)


def _emit_function_not_in_dump(
    function: str,
    available_names: list[str],
    *,
    hint: Optional[str] = None,
) -> None:
    typer.echo(f"function '{function}' not found in pcdump.", err=True)
    suggestions = _suggest_similar_functions(function, available_names)
    if suggestions:
        typer.echo("", err=True)
        typer.echo("Did you mean one of these?", err=True)
        for s in suggestions:
            typer.echo(f"  - {s}", err=True)
    else:
        # No close matches — show a sample
        typer.echo("", err=True)
        sample = available_names[:8]
        if sample:
            typer.echo(f"Sample of {len(available_names)} functions in this dump:", err=True)
            for s in sample:
                typer.echo(f"  - {s}", err=True)
            if len(available_names) > 8:
                typer.echo(f"  ... +{len(available_names) - 8} more", err=True)
    typer.echo("", err=True)
    if hint is None:
        hint = (
            "Hint: check spelling, or if the source changed since the cache "
            "was generated, re-run `debug dump remote <c_file>`."
        )
    typer.echo(hint, err=True)


def _resolve_pcdump_path(
    pcdump: Optional[Path],
    function: Optional[str],
    melee_root: Path = DEFAULT_MELEE_ROOT,
    *,
    require_fresh: bool = False,
) -> Path:
    """Resolve a pcdump path for a consumer command.

    Resolution order:
      1. If `pcdump` is given AND exists → use it.
      2. Else if `function` is given → look up its TU, check the cache.
         - If cache is fresh (or `require_fresh=False` and stale): use it.
         - If cache is missing or stale: raise typer.Exit with a clear hint.
      3. Else: raise typer.Exit asking for either path or function.

    The cache stale-vs-fresh logic: `require_fresh=False` lets the agent
    work with a slightly stale dump (useful when they just edited source
    but want to inspect what the OLD compile produced). `require_fresh=
    True` is for commands that NEED matching dump+source (e.g. ones that
    correlate per-line source positions).
    """
    if pcdump is not None and pcdump.exists():
        return pcdump
    if pcdump is not None:
        # User specified a path but it doesn't exist
        typer.echo(f"pcdump not found: {pcdump}", err=True)
        raise typer.Exit(2)
    # Auto-resolve via function → TU → cache
    if function is None:
        typer.echo(
            "no pcdump path provided and no --function given.\n"
            "Either pass the pcdump path positionally, or pass --function "
            "and we'll auto-resolve via the cache.",
            err=True,
        )
        raise typer.Exit(2)
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        # Suggest similar names from report.json
        try:
            report_path = melee_root / "build" / "GALE01" / "report.json"
            if report_path.exists():
                with report_path.open() as f:
                    rdata = json.load(f)
                all_names = [fn.get("name") for u in rdata.get("units", [])
                             for fn in u.get("functions", []) if fn.get("name")]
                suggestions = _suggest_similar_functions(function, all_names)
            else:
                suggestions = []
        except Exception:
            suggestions = []
        msg = f"function '{function}' not found in report.json.\n"
        if suggestions:
            msg += "\nDid you mean one of these?\n"
            for s in suggestions:
                msg += f"  - {s}\n"
        msg += "\nTry `ninja build/GALE01/report.json` to regenerate, then retry."
        typer.echo(msg, err=True)
        raise typer.Exit(2)
    entry = pcdump_cache.lookup(melee_root, unit)
    if entry is None:
        cache_p = pcdump_cache.cache_path(melee_root, unit)
        src_p = pcdump_cache.source_path(melee_root, unit)
        typer.echo(
            f"no cached pcdump for {unit} (function lives in {src_p}).\n"
            f"Generate one with:\n"
            f"  melee-agent debug dump remote {src_p.relative_to(melee_root)}\n"
            f"(it will be cached to {cache_p.relative_to(melee_root)})",
            err=True,
        )
        raise typer.Exit(3)
    if not entry.fresh and require_fresh:
        typer.echo(
            f"cached pcdump is stale (source modified since cache).\n"
            f"  Source: {entry.source_path}\n"
            f"  Cache:  {entry.path}\n"
            f"Regenerate with:\n"
            f"  melee-agent debug dump local {entry.source_path.relative_to(melee_root)}\n"
            f"or, if local dump support is unavailable:\n"
            f"  melee-agent debug dump remote {entry.source_path.relative_to(melee_root)}\n"
            f"If the command explicitly supports stale allocator facts, "
            f"retry with --allow-stale-pcdump.",
            err=True,
        )
        raise typer.Exit(4)
    if not entry.fresh:
        # Non-fatal — warn but use the stale cache.
        import datetime
        src_ts = datetime.datetime.fromtimestamp(
            entry.source_path.stat().st_mtime
        ).strftime("%H:%M:%S.%f")[:12]
        cache_ts = datetime.datetime.fromtimestamp(
            entry.path.stat().st_mtime
        ).strftime("%H:%M:%S.%f")[:12]
        typer.echo(
            f"[mwcc_debug] using stale cached pcdump "
            f"({entry.source_path.name} modified since cache; "
            f"src={src_ts} cache={cache_ts}). "
            f"Re-run `debug dump local` to refresh.",
            err=True,
        )
    return entry.path


def _auto_pcdump_cache_metadata(
    pcdump: Optional[Path],
    function: Optional[str],
    melee_root: Path = DEFAULT_MELEE_ROOT,
) -> dict | None:
    """Return cache freshness metadata for auto-resolved pcdumps."""
    if pcdump is not None or function is None:
        return None
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        return None
    entry = pcdump_cache.lookup(melee_root, unit)
    if entry is None:
        return None
    payload = {
        "unit": unit,
        "path": str(entry.path),
        "source_path": str(entry.source_path),
        "fresh": entry.fresh,
    }
    if entry.path.exists():
        payload["cache_mtime"] = entry.path.stat().st_mtime
    if entry.source_path.exists():
        payload["source_mtime"] = entry.source_path.stat().st_mtime
    return payload


def _format_hsd_assert_override_guidance(indent: str = "") -> str:
    lines = [
        "Candidate fix: before the <baselib/jobj.h> include, add:",
        "  #include <baselib/debug.h>",
        "  #undef HSD_ASSERT",
        "  #define HSD_ASSERT(line, cond) \\",
        "      ((cond) ? ((void) 0) : __assert(<file_sym>, line, <fn_sym>))",
        "where <file_sym> / <fn_sym> are named extern char[] symbols declared in the TU.",
        "Caution: this hint means anonymous assert strings are present in the TU; it may be neutral for the current function.",
        "If jobj.h is already included transitively through another local header, a local #undef may be too late or can perturb other functions.",
        "Verify with checkdiff for the target and nearby affected functions before keeping the include-order or wrapper change.",
    ]
    return "\n".join(f"{indent}{line}" for line in lines)


def _get_match_pct(func_name: str, melee_root: Path) -> Optional[float]:
    """Read the function's fuzzy_match_percent from report.json."""
    report_path = melee_root / "build" / "GALE01" / "report.json"
    if not report_path.exists():
        return None
    with report_path.open("r") as f:
        for unit in json.load(f).get("units", []):
            for function in unit.get("functions", []):
                if function.get("name") == func_name:
                    return function.get("fuzzy_match_percent")
    return None


def _merge3_function(
    base_fn: str,
    candidate_fn: str,
    current_fn: str,
) -> tuple[str, list[tuple[int, str]]]:
    """3-way merge wrapper delegating to source_patch.merge3_function.

    Returns (merged_text, conflicts) where conflicts is a list of
    (approx_line_number, description) pairs. Empty conflicts = clean merge.
    """
    from ..mwcc_debug.source_patch import merge3_function
    return merge3_function(base_fn, candidate_fn, current_fn)


_PERMUTER_PLACEHOLDERS = candidate_audit.PERMUTER_PLACEHOLDERS


def _permuter_placeholder_hits(text: str) -> list[tuple[str, int]]:
    return candidate_audit.placeholder_hits(text)


def _format_permuter_placeholder_summary(hits: list[tuple[str, int]]) -> str:
    return ", ".join(
        f"'{placeholder}' ({count} occurrence{'s' if count != 1 else ''})"
        for placeholder, count in hits
    )


def _format_permuter_placeholder_diagnostic(
    hits: list[tuple[str, int]],
    *,
    command: str,
    candidate: Optional[Path] = None,
) -> str:
    summary = _format_permuter_placeholder_summary(hits)
    message = (
        f"[{command}] ABORT: permuter placeholder(s) detected in "
        f"candidate source: {summary}. These are unresolved AST "
        f"placeholders from decomp-permuter's randomizer that should "
        f"never reach real source. The candidate is corrupt; do not apply."
    )
    if candidate is not None:
        message += f" Candidate: {candidate}"
    return message


def _format_permuter_candidate_audit_diagnostic(
    report: candidate_audit.CandidateAudit,
    *,
    command: str,
    candidate: Optional[Path] = None,
) -> str:
    placeholder_hits = [
        (risk.name or "", risk.count or 0)
        for risk in report.risks
        if risk.kind == "placeholder-leak" and risk.name
    ]
    if placeholder_hits and all(risk.kind == "placeholder-leak" for risk in report.risks):
        return _format_permuter_placeholder_diagnostic(
            placeholder_hits,
            command=command,
            candidate=candidate,
        )
    return candidate_audit.format_candidate_audit_diagnostic(
        report,
        command=command,
        candidate=candidate,
    )


def _write_permuter_candidate_status(
    candidate: Path,
    *,
    status: str,
    function: str,
    first_diag: Optional[str] = None,
    risks: tuple[candidate_audit.SourceRisk, ...] = (),
    match_pct: Optional[float] = None,
    delta: Optional[float] = None,
    semantic_risk_bucket: Optional[str] = None,
    source: str,
    extra: Optional[dict] = None,
) -> None:
    try:
        candidate_audit.write_candidate_status(
            candidate,
            status=status,
            function=function,
            first_diag=first_diag,
            risks=risks,
            match_pct=match_pct,
            delta=delta,
            semantic_risk_bucket=semantic_risk_bucket,
            source=source,
            extra=extra,
        )
    except OSError:
        pass


def _read_permuter_candidate_status(candidate: Path) -> Optional[dict]:
    try:
        payload = json.loads(
            candidate_audit.status_sidecar_path(candidate).read_text()
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _is_resume_skippable_candidate_status(payload: dict) -> bool:
    status = payload.get("status")
    source = payload.get("source")
    if source == "triage":
        return status is not None
    # Fetch-time source audit already proves these candidates cannot transfer
    # and triage would just rewrite the same terminal sidecar.
    return source == "fetch" and status in {
        "corrupt-candidate",
        "read-failed",
        "unsafe-candidate",
    }


def _permuter_candidate_score(candidate: Path) -> float:
    match = re.match(
        r"^output-(?P<score>-?\d+(?:\.\d+)?)-\d+$",
        candidate.parent.name,
    )
    if not match:
        return float("-inf")
    try:
        return float(match.group("score"))
    except ValueError:
        return float("-inf")


def _sort_permuter_candidate_paths(
    candidates: list[Path],
    *,
    order: str,
) -> list[Path]:
    if order == "name":
        return sorted(candidates, key=lambda path: path.parent.name)
    if order == "newest":
        return sorted(
            candidates,
            key=lambda path: (
                path.parent.stat().st_mtime,
                path.stat().st_mtime,
                path.parent.name,
            ),
            reverse=True,
        )
    if order == "score-desc":
        return sorted(
            candidates,
            key=lambda path: (_permuter_candidate_score(path), path.parent.name),
            reverse=True,
        )
    if order == "score-asc":
        return sorted(
            candidates,
            key=lambda path: (_permuter_candidate_score(path), path.parent.name),
        )
    raise ValueError(
        f"invalid --order {order!r}; expected name, newest, score-desc, or score-asc"
    )


def _canonical_c_for_format_merge(text: str) -> str:
    """Return C text with comments/formatting removed, preserving literals."""
    out: list[str] = []
    i = 0
    n = len(text)
    quote: Optional[str] = None
    while i < n:
        ch = text[i]
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            if text[i + 1] == "/":
                i += 2
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if text[i + 1] == "*":
                i += 2
                while i + 1 < n and not (
                    text[i] == "*" and text[i + 1] == "/"
                ):
                    i += 1
                i = min(n, i + 2)
                continue
        if ch.isspace():
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _merge_permuter_keep_candidate(
    base_fn: str,
    candidate_fn: str,
    current_fn: str,
    *,
    force: bool,
) -> tuple[str, str, list[tuple[int, str]]]:
    """Merge base->candidate into current for `verify --keep`.

    The first pass is the regular line-oriented 3-way merge. If that reports
    conflicts solely because the real source was reformatted after import, the
    canonical base/current functions still match; in that case taking the
    candidate is safe because there are no semantic current-side edits to
    preserve.
    """
    merged_fn, conflicts = _merge3_function(base_fn, candidate_fn, current_fn)
    if conflicts and not force:
        if (
            _canonical_c_for_format_merge(base_fn)
            == _canonical_c_for_format_merge(current_fn)
        ):
            return candidate_fn, "format-normalized-replace", []
    strategy = "3-way-merge" if not conflicts else "3-way-merge-forced"
    return merged_fn, strategy, conflicts


@permute_app.command(name="verify")
def verify_perm(
    candidate: Annotated[
        Path,
        typer.Argument(
            help="Path to permuter candidate source (.c file with the "
                 "mutated function). Typically output-NNNN-N/source.c "
                 "from decomp-permuter.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to transfer"),
    ],
    keep: Annotated[
        bool,
        typer.Option(
            "--keep",
            help="If the transfer improves match%, leave the patched source "
                 "in place. By default we always revert (dry-run semantics).",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="When --keep is set, allow overwriting manual edits that "
                 "diverge from the permuter's base.c. Without --force, "
                 "debug permute verify aborts if applying the candidate would silently "
                 "revert commits you made after importing the permuter baseline. "
                 "Has no effect without --keep.",
        ),
    ] = False,
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Minimum improvement (in percentage points) to consider "
                 "the candidate a win. Default 0.05 — small enough to catch "
                 "+0.05-0.09% chain wins permuter often produces, but not "
                 "so small that build-noise registers as a hit.",
        ),
    ] = 0.05,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit verification result as JSON."),
    ] = False,
    keep_failed: Annotated[
        bool,
        typer.Option(
            "--keep-failed",
            help="On compile failure, preserve the failing patched source "
                 "at a temp path (printed in the error message) instead "
                 "of reverting silently. Useful when the candidate is "
                 "promising but the transfer needs manual repair.",
        ),
    ] = False,
    force_schedule: Annotated[
        Optional[str],
        typer.Option(
            "--force-schedule",
            help="Compile the transferred candidate through `debug dump local` "
                 "with this MWCC schedule override before measuring match%. "
                 "Format matches `debug dump local --force-schedule`, e.g. "
                 "'lwz:0x74>0x70'.",
        ),
    ] = None,
    force_schedule_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-schedule-fn",
            help="Scope --force-schedule to a function. Defaults to the "
                 "verified --function when --force-schedule is set.",
        ),
    ] = None,
    candidate_timeout: Annotated[
        float,
        typer.Option(
            "--candidate-timeout",
            help="Build/report timeout in seconds for the transferred "
                 "candidate (0 disables).",
        ),
    ] = 120.0,
) -> None:
    """Tier 7a: apply a permuter candidate to the real source and verify.

    The permuter preprocesses its base.c (macro expansion, header merging),
    so a winning candidate doesn't always transfer cleanly. This command:

      1. Extracts the target function from the candidate source
      2. Patches it into the real source tree
      3. Runs `ninja <obj>` to rebuild
      4. Reads the fresh fuzzy_match_percent from report.json
      5. Reports the delta vs. pre-patch baseline

    By default the patched source is REVERTED at the end regardless of
    outcome — pass --keep to leave a winning transfer applied.

    Safe-keep behaviour: when --keep is set and a permuter base.c is found
    (candidate.parent.parent/base.c), debug permute verify performs a 3-way merge
    instead of a full replace — it applies the *diff* from base.c to the
    candidate onto the current real source.  If the merge conflicts (e.g.
    you edited the same lines the permuter mutated), the command aborts
    without writing anything.  Pass --force to fall back to a full replace
    when a merge conflict is detected.
    """
    melee_root = DEFAULT_MELEE_ROOT
    if not candidate.exists():
        typer.echo(f"candidate not found: {candidate}", err=True)
        raise typer.Exit(2)

    # Locate the real source file via report.json.
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"function not found in report.json: {function}\n"
            f"(report.json may be stale; try `ninja build/GALE01/report.json`)",
            err=True,
        )
        raise typer.Exit(2)
    # checkdiff convention: unit paths are relative to src/
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        typer.echo(f"target source not found: {target_path}", err=True)
        raise typer.Exit(2)

    # Baseline match%.
    baseline_pct = _get_match_pct(function, melee_root)
    if not json_out:
        print(f"Function:       {function}")
        print(f"Real source:    {target_path}")
        print(f"Candidate:      {candidate}")
        print(f"Baseline match: {baseline_pct:.2f}%" if baseline_pct is not None
              else "Baseline match: (unknown)")

    candidate_text = candidate.read_text()
    target_text = target_path.read_text()
    if force_schedule:
        force_schedule = _validate_force_schedule(force_schedule)
        if force_schedule_fn is None:
            force_schedule_fn = function
    if force_schedule_fn:
        if any(c in force_schedule_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-schedule-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
    compile_timeout = None if candidate_timeout <= 0 else candidate_timeout

    base_text_for_audit = candidate_audit.read_candidate_base_text(candidate.parent)
    if base_text_for_audit is None:
        base_text_for_audit = target_text
    audit_report = candidate_audit.audit_candidate_source(
        candidate_text,
        base_text=base_text_for_audit,
    )
    source_risks = candidate_audit.risks_to_dicts(audit_report.risks)
    semantic_risk_bucket = audit_report.semantic_risk_bucket
    if audit_report.should_reject:
        diagnostic = _format_permuter_candidate_audit_diagnostic(
            audit_report,
            command="verify-perm",
            candidate=candidate,
        )
        _write_permuter_candidate_status(
            candidate,
            status=audit_report.status,
            function=function,
            first_diag=diagnostic,
            risks=audit_report.risks,
            semantic_risk_bucket=semantic_risk_bucket,
            source="verify",
        )
        if json_out:
            print(json.dumps({
                "success": False,
                "status": audit_report.status,
                "semantic_risk_bucket": semantic_risk_bucket,
                "reason": audit_report.risks[0].kind if audit_report.risks else None,
                "placeholders": [
                    {"name": name, "count": count}
                    for name, count in _permuter_placeholder_hits(candidate_text)
                ],
                "source_risks": source_risks,
                "message": diagnostic,
                "candidate": str(candidate),
            }, indent=2))
        else:
            typer.echo(f"\n{diagnostic}", err=True)
        raise typer.Exit(7)
    if audit_report.risks and not json_out:
        print(
            _format_permuter_candidate_audit_diagnostic(
                audit_report,
                command="verify-perm",
                candidate=candidate,
            ),
            file=sys.stderr,
        )

    # Locate which side the function is missing in for a clearer message.
    from ..mwcc_debug.source_patch import find_function as _find_fn
    cand_span = _find_fn(candidate_text, function)
    target_span = _find_fn(target_text, function)
    if cand_span is None and target_span is None:
        typer.echo(
            f"function '{function}' not found in EITHER candidate or target.\n"
            f"  Candidate: {candidate}\n"
            f"  Target:    {target_path}\n"
            f"Maybe the function name is misspelled, or both sources were "
            f"renamed.",
            err=True,
        )
        raise typer.Exit(3)
    if cand_span is None:
        typer.echo(
            f"function '{function}' is in target but NOT in candidate.\n"
            f"  Candidate: {candidate}\n"
            f"This usually means the permuter mutated a different function "
            f"in the same TU. Check the candidate source manually:\n"
            f"  grep -n '^[A-Za-z_][A-Za-z_0-9 *]*(' {candidate}",
            err=True,
        )
        raise typer.Exit(3)
    if target_span is None:
        typer.echo(
            f"function '{function}' is in candidate but NOT in target.\n"
            f"  Target: {target_path}\n"
            f"This usually means the function was renamed in the real tree, "
            f"or doesn't exist yet. Verify with:\n"
            f"  grep -n '{function}' {target_path}",
            err=True,
        )
        raise typer.Exit(3)
    # --- 3-way merge / divergence check (when --keep is set) ---
    # When --keep is set, a full replacement of the function body silently
    # discards any manual edits made AFTER the permuter's base.c was created.
    # To prevent this:
    #   1. If base.c exists (candidate.parent.parent/base.c), perform a 3-way
    #      merge: apply the diff (base → candidate) to the current real source.
    #      Conflicts abort (require --force for unsafe full-replace).
    #   2. If base.c doesn't exist but the candidate's function differs from
    #      the current real source's function at lines NOT covered by the
    #      permutation, warn loudly and require --force to proceed.
    _merge_result: Optional[str] = None  # merged target text (if 3-way used)
    _merge_strategy: str = "full-replace"
    if keep:
        base_c_path = candidate.parent.parent / "base.c"
        if base_c_path.exists():
            from ..mwcc_debug.source_patch import (
                extract_function as _extract_fn,
                replace_function as _replace_fn,
            )
            base_text = base_c_path.read_text()
            base_fn = _extract_fn(base_text, function)
            cand_fn = _extract_fn(candidate_text, function)
            real_fn = _extract_fn(target_text, function)
            if base_fn is not None and cand_fn is not None and real_fn is not None:
                merged_fn, _merge_strategy, conflicts = (
                    _merge_permuter_keep_candidate(
                        base_fn,
                        cand_fn,
                        real_fn,
                        force=force,
                    )
                )
                if conflicts and not force:
                    # Show which lines conflict so the user knows what to fix
                    conflict_preview = "\n".join(
                        f"  line ~{ln}: {txt!r}" for ln, txt in conflicts[:8]
                    )
                    if len(conflicts) > 8:
                        conflict_preview += f"\n  ... and {len(conflicts) - 8} more"
                    typer.echo(
                        f"\n[verify-perm] ABORTED — 3-way merge conflict detected.\n"
                        f"The candidate mutates {len(conflicts)} line(s) that you "
                        f"also edited manually since the permuter baseline was "
                        f"imported. Applying the full candidate would silently "
                        f"revert those edits.\n\n"
                        f"Conflicting lines (candidate vs your edits):\n"
                        f"{conflict_preview}\n\n"
                        f"Options:\n"
                        f"  1. Re-import the permuter baseline:\n"
                        f"     cd ~/code/decomp-permuter && "
                        f"./import.py <c_file> <target.s> --function {function}\n"
                        f"  2. Apply just the diff manually from:\n"
                        f"     {base_c_path}\n"
                        f"  3. Pass --force to do a full replace (DISCARDS your "
                        f"manual edits in the function body).",
                        err=True,
                    )
                    raise typer.Exit(6)
                _merge_result = _replace_fn(target_text, function, merged_fn)
                if not json_out:
                    if conflicts:
                        print(
                            f"[verify-perm] WARNING: {len(conflicts)} merge conflict(s) "
                            f"resolved by taking candidate version (--force)."
                        )
                    elif _merge_strategy == "format-normalized-replace":
                        print(
                            f"[verify-perm] current source differs from "
                            f"permuter base only by formatting; applying "
                            f"candidate function."
                        )
                    else:
                        print(
                            f"[verify-perm] 3-way merge: applying permuter diff "
                            f"(base→candidate) onto current source."
                        )
            # else: can't extract from base — fall through to full replace
    # --- end merge logic ---

    orig = transfer_candidate(candidate_text, target_path, function)
    if orig is None:
        # Shouldn't happen if both spans are found, but defensive
        typer.echo(
            f"unexpected error: both sides have the function but transfer "
            f"failed. Please report this with the candidate path.",
            err=True,
        )
        raise typer.Exit(3)

    # If 3-way merge produced a result, overwrite the naive full-replace.
    if _merge_result is not None:
        # Belt-and-suspenders: check merged text for placeholder leaks too.
        # The pre-candidate check above covers regions touched by the permuter,
        # but the merge might theoretically introduce a placeholder from the
        # base side in a region outside the target function.
        _merged_ph_hits = _permuter_placeholder_hits(_merge_result)
        if _merged_ph_hits:
            diagnostic = _format_permuter_placeholder_diagnostic(
                _merged_ph_hits,
                command="verify-perm",
            )
            target_path.write_text(orig)
            typer.echo(
                f"\n{diagnostic}\n"
                f"The merged result is corrupt; aborting without writing.",
                err=True,
            )
            raise typer.Exit(7)
        target_path.write_text(_merge_result)

    leave_patched_source = False
    forced_dump_path: Optional[Path] = None
    try:
        # Build the affected .o. checkdiff convention: report.json's unit
        # name doesn't include the "src/" prefix; ninja target does.
        obj_path = f"build/GALE01/src/{unit}.o"
        if not json_out:
            if force_schedule:
                build_label = "debug dump local --force-schedule"
                print(f"\nForce-schedule rebuilding {obj_path}...")
            else:
                build_label = f"ninja {obj_path}"
                print(f"\nRebuilding {obj_path}...")
        if force_schedule:
            fd, tmp_dump = tempfile.mkstemp(
                prefix=f"verify-perm-force-schedule-{function}-",
                suffix=".pcdump.txt",
            )
            os.close(fd)
            forced_dump_path = Path(tmp_dump)
            build_cmd = [
                "python",
                "-m",
                "src.cli",
                "debug",
                "dump",
                "local",
                str(target_path),
                "--output",
                str(forced_dump_path),
                "--no-cache-sync",
                "--function",
                function,
                "--keep-obj",
                obj_path,
                "--force-schedule",
                force_schedule,
            ]
            if force_schedule_fn:
                build_cmd.extend(["--force-schedule-fn", force_schedule_fn])
            build_result = _run_command_with_optional_timeout(
                build_cmd,
                cwd=melee_root / "tools" / "melee-agent",
                timeout=compile_timeout,
            )
            build_label = "debug dump local --force-schedule"
        else:
            build_cmd = ["ninja", obj_path]
            build_result, _retried_build = _run_ninja_with_no_diag_retry(
                build_cmd,
                melee_root,
                timeout=compile_timeout,
            )
            build_label = f"ninja {obj_path}"
        if build_result.returncode != 0:
            build_status = (
                "build-timeout"
                if build_result.returncode == 124
                else "build-failed"
            )
            # Preserve the failing patched source if requested. We use
            # `tempfile.mkstemp` so the path is unique per call — agents
            # can re-run `debug permute verify --keep-failed` for multiple
            # candidates without trampling on each other's saved sources.
            failed_path: Optional[Path] = None
            if keep_failed:
                fd, tmp_path = tempfile.mkstemp(
                    prefix=f"verify-perm-failed-{function}-",
                    suffix=".c",
                )
                try:
                    with os.fdopen(fd, "w") as fh:
                        fh.write(target_path.read_text())
                    failed_path = Path(tmp_path)
                except Exception:
                    # If saving fails we still want the revert to happen.
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    failed_path = None
            err = _extract_ninja_error(build_result.stdout, build_result.stderr)
            first_diag = _failure_diagnostic_or_fallback(
                build_result.stdout,
                build_result.stderr,
                fallback=(
                    _timeout_message(build_cmd, compile_timeout)
                    if build_status == "build-timeout"
                    else (
                        f"{build_label} failed with exit "
                        f"{build_result.returncode} and emitted no compiler "
                        f"diagnostic"
                    )
                ),
            )
            source_reverted = False
            try:
                target_path.write_text(orig)
                source_reverted = target_path.read_text() == orig
            except Exception:
                source_reverted = False
            if json_out:
                _write_permuter_candidate_status(
                    candidate,
                    status=build_status,
                    function=function,
                    first_diag=first_diag,
                    risks=audit_report.risks,
                    semantic_risk_bucket="repo-invalid",
                    source="verify",
                    extra={
                        "returncode": build_result.returncode,
                        "timeout_seconds": compile_timeout,
                    },
                )
                print(json.dumps({
                    "function": function,
                    "candidate": str(candidate),
                    "success": False,
                    "status": build_status,
                    "semantic_risk_bucket": "repo-invalid",
                    "baseline_pct": baseline_pct,
                    "returncode": build_result.returncode,
                    "timeout_seconds": compile_timeout,
                    "first_diag": first_diag,
                    "error": err,
                    "failed_path": str(failed_path) if failed_path else None,
                    "source_reverted": source_reverted,
                    "source_risks": source_risks,
                }, indent=2))
                raise typer.Exit(4)
            _write_permuter_candidate_status(
                candidate,
                status=build_status,
                function=function,
                first_diag=first_diag,
                risks=audit_report.risks,
                semantic_risk_bucket="repo-invalid",
                source="verify",
                extra={
                    "returncode": build_result.returncode,
                    "timeout_seconds": compile_timeout,
                },
            )
            extra_lines: list[str] = []
            if first_diag:
                extra_lines.append(f"First diagnostic: {first_diag}")
            if failed_path is not None:
                extra_lines.append(
                    f"Failing source preserved at: {failed_path}"
                )
            elif keep_failed:
                extra_lines.append(
                    "(--keep-failed requested but the save step itself "
                    "failed; source was reverted.)"
                )
            extras_str = ("\n" + "\n".join(extra_lines)) if extra_lines else ""
            failure_label = (
                "timed out"
                if build_status == "build-timeout"
                else f"failed (exit {build_result.returncode})"
            )
            typer.echo(
                f"{build_label} {failure_label}. Relevant output:\n"
                f"{err}{extras_str}\n\n"
                f"Source reverted. The candidate doesn't compile in the real "
                f"tree — typical causes:\n"
                f"  - Permuter's base.c had macros expanded that the real "
                f"tree relies on via #include\n"
                f"  - Missing helper declarations\n"
                f"  - Type mismatches in unrelated decls that the candidate "
                f"introduced\n"
                f"For the full unfiltered ninja output, re-run with the "
                f"`{' '.join(build_cmd)}` command directly.",
                err=True,
            )
            raise typer.Exit(4)

        new_pct, report_diag = _refresh_match_pct_after_successful_build(
            unit,
            function,
            melee_root,
            fast_report=bool(force_schedule),
            timeout=compile_timeout,
        )
        if new_pct is None:
            if json_out:
                _write_permuter_candidate_status(
                    candidate,
                    status="report-read-failed",
                    function=function,
                    first_diag=(
                        report_diag
                        or "could not read fresh match% after build"
                    ),
                    risks=audit_report.risks,
                    semantic_risk_bucket="repo-invalid",
                    source="verify",
                )
                print(json.dumps({
                    "function": function,
                    "candidate": str(candidate),
                    "success": False,
                    "status": "report-read-failed",
                    "semantic_risk_bucket": "repo-invalid",
                    "baseline_pct": baseline_pct,
                    "first_diag": (
                        report_diag
                        or "could not read fresh match% after build"
                    ),
                    "source_reverted": True,
                    "source_risks": source_risks,
                }, indent=2))
            else:
                print(
                    report_diag or "Could not read fresh match% after build.",
                    file=sys.stderr,
                )
            target_path.write_text(orig)
            raise typer.Exit(5)

        delta = new_pct - (baseline_pct or 0.0)
        # Use epsilon to tolerate float-precision noise — e.g., 91.64-91.59
        # is 0.04999999... due to IEEE rounding even though both inputs
        # display as 2-decimal numbers. Without the epsilon a real
        # +0.05 win at threshold 0.05 gets silently dropped.
        improved = delta >= threshold - 1e-9
        kept = improved and keep
        leave_patched_source = kept

        if json_out:
            _write_permuter_candidate_status(
                candidate,
                status="ok",
                function=function,
                risks=audit_report.risks,
                match_pct=new_pct,
                delta=delta,
                semantic_risk_bucket=semantic_risk_bucket,
                source="verify",
                extra={"improved": improved, "kept": kept},
            )
            print(json.dumps({
                "function": function,
                "candidate": str(candidate),
                "status": "ok",
                "semantic_risk_bucket": semantic_risk_bucket,
                "baseline_pct": baseline_pct,
                "new_pct": new_pct,
                "delta": delta,
                "threshold": threshold,
                "improved": improved,
                "kept": kept,
                "source_risks": source_risks,
            }, indent=2))
        else:
            _write_permuter_candidate_status(
                candidate,
                status="ok",
                function=function,
                risks=audit_report.risks,
                match_pct=new_pct,
                delta=delta,
                semantic_risk_bucket=semantic_risk_bucket,
                source="verify",
                extra={"improved": improved, "kept": kept},
            )
            print(f"\nNew match:      {new_pct:.2f}%")
            print(f"Delta:          {delta:+.2f}%")

            if kept:
                print(f"\nCandidate improved match by ≥{threshold:.2f}% — leaving "
                      f"patched source in place ({target_path}).")
            elif improved:
                print(f"\nCandidate improved match by ≥{threshold:.2f}% but "
                      f"--keep was not set — reverting. Re-run with --keep to "
                      f"commit the change.")
            else:
                print(f"\nCandidate did not improve by ≥{threshold:.2f}% — "
                      f"reverting.")

        if not kept:
            target_path.write_text(orig)
            # Rebuild to restore prior state in report.json
            _run_ninja_with_no_diag_retry(
                ["ninja", obj_path, "build/GALE01/report.json"],
                melee_root,
                timeout=compile_timeout,
            )
    finally:
        # Always restore the source unless this invocation intentionally kept
        # an improving candidate. This also covers typer.Exit/SystemExit paths.
        if not leave_patched_source:
            try:
                if target_path.read_text() != orig:
                    target_path.write_text(orig)
            except Exception:
                pass
        if forced_dump_path is not None:
            try:
                forced_dump_path.unlink()
            except OSError:
                pass


def _build_and_match(
    unit: str,
    function: str,
    melee_root: Path,
    *,
    fast_report: bool = True,
) -> Optional[float]:
    """Rebuild a unit's .o and return the function's fuzzy_match_percent.

    Two paths to regenerate the per-function score after building:

      fast_report=True (default): call `objdiff-cli report generate`
        directly. Skips ninja's dependency-graph traversal and avoids
        re-checking unrelated files. Same metric (fuzzy_match_percent)
        as the slow path. Typical speedup: ~0.7sec vs ~2-3sec.

      fast_report=False: run `ninja build/GALE01/report.json` (slow
        path). Use this when ninja's full dependency reasoning is
        needed — e.g. after a configure change.

    Returns None on build failure.
    """
    pct, _diagnostic = _build_and_match_with_diagnostic(
        unit,
        function,
        melee_root,
        fast_report=fast_report,
    )
    return pct


def _build_and_match_with_diagnostic(
    unit: str,
    function: str,
    melee_root: Path,
    *,
    fast_report: bool = True,
) -> tuple[Optional[float], Optional[str]]:
    """Rebuild a unit and return match percent plus failure diagnostic."""
    obj_path = f"build/GALE01/src/{unit}.o"
    r, _retried = _run_ninja_with_no_diag_retry(
        ["ninja", obj_path],
        melee_root,
    )
    if r.returncode != 0:
        return None, _failure_diagnostic_or_fallback(
            r.stdout,
            r.stderr,
            fallback=f"ninja {obj_path} failed with exit {r.returncode}",
        )

    pct, _diagnostic = _refresh_match_pct_after_successful_build(
        unit,
        function,
        melee_root,
        fast_report=fast_report,
    )
    return pct, _diagnostic


def _run_command_with_optional_timeout(
    cmd: list[str],
    *,
    cwd: Path,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command, killing its process tree when a timeout is supplied."""
    try:
        if timeout is not None:
            return _run_with_process_group_timeout(
                cmd,
                cwd=cwd,
                timeout=timeout,
            )
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return subprocess.CompletedProcess(
            cmd,
            124,
            stdout,
            (stderr + "\n" + _timeout_message(cmd, timeout)).strip(),
        )


def _run_ninja_with_no_diag_retry(
    cmd: list[str],
    melee_root: Path,
    *,
    timeout: float | None = None,
) -> tuple[subprocess.CompletedProcess[str], bool]:
    """Run a ninja command, retrying once if it fails without diagnostics."""
    def _run_once() -> subprocess.CompletedProcess[str]:
        return _run_command_with_optional_timeout(
            cmd,
            cwd=melee_root,
            timeout=timeout,
        )

    result = _run_once()
    if result.returncode == 0:
        return result, False
    if result.returncode == 124:
        return result, False
    if _extract_first_diagnostic(result.stdout, result.stderr) is not None:
        return result, False
    retry = _run_once()
    return retry, True


def _timeout_message(cmd: list[str], timeout: float | None) -> str:
    if timeout is None:
        return f"timed out running {' '.join(cmd)}"
    return f"timed out after {timeout:g}s running {' '.join(cmd)}"


def _failure_diagnostic_or_fallback(
    stdout: str,
    stderr: str,
    *,
    fallback: str,
) -> str:
    first_diag = _extract_first_diagnostic(stdout, stderr)
    diagnostic = _extract_ninja_error(stdout, stderr, max_lines=8)
    if first_diag:
        if diagnostic and diagnostic != "(no error lines captured)":
            return diagnostic
        return first_diag
    if diagnostic and diagnostic != "(no error lines captured)":
        return diagnostic
    return fallback


def _get_match_pct_with_report_retry(
    function: str,
    melee_root: Path,
    *,
    attempts: int = 3,
    delay_seconds: float = 0.05,
) -> tuple[Optional[float], Optional[str]]:
    """Read match percent, retrying transient partial report.json reads."""
    last_error: Optional[BaseException] = None
    report_path = melee_root / "build" / "GALE01" / "report.json"
    for attempt in range(1, attempts + 1):
        try:
            return _get_match_pct(function, melee_root), None
        except (json.JSONDecodeError, OSError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(delay_seconds)
    if last_error is None:
        return None, None
    return (
        None,
        f"could not read {report_path} after {attempts} attempts: "
        f"{type(last_error).__name__}: {last_error}",
    )


def _refresh_match_pct_after_successful_build(
    unit: str,
    function: str,
    melee_root: Path,
    *,
    fast_report: bool = True,
    timeout: float | None = None,
) -> tuple[Optional[float], Optional[str]]:
    """Regenerate report.json after an object build and read match percent."""
    objdiff_bin = melee_root / "build" / "tools" / "objdiff-cli"
    if fast_report and objdiff_bin.exists():
        report_path = melee_root / "build" / "GALE01" / "report.json"
        cmd = [
            str(objdiff_bin),
            "report",
            "generate",
            "-o",
            str(report_path),
            "-f",
            "json",
        ]
        try:
            r = subprocess.run(
                cmd,
                cwd=melee_root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return None, _timeout_message(cmd, timeout)
        if r.returncode != 0:
            return None, _failure_diagnostic_or_fallback(
                r.stdout,
                r.stderr,
                fallback=(
                    f"objdiff report generation failed with exit "
                    f"{r.returncode}"
                ),
            )
        pct, read_diag = _get_match_pct_with_report_retry(
            function,
            melee_root,
        )
        if read_diag:
            return None, read_diag
        if pct is None:
            return None, f"report.json did not contain match percent for {function}"
        return pct, None

    # Slow path: full ninja regen.
    cmd = ["ninja", "build/GALE01/report.json"]
    try:
        r = subprocess.run(
            cmd,
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, _timeout_message(cmd, timeout)
    if r.returncode != 0:
        return None, _failure_diagnostic_or_fallback(
            r.stdout,
            r.stderr,
            fallback=f"report.json regeneration failed with exit {r.returncode}",
        )
    pct, read_diag = _get_match_pct_with_report_retry(function, melee_root)
    if read_diag:
        return None, read_diag
    if pct is None:
        return None, f"report.json did not contain match percent for {function}"
    return pct, None


def _recheck_transferred_candidate_match(
    candidate_text: str,
    target_path: Path,
    function: str,
    unit: str,
    melee_root: Path,
    original_source: str,
    *,
    timeout: float | None = None,
) -> tuple[Optional[float], Optional[str]]:
    """Re-measure a candidate from clean source using function-only transfer."""
    obj_path = f"build/GALE01/src/{unit}.o"
    target_path.write_text(original_source)
    if transfer_candidate(candidate_text, target_path, function) is None:
        return None, "function not in candidate during transfer recheck"
    try:
        build_result, retried_build = _run_ninja_with_no_diag_retry(
            ["ninja", obj_path],
            melee_root,
            timeout=timeout,
        )
        if build_result.returncode != 0:
            return None, _failure_diagnostic_or_fallback(
                build_result.stdout,
                build_result.stderr,
                fallback=(
                    f"ninja {obj_path} failed during transfer recheck "
                    f"with exit {build_result.returncode}"
                    + (" after retry" if retried_build else "")
                    + " and emitted no compiler diagnostic"
                ),
            )
        return _refresh_match_pct_after_successful_build(
            unit,
            function,
            melee_root,
            timeout=timeout,
        )
    finally:
        target_path.write_text(original_source)


@mutate_app.command(name="decl-orders")
def enumerate_decl_orders(
    function: Annotated[
        str,
        typer.Argument(help="Function name to enumerate orderings for"),
    ],
    strategy: Annotated[
        str,
        typer.Option(
            "--strategy",
            help="Which orderings to try: 'promote' (move each var to "
                 "first; N candidates), 'demote' (move each to last; N), "
                 "'swap' (adjacent pair swaps; N-1), 'all' (promote+demote+"
                 "swap), or 'full' (every permutation; N! — refuses for N>7).",
        ),
    ] = "promote",
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Minimum improvement (percentage points) to consider a win. "
                 "Default 0.05 — catches the +0.05-0.09% chain wins that "
                 "matching agents observed permuter producing.",
        ),
    ] = 0.05,
    keep_best: Annotated[
        bool,
        typer.Option(
            "--keep-best",
            help="If the best ordering improves match% by ≥threshold, "
                 "leave it applied. Default reverts to original.",
        ),
    ] = False,
    iterate: Annotated[
        bool,
        typer.Option(
            "--iterate",
            help="After finding the best ordering, apply it and re-run "
                 "the enumeration from the new baseline. Repeats until no "
                 "improvement found (or --iterate-max reached). Stacks "
                 "small wins below the per-iteration threshold. Implies "
                 "--keep-best.",
        ),
    ] = False,
    iterate_max: Annotated[
        int,
        typer.Option(
            "--iterate-max",
            help="Cap on --iterate rounds. Prevents infinite loops if a "
                 "win-finding cycle emerges. Default 10.",
        ),
    ] = 10,
    iterate_threshold: Annotated[
        float,
        typer.Option(
            "--iterate-threshold",
            help="Per-round threshold when --iterate is set. Smaller than "
                 "--threshold lets the loop stack micro-wins (0.04% type) "
                 "that don't qualify as a single big win.",
        ),
    ] = 0.01,
    scope: Annotated[
        Optional[str],
        typer.Option(
            "--scope",
            help="Optional scope_path display string. When omitted, "
                 "enumerates the function-top scope first.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit results as JSON."),
    ] = False,
) -> None:
    """Tier 7b: enumerate local-decl orderings, find ones that improve match%.

    Most "stuck near 99%" cases have a 1-line declaration-reorder fix that
    permuter eventually finds at ~2000 iterations. This command brute-forces
    the small decl-order search space directly.

    Strategies (in order of cost):

      promote (default): for each of N locals, try promoting to position 0
        → N candidates, ~N×6sec
      demote: each → position N-1 → N candidates
      swap: each adjacent pair swap → N-1 candidates
      all: promote + demote + swap → ~3N candidates
      full: all N! permutations (refuses for N>7 — would take hours)

    Default reverts after enumeration. Pass --keep-best to apply the best
    winning ordering.
    """
    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"function not found in report.json: {function}", err=True)
        raise typer.Exit(2)
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        typer.echo(f"target source not found: {target_path}", err=True)
        raise typer.Exit(2)

    orig = target_path.read_text()
    scope_map = get_decl_names_by_scope(orig, function)
    available_scopes = [
        {
            "scope": "/".join(scope_path),
            "names": names,
            "declaration_count": len(names),
            "is_top_level": scope_path == (function,),
        }
        for scope_path, names in scope_map.items()
    ]
    selected_scope_reason = "explicit" if scope else "function-top"
    if scope:
        selected_scope = tuple(scope.split("/"))
    else:
        selected_scope = (function,)
        if not scope_map.get(selected_scope):
            nested_scopes = [
                scope_path
                for scope_path, names in scope_map.items()
                if scope_path != (function,) and len(names) >= 2
            ]
            if not nested_scopes:
                nested_scopes = [
                    scope_path
                    for scope_path in scope_map
                    if scope_path != (function,)
                ]
            if nested_scopes:
                selected_scope = nested_scopes[0]
                selected_scope_reason = "auto-nested"
    names = scope_map.get(selected_scope)
    if not names:
        available = ", ".join(
            f"{item['scope']} ({len(item['names'])} decls)"
            for item in available_scopes
        ) or "none"
        typer.echo(
            f"could not find a declaration block in {function} scope "
            f"{'/'.join(selected_scope)}. Available scopes: {available}.",
            err=True,
        )
        raise typer.Exit(3)
    n = len(names)

    # Build the list of (label, permutation) candidates to try.
    candidates: list[tuple[str, list[int]]] = []
    if strategy in ("promote", "all"):
        for k in range(n):
            if k == 0:
                continue  # already first — identity
            perm = [k] + [i for i in range(n) if i != k]
            candidates.append((f"promote {names[k]}", perm))
    if strategy in ("demote", "all"):
        for k in range(n):
            if k == n - 1:
                continue
            perm = [i for i in range(n) if i != k] + [k]
            candidates.append((f"demote {names[k]}", perm))
    if strategy in ("swap", "all"):
        for k in range(n - 1):
            perm = list(range(n))
            perm[k], perm[k + 1] = perm[k + 1], perm[k]
            candidates.append((f"swap {names[k]} <-> {names[k+1]}", perm))
    if strategy == "full":
        if n > 7:
            typer.echo(
                f"--strategy full refused: {n} locals = {n}! permutations. "
                f"Use --strategy all for a tractable subset.",
                err=True,
            )
            raise typer.Exit(4)
        from itertools import permutations
        for p in permutations(range(n)):
            if list(p) == list(range(n)):
                continue
            candidates.append((f"order {list(p)}", list(p)))
    if not candidates and strategy not in ("promote", "demote", "swap", "all", "full"):
        typer.echo(f"unknown --strategy: {strategy}", err=True)
        raise typer.Exit(2)
    if not candidates:
        typer.echo("no candidate orderings to try (function may have only 1 local).")
        return

    # Baseline match%. Rebuild the current source first so the result table
    # compares candidates against the actual working tree, not a stale report.
    baseline = _build_and_match(unit, function, melee_root)
    if baseline is None:
        baseline = _get_match_pct(function, melee_root) or 0.0
    if not json_out:
        print(f"Function:    {function} ({n} locals: {', '.join(names)})")
        print(f"Source:      {target_path}")
        print(f"Scope:       {'/'.join(selected_scope)} ({selected_scope_reason})")
        print(f"Strategy:    {strategy} ({len(candidates)} candidates)")
        print(f"Baseline:    {baseline:.2f}%")
        if iterate:
            print(f"Mode:        --iterate (max {iterate_max} rounds, "
                  f"per-round threshold {iterate_threshold:.3f}%)")
        print()

    # When --iterate is set we want to stack wins. Each round:
    #   1. Re-read `current` as the baseline-of-the-round
    #   2. Sweep all candidates against it
    #   3. If best > iterate_threshold, apply it as the new baseline
    #   4. Else, terminate the iterate loop
    # If --iterate is NOT set, we just do one round and use the larger
    # --threshold to decide whether to apply (controlled by --keep-best).

    def run_one_round(round_idx: int, current_text: str,
                      round_baseline: float, round_threshold: float
                      ) -> tuple[Optional[str], float, Optional[list[int]], list[dict]]:
        """Run one enumeration sweep starting from `current_text`.

        Returns (best_label, best_pct, best_perm, per-candidate results).
        """
        r_results: list[dict] = []
        r_best_pct = round_baseline
        r_best_label: Optional[str] = None
        r_best_perm: Optional[list[int]] = None

        if iterate and not json_out:
            print(f"== Round {round_idx} ==")
            print(f"  Baseline: {round_baseline:.2f}%")

        for candidate_idx, (label, perm) in enumerate(candidates, start=1):
            if json_out:
                print(
                    f"[decl-orders] {candidate_idx}/{len(candidates)} {label}",
                    file=sys.stderr,
                    flush=True,
                )
            patched = reorder_decls_in_function_scope(
                current_text, function, selected_scope, perm,
            )
            if patched is None:
                reason = explain_decl_reorder_skip(
                    current_text, function, selected_scope, perm,
                )
                detail = f"skipped: {reason}" if reason else "skipped"
                if not json_out:
                    print(f"  {label}: {detail}")
                r_results.append({
                    "label": label,
                    "match_pct": None,
                    "delta": None,
                    "skipped": True,
                    "skip_reason": reason,
                })
                continue
            target_path.write_text(patched)
            pct = _build_and_match(unit, function, melee_root)
            target_path.write_text(current_text)  # revert before next iter
            if pct is None:
                if not json_out:
                    print(f"  {label}: BUILD FAILED")
                r_results.append({"label": label, "match_pct": None,
                                  "delta": None})
                continue
            delta = pct - round_baseline
            r_results.append({"label": label, "match_pct": pct,
                              "delta": delta})
            tag = ""
            # epsilon: 91.64-91.59 = 0.04999... in IEEE float; without
            # tolerance a real +0.05 win at threshold 0.05 silently drops.
            if delta >= round_threshold - 1e-9:
                tag = "  WIN"
                if pct > r_best_pct:
                    r_best_pct = pct
                    r_best_label = label
                    r_best_perm = perm
            elif delta > 0:
                tag = "  (improved)"
            elif delta < 0:
                tag = "  (worse)"
            if not json_out:
                print(f"  {label}: {pct:.2f}%  delta={delta:+.2f}%{tag}")
        return r_best_label, r_best_pct, r_best_perm, r_results

    all_rounds: list[dict] = []
    current = orig
    current_pct = baseline
    applied_chain: list[str] = []  # labels of rounds that we kept
    applied_single_best = False

    try:
        if not iterate:
            # Single sweep — preserve previous behavior.
            best_label, best_pct, best_perm, results = run_one_round(
                round_idx=0,
                current_text=current,
                round_baseline=baseline,
                round_threshold=threshold,
            )
            all_rounds.append({
                "round": 0,
                "baseline_pct": baseline,
                "best_label": best_label,
                "best_pct": best_pct,
                "results": results,
            })
            if keep_best and best_label is not None and best_perm is not None:
                patched = reorder_decls_in_function_scope(
                    current, function, selected_scope, best_perm,
                )
                if patched is not None:
                    current = patched
                    applied_single_best = True
        else:
            # Iterate mode: each round must clear iterate_threshold to
            # continue. We always commit the win for the round (writes
            # back to disk before next sweep).
            for r_idx in range(iterate_max):
                r_best_label, r_best_pct, r_best_perm, r_results = (
                    run_one_round(
                        round_idx=r_idx,
                        current_text=current,
                        round_baseline=current_pct,
                        round_threshold=iterate_threshold,
                    )
                )
                all_rounds.append({
                    "round": r_idx,
                    "baseline_pct": current_pct,
                    "best_label": r_best_label,
                    "best_pct": r_best_pct,
                    "results": r_results,
                })
                if r_best_label is None or r_best_perm is None:
                    if not json_out:
                        print(f"  No more wins; stopping iterate loop.")
                    break
                # Apply the round's winner and use it as the next baseline
                patched = reorder_decls_in_function_scope(
                    current, function, selected_scope, r_best_perm,
                )
                if patched is None:
                    if not json_out:
                        print(f"  Could not re-apply best perm "
                              f"({r_best_label}); stopping.")
                    break
                current = patched
                current_pct = r_best_pct
                applied_chain.append(r_best_label)
                if not json_out:
                    print(f"  ** Applied {r_best_label}; new baseline "
                          f"{current_pct:.2f}%")
                    print()
            # After the loop, `current` holds the latest patched text.
            # The top-level best_pct/best_label reflect the cumulative
            # state vs the original baseline.
            best_pct = current_pct
            best_label = (" + ".join(applied_chain)
                          if applied_chain else None)
            best_perm = None  # n/a in iterate mode — we already applied
    finally:
        # Decide whether the disk-state to keep is the accumulated `current`
        # (iterate mode with at least one winning round; or single-sweep
        # with --keep-best after a successful win) or the original.
        had_wins = bool(applied_chain) if iterate else (
            applied_single_best
        )
        keep_final = had_wins and current != orig
        if keep_final:
            target_path.write_text(current)
            if iterate and not json_out:
                typer.echo(
                    f"[mwcc_debug] iterate kept {len(applied_chain)} "
                    f"winning round(s).",
                    err=True,
                )
        else:
            # No wins (or single-sweep without --keep-best). Always revert
            # to the original, regardless of any intermediate writes the
            # candidate loop might have done. The per-candidate revert in
            # run_one_round should leave disk at the round's baseline
            # already, but write `orig` defensively so we're independent
            # of that contract.
            current_disk = target_path.read_text()
            if current_disk != orig:
                target_path.write_text(orig)
                if not json_out:
                    typer.echo(
                        f"[mwcc_debug] reverted source (no wins above "
                        f"threshold).",
                        err=True,
                    )
        subprocess.run(
            ["ninja", f"build/GALE01/src/{unit}.o",
             "build/GALE01/report.json"],
            cwd=melee_root, capture_output=True,
        )

    if json_out:
        print(json.dumps({
            "function": function,
            "scope": "/".join(selected_scope),
            "selected_scope_reason": selected_scope_reason,
            "available_scopes": available_scopes,
            "baseline_pct": baseline,
            "best_label": best_label,
            "best_pct": best_pct,
            "iterate": iterate,
            "applied_chain": applied_chain if iterate else [],
            "rounds": all_rounds,
        }, indent=2))
        return

    print()
    if best_label is None:
        if iterate:
            print(f"No wins clearing iterate-threshold "
                  f"{iterate_threshold:.3f}% in any round.")
        else:
            print(f"No ordering improved match by ≥{threshold:.2f}%.")
        return
    print(f"Best: {best_label} → {best_pct:.2f}% "
          f"(delta {best_pct - baseline:+.2f}%)")

    if iterate:
        print(f"Applied {len(applied_chain)} round(s) to {target_path}. "
              f"Verify with `git diff`.")
    elif keep_best and applied_single_best:
        print(f"Applied to {target_path}. Verify with `git diff`.")
    else:
        print("Source reverted. Re-run with --keep-best to apply the win.")


@util_app.command(name="patterns")
def pattern_catalog(
    name: Annotated[
        Optional[str],
        typer.Argument(help="Optional pattern name. If omitted, lists all "
                            "patterns."),
    ] = None,
    search: Annotated[
        Optional[str],
        typer.Option("--search", help="Filter the list by substring match "
                                      "against pattern name/title."),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit catalog as JSON."),
    ] = False,
) -> None:
    """Tier 7c: dump the catalog of recurring MWCC mutation patterns.

    The catalog captures the small family of source mutations that
    permuter keeps rediscovering across stuck functions — alias-split,
    decl-order, u8↔u32 widening, drop-variadic-cast, subexpr-extract,
    chained-init. Use as a starting point when staring at a stuck
    function; `debug inspect guide` will also cite pattern names directly.

    Without arguments: lists all patterns with title and one-liner summary.
    With `<name>`: shows the full pattern entry (when-to-try, example
    before/after, mechanism).
    """
    if name is not None:
        p = PATTERNS.get(name)
        if p is None:
            available = ", ".join(sorted(PATTERNS.keys()))
            typer.echo(
                f"unknown pattern: {name}\nAvailable: {available}",
                err=True,
            )
            raise typer.Exit(2)
        if json_out:
            print(json.dumps({
                "name": p.name,
                "title": p.title,
                "summary": p.summary,
                "when_to_try": p.when_to_try,
                "example_before": p.example_before,
                "example_after": p.example_after,
                "mechanism": p.mechanism,
                "addresses": list(p.addresses),
            }, indent=2))
            return
        print(f"Pattern: {p.name}")
        print(f"Title:   {p.title}")
        print(f"Addresses: {', '.join(p.addresses)}")
        print()
        print("Summary:")
        print(f"  {p.summary}")
        print()
        print("When to try:")
        print(f"  {p.when_to_try}")
        print()
        print("Example before:")
        for line in p.example_before.splitlines():
            print(f"  {line}")
        print()
        print("Example after:")
        for line in p.example_after.splitlines():
            print(f"  {line}")
        print()
        print("Mechanism:")
        print(f"  {p.mechanism}")
        return

    patterns = list_patterns()
    if search:
        s = search.lower()
        patterns = [p for p in patterns
                    if s in p.name.lower() or s in p.title.lower()]
        if not patterns:
            print(f"No patterns matched: {search}")
            return

    if json_out:
        print(json.dumps([{
            "name": p.name,
            "title": p.title,
            "summary": p.summary,
            "addresses": list(p.addresses),
        } for p in patterns], indent=2))
        return

    print(f"MWCC mutation pattern catalog ({len(patterns)} entries):\n")
    for p in patterns:
        print(f"  {p.name}")
        print(f"    {p.title}")
        print(f"    Addresses: {', '.join(p.addresses)}")
        print(f"    {p.summary}")
        print()
    print(
        "Run `melee-agent debug util patterns <name>` for full details "
        "(example before/after, mechanism)."
    )


@suggest_app.command(name="casts")
def suggest_casts(
    function: Annotated[
        str,
        typer.Argument(help="Function name to audit"),
    ],
    asm: Annotated[
        bool,
        typer.Option(
            "--asm",
            help="Cross-reference each call-site with the expected ASM "
                 "in build/GALE01/asm/. Detects integer-loaded args that "
                 "the source code wraps in (f32) (and vice versa).",
        ),
    ] = False,
    signedness: Annotated[
        bool,
        typer.Option(
            "--signedness",
            help="Scan the current-vs-expected ASM diff (via checkdiff) "
                 "for compare-opcode signedness mismatches: cmplwi (unsigned) "
                 "where expected has cmpwi (signed), or vice versa. "
                 "Requires the TU's .o to be built (`ninja <unit>.o`). "
                 "This is separate from the source-level cast audit.",
        ),
    ] = False,
    severity: Annotated[
        str,
        typer.Option(
            "--severity",
            help="Filter by severity: high/medium/low/all (default: medium+).",
        ),
    ] = "medium",
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit warnings as JSON."),
    ] = False,
) -> None:
    """Tier 7d: static lint for cast-mismatch and signedness patterns.

    Surfaces explicit casts on function arguments that are likely wrong —
    especially the `(f32)` cast on integer values that the matching agent
    identified as the `drop-variadic-cast` pattern in their session
    findings.

    Three-tier classification for cast warnings:
      HIGH — cast on a value the function declares as integer
      MEDIUM — cast on a value that LOOKS integer but can't be proven
      LOW — every other explicit cast (for general audit)

    With `--asm`, also cross-references the call site against
    build/GALE01/asm/<unit>.s to identify args loaded as integers when
    the source casts to float (and vice versa).

    With `--signedness`, scans the current-vs-expected ASM diff for
    compare-opcode mismatches: cmplwi (unsigned) where expected has cmpwi
    (signed), or vice versa. Useful when `u8 limit` → `int limit` gives
    a match improvement that the source-level cast audit misses.
    """
    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"function not found in report.json: {function}", err=True)
        raise typer.Exit(2)
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        typer.echo(f"target source not found: {target_path}", err=True)
        raise typer.Exit(2)

    text = target_path.read_text()
    warnings = audit_function_casts(text, function)

    # Severity filter
    sev_order = {"high": 0, "medium": 1, "low": 2}
    min_level = sev_order.get(severity, 1) if severity != "all" else 99
    if severity != "all":
        warnings = [w for w in warnings if sev_order.get(w.severity, 99) <= min_level]

    asm_contexts: dict = {}
    if asm:
        asm_path = melee_root / "build" / "GALE01" / "asm" / f"{unit}.s"
        if not asm_path.exists():
            typer.echo(
                f"asm file not found: {asm_path}\n"
                f"(try `ninja {asm_path.relative_to(melee_root)}`)",
                err=True,
            )
        else:
            from ..mwcc_debug.source_patch import find_function as _find_fn
            span = _find_fn(text, function)
            if span:
                fn_text = text[span.sig_start : span.full_end]
                sites = find_call_sites(fn_text)
                contexts = crossref_with_asm(sites, asm_path, function)
                # Index by (call_target, source_line) for warning correlation
                for ctx in contexts:
                    key = (ctx.source_site.call_target, ctx.source_site.line)
                    asm_contexts[key] = ctx

    # Signedness check: diff current compiled vs expected, look for
    # cmplwi/cmpwi (unsigned/signed) opcode disagreements.
    sign_mismatches = []
    if signedness:
        try:
            proc = subprocess.run(
                ["python", "tools/checkdiff.py", function,
                 "--format", "json", "--no-build"],
                cwd=melee_root, capture_output=True, text=True, timeout=60,
                env=_checkdiff_env_without_fingerprint(),
            )
            if proc.returncode in (0, 1) and proc.stdout:
                diff_data = json.loads(proc.stdout)
                diff_lines = diff_data.get("diff", [])
                if diff_lines:
                    sign_mismatches = detect_signedness_mismatches(diff_lines)
        except (FileNotFoundError, subprocess.TimeoutExpired,
                json.JSONDecodeError):
            typer.echo(
                "signedness check: checkdiff failed or produced no output",
                err=True,
            )

    if json_out:
        data = []
        for w in warnings:
            entry = {
                "kind": "cast",
                "line": w.line,
                "call_target": w.call_target,
                "arg_index": w.arg_index,
                "cast_type": w.cast_type,
                "inner_expr": w.inner_expr,
                "severity": w.severity,
                "reason": w.reason,
            }
            data.append(entry)
        sign_data = []
        for sm in sign_mismatches:
            sign_data.append({
                "kind": "signedness",
                "current_opcode": sm.current_opcode,
                "expected_opcode": sm.expected_opcode,
                "current_line": sm.current_line,
                "expected_line": sm.expected_line,
                "mismatch_kind": sm.kind,
                "suggestion": sm.suggestion,
            })
        print(json.dumps({
            "function": function,
            "warnings": data,
            "signedness_mismatches": sign_data,
        }, indent=2))
        return

    print(f"Function: {function}")
    print(f"Source:   {target_path}")
    if not warnings:
        print(
            f"No casts at severity≥{severity}. "
            f"(Re-run with --severity all to see all explicit casts.)"
        )
    else:
        print(f"Cast warnings ({len(warnings)} at severity≥{severity}):")
        print()
        for w in warnings:
            marker = {"high": "!!", "medium": "!", "low": "·"}.get(w.severity, " ")
            print(f"  {marker} {target_path}:{w.line}  ({w.severity})")
            print(f"     ({w.cast_type}) {w.inner_expr}  →  "
                  f"{w.call_target}(... arg{w.arg_index} ...)")
            print(f"     {w.reason}")
            if asm:
                key = (w.call_target, w.line - (text[:0].count('\n')))
                # Find any matching context by call target + line proximity
                for (target_name, src_line), ctx in asm_contexts.items():
                    if target_name == w.call_target and ctx.asm_line_idx is not None:
                        kinds = ctx.arg_register_kinds
                        if kinds:
                            kind_str = ", ".join(f"{r}={k}"
                                                 for r, k in sorted(kinds.items()))
                            print(f"     ASM arg loads: {kind_str}")
                        break
            print()

    if sign_mismatches:
        print(f"Signedness mismatches ({len(sign_mismatches)} compare-opcode disagreements):")
        print()
        for sm in sign_mismatches:
            print(f"  !! signedness-type-mismatch")
            print(f"     current:  {sm.current_line}")
            print(f"     expected: {sm.expected_line}")
            print(f"     {sm.suggestion}")
            print()
    elif signedness:
        print("No signedness mismatches detected.")


@permute_app.command(name="triage")
def triage_perm(
    perm_dir: Annotated[
        Path,
        typer.Argument(
            help="Directory containing permuter output subdirs "
                 "(output-NNNN-N/) each with a source.c.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to verify"),
    ],
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            help="Stop after evaluating this many candidates "
                 "(0 = no limit).",
        ),
    ] = 0,
    top_k: Annotated[
        int,
        typer.Option(
            "--top",
            help="Show the top K results in the summary.",
        ),
    ] = 5,
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Minimum improvement (percentage points) to consider a "
                 "win. Default 0.05 — catches the +0.05-0.09% chain "
                 "wins that hide at the previous 0.10 default.",
        ),
    ] = 0.05,
    apply_best: Annotated[
        bool,
        typer.Option(
            "--apply-best",
            help="If the best transferring candidate clears --threshold, "
                 "leave it applied. Default reverts at the end.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit results as JSON."),
    ] = False,
    keep_failed: Annotated[
        bool,
        typer.Option(
            "--keep-failed",
            help="For each compile failure, preserve the failing patched "
                 "source at a unique temp path (paths printed alongside "
                 "the BUILD FAILED status). Lets you re-attempt promising "
                 "candidates with targeted fixes instead of re-running "
                 "permuter.",
        ),
    ] = False,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume",
            "--skip-status-json",
            help="Skip candidates with terminal status sidecars before "
                 "applying --max-candidates.",
        ),
    ] = False,
    order: Annotated[
        str,
        typer.Option(
            "--order",
            help="Candidate traversal order: name, newest, score-desc, or "
                 "score-asc. Ordering is applied before resume filtering and "
                 "--max-candidates.",
        ),
    ] = "name",
    candidate_timeout: Annotated[
        float,
        typer.Option(
            "--candidate-timeout",
            help="Per-candidate build/report timeout in seconds (0 disables).",
        ),
    ] = 120.0,
) -> None:
    """Tier 7e: batch-triage decomp-permuter output candidates.

    The matching agent's session noted that many permuter "winners"
    (score=N where N < baseline) don't transfer to the real source tree
    because permuter preprocesses base.c (header merging, macro
    expansion). This command iterates each `output-*/source.c` in a
    permuter run, applies the candidate to the real tree via the same
    transfer logic as `debug permute verify`, runs `ninja` + reads
    fuzzy_match_percent, and produces a ranked list of which candidates
    actually improve real-tree match%.

    Per-candidate cost: ~5-10 seconds (one ninja + report.json). With
    permuter generating ~100 winning candidates per session, total
    triage time is typically a few minutes.

    Designed as the v1 of permuter integration. v2 would be a permuter
    `--external-scorer` patch that calls our scoring per-iteration
    instead of per-winner.
    """
    melee_root = DEFAULT_MELEE_ROOT
    if not perm_dir.is_dir():
        typer.echo(f"not a directory: {perm_dir}", err=True)
        raise typer.Exit(2)

    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"function not found in report.json: {function}", err=True)
        raise typer.Exit(2)
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        typer.echo(f"target source not found: {target_path}", err=True)
        raise typer.Exit(2)

    # Locate candidate sources. Try the common permuter layouts:
    #   <perm-dir>/output-NNNN-N/source.c     (default)
    #   <perm-dir>/<anything>/source.c
    candidate_paths: list[Path] = []
    for entry in sorted(perm_dir.iterdir()):
        if not entry.is_dir():
            continue
        src = entry / "source.c"
        if src.exists():
            candidate_paths.append(src)
    if not candidate_paths:
        # Fallback: maybe the perm-dir itself is one output (no subdirs)
        direct_src = perm_dir / "source.c"
        if direct_src.exists():
            candidate_paths = [direct_src]
    if not candidate_paths:
        typer.echo(
            f"no candidate sources found under {perm_dir}\n"
            f"(expected output-NNNN-N/source.c or source.c)",
            err=True,
        )
        raise typer.Exit(3)
    try:
        candidate_paths = _sort_permuter_candidate_paths(
            candidate_paths,
            order=order,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)
    skipped_candidates: list[dict] = []
    if resume:
        pending: list[Path] = []
        for candidate in candidate_paths:
            status_payload = _read_permuter_candidate_status(candidate)
            if (
                status_payload is not None
                and _is_resume_skippable_candidate_status(status_payload)
            ):
                skipped_candidates.append({
                    "path": str(candidate),
                    "status": status_payload.get("status"),
                    "semantic_risk_bucket": status_payload.get(
                        "semantic_risk_bucket"
                    ),
                    "source": status_payload.get("source"),
                })
                continue
            pending.append(candidate)
        candidate_paths = pending
    if max_candidates > 0 and len(candidate_paths) > max_candidates:
        candidate_paths = candidate_paths[:max_candidates]

    compile_timeout = None if candidate_timeout <= 0 else candidate_timeout
    baseline = _get_match_pct(function, melee_root) or 0.0
    if not json_out:
        print(f"Function: {function}")
        print(f"Target:   {target_path}")
        print(f"Baseline: {baseline:.2f}%")
        print(f"Candidates: {len(candidate_paths)}")
        if resume:
            print(f"Skipped: {len(skipped_candidates)}")
        print()

    orig = target_path.read_text()
    base_text = candidate_audit.read_candidate_base_text(perm_dir)

    @dataclasses.dataclass
    class Result:
        path: Path
        match_pct: Optional[float]
        delta: Optional[float]
        status: str  # ok/no-function/build-failed/corrupt-candidate/nonreproducible
        semantic_risk_bucket: str
        first_diag: Optional[str] = None  # set on build-failed/corrupt-candidate
        kept_failed_path: Optional[Path] = None  # set with --keep-failed
        source_risks: tuple[candidate_audit.SourceRisk, ...] = ()

    obj_path = f"build/GALE01/src/{unit}.o"
    results: list[Result] = []
    best: Optional[Result] = None

    def emit_progress(message: str) -> None:
        if json_out:
            typer.echo(f"[triage] {message}", err=True)
        else:
            print(message)

    try:
        for i, cand in enumerate(candidate_paths, 1):
            cand_text = cand.read_text()
            audit_report = candidate_audit.audit_candidate_source(
                cand_text,
                base_text=base_text,
            )
            if audit_report.should_reject:
                first_diag = _format_permuter_candidate_audit_diagnostic(
                    audit_report,
                    command="triage-perm",
                    candidate=cand,
                )
                _write_permuter_candidate_status(
                    cand,
                    status=audit_report.status,
                    function=function,
                    first_diag=first_diag,
                    risks=audit_report.risks,
                    semantic_risk_bucket=audit_report.semantic_risk_bucket,
                    source="triage",
                )
                results.append(Result(
                    path=cand, match_pct=None, delta=None,
                    status=audit_report.status,
                    semantic_risk_bucket=audit_report.semantic_risk_bucket,
                    first_diag=first_diag,
                    source_risks=audit_report.risks,
                ))
                if not json_out:
                    print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                          f"{audit_report.status.upper()}")
                    print(f"    first error: {first_diag}")
                continue
            orig_again = transfer_candidate(cand_text, target_path, function)
            if orig_again is None:
                _write_permuter_candidate_status(
                    cand,
                    status="no-function",
                    function=function,
                    risks=audit_report.risks,
                    semantic_risk_bucket="repo-invalid",
                    source="triage",
                )
                results.append(Result(path=cand, match_pct=None,
                                      delta=None, status="no-function",
                                      semantic_risk_bucket="repo-invalid",
                                      source_risks=audit_report.risks))
                if not json_out:
                    print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                          f"function not in candidate")
                continue
            # Inline the build so we can capture the first diagnostic
            # (instead of using _build_and_match, which discards stderr).
            emit_progress(
                f"[{i}/{len(candidate_paths)}] {cand.parent.name}: "
                f"building {obj_path} from {cand}"
            )
            r_build, retried_build = _run_ninja_with_no_diag_retry(
                ["ninja", obj_path],
                melee_root,
                timeout=compile_timeout,
            )
            if r_build.returncode != 0:
                first_diag = _failure_diagnostic_or_fallback(
                    r_build.stdout,
                    r_build.stderr,
                    fallback=(
                        f"ninja {obj_path} failed with exit "
                        f"{r_build.returncode}"
                        + (
                            " after retry"
                            if retried_build
                            else ""
                        )
                        + " and emitted no compiler diagnostic"
                    ),
                )
                kept_path: Optional[Path] = None
                if keep_failed:
                    try:
                        fd, tmp_path = tempfile.mkstemp(
                            prefix=(
                                f"triage-perm-failed-{function}-"
                                f"{cand.parent.name}-"
                            ),
                            suffix=".c",
                        )
                        with os.fdopen(fd, "w") as fh:
                            fh.write(target_path.read_text())
                        kept_path = Path(tmp_path)
                    except Exception:
                        kept_path = None
                # Always revert to original before next iter
                target_path.write_text(orig)
                _write_permuter_candidate_status(
                    cand,
                    status="build-failed",
                    function=function,
                    first_diag=first_diag,
                    risks=audit_report.risks,
                    semantic_risk_bucket="repo-invalid",
                    source="triage",
                    extra={"retried_build": retried_build},
                )
                results.append(Result(
                    path=cand, match_pct=None, delta=None,
                    status="build-failed",
                    semantic_risk_bucket="repo-invalid",
                    first_diag=first_diag,
                    kept_failed_path=kept_path,
                    source_risks=audit_report.risks,
                ))
                if not json_out:
                    parts = [
                        f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                        f"BUILD FAILED"
                    ]
                    parts.append(f"    first error: {first_diag}")
                    if kept_path is not None:
                        parts.append(f"    kept at: {kept_path}")
                    print("\n".join(parts))
                continue
            # Build succeeded — refresh report without rebuilding the object
            # a second time. Rebuilding here made triage vulnerable to
            # transient no-diagnostic failures after an already-good compile.
            pct, report_diag = _refresh_match_pct_after_successful_build(
                unit,
                function,
                melee_root,
                timeout=compile_timeout,
            )
            # Always revert to original before next iter
            target_path.write_text(orig)
            if pct is None:
                _write_permuter_candidate_status(
                    cand,
                    status="build-failed",
                    function=function,
                    first_diag=report_diag,
                    risks=audit_report.risks,
                    semantic_risk_bucket="repo-invalid",
                    source="triage",
                )
                results.append(Result(path=cand, match_pct=None,
                                      delta=None, status="build-failed",
                                      semantic_risk_bucket="repo-invalid",
                                      first_diag=report_diag,
                                      source_risks=audit_report.risks))
                if not json_out:
                    print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                          f"BUILD FAILED (report.json regen)")
                    if report_diag:
                        print(f"    first error: {report_diag}")
                continue
            delta = pct - baseline
            if delta >= threshold - 1e-9:
                recheck_pct, recheck_diag = _recheck_transferred_candidate_match(
                    cand_text,
                    target_path,
                    function,
                    unit,
                    melee_root,
                    orig,
                    timeout=compile_timeout,
                )
                if recheck_pct is None:
                    _write_permuter_candidate_status(
                        cand,
                        status="nonreproducible",
                        function=function,
                        first_diag=(
                            recheck_diag
                            or "transfer recheck failed without diagnostic"
                        ),
                        risks=audit_report.risks,
                        semantic_risk_bucket="repo-invalid",
                        source="triage",
                    )
                    results.append(Result(
                        path=cand,
                        match_pct=None,
                        delta=None,
                        status="nonreproducible",
                        semantic_risk_bucket="repo-invalid",
                        first_diag=(
                            recheck_diag
                            or "transfer recheck failed without diagnostic"
                        ),
                        source_risks=audit_report.risks,
                    ))
                    if not json_out:
                        print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                              f"NONREPRODUCIBLE")
                        if recheck_diag:
                            print(f"    first error: {recheck_diag}")
                    continue
                if abs(recheck_pct - pct) > 1e-6:
                    recheck_delta = recheck_pct - baseline
                    diag = (
                        f"transfer recheck produced {recheck_pct:.6f}% "
                        f"(delta={recheck_delta:+.6f}%) after initial triage "
                        f"reported {pct:.6f}% (delta={delta:+.6f}%)"
                    )
                    _write_permuter_candidate_status(
                        cand,
                        status="nonreproducible",
                        function=function,
                        first_diag=diag,
                        risks=audit_report.risks,
                        match_pct=recheck_pct,
                        delta=recheck_delta,
                        semantic_risk_bucket="repo-invalid",
                        source="triage",
                    )
                    results.append(Result(
                        path=cand,
                        match_pct=recheck_pct,
                        delta=recheck_delta,
                        status="nonreproducible",
                        semantic_risk_bucket="repo-invalid",
                        first_diag=diag,
                        source_risks=audit_report.risks,
                    ))
                    if not json_out:
                        print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                              f"NONREPRODUCIBLE")
                        print(f"    first error: {diag}")
                    continue
                pct = recheck_pct
                delta = pct - baseline
            _write_permuter_candidate_status(
                cand,
                status="ok",
                function=function,
                risks=audit_report.risks,
                match_pct=pct,
                delta=delta,
                semantic_risk_bucket=audit_report.semantic_risk_bucket,
                source="triage",
            )
            res = Result(
                path=cand, match_pct=pct, delta=delta, status="ok",
                semantic_risk_bucket=audit_report.semantic_risk_bucket,
                source_risks=audit_report.risks,
            )
            results.append(res)
            tag = ""
            # epsilon: float-precision tolerance so +0.05 wins at
            # threshold 0.05 don't silently drop.
            if delta >= threshold - 1e-9:
                tag = "  WIN"
                if best is None or pct > best.match_pct:
                    best = res
            elif delta < 0:
                tag = "  (worse)"
            if not json_out:
                print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                      f"{pct:.2f}%  delta={delta:+.2f}%{tag}")
    finally:
        target_path.write_text(orig)
        _run_ninja_with_no_diag_retry(
            ["ninja", obj_path, "build/GALE01/report.json"],
            melee_root,
            timeout=compile_timeout,
        )

    # Sort results: highest match% first, then by directory name as tiebreak
    ok_results = [r for r in results if r.status == "ok"]
    ok_results.sort(key=lambda r: (-(r.match_pct or 0), str(r.path)))

    if json_out:
        print(json.dumps({
            "function": function,
            "baseline_pct": baseline,
            "best_pct": best.match_pct if best else None,
            "best_path": str(best.path) if best else None,
            "skipped_count": len(skipped_candidates),
            "skipped_candidates": skipped_candidates,
            "results": [{
                "path": str(r.path),
                "match_pct": r.match_pct,
                "delta": r.delta,
                "status": r.status,
                "semantic_risk_bucket": r.semantic_risk_bucket,
                "first_diag": r.first_diag,
                "kept_failed_path": (
                    str(r.kept_failed_path)
                    if r.kept_failed_path else None
                ),
                "source_risks": candidate_audit.risks_to_dicts(r.source_risks),
            } for r in results],
        }, indent=2))
        return

    print()
    print("=" * 70)
    print(f"Top {min(top_k, len(ok_results))} candidates by real-tree match%:")
    print("=" * 70)
    for r in ok_results[:top_k]:
        marker = "WIN" if r.delta >= threshold - 1e-9 else "    "
        print(f"  {marker}  {r.match_pct:.2f}%  ({r.delta:+.2f}%)  "
              f"{r.path.parent.name}/source.c")

    n_wins = sum(1 for r in ok_results if r.delta >= threshold - 1e-9)
    n_build_failed = sum(1 for r in results if r.status == "build-failed")
    n_no_fn = sum(1 for r in results if r.status == "no-function")
    n_corrupt = sum(1 for r in results if r.status == "corrupt-candidate")
    n_unsafe = sum(1 for r in results if r.status == "unsafe-candidate")
    n_nonrepro = sum(1 for r in results if r.status == "nonreproducible")
    print()
    print(f"Summary: {n_wins} winners (≥{threshold:.2f}% over baseline), "
          f"{n_build_failed} build failures, {n_no_fn} missing function, "
          f"{n_corrupt} corrupt candidates, {n_unsafe} unsafe candidates, "
          f"{n_nonrepro} nonreproducible")

    if apply_best and best is not None and best.delta >= threshold - 1e-9:
        cand_text = best.path.read_text()
        transfer_candidate(cand_text, target_path, function)
        subprocess.run(
            ["ninja", f"build/GALE01/src/{unit}.o",
             "build/GALE01/report.json"],
            cwd=melee_root, capture_output=True,
        )
        print()
        print(f"Applied best candidate ({best.path.parent.name}) to "
              f"{target_path}. Verify with `git diff`.")


def _decl_order_candidate_count(names: list[str], strategy: str) -> int:
    n = len(names)
    if strategy in ("promote", "demote", "swap"):
        return max(0, n - 1)
    if strategy == "all":
        return max(0, 3 * (n - 1))
    if strategy == "full":
        import math
        return max(0, math.factorial(n) - 1)
    return 0


def _select_decl_order_scope(
    scope_map: dict[tuple[str, ...], list[str]],
    function: str,
    *,
    explicit_scope: str | None = None,
) -> tuple[tuple[str, ...], str]:
    if explicit_scope:
        return tuple(explicit_scope.split("/")), "explicit"
    selected_scope = (function,)
    selected_scope_reason = "function-top"
    if not scope_map.get(selected_scope):
        nested_scopes = [
            scope_path
            for scope_path, names in scope_map.items()
            if scope_path != (function,) and len(names) >= 2
        ]
        if not nested_scopes:
            nested_scopes = [
                scope_path
                for scope_path in scope_map
                if scope_path != (function,)
            ]
        if nested_scopes:
            selected_scope = nested_scopes[0]
            selected_scope_reason = "auto-nested"
    return selected_scope, selected_scope_reason


def _default_decl_order_search_summary(
    source: str,
    function: str,
    *,
    strategy: str = "promote",
) -> dict:
    scope_map = get_decl_names_by_scope(source, function)
    selected_scope, selected_scope_reason = _select_decl_order_scope(
        scope_map,
        function,
    )
    names = scope_map.get(selected_scope) or []
    available_scopes = [
        {
            "scope": "/".join(scope_path),
            "declaration_count": len(scope_names),
            "is_top_level": scope_path == (function,),
        }
        for scope_path, scope_names in scope_map.items()
    ]
    return {
        "scope": "/".join(selected_scope),
        "selected_scope_reason": selected_scope_reason,
        "declaration_count": len(names),
        "candidate_count": _decl_order_candidate_count(names, strategy),
        "strategy": strategy,
        "available_scopes": available_scopes,
    }


@inspect_app.command(name="stuck")
def stuck(
    function: Annotated[
        str,
        typer.Argument(help="Function name to diagnose"),
    ],
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Optional target spec (YAML/JSON) for guide comparisons. "
                 "If omitted, surfaces red-flag patterns without a specific "
                 "target.",
        ),
    ] = None,
    no_pcdump: Annotated[
        bool,
        typer.Option(
            "--no-pcdump",
            help="Skip the pcdump auto-generation step if the cache is "
                 "missing. Use when you already know there's no pcdump and "
                 "want a static-only digest.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit structured digest as JSON."),
    ] = False,
    asm_hunks: Annotated[
        int,
        typer.Option(
            "--asm-hunks",
            help="Also show the top N asm-diff hunks from checkdiff. "
                 "0 (default) omits. Saves switching tools when "
                 "allocator-level analysis doesn't explain the mismatch.",
        ),
    ] = 0,
) -> None:
    """One-shot diagnostic for a stuck function.

    Composes inspect analyze + inspect guide + suggest casts and recommends the next
    workflow step. Replaces what used to be 4-5 separate commands.

    Output sections (in order):
      1. Function status — match%, TU, virtual count
      2. Pcdump cache — fresh/stale/missing
      3. Coloring summary — virtuals, SPILLED markers, pass info
      4. Guidance issues — red-flag patterns from `debug inspect guide`
      5. Suspicious casts — HIGH+MEDIUM cast warnings
      6. Asm hunks (if --asm-hunks N) — text-level diff samples
      7. Next steps — ranked by cost/likelihood
    """
    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"function '{function}' not found in report.json.\n"
            f"Try `ninja build/GALE01/report.json` to regenerate, then retry.",
            err=True,
        )
        raise typer.Exit(2)
    src = melee_root / "src" / f"{unit}.c"
    match_pct = _get_match_pct(function, melee_root)

    # Pcdump status. If missing, try to generate (unless --no-pcdump).
    entry = pcdump_cache.lookup(melee_root, unit)
    pcdump_status: str
    pcdump_path: Optional[Path] = None
    if entry is None and not no_pcdump:
        pcdump_status = "missing — would auto-generate (run `debug dump remote src/" + unit + ".c`)"
    elif entry is None:
        pcdump_status = "missing (--no-pcdump set, skipping)"
    elif entry.fresh:
        pcdump_status = f"fresh ({entry.path.name})"
        pcdump_path = entry.path
    else:
        pcdump_status = f"stale (source modified after cache; regenerate for accuracy)"
        pcdump_path = entry.path

    # Collect digest data
    digest: dict = {
        "function": function,
        "tu": str(src.relative_to(melee_root)),
        "match_pct": match_pct,
        "pcdump_status": pcdump_status,
    }

    coloring_summary: Optional[dict] = None
    guidance_issues: list = []
    cast_warnings_high_med: list = []
    frame_residual_hint: dict | None = None
    src_text = src.read_text() if src.exists() else ""
    decl_order_summary = (
        _default_decl_order_search_summary(src_text, function)
        if src_text else None
    )
    checkdiff_classification = _get_checkdiff_classification(function, melee_root)
    static_frame_residual_hint = _frame_residual_hint_from_checkdiff_classification(
        function,
        checkdiff_classification,
        unit=unit,
    )

    if pcdump_path is not None:
        text = pcdump_path.read_text()
        fns = parse_pcdump(text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is not None:
            infos = analyze_function(fn)
            mapped = sum(1 for v in infos if v.physical is not None)
            unmapped = sum(1 for v in infos if v.physical is None)
            events_list = parse_hook_events(text)
            events = find_function(events_list, function)
            n_spilled = 0
            if events is not None:
                for sec in events.simplify_sections:
                    n_spilled += sum(1 for e in sec.entries if e.spilled)
            coloring_summary = {
                "n_virtuals": len(infos),
                "mapped": mapped,
                "unmapped": unmapped,
                "spilled": n_spilled,
                "pre_pass": (fn.last_precolor_pass().name
                             if fn.last_precolor_pass() else None),
            }

            # Guidance — empty target spec surfaces red-flag patterns
            if target is not None:
                spec = _load_target_spec(target)
            else:
                spec = {"virtuals": {}}
            result = score_function(fn, spec, events=events)
            suggestions = suggest(fn, result, events=events)
            guidance_issues = [{
                "virtual": s.virtual,
                "category": s.category,
                "severity": s.severity,
                "description": s.description,
                "patterns": s.patterns,
            } for s in suggestions]
        frame_residual_hint = _detect_frame_residual_hint(
            function,
            unit=unit,
            melee_root=melee_root,
            pcdump_path=pcdump_path,
        )
    if frame_residual_hint is None:
        frame_residual_hint = static_frame_residual_hint

    # Cast warnings — always run regardless of pcdump
    if src_text:
        warnings = audit_function_casts(src_text, function)
        cast_warnings_high_med = [{
            "line": w.line,
            "call_target": w.call_target,
            "arg_index": w.arg_index,
            "cast_type": w.cast_type,
            "inner_expr": w.inner_expr,
            "severity": w.severity,
            "reason": w.reason,
        } for w in warnings if w.severity in ("high", "medium")]

    # HSD_ASSERT override detection — scan the compiled .o for anonymous
    # .sdata symbols whose content matches known assert filename strings
    # (jobj.h, jobj, lobj.h, etc.).  When found, the fix is to override
    # HSD_ASSERT before the jobj.h include so the inline assert uses named
    # extern char[] symbols instead of anonymous @N ones.
    hsd_assert_strings: list[tuple[str, str]] = []
    _built_o = melee_root / "build" / "GALE01" / "src" / f"{unit}.o"
    if _built_o.exists():
        try:
            from ..mwcc_debug.o_rewriter import find_anonymous_assert_strings
            hsd_assert_strings = find_anonymous_assert_strings(_built_o)
        except Exception:
            pass

    # Next steps — ranked by cost
    next_steps: list[str] = []
    if frame_residual_hint:
        next_steps.extend(frame_residual_hint["next_steps"])
    if any(w["severity"] == "high" for w in cast_warnings_high_med):
        next_steps.append(
            "[free, static] Drop suspicious casts surfaced by suggest casts. "
            "Run `melee-agent debug suggest casts " + function + "` for "
            "full details."
        )
    if coloring_summary and coloring_summary.get("spilled", 0) > 0:
        next_steps.append(
            "[medium] Try patterns from `debug util patterns` that "
            "address SPILLED markers: widen-u8-to-u32, alias-split."
        )
    if (
        decl_order_summary is not None
        and decl_order_summary["candidate_count"] > 0
    ):
        if frame_residual_hint and frame_residual_hint.get("kind") in {
            "frame-size",
            "same-frame-stack-slot-placement",
        }:
            next_steps.append(
                "[~70sec] Optional cheap probe: run `melee-agent debug mutate "
                "decl-orders " + function + "` after the headline stack-layout "
                "tool; decl-order search is often neutral on this class."
            )
        else:
            next_steps.append(
                "[~70sec] Run `melee-agent debug mutate decl-orders " + function +
                "` — brute-forces the decl-order search space, finds 1-line wins."
            )
        next_steps.append(
            "[minutes] Run `melee-agent debug inspect diagnose " + function +
            "` for a current-tooling diagnosis (combines force-phys evidence + "
            "mutate decl-orders without treating the function as impossible)."
        )
    elif decl_order_summary is not None:
        next_steps.append(
            "[free] Skip direct decl-order search: no decl-order candidates "
            f"in default scope {decl_order_summary['scope']} "
            f"({decl_order_summary['declaration_count']} declaration"
            f"{'' if decl_order_summary['declaration_count'] == 1 else 's'})."
        )
        next_steps.append(
            "[minutes] Run `melee-agent debug inspect diagnose " + function +
            " --skip-decl-orders` for the remaining current-tooling diagnosis."
        )
    else:
        next_steps.append(
            "[minutes] Run `melee-agent debug inspect diagnose " + function +
            " --skip-decl-orders` for a current-tooling diagnosis; source was "
            "unavailable for decl-order preflight."
        )
    next_steps.append(
        "[hours] As a last resort, run decomp-permuter and feed its "
        "outputs through `debug permute triage`."
    )

    digest["coloring_summary"] = coloring_summary
    digest["guidance_issues"] = guidance_issues
    digest["cast_warnings"] = cast_warnings_high_med
    digest["checkdiff_classification"] = checkdiff_classification
    digest["decl_order_summary"] = decl_order_summary
    digest["hsd_assert_strings"] = [
        {"sym": s, "string": v} for s, v in hsd_assert_strings
    ]
    digest["frame_residual"] = frame_residual_hint
    digest["next_steps"] = next_steps

    if json_out:
        print(json.dumps(digest, indent=2))
        return

    # Human-readable output
    print(f"== Function status ==")
    print(f"  {function}")
    print(f"  TU:       {digest['tu']}")
    if match_pct is not None:
        print(f"  Match:    {match_pct:.2f}%")
    else:
        print(f"  Match:    (no entry in report.json)")
    print()

    print(f"== Pcdump cache ==")
    print(f"  {pcdump_status}")
    print()

    if coloring_summary:
        s = coloring_summary
        print(f"== Coloring summary ==")
        print(f"  Virtuals:    {s['n_virtuals']} ({s['mapped']} mapped, "
              f"{s['unmapped']} unmapped)")
        print(f"  Spilled:     {s['spilled']}")
        print(f"  Pre-pass:    {s['pre_pass']}")
        print()

    if guidance_issues:
        print(f"== Guidance issues ({len(guidance_issues)}) ==")
        for issue in guidance_issues:
            marker = {"high": "!!", "medium": "!", "low": "·"}.get(
                issue["severity"], " ")
            print(f"  {marker} [r{issue['virtual']} / {issue['category']}]")
            print(f"     {issue['description']}")
            if issue["patterns"]:
                names = ", ".join(f"`{p}`" for p in issue["patterns"])
                print(f"     Patterns: {names}")
        print()
    elif coloring_summary:
        print(f"== Guidance issues ==")
        if frame_residual_hint:
            print(f"  (none from register-allocation guidance; see "
                  f"frame/local-area residual below.)")
        else:
            print(f"  (none — pcdump available but no flagged issues. Provide "
                  f"--target to compare against a specific mapping.)")
        print()

    if frame_residual_hint:
        print(f"== Frame/local-area residual ==")
        print(f"  {frame_residual_hint['message']}")
        print()

    if cast_warnings_high_med:
        print(f"== Suspicious casts ({len(cast_warnings_high_med)}) ==")
        for w in cast_warnings_high_med:
            marker = {"high": "!!", "medium": "!"}.get(w["severity"], " ")
            print(f"  {marker} line {w['line']}: ({w['cast_type']}) "
                  f"{w['inner_expr']} → {w['call_target']}")
        print()

    if hsd_assert_strings:
        syms_str = ", ".join(f"{s} ({v!r})" for s, v in hsd_assert_strings)
        print(f"== HSD_ASSERT override needed ==")
        print(f"  Anonymous .sdata assert strings detected: {syms_str}")
        print(f"  These come from HSD_ASSERT inside jobj.h (or similar) inline")
        print(f"  functions. The relocation names will differ from the target .o.")
        print(_format_hsd_assert_override_guidance("  "))
        print()

    if asm_hunks > 0:
        hunks = _get_asm_hunks(function, melee_root, top_n=asm_hunks)
        if hunks is None:
            print(f"== Asm hunks ==")
            print(f"  (checkdiff didn't produce a diff — either matching, "
                  f"not built, or errored. Try `tools/checkdiff.py "
                  f"{function}` directly.)")
            print()
        elif hunks:
            print(f"== Top {len(hunks)} asm hunks (by diff size) ==")
            print(_format_asm_hunks(hunks))
            print()

    print(f"== Next steps (ranked by cost) ==")
    for i, step in enumerate(next_steps, 1):
        print(f"  {i}. {step}")


def _ceiling_recommendations(function: str, unit: str) -> list[str]:
    """Next steps when current fast transforms found no path."""
    src_rel = f"src/{unit}.c"
    return [
        "No fast transform found from casts or decl-order. Next options:",
        "  (a) Construct a target mapping and run "
        f"`melee-agent debug dump local {src_rel} --force-phys ... "
        f"--force-phys-fn {function}` to test whether the force-target "
        "can be reached from the current IR.",
        "      If local dump support is unavailable in this environment, use "
        f"`melee-agent debug dump remote {src_rel} --force-phys ... "
        f"--force-phys-fn {function}` as the remote fallback.",
        "  (b) If force-phys reaches the target, this requires "
        "source-shape search; run decomp-permuter or a focused mutation "
        "campaign.",
        "  (c) If force-phys does not reach the target, record the "
        "force-target-not-reached evidence as unresolved by current "
        "heuristics, then move to another target until new evidence or a "
        "broader search path exists.",
    ]


@dataclasses.dataclass(frozen=True)
class DiagnoseForcePhysEntry:
    class_id: int | None
    virtual: int
    phys: int
    token: str


def _parse_diagnose_force_phys(
    raw: str,
) -> tuple[list[DiagnoseForcePhysEntry], str, list[str]]:
    """Parse a diagnose-only force-phys proof vector."""
    normalized, warnings = _normalize_force_phys(raw)
    entries: list[DiagnoseForcePhysEntry] = []
    for token in normalized.split(","):
        token = token.strip()
        if not token:
            continue
        parts = token.split(":")
        try:
            if len(parts) == 3:
                class_id = _parse_force_phys_class(parts[0])
                virtual = _parse_force_vector_int(parts[1], prefix="ig")
                phys = _parse_force_vector_phys(parts[2])
            elif len(parts) == 2:
                class_id = None
                virtual = _parse_force_vector_int(parts[0], prefix="ig")
                phys = _parse_force_vector_phys(parts[1])
            else:
                raise ValueError(
                    "expected IG:PHYS or CLASS:IG:PHYS"
                )
        except ValueError as exc:
            raise typer.BadParameter(
                f"--force-phys entry {token!r} is invalid: {exc}"
            ) from exc
        entries.append(DiagnoseForcePhysEntry(
            class_id=class_id,
            virtual=virtual,
            phys=phys,
            token=token,
        ))
    if not entries:
        raise typer.BadParameter("--force-phys did not contain any entries")
    return entries, normalized, warnings


def _format_force_phys_members(entries: list[DiagnoseForcePhysEntry]) -> str:
    return ", ".join(f"r{entry.virtual}->r{entry.phys}" for entry in entries)


def _cluster_entries_by_virtuals(
    entries: list[DiagnoseForcePhysEntry],
    virtuals: list[int],
) -> list[DiagnoseForcePhysEntry]:
    by_virtual = {entry.virtual: entry for entry in entries}
    return [by_virtual[v] for v in virtuals if v in by_virtual]


def _attempt_evidence_for_keywords(
    function: str,
    keywords: list[str],
) -> dict:
    from .tracking import summarize_attempts

    summary = summarize_attempts(function)
    attempts = summary.get("attempts", [])
    matches: list[dict] = []
    lowered_keywords = [keyword.lower() for keyword in keywords]
    for attempt in attempts:
        text = " ".join(
            str(attempt.get(key) or "")
            for key in ("note", "classification", "blocker", "verdict")
        ).lower()
        if lowered_keywords and not any(keyword in text for keyword in lowered_keywords):
            continue
        matches.append(attempt)

    retained = [attempt for attempt in matches if attempt.get("retained")]
    negative = [
        attempt for attempt in matches
        if str(attempt.get("outcome") or "") in {
            "neutral", "regressed", "reverted", "blocked",
        }
    ]
    if retained:
        status = "retained-source-improvement"
    elif negative:
        status = "negative-evidence"
    elif matches:
        status = "tried"
    else:
        status = "untried"
    evidence_notes: list[str] = []
    for attempt in (retained or negative or matches)[:3]:
        note = str(attempt.get("blocker") or attempt.get("note") or "").strip()
        if not note:
            continue
        if len(note) > 220:
            note = note[:217].rstrip() + "..."
        evidence_notes.append(note)
    return {
        "status": status,
        "attempt_count": len(matches),
        "evidence": evidence_notes,
    }


def _coverage_family(
    *,
    function: str,
    name: str,
    keywords: list[str],
    expected_effect: str,
    next_probe: str,
) -> dict:
    evidence = _attempt_evidence_for_keywords(function, keywords)
    return {
        "name": name,
        "status": evidence["status"],
        "attempt_count": evidence["attempt_count"],
        "evidence": evidence["evidence"],
        "expected_effect": expected_effect,
        "next_probe": next_probe,
    }


def _force_phys_coverage_matrix(
    *,
    function: str,
    unit: str,
    clusters: list[dict],
) -> list[dict]:
    src_rel = f"src/{unit}.c"
    rows: list[dict] = []
    for cluster in clusters:
        name = cluster.get("name", "")
        holders = [
            f"ig{virtual}->r{phys}"
            for virtual, phys in zip(
                cluster.get("virtuals", []),
                cluster.get("phys", []),
                strict=False,
            )
        ]
        if function == "ftCo_8009E7B4" and "early" in name:
            rows.append({
                "cluster": name,
                "source_file": src_rel,
                "source_regions": [
                    "early flag/reload block",
                    "boolean flag temp and reload boundary",
                    "early volatile call-adjacent temps",
                ],
                "target_holders": holders,
                "transform_families": [
                    _coverage_family(
                        function=function,
                        name="flag-temp split/merge",
                        keywords=["flag", "split", "merge", "boolean"],
                        expected_effect="move volatile proof holders together",
                        next_probe="split/merge the flag temp and keep reload placement stable",
                    ),
                    _coverage_family(
                        function=function,
                        name="reload sink/hoist",
                        keywords=["reload", "sink", "hoist", "remote permuter"],
                        expected_effect="change reload live-range overlap near ig58/ig44/ig42",
                        next_probe="move the reload closer to first use or preserve it across the branch",
                    ),
                    _coverage_family(
                        function=function,
                        name="early local declaration/use order",
                        keywords=["decl", "order", "early", "local"],
                        expected_effect="change allocator tie-break order without semantic refactor",
                        next_probe="try scoped declaration/use-boundary movement in the early block",
                    ),
                ],
            })
        elif function == "ftCo_8009E7B4" and "late" in name:
            rows.append({
                "cluster": name,
                "source_file": src_rel,
                "source_regions": [
                    "x594_b4/x594_b3 field-bit tests",
                    "loop IV/tree-pointer lifetime boundary",
                    "late callee-save holder overlap",
                ],
                "target_holders": holders,
                "transform_families": [
                    _coverage_family(
                        function=function,
                        name="b4/b3 direct field test vs named temps",
                        keywords=["b4", "b3", "field", "tree probes"],
                        expected_effect="move late callee-save proof holders around field-bit tests",
                        next_probe="compare direct field tests with named temp forms",
                    ),
                    _coverage_family(
                        function=function,
                        name="loop index vs pointer-walk role split",
                        keywords=["loop", "tree", "pointer", "iv", "b4"],
                        expected_effect="change loop IV/tree-pointer holder overlap",
                        next_probe="split pointer-walk base from loop index and validate real-tree output",
                    ),
                    _coverage_family(
                        function=function,
                        name="tree-pointer reload sink/hoist",
                        keywords=["tree", "reload", "sink", "hoist"],
                        expected_effect="change r30/r29 callee-save pressure in the late cluster",
                        next_probe="sink or hoist the tree-pointer reload across the bit-test block",
                    ),
                ],
            })
        else:
            rows.append({
                "cluster": name,
                "source_file": src_rel,
                "source_regions": [
                    "proof-vector source region unresolved",
                    "run virtual-to-var or first-divergence to refine spans",
                ],
                "target_holders": holders,
                "transform_families": [
                    _coverage_family(
                        function=function,
                        name="clustered source-shape probe",
                        keywords=["source", "shape", "probe", "force"],
                        expected_effect="move all proof holders in this cluster together",
                        next_probe="instantiate one source-shape edit per mapped holder region",
                    )
                ],
            })
    return rows


def _diagnose_coupled_force_phys_guidance(
    *,
    function: str,
    unit: str,
    force_phys: str | None,
) -> dict | None:
    if not force_phys:
        return None
    entries, normalized, warnings = _parse_diagnose_force_phys(force_phys)
    if len(entries) < 3:
        return {
            "proof_force_phys": normalized,
            "warnings": warnings,
            "coupled": False,
            "reason": (
                "At least three proof assignments are needed before diagnose "
                "treats the vector as a coupled source-shape problem."
            ),
            "entries": [
                {
                    "class_id": entry.class_id,
                    "virtual": entry.virtual,
                    "phys": entry.phys,
                }
                for entry in entries
            ],
            "clusters": [],
            "experiments": [],
            "verification_commands": [],
        }

    entry_virtuals = {entry.virtual for entry in entries}
    clusters: list[dict] = []
    experiments: list[str] = []
    if function == "ftCo_8009E7B4" and (
        entry_virtuals & {58, 44, 42}
    ) and (
        entry_virtuals & {35, 56, 34}
    ):
        early = _cluster_entries_by_virtuals(entries, [58, 44, 42])
        late = _cluster_entries_by_virtuals(entries, [35, 56, 34])
        clusters = [
            {
                "name": "early flag/reload temps",
                "members": _format_force_phys_members(early),
                "virtuals": [entry.virtual for entry in early],
                "phys": [entry.phys for entry in early],
                "rationale": (
                    "These volatile-register targets sit around the early "
                    "flag/reload path; changing one temp alone leaves the "
                    "same allocator pressure for the neighboring reloads."
                ),
            },
            {
                "name": "late x594_b4/x594_b3 loop IV/tree-pointer swaps",
                "members": _format_force_phys_members(late),
                "virtuals": [entry.virtual for entry in late],
                "phys": [entry.phys for entry in late],
                "rationale": (
                    "These callee-save targets couple the late field-bit "
                    "tests with loop-index and tree-pointer lifetimes."
                ),
            },
        ]
        experiments = [
            (
                "Early cluster: try natural flag/reload variants together "
                "(split or merge the flag temp, move the reload closer to "
                "first use, and reorder the nearby boolean/reload locals)."
            ),
            (
                "Late cluster: try natural x594_b4/x594_b3 variants together "
                "(direct field tests versus named temps, swap loop IV and "
                "tree-pointer declaration/use order, and hoist/sink the "
                "tree-pointer reload)."
            ),
            (
                "Combined probe: apply one early-cluster edit and one "
                "late-cluster edit in the same candidate before judging the "
                "byte score; this is a multi-site allocator-shape hypothesis."
            ),
        ]
    else:
        volatile = [
            entry for entry in entries
            if entry.phys <= 12 or entry.virtual >= 40
        ]
        callee_save = [entry for entry in entries if entry not in volatile]
        if not volatile or not callee_save:
            mid = max(1, len(entries) // 2)
            volatile = entries[:mid]
            callee_save = entries[mid:]
        clusters = [
            {
                "name": "volatile/reload-pressure cluster",
                "members": _format_force_phys_members(volatile),
                "virtuals": [entry.virtual for entry in volatile],
                "phys": [entry.phys for entry in volatile],
                "rationale": (
                    "These assignments bias volatile or high-numbered temps; "
                    "they often move when reloads, predicates, or call-return "
                    "copies are reshaped together."
                ),
            },
            {
                "name": "callee-save/lifetime-pressure cluster",
                "members": _format_force_phys_members(callee_save),
                "virtuals": [entry.virtual for entry in callee_save],
                "phys": [entry.phys for entry in callee_save],
                "rationale": (
                    "These assignments bias longer-lived callee-save choices; "
                    "they often need loop, cursor, or pointer lifetime changes."
                ),
            },
        ]
        experiments = [
            (
                "Treat each cluster as one source-shape region, not as "
                "independent virtual nudges."
            ),
            (
                "Combine one volatile/reload edit with one lifetime-pressure "
                "edit before judging whether the allocator movement is useful."
            ),
        ]

    src_rel = f"src/{unit}.c"
    guidance = {
        "proof_force_phys": normalized,
        "warnings": warnings,
        "coupled": True,
        "entries": [
            {
                "class_id": entry.class_id,
                "virtual": entry.virtual,
                "phys": entry.phys,
            }
            for entry in entries
        ],
        "clusters": clusters,
        "partial_probe_explanation": (
            "singleton/prefix force-phys probes can no-match because each "
            "partial override preserves pressure that the other cluster must "
            "also relieve; a union byte-match is evidence for coupled source "
            "shape, not independent one-virtual nudges."
        ),
        "hypothesis": (
            "multi-site allocator-shape hypothesis: look for natural C edits "
            "that move both clusters together, then re-score assignment "
            "satisfaction and byte preservation."
        ),
        "experiments": experiments,
        "verification_commands": [
            (
                f"melee-agent debug dump local {src_rel} --force-phys "
                f"{normalized} --force-phys-fn {function}"
            ),
            (
                f"melee-agent debug inspect diagnose {function} "
                f"--skip-decl-orders --force-phys {normalized}"
            ),
        ],
    }
    guidance["coverage_matrix"] = _force_phys_coverage_matrix(
        function=function,
        unit=unit,
        clusters=clusters,
    )
    return guidance


def _print_coupled_force_phys_guidance(guidance: dict) -> None:
    if not guidance.get("coupled"):
        print("[!] Force-phys proof vector:")
        print(f"    {guidance.get('reason', 'not enough entries')}")
        print()
        return
    print("[!] Coupled force-phys proof vector:")
    print(f"    proof: {guidance['proof_force_phys']}")
    for warning in guidance.get("warnings", []):
        print(f"    warning: {warning}")
    print("    Clusters:")
    for cluster in guidance.get("clusters", []):
        print(f"      - {cluster['name']}: {cluster['members']}")
        if cluster.get("rationale"):
            print(f"        {cluster['rationale']}")
    print(f"    Why partial probes fail: {guidance['partial_probe_explanation']}")
    print(f"    Hypothesis: {guidance['hypothesis']}")
    if guidance.get("experiments"):
        print("    Source experiments:")
        for experiment in guidance["experiments"]:
            print(f"      - {experiment}")
    if guidance.get("coverage_matrix"):
        print("    Source-lever coverage matrix:")
        for row in guidance["coverage_matrix"]:
            print(f"      - {row['cluster']}:")
            print(f"        source: {row['source_file']}")
            print(f"        regions: {', '.join(row.get('source_regions') or [])}")
            print(f"        holders: {', '.join(row.get('target_holders') or [])}")
            for family in row.get("transform_families", []):
                print(
                    f"        * {family['name']} "
                    f"(status: {family['status']}, "
                    f"attempts: {family['attempt_count']})"
                )
                if family.get("evidence"):
                    print(f"          evidence: {'; '.join(family['evidence'])}")
                print(f"          expected: {family['expected_effect']}")
                print(f"          next: {family['next_probe']}")
    if guidance.get("verification_commands"):
        print("    Verify:")
        for command in guidance["verification_commands"]:
            print(f"      {command}")
    print()


def _register_tiebreak_guidance(
    *,
    function: str,
    unit: str | None,
    force_phys: str,
) -> dict:
    entries, normalized, warnings = _parse_diagnose_force_phys(force_phys)
    src_rel = f"src/{unit}.c" if unit else "<source.c>"
    targets = [
        {
            "class_id": entry.class_id,
            "ig_idx": entry.virtual,
            "target_phys": entry.phys,
            "register": f"r{entry.phys}",
            "below_registers": [f"r{reg}" for reg in range(3, entry.phys)],
        }
        for entry in entries
    ]
    primary = targets[0]
    primary_ig = primary["ig_idx"]
    primary_phys = primary["target_phys"]
    below_registers = primary["below_registers"]
    below_text = ", ".join(below_registers) if below_registers else (
        "the lower volatile register set"
    )
    levers = [
        {
            "rank": 1,
            "kind": "interference-insertion",
            "target": f"ig{primary_ig}->r{primary_phys}",
            "description": (
                f"Keep a nearby named value live across ig{primary_ig}'s first "
                f"definition so the allocator must occupy {below_text} before "
                f"the compiler temp is colored."
            ),
            "source_moves": [
                (
                    "Introduce a short-lived alias for a pointer, counter, or "
                    "table expression immediately before the temp's defining "
                    "expression, then consume it after that expression."
                ),
                (
                    "Extend an existing loop or table pointer's lifetime by "
                    "moving its last use just past the temp definition."
                ),
            ],
        },
        {
            "rank": 2,
            "kind": "simplify-order-shift",
            "target": f"ig{primary_ig}->r{primary_phys}",
            "description": (
                f"move the defining expression for ig{primary_ig} later in "
                "source order, or sink the load/use that creates the compiler "
                "temp closer to its first real use."
            ),
            "source_moves": [
                (
                    "Inline a one-use table/global expression at the store or "
                    "call site instead of materializing it before loop pressure "
                    "is established."
                ),
                (
                    "Split a combined condition or store so the temp-producing "
                    "subexpression appears after the named holder that should "
                    f"claim {below_text}."
                ),
            ],
        },
        {
            "rank": 3,
            "kind": "targeted-alias",
            "target": f"ig{primary_ig}->r{primary_phys}",
            "description": (
                "Try a scoped alias around the first defining expression to "
                "change the temp's local lifetime without changing observable C."
            ),
            "source_moves": [
                (
                    "Use `debug mutate insert-alias` on candidate holder "
                    "locals near the temp definition, then score against the "
                    "force-phys objective."
                ),
            ],
        },
    ]
    verification_commands = [
        (
            f"melee-agent debug inspect virtual-to-var -f {function} "
            f"r{primary_ig}"
        ),
        (
            f"melee-agent debug inspect first-divergence -f {function} "
            f"--force-phys {normalized} --source"
        ),
        (
            f"melee-agent debug dump local {src_rel} --force-phys "
            f"{normalized} --force-phys-fn {function}"
        ),
        (
            f"melee-agent debug mutate simplify-order --fn {function} "
            f"--force-phys {normalized} --no-preserve-precolor"
        ),
        (
            f"melee-agent debug mutate decl-orders {function} --strategy all"
        ),
    ]
    return {
        "function": function,
        "source": src_rel,
        "normalized_force_phys": normalized,
        "warnings": warnings,
        "targets": targets,
        "levers": levers,
        "verification_commands": verification_commands,
        "notes": [
            (
                "This is source guidance for Case B/C compiler-temp register "
                "tiebreaks: force-phys proves reachability, but no source "
                "variable is directly bound to the temp."
            ),
            (
                "Prefer variants that preserve the target function's current "
                "byte score until the requested physical assignment moves."
            ),
        ],
    }


def _print_register_tiebreak_guidance(guidance: dict) -> None:
    print(f"Register-tiebreak source levers for {guidance['function']}")
    print(f"  force-phys: {guidance['normalized_force_phys']}")
    print(f"  source:     {guidance['source']}")
    for warning in guidance.get("warnings", []):
        print(f"  warning:    {warning}")
    print()
    print("Targets:")
    for target in guidance["targets"]:
        below = ", ".join(target["below_registers"]) or "none below target"
        print(f"  - ig{target['ig_idx']} -> r{target['target_phys']} "
              f"(below: {below})")
    print()
    print("Source levers:")
    for lever in guidance["levers"]:
        print(f"  {lever['rank']}. {lever['kind']}: {lever['description']}")
        for move in lever.get("source_moves", []):
            print(f"     - {move}")
    print()
    print("Verify:")
    for command in guidance["verification_commands"]:
        print(f"  {command}")


def _diagnose_site_hint(site) -> dict:
    return {
        "block_idx": site.block_idx,
        "opcode": site.opcode,
        "operands": site.operands,
    }


def _diagnose_spilled_virtual_hints(
    pcdump_text: str,
    function: str,
    source_text: str,
    *,
    source_file: str | None = None,
) -> list[dict]:
    """Return source-oriented diagnose hints for SPILLED virtuals."""
    events = find_function(parse_hook_events(pcdump_text), function)
    spilled_virts: list[int] = []
    if events is not None:
        seen: set[int] = set()
        for section in events.simplify_sections:
            for entry in section.entries:
                if (
                    entry.spilled
                    and entry.ig_idx >= 32
                    and entry.ig_idx not in seen
                ):
                    seen.add(entry.ig_idx)
                    spilled_virts.append(entry.ig_idx)
    if not spilled_virts:
        return []

    attribution_by_virtual = {}
    try:
        from ..mwcc_debug.virtual_attribution import explain_virtuals
        report = explain_virtuals(
            pcdump_text,
            function,
            virtuals=spilled_virts,
            source_text=source_text,
            source_file=source_file,
        )
        attribution_by_virtual = {
            entry.virtual: entry
            for entry in report.virtuals
        }
    except Exception:
        attribution_by_virtual = {}

    hints: list[dict] = []
    for virtual in spilled_virts:
        hint: dict = {"virtual": virtual}
        source = getattr(attribution_by_virtual.get(virtual), "source", None)
        if source is not None:
            hint["kind"] = source.kind
            hint["confidence"] = source.confidence
            if source.name:
                hint["var_name"] = source.name
            if source.source_file:
                hint["source_file"] = source.source_file
            if source.source_line is not None:
                hint["source_line"] = source.source_line
            if source.source_col is not None:
                hint["source_col"] = source.source_col
            if source.expression:
                hint["expression"] = source.expression
            if source.call_symbol:
                hint["call_symbol"] = source.call_symbol
            if source.copy_chain:
                hint["copy_chain"] = list(source.copy_chain)
            if source.base_virtual is not None:
                hint["base_virtual"] = source.base_virtual
            if source.base_var:
                hint["base_var"] = source.base_var
            if source.field_offset is not None:
                hint["field_offset"] = source.field_offset
            if source.field_name:
                hint["field_name"] = source.field_name
            if source.first_def is not None:
                hint["first_def"] = _diagnose_site_hint(source.first_def)
            if source.use_sites:
                hint["use_sites"] = [
                    _diagnose_site_hint(site)
                    for site in source.use_sites[:3]
                ]
        first_def = hint.get("first_def")
        if (
            isinstance(first_def, dict)
            and first_def.get("opcode") == "li"
            and first_def.get("block_idx") == 0
        ):
            hint["inline_hint"] = (
                "compiler-emitted immediate (li) in "
                "entry block — likely an inlined "
                "sentinel/return value; check "
                "static-inline callees for "
                "restructurable return paths"
            )
        hints.append(hint)
    return hints


def _format_diagnose_hint_location(hint: dict) -> str:
    source_file = hint.get("source_file")
    source_line = hint.get("source_line")
    if not source_file or source_line is None:
        return ""
    loc = f" {source_file}:{source_line}"
    if hint.get("source_col") is not None:
        loc += f":{hint['source_col']}"
    return loc


def _diagnose_call_return_recommendations(
    function: str,
    hints: list[dict],
) -> list[str]:
    call_hints = [h for h in hints if h.get("kind") == "call-return"]
    if not call_hints:
        return []
    regs = ", ".join(f"r{h['virtual']}" for h in call_hints[:5])
    expressions = []
    for hint in call_hints:
        expression = hint.get("expression") or hint.get("call_symbol")
        if expression and expression not in expressions:
            expressions.append(str(expression))
    expr_text = ", ".join(expressions[:2]) if expressions else "call returns"
    return [
        f"Spilled call-return copies ({regs}) trace to {expr_text}; "
        "prioritize call-return compare-chain source probes "
        f"(`melee-agent debug mutate lifetime-layout -f {function} ...` "
        "or `debug select-order-search`) before chasing unrelated locals."
    ]


def _read_diagnose_expected_asm(
    function: str,
    unit: str,
    melee_root: Path,
) -> str | None:
    asm_path = melee_root / "build" / "GALE01" / "asm" / f"{unit}.s"
    if asm_path.exists():
        return asm_path.read_text()
    try:
        return _read_frame_reservation_expected_asm(
            function,
            expected_asm=None,
            no_expected=False,
            melee_root=melee_root,
        )
    except Exception:
        return None


def _value_numbering_ceiling_recommendation(finding: Mapping[str, Any]) -> str:
    recommendation = finding.get("recommendation")
    if isinstance(recommendation, str) and recommendation:
        return f"value-numbering ceiling: {recommendation}"
    return (
        "value-numbering ceiling: target rematerializes a signed "
        "magic divide while this compile CSEs the quotient; bank this as a "
        "current-tooling ceiling unless a new semantic source-transform family "
        "is added."
    )


def _print_value_numbering_ceiling(finding: Mapping[str, Any]) -> None:
    print("[!] Value-numbering ceiling:")
    kind = finding.get("kind") or "unknown"
    confidence = finding.get("confidence") or "unknown"
    print(f"    {kind} ({confidence})")
    print(
        "    target rematerializes the signed magic divide quotient; "
        "current compile reuses the value-numbered quotient before xoris"
    )
    print(f"    {_value_numbering_ceiling_recommendation(finding)}")
    print()


@dataclasses.dataclass(frozen=True)
class DeclCandidateFailure:
    status: str
    diagnostic: Optional[str] = None
    candidate_path: Optional[Path] = None


def _classify_decl_candidate_failure(diagnostic: Optional[str]) -> str:
    if diagnostic and _extract_first_diagnostic("", diagnostic):
        return "invalid-probe"
    return "build-failed"


def _run_decl_candidates(
    candidates,
    *,
    reorder,
    build_and_match,
    baseline,
    max_seconds: float = 0.0,
    emit=lambda msg: None,
    now=time.monotonic,
):
    """Execute decl-order candidates, emitting per-candidate progress and
    honoring an optional wall-clock budget.

    ``reorder(perm)`` returns patched source (or None to skip a candidate);
    ``build_and_match(patched)`` compiles it and returns a match percent (or
    None/DeclCandidateFailure on failure). Returns
    ``(results, best_pct, best_label, stopped_early)``.
    """
    results: list = []
    best_pct = baseline
    best_label = None
    total = len(candidates)
    start = now()
    stopped_early = False
    for i, (label, perm) in enumerate(candidates, 1):
        if max_seconds and (now() - start) >= max_seconds:
            emit(
                f"    time budget {max_seconds:g}s reached after {i - 1}/{total} "
                f"candidates — stopping early (raise --max-seconds, or 0 to disable)"
            )
            stopped_early = True
            break
        patched = reorder(perm)
        if patched is None:
            continue
        build_result = build_and_match(patched)
        if isinstance(build_result, DeclCandidateFailure):
            result = {
                "label": label,
                "pct": None,
                "delta": None,
                "status": build_result.status,
            }
            if build_result.candidate_path is not None:
                result["candidate_path"] = str(build_result.candidate_path)
            if build_result.diagnostic:
                result["diagnostic"] = build_result.diagnostic
            results.append(result)
            emit(f"    ({i}/{total}) {label}: {build_result.status}")
            if build_result.candidate_path is not None:
                emit(f"        candidate: {build_result.candidate_path}")
            if build_result.diagnostic:
                emit(f"        first error: {build_result.diagnostic}")
            continue
        pct = build_result
        if pct is None:
            results.append({
                "label": label,
                "pct": None,
                "delta": None,
                "status": "build-failed",
            })
            emit(f"    ({i}/{total}) {label}: build-failed")
            continue
        delta = pct - baseline
        results.append({"label": label, "pct": pct, "delta": delta})
        emit(f"    ({i}/{total}) {label}: {pct:.2f}% ({delta:+.2f}%)")
        if pct > best_pct:
            best_pct = pct
            best_label = label
    return results, best_pct, best_label, stopped_early


@inspect_app.command(name="ceiling", hidden=True)
@inspect_app.command(name="diagnose")
def ceiling(
    function: Annotated[
        str,
        typer.Argument(help="Function name to check"),
    ],
    skip_decl_orders: Annotated[
        bool,
        typer.Option(
            "--skip-decl-orders",
            help="Skip the mutate decl-orders step (saves ~1 min "
                 "but produces a less confident verdict).",
        ),
    ] = False,
    decl_strategy: Annotated[
        str,
        typer.Option(
            "--decl-strategy",
            help="Strategy passed to mutate decl-orders. 'promote' is "
                 "fast (N candidates); 'all' covers promote+demote+swap "
                 "(~3N candidates).",
        ),
    ] = "promote",
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help=(
                "Optional force-phys proof vector to explain as a coupled "
                "source-shape problem. Accepts IG:PHYS or CLASS:IG:PHYS CSV."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit verdict as JSON."),
    ] = False,
    max_seconds: Annotated[
        float,
        typer.Option(
            "--max-seconds",
            help="Wall-clock budget for the decl-order enumeration phase "
                 "(0 = unlimited). Stops early with a clear message instead "
                 "of appearing hung.",
        ),
    ] = 0.0,
) -> None:
    """Current-tooling diagnosis: is there a quick win we haven't tried?

    Combines two checks:
      1. suggest casts — static cast linter (free, milliseconds)
      2. mutate decl-orders — brute-force decl-order space (~70s)

    Verdict categories:
      - WIN AVAILABLE — a quick fix exists (casts to drop, or a decl-
        order that improves match%)
      - INTRINSIC VALUE-NUMBERING CEILING — target rematerializes a
        signed magic divide while this compile CSEs the quotient; current
        source/allocator levers are not expected to add the missing
        arithmetic instructions
      - NO FAST TRANSFORM FOUND — current fast heuristics found no
        improvement; recommends force-phys reachability testing and/or
        source-shape search as next steps

    This is the command to run when you're staring at a stuck function
    and asking what evidence-backed workflow to run next.
    """
    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"function '{function}' not found in report.json", err=True
        )
        raise typer.Exit(2)
    src = melee_root / "src" / f"{unit}.c"
    baseline = _get_match_pct(function, melee_root) or 0.0
    diagnose_pcdump_path = _resolve_pcdump_path(
        None,
        function,
        melee_root,
        require_fresh=True,
    )
    diagnose_pcdump_text = diagnose_pcdump_path.read_text()
    value_numbering_ceiling = detect_divide_rematerialization_ceiling(
        function=function,
        expected_asm_text=_read_diagnose_expected_asm(
            function,
            unit,
            melee_root,
        ),
        current_pcdump_text=diagnose_pcdump_text,
    )
    frame_residual_hint = _detect_frame_residual_hint(
        function,
        unit=unit,
        melee_root=melee_root,
        pcdump_path=diagnose_pcdump_path,
    )

    if not json_out:
        print(f"== Current-tooling diagnosis for {function} ==")
        print(f"  Baseline: {baseline:.2f}%")
        print(f"  TU:       {src.relative_to(melee_root)}")
        print()

    # Step 1: suggest casts (with auto-verify for HIGH-severity findings)
    src_text = src.read_text() if src.exists() else ""
    coupled_force_phys_guidance = _diagnose_coupled_force_phys_guidance(
        function=function,
        unit=unit,
        force_phys=force_phys,
    )
    register_tiebreak_guidance = (
        _register_tiebreak_guidance(
            function=function,
            unit=unit,
            force_phys=force_phys,
        )
        if force_phys else None
    )
    cast_warnings = audit_function_casts(src_text, function)
    high_casts = [w for w in cast_warnings if w.severity == "high"]
    med_casts = [w for w in cast_warnings if w.severity == "medium"]
    cast_verify_secs = len(high_casts) * 6
    if not json_out:
        if high_casts:
            print(f"[1] Cast audit (~{cast_verify_secs}s including verify)...", flush=True)
        else:
            print(f"[1] Cast audit (free, ~ms)...", flush=True)

    # Auto-verify each HIGH cast by drop-test: patch src, compile, revert.
    # Avoids false-positive WIN AVAILABLE when the cast is heuristically
    # suspicious but removal is actually a no-op for codegen.
    cast_verify_results: list[dict] = []  # per-cast verify record
    if high_casts and src.exists():
        orig_src = src.read_text()
        try:
            for w in high_casts:
                # Build the drop pattern: remove "(cast_type) " prefix on the
                # cast's line.  We match the exact text the linter found.
                cast_text = f"({w.cast_type}) {w.inner_expr}"
                if cast_text not in orig_src:
                    # Fallback: maybe there's no space after the cast type.
                    cast_text = f"({w.cast_type}){w.inner_expr}"
                if cast_text not in orig_src:
                    cast_verify_results.append({
                        "line": w.line,
                        "cast_type": w.cast_type,
                        "inner_expr": w.inner_expr,
                        "call_target": w.call_target,
                        "pct_before": baseline,
                        "pct_after": None,
                        "delta": None,
                        "note": "could not locate cast text in source",
                    })
                    continue
                patched = orig_src.replace(cast_text, w.inner_expr, 1)
                src.write_text(patched)
                pct_after = _build_and_match(unit, function, melee_root)
                src.write_text(orig_src)  # revert immediately
                delta = (pct_after - baseline) if pct_after is not None else None
                cast_verify_results.append({
                    "line": w.line,
                    "cast_type": w.cast_type,
                    "inner_expr": w.inner_expr,
                    "call_target": w.call_target,
                    "pct_before": baseline,
                    "pct_after": pct_after,
                    "delta": delta,
                    "note": (
                        "WIN" if (delta is not None and delta > 0.0)
                        else "no change" if (delta is not None and delta == 0.0)
                        else "regression" if (delta is not None and delta < 0.0)
                        else "build failed"
                    ),
                })
        finally:
            # Guarantee revert even if an exception was raised mid-loop.
            src.write_text(orig_src)
            subprocess.run(
                ["ninja", f"build/GALE01/src/{unit}.o",
                 "build/GALE01/report.json"],
                cwd=melee_root, capture_output=True,
            )

    if not json_out:
        if high_casts:
            print(f"    ! {len(high_casts)} HIGH-severity cast(s) found — "
                  f"auto-verified:")
            for w, vr in zip(high_casts[:3], cast_verify_results[:3]):
                delta_str = ""
                if vr["delta"] is not None:
                    if vr["delta"] > 0.0:
                        delta_str = (f"  → drop test: {vr['pct_before']:.2f}% → "
                                     f"{vr['pct_after']:.2f}% "
                                     f"(+{vr['delta']:.2f}%, WIN)")
                    else:
                        delta_str = (f"  → drop test: {vr['pct_before']:.2f}% → "
                                     f"{vr['pct_after']:.2f}% "
                                     f"({vr['delta']:+.2f}%, false positive)")
                elif vr.get("note") == "could not locate cast text in source":
                    delta_str = "  → (could not locate cast in source; skipped)"
                else:
                    delta_str = "  → (build failed during verify)"
                print(f"      - line {w.line}: ({w.cast_type}) "
                      f"{w.inner_expr} → {w.call_target}")
                if delta_str:
                    print(f"      {delta_str}")
            if len(high_casts) > 3:
                print(f"      ... +{len(high_casts) - 3} more")
        else:
            print(f"    No HIGH-severity casts.")
        print()

    # Step 2: mutate decl-orders (optional)
    decl_results: list = []
    decl_best_pct: float = baseline
    decl_best_label: Optional[str] = None
    if not skip_decl_orders:
        if not json_out:
            budget_note = f", budget {max_seconds:g}s" if max_seconds else ""
            print(f"[2] Decl-order enumeration ({decl_strategy} strategy, "
                  f"~minute{budget_note})...", flush=True)
        scope_map = get_decl_names_by_scope(src_text, function) if src_text else {}
        selected_scope, selected_scope_reason = _select_decl_order_scope(
            scope_map,
            function,
        )
        names = scope_map.get(selected_scope)
        if not names:
            if not json_out:
                available = ", ".join(
                    f"{'/'.join(scope_path)} ({len(scope_names)} decls)"
                    for scope_path, scope_names in scope_map.items()
                ) or "none"
                print(
                    "    Could not find reorderable decl scope — skipping. "
                    f"Available scopes: {available}."
                )
        else:
            if not json_out:
                print(
                    f"    Scope: {'/'.join(selected_scope)} "
                    f"({selected_scope_reason})"
                )
                nested = [
                    f"{'/'.join(scope_path)} ({len(scope_names)} decls)"
                    for scope_path, scope_names in scope_map.items()
                    if scope_path != selected_scope
                ]
                if nested:
                    print(f"    Other scopes: {', '.join(nested)}")
            # Build candidate list (mirror of enumerate_decl_orders logic)
            n = len(names)
            candidates: list[tuple[str, list[int]]] = []
            if decl_strategy in ("promote", "all"):
                for k in range(1, n):
                    perm = [k] + [i for i in range(n) if i != k]
                    candidates.append((f"promote {names[k]}", perm))
            if decl_strategy in ("demote", "all"):
                for k in range(n - 1):
                    perm = [i for i in range(n) if i != k] + [k]
                    candidates.append((f"demote {names[k]}", perm))
            if decl_strategy in ("swap", "all"):
                for k in range(n - 1):
                    perm = list(range(n))
                    perm[k], perm[k + 1] = perm[k + 1], perm[k]
                    candidates.append((f"swap {names[k]}<->{names[k+1]}",
                                       perm))

            orig = src.read_text()
            decl_failure_dir: Optional[Path] = None

            def _write_failed_decl_candidate(patched_src: str) -> Path:
                nonlocal decl_failure_dir
                if decl_failure_dir is None:
                    safe_function = re.sub(r"[^A-Za-z0-9_.-]+", "_", function)
                    decl_failure_dir = Path(tempfile.mkdtemp(
                        prefix=f"melee-agent-diagnose-{safe_function}-",
                    ))
                digest = hashlib.sha1(patched_src.encode()).hexdigest()[:12]
                candidate_path = decl_failure_dir / f"candidate-{digest}.c"
                candidate_path.write_text(patched_src)
                return candidate_path

            def _bm(patched_src: str):
                src.write_text(patched_src)
                try:
                    pct, diagnostic = _build_and_match_with_diagnostic(
                        unit,
                        function,
                        melee_root,
                    )
                    if pct is not None:
                        return pct
                    candidate_path = _write_failed_decl_candidate(patched_src)
                    return DeclCandidateFailure(
                        status=_classify_decl_candidate_failure(diagnostic),
                        diagnostic=diagnostic,
                        candidate_path=candidate_path,
                    )
                finally:
                    src.write_text(orig)  # revert immediately

            try:
                (
                    decl_results,
                    decl_best_pct,
                    decl_best_label,
                    _stopped_early,
                ) = _run_decl_candidates(
                    candidates,
                    reorder=lambda perm: reorder_decls_in_function_scope(
                        orig,
                        function,
                        selected_scope,
                        perm,
                    ),
                    build_and_match=_bm,
                    baseline=baseline,
                    max_seconds=max_seconds,
                    emit=(lambda msg: print(msg, flush=True)) if not json_out else (lambda msg: None),
                )
            finally:
                src.write_text(orig)
                subprocess.run(
                    ["ninja", f"build/GALE01/src/{unit}.o",
                     "build/GALE01/report.json"],
                    cwd=melee_root, capture_output=True,
                )
            if not json_out:
                if decl_best_label is not None:
                    print(f"    WIN: {decl_best_label} → "
                          f"{decl_best_pct:.2f}% (delta "
                          f"{decl_best_pct - baseline:+.2f}%)")
                else:
                    print(f"    No decl-order win found "
                          f"({len(decl_results)} candidates).")
            print() if not json_out else None
    else:
        if not json_out:
            print(f"[2] Decl-order enumeration: SKIPPED")
            print()

    # HSD_ASSERT override detection — same as in `stuck`.
    ceiling_hsd_assert_strings: list[tuple[str, str]] = []
    _ceiling_built_o = melee_root / "build" / "GALE01" / "src" / f"{unit}.o"
    if _ceiling_built_o.exists():
        try:
            from ..mwcc_debug.o_rewriter import find_anonymous_assert_strings
            ceiling_hsd_assert_strings = find_anonymous_assert_strings(
                _ceiling_built_o)
        except Exception:
            pass
    if ceiling_hsd_assert_strings and not json_out:
        syms_str = ", ".join(
            f"{s} ({v!r})" for s, v in ceiling_hsd_assert_strings)
        print(f"[!] HSD_ASSERT override needed — anonymous .sdata assert "
              f"strings: {syms_str}")
        print(_format_hsd_assert_override_guidance("    "))
        print()

    # SPILLED virtual hints — surface compiler-introduced spills before
    # the verdict. When NO FAST TRANSFORM FOUND is reported but SPILLED
    # virtuals exist, they often point at inline-function code shape
    # (sentinel returns, etc.) that's actually fixable in C. We list each
    # SPILLED virtual along with whatever source binding or first-def IR
    # op virtual-to-var can surface, and flag candidates that look like
    # they came from an inlined callee.
    #
    # Failure modes are non-fatal: no pcdump cache, no SimplifyEntry
    # data, or no source bindings just means we surface less info.
    ceiling_spilled_hints: list[dict] = []
    _pcdump_path_for_spilled: Optional[Path] = None
    try:
        _pcdump_path_for_spilled = _resolve_pcdump_path(
            None, function, melee_root,
        )
    except (typer.Exit, Exception):
        _pcdump_path_for_spilled = None  # cache missing — skip hint pass

    if _pcdump_path_for_spilled is not None:
        try:
            _pcdump_text = (
                diagnose_pcdump_text
                if _pcdump_path_for_spilled == diagnose_pcdump_path
                else _pcdump_path_for_spilled.read_text()
            )
            _src_text = src.read_text() if src.exists() else ""
            _source_file = (
                str(src.relative_to(melee_root))
                if src.exists() else None
            )
            ceiling_spilled_hints = _diagnose_spilled_virtual_hints(
                _pcdump_text,
                function,
                _src_text,
                source_file=_source_file,
            )
        except Exception:
            # Any parse/lookup failure: drop hints; verdict still emits.
            ceiling_spilled_hints = []

    if ceiling_spilled_hints and not json_out:
        print(
            f"[!] SPILLED virtuals (compiler couldn't keep in registers):"
        )
        for _h in ceiling_spilled_hints[:8]:
            _v = _h["virtual"]
            if _h.get("kind") == "call-return":
                _expr = _h.get("expression") or _h.get("call_symbol") or "call return"
                _name = f" -> {_h['var_name']}" if "var_name" in _h else ""
                print(
                    f"    r{_v}: {_expr}{_name} "
                    f"(call-return/copy-chain)"
                    f"{_format_diagnose_hint_location(_h)}"
                )
                if _h.get("copy_chain"):
                    _chain = " <- ".join(
                        f"r{_reg}" for _reg in _h["copy_chain"]
                    )
                    print(f"        chain: {_chain}")
                for _site in _h.get("use_sites", [])[:2]:
                    print(
                        f"        use: B{_site['block_idx']}: "
                        f"`{_site['opcode']} {_site['operands']}`"
                    )
            elif "var_name" in _h:
                print(
                    f"    r{_v}: {_h['var_name']} "
                    f"({_h.get('kind', '?')}/{_h.get('confidence', '?')})"
                )
            elif _h.get("expression") and _h.get("kind") != "first-def":
                print(
                    f"    r{_v}: {_h['expression']} "
                    f"({_h.get('kind', '?')}/{_h.get('confidence', '?')})"
                    f"{_format_diagnose_hint_location(_h)}"
                )
            elif "first_def" in _h:
                _fd = _h["first_def"]
                print(
                    f"    r{_v}: compiler temp — first def in "
                    f"B{_fd['block_idx']}: `{_fd['opcode']} {_fd['operands']}`"
                )
                if "inline_hint" in _h:
                    print(f"        hint: {_h['inline_hint']}")
            else:
                print(f"    r{_v}: (no source binding or first-def found)")
        if len(ceiling_spilled_hints) > 8:
            print(f"    ... +{len(ceiling_spilled_hints) - 8} more")
        if any(_h.get("kind") == "call-return" for _h in ceiling_spilled_hints):
            print(
                "    Call-return copy chains usually need compare-order or "
                "lifetime-shape probes before unrelated local rewrites."
            )
        print(
            f"    Re-run `debug inspect virtual-to-var -f {function} <virt>` for "
            f"each row to get full context."
        )
        print()

    if coupled_force_phys_guidance and not json_out:
        _print_coupled_force_phys_guidance(coupled_force_phys_guidance)
    if register_tiebreak_guidance and not json_out:
        _print_register_tiebreak_guidance(register_tiebreak_guidance)
        print()

    if frame_residual_hint and not json_out:
        print("[!] Frame/local-area residual:")
        print(f"    {frame_residual_hint['message']}")
        print()

    if value_numbering_ceiling and not json_out:
        _print_value_numbering_ceiling(value_numbering_ceiling)

    # Verdict — use verified cast results (not raw heuristic count) so we
    # don't produce false-positive WIN AVAILABLE on no-op casts.
    #
    # A cast counts as a win only if its verified delta is strictly positive.
    # If cast_verify_results is empty (no high casts, or source not found),
    # has_cast_win is False.
    verified_cast_wins = [
        vr for vr in cast_verify_results
        if vr.get("delta") is not None and vr["delta"] > 0.0
    ]
    has_cast_win = bool(verified_cast_wins)
    decl_delta = decl_best_pct - baseline if decl_best_label else 0.0
    has_decl_win = decl_delta >= 0.05

    if has_cast_win or has_decl_win:
        verdict = "WIN AVAILABLE"
        recommendations: list[str] = []
        if has_cast_win:
            win_lines = ", ".join(
                f"line {vr['line']}" for vr in verified_cast_wins[:3]
            )
            if len(verified_cast_wins) > 3:
                win_lines += f" +{len(verified_cast_wins) - 3} more"
            recommendations.append(
                f"Drop {len(verified_cast_wins)} HIGH-severity cast(s) with "
                f"verified improvement ({win_lines}). "
                f"Run `melee-agent debug suggest casts {function}` for details."
            )
        if has_decl_win:
            recommendations.append(
                f"Apply decl-order win: `melee-agent debug "
                f"mutate decl-orders {function} --strategy "
                f"{decl_strategy} --keep-best` → expected "
                f"{decl_best_pct:.2f}%."
            )
    elif frame_residual_hint:
        verdict = "FRAME/LOCAL-AREA RESIDUAL"
        recommendations = [
            frame_residual_hint["message"],
            *frame_residual_hint["next_steps"],
        ]
    elif value_numbering_ceiling:
        verdict = "INTRINSIC VALUE-NUMBERING CEILING"
        recommendations = [
            _value_numbering_ceiling_recommendation(value_numbering_ceiling)
        ]
    else:
        verdict = "NO FAST TRANSFORM FOUND"
        recommendations = _ceiling_recommendations(function, unit)
    recommendations = (
        _diagnose_call_return_recommendations(function, ceiling_spilled_hints)
        + recommendations
    )

    if json_out:
        print(json.dumps({
            "function": function,
            "baseline_pct": baseline,
            "verdict": verdict,
            "high_cast_warnings": [{
                "line": w.line, "call_target": w.call_target,
                "cast_type": w.cast_type, "inner_expr": w.inner_expr,
            } for w in high_casts],
            "med_cast_warnings": [{
                "line": w.line, "call_target": w.call_target,
                "cast_type": w.cast_type, "inner_expr": w.inner_expr,
            } for w in med_casts],
            "cast_verify_results": cast_verify_results,
            "decl_best_label": decl_best_label,
            "decl_best_pct": decl_best_pct,
            "decl_results": decl_results,
            "hsd_assert_strings": [
                {"sym": s, "string": v}
                for s, v in ceiling_hsd_assert_strings
            ],
            "spilled_virtual_hints": ceiling_spilled_hints,
            "coupled_force_phys": coupled_force_phys_guidance,
            "register_tiebreak": register_tiebreak_guidance,
            "frame_residual": frame_residual_hint,
            "value_numbering_ceiling": value_numbering_ceiling,
            "recommendations": recommendations,
        }, indent=2))
        return

    print(f"== VERDICT: {verdict} ==")
    for rec in recommendations:
        print(f"  {rec}")


@inspect_app.command(name="rank-callees")
def rank_callees(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze (required)",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Predict the callee-save cascade for a function before compiling.

    Lists callee-save virtuals (those that got r13-r31) sorted by
    ig_idx descending — the order MWCC's simplifygraph processes them.
    Higher ig_idx = colored first = gets r31, r30, r29, ... via
    top-down nonvolatile dispense.

    Useful for predicting the param-iter-ceiling: if your target wants
    a parameter virtual (low ig_idx) at r31 but several locals have
    higher ig_idx, the cascade will give those locals r31 first and
    the parameter will land lower. No source-level fix.
    """
    pcdump = _resolve_pcdump_path(pcdump, function)
    text = pcdump.read_text()
    events_list = parse_hook_events(text)
    fn_events = find_function(events_list, function)
    if fn_events is None or not fn_events.colorgraph_sections:
        # Fall back to analyze-derived data if no hook events
        fns = parse_pcdump(text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is None:
            _abort_function_not_in_dump(function, [f.name for f in fns])
        infos = analyze_function(fn)
        # No ig_idx info from this path; only sort by virtual num
        callee_saves = [v for v in infos
                        if v.physical is not None and 13 <= v.physical <= 31]
        callee_saves.sort(key=lambda v: -v.virtual)
        if json_out:
            print(json.dumps({
                "function": function,
                "source": "analyze (no hook events)",
                "callees": [{
                    "virtual": v.virtual,
                    "ig_idx": None,
                    "physical": v.physical,
                } for v in callee_saves],
            }, indent=2))
            return
        print(f"Function: {function}")
        print(f"Source:   analyze (no COLORGRAPH DECISIONS in dump)")
        print()
        if not callee_saves:
            print("No callee-save virtuals (r13-r31) found.")
            return
        print(f"{'virtual':>8}  {'phys':>4}  {'note':<30}")
        for v in callee_saves:
            note = "param-like (low virtual #)" if v.virtual <= 34 else ""
            print(f"  r{v.virtual:<6}  r{v.physical:<3}  {note}")
        return

    # Build the cascade from COLORGRAPH DECISIONS sections.
    # Decisions are emitted in iter order (which is descending ig_idx order
    # for the virtual-reg nodes).
    rows: list[dict] = []
    for sec in fn_events.colorgraph_sections:
        for d in sec.decisions:
            if d.ig_idx < 0:
                continue  # physical-reg sentinel nodes — skip
            if not (13 <= d.assigned_reg <= 31):
                continue  # not a callee-save
            rows.append({
                "iter": d.iter_idx,
                "ig_idx": d.ig_idx,
                "assigned_reg": d.assigned_reg,
                "degree": d.degree,
                "class_id": sec.class_id,
            })

    # Sort by ig_idx descending (= iter order = coloring order)
    rows.sort(key=lambda r: -r["ig_idx"])

    # Top-down dispense prediction: the i-th popped virtual gets r(31-i)
    # if workingMask is empty. (workingMask non-empty would pick a caller-
    # save first; the cascade prediction is only meaningful for callee-save-
    # bound virtuals — which is what we filtered to above.)
    expected_seq = list(range(31, 12, -1))  # r31, r30, ..., r13

    enriched = []
    for i, r in enumerate(rows):
        expected = expected_seq[i] if i < len(expected_seq) else None
        is_param_like = r["ig_idx"] <= 34
        match = (expected is not None and r["assigned_reg"] == expected)
        enriched.append({
            **r,
            "expected": expected,
            "expected_match": match,
            "is_param_like": is_param_like,
        })

    if json_out:
        print(json.dumps({
            "function": function,
            "source": "COLORGRAPH DECISIONS",
            "callees": enriched,
        }, indent=2))
        return

    print(f"Function: {function}")
    print(f"Source:   COLORGRAPH DECISIONS")
    print()
    print(
        f"  Predicting the callee-save cascade. Higher ig_idx → colored "
        f"first → gets top of dispense pool."
    )
    print()
    print(
        f"  {'ig_idx':>7}  {'phys':>4}  {'predict':>7}  {'deg':>3}  notes"
    )
    print(f"  {'-'*7}  {'-'*4}  {'-'*7}  {'-'*3}  -----")
    for r in enriched:
        notes = []
        if r["is_param_like"]:
            notes.append("param-like (low ig_idx)")
        if r["expected"] is not None and not r["expected_match"]:
            notes.append(f"got r{r['assigned_reg']} not r{r['expected']}")
        notes_str = "; ".join(notes)
        expected_str = (f"r{r['expected']}" if r["expected"] is not None
                        else "-")
        print(
            f"  {r['ig_idx']:>7}  r{r['assigned_reg']:<3}  {expected_str:>7}  "
            f"{r['degree']:>3}  {notes_str}"
        )

    # Footer: surface param-iter-ceiling if any
    params = [r for r in enriched if r["is_param_like"]]
    if any(p["assigned_reg"] != p.get("expected", -1) for p in params):
        print()
        print(
            "Note: at least one param-like virtual (low ig_idx) landed "
            "below its predicted top-down position. This is the typical "
            "param-iter-ceiling signature — see `debug util patterns "
            "param-iter-ceiling` for the full pattern."
        )


@target_app.command(name="force-phys-from-diff")
def force_phys_from_diff(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze (required).",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    checkdiff_json: Annotated[
        Optional[Path],
        typer.Option(
            "--checkdiff-json",
            help=(
                "Existing `tools/checkdiff.py <function> --format json` "
                "payload. If omitted, this command runs checkdiff with "
                "--no-build."
            ),
        ),
    ] = None,
    checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--checkdiff-timeout",
            help="Timeout in seconds when auto-running checkdiff.",
        ),
    ] = 60.0,
    verify: Annotated[
        bool,
        typer.Option(
            "--verify/--no-verify",
            help=(
                "Run bounded union, singleton, and prefix force-vector "
                "verification after deriving the target list."
            ),
        ),
    ] = False,
    force_vector_probes: Annotated[
        bool,
        typer.Option(
            "--force-vector-probes/--no-force-vector-probes",
            help=(
                "With --verify, run singleton and prefix diagnostic probes "
                "after the full force-vector union."
            ),
        ),
    ] = True,
    force_vector_checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--force-vector-checkdiff-timeout",
            help="Timeout in seconds for each force-vector checkdiff run.",
        ),
    ] = 60.0,
    allow_stale_pcdump: Annotated[
        bool,
        typer.Option(
            "--allow-stale-pcdump",
            help=(
                "Allow an auto-resolved cached pcdump whose source has "
                "changed since capture. Off by default because stale "
                "precolor data can map targets to the wrong ig_idx."
            ),
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Derive --force-phys targets from a register-only checkdiff.

    The command aligns target/current checkdiff assembly lines to the
    function's pre-coloring pcdump, maps each mismatching physical-register
    destination back to its virtual/ig node, and emits both target-spec JSON
    for `debug target score-dump` and a class-scoped force-vector suitable
    for `match-iter-first --force-vector` diagnostic verification.
    """
    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        melee_root,
        require_fresh=not allow_stale_pcdump,
    )
    pcdump_text = pcdump_path.read_text()

    fns = parse_pcdump(pcdump_text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre_pass = fn.last_precolor_pass()
    if pre_pass is None:
        typer.echo(
            f"no pre-coloring pass found in pcdump for {function}",
            err=True,
        )
        raise typer.Exit(4)

    events_fn = find_function(parse_hook_events(pcdump_text), function)
    checkdiff_payload, checkdiff_source = _read_force_phys_checkdiff_payload(
        function=function,
        melee_root=melee_root,
        checkdiff_json=checkdiff_json,
        checkdiff_timeout=checkdiff_timeout,
    )
    payload_function = checkdiff_payload.get("function")
    if isinstance(payload_function, str) and payload_function != function:
        typer.echo(
            f"checkdiff JSON is for {payload_function}, not {function}",
            err=True,
        )
        raise typer.Exit(2)

    target_asm = _checkdiff_asm_lines(checkdiff_payload, "target_asm")
    current_asm = _checkdiff_asm_lines(checkdiff_payload, "current_asm")
    vector = _derive_force_phys_from_register_diff_lines(
        target_asm,
        current_asm,
        pre_pass,
        events_fn,
    )
    target_spec = _force_phys_target_spec(function, vector)
    unit = _find_unit_for_function(function, melee_root)

    force_vector_result: dict | None = None
    if verify:
        force_vector = vector.get("force_vector")
        if not force_vector:
            force_vector_result = {
                "ran": False,
                "reason": "no force-vector targets were derived",
            }
        elif unit is None:
            force_vector_result = {
                "ran": False,
                "reason": "function not found in report.json",
            }
        else:
            src_path = melee_root / "src" / f"{unit}.c"
            if not src_path.exists():
                force_vector_result = {
                    "ran": False,
                    "reason": f"source not found: {src_path}",
                }
            else:
                try:
                    entries = _parse_force_vector(force_vector)
                    force_vector_result = _run_force_vector_auto_verify(
                        src_path=src_path,
                        function=function,
                        entries=entries,
                        melee_root=melee_root,
                        checkdiff_timeout=force_vector_checkdiff_timeout,
                        run_diagnostic_probes=force_vector_probes,
                    )
                    force_vector_result["ran"] = True
                except Exception as exc:
                    force_vector_result = {
                        "ran": False,
                        "reason": str(exc),
                    }

    classification = checkdiff_payload.get("classification")
    result_payload = {
        "function": function,
        "unit": unit,
        "pcdump": str(pcdump_path),
        "checkdiff_source": checkdiff_source,
        "checkdiff_classification": classification,
        "target_spec": target_spec,
        "force_phys": vector["force_phys"],
        "force_phys_csv": vector["force_phys_csv"],
        "force_vector": vector["force_vector"],
        "targets": vector["targets"],
        "conflicts": vector["conflicts"],
        "register_only_target_count": vector["register_only_target_count"],
        "frame_alignment": vector.get("frame_alignment"),
    }
    if force_vector_result is not None:
        result_payload["force_vector_verify"] = force_vector_result

    if json_out:
        print(json.dumps(result_payload, indent=2))
        return

    print(f"Function: {function}")
    if unit:
        print(f"Unit:     {unit}")
    print(f"PCDump:   {pcdump_path}")
    print(f"Checkdiff: {checkdiff_source}")
    frame_alignment = vector.get("frame_alignment") or {}
    if frame_alignment.get("applied"):
        print(
            "Frame alignment: "
            f"target=0x{frame_alignment['target_frame_size']:x} "
            f"current=0x{frame_alignment['current_frame_size']:x} "
            f"delta={frame_alignment['frame_delta']}"
        )
    print()
    if not vector["targets"]:
        print("No register-only physical-register target destinations derived.")
    else:
        print("Derived force-phys targets from register-only checkdiff:")
        for target in vector["targets"]:
            current = target.get("current_reg_name") or "?"
            status = (
                "already target"
                if target.get("already_target") is True
                else "needs move"
                if target.get("already_target") is False
                else "current unknown"
            )
            print(
                f"  class{target['class_id']} ig{target['ig_idx']} -> "
                f"{target['target_reg_name']} "
                f"(current {current}; {status}; "
                f"{target['occurrence_count']} occurrence"
                f"{'' if target['occurrence_count'] == 1 else 's'})"
            )
    if vector["conflicts"]:
        print()
        print("Conflicting targets skipped:")
        for conflict in vector["conflicts"]:
            print(
                f"  class{conflict['class_id']} ig{conflict['ig_idx']} "
                f"wanted both {conflict['kind']}{conflict['existing_phys']} "
                f"and {conflict['kind']}{conflict['conflicting_phys']}"
            )
    print()
    print("Target spec for debug target score-dump:")
    print(json.dumps(target_spec, indent=2))
    if vector["force_phys_csv"]:
        print()
        print(f"Force-phys vector: {vector['force_phys_csv']}")
    if vector["force_vector"]:
        print(f"Force-vector: {vector['force_vector']}")
    if force_vector_result is not None:
        print()
        print("== force-vector verify ==")
        if not force_vector_result.get("ran"):
            print(f"  did not run: {force_vector_result.get('reason')}")
        else:
            union = force_vector_result.get("union", {})
            if isinstance(union, dict):
                print(
                    f"  union: {union.get('status')} "
                    f"(returncode {union.get('returncode')})"
                )
            probes = force_vector_result.get("probes")
            if isinstance(probes, list) and probes:
                print("  diagnostic probes:")
                for probe in probes:
                    print(
                        f"    {probe.get('label')}: {probe.get('status')} "
                        f"(returncode {probe.get('returncode')})"
                    )


@target_app.command(name="match-iter-first")
def match_iter_first(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze (required)",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    regs: Annotated[
        str,
        typer.Option(
            "--regs",
            help="Comma-separated physical regs to report on "
                 "(for example r31,r30, f31-f30, gpr-callee for "
                 "r31-r25, or gpr-volatile,r0 for volatile target diffs; "
                 "default: r31,r30,r29,r28).",
        ),
    ] = "r31,r30,r29,r28",
    asm: Annotated[
        Optional[Path],
        typer.Option(
            "--asm",
            help="Override path to expected .s file. "
                 "Auto-resolves via report.json.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
    auto_verify: Annotated[
        bool,
        typer.Option(
            "--auto-verify",
            help="When ambiguous targets are present, run "
                 "`debug dump local --force-iter-first <list>` to score the "
                 "recommended list against the expected output and "
                 "report the match% delta. Then restore object/report "
                 "state with a managed cleanup bounded by "
                 "MWCC_DEBUG_RESTORE_TIMEOUT, falling back to "
                 "MWCC_DEBUG_HANG_TIMEOUT. Restore failures print "
                 "cleanup_complete=false in JSON and exit non-zero. "
                 "Off by default — the explicit verify step costs ~10–30s.",
        ),
    ] = False,
    force_vector: Annotated[
        Optional[str],
        typer.Option(
            "--force-vector",
            help=(
                "Compose several force overrides and verify them together "
                "with `debug dump local --diff`. Entries are comma-separated: "
                "ig40:phys=r30, ig42:coalesce=38, "
                "class0:iter5:phys=r31, ig50:iter-first. The union is tested "
                "first, then singleton and prefix probes run by default to "
                "expose incompatible steps."
            ),
        ),
    ] = None,
    force_vector_probes: Annotated[
        bool,
        typer.Option(
            "--force-vector-probes/--no-force-vector-probes",
            help=(
                "When --force-vector is set, also test each singleton entry "
                "and each intermediate prefix after the full union."
            ),
        ),
    ] = True,
    force_vector_checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--force-vector-checkdiff-timeout",
            help="Timeout in seconds for each force-vector integrated checkdiff run.",
        ),
    ] = 60.0,
    allow_stale_pcdump: Annotated[
        bool,
        typer.Option(
            "--allow-stale-pcdump",
            help=(
                "Allow an auto-resolved cached pcdump whose source has "
                "changed since capture. Off by default because target "
                "derivation can produce stale ig_idx mappings."
            ),
        ),
    ] = False,
) -> None:
    """Recommend --force-iter-first arguments by reading the expected .s.

    For each physical register in --regs, finds the first instruction in
    the expected output that defines it (post-prologue), structurally
    aligns that instruction to the current pcdump's pre-coloring pass,
    and reports the virtual register (= ig_idx in MWCC's IG).

    Useful for local-vs-local iter-order cascades where rank-callees
    can't tell which local "should have" gotten r31. Pipe the output's
    ig_idx list into --force-iter-first.

    Warning: when any matched target has `[ambiguous]` confidence
    (multiple pre-coloring instructions matched the expected signature),
    feeding the full list to --force-iter-first can disturb unrelated
    code. Verify with `debug dump local <tu> --force-iter-first <list>
    --diff` (or run with --auto-verify) before trusting the suggestion.

    Auto-verify cleanup is bounded by MWCC_DEBUG_RESTORE_TIMEOUT, falling back
    to MWCC_DEBUG_HANG_TIMEOUT; restore failures print cleanup_complete=false.

    --force-vector composes multiple force overrides, verifies the union with
    integrated checkdiff, and probes individual/prefix steps for compatibility.
    """
    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        melee_root,
        require_fresh=not allow_stale_pcdump,
    )
    pcdump_text = pcdump_path.read_text()

    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"function '{function}' not found in report.json. "
            f"Run `ninja build/GALE01/report.json` and retry.",
            err=True,
        )
        raise typer.Exit(2)

    if asm is None:
        asm_path = melee_root / "build" / "GALE01" / "asm" / f"{unit}.s"
    else:
        asm_path = asm
    if not asm_path.exists():
        typer.echo(
            f"expected .s not found: {asm_path}\n"
            f"Run `python configure.py && ninja` to build it.",
            err=True,
        )
        raise typer.Exit(3)

    asm_text = asm_path.read_text()
    asm_fn = asm_extract_function(asm_text, function)
    if asm_fn is None:
        typer.echo(
            f"function '{function}' not found in {asm_path}",
            err=True,
        )
        raise typer.Exit(3)

    prologue_end = asm_parse_prologue_end(asm_fn.instructions)
    body = asm_fn.instructions[prologue_end:]

    fns = parse_pcdump(pcdump_text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre_pass = fn.last_precolor_pass()
    if pre_pass is None:
        typer.echo(
            f"no pre-coloring pass found in pcdump for {function}",
            err=True,
        )
        raise typer.Exit(4)

    try:
        reg_list = _parse_match_iter_first_regs(regs)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    results: list[dict] = []
    for reg in reg_list:
        expected_def = asm_find_first_def(
            body,
            target_reg=reg.number,
            reg_kind=reg.kind,
        )
        if expected_def is None:
            results.append({
                "reg": reg.number,
                "kind": reg.kind,
                "reg_name": reg.name,
                "status": "unused",
                "note": (
                    f"{reg.name} never used as a destination in expected"
                ),
            })
            continue
        pos, expected_ist = expected_def
        match = match_virtual_for_expected_def(
            expected_ist=expected_ist,
            expected_position=pos,
            pre_pass=pre_pass,
            reg_kind=reg.kind,
        )
        if match is None:
            results.append({
                "reg": reg.number,
                "kind": reg.kind,
                "reg_name": reg.name,
                "status": "no_match",
                "note": f"no structural match in pre-coloring for "
                        f"`{expected_ist.opcode} {expected_ist.operands}`",
            })
            continue
        results.append({
            "reg": reg.number,
            "kind": reg.kind,
            "reg_name": reg.name,
            "status": "ok",
            "ig_idx": match.ig_idx,
            "virtual": match.virtual,
            "instr_idx": match.instruction_index,
            "opcode": expected_ist.opcode,
            "operands": expected_ist.operands,
            "confidence": match.confidence,
        })

    # Detect ambiguous matches up front so both text and JSON paths agree.
    ig_indices: list[int] = list(dict.fromkeys(
        r["ig_idx"] for r in results if r.get("status") == "ok"
    ))
    ambiguous_results = [
        r for r in results
        if r.get("status") == "ok" and r.get("confidence") == "ambiguous"
    ]
    has_ambiguous = bool(ambiguous_results)
    warning_message: Optional[str] = None
    if has_ambiguous:
        amb_regs = ", ".join(
            str(r.get("reg_name") or f"r{r['reg']}")
            for r in ambiguous_results
        )
        warning_message = (
            f"{len(ambiguous_results)} target(s) are [ambiguous] "
            f"({amb_regs}) — multiple pre-coloring instructions matched "
            f"the expected signature, and the closest-position pick may "
            f"be wrong. Before trusting this output, verify with "
            f"`debug dump local <c_file> --force-iter-first "
            f"{','.join(str(i) for i in ig_indices)} "
            f"--force-iter-first-fn {function} --diff` "
            f"(or pass --auto-verify on this command). If the diff "
            f"doesn't improve, the ambiguous assignments are wrong; "
            f"try a subset."
        )

    events_fn = find_function(parse_hook_events(pcdump_text), function)
    target_vector = _build_match_iter_first_target_vector(results, events_fn)

    force_vector_entries: list[_ForceVectorEntry] | None = None
    force_vector_result: Optional[dict] = None
    if force_vector is not None:
        try:
            force_vector_entries = _parse_force_vector(force_vector)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(2) from exc
        src_path = melee_root / "src" / f"{unit}.c"
        if not src_path.exists():
            force_vector_result = {
                "ran": False,
                "reason": f"source not found: {src_path}",
            }
        else:
            try:
                force_vector_result = _run_force_vector_auto_verify(
                    src_path=src_path,
                    function=function,
                    entries=force_vector_entries,
                    melee_root=melee_root,
                    checkdiff_timeout=force_vector_checkdiff_timeout,
                    run_diagnostic_probes=force_vector_probes,
                )
                force_vector_result["ran"] = True
            except Exception as exc:
                force_vector_result = {"ran": False, "reason": str(exc)}

    # Optional auto-verify: run debug dump local with the proposed iter-first
    # list, compare per-function match% against the baseline, and surface
    # the delta. Gated behind --auto-verify because the underlying MWCC
    # compile is the slow part (~10–30s in our local wibo path).
    auto_verify_result: Optional[dict] = None
    if auto_verify and ig_indices:
        try:
            src_path = melee_root / "src" / f"{unit}.c"
            if not src_path.exists():
                auto_verify_result = {
                    "ran": False,
                    "reason": f"source not found: {src_path}",
                }
            else:
                print(
                    f"[auto-verify] resolving baseline match% for {function}",
                    file=sys.stderr,
                )
                baseline_pct = _get_match_pct(function, melee_root)
                ig_csv_av = ",".join(str(i) for i in ig_indices)
                watchdog_s = os.environ.get("MWCC_DEBUG_HANG_TIMEOUT", "45")
                print(
                    f"[auto-verify] debug dump local watchdog: {watchdog_s}s "
                    f"without compile progress",
                    file=sys.stderr,
                )
                # Run debug dump local with the override. The dump itself is
                # discarded; dump local's local watchdog bounds no-progress
                # hangs, while this wrapper emits periodic status so long
                # runs are visibly alive.
                auto_verify_output = (
                    src_path.parent
                    / f".{function}.auto-verify.{os.getpid()}.{int(time.time() * 1000)}.pcdump.txt"
                )
                cmd = _build_match_iter_first_auto_verify_cmd(
                    src_path=src_path,
                    ig_csv=ig_csv_av,
                    function=function,
                    output_path=auto_verify_output,
                )
                status_label = (
                    f"--force-iter-first {ig_csv_av} "
                    f"--force-iter-first-fn {function}"
                )
                r_av = _run_auto_verify_command_with_status(
                    cmd,
                    cwd=melee_root / "tools" / "melee-agent",
                    status_label=status_label,
                )
                auto_verify_output.unlink(missing_ok=True)
                print(
                    "[auto-verify] reading post-verify match%",
                    file=sys.stderr,
                )
                new_pct = _get_match_pct(function, melee_root)
                delta = (
                    None if (new_pct is None or baseline_pct is None)
                    else new_pct - baseline_pct
                )
                auto_verify_result = {
                    "ran": True,
                    "returncode": r_av.returncode,
                    "status": "ok" if r_av.returncode == 0 else "verify_failed",
                    "force_iter_first": target_vector["force_iter_first"],
                    "force_iter_first_csv": target_vector["force_iter_first_csv"],
                    "force_phys": target_vector["force_phys"],
                    "force_phys_csv": target_vector["force_phys_csv"],
                    "force_vector": target_vector["force_vector"],
                    "baseline_pct": baseline_pct,
                    "new_pct": new_pct,
                    "delta": delta,
                    "stderr_tail": "\n".join(
                        r_av.stderr.splitlines()[-5:]
                    ) if r_av.stderr else "",
                }
                # Restore the report by rebuilding the .o cleanly so the
                # cached state isn't poisoned by our verify override.
                (
                    restore_timeout_s,
                    restore_timeout_source,
                ) = _resolve_auto_verify_restore_timeout()
                restore_max_steps = _resolve_auto_verify_restore_max_steps()
                print(
                    f"[auto-verify] restore timeout: {restore_timeout_s:g}s "
                    f"({restore_timeout_source})",
                    file=sys.stderr,
                )
                print(
                    f"[auto-verify] restore max dry-run steps: "
                    f"{restore_max_steps}",
                    file=sys.stderr,
                )
                print(
                    "[auto-verify] restoring clean object/report state",
                    file=sys.stderr,
                )
                restore_proc, restore_planned_steps = (
                    _restore_object_report_for_unit(
                        unit=unit,
                        melee_root=melee_root,
                        timeout_s=restore_timeout_s,
                        max_steps=restore_max_steps,
                        force=False,
                    )
                )
                if restore_planned_steps > restore_max_steps:
                    print(
                        f"[auto-verify] restore skipped: dry-run planned "
                        f"{restore_planned_steps} ninja steps, above "
                        f"MWCC_DEBUG_RESTORE_MAX_STEPS={restore_max_steps}",
                        file=sys.stderr,
                    )
                restore_stderr_tail = "\n".join(
                    restore_proc.stderr.splitlines()[-5:]
                ) if restore_proc.stderr else ""
                restore_result = {
                    "returncode": restore_proc.returncode,
                    "timeout_s": restore_timeout_s,
                    "timeout_source": restore_timeout_source,
                    "max_steps": restore_max_steps,
                    "planned_steps": restore_planned_steps,
                    "stderr_tail": restore_stderr_tail,
                }
                restore_hint = _auto_verify_restore_cleanup_hint(
                    restore_proc.stderr or ""
                )
                if restore_hint:
                    restore_result["cleanup_hint"] = restore_hint
                auto_verify_result["restore"] = restore_result
                if restore_proc.returncode == 0:
                    auto_verify_result["cleanup_complete"] = True
                else:
                    auto_verify_result["status"] = "restore_failed"
                    auto_verify_result["cleanup_complete"] = False
        except (subprocess.TimeoutExpired, Exception) as _av_exc:
            auto_verify_result = {"ran": False, "reason": str(_av_exc)}

    if isinstance(auto_verify_result, dict):
        _annotate_auto_verify_actionability(auto_verify_result)

    if json_out:
        payload: dict = {
            "function": function,
            "unit": unit,
            "results": results,
            "has_ambiguous": has_ambiguous,
            "target_vector": target_vector,
            "force_iter_first": target_vector["force_iter_first"],
            "force_iter_first_csv": target_vector["force_iter_first_csv"],
            "force_phys": target_vector["force_phys"],
            "force_phys_csv": target_vector["force_phys_csv"],
            "force_vector": target_vector["force_vector"],
            "force_vector_runnable": target_vector.get(
                "force_vector_runnable", True,
            ),
            "force_vector_conflicts": target_vector.get("conflicts", []),
        }
        if warning_message:
            payload["warning"] = warning_message
        if auto_verify_result is not None:
            payload["auto_verify"] = auto_verify_result
            status = auto_verify_result.get("status")
            if status:
                payload["auto_verify_status"] = status
            actionability = auto_verify_result.get("actionability")
            if actionability:
                payload["auto_verify_actionability"] = actionability
            if "cleanup_complete" in auto_verify_result:
                payload["cleanup_complete"] = auto_verify_result[
                    "cleanup_complete"
                ]
        if force_vector_result is not None:
            payload["force_vector_verify"] = force_vector_result
            union = force_vector_result.get("union")
            if isinstance(union, dict):
                payload["force_vector_status"] = union.get("status")
                payload["force_vector_match"] = union.get("match")
        print(json.dumps(payload, indent=2))
        exit_code = _auto_verify_failure_exit_code(auto_verify_result)
        if exit_code is not None:
            raise typer.Exit(exit_code)
        return

    print(f"Function: {function}")
    print(f"Unit:     {unit}")
    print(f"ASM:      {asm_path.relative_to(melee_root)}")
    print()
    print(f"Expected iter-first targets:")
    for r in results:
        reg_str = str(r.get("reg_name") or f"r{r['reg']}")
        virt_str = f"{r.get('kind', 'r')}{r['virtual']}" if r["status"] == "ok" else ""
        if r["status"] == "ok":
            print(
                f"  {reg_str} <- ig_idx {r['ig_idx']:<4} "
                f"(virt {virt_str}, instr {r['instr_idx']}: "
                f"{r['opcode']} {r['operands']}) [{r['confidence']}]"
            )
        else:
            print(f"  {reg_str} - {r['note']}")
    if ig_indices:
        ig_csv = ",".join(str(i) for i in ig_indices)
        print()
        print("Full target vector:")
        for target in target_vector["targets"]:
            current = target.get("current_reg_name") or "?"
            status = (
                "already target"
                if target.get("already_target") is True
                else "needs move"
                if target.get("already_target") is False
                else "current unknown"
            )
            print(
                f"  {target['target_reg_name']} <- ig_idx "
                f"{target['ig_idx']} (current {current}; {status})"
            )
        print()
        print(f"Try:")
        print(
            f"  melee-agent debug dump local <source.c> "
            f"--force-iter-first {ig_csv} "
            f"--force-iter-first-fn {function} --diff"
        )
        if target_vector["force_phys_csv"]:
            print(
                f"Force-phys vector for scorer setup: "
                f"{target_vector['force_phys_csv']}"
            )
        if target_vector["force_vector"]:
            print(
                f"Force-vector for diagnostic probes: "
                f"{target_vector['force_vector']}"
            )
        if target_vector.get("conflicts"):
            print("Force-vector conflicts omitted from runnable vector:")
            for conflict in target_vector["conflicts"]:
                class_part = (
                    f"class{conflict['class_id']}:"
                    if conflict.get("class_id") is not None else ""
                )
                regs = ", ".join(conflict.get("target_reg_names") or [])
                print(
                    f"  {class_part}ig{conflict['ig_idx']} has multiple "
                    f"target phys regs: {regs}"
                )
    if warning_message:
        print()
        print(f"WARNING: {warning_message}")
    if auto_verify_result is not None:
        print()
        print(f"== auto-verify ==")
        if auto_verify_result.get("ran"):
            base = auto_verify_result.get("baseline_pct")
            new = auto_verify_result.get("new_pct")
            delta = auto_verify_result.get("delta")
            base_str = (
                f"{base:.2f}%" if isinstance(base, (int, float)) else "?"
            )
            new_str = (
                f"{new:.2f}%" if isinstance(new, (int, float)) else "?"
            )
            delta_str = (
                f"{delta:+.2f}%" if isinstance(delta, (int, float))
                else "(unknown)"
            )
            print(
                f"  baseline -> with override: {base_str} -> {new_str} "
                f"({delta_str})"
            )
            actionability_note = auto_verify_result.get("actionability_note")
            if actionability_note:
                print(f"  actionability: {auto_verify_result.get('actionability')} - {actionability_note}")
            tail = auto_verify_result.get("stderr_tail")
            if tail:
                print(f"  stderr tail:")
                for line in tail.splitlines():
                    print(f"    {line}")
            restore = auto_verify_result.get("restore")
            if isinstance(restore, dict):
                print(
                    f"  restore object/report: exit "
                    f"{restore.get('returncode')} "
                    f"(timeout {restore.get('timeout_s')}s"
                    f" via {restore.get('timeout_source', 'unknown')}; "
                    f"planned {restore.get('planned_steps', '?')} steps, "
                    f"max {restore.get('max_steps', '?')})"
                )
                restore_tail = restore.get("stderr_tail")
                if restore_tail:
                    print(f"  restore stderr tail:")
                    for line in restore_tail.splitlines():
                        print(f"    {line}")
                cleanup_hint = restore.get("cleanup_hint")
                if cleanup_hint:
                    print(f"  cleanup hint: {cleanup_hint}")
        else:
            print(f"  did not run: {auto_verify_result.get('reason')}")
    if force_vector_result is not None:
        print()
        print("== force-vector verify ==")
        if not force_vector_result.get("ran"):
            print(f"  did not run: {force_vector_result.get('reason')}")
        else:
            union = force_vector_result.get("union", {})
            if isinstance(union, dict):
                print(
                    f"  union: {union.get('status')} "
                    f"(returncode {union.get('returncode')})"
                )
                for key in (
                    "force_phys_csv",
                    "force_phys_iter_csv",
                    "force_coalesce_csv",
                    "force_iter_first_csv",
                ):
                    if union.get(key):
                        print(f"    {key}: {union[key]}")
                stdout_tail = union.get("stdout_tail")
                if stdout_tail and union.get("status") != "match":
                    print("    stdout tail:")
                    for line in str(stdout_tail).splitlines():
                        print(f"      {line}")
            probes = force_vector_result.get("probes")
            if isinstance(probes, list) and probes:
                print("  diagnostic probes:")
                for probe in probes:
                    print(
                        f"    {probe.get('label')}: {probe.get('status')} "
                        f"(returncode {probe.get('returncode')})"
                    )
    exit_code = _auto_verify_failure_exit_code(auto_verify_result)
    if exit_code is not None:
        raise typer.Exit(exit_code)


@util_app.command(name="name-magic")
def name_magic(
    o_file: Annotated[
        Path,
        typer.Argument(help="Path to the .o file to post-process."),
    ],
    mapping: Annotated[
        Optional[str],
        typer.Option(
            "--map", "-m",
            help="Mapping of magic constant value to symbol name. "
                 "Format: '<value>=<name>,<value>=<name>'. <value> is "
                 "'s32' (0x4330000080000000), 'u32' (0x4330000000000000), "
                 "or a hex/decimal literal. May be specified once with "
                 "multiple pairs.",
        ),
    ] = None,
    out: Annotated[
        Optional[Path],
        typer.Option(
            "--out", "-o",
            help="Output path (default: rewrite in place).",
        ),
    ] = None,
    list_only: Annotated[
        bool,
        typer.Option(
            "--list",
            help="Just list anonymous .sdata2 symbols and their values; "
                 "don't rename.",
        ),
    ] = False,
    globalize: Annotated[
        bool,
        typer.Option(
            "--globalize/--no-globalize",
            help="After renaming, promote each new symbol to global "
                 "(STB_GLOBAL) via objcopy --globalize-symbol. Default "
                 "true — the expected .o always has these symbols as "
                 "global, so local symbols produce a symbol-binding diff "
                 "even after renaming.",
        ),
    ] = True,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Rename anonymous @N symbols in a .o's .sdata2 to user-supplied names.

    Use case: MWCC's int-to-float cast emits an anonymous symbol like
    `@491` for the 0x4330000080000000 magic constant. The matching .o
    references this data via a named global like `mnVibration_804DC018`
    (from symbols.txt). The relocation target name diff blocks byte
    matching even when the data is identical.

    With `--map s32=mnVibration_804DC018`, this tool finds the
    anonymous symbol whose .sdata2 value matches the s32 int-to-float
    bias and renames it via objcopy.  The new symbol is also promoted to
    global (``STB_GLOBAL``) by default, matching the binding in the
    expected .o.  Pass ``--no-globalize`` to skip this step.

    Use `--list` to see what's available without renaming.
    """
    from ..mwcc_debug.o_rewriter import (
        find_all_anonymous_sdata2_symbols,
        globalize_symbols,
        parse_mapping,
        rename_magic_symbols,
    )

    if not o_file.exists():
        typer.echo(f".o file not found: {o_file}", err=True)
        raise typer.Exit(2)

    if list_only:
        symbols = find_all_anonymous_sdata2_symbols(o_file)
        if json_out:
            print(json.dumps({
                "o_file": str(o_file),
                "symbols": [{
                    "name": s.name,
                    "offset": s.offset,
                    "value": f"0x{s.value:016x}" if s.size == 8
                             else f"0x{s.value:08x}",
                    "size": s.size,
                } for s in symbols],
            }, indent=2))
            return
        if not symbols:
            print(f"No anonymous .sdata2 symbols found in {o_file}")
            return
        print(f"Anonymous .sdata2 symbols in {o_file}:")
        print(f"  {'name':<10}  {'offset':>6}  {'sz':>2}  {'value':<18}  notes")
        print(f"  {'-'*10}  {'-'*6}  {'-'*2}  {'-'*18}  -----")
        import struct as _struct
        for sym in symbols:
            note = ""
            if sym.size == 8:
                value_str = f"0x{sym.value:016x}"
                if sym.value == 0x4330000080000000:
                    note = "int-to-float bias (signed)"
                elif sym.value == 0x4330000000000000:
                    note = "int-to-float bias (unsigned)"
            elif sym.size == 4:
                value_str = f"0x{sym.value:08x}"
                # Try interpreting as float for the note
                try:
                    f_val = _struct.unpack(">f",
                                           _struct.pack(">I", sym.value))[0]
                    note = f"float ≈ {f_val:g}"
                except Exception:
                    pass
            else:
                value_str = f"0x{sym.value:x}"
            print(
                f"  {sym.name:<10}  {sym.offset:>6}  {sym.size:>2}  "
                f"{value_str:<18}  {note}"
            )
        return

    if mapping is None:
        typer.echo(
            "no --map provided. Use --list to see available symbols.",
            err=True,
        )
        raise typer.Exit(2)

    try:
        value_to_name = parse_mapping(mapping)
    except ValueError as e:
        typer.echo(f"invalid --map: {e}", err=True)
        raise typer.Exit(2)

    try:
        renames = rename_magic_symbols(
            o_file, value_to_name, out_path=out
        )
    except FileNotFoundError as e:
        typer.echo(
            f"objcopy not found: {e}. Install devkitPPC or pass a custom "
            f"path via the o_rewriter module.",
            err=True,
        )
        raise typer.Exit(5)
    except subprocess.CalledProcessError as e:
        typer.echo(f"objcopy failed: {e}", err=True)
        raise typer.Exit(5)

    # Promote renamed symbols to global so the binding matches the expected
    # .o.  The rename step leaves them local (MWCC emits anonymous symbols as
    # STB_LOCAL); the expected .o always has them STB_GLOBAL.
    globalized: list[str] = []
    if globalize and renames:
        target_path = out if out is not None else o_file
        new_names = [new for _, new in renames]
        try:
            globalize_symbols(target_path, new_names)
            globalized = new_names
        except FileNotFoundError as e:
            typer.echo(
                f"objcopy not found during globalize: {e}. "
                f"Rename succeeded but symbols remain local.",
                err=True,
            )
        except subprocess.CalledProcessError as e:
            typer.echo(
                f"objcopy --globalize-symbol failed: {e}. "
                f"Rename succeeded but symbols remain local.",
                err=True,
            )

    if json_out:
        print(json.dumps({
            "o_file": str(o_file),
            "out": str(out) if out else str(o_file),
            "renames": [
                {"old": old, "new": new} for old, new in renames
            ],
            "globalized": globalized,
        }, indent=2))
        return

    target = out if out is not None else o_file
    if not renames:
        print(
            f"No matching anonymous symbols found in {o_file}. "
            f"Use --list to see what's available."
        )
        return
    print(f"Renamed {len(renames)} symbol(s) in {target}:")
    for old, new in renames:
        glob_note = " (globalized)" if new in globalized else ""
        print(f"  {old} -> {new}{glob_note}")


# ---------------------------------------------------------------------------
# setup-simplify-order-scorer: end-to-end campaign setup
# ---------------------------------------------------------------------------


# Sentinel marker line we drop at the top of a wrapped compile.sh so future
# invocations can detect "already wrapped" without parsing the body.
_SIMPLIFY_SCORER_COMPILE_MARKER = (
    "# Wrapped by melee-agent debug permute setup-simplify-order-scorer"
)


def _render_force_phys_target_yaml(
    *,
    function: str,
    class_id: int,
    baseline_dump: Path,
    force_phys: Mapping[int, int],
    coalesce_preservation: bool = True,
) -> str:
    lines = [
        "# Generated by melee-agent debug permute setup-simplify-order-scorer",
        "# objective: force-phys",
        f"function: {function}",
        f"class_id: {class_id}",
        f"baseline_dump: {baseline_dump}",
        "force_phys:",
    ]
    for ig_idx, phys in sorted(force_phys.items()):
        lines.append(f"  {ig_idx}: {phys}")
    if not coalesce_preservation:
        lines.append("coalesce_preservation: false")
    return "\n".join(lines) + "\n"


def _build_simplify_order_compile_sh(
    *,
    wibo_path: Path,
    debug_compiler: Path,
    project_root: Path,
    cflags: str,
) -> str:
    """Generate a compile.sh that produces .o + sibling pcdump per call.

    Permuter invokes compile.sh with positional args ``$1 = source.c`` and
    ``$3 = out.o`` (with ``-o`` in slot ``$2``). The wrapped script:

      1. Stages the .c into ``nonmatchings/.permuter_stage_$$.c`` (the
         existing mwcc+wibo macOS-path-assertion workaround, see
         fix_perm_compile.py).
      2. Sets ``MWCC_DEBUG_PCDUMP_PATH=<out.o>.pcdump.txt`` so the
         patched DLL writes the pcdump sidecar next to the .o.
      3. Invokes wibo + mwcceppc_debug with the unit's normal cflags.

    The pcdump-sidecar convention is the contract that
    ``debug target score-simplify-order`` consumes — it reads
    ``<o>.pcdump.txt`` to compute the score, no recompile.
    """
    return "\n".join([
        "#!/usr/bin/env bash",
        _SIMPLIFY_SCORER_COMPILE_MARKER,
        "set -e",
        "INPUT_ABS=\"$(realpath \"$1\")\"",
        "OUTPUT_ABS=\"$(realpath \"$3\")\"",
        f"cd {shlex.quote(str(project_root))}",
        "STAGE=\"nonmatchings/.permuter_stage_$$.c\"",
        "mkdir -p nonmatchings",
        "cp \"$INPUT_ABS\" \"$STAGE\"",
        "trap 'rm -f \"$STAGE\"' EXIT",
        "# Deposit the pcdump as a sibling of the .o so",
        "# `debug target score-simplify-order` finds it via the fast path.",
        "export MWCC_DEBUG_PCDUMP_PATH=\"${OUTPUT_ABS}.pcdump.txt\"",
        f"{shlex.quote(str(wibo_path))} {shlex.quote(str(debug_compiler))} "
        f"{cflags} -c \"$STAGE\" -o \"$OUTPUT_ABS\"",
        "",
    ])


def _detect_existing_compile_sh_project_root(text: str) -> Optional[str]:
    """Pull the `cd <project_root>` line out of an existing compile.sh.

    Returns the path string (the part after `cd `) or None if not found.
    We do this because permuter's import.py + our prior fix_perm_compile
    encode the project root into compile.sh, and we want to preserve it
    when generating a fresh wrapper.
    """
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("cd "):
            return s[len("cd "):].strip()
    return None


@permute_app.command(name="setup-simplify-order-scorer")
def setup_simplify_order_scorer(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to set up the simplify-order scorer for "
                 "(required). Must match the function name inside the "
                 "perm dir's base.c.",
        ),
    ],
    want_first: Annotated[
        Optional[str],
        typer.Option(
            "--want-first",
            help="Target simplify-order prefix, comma-separated ig_idx "
                 "values. E.g. '42,32' means we want ig_idx 42 to be the "
                 "first simplification target and 32 to be the second. "
                 "Mutually exclusive with --want-late.",
        ),
    ] = None,
    want_late: Annotated[
        Optional[str],
        typer.Option(
            "--want-late",
            help=(
                "Target ig_idx sequence at the END of simplify order, "
                "comma-separated (e.g., '46,44'). Mutually exclusive with "
                "--want-first. Use for high-volatile target physicals "
                "(r10-r12) per deferred-debt #20 Phase 3."
            ),
        ),
    ] = None,
    class_id: Annotated[
        int,
        typer.Option(
            "--class",
            help="Register class to score against. 0 = GPR (default), "
                 "1 = FPR.",
        ),
    ] = 0,
    baseline_dump: Annotated[
        Optional[Path],
        typer.Option(
            "--baseline-dump",
            help="Path to a pre-search pcdump.txt for the function. If "
                 "omitted, the command will fail with instructions on "
                 "how to generate one via `debug dump local`.",
        ),
    ] = None,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    timeout_seconds: Annotated[
        float,
        typer.Option(
            "--scorer-timeout",
            help="Per-candidate scorer timeout in seconds (passed through "
                 "to permuter's [scorer].timeout_seconds).",
        ),
    ] = 5.0,
    scorer_mode: Annotated[
        str,
        typer.Option(
            "--scorer-mode",
            help=(
                "Permuter scorer objective: simplify-order (default) or "
                "force-phys. force-phys scores candidate pcdumps by whether "
                "target ig_idx values receive their requested physical regs."
            ),
        ),
    ] = "simplify-order",
    bootstrap: Annotated[
        bool,
        typer.Option(
            "--bootstrap",
            help="If the permuter function dir is missing, create it first "
                 "with `debug permute bootstrap` semantics before wiring "
                 "the simplify-order scorer.",
        ),
    ] = False,
    auto_baseline_dump: Annotated[
        bool,
        typer.Option(
            "--auto-baseline-dump",
            help="Generate <perm-dir>/baseline.pcdump.txt with "
                 "`debug dump local` when --baseline-dump is omitted.",
        ),
    ] = False,
    melee_agent_bin: Annotated[
        str,
        typer.Option(
            "--melee-agent",
            help="Command to invoke melee-agent. Default 'melee-agent' "
                 "assumes the wrapper is on $PATH. Override for testing "
                 "or non-standard installs.",
        ),
    ] = "melee-agent",
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help=(
                "Optional force-phys mapping (comma-separated ig_idx:phys pairs, "
                "e.g. '34:31,37:30,32:29'). Captured into target.yaml for the "
                "pre-flight polarity check. Pass the same mapping you used in "
                "--force-phys when proving the function's force allocation."
            ),
        ),
    ] = None,
    no_coalesce_preservation: Annotated[
        bool,
        typer.Option(
            "--no-coalesce-preservation",
            help=(
                "Disable the coalesce-preservation constraint in the scorer. "
                "By default (when --force-phys is provided), candidates that "
                "coalesce any force_phys key ig_idx into another root are "
                "rejected as structurally infeasible. Pass this flag to opt "
                "out — useful for diagnostic runs or when the target tolerates "
                "coalescing."
            ),
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite existing simplify_order_target.yaml / "
                 "settings.toml / compile.sh without prompting. Use when "
                 "you've already set up a campaign and want to retarget.",
        ),
    ] = False,
) -> None:
    """Wire decomp-permuter to save candidates that improve simplify-order.

    Configures the perm dir at ``<perm_root>/nonmatchings/<function>/`` to
    use our lex-encoded simplify-order + precolor scorer in place of the
    built-in objdiff scorer. Writes three files:

      1. ``simplify_order_target.yaml`` — the target spec (function,
         simplify_order_target, class_id, baseline_dump).
      2. ``settings.toml`` — adds a ``[scorer]`` section pointing at
         ``melee-agent debug target score-simplify-order``. Preserves
         existing weight_overrides via the permuter_config builder.
      3. ``compile.sh`` — wrapped to use mwcc_debug + emit a pcdump
         sidecar next to each candidate .o. The score-simplify-order
         command reads that sidecar via the fast path.

    Requires the companion decomp-permuter [scorer] interface patch
    (commit 81378ff on the decomp-permuter side).

    Next step after running this command: ``./permuter.py <perm_dir>``
    will produce candidates in ``<perm_dir>/output-*/``. The score is
    the integer printed by score-simplify-order — lower is better,
    0 = perfect prefix hit with no precolor disturbance.
    """
    from ..mwcc_debug.permuter_config import (
        ScorerConfig,
        SettingsTomlSpec,
        build_spec,
        parse_existing_overrides,
        render_settings_toml,
        render_simplify_order_target_yaml,
        write_settings_toml,
    )

    # ----------------------------------------------------------------
    # Validate inputs
    # ----------------------------------------------------------------

    perm_dir = perm_root / "nonmatchings" / function
    if not perm_dir.is_dir():
        if bootstrap:
            _bootstrap_permuter_dir(
                function,
                perm_root=perm_root,
                source_file=None,
                melee_root=None,
                preserve_macros=_PERMUTER_DEFAULT_PRESERVE_MACROS,
                force=force,
            )
            perm_dir = perm_root / "nonmatchings" / function
        if not perm_dir.is_dir():
            typer.echo(
                f"perm dir not found: {perm_dir}\n"
                f"Expected layout: <perm_root>/nonmatchings/<function>/\n"
                f"Create one first with:\n"
                f"  melee-agent extract get {function} --create-scratch\n"
                f"or by running decomp-permuter's import.py.",
                err=True,
            )
            raise typer.Exit(2)

    if baseline_dump is None and auto_baseline_dump:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is None:
            typer.echo(
                f"could not find {function!r} in report.json. "
                "Rebuild report.json and retry.",
                err=True,
            )
            raise typer.Exit(2)
        src_path = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
        if not src_path.exists():
            typer.echo(f"source not found: {src_path}", err=True)
            raise typer.Exit(2)
        baseline_dump = perm_dir / "baseline.pcdump.txt"
        if force or not baseline_dump.exists():
            baseline_dump.parent.mkdir(parents=True, exist_ok=True)
            dump_cmd = [
                sys.executable,
                "-m",
                "src.cli",
                "debug",
                "dump",
                "local",
                str(src_path),
                "--output",
                str(baseline_dump),
                "--function",
                function,
                "--no-cache-sync",
            ]
            dump_proc = subprocess.run(
                dump_cmd,
                cwd=DEFAULT_MELEE_ROOT / "tools" / "melee-agent",
                capture_output=True,
                text=True,
            )
            if dump_proc.returncode != 0:
                typer.echo(dump_proc.stderr or dump_proc.stdout, err=True)
                raise typer.Exit(dump_proc.returncode or 1)

    if scorer_mode not in {"simplify-order", "force-phys"}:
        typer.echo(
            "error: --scorer-mode must be one of: simplify-order, force-phys",
            err=True,
        )
        raise typer.Exit(code=2)
    force_phys_mode = scorer_mode == "force-phys"

    if want_first is not None and want_late is not None:
        typer.echo(
            "error: --want-first and --want-late are mutually exclusive",
            err=True,
        )
        raise typer.Exit(code=2)
    if not force_phys_mode and want_first is None and want_late is None:
        typer.echo(
            "error: must specify exactly one of --want-first or --want-late",
            err=True,
        )
        raise typer.Exit(code=2)
    if force_phys_mode and (want_first is not None or want_late is not None):
        typer.echo(
            "error: --scorer-mode force-phys does not use --want-first/--want-late",
            err=True,
        )
        raise typer.Exit(code=2)

    parsed_targets: tuple[int, ...] = ()
    parsed_targets_late: tuple[int, ...] = ()
    if want_first is not None:
        try:
            parsed_targets = tuple(
                int(s.strip()) for s in want_first.split(",") if s.strip()
            )
        except ValueError:
            typer.echo(
                f"--want-first must be a comma-separated list of integers; "
                f"got {want_first!r}",
                err=True,
            )
            raise typer.Exit(2)
        if not parsed_targets:
            typer.echo(
                "--want-first must contain at least one ig_idx value", err=True
            )
            raise typer.Exit(2)
    if want_late is not None:
        try:
            parsed_targets_late = tuple(
                int(s.strip()) for s in want_late.split(",") if s.strip()
            )
        except ValueError:
            typer.echo(
                f"--want-late must be a comma-separated list of integers; "
                f"got {want_late!r}",
                err=True,
            )
            raise typer.Exit(2)
        if not parsed_targets_late:
            typer.echo(
                "--want-late must contain at least one ig_idx value", err=True
            )
            raise typer.Exit(2)

    if baseline_dump is None:
        typer.echo(
            "--baseline-dump is required.\n"
            "Generate one via:\n"
            f"  melee-agent debug dump local <c_file_for_{function}>\n"
            "Then re-run this command with `--baseline-dump <path>`.",
            err=True,
        )
        raise typer.Exit(2)
    baseline_dump = baseline_dump.expanduser().resolve()
    if not baseline_dump.exists():
        typer.echo(
            f"--baseline-dump {baseline_dump} does not exist", err=True
        )
        raise typer.Exit(2)

    # Pre-flight: ensure the requested function is actually in the
    # baseline so we don't write a broken spec.
    baseline_text = baseline_dump.read_text(encoding="utf-8")
    if function not in baseline_text:
        typer.echo(
            f"baseline dump {baseline_dump} does not appear to contain "
            f"function {function!r}. Check the dump or regenerate it.",
            err=True,
        )
        raise typer.Exit(2)

    # ----------------------------------------------------------------
    # Locate the debug compiler + wibo for the wrapper compile.sh
    # ----------------------------------------------------------------

    wibo_path = _find_wibo()
    if wibo_path is None or not wibo_path.exists():
        typer.echo(
            "wibo not found. Run `melee-agent debug dump setup` first "
            "or set $MWCC_DEBUG_WIBO.",
            err=True,
        )
        raise typer.Exit(2)
    debug_compiler = _find_compiler_dir() / "mwcceppc_debug.exe"
    if not debug_compiler.exists():
        typer.echo(
            f"patched compiler not found: {debug_compiler}. "
            f"Run `melee-agent debug dump setup` first.",
            err=True,
        )
        raise typer.Exit(2)

    # ----------------------------------------------------------------
    # Resolve cflags for the wrapper compile.sh.
    # Strategy: read the existing compile.sh in the perm dir and rip
    # the cflags off its mwcc invocation. This way we preserve whatever
    # weird flags the perm dir was set up with (e.g. extra -i paths).
    # ----------------------------------------------------------------

    existing_compile_sh = perm_dir / "compile.sh"
    if not existing_compile_sh.exists():
        typer.echo(
            f"perm dir {perm_dir} lacks compile.sh — was the function "
            f"imported correctly? Run import.py first.",
            err=True,
        )
        raise typer.Exit(2)
    existing_compile_text = existing_compile_sh.read_text(encoding="utf-8")

    # Refuse to clobber an already-wrapped compile.sh unless --force.
    # The marker indicates a previous run of this command, in which
    # case re-running is intentional only when --force is passed.
    if (
        _SIMPLIFY_SCORER_COMPILE_MARKER in existing_compile_text
        and not force
    ):
        typer.echo(
            f"compile.sh already wrapped by setup-simplify-order-scorer. "
            f"Pass --force to re-wrap.",
            err=True,
        )
        raise typer.Exit(2)

    project_root_str = _detect_existing_compile_sh_project_root(
        existing_compile_text
    )
    if project_root_str is None:
        typer.echo(
            f"could not parse `cd <project_root>` line from "
            f"{existing_compile_sh}. The compile.sh doesn't match the "
            f"expected import.py/fix-compile shape — bail out and "
            f"inspect manually.",
            err=True,
        )
        raise typer.Exit(2)
    project_root = Path(project_root_str)

    cflags = _extract_cflags_from_compile_sh(existing_compile_text)
    if cflags is None:
        typer.echo(
            f"could not extract cflags from {existing_compile_sh}. "
            f"Expected a mwcceppc.exe (or wibo+mwcceppc.exe) invocation "
            f"with standard flags. Bail out and inspect manually.",
            err=True,
        )
        raise typer.Exit(2)

    # ----------------------------------------------------------------
    # Parse optional --force-phys mapping for the polarity check.
    # ----------------------------------------------------------------

    parsed_force_phys: dict[int, int] = {}
    if force_phys is not None:
        for pair in force_phys.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if ":" not in pair:
                typer.echo(
                    f"error: --force-phys entry '{pair}' must be IG_IDX:PHYS_REG",
                    err=True,
                )
                raise typer.Exit(code=2)
            ig_str, phys_str = pair.split(":", 1)
            try:
                ig_idx = int(ig_str.strip())
                phys = int(phys_str.strip())
            except ValueError:
                typer.echo(
                    f"error: --force-phys entry '{pair}' must be IG_IDX:PHYS_REG "
                    f"with integer values",
                    err=True,
                )
                raise typer.Exit(code=2)
            parsed_force_phys[ig_idx] = phys
    if force_phys_mode and not parsed_force_phys:
        typer.echo(
            "error: --scorer-mode force-phys requires --force-phys IG:PHYS entries",
            err=True,
        )
        raise typer.Exit(code=2)

    # ----------------------------------------------------------------
    # Write simplify_order_target.yaml
    # ----------------------------------------------------------------

    spec_path = perm_dir / "simplify_order_target.yaml"
    if spec_path.exists() and not force:
        typer.echo(
            f"{spec_path} already exists. Pass --force to overwrite.",
            err=True,
        )
        raise typer.Exit(2)

    coalesce_preservation = not no_coalesce_preservation
    if force_phys_mode:
        spec_yaml = _render_force_phys_target_yaml(
            function=function,
            class_id=class_id,
            baseline_dump=baseline_dump,
            force_phys=parsed_force_phys,
            coalesce_preservation=coalesce_preservation,
        )
    else:
        spec_yaml = render_simplify_order_target_yaml(
            function=function,
            simplify_order_target=parsed_targets,
            simplify_order_target_late=parsed_targets_late,
            class_id=class_id,
            baseline_dump=baseline_dump,
            force_phys=parsed_force_phys or None,
            coalesce_preservation=coalesce_preservation,
        )
    spec_path.write_text(spec_yaml, encoding="utf-8")

    # ----------------------------------------------------------------
    # Update settings.toml (preserve existing weight_overrides)
    # ----------------------------------------------------------------

    settings_path = perm_dir / "settings.toml"
    existing_overrides: dict[str, float] = {}
    if settings_path.exists():
        existing_overrides = parse_existing_overrides(
            settings_path.read_text(encoding="utf-8")
        )

    # Build the scorer command: a fully-quoted invocation of
    # `melee-agent debug target score-simplify-order` with --function
    # and --target pre-baked. Permuter appends the .o path as argv[N].
    scorer_command_name = (
        "score-force-phys" if force_phys_mode else "score-simplify-order"
    )
    scorer_command = " ".join(
        shlex.quote(s) for s in [
            melee_agent_bin,
            "debug",
            "target",
            scorer_command_name,
            "--function",
            function,
            "--target",
            str(spec_path),
        ]
    )

    scorer_cfg = ScorerConfig(
        command=scorer_command,
        timeout_seconds=timeout_seconds,
    )

    new_spec = build_spec(
        function,
        pattern=None,
        existing_overrides=existing_overrides,
        merge=True,
        scorer=scorer_cfg,
    )
    write_settings_toml(new_spec, settings_path)

    # ----------------------------------------------------------------
    # Replace compile.sh with the wrapped version
    # ----------------------------------------------------------------

    new_compile = _build_simplify_order_compile_sh(
        wibo_path=wibo_path,
        debug_compiler=debug_compiler,
        project_root=project_root,
        cflags=cflags,
    )
    existing_compile_sh.write_text(new_compile, encoding="utf-8")
    existing_compile_sh.chmod(0o755)

    # ----------------------------------------------------------------
    # Final summary + next-step instructions
    # ----------------------------------------------------------------

    typer.echo(f"Wrote {spec_path}")
    typer.echo(f"Wrote {settings_path}")
    typer.echo(f"Wrote {existing_compile_sh}")
    typer.echo("")
    typer.echo("Setup complete. Next:")
    typer.echo(f"  cd {perm_root}")
    typer.echo(f"  ./permuter.py nonmatchings/{function}")
    typer.echo("")
    typer.echo(
        (
            "Candidates that improve force-phys assignment will be saved to "
            if force_phys_mode
            else "Candidates that improve simplify-order will be saved to "
        ) + f"{perm_dir}/output-*/."
    )


_CFLAGS_LINE_RE = re.compile(
    # Match a line containing mwcceppc(_debug)?.exe (possibly via wibo or wine)
    # and capture everything between the .exe and either "$INPUT" or "-c".
    r"mwcceppc(?:_debug)?\.exe\s+(.*?)(?:\s+-c\b|\s+\"\$INPUT\"|\s+\$INPUT\b)"
)


def _extract_cflags_from_compile_sh(text: str) -> Optional[str]:
    """Rip the mwcc cflags out of a compile.sh body.

    The expected line shape is one of::

        wine ... mwcceppc.exe <flags...> -c "$INPUT" -o "$OUTPUT"
        wibo ... mwcceppc.exe <flags...> -c "$INPUT" -o "$OUTPUT"
        ... mwcceppc.exe <flags...> "$INPUT" -o "$OUTPUT"

    We pull out <flags...> as a single shlex-joinable string so we can
    re-emit them inside the new wrapper. If the compile.sh doesn't
    match any of these shapes, returns None.
    """
    m = _CFLAGS_LINE_RE.search(text)
    if not m:
        return None
    return m.group(1).strip()


@permute_app.command(name="config")
def gen_permuter_config(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to generate permuter config for (required).",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    pattern: Annotated[
        Optional[str],
        typer.Option(
            "--pattern", "-p",
            help="Override pattern auto-detection. Use a name from "
                 "`debug util patterns` (e.g. decl-order, alias-split).",
        ),
    ] = None,
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Target spec (YAML or JSON, from `debug target derive`). "
                 "Auto-detection needs this to identify wrong virtuals. "
                 "Without it, falls back to stock settings unless "
                 "--pattern is provided.",
        ),
    ] = None,
    out: Annotated[
        Optional[Path],
        typer.Option(
            "--out", "-o",
            help="Output path. Default: "
                 "<perm-root>/nonmatchings/<function>/settings.toml",
        ),
    ] = None,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    print_only: Annotated[
        bool,
        typer.Option(
            "--print",
            help="Print rendered TOML to stdout instead of writing.",
        ),
    ] = False,
    merge: Annotated[
        bool,
        typer.Option(
            "--merge",
            help="Preserve existing [weight_overrides] keys not touched "
                 "by the pattern profile. Default: overwrite.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Generate config even for skip-marked patterns "
                 "(e.g. param-iter-ceiling). Use only if you know why.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit a JSON summary of the action."),
    ] = False,
) -> None:
    """Generate a decomp-permuter settings.toml tuned for the detected pattern.

    Pairs with `debug permute triage` to close the integration loop: this
    command BIASES which mutations permuter prefers based on mwcc-debug's
    pattern detection, then debug permute triage filters out base.c-vs-real-tree
    drift on the resulting winners.

    For patterns with no useful permuter weighting profile yet
    (for example, param-iter-ceiling), this command refuses to generate
    a config and points at the evidence-gathering workflow. Use
    `--force` to override.

    For `decl-order` specifically, you should ALSO run
    `debug mutate decl-orders` first — it's deterministic and
    ~100x faster than letting permuter rediscover decl-order rounds.
    """
    from ..mwcc_debug.patterns import (
        PATTERNS,
        get_pattern,
        patterns_for_category,
    )
    from ..mwcc_debug.permuter_config import (
        PatternSkippedError,
        build_spec,
        parse_existing_overrides,
        render_settings_toml,
        write_settings_toml,
    )

    melee_root = DEFAULT_MELEE_ROOT

    # Determine the pattern
    detected_via: str = ""
    selected: Optional = None  # type: ignore[type-arg]
    if pattern is not None:
        # Explicit pattern — skip pcdump resolution entirely. Useful when
        # the function isn't yet in report.json (e.g. setting up permuter
        # for a newly-imported function).
        selected = get_pattern(pattern)
        if selected is None:
            typer.echo(
                f"unknown pattern: {pattern!r}. "
                f"Run `melee-agent debug util patterns` to list.",
                err=True,
            )
            raise typer.Exit(2)
        detected_via = "--pattern flag"
    else:
        # Auto-detect via guide/suggest infrastructure
        pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
        text = pcdump_path.read_text()
        fns = parse_pcdump(text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is None:
            _abort_function_not_in_dump(function, [f.name for f in fns])
        events_list = parse_hook_events(text)
        events = find_function(events_list, function)
        if target is not None:
            target_spec = _load_target_spec(target)
        else:
            target_spec = {"virtuals": {}}
        result = score_function(fn, target_spec, events=events)
        suggestions = suggest(fn, result, events=events)

        # Walk suggestions in severity order. For each, find the best-fit
        # pattern. Prefer permuter_skip patterns when they match — those
        # need a different workflow message.
        for s in suggestions:
            candidates = patterns_for_category(s.category)
            # Prefer skip-marked patterns (they're more specific signals)
            skip_candidates = [p for p in candidates if p.permuter_skip]
            if skip_candidates:
                selected = skip_candidates[0]
                detected_via = (
                    f"suggestion category={s.category!r} (severity={s.severity})"
                )
                break
            # Otherwise pick the first pattern with weights
            for p in candidates:
                if p.permuter_weights:
                    selected = p
                    detected_via = (
                        f"suggestion category={s.category!r} "
                        f"(severity={s.severity})"
                    )
                    break
            if selected is not None:
                break

        if selected is None and suggestions:
            # Suggestions exist but no pattern has weights for any category
            detected_via = "no pattern matched any suggestion category"

    # Resolve output path
    if out is None:
        if not perm_root.exists():
            typer.echo(
                f"--perm-root {perm_root} does not exist. "
                f"Clone decomp-permuter there or pass --out explicitly.",
                err=True,
            )
            raise typer.Exit(2)
        fn_dir = _resolve_permuter_function_dir(
            function, perm_root=perm_root, melee_root=melee_root)
        if not fn_dir.exists() and not print_only:
            typer.echo(
                f"{fn_dir} does not exist.\n"
                + _permuter_import_hint(
                    function,
                    perm_root=perm_root,
                    melee_root=melee_root,
                ),
                err=True,
            )
            raise typer.Exit(2)
        out = fn_dir / "settings.toml"

    # Read existing overrides if present (for --merge)
    existing_overrides: dict[str, float] = {}
    if out.exists() and merge:
        existing_overrides = parse_existing_overrides(out.read_text())

    # Build the spec
    try:
        spec = build_spec(
            function,
            selected,
            existing_overrides=existing_overrides,
            merge=merge,
            force=force,
        )
    except PatternSkippedError:
        # No useful permuter weighting profile — print guidance instead of writing.
        assert selected is not None
        if json_out:
            print(json.dumps({
                "function": function,
                "pattern": selected.name,
                "detected_via": detected_via,
                "action": "skipped",
                "reason": "permuter_skip=True (requires Tier 6 evidence workflow)",
            }, indent=2))
            raise typer.Exit(1)
        typer.echo(
            f"Pattern: {selected.name} "
            f"(detected via {detected_via})",
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "This is a Tier 6 allocator-order mismatch with no current "
            "permuter weight profile. The parameter virtual gets a low "
            "ig_idx by C semantics, and locals win the top callee-saves "
            "under the observed simplify order.",
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "Recommended: confirm via `debug target match-iter-first -f "
            f"{function}` and record the result as allocator-order evidence. "
            "If the target is reached, use source-shape search; otherwise "
            "mark it unresolved by current heuristics.",
            err=True,
        )
        typer.echo(
            "Pass --force to debug permute config if you want a config "
            "anyway (no permuter_weights will be applied).",
            err=True,
        )
        raise typer.Exit(1)

    # Render
    rendered = render_settings_toml(spec)

    if print_only:
        if json_out:
            print(json.dumps({
                "function": function,
                "pattern": spec.pattern_name,
                "detected_via": detected_via,
                "action": "printed",
                "overrides": spec.weight_overrides,
                "toml": rendered,
            }, indent=2))
            return
        print(rendered, end="")
        return

    write_settings_toml(spec, out)

    # Side-effect: fix the compile.sh for macOS+wine if it has the
    # known import.py path-handling bug. Quiet if not applicable;
    # one-liner note if a fix was applied.
    from ..mwcc_debug.fix_perm_compile import fix_perm_dir
    compile_fix = fix_perm_dir(out.parent)

    if json_out:
        print(json.dumps({
            "function": function,
            "pattern": spec.pattern_name,
            "detected_via": detected_via,
            "action": "wrote",
            "path": str(out),
            "overrides": spec.weight_overrides,
            "compile_sh_fix": {
                "action": compile_fix.action,
                "reason": compile_fix.reason,
            },
        }, indent=2))
        return

    if spec.pattern_name:
        print(f"Pattern: {spec.pattern_name} (detected via {detected_via})")
        if spec.weight_overrides:
            print(f"Weight overrides:")
            for key in sorted(spec.weight_overrides):
                print(f"  {key} = {spec.weight_overrides[key]}")
    else:
        print(f"No pattern detected ({detected_via or 'no suggestions'}). "
              f"Wrote stock settings.")
    print(f"Wrote: {out}")
    if compile_fix.action == "fixed":
        print(
            f"Also fixed: {compile_fix.path.name} "
            f"(macOS+wine path handling)"
        )
    print()

    # Tail recommendation
    if spec.pattern_name == "decl-order":
        print(
            "Tip: for decl-order specifically, try the deterministic "
            "search first — it's ~100x faster than letting permuter "
            "rediscover decl-order rounds:"
        )
        print(
            f"  melee-agent debug mutate decl-orders "
            f"-f {function} --keep-best"
        )
        print(
            "If that doesn't find a win, fall back to permuter with "
            "this config."
        )
    else:
        rel_dir = out.parent.relative_to(perm_root) \
            if perm_root in out.parents else out.parent
        print(f"Run: cd {perm_root} && ./permuter.py {rel_dir}")


@permute_app.command(name="fix-compile")
def fix_perm_compile(
    target: Annotated[
        Path,
        typer.Argument(
            help="Path to either a nonmatchings/<fn>/ directory or a "
                 "compile.sh file directly.",
        ),
    ],
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Fix decomp-permuter's `compile.sh` for macOS+wine compatibility.

    The compile.sh generated by `import.py` passes an absolute mac path
    to mwcc via wine, which fails with an OS_PATHSEP assertion. This
    command rewrites it to stage the candidate as a relative path
    inside `nonmatchings/.permuter_stage_$$.c` (git-ignored,
    parallel-safe), which mwcc accepts.

    Idempotent: re-running on an already-fixed file is a no-op.

    Pass either the function's permuter dir (e.g.
    `~/code/decomp-permuter/nonmatchings/fn_xyz`) or the compile.sh
    directly.
    """
    from ..mwcc_debug.fix_perm_compile import (
        fix_compile_sh,
        fix_perm_dir,
    )

    if not target.exists():
        typer.echo(f"target not found: {target}", err=True)
        raise typer.Exit(2)

    if target.is_dir():
        result = fix_perm_dir(target)
    else:
        result = fix_compile_sh(target)

    if json_out:
        print(json.dumps({
            "path": str(result.path),
            "action": result.action,
            "reason": result.reason,
        }, indent=2))
        if result.action in ("skipped", "not-applicable"):
            raise typer.Exit(1)
        return

    icons = {
        "fixed": "[ok]",
        "already-fixed": "[--]",
        "not-applicable": "[!!]",
        "skipped": "[!!]",
    }
    icon = icons.get(result.action, "[??]")
    print(f"{icon} {result.path}")
    print(f"   {result.action}: {result.reason}")
    if result.action == "fixed":
        print()
        print("Now permuter's compile.sh will:")
        print("  1. Stage the candidate as nonmatchings/.permuter_stage_$$.c")
        print("  2. Pass that relative path to mwcc (avoids OS_PATHSEP)")
        print("  3. Clean up the stage file on exit")
    if result.action in ("skipped", "not-applicable"):
        raise typer.Exit(1)


def _find_wibo() -> Optional[Path]:
    """Locate the patched wibo binary. Resolution order:

    1. $MWCC_DEBUG_WIBO env var
    2. <melee_root>/tools/mwcc_debug/bin/wibo (vendored — built by build_wibo.sh)
    3. <melee_root>/../melee-harness/bin/wibo (adjacent harness checkout)
    4. ~/code/melee-harness/bin/wibo
    """
    import os as _os
    env = _os.environ.get("MWCC_DEBUG_WIBO")
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None
    candidates = [
        DEFAULT_MELEE_ROOT / "tools" / "mwcc_debug" / "bin" / "wibo",
        DEFAULT_MELEE_ROOT.parent / "melee-harness" / "bin" / "wibo",
        Path("~/code/melee-harness/bin/wibo").expanduser(),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _build_local_wibo() -> Optional[Path]:
    """Build the vendored wibo via tools/mwcc_debug/build_wibo.sh.
    Returns the built path or None on failure.
    """
    build_script = (
        DEFAULT_MELEE_ROOT / "tools" / "mwcc_debug" / "build_wibo.sh"
    )
    if not build_script.exists():
        return None
    try:
        subprocess.run(
            [str(build_script)],
            cwd=build_script.parent,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None
    out = build_script.parent / "bin" / "wibo"
    return out if out.exists() else None


def _find_compiler_dir() -> Path:
    """Path to the GC/1.2.5n compiler directory."""
    return DEFAULT_MELEE_ROOT / "build" / "compilers" / "GC" / "1.2.5n"


def _build_local_dll() -> Optional[Path]:
    """Build the mwcc_debug DLL via tools/mwcc_debug/build_macos.sh.
    Returns the built DLL path or None on failure.
    """
    build_script = (
        DEFAULT_MELEE_ROOT / "tools" / "mwcc_debug" / "build_macos.sh"
    )
    if not build_script.exists():
        return None
    try:
        proc = subprocess.run(
            [str(build_script)],
            cwd=build_script.parent,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout, end="")
        if exc.stderr:
            typer.echo(exc.stderr, err=True)
        return None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        typer.echo(proc.stderr, err=True)
    built = build_script.parent / "MWDBG326.dll"
    if built.exists():
        return built
    import_name_dll = build_script.parent / "lmgr326b.dll"
    if import_name_dll.exists():
        shutil.copy2(import_name_dll, built)
        print(
            f"[ok] using alternate DLL output {import_name_dll.name} "
            f"as {built.name}"
        )
        return built
    return built


@dataclasses.dataclass(frozen=True)
class _DumpSetupCheck:
    label: str
    ok: bool
    detail: str


def _check_path(label: str, path: Path, *, executable: bool = False) -> _DumpSetupCheck:
    if not path.exists():
        return _DumpSetupCheck(label, False, f"missing: {path}")
    if executable and not os.access(path, os.X_OK):
        return _DumpSetupCheck(label, False, f"not executable: {path}")
    return _DumpSetupCheck(label, True, str(path))


def _path_newer_than(left: Path, right: Path) -> bool:
    return left.stat().st_mtime_ns > right.stat().st_mtime_ns


def _dll_needs_rebuild(dll_path: Path, source_path: Path) -> bool:
    if not dll_path.exists():
        return True
    if not source_path.exists():
        return False
    return _path_newer_than(source_path, dll_path)


def _check_mwcc_debug_dll_freshness(
    tools_dir: Path,
    compiler_dir: Path,
) -> _DumpSetupCheck:
    source = tools_dir / "mwcc_debug.c"
    built_dll = tools_dir / "MWDBG326.dll"
    deployed_dll = compiler_dir / "MWDBG326.dll"
    missing = [p for p in (source, built_dll, deployed_dll) if not p.exists()]
    if missing:
        missing_s = ", ".join(str(p) for p in missing)
        return _DumpSetupCheck(
            "mwcc_debug DLL freshness",
            False,
            f"missing freshness input: {missing_s}",
        )

    stale: list[str] = []
    if _path_newer_than(source, built_dll):
        stale.append(f"{source} is newer than DLL {built_dll}")
    if _path_newer_than(source, deployed_dll):
        stale.append(f"{source} is newer than deployed DLL {deployed_dll}")
    elif _path_newer_than(built_dll, deployed_dll):
        stale.append(f"{built_dll} is newer than deployed DLL {deployed_dll}")
    if stale:
        return _DumpSetupCheck(
            "mwcc_debug DLL freshness",
            False,
            "; ".join(stale),
        )
    return _DumpSetupCheck(
        "mwcc_debug DLL freshness",
        True,
        f"{built_dll} and {deployed_dll} are current for {source}",
    )


def _local_dump_setup_checks() -> list[_DumpSetupCheck]:
    melee_root = DEFAULT_MELEE_ROOT
    compiler_dir = _find_compiler_dir()
    tools_dir = melee_root / "tools" / "mwcc_debug"
    wibo = _find_wibo()
    checks = [
        (
            _DumpSetupCheck(
                "wibo",
                False,
                "missing: set $MWCC_DEBUG_WIBO or build vendored wibo",
            )
            if wibo is None
            else _check_path("wibo", wibo, executable=True)
        ),
        _check_path("compiler directory", compiler_dir),
        _check_path("stock compiler", compiler_dir / "mwcceppc.exe"),
        _check_path("patched compiler", compiler_dir / "mwcceppc_debug.exe"),
        _check_path("mwcc_debug DLL source", tools_dir / "MWDBG326.dll"),
        _check_path("deployed DLL", compiler_dir / "MWDBG326.dll"),
        _check_path("mwcc_debug C source", tools_dir / "mwcc_debug.c"),
        _check_mwcc_debug_dll_freshness(tools_dir, compiler_dir),
        _check_path("wibo build script", tools_dir / "build_wibo.sh"),
        _check_path("DLL build script", tools_dir / "build_macos.sh"),
        _check_path("compiler patcher", tools_dir / "patch_mwcceppc_for_wibo.py"),
    ]
    return checks


def _print_local_dump_setup_checks(checks: list[_DumpSetupCheck]) -> None:
    for check in checks:
        status = "PASS" if check.ok else "FAIL"
        print(f"{status}\t{check.label}\t{check.detail}")


@dump_app.command(name="setup")
def setup_local(
    rebuild_dll: Annotated[
        bool,
        typer.Option(
            "--rebuild-dll",
            help="Rebuild the mwcc_debug DLL via build_macos.sh even if "
                 "it already exists.",
        ),
    ] = False,
) -> None:
    """One-time setup for local mwcc_debug pcdump (macOS+wibo).

    Steps:
    1. Verify wibo binary is available (built via melee-harness).
    2. Build the mwcc_debug DLL via tools/mwcc_debug/build_macos.sh
       if not already present.
    3. Patch a copy of mwcceppc.exe to import MWDBG326.dll instead
       of LMGR326B.dll (lives next to the stock compiler as
       mwcceppc_debug.exe; stock compiler untouched).
    4. Copy the DLL into the compiler dir so wibo finds it.

    After setup, `melee-agent debug dump local <c_file>` works.

    Wibo dependency: this command expects Luke Champine's patched wibo
    at <melee>/../melee-harness/bin/wibo (or path in $MWCC_DEBUG_WIBO).
    Clone melee-harness adjacent to melee and build via its setup.sh.
    """
    melee_root = DEFAULT_MELEE_ROOT
    compiler_dir = _find_compiler_dir()

    # 1. Locate wibo, or build it
    wibo = _find_wibo()
    if wibo is None:
        print("[..] wibo not found; building via build_wibo.sh...")
        wibo = _build_local_wibo()
        if wibo is None:
            typer.echo(
                "wibo build failed. See tools/mwcc_debug/build_wibo.sh.\n"
                "Alternatives: set $MWCC_DEBUG_WIBO=<path-to-wibo-binary>.",
                err=True,
            )
            raise typer.Exit(2)
    print(f"[ok] wibo: {wibo}")

    # 2. Build the DLL if needed
    dll_c_source = melee_root / "tools" / "mwcc_debug" / "mwcc_debug.c"
    dll_src = melee_root / "tools" / "mwcc_debug" / "MWDBG326.dll"
    dll_is_stale = _dll_needs_rebuild(dll_src, dll_c_source)
    if rebuild_dll or dll_is_stale:
        if rebuild_dll:
            reason = "--rebuild-dll requested"
        elif dll_src.exists():
            reason = "mwcc_debug.c is newer than MWDBG326.dll"
        else:
            reason = "MWDBG326.dll is missing"
        print(f"[..] building mwcc_debug DLL via build_macos.sh ({reason})...")
        built = _build_local_dll()
        if built is None or not built.exists():
            typer.echo(
                "DLL build failed. Check tools/mwcc_debug/build_macos.sh.",
                err=True,
            )
            raise typer.Exit(3)
        dll_src = built
    print(f"[ok] DLL:  {dll_src}")

    # 3. Patch the compiler if needed
    stock_compiler = compiler_dir / "mwcceppc.exe"
    debug_compiler = compiler_dir / "mwcceppc_debug.exe"
    patcher = melee_root / "tools" / "mwcc_debug" / "patch_mwcceppc_for_wibo.py"

    if not stock_compiler.exists():
        typer.echo(
            f"stock compiler not found: {stock_compiler}. "
            f"Run `python configure.py` first to download it.",
            err=True,
        )
        raise typer.Exit(4)
    if not patcher.exists():
        typer.echo(
            f"patcher script not found: {patcher}. "
            f"Pull latest tools/mwcc_debug/.",
            err=True,
        )
        raise typer.Exit(5)

    print(f"[..] patching {stock_compiler.name} -> {debug_compiler.name}...")
    try:
        subprocess.run(
            [
                "python3", str(patcher),
                str(stock_compiler), str(debug_compiler),
                "--dll", str(dll_src),
            ],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        typer.echo(f"patcher failed: {e}", err=True)
        raise typer.Exit(6)
    print(f"[ok] compiler patched: {debug_compiler}")
    print(f"[ok] DLL deployed:     {compiler_dir / 'MWDBG326.dll'}")
    print()
    print("Setup complete. Try:")
    print("  melee-agent debug dump local src/melee/mn/mnvibration.c")


@dump_app.command(name="doctor")
def setup_doctor(
    repair: Annotated[
        bool,
        typer.Option(
            "--repair",
            help="Run `debug dump setup` when required checks are missing, "
                 "then report the post-setup state.",
        ),
    ] = False,
) -> None:
    """Diagnose local mwcc_debug setup before dump/inspect workflows fail."""
    checks = _local_dump_setup_checks()
    failures = [check for check in checks if not check.ok]

    if failures and repair:
        print("REPAIR\tRunning: melee-agent debug dump setup")
        setup_local(rebuild_dll=False)
        checks = _local_dump_setup_checks()
        failures = [check for check in checks if not check.ok]

    _print_local_dump_setup_checks(checks)
    if failures:
        print("NEXT\tRun: melee-agent debug dump setup")
        print("NEXT\tOr retry doctor with: melee-agent debug dump doctor --repair")
        raise typer.Exit(2)

    print("OK\tready for `melee-agent debug dump local`")


def _ninja_cflags_for_unit(src_rel: str) -> tuple[str, str]:
    """Extract (cflags, mw_version) for a source from build.ninja.

    Mirrors melee-harness/tools/mwcc_dump.py's find_build_block.
    Raises typer.Exit if the source has no build block.
    """
    import re as _re
    build_ninja = DEFAULT_MELEE_ROOT / "build.ninja"
    try:
        text = build_ninja.read_text()
    except FileNotFoundError:
        typer.echo(
            f"build.ninja missing: {build_ninja}\n"
            f"Run `python configure.py` from the repo root, then retry "
            f"`debug dump local`.",
            err=True,
        )
        raise typer.Exit(2)
    text = text.replace("$\n", " ")  # unfold ninja line continuations
    obj = f"build/GALE01/{src_rel[:-2]}.o"
    blocks = _re.split(r"^build ", text, flags=_re.M)
    for b in blocks:
        if b.startswith(f"{obj}:") or b.startswith(f"{obj} :"):
            cflags = _re.search(r"\bcflags = (.*)", b).group(1).strip()
            mw = _re.search(r"\bmw_version = (\S+)", b).group(1).strip()
            return cflags, mw
    typer.echo(
        f"no build block for {obj} in build.ninja. "
        f"Run `python configure.py && ninja build/GALE01/report.json` "
        f"first to ensure the source is registered.",
        err=True,
    )
    raise typer.Exit(2)


def _cflags_with_same_tu_include_dir(cflags: str, unit_src_rel: str) -> str:
    """Make copied same-TU probes resolve quote-includes like the real source.

    The Melee build uses MWCC's `-cwd source`, so `"foo.h"` is resolved from
    the compiled file's directory. A probe copied under build/... needs the
    original source directory on the include path to keep local headers working.
    """
    unit_dir = Path(unit_src_rel).parent.as_posix()
    if not unit_dir or unit_dir == ".":
        return cflags
    return f"-i {shlex.quote(unit_dir)} {cflags}"


def _raise_pcdump_local_watchdog_exit(killed_by_watchdog: bool) -> None:
    if killed_by_watchdog:
        raise typer.Exit(124)


def _cache_settle_seconds(env: Optional[Mapping[str, str]] = None) -> float:
    values = env if env is not None else os.environ
    raw = values.get("MWCC_DEBUG_CACHE_SETTLE_SECONDS", "0.25")
    try:
        seconds = float(raw)
    except ValueError:
        return 0.25
    return max(0.0, seconds)


def _compiled_source_snapshot_still_current(
    src_path: Path,
    compiled_digest: Optional[str],
    *,
    settle_seconds: Optional[float] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[bool, Optional[str]]:
    if compiled_digest is None:
        return True, None
    seconds = _cache_settle_seconds() if settle_seconds is None else settle_seconds
    if seconds > 0:
        sleep_fn(seconds)
    try:
        current_digest = pcdump_cache.source_digest(src_path)
    except OSError:
        return False, None
    return current_digest == compiled_digest, current_digest


def _build_match_iter_first_auto_verify_cmd(
    *,
    src_path: Path,
    ig_csv: str,
    function: str,
    output_path: Optional[Path] = None,
) -> list[str]:
    if output_path is None:
        output_path = (
            src_path.parent
            / f".{function}.auto-verify.{os.getpid()}.{int(time.time() * 1000)}.pcdump.txt"
        )
    return [
        sys.executable, "-m", "src.cli", "debug",
        "dump", "local", str(src_path),
        "--force-iter-first", ig_csv,
        "--force-iter-first-fn", function,
        "-o", str(output_path),
    ]


def _resolve_auto_verify_restore_timeout(
    env: Optional[Mapping[str, str]] = None,
) -> tuple[float, str]:
    values = env if env is not None else os.environ
    restore_timeout = values.get("MWCC_DEBUG_RESTORE_TIMEOUT")
    if restore_timeout is not None:
        return float(restore_timeout), "MWCC_DEBUG_RESTORE_TIMEOUT"
    hang_timeout = values.get("MWCC_DEBUG_HANG_TIMEOUT")
    if hang_timeout is not None:
        return float(hang_timeout), "MWCC_DEBUG_HANG_TIMEOUT"
    return 180.0, "default"


def _resolve_auto_verify_restore_max_steps(
    env: Optional[Mapping[str, str]] = None,
) -> int:
    values = env if env is not None else os.environ
    return int(values.get("MWCC_DEBUG_RESTORE_MAX_STEPS", "64"))


def _auto_verify_restore_cleanup_hint(stderr: str) -> str:
    if "ninja: warning: premature end of file; recovering" not in stderr:
        return ""
    return (
        "ninja metadata looks truncated after an interrupted build; run "
        "`ninja -t recompact` from the repo root, then retry with "
        "`melee-agent debug dump restore-object-report <source.c>`. That command "
        "previews the ninja plan, refuses large rebuilds unless `--force` is "
        "passed, and owns the restore process group. If the warning persists, "
        "remove `.ninja_deps`/`.ninja_log`, then run `python configure.py` "
        "before retrying."
    )


def _restore_object_report_cmd_for_unit(unit: str) -> list[str]:
    return [
        "ninja",
        f"build/GALE01/src/{unit}.o",
        "build/GALE01/report.json",
    ]


def _ninja_dry_run_planned_steps(output: str) -> int:
    total_steps = 0
    fallback_steps = 0
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "ninja: no work to do.":
            continue
        match = re.match(r"^\[(\d+)/(\d+)\]", stripped)
        if match:
            total_steps = max(total_steps, int(match.group(2)))
        else:
            fallback_steps += 1
    return total_steps or fallback_steps


def _make_expensive_restore_result(
    cmd: list[str],
    *,
    planned_steps: int,
    max_steps: int,
    dry_run_output: str = "",
) -> subprocess.CompletedProcess[str]:
    preview_lines = [
        line.strip()
        for line in dry_run_output.splitlines()
        if line.strip()
    ][:8]
    preview = "\n".join(f"  {line}" for line in preview_lines)
    stderr = (
        f"[restore] refusing to launch restore: ninja dry-run would run "
        f"{planned_steps} ninja step(s), above "
        f"MWCC_DEBUG_RESTORE_MAX_STEPS={max_steps}.\n"
        f"This can expand into a large rebuild. Re-run with "
        f"`melee-agent debug dump restore-object-report <source.c> --force` "
        f"or raise MWCC_DEBUG_RESTORE_MAX_STEPS if you intentionally want "
        f"to launch it.\n"
        f"[restore] If worktree-doctor reports `build/GALE01/report.json "
        f"is older than build.ninja`, ninja must treat report generation as "
        f"stale and may fan out through many compile edges. There is no "
        f"metadata-only repair for that generated report/object state; run "
        f"`python configure.py` first if build metadata changed, then retry "
        f"the managed restore."
    )
    if preview:
        stderr += f"\n[restore] dry-run preview:\n{preview}"
    return subprocess.CompletedProcess(cmd, 125, "", stderr)


def _restore_object_report_for_unit(
    *,
    unit: str,
    melee_root: Path,
    timeout_s: float,
    max_steps: int,
    force: bool = False,
) -> tuple[subprocess.CompletedProcess[str], int]:
    restore_cmd = _restore_object_report_cmd_for_unit(unit)
    dry_run_cmd = ["ninja", "-n", *restore_cmd[1:]]
    try:
        dry_run = subprocess.run(
            dry_run_cmd,
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = (
            (exc.stderr or "") + "\n"
            f"[restore] ninja dry-run timed out after 30s; refusing to "
            f"launch restore without a plan."
        )
        return subprocess.CompletedProcess(dry_run_cmd, 124, exc.stdout or "", stderr), 0
    dry_output = "\n".join(
        text for text in (dry_run.stdout, dry_run.stderr) if text
    )
    planned_steps = _ninja_dry_run_planned_steps(dry_output)
    print(
        f"[auto-verify] restore dry-run: {planned_steps} ninja step(s)",
        file=sys.stderr,
    )
    if dry_run.returncode != 0:
        return dry_run, planned_steps
    if planned_steps == 0:
        return subprocess.CompletedProcess(
            restore_cmd,
            0,
            dry_run.stdout,
            dry_run.stderr,
        ), planned_steps
    if planned_steps > max_steps and not force:
        return _make_expensive_restore_result(
            restore_cmd,
            planned_steps=planned_steps,
            max_steps=max_steps,
            dry_run_output=dry_output,
        ), planned_steps
    if planned_steps > max_steps:
        print(
            f"[auto-verify] restore dry-run plans {planned_steps} steps; "
            f"running anyway because --force was requested",
            file=sys.stderr,
        )
    proc = _run_auto_verify_command_with_status(
        restore_cmd,
        cwd=melee_root,
        phase="restoring object/report",
        status_label=" ".join(restore_cmd),
        timeout_s=timeout_s,
    )
    return proc, planned_steps


def _pcdump_local_missing_diff_target_hint(
    function: str,
    *,
    src_rel: str,
    explicit: bool,
) -> str:
    if explicit:
        return (
            f"[diff] target function {function!r} is not in report.json. "
            f"Check the spelling, run `ninja build/GALE01/report.json` if "
            f"the report is stale, or pass `--function <function_name>` for "
            f"a report-backed function in {src_rel}."
        )
    return (
        f"[diff] inferred target function {function!r} from the first "
        f"function definition in {src_rel}, but it is not in report.json. "
        f"The first function may be a static inline helper. Re-run with "
        f"`--function <function_name>` for the non-inline function you want "
        f"to compare."
    )


def _auto_verify_failure_exit_code(auto_verify_result: Optional[dict]) -> Optional[int]:
    if not isinstance(auto_verify_result, dict) or not auto_verify_result.get("ran"):
        return None
    restore = auto_verify_result.get("restore")
    if not isinstance(restore, dict):
        return None
    returncode = restore.get("returncode")
    if returncode in (None, 0, "0"):
        return None
    try:
        numeric_returncode = int(returncode)
    except (TypeError, ValueError):
        return 1
    if numeric_returncode == 125:
        restore_text = "\n".join(
            str(restore.get(key, ""))
            for key in ("stdout", "stdout_tail", "stderr", "stderr_tail", "cleanup_hint")
        )
        if "refusing to launch restore" in restore_text:
            return None
    return numeric_returncode


def _annotate_auto_verify_actionability(auto_verify_result: dict) -> None:
    """Classify whether an auto-verified target is worth pursuing."""
    if not isinstance(auto_verify_result, dict) or not auto_verify_result.get("ran"):
        return
    delta = auto_verify_result.get("delta")
    if not isinstance(delta, (int, float)):
        auto_verify_result["actionability"] = "unknown"
        auto_verify_result["actionable"] = False
        auto_verify_result["actionability_note"] = (
            "auto-verify did not produce a numeric match% delta"
        )
        return
    if delta > 0.01:
        auto_verify_result["actionability"] = "improved"
        auto_verify_result["actionable"] = True
        auto_verify_result["actionability_note"] = (
            "forced target improved the function match%"
        )
    elif delta < -0.01:
        auto_verify_result["actionability"] = "regressed"
        auto_verify_result["actionable"] = False
        auto_verify_result["actionability_note"] = (
            "forced target made the function match% worse"
        )
    else:
        auto_verify_result["actionability"] = "no_improvement"
        auto_verify_result["actionable"] = False
        auto_verify_result["actionability_note"] = (
            "forced target matched but did not move the function match%"
        )


def _run_auto_verify_command_with_status(
    cmd: list[str],
    *,
    cwd: Path,
    status_label: str,
    phase: str = "testing",
    status_interval_s: float = 10.0,
    timeout_s: Optional[float] = None,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    if phase == "testing":
        print(f"[auto-verify] testing {status_label}", file=sys.stderr)
    else:
        print(f"[auto-verify] {phase}: {status_label}", file=sys.stderr)
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    started = time.time()
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=status_interval_s)
            return subprocess.CompletedProcess(
                cmd,
                proc.returncode,
                stdout,
                stderr,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.time() - started
            if timeout_s is not None and elapsed >= timeout_s:
                import signal as _signal
                timeout_msg = (
                    f"[auto-verify] {phase} timed out after "
                    f"{timeout_s:g}s ({status_label})"
                )
                print(timeout_msg, file=sys.stderr)
                try:
                    os.killpg(os.getpgid(proc.pid), _signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    stdout, stderr = proc.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    stdout, stderr = "", ""
                stderr = (stderr or "")
                if stderr and not stderr.endswith("\n"):
                    stderr += "\n"
                stderr += timeout_msg
                return subprocess.CompletedProcess(cmd, 124, stdout, stderr)
            print(
                f"[auto-verify] still running after {elapsed:.0f}s "
                f"({phase}: {status_label})",
                file=sys.stderr,
            )


@dump_app.command(name="restore-object-report")
def restore_object_report(
    c_file: Annotated[
        str,
        typer.Argument(
            help="Path to the .c file whose object/report state should be restored.",
        ),
    ],
    timeout: Annotated[
        Optional[float],
        typer.Option(
            "--timeout",
            help="Restore timeout in seconds. Defaults to "
                 "MWCC_DEBUG_RESTORE_TIMEOUT, then MWCC_DEBUG_HANG_TIMEOUT, "
                 "then 180.",
        ),
    ] = None,
    max_steps: Annotated[
        Optional[int],
        typer.Option(
            "--max-steps",
            help="Maximum ninja dry-run steps allowed before refusing to "
                 "launch restore. Defaults to MWCC_DEBUG_RESTORE_MAX_STEPS "
                 "(64).",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Run even when the dry-run plan exceeds --max-steps.",
        ),
    ] = False,
) -> None:
    """Safely restore one source's object and build report.

    This is the managed cleanup path used by match-iter-first --auto-verify.
    It previews the ninja plan first, refuses unexpectedly large rebuilds by
    default, and runs the restore in an owned process group with a timeout.
    """
    melee_root = DEFAULT_MELEE_ROOT
    src_rel = _resolve_src_relative(c_file)
    unit = src_rel[:-2].removeprefix("src/")
    if timeout is None:
        timeout_s, timeout_source = _resolve_auto_verify_restore_timeout()
    else:
        timeout_s, timeout_source = timeout, "--timeout"
    max_step_count = (
        max_steps
        if max_steps is not None
        else _resolve_auto_verify_restore_max_steps()
    )
    print(
        f"[restore] timeout: {timeout_s:g}s ({timeout_source})",
        file=sys.stderr,
    )
    print(
        f"[restore] max dry-run steps: {max_step_count}",
        file=sys.stderr,
    )
    proc, planned_steps = _restore_object_report_for_unit(
        unit=unit,
        melee_root=melee_root,
        timeout_s=timeout_s,
        max_steps=max_step_count,
        force=force,
    )
    print(
        f"[restore] planned ninja steps: {planned_steps}",
        file=sys.stderr,
    )
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        typer.echo(proc.stderr, err=True)
    if proc.returncode != 0:
        raise typer.Exit(proc.returncode)

@dump_app.command(name="local")
def pcdump_local(
    c_file: Annotated[
        str,
        typer.Argument(help="Path to a .c file in the melee repo"),
    ],
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Output path for the dump. Default: cache it under "
                 "build/mwcc_debug_cache/<unit>.txt. Use '-' for stdout.",
        ),
    ] = None,
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help="Tier 5: allocator bias by ig_idx. Format "
                 "'virtIdx:physReg[,...]' or 'class:virtIdx:physReg[,...]'. "
                 "Class-scoped entries are passed through to the DLL and only "
                 "apply to that register class. By default "
                 "applies globally — scope with --force-phys-fn. "
                 "DIAGNOSTIC-ONLY: uses the patched debug compiler and does "
                 "not affect production ninja builds.",
        ),
    ] = None,
    force_phys_iter: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys-iter",
            help="Tier 5: allocator bias by colorgraph iteration "
                 "position (class:iter:phys[,...]). Use when "
                 "--force-phys can't target a node by ig_idx (rare, "
                 "but happens for split/spill nodes created post-IG-"
                 "build). E.g. '0:0:31' = class 0 (GPR), iter 0, "
                 "force to r31. DIAGNOSTIC-ONLY: uses the patched debug "
                 "compiler and does not affect production ninja builds.",
        ),
    ] = None,
    force_phys_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys-fn",
            help="Scope --force-phys and --force-phys-iter to a "
                 "single function name (mirrors --force-coalesce-fn).",
        ),
    ] = None,
    force_iter_first: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first",
            help="Tier 6: reorder simplification list. By default this "
                 "applies to every function in the TU; scope with "
                 "--force-iter-first-fn on multi-function TUs. "
                 "DIAGNOSTIC-ONLY: uses the patched debug compiler and does "
                 "not affect production ninja builds.",
        ),
    ] = None,
    force_iter_first_class: Annotated[
        Optional[int],
        typer.Option(
            "--force-iter-first-class",
            help=(
                "Scope --force-iter-first IG indices to one register class "
                "(0=GPR, 1=FPR), preventing an FPR-only probe from reordering "
                "same-numbered GPR nodes or vice versa."
            ),
        ),
    ] = None,
    force_iter_first_iter: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first-iter",
            help=(
                "Tier 6: reorder simplification list by class and current "
                "iteration position. Format 'class:iter[,class:iter]*'. "
                "Useful for split/spill nodes that lack a stable ig_idx."
            ),
        ),
    ] = None,
    force_iter_first_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first-fn",
            help="Scope --force-iter-first to a single function name. "
                 "Other functions in the same TU compile with their "
                 "natural simplification order. E.g. "
                 "'--force-iter-first-fn mnVibration_80247510 "
                 "--force-iter-first 151,48'.",
        ),
    ] = None,
    force_select_order: Annotated[
        Optional[str],
        typer.Option(
            "--force-select-order",
            help="Tier 6: explicit alias for --force-iter-first when testing "
                 "allocator selection order. Format 'virtIdx[,virtIdx]*'; "
                 "the first listed node gets first selection priority. "
                 "DIAGNOSTIC-ONLY: uses the patched debug compiler and does "
                 "not affect production ninja builds.",
        ),
    ] = None,
    force_select_order_class: Annotated[
        Optional[int],
        typer.Option(
            "--force-select-order-class",
            help=(
                "Scope --force-select-order IG indices to one register class "
                "(0=GPR, 1=FPR), matching --force-iter-first-class."
            ),
        ),
    ] = None,
    force_select_order_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-select-order-fn",
            help="Scope --force-select-order to a single function name. "
                 "Other functions in the same TU compile with their "
                 "natural selection order.",
        ),
    ] = None,
    force_coalesce: Annotated[
        Optional[str],
        typer.Option(
            "--force-coalesce",
            help="Tier 6: override the conservative coalescer's union-find "
                 "decisions. Format 'virt=root[,virt=root]*'. E.g. '42=38' "
                 "forces virtual 42 to coalesce into virtual 38; '42=42' "
                 "un-coalesces 42 back to its own root. By default applies "
                 "to EVERY coalesce invocation in the TU (out-of-bounds "
                 "pairs are silently skipped). For multi-function TUs "
                 "where one function's overrides would corrupt others, "
                 "scope with --force-coalesce-fn. EXPERIMENTAL — forcing "
                 "two interfering virtuals to coalesce produces "
                 "incorrect code. DIAGNOSTIC-ONLY: uses the patched debug "
                 "compiler and does not affect production ninja builds.",
        ),
    ] = None,
    force_coalesce_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-coalesce-fn",
            help="Scope --force-coalesce to a single function name. "
                 "When set, overrides only apply when the currently-"
                 "compiling function (captured by mwcc_debug's debuglisting "
                 "hook) matches the given name exactly. Other functions in "
                 "the same TU compile naturally — prevents one function's "
                 "experimental overrides from corrupting earlier or later "
                 "functions. E.g. '--force-coalesce-fn mnVibration_802474C4 "
                 "--force-coalesce 32=87'.",
        ),
    ] = None,
    force_schedule: Annotated[
        Optional[str],
        typer.Option(
            "--force-schedule",
            help="Tier 7: pin adjacent same-base loads after instruction "
                 "scheduling. Format 'op:beforeOffset>afterOffset[,...]'. "
                 "E.g. 'lwz:0x74>0x70' forces an adjacent same-base lwz pair "
                 "at offsets 0x70/0x74 to emit 0x74 first. By default "
                 "applies globally — scope with --force-schedule-fn. "
                 "DIAGNOSTIC-ONLY: uses the patched debug compiler and does "
                 "not affect production ninja builds.",
        ),
    ] = None,
    force_schedule_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-schedule-fn",
            help="Scope --force-schedule to a single function name. Other "
                 "functions in the same TU compile with their natural "
                 "schedule.",
        ),
    ] = None,
    wibo: Annotated[
        Optional[Path],
        typer.Option(
            "--wibo",
            help="Path to wibo binary. Default: auto-resolve from "
                 "$MWCC_DEBUG_WIBO or ../melee-harness/bin/wibo.",
        ),
    ] = None,
    keep_obj: Annotated[
        Optional[Path],
        typer.Option(
            "--keep-obj",
            help="Preserve the compiled .o at this path instead of "
                 "discarding it. The default behavior is to discard, "
                 "but for force-coalesce / force-phys hypothesis "
                 "testing the .o is exactly what you need to feed into "
                 "objdiff/checkdiff. Path can be absolute or relative "
                 "to the melee root.",
        ),
    ] = None,
    diff: Annotated[
        bool,
        typer.Option(
            "--diff",
            help="After compile, run objdiff against the production "
                 "target.o for the function (or whole TU). Saves a "
                 "round-trip when you want to know 'does this "
                 "force-coalesce reach the target?' in one shot. "
                 "Implies --keep-obj (uses a temp path if --keep-obj "
                 "not given).",
        ),
    ] = False,
    force_frame_from_diff: Annotated[
        bool,
        typer.Option(
            "--force-frame-from-diff",
            "--force-no-home-from-diff",
            help=(
                "DIAGNOSTIC-ONLY: with --diff, run a preflight checkdiff JSON "
                "pass, derive stack-frame immediates and anonymous literal "
                "renames from the paired current/target asm, patch the "
                "temporary .o, then run the final checkdiff. Useful for "
                "proving held-FP/no-home frame hypotheses without changing C "
                "source."
            ),
        ),
    ] = False,
    function: Annotated[
        Optional[str],
        typer.Option(
            "--function", "-f",
            help="Function name to use as the --diff target. When "
                 "omitted, defaults to the value of --force-iter-first-fn / "
                 "--force-select-order-fn / --force-phys-fn / "
                 "--force-coalesce-fn (in that order) if any is set; "
                 "otherwise falls back to the first "
                 "function found in the source file. Use this option "
                 "when working on a non-first function in a multi-function "
                 "TU so --diff compares the right function.",
        ),
    ] = None,
    unit_source: Annotated[
        Optional[str],
        typer.Option(
            "--unit-source",
            help=(
                "Use this real same-TU source file's build.ninja flags and "
                "object/cache identity while compiling C_FILE. This lets "
                "`build/mwcc_debug_cache/probes/.../*.c` probe files compile "
                "with the original TU settings without registering their own "
                "ninja edge. Probe runs leave the baseline cache unchanged."
            ),
        ),
    ] = None,
    no_cache_sync: Annotated[
        bool,
        typer.Option(
            "--no-cache-sync",
            help="Do not update the canonical pcdump cache. Use for "
                 "temporary source experiments that should not become the "
                 "baseline for follow-up diagnostics.",
        ),
    ] = False,
    checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--checkdiff-timeout",
            help="Timeout in seconds for the integrated --diff checkdiff run.",
        ),
    ] = 60.0,
) -> None:
    """Local mwcc_debug pcdump (macOS+wibo+Zig-built DLL, no SSH).

    Compiles the given .c file locally via wibo + the patched
    mwcceppc_debug.exe. Produces the same pcdump.txt our SSH-based
    `debug dump remote` produces, in ~1 second vs ~30 seconds.

    Requires one-time setup: run `melee-agent debug dump setup`
    first to patch the compiler and deploy the DLL.

    Env-var hooks (--force-phys, --force-iter-first, --force-coalesce,
    --force-schedule, and their function-scope variants) pass through to
    the DLL.

    Use --keep-obj PATH to preserve the compiled .o for downstream
    inspection (objdiff/checkdiff/etc.). Use --diff to run an integrated
    objdiff against the target — answers "does this match?" in one go.
    """
    melee_root = DEFAULT_MELEE_ROOT
    src_rel = _resolve_src_relative(c_file)
    unit_src_rel = (
        _resolve_src_relative(unit_source)
        if unit_source is not None
        else src_rel
    )
    same_tu_probe = unit_src_rel != src_rel

    if force_frame_from_diff and not diff:
        typer.echo(
            "--force-frame-from-diff requires --diff so it can derive patches "
            "from paired checkdiff asm.",
            err=True,
        )
        raise typer.Exit(2)

    # Resolve wibo
    wibo_path = wibo or _find_wibo()
    if wibo_path is None or not wibo_path.exists():
        typer.echo(
            "wibo binary not found. Run `melee-agent debug dump doctor` "
            "to diagnose, then `melee-agent debug dump setup`, or set "
            "$MWCC_DEBUG_WIBO.",
            err=True,
        )
        raise typer.Exit(2)

    compiler_dir = _find_compiler_dir()
    debug_compiler = compiler_dir / "mwcceppc_debug.exe"
    if not debug_compiler.exists():
        typer.echo(
            f"patched compiler not found: {debug_compiler}. "
            f"Run `melee-agent debug dump doctor` to diagnose, then "
            f"`melee-agent debug dump setup`.",
            err=True,
        )
        raise typer.Exit(2)

    # Extract cflags from build.ninja. Probe files can borrow settings from
    # their real same-TU source via --unit-source.
    cflags, _mw_version = _ninja_cflags_for_unit(unit_src_rel)
    if same_tu_probe:
        cflags = _cflags_with_same_tu_include_dir(cflags, unit_src_rel)

    # Construct compile command. The patched DLL reads
    # MWCC_DEBUG_PCDUMP_PATH for its output filename (relative paths land
    # in cwd = melee_root). Use a unique per-PID + per-time name so
    # parallel debug dump local runs don't race on a shared pcdump.txt.
    import time
    pcdump_name = f"pcdump_{os.getpid()}_{int(time.time() * 1000)}.txt"
    pcdump_path = melee_root / pcdump_name
    if pcdump_path.exists():
        pcdump_path.unlink()

    # Resolve where the .o lands. Default: discard via /tmp. When the
    # agent wants to inspect/diff the output, --keep-obj routes it to a
    # specific path. --diff implies keeping (a temp path if no --keep-obj
    # was given) so we have something to diff against.
    if keep_obj is not None:
        obj_target = keep_obj if keep_obj.is_absolute() else (melee_root / keep_obj)
        obj_target.parent.mkdir(parents=True, exist_ok=True)
        obj_out = str(obj_target)
        discard_obj_after = False
    elif diff:
        obj_target = Path(
            f"/tmp/pcdump_local_keep_{os.getpid()}_{int(time.time() * 1000)}.o"
        )
        obj_out = str(obj_target)
        discard_obj_after = True  # remove after diff if not user-requested
    else:
        obj_target = Path(
            f"/tmp/pcdump_local_discard_{os.getpid()}_{int(time.time() * 1000)}.o"
        )
        obj_out = str(obj_target)
        discard_obj_after = True

    # Args: cflags split + source + output.
    args = (
        [str(wibo_path), str(debug_compiler)]
        + shlex.split(cflags)
        + ["-c", src_rel, "-o", obj_out]
    )
    src_path_for_cache = melee_root / src_rel
    try:
        compiled_source_digest = pcdump_cache.source_digest(src_path_for_cache)
    except OSError:
        compiled_source_digest = None

    # Set env vars for our DLL's hooks
    env = os.environ.copy()
    env["MWCC_DEBUG_PCDUMP_PATH"] = pcdump_name
    if force_phys:
        # Normalize: strip optional class prefix (gpr:N:M → N:M), emit
        # ambiguity warning when bare form is used.
        force_phys_dll, fp_warnings = _normalize_force_phys(force_phys)
        for w in fp_warnings:
            print(w, file=sys.stderr)
        env["MWCC_DEBUG_FORCE_PHYS"] = force_phys_dll
    if force_phys_iter:
        env["MWCC_DEBUG_FORCE_PHYS_ITER"] = force_phys_iter
    if force_phys_fn:
        env["MWCC_DEBUG_FORCE_PHYS_FUNCTION"] = force_phys_fn
    if force_iter_first and force_select_order:
        raise typer.BadParameter(
            "--force-select-order and --force-iter-first target the same "
            "selection-order hook; use one spelling per run"
        )
    iter_first_value = force_iter_first or force_select_order
    iter_first_class = (
        force_iter_first_class
        if force_iter_first is not None
        else force_select_order_class
    )
    iter_first_fn = force_iter_first_fn or force_select_order_fn

    if iter_first_value:
        env["MWCC_DEBUG_FORCE_ITER_FIRST"] = iter_first_value
    if iter_first_class is not None:
        if not iter_first_value:
            raise typer.BadParameter(
                "--force-iter-first-class/--force-select-order-class requires "
                "--force-iter-first or --force-select-order"
            )
        env["MWCC_DEBUG_FORCE_ITER_FIRST_CLASS"] = str(iter_first_class)
    if force_iter_first_iter:
        if any(c in force_iter_first_iter for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-iter-first-iter must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        env["MWCC_DEBUG_FORCE_ITER_FIRST_ITER"] = force_iter_first_iter
    if iter_first_fn:
        env["MWCC_DEBUG_FORCE_ITER_FIRST_FUNCTION"] = iter_first_fn
    if force_coalesce:
        env["MWCC_DEBUG_FORCE_COALESCE"] = force_coalesce
    if force_coalesce_fn:
        env["MWCC_DEBUG_FORCE_COALESCE_FUNCTION"] = force_coalesce_fn
    if force_schedule:
        env["MWCC_DEBUG_FORCE_SCHEDULE"] = _validate_force_schedule(force_schedule)
    if force_schedule_fn:
        env["MWCC_DEBUG_FORCE_SCHEDULE_FUNCTION"] = force_schedule_fn

    # Safety guard: --force-coalesce without --force-coalesce-fn on a
    # multi-function TU is a known wibo-hanger. Virtual indices are
    # per-function; if the spec happens to be in-bounds for an unintended
    # function, the resulting compile can drive that function's state
    # into pathology and lock the wibo process in UE state (immune to
    # SIGKILL). Detect heuristically by counting function definitions
    # in the .c file and refuse the run with a clear error.
    # Distinguish "not provided" (None) from "explicit empty opt-out" (""):
    # the guard only fires on None.
    if force_coalesce and force_coalesce_fn is None:
        src_path = melee_root / src_rel
        if src_path.exists():
            n_fns = _count_function_defs(src_path.read_text())
            if n_fns >= 2:
                typer.echo(
                    f"refusing --force-coalesce without --force-coalesce-fn "
                    f"on a multi-function TU ({src_rel} has ~{n_fns} "
                    f"function definitions).\n"
                    f"Virtual indices are per-function; an override aimed at "
                    f"one function can corrupt others and may hang the wibo "
                    f"compile process in UE state.\n"
                    f"Re-run with `--force-coalesce-fn <function_name>` to "
                    f"scope the override. Pass `--force-coalesce-fn ''` to "
                    f"explicitly opt out of this check (NOT RECOMMENDED).",
                    err=True,
                )
                raise typer.Exit(2)
    # Same guard for --force-phys: same per-function issue, same wibo
    # risk if a per-function-class override happens to fit elsewhere.
    if (force_phys or force_phys_iter) and force_phys_fn is None:
        src_path = melee_root / src_rel
        if src_path.exists():
            n_fns = _count_function_defs(src_path.read_text())
            if n_fns >= 2:
                typer.echo(
                    f"refusing --force-phys/--force-phys-iter without "
                    f"--force-phys-fn on a multi-function TU "
                    f"({src_rel} has ~{n_fns} function definitions).\n"
                    f"Same per-function-virtual hazard as --force-coalesce. "
                    f"Re-run with `--force-phys-fn <function_name>` to scope. "
                    f"Pass `--force-phys-fn ''` to opt out (NOT RECOMMENDED).",
                    err=True,
                )
                raise typer.Exit(2)

    if force_coalesce:
        if force_coalesce_fn == "":
            coalesce_preflight_function = None
        else:
            coalesce_preflight_function = force_coalesce_fn or function
        if coalesce_preflight_function:
            _reject_unsafe_force_coalesce(
                force_coalesce=force_coalesce,
                function=coalesce_preflight_function,
                melee_root=melee_root,
            )

    # Use Popen + a no-progress watchdog so a hung wibo (UE state from a
    # force-coalesce edge case, etc.) doesn't burn the full default
    # timeout. The watchdog kills the subprocess group after N seconds
    # without any progress on stdout/stderr or the pcdump output file.
    # We can't actually kill a wibo that's pinned in UE state (immune
    # to SIGKILL — only a host reboot reaps it), but we can stop OUR
    # process from waiting and stop accumulating new compile attempts
    # behind it.
    WATCHDOG_TIMEOUT_S = float(os.environ.get(
        "MWCC_DEBUG_HANG_TIMEOUT", "45"))
    try:
        proc_handle = subprocess.Popen(
            args,
            cwd=melee_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,  # own pgrp for clean kill
        )
    except FileNotFoundError as e:
        typer.echo(f"failed to invoke wibo: {e}", err=True)
        raise typer.Exit(3)

    import select
    out_buf: list[str] = []
    err_buf: list[str] = []
    last_progress = time.time()
    pcdump_progress_marker: tuple[int, int] | None = None
    killed_by_watchdog = False
    while True:
        if proc_handle.poll() is not None:
            # Drain remaining output
            remaining_out, remaining_err = proc_handle.communicate()
            if remaining_out:
                out_buf.append(remaining_out)
            if remaining_err:
                err_buf.append(remaining_err)
            break
        # Wait for output (up to 1s at a time so we can check watchdog).
        ready, _, _ = select.select(
            [proc_handle.stdout, proc_handle.stderr], [], [], 1.0,
        )
        for stream in ready:
            chunk = stream.readline()
            if chunk:
                if stream is proc_handle.stdout:
                    out_buf.append(chunk)
                else:
                    err_buf.append(chunk)
                last_progress = time.time()
        try:
            pcdump_stat = pcdump_path.stat()
        except OSError:
            pcdump_marker = None
        else:
            pcdump_marker = (pcdump_stat.st_size, pcdump_stat.st_mtime_ns)
        if pcdump_marker is not None and pcdump_marker != pcdump_progress_marker:
            pcdump_progress_marker = pcdump_marker
            last_progress = time.time()
        if time.time() - last_progress > WATCHDOG_TIMEOUT_S:
            killed_by_watchdog = True
            _kill_debug_dump_local_process_tree(proc_handle)
            # Drain whatever the OS still hands back (proc may be UE)
            try:
                remaining_out, remaining_err = proc_handle.communicate(timeout=2)
                if remaining_out:
                    out_buf.append(remaining_out)
                if remaining_err:
                    err_buf.append(remaining_err)
            except subprocess.TimeoutExpired:
                # wibo is in UE state — can't reap. Move on.
                pass
            break

    # Shim into the old proc.stderr/stdout/returncode contract so the
    # rest of the function works unchanged.
    class _ProcShim:
        def __init__(self, rc, out, err):
            self.returncode = rc
            self.stdout = out
            self.stderr = err
    proc = _ProcShim(
        rc=(
            124
            if killed_by_watchdog
            else (proc_handle.returncode if proc_handle.returncode is not None else 124)
        ),
        out="".join(out_buf),
        err="".join(err_buf),
    )

    if killed_by_watchdog:
        hang_msg = (
            f"[debug dump local] no compile progress for "
            f"{WATCHDOG_TIMEOUT_S:.0f}s — likely wibo hang (UE state). "
            f"Subprocess killed; check `ps aux | grep wibo` for zombie. "
            f"Override via MWCC_DEBUG_HANG_TIMEOUT=<seconds>."
        )
        if force_coalesce:
            hang_msg += (
                f"\n[debug dump local] --force-coalesce '{force_coalesce}' was "
                f"active. Possible causes for the hang:\n"
                f"  - Invalid pair: one or both virtuals are not in this "
                f"function's IGNode set (wrong function scoped by "
                f"--force-coalesce-fn, or index out of range).\n"
                f"  - Interfering pair: the two virtuals have a live-range "
                f"conflict — run `debug inspect analyze -f <fn>` and look for "
                f"'interferers:' near the relevant ig_idx to check "
                f"interference edges.\n"
                f"  - DLL crash in the coalesce hook (rare): check stderr "
                f"above for exception traces.\n"
                f"  Next: try a different pair, or run `debug inspect analyze -f <fn>` "
                f"and search the output for 'interferers:' near each ig_idx "
                f"to find a non-interfering candidate."
            )
        typer.echo(hang_msg, err=True)

    if proc.returncode != 0:
        # Compile failed — surface stderr but keep going if pcdump.txt
        # got produced (mwcc sometimes errors after emitting partial dump).
        #
        # Filter out MWCC's "User break, cancelled..." noise: that message
        # fires from MWCC's interrupt handler during late-cleanup paths
        # (post-listing, post-flush). It does NOT indicate the dump is
        # bad — pcdump.txt is already written by the time this fires.
        # Echoing it makes successful runs look like errors. We only echo
        # stderr if there are non-noise lines left AND the dump is missing.
        filtered = "\n".join(
            line for line in proc.stderr.splitlines()
            if "User break" not in line
            and "cancelled..." not in line
        ).strip()
        if filtered:
            typer.echo(filtered, err=True)
        if not pcdump_path.exists():
            raise typer.Exit(proc.returncode)

    if not pcdump_path.exists():
        typer.echo("compile completed but no pcdump.txt was emitted", err=True)
        raise typer.Exit(4)

    function_missing_exit_code: int | None = None
    if function:
        available_names = [fn.name for fn in parse_pcdump(pcdump_path.read_text())]
        if function not in available_names:
            _emit_function_not_in_dump(
                function,
                available_names,
                hint=(
                    "Hint: `debug dump local --function` only validates "
                    "functions emitted by the compiled source. Check that the "
                    "function is defined in this TU, or regenerate the source "
                    "context before running downstream inspect commands."
                ),
            )
            function_missing_exit_code = 3

    # Warn early if --keep-obj was requested but the compiler didn't emit
    # an object (e.g. a forced coalesce hung the wibo process mid-compile).
    if keep_obj is not None and not obj_target.exists():
        typer.echo(
            f"[debug dump local] --keep-obj requested but no object was produced "
            f"(compile likely failed mid-way). Check pcdump for clues.",
            err=True,
        )

    # Run objdiff if --diff was requested. The integrated check
    # answers "did this compile reach the target?" without the agent
    # having to manually re-run objdiff-cli. We invoke checkdiff in
    # --no-build mode so it uses the .o we just produced.
    diff_failure_exit_code: int | None = None
    if diff and function_missing_exit_code is None:
        if not obj_target.exists():
            typer.echo(
                f"--diff requested but .o not produced at {obj_target}; "
                f"compile likely failed (see error above).",
                err=True,
            )
            diff_failure_exit_code = 4
        else:
            # checkdiff finds the function by name across all .o files
            # the build emits; the simplest contract is to copy our .o
            # into the build path that checkdiff expects, then call it.
            unit_for_o = unit_src_rel[:-2].removeprefix("src/")  # melee/mn/foo
            build_o = melee_root / "build" / "GALE01" / "src" / f"{unit_for_o}.o"
            with _acquire_checkdiff_repo_lock(melee_root):
                build_o_existed = build_o.exists()
                saved_o: Optional[bytes] = None
                if build_o_existed:
                    saved_o = build_o.read_bytes()
                try:
                    build_o.parent.mkdir(parents=True, exist_ok=True)
                    build_o.write_bytes(obj_target.read_bytes())
                    print(f"[diff] running checkdiff against {build_o}...",
                          file=sys.stderr)
                    # Resolve the function name for --diff.
                    # Priority: explicit --function > --force-phys-fn >
                    # --force-coalesce-fn > --force-schedule-fn >
                    # first function found in source.
                    src_path = melee_root / src_rel
                    explicit_diff_target = any([
                        function,
                        force_iter_first_fn,
                        force_select_order_fn,
                        force_phys_fn,
                        force_coalesce_fn,
                        force_schedule_fn,
                    ])
                    fn_to_diff = (
                        function
                        or force_iter_first_fn
                        or force_select_order_fn
                        or force_phys_fn
                        or force_coalesce_fn
                        or force_schedule_fn
                        or None
                    )
                    if fn_to_diff is None and src_path.exists():
                        src_text = src_path.read_text()
                        # First function definition; coarse heuristic
                        m = re.search(
                            r'^[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\([^)]*\)\s*'
                            r'(?:[A-Za-z_]\w*\s*)*\{',
                            src_text, re.MULTILINE,
                        )
                        if m:
                            fn_to_diff = m.group(1)
                    if fn_to_diff is None:
                        print(
                            "[diff] could not find a function name to diff; "
                            "use checkdiff manually.", file=sys.stderr,
                        )
                    elif _find_unit_for_function(fn_to_diff, melee_root) is None:
                        print(
                            _pcdump_local_missing_diff_target_hint(
                                fn_to_diff,
                                src_rel=unit_src_rel,
                                explicit=explicit_diff_target,
                            ),
                            file=sys.stderr,
                        )
                    else:
                        print(
                            f"[diff] target function: {fn_to_diff}",
                            file=sys.stderr,
                        )
                        checkdiff_env = _checkdiff_env_for_locked_child(
                            disable_fingerprint=bool(
                                force_iter_first_fn
                                or force_select_order_fn
                                or force_phys_fn
                                or force_coalesce_fn
                                or force_schedule_fn
                                or force_frame_from_diff
                            )
                        )
                        if force_frame_from_diff:
                            try:
                                force_json_proc = subprocess.run(
                                    ["python", "tools/checkdiff.py", fn_to_diff,
                                     "--format", "json", "--no-build"],
                                    cwd=melee_root,
                                    timeout=checkdiff_timeout,
                                    env=checkdiff_env,
                                    capture_output=True,
                                    text=True,
                                )
                                if not force_json_proc.stdout.strip():
                                    if force_json_proc.stderr:
                                        print(force_json_proc.stderr, file=sys.stderr)
                                    print(
                                        "[force-frame] checkdiff JSON preflight "
                                        "produced no JSON; final diff will run "
                                        "without object patching.",
                                        file=sys.stderr,
                                    )
                                else:
                                    from ..mwcc_debug.force_frame import (
                                        ForceFramePatchError,
                                        apply_force_frame_patch_plan,
                                        derive_force_frame_patch_plan,
                                    )

                                    payload = json.loads(force_json_proc.stdout)
                                    plan = derive_force_frame_patch_plan(payload)
                                    if plan.is_empty:
                                        print(
                                            "[force-frame] no eligible "
                                            "stack-frame immediates or "
                                            "anonymous literal renames found; "
                                            "final diff will run unchanged.",
                                            file=sys.stderr,
                                        )
                                    else:
                                        result = apply_force_frame_patch_plan(
                                            build_o,
                                            fn_to_diff,
                                            plan,
                                        )
                                        obj_target.write_bytes(build_o.read_bytes())
                                        print(
                                            "[force-frame] applied "
                                            f"{result.byte_patches_applied} "
                                            "stack-frame immediate patch(es) "
                                            f"and {len(result.symbol_renames)} "
                                            "literal rename(s) before final "
                                            "checkdiff.",
                                            file=sys.stderr,
                                        )
                            except subprocess.TimeoutExpired:
                                print(
                                    f"[force-frame] checkdiff JSON preflight "
                                    f"timed out after {checkdiff_timeout:g}s; "
                                    "final diff will run without object "
                                    "patching.",
                                    file=sys.stderr,
                                )
                            except (
                                ForceFramePatchError,
                                json.JSONDecodeError,
                                OSError,
                                subprocess.CalledProcessError,
                            ) as exc:
                                print(
                                    f"[force-frame] could not apply "
                                    f"diff-derived object patch: {exc}; final "
                                    "diff will run unchanged.",
                                    file=sys.stderr,
                                )
                        try:
                            diff_proc = subprocess.run(
                                ["python", "tools/checkdiff.py", fn_to_diff,
                                 "--format", "plain", "--no-build"],
                                cwd=melee_root,
                                timeout=checkdiff_timeout,
                                env=checkdiff_env,
                            )
                            if diff_proc.returncode == 0:
                                print("[diff] MATCH — function bytes are identical.")
                        except subprocess.TimeoutExpired:
                            print(
                                f"[diff] checkdiff timed out after "
                                f"{checkdiff_timeout:g}s; rerun manually or raise "
                                f"--checkdiff-timeout.",
                                file=sys.stderr,
                            )
                finally:
                    if build_o_existed and saved_o is not None:
                        build_o.write_bytes(saved_o)
                    elif not build_o_existed and build_o.exists():
                        try:
                            build_o.unlink()
                        except OSError:
                            pass

    # Clean up the .o if it was temp-allocated (and not requested by user)
    if discard_obj_after:
        try:
            os.unlink(obj_out)
        except OSError:
            pass

    # Determine whether ANY force-* override was active this run.
    # Forced pcdumps contain experimental allocator decisions that should
    # NOT overwrite the shared baseline cache — downstream commands that
    # auto-resolve via the cache would silently read forced data as if it
    # were the natural allocation, producing misleading diagnostics.
    any_forced = any([
        force_phys, force_phys_iter, force_phys_fn,
        force_iter_first, force_iter_first_fn,
        force_select_order, force_select_order_fn,
        force_coalesce, force_coalesce_fn,
        force_schedule, force_schedule_fn,
        force_frame_from_diff,
    ])
    if any_forced:
        print(
            "[debug dump local] force-* overrides are DIAGNOSTIC-ONLY: "
            "they use mwcceppc_debug.exe and do not affect production "
            "ninja builds. Treat matches as hypotheses, not shippable "
            "source results.",
            file=sys.stderr,
        )

    def _finish_pcdump_local_run() -> None:
        _raise_pcdump_local_watchdog_exit(killed_by_watchdog)
        if function_missing_exit_code is not None:
            raise typer.Exit(function_missing_exit_code)
        if diff_failure_exit_code is not None:
            raise typer.Exit(diff_failure_exit_code)

    # Place output
    if str(output) == "-":
        print(pcdump_path.read_text())
        pcdump_path.unlink()
        _finish_pcdump_local_run()
        return

    skip_cache_sync = any_forced or no_cache_sync or same_tu_probe

    # Resolve the canonical cache location for this TU so we can ALWAYS
    # update it — even when --output specifies a different path.
    # Without this, downstream commands (analyze, var-to-virtual, guide)
    # auto-resolve via the cache and silently read stale data.
    # EXCEPTION: forced runs skip the cache entirely (see any_forced above).
    unit = unit_src_rel[:-2].removeprefix("src/")  # melee/mn/mnvibration
    pcdump_cache.ensure_cache_dir(melee_root)
    cache_target = pcdump_cache.cache_path(melee_root, unit)
    cache_skip_reason: Optional[str] = None
    if same_tu_probe:
        cache_skip_reason = (
            f"same-TU probe {src_rel} compiled with build settings from "
            f"{unit_src_rel}"
        )
    elif function_missing_exit_code is not None:
        skip_cache_sync = True
        cache_skip_reason = (
            f"requested function {function!r} was not emitted in pcdump"
        )
    elif not skip_cache_sync:
        source_current, _current_digest = _compiled_source_snapshot_still_current(
            src_path_for_cache,
            compiled_source_digest,
        )
        if not source_current:
            skip_cache_sync = True
            cache_skip_reason = (
                "source changed or restored after the compiled snapshot"
            )

    if output is None:
        if skip_cache_sync:
            # Forced/no-cache run — write to a temp path and skip cache sync.
            prefix = (
                "unstable-source" if cache_skip_reason
                else "forced" if any_forced
                else "nocache"
            )
            output = Path(
                f"/tmp/pcdump_{prefix}_{os.getpid()}_{int(time.time() * 1000)}.txt"
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            pcdump_path.rename(output)
            os.utime(output, None)
            if cache_skip_reason:
                print(
                    f"[debug dump local] {cache_skip_reason}; leaving "
                    f"baseline cache unchanged. Dump at: {output}",
                    file=sys.stderr,
                )
            elif any_forced:
                print(
                    f"[debug dump local] forced run — skipping cache sync to avoid "
                    f"contaminating baseline. Dump at: {output}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[debug dump local] --no-cache-sync — leaving baseline cache "
                    f"unchanged. Dump at: {output}",
                    file=sys.stderr,
                )
        else:
            # No --output → cache is the destination, no extra copy needed.
            output = cache_target
            output.parent.mkdir(parents=True, exist_ok=True)
            pcdump_path.rename(output)
            # Touch mtime to now: Path.rename() preserves the source file's
            # creation time (the pcdump temp was created at compile start, so
            # its mtime predates any edits the user made during the compile).
            # Without this, the mtime-based staleness check fires immediately
            # after a refresh because src_mtime > cache_mtime.  The content-
            # hash sidecar (written below) supersedes mtime for freshness, but
            # os.utime() is kept for backward compat with callers that don't
            # have a sidecar yet.
            os.utime(output, None)
            # Write the content-hash sidecar for the canonical cache target.
            try:
                if compiled_source_digest is not None:
                    pcdump_cache.write_hash_sidecar_digest(
                        output, compiled_source_digest
                    )
                else:
                    pcdump_cache.write_hash_sidecar(output, src_path_for_cache)
            except OSError:
                pass  # best-effort; mtime fallback still applies
    else:
        # --output specified: write there.
        output.parent.mkdir(parents=True, exist_ok=True)
        pcdump_path.rename(output)
        os.utime(output, None)  # same mtime fix as above
        if skip_cache_sync:
            # Forced run — don't mirror the experimental pcdump into the
            # shared cache; it would be treated as baseline by follow-up cmds.
            if cache_skip_reason:
                print(
                    f"[debug dump local] {cache_skip_reason}; leaving "
                    f"baseline cache unchanged.",
                    file=sys.stderr,
                )
            elif any_forced:
                print(
                    f"[debug dump local] forced run — skipping cache sync to avoid "
                    f"contaminating baseline.",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[debug dump local] --no-cache-sync — leaving baseline cache "
                    f"unchanged.",
                    file=sys.stderr,
                )
        else:
            # Mirror to cache (best-effort; same content) so downstream
            # auto-resolve doesn't read a stale dump.
            try:
                cache_target.parent.mkdir(parents=True, exist_ok=True)
                cache_target.write_bytes(output.read_bytes())
                # Write hash sidecar for the mirrored cache file.
                try:
                    if compiled_source_digest is not None:
                        pcdump_cache.write_hash_sidecar_digest(
                            cache_target, compiled_source_digest
                        )
                    else:
                        pcdump_cache.write_hash_sidecar(
                            cache_target, src_path_for_cache
                        )
                except OSError:
                    pass  # best-effort
                if cache_target != output:
                    print(
                        f"wrote: {output} (also synced to cache {cache_target})",
                        file=sys.stderr,
                    )
            except OSError as e:
                print(
                    f"wrote: {output} (cache mirror failed: {e})",
                    file=sys.stderr,
                )
                _finish_pcdump_local_run()
                return
            _finish_pcdump_local_run()
            return

    print(f"wrote: {output}", file=sys.stderr)
    _finish_pcdump_local_run()


@target_app.command(name="score-source")
def score_source(
    c_file: Annotated[
        str,
        typer.Argument(
            help="Path to a .c file to compile (relative to melee root). "
                 "Can be a staging path inside `nonmatchings/`.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function within the TU to score.",
        ),
    ],
    target: Annotated[
        Path,
        typer.Option(
            "--target", "-t",
            help="Target spec (YAML or JSON, from `debug target derive`).",
        ),
    ],
    cflags_from: Annotated[
        Optional[str],
        typer.Option(
            "--cflags-from",
            help="Use cflags from this unit's ninja block instead of "
                 "inferring from c_file. Useful when c_file is a staged "
                 "candidate without its own ninja build block.",
        ),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet", "-q",
            help="Suppress everything except the integer score on stdout. "
                 "Designed for use as permuter's external scorer command.",
        ),
    ] = False,
) -> None:
    """Compile a source via debug dump local, then score against a target.

    Single-command flow for use as decomp-permuter's external scorer.
    Outputs an integer score (lower = better; 0 = perfect target match).
    Use `--quiet` to silence everything except the score itself.

    Wires:
        c_file → mwcceppc_debug.exe → pcdump.txt → parse → score_function
    """
    from ..mwcc_debug import (
        find_function,
        parse_hook_events,
        parse_pcdump,
        score_function,
    )

    melee_root = DEFAULT_MELEE_ROOT
    src_rel = _resolve_src_relative(c_file)

    # Resolve wibo + compiler (re-use debug dump local's resolution)
    wibo_path = _find_wibo()
    if wibo_path is None or not wibo_path.exists():
        typer.echo("wibo not found. Run `debug dump setup` first.", err=True)
        raise typer.Exit(2)
    debug_compiler = _find_compiler_dir() / "mwcceppc_debug.exe"
    if not debug_compiler.exists():
        typer.echo(
            "patched compiler not found. Run `debug dump setup` first.",
            err=True,
        )
        raise typer.Exit(2)

    # cflags: from the explicit unit OR from c_file's ninja block
    cflags_unit = cflags_from if cflags_from else c_file
    cflags_unit_rel = _resolve_src_relative(cflags_unit)
    cflags, _mw_version = _ninja_cflags_for_unit(cflags_unit_rel)
    if cflags_unit_rel != src_rel:
        cflags = _cflags_with_same_tu_include_dir(cflags, cflags_unit_rel)

    # Compile, generating pcdump under a unique per-PID name so parallel
    # scorer runs don't race on a shared pcdump.txt. The patched DLL reads
    # MWCC_DEBUG_PCDUMP_PATH; we write the file relative to melee_root
    # (which is the subprocess cwd) and read it back from the same path.
    import time
    pcdump_name = f"pcdump_score_{os.getpid()}_{int(time.time() * 1000)}.txt"
    pcdump_path = melee_root / pcdump_name
    if pcdump_path.exists():
        pcdump_path.unlink()

    # Use unique discard .o to avoid races across parallel scorers
    discard_o = f"/tmp/score_source_discard_{os.getpid()}_{int(time.time()*1000)}.o"

    args = (
        [str(wibo_path), str(debug_compiler)]
        + shlex.split(cflags)
        + ["-c", src_rel, "-o", discard_o]
    )

    env = os.environ.copy()
    env["MWCC_DEBUG_PCDUMP_PATH"] = pcdump_name

    proc = subprocess.run(
        args, cwd=melee_root, env=env, capture_output=True, text=True,
    )
    if not pcdump_path.exists():
        if not quiet:
            typer.echo(proc.stderr, err=True)
        # Penalty for unscoreable candidates
        print(2**30)
        raise typer.Exit(0)

    pcdump_text = pcdump_path.read_text()
    pcdump_path.unlink()  # don't pollute repo
    # Clean up the discarded .o
    try:
        os.unlink(discard_o)
    except OSError:
        pass

    # Parse + score
    fns = parse_pcdump(pcdump_text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        if not quiet:
            typer.echo(
                f"function {function!r} not in compiled pcdump. "
                f"Candidate may have removed/renamed it.",
                err=True,
            )
        print(2**30)
        raise typer.Exit(0)

    events_list = parse_hook_events(pcdump_text)
    events = find_function(events_list, function)

    target_spec = _load_target_spec(target)
    result = score_function(fn, target_spec, events=events)

    # Permuter expects an integer
    print(int(result.total))


# ---------------------------------------------------------------------------
# score-simplify-order: permuter-callable scorer for simplify-order campaigns
# ---------------------------------------------------------------------------


def _resolve_candidate_c_source(object_file: Path) -> Optional[Path]:
    """Find the candidate .c source for a given permuter-produced .o.

    Resolution order (first hit wins):
      1. $PERMUTER_C_FILE — set by decomp-permuter's CustomCommandScorer
         when the patched version is in use.
      2. <object_file>.c — convention used by our setup-simplify-order-
         scorer command: the wrapper compile.sh copies the source next
         to the .o.
      3. <object_file with .o replaced by .c> — fallback for raw permuter
         workflows where the .o was renamed.

    Returns None if no source can be found. Callers fall back to the
    pcdump-sidecar fast path or fail with a clear error.
    """
    env_path = os.environ.get("PERMUTER_C_FILE")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    sidecar = Path(str(object_file) + ".c")
    if sidecar.exists():
        return sidecar
    if object_file.suffix == ".o":
        alt = object_file.with_suffix(".c")
        if alt.exists():
            return alt
    return None


def _pcdump_for_object(
    object_file: Path,
    *,
    debug_mode: bool = False,
) -> Optional[str]:
    """Return pcdump text for a permuter-produced .o file.

    Fast path: <object_file>.pcdump.txt exists alongside the .o. This
    is the artifact the setup-simplify-order-scorer wrapper compile.sh
    drops next to the .o by setting MWCC_DEBUG_PCDUMP_PATH=<o>.pcdump.txt
    during the per-candidate compile. Zero overhead per candidate.

    Slow path: not implemented in this version. If the sidecar pcdump
    is missing, returns None and the caller surfaces a clear error
    asking the user to re-run setup-simplify-order-scorer.

    Why not implement a recompile fallback here:
      * Permuter deletes the candidate .c immediately after compile, so
        we'd have to (a) recover the source via the resolver above, and
        (b) reinvoke the debug compiler with the unit's exact cflags.
      * Both are doable but inflate per-candidate latency by ~1s
        (mwcc+wibo cold start), which materially slows the campaign.
      * The sidecar approach demands a small setup-time wrapper script,
        which we already need to generate anyway for the scorer to be
        usable as a permuter `[scorer].command`.
      * Adding the recompile path later is one well-scoped change in
        this function; doing it both now and later means we never
        exercise the fast-path code that the production setup uses.
    """
    sidecar = Path(str(object_file) + ".pcdump.txt")
    if sidecar.exists():
        try:
            return sidecar.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            if debug_mode:
                print(
                    f"[score-simplify-order] failed to read pcdump sidecar "
                    f"{sidecar}: {e}",
                    file=sys.stderr,
                )
            return None
    return None


@target_app.command(name="score-force-phys")
def score_force_phys(
    object_file: Annotated[
        Path,
        typer.Argument(
            help="Path to the candidate .o file. Reads sibling <object>.pcdump.txt.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to score."),
    ],
    target: Annotated[
        Path,
        typer.Option(
            "--target", "-t",
            help=(
                "Path to force-phys target YAML generated by "
                "setup-simplify-order-scorer --scorer-mode force-phys."
            ),
        ),
    ],
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit score breakdown as JSON."),
    ] = False,
    breakdown: Annotated[
        bool,
        typer.Option("--breakdown", help="Print human-readable breakdown."),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Emit diagnostics to stderr."),
    ] = False,
) -> None:
    """Permuter scorer: lex-encoded force-phys assignment hits.

    This is the colorgraph-DISPENSE companion to score-simplify-order. It
    scores candidate pcdumps by whether target ig_idx values actually receive
    their requested physical registers, so candidates remain rankable even
    when simplify-order rows are all physical placeholders (-1).
    """
    import json as _json

    from ..mwcc_debug.simplify_order_scoring import (
        LEX_BIG,
        STRUCTURAL_REJECTION_SCORE,
        extract_signature,
        find_coalesced_targets,
    )
    from ..mwcc_debug.simplify_search import (
        precolor_distance,
        score_force_phys_assignment,
    )

    PENALTY_INF = 10**9

    def _emit_sentinel(reason: str) -> None:
        if debug:
            print(f"[score-force-phys] {reason}", file=sys.stderr)
        if json_out:
            print(_json.dumps({"score": PENALTY_INF, "error": reason}))
        else:
            print(PENALTY_INF)
        raise typer.Exit(0)

    if not object_file.exists():
        _emit_sentinel(f"object file not found: {object_file}")

    try:
        import yaml  # type: ignore

        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        typer.echo(f"target spec file not found: {target}", err=True)
        raise typer.Exit(2)
    except Exception as exc:
        typer.echo(f"target spec error: {exc}", err=True)
        raise typer.Exit(2)
    if not isinstance(data, dict):
        typer.echo(f"target spec {target} must be a mapping", err=True)
        raise typer.Exit(2)
    spec_function = data.get("function")
    if spec_function != function:
        typer.echo(
            f"target spec function mismatch: spec.function={spec_function!r} "
            f"!= --function={function!r}",
            err=True,
        )
        raise typer.Exit(2)
    class_id = data.get("class_id", 0)
    if not isinstance(class_id, int) or isinstance(class_id, bool):
        typer.echo("target spec class_id must be an integer", err=True)
        raise typer.Exit(2)
    raw_baseline = data.get("baseline_dump")
    if not isinstance(raw_baseline, str) or not raw_baseline:
        typer.echo("target spec missing baseline_dump", err=True)
        raise typer.Exit(2)
    baseline_dump = Path(raw_baseline).expanduser()
    if not baseline_dump.is_absolute():
        baseline_dump = (target.parent / baseline_dump).resolve()
    raw_force_phys = data.get("force_phys")
    if not isinstance(raw_force_phys, dict) or not raw_force_phys:
        typer.echo("target spec missing non-empty force_phys mapping", err=True)
        raise typer.Exit(2)
    force_phys_map: dict[int, int] = {}
    for raw_ig, raw_phys in raw_force_phys.items():
        if (
            not isinstance(raw_ig, int)
            or isinstance(raw_ig, bool)
            or not isinstance(raw_phys, int)
            or isinstance(raw_phys, bool)
        ):
            typer.echo("force_phys must map integer ig_idx to integer phys", err=True)
            raise typer.Exit(2)
        force_phys_map[raw_ig] = raw_phys
    coalesce_preservation = data.get("coalesce_preservation", True)
    if not isinstance(coalesce_preservation, bool):
        typer.echo("coalesce_preservation must be true/false", err=True)
        raise typer.Exit(2)

    try:
        baseline_text = baseline_dump.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"failed to read baseline_dump {baseline_dump}: {exc}", err=True)
        raise typer.Exit(2)
    baseline = extract_signature(baseline_text, function, class_id=class_id)
    if baseline is None:
        typer.echo(
            f"baseline pcdump {baseline_dump} does not contain {function!r}",
            err=True,
        )
        raise typer.Exit(2)

    pcdump_text = _pcdump_for_object(object_file, debug_mode=debug)
    if pcdump_text is None:
        _emit_sentinel(
            f"pcdump sidecar missing for {object_file}; expected at "
            f"{object_file}.pcdump.txt"
        )

    candidate = extract_signature(pcdump_text, function, class_id=class_id)
    if candidate is None:
        _emit_sentinel(f"function {function!r} not in candidate pcdump")

    candidate_events = find_function(parse_hook_events(pcdump_text), function)
    coalesced_targets: set[int] = set()
    if coalesce_preservation and candidate_events is not None:
        coalesced_targets = find_coalesced_targets(
            candidate_events,
            targets=set(force_phys_map),
            class_id=class_id,
        )
    dist = precolor_distance(baseline, candidate)
    force_score = score_force_phys_assignment(baseline, candidate, force_phys_map)
    missed = len(force_phys_map) - force_score.common_prefix_length
    structural_rejection = bool(coalesced_targets)
    score = (
        STRUCTURAL_REJECTION_SCORE
        if structural_rejection
        else missed * LEX_BIG + dist.total
    )
    if json_out:
        print(_json.dumps({
            "score": score,
            "function": function,
            "targeted": len(force_phys_map),
            "force_phys_hits": force_score.common_prefix_length,
            "baseline_hits": force_score.baseline_common_prefix_length,
            "matched_igs": list(force_score.observed_prefix),
            "target_igs": list(force_score.target_prefix),
            "precolor_distance": {
                "total": dist.total,
                "ig_added": dist.ig_added,
                "ig_removed": dist.ig_removed,
                "coalesce_added": dist.coalesce_added,
                "coalesce_removed": dist.coalesce_removed,
                "spill_added": dist.spill_added,
                "spill_removed": dist.spill_removed,
            },
            "structural_rejection": structural_rejection,
            "coalesced_targets": sorted(coalesced_targets),
        }))
        return
    if breakdown:
        print(f"Function:          {function}")
        print(f"Score:             {score}")
        print(f"Target force-phys: {force_phys_map}")
        print(
            f"Force-phys hits:   {force_score.common_prefix_length} / "
            f"{len(force_phys_map)}"
        )
        print(f"Matched ig_idx:    {list(force_score.observed_prefix)}")
        print(f"Precolor distance: {dist.total}")
        if structural_rejection:
            print(f"Coalesce preservation: REJECTED {sorted(coalesced_targets)}")
        return
    print(score)


@target_app.command(name="score-simplify-order")
def score_simplify_order(
    object_file: Annotated[
        Path,
        typer.Argument(
            help="Path to the candidate .o file (positional). When "
                 "invoked from decomp-permuter's CustomCommandScorer, "
                 "this is the .o permuter just compiled.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function name to score within the candidate's TU "
                 "(required).",
        ),
    ],
    target: Annotated[
        Path,
        typer.Option(
            "--target", "-t",
            help="Path to a simplify-order target YAML spec. See "
                 "SimplifyOrderTargetSpec in "
                 "src/mwcc_debug/simplify_order_scoring.py for the schema.",
        ),
    ],
    json_out: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit the score + breakdown as a single JSON object. "
                 "When unset, prints only the integer score (permuter "
                 "contract).",
        ),
    ] = False,
    breakdown: Annotated[
        bool,
        typer.Option(
            "--breakdown",
            help="Print human-readable score breakdown to stdout. "
                 "Implies non-permuter-contract output.",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Emit diagnostic output to stderr (does not affect "
                 "stdout, so permuter still parses the integer).",
        ),
    ] = False,
    strict_polarity: Annotated[
        bool,
        typer.Option(
            "--strict-polarity",
            help=(
                "Exit non-zero when the polarity check is WRONG_POLARITY. "
                "Use in screening scripts to refuse high-volatile-target "
                "campaigns before they burn cloud compute. UNCERTAIN polarity "
                "is allowed in strict mode — only the structurally-impossible "
                "case is rejected."
            ),
        ),
    ] = False,
) -> None:
    """Permuter scorer: lex-encoded simplify-order + precolor distance.

    Outputs a single integer to stdout (lower = better, 0 = perfect).
    Designed to be invoked by decomp-permuter as a `[scorer].command`
    in settings.toml — see `debug permute setup-simplify-order-scorer`
    for the workflow that wires this up.

    The candidate's pcdump is read from the sibling `<object_file>.pcdump.txt`
    file that the wrapper compile.sh deposits during compilation. If that
    sidecar is missing the scorer emits the sentinel PENALTY_INF score so
    permuter treats the iteration as a compile failure rather than crashing.
    """
    # --strict-polarity implies --breakdown: the polarity diagnostic must
    # run for the strict exit to fire. Without this implication, passing
    # --strict-polarity alone would be a silent no-op.
    if strict_polarity:
        breakdown = True

    import json as _json

    from ..mwcc_debug.simplify_order_scoring import (
        Polarity,
        SimplifyOrderSpecError,
        classify_polarity,
        compute_lex_score,
        extract_signature,
        load_simplify_order_target_spec,
    )

    # Permuter's CustomCommandScorer treats PENALTY_INF (=10**9) as
    # "iteration is bad". We use the same value for any pre-score failure
    # mode (missing pcdump, missing function, malformed spec) so permuter
    # discards the iteration cleanly.
    PENALTY_INF = 10**9

    def _emit_sentinel(reason: str) -> None:
        if debug:
            print(f"[score-simplify-order] {reason}", file=sys.stderr)
        if json_out:
            print(_json.dumps({"score": PENALTY_INF, "error": reason}))
        else:
            print(PENALTY_INF)
        raise typer.Exit(0)

    if not object_file.exists():
        _emit_sentinel(f"object file not found: {object_file}")
        return  # for typing — Exit() raises

    try:
        spec = load_simplify_order_target_spec(target)
    except SimplifyOrderSpecError as e:
        # Spec-level errors are user errors, not iteration errors. Print
        # to stderr with a high exit code so permuter logs them visibly
        # but DON'T print PENALTY_INF to stdout (which would be parsed
        # silently and never reported).
        typer.echo(f"target spec error: {e}", err=True)
        raise typer.Exit(2)

    if spec.function != function:
        typer.echo(
            f"target spec function mismatch: "
            f"spec.function={spec.function!r} != --function={function!r}",
            err=True,
        )
        raise typer.Exit(2)

    # Load the baseline signature once per call (cheap — small pcdump).
    try:
        baseline_text = spec.baseline_dump.read_text(encoding="utf-8")
    except OSError as e:
        typer.echo(
            f"failed to read baseline_dump {spec.baseline_dump}: {e}",
            err=True,
        )
        raise typer.Exit(2)
    baseline = extract_signature(
        baseline_text, function, class_id=spec.class_id,
    )
    if baseline is None:
        typer.echo(
            f"baseline pcdump {spec.baseline_dump} does not contain "
            f"function {function!r}",
            err=True,
        )
        raise typer.Exit(2)

    # Per-candidate: resolve pcdump for the .o.
    pcdump_text = _pcdump_for_object(object_file, debug_mode=debug)
    if pcdump_text is None:
        _emit_sentinel(
            f"pcdump sidecar missing for {object_file}; expected at "
            f"{object_file}.pcdump.txt. The wrapper compile.sh deposits "
            f"this file during each candidate compile."
        )
        return

    candidate = extract_signature(
        pcdump_text, function, class_id=spec.class_id,
    )
    if candidate is None:
        _emit_sentinel(
            f"function {function!r} not in candidate pcdump (codegen "
            f"path may have eliminated it)"
        )
        return

    candidate_events = find_function(parse_hook_events(pcdump_text), function)

    result = compute_lex_score(
        baseline,
        candidate,
        spec.simplify_order_target,
        candidate_events=candidate_events,
        spec=spec,
    )

    if json_out:
        payload = {
            "score": result.score,
            "function": function,
            "target_len": len(spec.simplify_order_target),
            "common_prefix_length": result.simplify_score.common_prefix_length,
            "missed_prefix": (
                len(spec.simplify_order_target)
                - result.simplify_score.common_prefix_length
            ),
            "precolor_distance": {
                "total": result.precolor_distance.total,
                "ig_added": result.precolor_distance.ig_added,
                "ig_removed": result.precolor_distance.ig_removed,
                "coalesce_added": result.precolor_distance.coalesce_added,
                "coalesce_removed": result.precolor_distance.coalesce_removed,
                "spill_added": result.precolor_distance.spill_added,
                "spill_removed": result.precolor_distance.spill_removed,
            },
            "observed_prefix": list(result.simplify_score.observed_prefix),
            "target_prefix": list(result.simplify_score.target_prefix),
        }
        print(_json.dumps(payload))
        return

    if breakdown:
        print(f"Function:          {function}")
        print(f"Score:             {result.score}")

        # Decide which mode we're in for rendering prefix vs suffix lines.
        is_late_mode = bool(spec.simplify_order_target_late)

        if is_late_mode:
            target_late = spec.simplify_order_target_late
            # Derive the observed suffix by slicing the last N elements of
            # the candidate's filtered simplify order, where N = len(target_late).
            n_late = len(target_late)
            observed_suffix = list(candidate.simplify_order[-n_late:]) if n_late else []
            print(f"Target suffix:     {list(target_late)}")
            print(f"Observed suffix:   {observed_suffix}")
            print(
                f"Common suffix:     "
                f"{result.common_suffix_length} / {n_late}"
            )
        else:
            print(f"Target prefix:     {list(result.simplify_score.target_prefix)}")
            print(
                f"Observed prefix:   {list(result.simplify_score.observed_prefix)}"
            )
            print(
                f"Common prefix:     "
                f"{result.simplify_score.common_prefix_length} / "
                f"{len(spec.simplify_order_target)}"
            )

        d = result.precolor_distance
        print(f"Precolor distance: {d.total}")
        print(
            f"  IG       +{d.ig_added} -{d.ig_removed}\n"
            f"  Coalesce +{d.coalesce_added} -{d.coalesce_removed}\n"
            f"  Spill    +{d.spill_added} -{d.spill_removed}"
        )
        # Coalesce-preservation diagnostic (deferred debt #19).
        # Only runs when force_phys is present (the check needs targets).
        if spec.force_phys:
            print("")  # separator
            if not spec.coalesce_preservation:
                print("Coalesce preservation:    DISABLED")
                print(
                    "  Constraint disabled via coalesce_preservation: false. "
                    "Candidates that coalesce target ig_idx values are NOT "
                    "rejected."
                )
            elif result.structural_rejection:
                aliased = ",".join(str(x) for x in sorted(result.coalesced_targets))
                print("Coalesce preservation:    REJECTED")
                print(
                    f"  Target ig_idx [{aliased}] coalesced as alias(es) into "
                    f"another root. The candidate's allocator graph has fewer "
                    f"independent nodes than the force_phys mapping presupposes. "
                    f"Rejected with score={result.score}."
                )
            else:
                print("Coalesce preservation:    ALL TARGETS INDEPENDENT")

        # Polarity diagnosis (deferred debt #20 pre-flight check).
        # Only runs when the target.yaml provides force_phys; otherwise
        # the screening agent didn't ask for the check and we stay quiet.
        if spec.force_phys:
            target_position = "late" if is_late_mode else "first"
            polarity = classify_polarity(spec.force_phys, target_position=target_position)
            print("")  # blank line separator
            if polarity is Polarity.WRONG_POLARITY:
                print("Polarity check:    WRONG POLARITY")
                if target_position == "first":
                    print(
                        "  At least one target physical is in the high-volatile "
                        "range (r10-r12). MWCC's volatile dispense is lowest-"
                        "first, so target ig_idx values at simplify positions "
                        "0/1/... get r3/r4/... not r10-r12. --want-first is the "
                        "wrong polarity for this target."
                    )
                    print(
                        "  Recommend: switch to `--want-late N,M` (Phase 3 of "
                        "deferred debt #20, shipped). The target ig_idx values "
                        "need to be at the END of simplify order so the lower "
                        "volatiles are consumed first."
                    )
                else:  # target_position == "late"
                    print(
                        "  At least one target physical is in the top "
                        "non-volatile range (r28-r31) or is r3. Those are "
                        "dispensed FIRST by MWCC's allocator, so target "
                        "ig_idx values at the END of simplify order won't "
                        "get them. --want-late is the wrong polarity for "
                        "this target."
                    )
                    print(
                        "  Recommend: switch to `--want-first N,M`. The "
                        "target ig_idx values should be at the START of "
                        "simplify order."
                    )
            elif polarity is Polarity.UNCERTAIN:
                print("Polarity check:    UNCERTAIN")
                print(
                    "  At least one target physical is mid-volatile (r4-r9). "
                    "--want-first may or may not reach the target depending "
                    "on interference state at dispense time. If campaign "
                    "produces prefix hits but no match% progress, consider "
                    "whether dispense direction is the issue."
                )
            elif polarity is Polarity.SAFE:
                print("Polarity check:    SAFE")
            else:
                raise ValueError(
                    f"unhandled Polarity value: {polarity!r} "
                    f"(this branch needs updating when Polarity is extended)"
                )

            if strict_polarity and polarity is Polarity.WRONG_POLARITY:
                raise typer.Exit(code=2)
        return

    # Permuter contract: single integer on stdout.
    print(result.score)


@permute_app.command(name="run")
def permute(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to permute (required).",
        ),
    ],
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Target spec for mwcc-debug scoring. Auto-derived from "
                 "current pcdump if omitted.",
        ),
    ] = None,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    blend: Annotated[
        float,
        typer.Option(
            "--blend",
            help="Weight α applied to mwcc-debug score when blending "
                 "with objdiff bytes. Final = bytes + α * mwcc.",
        ),
    ] = 0.1,
    threads: Annotated[
        int,
        typer.Option(
            "-j", "--threads",
            help="Permuter parallelism. score-source now uses unique "
                 "per-PID pcdump filenames so parallel threads no longer "
                 "race; safe to raise above 1.",
        ),
    ] = 1,
    extra: Annotated[
        Optional[list[str]],
        typer.Argument(
            help="Extra args passed through to permuter.py.",
        ),
    ] = None,
) -> None:
    """Tier 2: run decomp-permuter with mwcc-debug score blended in.

    Per-iteration, permuter scores candidates by combining objdiff
    byte-distance with `melee-agent debug target score-source` (IGNode-distance
    from pcdump). Byte distance stays primary; the mwcc signal breaks
    ties between byte-equivalent candidates — useful for register-cascade
    stuck cases where the byte scorer can't distinguish many mutations.

    Prerequisites:
    - Run `melee-agent debug dump setup` (one-time).
    - `<perm-root>/nonmatchings/<function>/` exists with base.c, target.o,
      compile.sh. Create via `decomp-permuter/import.py`.
    - `melee-agent debug permute fix-compile <perm_dir>` if compile.sh was
      generated on macOS (auto-applied by debug permute config).

    Default is single-threaded for safety. score-source now emits
    per-PID pcdump filenames so parallel threads no longer race on a
    shared pcdump.txt — raise `-j` above 1 if you want concurrency.

    Passing flags through to permuter.py: Typer will try to consume any
    leading `--<name>` tokens as options of `permute` itself. Use `--`
    to separate. Examples:

        # WRONG — Typer rejects --best-only as an unknown option
        melee-agent debug permute run -f my_fn --best-only

        # RIGHT — `--` ends `permute run`'s own options; everything after
        # is forwarded to permuter.py
        melee-agent debug permute run -f my_fn -- --best-only
        melee-agent debug permute run -f my_fn -j 4 -- --best-only --seed 0

    Note: stdout is set to line-buffering so that piping through `tail -N`
    shows live progress instead of buffering until the permuter exits.
    """
    # Force line-buffering on stdout so progress output is visible when
    # the command is piped (e.g. `melee-agent debug permute run ... | tail -20`).
    # Without this, Python's stdio buffering holds all output until the
    # process exits — which never happens naturally for the permuter.
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

    melee_root = DEFAULT_MELEE_ROOT
    perm_dir = _resolve_permuter_function_dir(
        function, perm_root=perm_root, melee_root=melee_root)

    if not perm_dir.exists():
        typer.echo(
            f"{perm_dir} not found.\n"
            + _permuter_import_hint(
                function,
                perm_root=perm_root,
                melee_root=melee_root,
            ),
            err=True,
        )
        raise typer.Exit(2)

    # Resolve TU for cflags
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"could not find {function!r} in report.json. "
            f"Rebuild via `ninja build/GALE01/report.json`.",
            err=True,
        )
        raise typer.Exit(3)
    unit_c = f"src/{unit}.c"

    # Derive target if not given
    if target is None:
        target = melee_root / "build" / "mwcc_debug_cache" / \
            f"{unit}_target.json"
        target.parent.mkdir(parents=True, exist_ok=True)

        cache_p = pcdump_cache.cache_path(melee_root, unit)
        if not cache_p.exists():
            print(
                f"[..] no cached pcdump for {unit}; "
                f"generating via debug dump local..."
            )
            wibo_p = _find_wibo()
            cc_p = _find_compiler_dir() / "mwcceppc_debug.exe"
            if wibo_p is None or not wibo_p.exists() or not cc_p.exists():
                typer.echo(
                    "wibo or patched compiler missing. Run "
                    "`melee-agent debug dump setup` first.",
                    err=True,
                )
                raise typer.Exit(4)
            cflags, _ = _ninja_cflags_for_unit(unit_c)
            pcd_path = melee_root / "pcdump.txt"
            if pcd_path.exists():
                pcd_path.unlink()
            subprocess.run(
                [str(wibo_p), str(cc_p)]
                + shlex.split(cflags)
                + ["-c", unit_c, "-o", "/tmp/permute_init.o"],
                cwd=melee_root,
                check=True,
            )
            pcdump_cache.ensure_cache_dir(melee_root)
            pcd_path.rename(cache_p)
            print(f"[ok] pcdump → {cache_p}")

        from ..mwcc_debug import derive_target_from_function
        text = cache_p.read_text()
        fns = parse_pcdump(text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is None:
            _abort_function_not_in_dump(function, [f.name for f in fns])
        spec = derive_target_from_function(fn)
        target.write_text(json.dumps(spec, indent=2))
        print(f"[ok] derived target → {target}")
    else:
        print(f"[ok] using target: {target}")

    # Locate the wrapper script
    wrapper = (
        melee_root / "tools" / "melee-agent" / "scripts"
        / "permute_with_mwcc.py"
    )
    if not wrapper.exists():
        typer.echo(f"wrapper not found: {wrapper}", err=True)
        raise typer.Exit(4)

    # Build env
    env = os.environ.copy()
    permuter_code_root = _resolve_decomp_permuter_root(perm_root)
    env["MELEE_PERMUTER_ROOT"] = str(permuter_code_root)
    env["MELEE_ROOT"] = str(melee_root)
    env["MWCC_DEBUG_TARGET"] = str(target)
    env["MWCC_DEBUG_FN"] = function
    env["MWCC_DEBUG_UNIT"] = unit_c
    env["MWCC_DEBUG_BLEND"] = str(blend)

    cmd = ["python", str(wrapper), str(perm_dir), "-j", str(threads)]
    if extra:
        cmd.extend(extra)

    print(f"[ok] launching permuter (blend={blend} threads={threads})...")
    print(f"  {' '.join(cmd)}")
    print()

    proc = subprocess.run(cmd, env=env, cwd=permuter_code_root)
    raise typer.Exit(proc.returncode)


@inspect_app.command(name="var-to-virtual")
def var_to_virtual(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to look up (required).",
        ),
    ],
    var_name: Annotated[
        str,
        typer.Argument(help="Source-level variable name."),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Auto-resolves from cache.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
    basis: Annotated[
        bool,
        typer.Option(
            "--basis",
            help="Also dump the heuristic's evidence: parsed params/locals, "
                 "the cursor calculation step-by-step, observed virtuals in "
                 "the pre-pass, and any red flags that lowered confidence. "
                 "Use when you suspect var-to-virtual gave you a wrong "
                 "mapping — the basis tells you whether the cursor "
                 "shifted, a macro hid a decl, or the function has nested "
                 "blocks the parser skipped.",
        ),
    ] = False,
    all_matches: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Return ALL bindings matching the name. Default picks "
                 "the highest-confidence top-level binding for back-compat.",
        ),
    ] = False,
    scope_filter: Annotated[
        Optional[str],
        typer.Option(
            "--scope",
            help="Filter bindings by scope path. Exact match by default; "
                 "trailing '/' for prefix (e.g. 'fn_X/' matches the "
                 "function and all nested blocks inside it).",
        ),
    ] = None,
) -> None:
    """Bridge: given a source variable name, predict its MWCC virtual.

    Reports `confidence`: best-guess (heuristic matched, no concerns),
    low-confidence (matched but red flags present — cursor may be
    wrong), ambiguous (no observed virtual for this variable), or
    unsupported (e.g., variable lives in a macro the tokenizer can't
    see). Pass `--basis` to see the underlying evidence.
    """
    from ..mwcc_debug.symbol_bridge import (
        find_virtual_for_var,
        find_all_virtuals_for_var,
        list_bindings_with_basis,
    )
    from ..mwcc_debug.scope_path import format_for_display, is_nested_within

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    text = pcdump_path.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre = fn.last_precolor_pass()
    if pre is None:
        typer.echo(
            f"no pre-coloring pass for {function}", err=True,
        )
        raise typer.Exit(3)

    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    source = (melee_root / "src" / f"{unit}.c").read_text()
    bindings, basis_data = list_bindings_with_basis(source, function, pre)
    # Phase 1 nested-block awareness: scope-aware lookup with optional
    # --all and --scope filters. Default behavior (single binding,
    # highest confidence) preserves back-compat.
    matches = find_all_virtuals_for_var(bindings, var_name)

    if scope_filter is not None:
        scope_value = scope_filter.rstrip("/")
        prefix_mode = scope_filter.endswith("/")
        target = tuple(scope_value.split("/")) if scope_value else ()
        if prefix_mode:
            matches = [b for b in matches if is_nested_within(b.scope_path, target)]
        else:
            matches = [b for b in matches if b.scope_path == target]

    binding = matches[0] if matches else None

    if all_matches:
        # New --all output path — emit the full match list, then return.
        if not matches:
            if json_out:
                print(json.dumps(
                    {"var_name": var_name, "found": False, "bindings": []},
                    indent=2,
                ))
            else:
                typer.echo(
                    f"variable {var_name!r} not found in {function}",
                    err=True,
                )
            raise typer.Exit(1)
        if json_out:
            payload = {
                "var_name": var_name,
                "found": True,
                "bindings": [
                    {
                        "virtual": b.virtual,
                        "decl_line": b.decl_line,
                        "kind": b.kind,
                        "type": b.type_str,
                        "confidence": b.confidence,
                        "scope_path": list(b.scope_path),
                    } for b in matches
                ],
            }
            if basis and basis_data is not None:
                payload["basis"] = _basis_to_dict(basis_data)
            print(json.dumps(payload, indent=2))
        else:
            print(f"{var_name} ({len(matches)} matches):")
            for b in matches:
                scope_str = format_for_display(b.scope_path) or "(top)"
                print(
                    f"  -> r{b.virtual}  ({b.confidence}, "
                    f"type={b.type_str}, scope={scope_str}, "
                    f"line {b.decl_line})"
                )
        return

    if binding is None:
        if json_out:
            payload: dict = {"var_name": var_name, "found": False}
            if basis and basis_data is not None:
                payload["basis"] = _basis_to_dict(basis_data)
            print(json.dumps(payload, indent=2))
        else:
            typer.echo(
                f"variable {var_name!r} not found in {function}",
                err=True,
            )
            if basis and basis_data is not None:
                _print_basis(basis_data, bindings)
        raise typer.Exit(1)

    if json_out:
        payload = {
            "var_name": binding.var_name,
            "virtual": binding.virtual,
            "kind": binding.kind,
            "type": binding.type_str,
            "confidence": binding.confidence,
            "found": True,
        }
        if basis and basis_data is not None:
            payload["basis"] = _basis_to_dict(basis_data)
        print(json.dumps(payload, indent=2))
    else:
        scope_str = format_for_display(binding.scope_path) or "(top)"
        print(
            f"{binding.var_name} -> r{binding.virtual}  "
            f"({binding.confidence}, type={binding.type_str}, "
            f"scope={scope_str}, line {binding.decl_line})"
        )
        if basis and basis_data is not None:
            print()
            _print_basis(basis_data, bindings)


@suggest_app.command(name="register-tiebreak")
def suggest_register_tiebreak(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    force_phys: Annotated[
        str,
        typer.Option(
            "--force-phys",
            help="Reachable IG:PHYS or CLASS:IG:PHYS assignment, e.g. 53:4.",
        ),
    ],
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit guidance as JSON."),
    ] = False,
) -> None:
    """Suggest source levers for compiler-temp register tiebreaks.

    Use this when force-phys proves a Case B/C register assignment reachable
    but `virtual-to-var` reports no source variable bound to the target IG.
    """
    unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
    guidance = _register_tiebreak_guidance(
        function=function,
        unit=unit,
        force_phys=force_phys,
    )
    if json_out:
        print(json.dumps(guidance, indent=2))
    else:
        _print_register_tiebreak_guidance(guidance)


@suggest_app.command(name="coalesce")
def suggest_coalesce_source(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze (required).",
        ),
    ],
    pair: Annotated[
        Optional[str],
        typer.Option(
            "-V", "--pair",
            help="Pair mode: 'virt=root' (e.g. '53=3'). Mutually "
                 "exclusive with --discover.",
        ),
    ] = None,
    discover: Annotated[
        bool,
        typer.Option(
            "--discover",
            help="Discover mode: find candidate coalesces that would "
                 "shorten the longest callee-save cascade. Mutually "
                 "exclusive with --pair.",
        ),
    ] = False,
    top: Annotated[
        int,
        typer.Option(
            "--top",
            help="Discover mode: max candidates (default 3). Raises "
                 "BadParameter if passed in pair mode.",
        ),
    ] = 3,
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Path to pcdump.txt. Auto-resolves from cache.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
    include_low_confidence: Annotated[
        bool,
        typer.Option(
            "--include-low-confidence",
            help="Use low-confidence bridge bindings for source-line "
                 "annotations.",
        ),
    ] = False,
) -> None:
    """Suggest C-source patterns producing a specific coalesce, or
    discover candidate coalesces that would shorten the cascade.

    Pair mode example:
        debug suggest coalesce -f fn_802461BC -V 53=3

    Discover mode example:
        debug suggest coalesce -f fn_802461BC --discover --top 5
    """
    from ..mwcc_debug.suggest_coalesce import render_json, render_text, run

    # Validation: exactly one of --pair / --discover (XOR check)
    if (pair is None) == (not discover):
        raise typer.BadParameter(
            "exactly one of --pair / --discover required"
        )
    # --top only makes sense in discover mode
    if pair is not None and top != 3:
        raise typer.BadParameter(
            "--top is only valid with --discover"
        )

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(
        pcdump, function, melee_root, require_fresh=True,
    )
    text = pcdump_path.read_text()

    # Load source for the bridge — CLI handles this so the orchestrator
    # stays path-free (avoids circular import on cli.debug helpers).
    source_text = ""
    unit = _find_unit_for_function(function, melee_root)
    if unit is not None:
        src_path = melee_root / "src" / f"{unit}.c"
        if src_path.exists():
            source_text = src_path.read_text()

    parsed_pair: Optional[tuple[int, int]] = None
    if pair is not None:
        try:
            lhs, rhs = pair.split("=", 1)
            parsed_pair = (int(lhs), int(rhs))
        except (ValueError, TypeError):
            raise typer.BadParameter(
                f"invalid --pair {pair!r}; expected 'virt=root' (e.g. '53=3')"
            )

    try:
        report = run(
            function=function,
            pair=parsed_pair,
            discover=discover,
            top=top,
            include_low_confidence=include_low_confidence,
            pcdump_text=text,
            source_text=source_text,
        )
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(3)

    if json_out:
        print(render_json(report))
    else:
        print(render_text(report))


def _emit_suggest_schedule_source(
    *,
    function: str,
    force_schedule: str,
    against: Path,
    pcdump: Path | None,
    source_file: Path | None,
    json_out: bool,
) -> None:
    from ..mwcc_debug.suggest_schedule import (
        render_json,
        render_text,
        run,
    )

    force_schedule = _validate_force_schedule(force_schedule)
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=False,
    )
    if not against.is_file():
        raise typer.BadParameter(f"forced-path pcdump not found: {against}")
    source_text = None
    source_label = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            candidate = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if candidate.is_file():
                source_text = candidate.read_text()
                try:
                    source_label = str(candidate.relative_to(DEFAULT_MELEE_ROOT))
                except ValueError:
                    source_label = str(candidate)

    report = run(
        pcdump_path.read_text(),
        against.read_text(),
        function=function,
        force_schedule=force_schedule,
        source_text=source_text,
        source_file=source_label,
    )
    print(render_json(report) if json_out else render_text(report))


@suggest_app.command(name="schedule")
def suggest_schedule_source(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    force_schedule: Annotated[
        str,
        typer.Option(
            "--force-schedule",
            help=(
                "Target scheduler swap list that produced the forced pcdump, "
                "e.g. 'lwz:0x94>0x90,lwz:0xAC>0xA8'."
            ),
        ),
    ],
    against: Annotated[
        Path,
        typer.Option(
            "--against",
            help="Forced-path pcdump.txt to compare against the real path.",
        ),
    ],
    pcdump: Annotated[
        Path | None,
        typer.Option(
            "--pcdump",
            help="Real-path pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    source_file: Annotated[
        Path | None,
        typer.Option(
            "--source-file",
            help=(
                "C source file used for advisory IR/source provenance. "
                "Defaults to the repo source for the function when available."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Suggest C source reshapes for a divergent scheduler decision."""
    _emit_suggest_schedule_source(
        function=function,
        force_schedule=force_schedule,
        against=against,
        pcdump=pcdump,
        source_file=source_file,
        json_out=json_out,
    )


@debug_app.command(name="suggest-schedule-source", hidden=True)
def suggest_schedule_source_compat(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    force_schedule: Annotated[
        str,
        typer.Option(
            "--force-schedule",
            help=(
                "Target scheduler swap list that produced the forced pcdump, "
                "e.g. 'lwz:0x94>0x90,lwz:0xAC>0xA8'."
            ),
        ),
    ],
    against: Annotated[
        Path,
        typer.Option(
            "--against",
            help="Forced-path pcdump.txt to compare against the real path.",
        ),
    ],
    pcdump: Annotated[
        Path | None,
        typer.Option(
            "--pcdump",
            help="Real-path pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    source_file: Annotated[
        Path | None,
        typer.Option(
            "--source-file",
            help=(
                "C source file used for advisory IR/source provenance. "
                "Defaults to the repo source for the function when available."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Backward-compatible alias for `debug suggest schedule`."""
    _emit_suggest_schedule_source(
        function=function,
        force_schedule=force_schedule,
        against=against,
        pcdump=pcdump,
        source_file=source_file,
        json_out=json_out,
    )


@suggest_app.command(name="inlines")
def suggest_inlines_cmd(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function to analyze."),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option("--pcdump", help="Optional pcdump path."),
    ] = None,
    seed_source: Annotated[
        str,
        typer.Option(
            "--seed-source",
            help="Candidate seed source: all, repeated, guide, coalesce, or patterns.",
        ),
    ] = "all",
    budget: Annotated[
        int,
        typer.Option("--budget", help="Maximum candidate count."),
    ] = 8,
    max_span_statements: Annotated[
        int,
        typer.Option("--max-span-statements", help="Max statements per repeated group."),
    ] = 6,
    verify: Annotated[
        bool,
        typer.Option("--verify", help="Stage and verify candidates."),
    ] = False,
    apply_best: Annotated[
        bool,
        typer.Option("--apply-best", help="Apply best verified candidate."),
    ] = False,
    target: Annotated[
        Optional[Path],
        typer.Option("--target", help="Optional target spec for allocator scoring."),
    ] = None,
    threshold: Annotated[
        float,
        typer.Option("--threshold", help="Minimum checkdiff delta for --apply-best."),
    ] = 0.05,
    keep_failed: Annotated[
        bool,
        typer.Option("--keep-failed", help="Preserve failed candidate diagnostics."),
    ] = False,
    emit_patches: Annotated[
        bool,
        typer.Option(
            "--emit-patches",
            help="Include full patched_source payloads in --json output.",
        ),
    ] = False,
    emit_hunks: Annotated[
        bool,
        typer.Option(
            "--emit-hunks",
            "--emit-diffs",
            help=(
                "Include compact unified hunks in --json output without "
                "full patched_source payloads."
            ),
        ),
    ] = False,
    trace_copies: Annotated[
        bool,
        typer.Option(
            "--trace-copies",
            help=(
                "With --verify, compile candidate pcdumps and trace newly "
                "introduced `mr` copies."
            ),
        ),
    ] = False,
    explain: Annotated[
        bool,
        typer.Option(
            "--explain",
            help="Alias for --trace-copies during --verify.",
        ),
    ] = False,
    trace_timeout: Annotated[
        float,
        typer.Option(
            "--trace-timeout",
            help="Timeout in seconds for each trace-copy pcdump compile.",
        ),
    ] = 60.0,
    checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--checkdiff-timeout",
            help="Timeout in seconds for each checkdiff run during --verify.",
        ),
    ] = 60.0,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON."),
    ] = False,
) -> None:
    """Suggest hidden inline/helper/source-shape candidates."""
    if seed_source not in {"all", "repeated", "guide", "coalesce", "patterns"}:
        raise typer.BadParameter(
            "--seed-source must be one of: all, repeated, guide, coalesce, patterns"
        )
    if apply_best and not verify:
        typer.echo("--apply-best requires --verify", err=True)
        raise typer.Exit(2)
    if explain:
        trace_copies = True
    if trace_copies and not verify:
        typer.echo("--trace-copies/--explain requires --verify", err=True)
        raise typer.Exit(2)
    if target is not None and not verify:
        typer.echo("--target is only used with --verify", err=True)

    from ..mwcc_debug.suggest_inlines import render_json, render_text, run

    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    source_path = melee_root / "src" / f"{unit}.c"
    source_rel = str(source_path.relative_to(melee_root))
    source = source_path.read_text()
    pcdump_text = ""
    if pcdump is not None:
        pcdump_text = pcdump.read_text()

    report = run(
        source=source,
        function=function,
        pcdump_text=pcdump_text,
        seed_source=seed_source,
        budget=budget,
        max_span_statements=max_span_statements,
        verify=False,
    )
    if verify:
        from ..mwcc_debug.candidate_verify import (
            CheckdiffResult,
            parse_checkdiff_json,
            verify_real_tree_patches,
        )
        from ..mwcc_debug.source_shape import (
            CandidateCopyTrace,
            CandidateCopyTraceSet,
            rank_scores,
            summarize_candidate_copy_traces,
        )

        def _run_trace_pcdump(src_rel: str) -> str:
            with tempfile.TemporaryDirectory() as td:
                out_path = Path(td) / "pcdump.txt"
                env = os.environ.copy()
                pkg_root = str(melee_root / "tools" / "melee-agent")
                existing = env.get("PYTHONPATH")
                env["PYTHONPATH"] = (
                    pkg_root if not existing
                    else f"{pkg_root}{os.pathsep}{existing}"
                )
                cmd = [
                    sys.executable,
                    "-m",
                    "src.cli",
                    "debug",
                    "dump",
                    "local",
                    src_rel,
                    "--output",
                    str(out_path),
                    "--no-cache-sync",
                    "--function",
                    function,
                ]
                proc = subprocess.run(
                    cmd,
                    cwd=melee_root,
                    capture_output=True,
                    text=True,
                    timeout=trace_timeout,
                    env=env,
                )
                if proc.returncode != 0:
                    detail = (proc.stderr or proc.stdout).strip()
                    raise RuntimeError(
                        detail or f"debug dump local exited {proc.returncode}"
                    )
                if not out_path.exists():
                    raise RuntimeError("debug dump local produced no pcdump output")
                return out_path.read_text()

        def _candidate_copy_trace_from_report(copy_report) -> CandidateCopyTrace:
            return CandidateCopyTrace(
                from_virtual=copy_report.from_virtual,
                to_virtual=copy_report.to_virtual,
                status=copy_report.status,
                likely_cause=copy_report.likely_cause,
                first_copy_pass=(
                    None if copy_report.first_copy is None
                    else copy_report.first_copy.pass_name
                ),
                last_copy_pass=(
                    None if copy_report.last_copy is None
                    else copy_report.last_copy.pass_name
                ),
                first_copy_block=(
                    None if copy_report.first_copy is None
                    else copy_report.first_copy.block_idx
                ),
                last_copy_block=(
                    None if copy_report.last_copy is None
                    else copy_report.last_copy.block_idx
                ),
                first_absent_pass=copy_report.first_absent_pass,
                transform_category=copy_report.transform_category,
                note=copy_report.note,
            )

        def _candidate_target_function(candidate) -> str:
            if candidate.anchor.scope_path:
                return candidate.anchor.scope_path[0]
            return candidate.metadata.get("helper_function", function)

        def _candidate_priority_virtuals(
            candidate,
            candidate_pcdump: str,
        ) -> tuple[int, ...]:
            from ..mwcc_debug.symbol_bridge import (
                find_all_virtuals_for_var,
                list_bindings_with_basis,
            )

            virtuals: list[int] = list(candidate.anchor.virtuals)
            target_function = _candidate_target_function(candidate)
            fns = parse_pcdump(candidate_pcdump, function=target_function)
            fn = fns[0] if fns else None
            pre_pass = None if fn is None else fn.last_precolor_pass()
            if pre_pass is None:
                return tuple(dict.fromkeys(virtuals))

            bindings, _basis = list_bindings_with_basis(
                source_path.read_text(),
                target_function,
                pre_pass,
            )
            for name in candidate.reads:
                if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) is None:
                    continue
                for binding in find_all_virtuals_for_var(bindings, name):
                    if binding.virtual >= 32:
                        virtuals.append(binding.virtual)
            return tuple(dict.fromkeys(virtuals))

        def _checkdiff_runner(fn_name: str) -> CheckdiffResult:
            cmd = [
                "python",
                "tools/checkdiff.py",
                fn_name,
                "--no-build",
                "--no-tty",
                "--format",
                "json",
            ]
            proc = subprocess.run(
                cmd,
                cwd=melee_root,
                capture_output=True,
                text=True,
                timeout=checkdiff_timeout,
                env=_checkdiff_env_without_fingerprint(),
            )
            if not proc.stdout.strip():
                cmd_text = " ".join(cmd)
                raise RuntimeError(
                    proc.stderr.strip()
                    or f"checkdiff produced no JSON: {cmd_text}"
                )
            return parse_checkdiff_json(proc.stdout)

        baseline_result = None
        try:
            baseline_result = _checkdiff_runner(function)
        except Exception as exc:
            typer.echo(
                f"[suggest-inlines] baseline checkdiff unavailable: "
                f"{type(exc).__name__}: {exc}",
                err=True,
            )

        copy_trace_runner = None
        trace_setup_error = None
        baseline_trace_pcdump = pcdump_text or None
        candidate_by_id = {
            candidate.candidate_id: candidate
            for candidate in report.candidates
        }
        if trace_copies:
            if baseline_trace_pcdump is None:
                try:
                    baseline_trace_pcdump = _run_trace_pcdump(source_rel)
                except Exception as exc:
                    trace_setup_error = f"{type(exc).__name__}: {exc}"
                    typer.echo(
                        f"[suggest-inlines] baseline pcdump unavailable for "
                        f"copy tracing: {trace_setup_error}",
                        err=True,
                    )

            if baseline_trace_pcdump is None:
                def _copy_trace_runner(_candidate) -> CandidateCopyTraceSet:
                    trace = CandidateCopyTrace(
                        from_virtual=None,
                        to_virtual=None,
                        status="trace-error",
                        likely_cause="trace-error",
                        note=trace_setup_error,
                    )
                    return CandidateCopyTraceSet(
                        traces=(trace,),
                        total_count=1,
                    )
            else:
                from ..mwcc_debug.copy_trace import list_new_copy_lifetimes

                def _copy_trace_runner(_candidate) -> CandidateCopyTraceSet:
                    candidate_pcdump = _run_trace_pcdump(source_rel)
                    traces = [
                        _candidate_copy_trace_from_report(copy_report)
                        for copy_report in list_new_copy_lifetimes(
                            baseline_trace_pcdump,
                            candidate_pcdump,
                            function,
                            reg_class="gpr",
                        )
                    ]
                    candidate = candidate_by_id.get(_candidate.candidate_id)
                    priority_virtuals = (
                        () if candidate is None
                        else _candidate_priority_virtuals(
                            candidate,
                            candidate_pcdump,
                        )
                    )
                    return summarize_candidate_copy_traces(
                        traces,
                        priority_virtuals=priority_virtuals,
                    )

            copy_trace_runner = _copy_trace_runner

        report.scores = rank_scores(verify_real_tree_patches(
            function=function,
            source_path=source_path,
            patches=report.patches,
            checkdiff_runner=_checkdiff_runner,
            apply_best=apply_best,
            threshold=threshold,
            diagnostics_root=Path("nonmatchings") / function / "suggest_inlines",
            baseline_result=baseline_result,
            copy_trace_runner=copy_trace_runner,
        ))
    if json_out:
        print(render_json(
            report,
            emit_patches=emit_patches,
            emit_hunks=emit_hunks,
        ))
    else:
        print(render_text(report))


def _basis_to_dict(basis) -> dict:
    """Render a BindingBasis as a JSON-compatible dict."""
    return {
        "parsed_params": [
            {"name": p.name, "type": p.type_str, "decl_index": p.decl_index}
            for p in basis.parsed_params
        ],
        "parsed_locals": [
            {"name": ld.name, "type": ld.type_str, "decl_index": ld.decl_index}
            for ld in basis.parsed_locals
        ],
        "observed_virtuals": basis.observed_virtuals,
        "unrecognized_decls": basis.unrecognized_decls,
        "red_flags": basis.red_flags,
    }


def _print_basis(basis, bindings) -> None:
    """Human-readable dump of a BindingBasis + how the cursor mapped."""
    print("=== basis ===")
    if basis.red_flags:
        print(f"red flags: {', '.join(basis.red_flags)}")
        print("  (these demote 'best-guess' → 'low-confidence' for locals)")
    else:
        print("red flags: (none)")
    print()
    print(f"parsed params ({len(basis.parsed_params)}):")
    if not basis.parsed_params:
        print("  (none)")
    for p in basis.parsed_params:
        print(f"  [{p.decl_index}] {p.type_str:<22s} {p.name}")
    print()
    print(f"parsed locals ({len(basis.parsed_locals)}):")
    if not basis.parsed_locals:
        print("  (none)")
    for ld in basis.parsed_locals:
        print(f"  [{ld.decl_index}] {ld.type_str:<22s} {ld.name}")
    if basis.unrecognized_decls:
        print()
        print("unrecognized decl-shaped statements (parser couldn't handle):")
        for s in basis.unrecognized_decls:
            print(f"  • {s}")
    print()
    obs = basis.observed_virtuals
    obs_str = (
        ", ".join(f"r{v}" for v in obs[:16])
        + (f", ... (+{len(obs) - 16} more)" if len(obs) > 16 else "")
    ) if obs else "(none)"
    print(f"observed virtuals in pre-pass ({len(obs)}): {obs_str}")
    print()
    print("predicted bindings (cursor = 32 + position):")
    for b in bindings:
        marker = "✓" if b.virtual in obs else "·" if b.kind == "param" else "✗"
        print(f"  {marker} {b.var_name:<22s} r{b.virtual:<5d} "
              f"[{b.kind}/{b.confidence}]")


def _parse_virtual_reg_token(token: str) -> int:
    vstr = token.strip()
    if vstr.lower().startswith(("r", "f")):
        vstr = vstr[1:]
    try:
        return int(vstr)
    except ValueError:
        raise typer.BadParameter(
            f"invalid virtual register {token!r}; expected an integer "
            "or a register token like r108/f108"
        )


def _reg_class_from_virtual_token(token: Optional[str]) -> Optional[str]:
    if token is None:
        return None
    stripped = token.strip().lower()
    if stripped.startswith("r"):
        return "gpr"
    if stripped.startswith("f"):
        return "fpr"
    return None


def _effective_reg_class(
    explicit: Optional[str],
    *tokens: Optional[str],
    default: Optional[str] = None,
) -> Optional[str]:
    if explicit is not None:
        valid = {"gpr", "int", "r", "fp", "fpr", "f", "float"}
        if explicit.strip().lower() not in valid:
            raise typer.BadParameter(
                f"invalid register class {explicit!r}; expected gpr/int or fp/fpr"
            )
        return explicit
    for token in tokens:
        inferred = _reg_class_from_virtual_token(token)
        if inferred is not None:
            return inferred
    return default


@inspect_app.command(name="virtual-to-ig")
def virtual_to_ig(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to look up.",
        ),
    ],
    virtual: Annotated[
        str,
        typer.Option(
            "--virtual",
            help="Visible pcode virtual register, e.g. r108 or 108.",
        ),
    ],
    reg_class: Annotated[
        Optional[str],
        typer.Option(
            "--class",
            help="Register class to select when an ig_idx is ambiguous "
                 "(gpr/int or fp/fpr). Inferred from r*/f* tokens when omitted.",
        ),
    ] = None,
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Map a visible pcode virtual register to allocator graph identity."""
    from ..mwcc_debug.copy_trace import find_virtual_to_ig

    virtual_int = _parse_virtual_reg_token(virtual)
    effective_class = _effective_reg_class(reg_class, virtual)
    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    result = find_virtual_to_ig(
        pcdump_path.read_text(),
        function,
        virtual_int,
        reg_class=effective_class,
    )

    if json_out:
        print(json.dumps(result.to_dict(), indent=2))
        return

    print(f"Function: {function}")
    print(f"Virtual:  r{virtual_int}")
    print(f"Status:   {result.status}")
    if result.note:
        print(f"Note:     {result.note}")
    if result.class_id is not None:
        print(f"Class:    {result.class_id}")
    if result.candidate_class_ids:
        classes = ", ".join(str(class_id) for class_id in result.candidate_class_ids)
        print(f"Classes:  {classes}")
    if result.ig_idx is not None:
        print(f"ig_idx:   {result.ig_idx}")
    if result.simplify_iter is not None:
        print(f"Simplify: iter {result.simplify_iter}")
    if result.color_iter is not None:
        assigned = (
            "?" if result.assigned_reg is None else f"r{result.assigned_reg}"
        )
        print(f"Color:    iter {result.color_iter}, assigned {assigned}")
    if result.live_range is not None:
        print(
            f"Live:     {result.live_range[0]}..{result.live_range[1]} "
            f"({result.use_count} use(s))"
        )
    if result.first_occurrence is not None:
        occ = result.first_occurrence
        print(
            "First:    "
            f"{occ.pass_name} B{occ.block_idx}:{occ.instr_idx} "
            f"{occ.opcode} {occ.operands}"
        )
    if result.last_occurrence is not None:
        occ = result.last_occurrence
        print(
            "Last:     "
            f"{occ.pass_name} B{occ.block_idx}:{occ.instr_idx} "
            f"{occ.opcode} {occ.operands}"
        )


@inspect_app.command(name="trace-copy")
def trace_copy(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function containing the pcode copy.",
        ),
    ],
    from_reg: Annotated[
        Optional[str],
        typer.Option(
            "--from",
            help="Source virtual register for the copy, e.g. r50.",
        ),
    ] = None,
    to_reg: Annotated[
        Optional[str],
        typer.Option(
            "--to",
            help="Destination virtual register for the copy, e.g. r108.",
        ),
    ] = None,
    list_copies: Annotated[
        bool,
        typer.Option(
            "--list-copies",
            help="Discover and trace all virtual-register copies in the function.",
        ),
    ] = False,
    involving: Annotated[
        Optional[str],
        typer.Option(
            "--involving",
            help="Discovery filter: only copies with this source or destination virtual.",
        ),
    ] = None,
    near_block: Annotated[
        Optional[int],
        typer.Option(
            "--near-block",
            help="Discovery filter: only copies observed in this basic block.",
        ),
    ] = None,
    reg_class: Annotated[
        Optional[str],
        typer.Option(
            "--class",
            help="Register class for virtual-to-IG lookup (gpr/int or fp/fpr).",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "C source file used to map call-return copy chains back to "
                "source expressions. Defaults to the repo source for the "
                "function when available."
            ),
        ),
    ] = None,
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Trace where a pcode copy appears and why it disappears."""
    from ..mwcc_debug.copy_trace import list_copy_lifetimes, trace_copy_lifetime

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    pcdump_text = pcdump_path.read_text()
    effective_class = _effective_reg_class(
        reg_class,
        from_reg,
        to_reg,
        involving,
        default="gpr",
    )
    source_text = None
    source_label = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, melee_root)
        if unit is not None:
            candidate = melee_root / "src" / f"{unit}.c"
            if candidate.is_file():
                source_text = candidate.read_text()
                try:
                    source_label = str(candidate.relative_to(melee_root))
                except ValueError:
                    source_label = str(candidate)

    if list_copies or involving is not None or near_block is not None:
        involving_virtual = (
            None if involving is None else _parse_virtual_reg_token(involving)
        )
        reports = list_copy_lifetimes(
            pcdump_text,
            function,
            involving=involving_virtual,
            near_block=near_block,
            reg_class=effective_class,
            source_text=source_text,
            source_file=source_label,
        )
        if json_out:
            print(json.dumps([report.to_dict() for report in reports], indent=2))
            return
        print(f"Function: {function}")
        print(f"Copies:   {len(reports)}")
        for report in reports:
            print(f"- r{report.to_virtual} <- r{report.from_virtual}")
            print(f"  status: {report.status}")
            print(f"  likely: {report.likely_cause}")
            if report.transform_category:
                print(f"  transform: {report.transform_category}")
            if report.first_copy is not None:
                occ = report.first_copy
                print(
                    "  first: "
                    f"{occ.pass_name} B{occ.block_idx}:{occ.instr_idx} "
                    f"{occ.opcode} {occ.operands}"
                )
            if report.last_copy is not None:
                occ = report.last_copy
                print(
                    "  last:  "
                    f"{occ.pass_name} B{occ.block_idx}:{occ.instr_idx} "
                    f"{occ.opcode} {occ.operands}"
                )
            if report.first_absent_pass is not None:
                print(f"  first absent: {report.first_absent_pass}")
            origin = report.to_mapping.call_return_origin
            if origin is not None:
                expr = origin.expression or f"{origin.call_symbol}(...)"
                loc = (
                    ""
                    if origin.source_file is None or origin.source_line is None
                    else f" {origin.source_file}:{origin.source_line}"
                )
                print(f"  source:{loc} {expr}")
        return

    if from_reg is None or to_reg is None:
        typer.echo(
            "--from and --to are required unless using --list-copies, "
            "--involving, or --near-block.",
            err=True,
        )
        raise typer.Exit(2)

    from_virtual = _parse_virtual_reg_token(from_reg)
    to_virtual = _parse_virtual_reg_token(to_reg)
    report = trace_copy_lifetime(
        pcdump_text,
        function,
        from_virtual=from_virtual,
        to_virtual=to_virtual,
        reg_class=effective_class,
        source_text=source_text,
        source_file=source_label,
    )

    if json_out:
        print(json.dumps(report.to_dict(), indent=2))
        return

    print(f"Function: {function}")
    print(f"Copy:     r{to_virtual} <- r{from_virtual}")
    print(f"Status:   {report.status}")
    print(f"Likely:   {report.likely_cause}")
    if report.transform_category:
        print(f"Transform: {report.transform_category}")
    if report.note:
        print(f"Note:     {report.note}")
    if report.first_copy is not None:
        occ = report.first_copy
        print(
            "First:    "
            f"{occ.pass_name} B{occ.block_idx}:{occ.instr_idx} "
            f"{occ.opcode} {occ.operands}"
        )
    if report.last_copy is not None:
        occ = report.last_copy
        print(
            "Last:     "
            f"{occ.pass_name} B{occ.block_idx}:{occ.instr_idx} "
            f"{occ.opcode} {occ.operands}"
        )
    if report.first_absent_pass is not None:
        print(f"Absent:   first absent in {report.first_absent_pass}")
    print()
    print("Source virtual:")
    print(f"  status: {report.from_mapping.status}")
    if report.from_mapping.ig_idx is not None:
        print(f"  ig_idx: {report.from_mapping.ig_idx}")
    if report.from_mapping.assigned_reg is not None:
        print(f"  phys:   r{report.from_mapping.assigned_reg}")
    if report.from_mapping.call_return_origin is not None:
        origin = report.from_mapping.call_return_origin
        expr = origin.expression or f"{origin.call_symbol}(...)"
        print(f"  source: {expr}")
    print("Destination virtual:")
    print(f"  status: {report.to_mapping.status}")
    if report.to_mapping.ig_idx is not None:
        print(f"  ig_idx: {report.to_mapping.ig_idx}")
    if report.to_mapping.assigned_reg is not None:
        print(f"  phys:   r{report.to_mapping.assigned_reg}")
    if report.to_mapping.call_return_origin is not None:
        origin = report.to_mapping.call_return_origin
        expr = origin.expression or f"{origin.call_symbol}(...)"
        print(f"  source: {expr}")


def _parse_virtual_csv(value: str) -> list[int]:
    out: list[int] = []
    for raw in value.split(","):
        token = raw.strip()
        if not token:
            continue
        out.append(_parse_virtual_reg_token(token))
    return out


def _parse_virtual_pair_csv(value: str) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for raw in value.split(","):
        token = raw.strip()
        if not token:
            continue
        sep = next((candidate for candidate in (":", "=", "/") if candidate in token), None)
        if sep is None:
            raise typer.BadParameter(
                f"invalid pair {token!r}; expected rA:rB, rA/rB, or rA=rB"
            )
        left, right = token.split(sep, 1)
        if not left.strip() or not right.strip():
            raise typer.BadParameter(
                f"invalid pair {token!r}; expected rA:rB, rA/rB, or rA=rB"
            )
        pairs.append((
            _parse_virtual_reg_token(left.strip()),
            _parse_virtual_reg_token(right.strip()),
        ))
    return pairs


def _parse_virtual_order_csv(value: str) -> list[tuple[int, int]]:
    orders: list[tuple[int, int]] = []
    for raw in value.split(","):
        token = raw.strip()
        if not token:
            continue
        if "<" in token:
            left, right = token.split("<", 1)
            first, second = left, right
        elif ">" in token:
            left, right = token.split(">", 1)
            first, second = right, left
        else:
            raise typer.BadParameter(
                f"invalid order {token!r}; expected rA<rB or rB>rA"
            )
        if not first.strip() or not second.strip():
            raise typer.BadParameter(
                f"invalid order {token!r}; expected rA<rB or rB>rA"
            )
        orders.append((
            _parse_virtual_reg_token(first.strip()),
            _parse_virtual_reg_token(second.strip()),
        ))
    return orders


def _parse_probe_provenance(value: str) -> dict:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"--probe-provenance must be a JSON object: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("--probe-provenance must be a JSON object")
    return payload


_ACTIVE_SOURCE_RESTORES: dict[Path, str] = {}
_SOURCE_RESTORE_SIGNAL_HANDLERS: dict[int, object] = {}


def _restore_source_snapshot(path: Path, original: str) -> str | None:
    try:
        path.write_text(original)
        restored = path.read_text()
    except Exception as exc:
        return f"failed to restore {path}: {type(exc).__name__}: {exc}"
    if restored != original:
        return f"failed to restore {path}: restored content hash mismatch"
    return None


def _restore_active_sources_for_signal(signum: int, _frame: object) -> None:
    errors: list[str] = []
    for path, original in list(_ACTIVE_SOURCE_RESTORES.items()):
        error = _restore_source_snapshot(path, original)
        if error:
            errors.append(error)
        else:
            _ACTIVE_SOURCE_RESTORES.pop(path, None)
    for error in errors:
        print(f"[source-restore] {error}", file=sys.stderr)
    if signum == signal.SIGINT:
        raise KeyboardInterrupt
    raise SystemExit(128 + signum)


def _ensure_source_restore_signal_handlers() -> None:
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        if signum in _SOURCE_RESTORE_SIGNAL_HANDLERS:
            continue
        _SOURCE_RESTORE_SIGNAL_HANDLERS[signum] = signal.getsignal(signum)
        signal.signal(signum, _restore_active_sources_for_signal)


def _register_active_source_restore(path: Path, original: str) -> None:
    _ensure_source_restore_signal_handlers()
    _ACTIVE_SOURCE_RESTORES.setdefault(path, original)


def _unregister_active_source_restore(path: Path) -> None:
    _ACTIVE_SOURCE_RESTORES.pop(path, None)


@dataclasses.dataclass(frozen=True)
class _SourceCandidateRealScore:
    match_percent: float | None
    match_percent_error: str | None
    stack_slot_localizer: dict | None = None
    stack_slot_error: str | None = None
    checkdiff_payload: dict | None = None


def _new_external_function_definitions(
    candidate_text: str,
    original_text: str,
    *,
    function: str,
) -> list[str]:
    candidate_names = {
        span.name for span in find_function_definitions(candidate_text)
    }
    original_names = {
        span.name for span in find_function_definitions(original_text)
    }
    return sorted(candidate_names - original_names - {function})


class _MalformedSourceCandidate(ValueError):
    def __init__(self, message: str, *, source_hunk: str | None = None):
        super().__init__(message)
        self.source_hunk = source_hunk


def _compact_source_hunk_for_function(
    source_text: str,
    function: str,
    *,
    context: int = 4,
    max_lines: int = 14,
) -> str:
    lines = source_text.splitlines()
    if not lines:
        return ""

    span = find_source_function(source_text, function)
    if span is not None:
        anchor_offset = span.sig_start
    else:
        match = re.search(rf"\b{re.escape(function)}\s*\(", source_text)
        if match is not None:
            anchor_offset = match.start()
        else:
            definitions = find_function_definitions(source_text)
            anchor_offset = definitions[0].sig_start if definitions else 0

    anchor_line = source_text[:anchor_offset].count("\n")
    start = max(0, anchor_line - context)
    end = min(len(lines), max(start + 1, anchor_line + max_lines - context))
    return "\n".join(f"{idx + 1}: {lines[idx]}" for idx in range(start, end))


def _prevalidate_lifetime_layout_source_candidate(
    path: Path,
    *,
    function: str,
) -> tuple[str, str | None]:
    source_text = path.read_text(encoding="utf-8", errors="replace")
    if find_source_function(source_text, function) is not None:
        return source_text, None

    names = [span.name for span in find_function_definitions(source_text)[:5]]
    suffix = f"; candidate defines: {', '.join(names)}" if names else ""
    raise _MalformedSourceCandidate(
        (
            f"target function {function} not found in candidate source before "
            f"compile: {path}{suffix}"
        ),
        source_hunk=_compact_source_hunk_for_function(source_text, function),
    )


def _kill_debug_dump_local_process_tree(proc_handle: subprocess.Popen[str]) -> None:
    _kill_process_tree(proc_handle.pid, proc_handle)


def _find_stack_slot_localizer_in_json(value: object) -> dict | None:
    if isinstance(value, dict):
        localizer = value.get("stack_slot_localizer")
        if isinstance(localizer, dict):
            return localizer
        for child in value.values():
            found = _find_stack_slot_localizer_in_json(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_stack_slot_localizer_in_json(child)
            if found is not None:
                return found
    return None


def _run_checkdiff_stack_slot_localizer(
    *,
    function: str,
    melee_root: Path,
    timeout: float | None = None,
) -> tuple[dict | None, str | None]:
    payload, error = _run_checkdiff_stack_slot_payload(
        function=function,
        melee_root=melee_root,
        timeout=timeout,
    )
    if error is not None:
        return None, error
    localizer = _find_stack_slot_localizer_in_json(payload)
    if localizer is not None:
        return localizer, None
    return None, None


def _run_checkdiff_stack_slot_payload(
    *,
    function: str,
    melee_root: Path,
    timeout: float | None = None,
) -> tuple[dict | None, str | None]:
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "tools/checkdiff.py",
                function,
                "--format",
                "json",
                "--no-build",
            ],
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, "checkdiff stack-slot localizer timed out"
    except Exception as exc:
        return None, f"checkdiff stack-slot localizer failed: {exc}"

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        detail = (proc.stderr or proc.stdout or str(exc)).strip()
        return None, f"checkdiff stack-slot analysis emitted non-json: {detail}"

    if proc.returncode not in (0, 1):
        detail = (proc.stderr or proc.stdout or "").strip()
        return None, (
            f"checkdiff stack-slot analysis failed with exit {proc.returncode}"
            + (f": {detail}" if detail else "")
        )
    return payload, None


@inspect_app.command(name="stack-homes")
def inspect_stack_homes(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    checkdiff_json: Annotated[
        Optional[Path],
        typer.Option(
            "--checkdiff-json",
            help=(
                "Existing checkdiff --format json output containing a "
                "stack_slot_localizer. If omitted, checkdiff is run with "
                "--no-build to get one."
            ),
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "C source file used for source/lifetime attribution. Defaults "
                "to the repo source for the function when available."
            ),
        ),
    ] = None,
    checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--checkdiff-timeout",
            help="Timeout in seconds when auto-running checkdiff.",
        ),
    ] = 60.0,
    score_sqrt_array_variants: Annotated[
        bool,
        typer.Option(
            "--score-sqrt-array-variants",
            help=(
                "Generate local-array sqrtf variants, compile them in the "
                "current tree, and rank target stack-slot movement before "
                "overall match percent."
            ),
        ),
    ] = False,
    max_variants: Annotated[
        int,
        typer.Option(
            "--max-variants",
            help="Maximum generated sqrt-array variants to score.",
        ),
    ] = 4,
    variant_timeout: Annotated[
        float,
        typer.Option(
            "--variant-timeout",
            help="Timeout in seconds for each generated variant build/score.",
        ),
    ] = 120.0,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Explain final-only FPR stack-home targets and source-shape leads."""
    from ..mwcc_debug.stack_home_explorer import (
        attach_variant_rankings,
        explore_stack_homes,
        generate_local_array_sqrt_variants,
        render_stack_home_report_text,
    )

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        melee_root,
        require_fresh=False,
    )

    if checkdiff_json is not None:
        if not checkdiff_json.is_file():
            raise typer.BadParameter(f"checkdiff JSON not found: {checkdiff_json}")
        try:
            checkdiff_payload = json.loads(checkdiff_json.read_text())
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(
                f"checkdiff JSON could not be parsed: {exc}"
            ) from exc
        localizer = _find_stack_slot_localizer_in_json(checkdiff_payload)
        if localizer is None:
            typer.echo(
                f"{checkdiff_json} did not contain stack_slot_localizer",
                err=True,
            )
            raise typer.Exit(3)
    else:
        localizer, error = _run_checkdiff_stack_slot_localizer(
            function=function,
            melee_root=melee_root,
            timeout=checkdiff_timeout,
        )
        if error is not None:
            typer.echo(error, err=True)
            raise typer.Exit(3)
        if localizer is None:
            typer.echo(
                "checkdiff did not report a stack_slot_localizer for "
                f"{function}",
                err=True,
            )
            raise typer.Exit(3)

    source_text = None
    source_label = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, melee_root)
        if unit is not None:
            candidate = melee_root / "src" / f"{unit}.c"
            if candidate.is_file():
                source_text = candidate.read_text()
                try:
                    source_label = str(candidate.relative_to(melee_root))
                except ValueError:
                    source_label = str(candidate)

    report = explore_stack_homes(
        pcdump_path.read_text(),
        function,
        localizer,
        source_text=source_text,
        source_file=source_label,
    )
    if score_sqrt_array_variants:
        if source_text is None:
            typer.echo(
                "--score-sqrt-array-variants requires source text; pass "
                "--source-file or rebuild report.json so the function source "
                "can be resolved.",
                err=True,
            )
            raise typer.Exit(2)
        variants = generate_local_array_sqrt_variants(
            source_text,
            function,
            max_variants=max_variants,
        )
        variant_results: list[dict] = []
        with tempfile.TemporaryDirectory(prefix="stack-home-variants-") as td:
            temp_dir = Path(td)
            for variant in variants:
                variant_id = variant["id"]
                candidate_path = temp_dir / f"{variant_id}.c"
                candidate_path.write_text(variant["candidate_source"])
                score = _score_source_candidate_real_tree(
                    candidate_path,
                    function=function,
                    melee_root=melee_root,
                    timeout=variant_timeout,
                    include_stack_slot=True,
                )
                variant_results.append({
                    "variant_id": variant_id,
                    "kind": variant["kind"],
                    "description": variant["description"],
                    "match_percent": score.match_percent,
                    "match_percent_error": score.match_percent_error,
                    "stack_slot_localizer": score.stack_slot_localizer,
                    "stack_slot_error": score.stack_slot_error,
                    "checkdiff_payload": getattr(score, "checkdiff_payload", None),
                    "source_patch": variant.get("source_patch"),
                })
        attach_variant_rankings(
            report,
            variant_results,
            source_text=source_text,
            function=function,
        )
    if json_out:
        print(json.dumps(report, indent=2))
    else:
        print(render_stack_home_report_text(report))


def _score_source_candidate_real_tree(
    path: Path,
    *,
    function: str,
    melee_root: Path,
    timeout: float | None = None,
    status: Callable[[str], None] | None = None,
    include_stack_slot: bool = False,
) -> _SourceCandidateRealScore:
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        return _SourceCandidateRealScore(
            None,
            f"function not found in report.json: {function}",
        )
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        return _SourceCandidateRealScore(
            None,
            f"target source not found: {target_path}",
        )
    if status is not None:
        status("waiting for source-scoring lock")
    with _acquire_source_score_repo_lock(melee_root):
        if status is not None:
            status("source-scoring lock acquired")
        candidate_text = path.read_text()
        original = target_path.read_text()
        external_helpers = _new_external_function_definitions(
            candidate_text,
            original,
            function=function,
        )
        if external_helpers:
            helper_list = ", ".join(external_helpers)
            return _SourceCandidateRealScore(
                None,
                (
                    f"candidate source defines helper function(s) outside "
                    f"{function}: {helper_list}. Source candidate scoring only "
                    f"transfers {function} into {target_path.relative_to(melee_root)}, "
                    "so those definitions would be dropped before the real-tree "
                    "build. Inline the helper into the target function or apply "
                    "the helper to the real source file before scoring."
                ),
            )
        obj_path = f"build/GALE01/src/{unit}.o"
        _register_active_source_restore(target_path, original)
        result: tuple[float | None, str | None] = (None, None)
        restore_error: str | None = None
        cleanup_error: str | None = None
        applied = False
        try:
            if status is not None:
                status(f"applying candidate to src/{unit}.c")
            if transfer_candidate(candidate_text, target_path, function) is None:
                result = (None, f"function not found in candidate source: {path}")
                return _SourceCandidateRealScore(*result)
            applied = True
            if status is not None:
                status(f"building {obj_path}")
            build_result, retried = _run_ninja_with_no_diag_retry(
                ["ninja", obj_path],
                melee_root,
                timeout=timeout,
            )
            if build_result.returncode != 0:
                result = (None, _failure_diagnostic_or_fallback(
                    build_result.stdout,
                    build_result.stderr,
                    fallback=(
                        f"ninja {obj_path} failed with exit {build_result.returncode}"
                        + (" after retry" if retried else "")
                    ),
                ))
                return _SourceCandidateRealScore(*result)
            if status is not None:
                status("build complete; refreshing report.json")
            result = _refresh_match_pct_after_successful_build(
                unit,
                function,
                melee_root,
                timeout=timeout,
            )
            stack_slot_localizer = None
            stack_slot_error = None
            checkdiff_payload = None
            if include_stack_slot:
                if status is not None:
                    status("running checkdiff stack-slot localizer")
                checkdiff_payload, stack_slot_error = (
                    _run_checkdiff_stack_slot_payload(
                        function=function,
                        melee_root=melee_root,
                        timeout=timeout,
                    )
                )
                if checkdiff_payload is not None:
                    stack_slot_localizer = _find_stack_slot_localizer_in_json(
                        checkdiff_payload
                    )
            if status is not None:
                status("match-percent refresh complete")
            return _SourceCandidateRealScore(
                result[0],
                result[1],
                stack_slot_localizer,
                stack_slot_error,
                checkdiff_payload,
            )
        finally:
            if applied:
                if status is not None:
                    status("restoring source")
                restore_error = _restore_source_snapshot(target_path, original)
            _unregister_active_source_restore(target_path)
            if restore_error:
                print(f"[source-restore] {restore_error}", file=sys.stderr)
            elif applied:
                try:
                    if status is not None:
                        status(
                            f"cleanup rebuild {obj_path} build/GALE01/report.json"
                        )
                    subprocess.run(
                        ["ninja", obj_path, "build/GALE01/report.json"],
                        cwd=melee_root,
                        capture_output=True,
                        timeout=timeout,
                    )
                except subprocess.TimeoutExpired:
                    cleanup_error = (
                        f"timed out restoring object/report after source restore: "
                        f"ninja {obj_path} build/GALE01/report.json"
                    )
                except Exception:
                    cleanup_error = (
                        "failed to rebuild object/report after source restore"
                    )
                if cleanup_error is None and status is not None:
                    status("cleanup rebuild complete")
            if restore_error:
                raise RuntimeError(restore_error)
            if cleanup_error:
                raise RuntimeError(cleanup_error)


def _select_order_source_match_percent(
    path: Path,
    *,
    function: str,
    melee_root: Path,
    timeout: float | None = None,
    status: Callable[[str], None] | None = None,
) -> tuple[float | None, str | None]:
    score = _score_source_candidate_real_tree(
        path,
        function=function,
        melee_root=melee_root,
        timeout=timeout,
        status=status,
    )
    return score.match_percent, score.match_percent_error


def _select_order_source_fingerprints(
    *,
    base_source: str,
    candidate_source: str,
    function: str,
) -> tuple[str, str]:
    candidate_function = extract_function(candidate_source, function)
    body_basis = candidate_function if candidate_function is not None else candidate_source
    body_hash = hashlib.sha256(body_basis.encode("utf-8")).hexdigest()[:16]
    base_function = extract_function(base_source, function) or base_source
    diff_text = "\n".join(difflib.unified_diff(
        base_function.splitlines(),
        body_basis.splitlines(),
        lineterm="",
    ))
    diff_hash = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()[:16]
    return body_hash, diff_hash


def _select_order_real_score_sort_key(variant: dict) -> tuple[float, ...]:
    if variant.get("status") != "ok":
        return (-1.0,)
    objective = variant.get("objective") or {}
    match = objective.get("match_percent")
    match_score = float(match) if isinstance(match, (int, float)) else -1.0
    sort_key = objective.get("sort_key") or ()
    if isinstance(sort_key, list):
        objective_key = tuple(float(item) for item in sort_key)
    elif isinstance(sort_key, tuple):
        objective_key = tuple(float(item) for item in sort_key)
    else:
        objective_key = ()
    return (1.0, match_score, *objective_key)


def _rank_select_order_candidates_real_first(
    variants: list[dict],
) -> list[dict]:
    ranked = [dict(variant) for variant in variants]
    ranked.sort(key=_select_order_real_score_sort_key, reverse=True)
    for idx, variant in enumerate(ranked, start=1):
        variant["rank"] = idx
    return ranked


def _select_order_safe_label(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return cleaned[:80] or "candidate"


@inspect_app.command(name="explain-virtual")
def inspect_explain_virtual(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    virtuals: Annotated[
        str,
        typer.Option(
            "--virtuals",
            help="Comma-separated virtual registers to explain, e.g. r37,r40.",
        ),
    ] = "",
    pairs: Annotated[
        str,
        typer.Option(
            "--pairs",
            help=(
                "Comma-separated virtual pairs to explain, e.g. "
                "r37/r40,r43/r33."
            ),
        ),
    ] = "",
    all_virtuals: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Explain every virtual register observed in pre-coloring pcode.",
        ),
    ] = False,
    reg_class: Annotated[
        Optional[str],
        typer.Option(
            "--class",
            help="Register class for allocator lookup (gpr/int or fp/fpr).",
        ),
    ] = "gpr",
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Path to pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "C source file used for source/interference attribution. "
                "Defaults to the repo source for the function when available."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Explain virtual-register source/interference attribution."""
    from ..mwcc_debug.virtual_attribution import (
        explain_virtuals,
        list_pcode_virtuals,
        render_virtual_attribution_text,
    )

    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=False,
    )
    source_text = None
    source_label = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            candidate = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if candidate.is_file():
                source_text = candidate.read_text()
                try:
                    source_label = str(candidate.relative_to(DEFAULT_MELEE_ROOT))
                except ValueError:
                    source_label = str(candidate)

    pcdump_text = pcdump_path.read_text()
    virtual_list = _parse_virtual_csv(virtuals)
    pair_list = _parse_virtual_pair_csv(pairs)
    if all_virtuals:
        virtual_list = list(list_pcode_virtuals(pcdump_text, function))
    if not virtual_list and not pair_list:
        typer.echo("--virtuals, --pairs, or --all is required.", err=True)
        raise typer.Exit(2)

    report = explain_virtuals(
        pcdump_text,
        function,
        virtuals=virtual_list,
        pairs=pair_list,
        source_text=source_text,
        source_file=source_label,
        reg_class=reg_class,
    )
    if json_out:
        print(json.dumps(report.to_dict(), indent=2))
        return
    print(render_virtual_attribution_text(report))


@inspect_app.command(name="explain-schedule")
def inspect_explain_schedule(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    force_schedule: Annotated[
        str,
        typer.Option(
            "--force-schedule",
            help=(
                "Target scheduler swap list to explain, e.g. "
                "'lwz:0x94>0x90,lwz:0xAC>0xA8'."
            ),
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Path to pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "C source file used for advisory IR/source provenance. "
                "Defaults to the repo source for the function when available."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Explain observed scheduler windows for known force-schedule targets."""
    from ..mwcc_debug.schedule_explain import (
        explain_schedule,
        render_json,
        render_text,
    )

    force_schedule = _validate_force_schedule(force_schedule)
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=False,
    )
    source_text = None
    source_label = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            candidate = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if candidate.is_file():
                source_text = candidate.read_text()
                try:
                    source_label = str(candidate.relative_to(DEFAULT_MELEE_ROOT))
                except ValueError:
                    source_label = str(candidate)
    report = explain_schedule(
        pcdump_path.read_text(),
        function=function,
        force_schedule=force_schedule,
        source_text=source_text,
        source_file=source_label,
    )
    print(render_json(report) if json_out else render_text(report))


@debug_app.command(name="diff-schedule")
def debug_diff_schedule(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    force_schedule: Annotated[
        str,
        typer.Option(
            "--force-schedule",
            help=(
                "Target scheduler swap list to compare, e.g. "
                "'lwz:0x94>0x90,lwz:0xAC>0xA8'."
            ),
        ),
    ],
    against: Annotated[
        Path,
        typer.Option(
            "--against",
            help="Forced-path pcdump.txt to compare against the real path.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Real-path pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "C source file used for advisory IR/source provenance. "
                "Defaults to the repo source for the function when available."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Diff real vs forced scheduler-window decisions."""
    from ..mwcc_debug.schedule_explain import (
        diff_schedule,
        render_diff_json,
        render_diff_text,
    )

    force_schedule = _validate_force_schedule(force_schedule)
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=False,
    )
    if not against.is_file():
        raise typer.BadParameter(f"forced-path pcdump not found: {against}")
    source_text = None
    source_label = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            candidate = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if candidate.is_file():
                source_text = candidate.read_text()
                try:
                    source_label = str(candidate.relative_to(DEFAULT_MELEE_ROOT))
                except ValueError:
                    source_label = str(candidate)
    report = diff_schedule(
        pcdump_path.read_text(),
        against.read_text(),
        function=function,
        force_schedule=force_schedule,
        source_text=source_text,
        source_file=source_label,
    )
    print(render_diff_json(report) if json_out else render_diff_text(report))


def _normalize_virtual_to_var_reg_class(value: str) -> str:
    key = value.strip().lower()
    if key in {"gpr", "int", "r", "0"}:
        return "gpr"
    if key in {"fpr", "fp", "float", "f", "1"}:
        return "fpr"
    raise typer.BadParameter(
        f"unknown register class {value!r}; expected gpr/r/0 or fpr/f/1"
    )


@inspect_app.command(name="virtual-to-var")
def virtual_to_var(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to look up (required).",
        ),
    ],
    virtual: Annotated[
        str,
        typer.Argument(
            help="Virtual register number (32+) or ig_idx. Accepts "
                 "'62' or 'r62' — the 'r' prefix is stripped so you "
                 "can copy-paste straight from analyze/guide output.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Auto-resolves from cache.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
    reg_class: Annotated[
        Optional[str],
        typer.Option(
            "--class",
            help="Register class for the inverse lookup: gpr/r/0 or fpr/f/1. "
                 "When omitted, infer from an r*/f* virtual token and "
                 "default to GPR for bare numbers.",
        ),
    ] = None,
) -> None:
    """Bridge inverse: given a virtual register, predict the source
    variable name (decl-order heuristic), including the variable's
    scope path (function-top vs nested-block). When no source variable
    binds to the requested virtual (compiler-introduced temps, spill
    nodes, etc.), falls back to showing the first defining IR op
    so you can correlate to the C source manually.
    """
    from ..mwcc_debug.symbol_bridge import (
        find_first_def,
        find_var_for_virtual,
    )

    # Accept 'r62' and 'f42' alongside bare numbers — easier to copy from
    # analyze/guide/explain output while preserving the old bare-GPR default.
    vstr = virtual.strip()
    inferred_class = None
    if vstr.lower().startswith("f"):
        inferred_class = "fpr"
        vstr = vstr[1:]
    elif vstr.lower().startswith("r"):
        inferred_class = "gpr"
        vstr = vstr[1:]
    try:
        virtual_int = int(vstr)
    except ValueError:
        typer.echo(
            f"invalid virtual register {virtual!r}; expected an integer "
            f"(optionally with 'r' or 'f' prefix).", err=True,
        )
        raise typer.Exit(2)
    virtual = virtual_int  # downstream code uses int form
    reg_class = _normalize_virtual_to_var_reg_class(
        reg_class or inferred_class or "gpr"
    )
    reg_kind = "f" if reg_class == "fpr" else "r"

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    text = pcdump_path.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre = fn.last_precolor_pass()
    if pre is None:
        typer.echo(
            f"no pre-coloring pass for {function}", err=True,
        )
        raise typer.Exit(3)

    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    source_path = melee_root / "src" / f"{unit}.c"
    source = source_path.read_text()
    try:
        source_label = str(source_path.relative_to(melee_root))
    except ValueError:
        source_label = str(source_path)
    if reg_class == "fpr":
        from ..mwcc_debug.virtual_attribution import explain_virtuals
        report = explain_virtuals(
            text,
            function,
            virtuals=[virtual],
            source_text=source,
            source_file=source_label,
            reg_class=reg_class,
        )
        entry = report.virtuals[0]
        source_info = entry.source
        first = (
            source_info.first_def
            if source_info is not None and source_info.first_def is not None
            else entry.first_occurrence
        )
        assigned = (
            None
            if entry.assigned_reg is None
            else f"{reg_kind}{entry.assigned_reg}"
        )
        if json_out:
            payload = {
                "virtual": virtual,
                "register_class": reg_class,
                "class_id": entry.class_id,
                "ig_idx": entry.ig_idx,
                "assigned_reg": assigned,
                "status": entry.status,
                "found": False,
                "source": (
                    None if source_info is None else dataclasses.asdict(source_info)
                ),
                "first_def": None if first is None else dataclasses.asdict(first),
            }
            print(json.dumps(payload, indent=2))
        else:
            typer.echo(
                f"no source variable bound to {reg_kind}{virtual} in {function} "
                "(likely an FPR compiler-introduced temp or spill root).",
                err=True,
            )
            if first is not None:
                typer.echo("", err=True)
                typer.echo("first defining FPR op:", err=True)
                typer.echo(
                    f"  block {first.block_idx}: {first.opcode} {first.operands}",
                    err=True,
                )
            if assigned is not None:
                typer.echo(f"assigned physical: {assigned}", err=True)
        return

    binding = find_var_for_virtual(source, function, virtual, pre)

    if binding is None:
        call_return_source = _virtual_to_var_call_return_source(
            text,
            function=function,
            virtual=virtual,
            source_text=source,
            source_file=source_label,
        )
        if call_return_source is not None:
            if json_out:
                payload = {
                    "virtual": virtual,
                    "found": False,
                    "source": dataclasses.asdict(call_return_source),
                }
                print(json.dumps(payload, indent=2))
            else:
                print(
                    _render_virtual_to_var_call_return_source(
                        virtual,
                        function=function,
                        source=call_return_source,
                    )
                )
            return

        # Fallback: no source variable mapped (compiler temp, spill,
        # post-CSE intermediate, etc.). Surface the first-def IR op so
        # the agent can correlate to a C expression manually — e.g.,
        # `lwz r62, 44(r34)` means "r62 is something->field_at_0x2C
        # where something is in r34".
        first = find_first_def(virtual, pre)
        if json_out:
            payload: dict = {
                "virtual": virtual,
                "found": False,
            }
            if first is not None:
                payload["first_def"] = {
                    "block_idx": first.block_idx,
                    "opcode": first.opcode,
                    "operands": first.operands,
                    "annotations": first.annotations,
                }
            print(json.dumps(payload, indent=2))
        else:
            typer.echo(
                f"no source variable bound to r{virtual} in {function} "
                f"(likely a compiler-introduced temp — spill, CSE, or IV).",
                err=True,
            )
            if first is not None:
                typer.echo("", err=True)
                typer.echo("first defining op (in pre-coloring pass):", err=True)
                typer.echo(
                    f"  block {first.block_idx}: {first.opcode} {first.operands}",
                    err=True,
                )
                if first.annotations:
                    for a in first.annotations:
                        typer.echo(f"    {a}", err=True)
                typer.echo("", err=True)
                typer.echo(
                    "Hint: correlate the load address/offset back to a C "
                    "struct field, or trace the source register(s) to find "
                    "the originating expression.",
                    err=True,
                )
        return

    if json_out:
        from ..mwcc_debug.scope_path import format_for_display
        payload: dict = {
            "var_name": binding.var_name,
            "virtual": binding.virtual,
            "kind": binding.kind,
            "type": binding.type_str,
            "confidence": binding.confidence,
            "scope_path": list(binding.scope_path),
            "found": True,
        }
        print(json.dumps(payload, indent=2))
    else:
        from ..mwcc_debug.scope_path import format_for_display
        scope_str = format_for_display(binding.scope_path) if binding.scope_path else ""
        scope_suffix = f"  scope: {scope_str}" if scope_str else ""
        print(f"r{virtual}: {binding.var_name} ({binding.kind})")
        print(f"  type:    {binding.type_str}")
        print(f"  conf:    {binding.confidence}")
        if scope_suffix:
            print(scope_suffix)


def _virtual_to_var_call_return_source(
    pcdump_text: str,
    *,
    function: str,
    virtual: int,
    source_text: str,
    source_file: str,
):
    try:
        from ..mwcc_debug.virtual_attribution import explain_virtuals
        report = explain_virtuals(
            pcdump_text,
            function,
            virtuals=[virtual],
            source_text=source_text,
            source_file=source_file,
        )
    except Exception:
        return None
    entry = next(
        (candidate for candidate in report.virtuals if candidate.virtual == virtual),
        None,
    )
    source = None if entry is None else entry.source
    if source is None or source.kind != "call-return":
        return None
    return source


def _render_virtual_to_var_call_return_source(
    virtual: int,
    *,
    function: str,
    source,
) -> str:
    loc = ""
    if source.source_file and source.source_line is not None:
        loc = f" {source.source_file}:{source.source_line}"
        if source.source_col is not None:
            loc += f":{source.source_col}"
    expr = source.expression or source.call_symbol or "call return"
    name_suffix = f" -> {source.name}" if source.name else ""
    lines = [
        f"r{virtual}: {expr}{name_suffix} "
        f"(call-return/copy-chain){loc}",
        (
            "  note:   no declared local is bound directly to "
            f"r{virtual} in {function}; this virtual carries a copied "
            "call return."
        ),
    ]
    if source.call_symbol:
        lines.append(f"  callee: {source.call_symbol}")
    if source.first_def is not None:
        site = source.first_def
        lines.append(
            "  call:   "
            f"{site.pass_name} B{site.block_idx}:{site.instr_idx} "
            f"{site.opcode} {site.operands}"
        )
    if source.copy_chain:
        chain = " <- ".join(f"r{reg}" for reg in source.copy_chain)
        lines.append(f"  chain:  {chain}")
    if source.use_sites:
        for site in source.use_sites[:3]:
            lines.append(
                "  use:    "
                f"{site.pass_name} B{site.block_idx}:{site.instr_idx} "
                f"{site.opcode} {site.operands}"
            )
    return "\n".join(lines)


def _read_source_for(function: str, melee_root: Path) -> tuple[Path, str]:
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    p = melee_root / "src" / f"{unit}.c"
    return p, p.read_text()


@intervene_app.command(name="coalesce")
def intervene_coalesce_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to scope the backend coalesce intervention to.",
        ),
    ],
    force: Annotated[
        Optional[str],
        typer.Option(
            "--force",
            help="Force one coalesce pair, e.g. r43=r40.",
        ),
    ] = None,
    block: Annotated[
        Optional[str],
        typer.Option(
            "--block",
            help="Block one natural coalesce pair by un-coalescing the left "
                 "virtual, e.g. r43=r40 emits MWCC_DEBUG_FORCE_COALESCE=43=43.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file to compile when pcdumps are not both supplied.",
        ),
    ] = None,
    baseline_pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--baseline-pcdump",
            help="Existing natural pcdump. If omitted, compile --source-file.",
        ),
    ] = None,
    intervention_pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--intervention-pcdump",
            help="Existing forced pcdump. If omitted, compile --source-file "
                 "with the backend coalesce hook.",
        ),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Compile path for missing pcdumps: local or remote.",
        ),
    ] = "local",
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output-dir",
            help="Directory for generated baseline/intervention pcdumps.",
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Per-dump compile timeout in seconds.",
        ),
    ] = 120,
    host: Annotated[
        str,
        typer.Option(
            "--host",
            help="Remote host when --mode remote is used.",
            envvar="MWCC_DEBUG_HOST",
        ),
    ] = "nzxt-local",
    no_pull: Annotated[
        bool,
        typer.Option(
            "--no-pull",
            help="Forward --no-pull to debug dump remote.",
        ),
    ] = False,
    baseline_match_percent: Annotated[
        Optional[float],
        typer.Option(
            "--baseline-match-percent",
            help="Optional externally measured baseline real match percent.",
        ),
    ] = None,
    intervention_match_percent: Annotated[
        Optional[float],
        typer.Option(
            "--intervention-match-percent",
            help="Optional externally measured intervention real match percent.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Run/report a scoped coalesce intervention backed by the mwcc_debug DLL.

    The implemented block slice uses the existing backend hook:
    `MWCC_DEBUG_FORCE_COALESCE=virt=virt`. That value is passed through
    `debug dump local|remote --force-coalesce ... --force-coalesce-fn FN`,
    so the compiler/DLL, not this wrapper, changes allocator state.
    """
    from ..mwcc_debug.allocator_intervention import (
        CoalesceInterventionSpec,
        analyze_coalesce_intervention,
        parse_coalesce_pair,
        render_coalesce_intervention_text,
    )

    if bool(force) == bool(block):
        typer.echo("provide exactly one of --force or --block.", err=True)
        raise typer.Exit(2)
    if mode not in {"local", "remote"}:
        typer.echo("--mode must be either local or remote.", err=True)
        raise typer.Exit(2)

    raw_pair = force if force is not None else block
    assert raw_pair is not None
    try:
        virt, root = parse_coalesce_pair(raw_pair)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)
    spec = CoalesceInterventionSpec(
        action="force" if force is not None else "block",
        virt=virt,
        root=root,
    )

    if baseline_pcdump is not None and not baseline_pcdump.is_file():
        raise typer.BadParameter(f"baseline pcdump not found: {baseline_pcdump}")
    if intervention_pcdump is not None and not intervention_pcdump.is_file():
        raise typer.BadParameter(
            f"intervention pcdump not found: {intervention_pcdump}"
        )

    if baseline_pcdump is None or intervention_pcdump is None:
        if source_file is None:
            typer.echo(
                "--source-file is required when either pcdump is omitted.",
                err=True,
            )
            raise typer.Exit(2)
        source_file = _resolve_existing_cli_file(
            source_file,
            melee_root=DEFAULT_MELEE_ROOT,
            label="source file",
        )
        run_dir = output_dir or Path(tempfile.mkdtemp(prefix="melee_intervene_"))
        run_dir.mkdir(parents=True, exist_ok=True)
        if baseline_pcdump is None:
            baseline_pcdump = run_dir / f"{function}.baseline.pcdump.txt"
            _run_intervention_dump(
                label="baseline",
                source_file=source_file,
                output=baseline_pcdump,
                function=function,
                mode=mode,
                timeout=timeout,
                host=host,
                no_pull=no_pull,
                spec=None,
            )
        if intervention_pcdump is None:
            intervention_pcdump = run_dir / f"{function}.coalesce-intervention.pcdump.txt"
            _run_intervention_dump(
                label="intervention",
                source_file=source_file,
                output=intervention_pcdump,
                function=function,
                mode=mode,
                timeout=timeout,
                host=host,
                no_pull=no_pull,
                spec=spec,
            )

    assert baseline_pcdump is not None
    assert intervention_pcdump is not None
    try:
        report = analyze_coalesce_intervention(
            baseline_pcdump.read_text(encoding="utf-8", errors="replace"),
            intervention_pcdump.read_text(encoding="utf-8", errors="replace"),
            function=function,
            spec=spec,
            baseline_match_percent=baseline_match_percent,
            intervention_match_percent=intervention_match_percent,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)
    if json_out:
        print(json.dumps(report.to_dict(), indent=2))
        return
    print(render_coalesce_intervention_text(report))
    print(f"baseline pcdump: {baseline_pcdump}")
    print(f"intervention pcdump: {intervention_pcdump}")


def _run_intervention_dump(
    *,
    label: str,
    source_file: Path,
    output: Path,
    function: str,
    mode: str,
    timeout: int,
    host: str,
    no_pull: bool,
    spec,
) -> None:
    cmd = [
        "python",
        "-m",
        "src.cli",
        "debug",
        "dump",
        mode,
        str(source_file),
        "--output",
        str(output),
    ]
    env = os.environ.copy()
    if mode == "local":
        cmd.extend(["--no-cache-sync", "--function", function])
        env["MWCC_DEBUG_HANG_TIMEOUT"] = str(timeout)
    else:
        cmd.extend(["--timeout", str(timeout)])
        cmd.extend(["--host", host])
        if no_pull:
            cmd.append("--no-pull")
    if spec is not None:
        cmd.extend([
            "--force-coalesce",
            spec.backend_value,
            "--force-coalesce-fn",
            function,
        ])

    proc = subprocess.run(
        cmd,
        cwd=DEFAULT_MELEE_ROOT / "tools" / "melee-agent",
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        env_hint = ""
        if spec is not None:
            env_hint = (
                " ("
                + " ".join(f"{key}={value}" for key, value in spec.backend_env.items())
                + ")"
            )
        typer.echo(f"{label} compile failed{env_hint}", err=True)
        if proc.stderr:
            typer.echo(proc.stderr, err=True, nl=False)
        if proc.stdout:
            typer.echo(proc.stdout, err=True, nl=False)
        raise typer.Exit(proc.returncode)
    if not output.exists():
        typer.echo(f"{label} compile completed without writing {output}", err=True)
        raise typer.Exit(4)


@mutate_app.command(name="type-change")
def mutate_type_change_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function containing the variable.",
        ),
    ],
    var: Annotated[
        str,
        typer.Option("--var", help="Local variable name to retype."),
    ],
    new_type: Annotated[
        str,
        typer.Option("--type", help="New type string (e.g., 'u32')."),
    ],
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file to mutate instead of resolving from report.json.",
        ),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Write the mutated source back to the file. "
                 "Default: print to stdout.",
        ),
    ] = False,
    diff: Annotated[
        bool,
        typer.Option("--diff", help="Print a focused unified diff instead of the full mutated source."),
    ] = False,
) -> None:
    """Change a local variable's declared type."""
    from ..mwcc_debug.mutators import MutationUnsupported, mutate_type_change

    melee_root = DEFAULT_MELEE_ROOT
    if source_file is not None:
        src_path = _resolve_existing_cli_file(
            source_file,
            melee_root=melee_root,
            label="source file",
        )
        source = src_path.read_text()
    else:
        src_path, source = _read_source_for(function, melee_root)
    try:
        out = mutate_type_change(source, function, var, new_type)
    except MutationUnsupported as e:
        typer.echo(f"mutation failed: {e}", err=True)
        raise typer.Exit(2)
    if apply:
        src_path.write_text(out)
        typer.echo(f"wrote: {src_path}", err=True)
    elif diff:
        print(
            _format_source_diff(
                source,
                out,
                fromfile=str(src_path),
                tofile=f"{src_path} (mutated)",
            ),
            end="",
        )
    else:
        print(out, end="")


@mutate_app.command(name="insert-alias")
def mutate_insert_alias_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function containing the variable.",
        ),
    ],
    var: Annotated[
        str,
        typer.Option("--var", help="Local variable name to alias."),
    ],
    at: Annotated[
        int,
        typer.Option(
            "--at",
            help="0-indexed N-th reading statement to alias before.",
        ),
    ] = 0,
    new_name: Annotated[
        Optional[str],
        typer.Option(
            "--name",
            help="Alias variable name (default: <var>_alias).",
        ),
    ] = None,
    scope: Annotated[
        Optional[str],
        typer.Option(
            "--scope",
            help="Optional exact scope_path display string, e.g. "
                 "fn/block@l10c4. Use var-to-virtual --all to inspect.",
        ),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Write the mutated source back to the file. "
                 "Default: print to stdout.",
        ),
    ] = False,
    diff: Annotated[
        bool,
        typer.Option("--diff", help="Print a focused unified diff instead of the full mutated source."),
    ] = False,
) -> None:
    """Insert a fresh local copy of a variable before the N-th
    reading statement and rewrite that statement to use the alias."""
    from ..mwcc_debug.mutators import (
        MutationUnsupported, mutate_insert_alias_before_use,
    )

    melee_root = DEFAULT_MELEE_ROOT
    src_path, source = _read_source_for(function, melee_root)
    parsed_scope = tuple(scope.split("/")) if scope else None
    try:
        out = mutate_insert_alias_before_use(
            source,
            function,
            var,
            at_stmt_index=at,
            new_name=new_name,
            scope_filter=parsed_scope,
        )
    except MutationUnsupported as e:
        typer.echo(f"mutation failed: {e}", err=True)
        raise typer.Exit(2)
    if apply:
        src_path.write_text(out)
        typer.echo(f"wrote: {src_path}", err=True)
    elif diff:
        print(
            _format_source_diff(
                source,
                out,
                fromfile=str(src_path),
                tofile=f"{src_path} (mutated)",
            ),
            end="",
        )
    else:
        print(out, end="")


def _parse_lifetime_layout_candidate(spec: str) -> tuple[str, str, Path]:
    if "=" not in spec:
        raise typer.BadParameter(
            f"invalid candidate {spec!r}; expected OPERATOR=path or LABEL:OPERATOR=path"
        )
    left, raw_path = spec.split("=", 1)
    if not left.strip() or not raw_path.strip():
        raise typer.BadParameter(
            f"invalid candidate {spec!r}; expected OPERATOR=path or LABEL:OPERATOR=path"
        )
    if ":" in left:
        label, operator = left.split(":", 1)
    else:
        label = left
        operator = left
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        raise typer.BadParameter(f"candidate path not found: {path}")
    return label.strip(), operator.strip(), path


def _make_real_score_status(command: str, label: str) -> Callable[[str], None]:
    def _status(message: str) -> None:
        print(f"[{command}] {label}: {message}", file=sys.stderr, flush=True)

    return _status


_LIFETIME_LAYOUT_RANKING = (
    "lifetime-layout pressure objective, final match percent tiebreaker"
)

_LIFETIME_LAYOUT_FOCUSES: dict[str, tuple[str, ...]] = {
    "b4-tree-loop": (
        "declaration-order",
        "indexed-pointer-loop",
        "loop-counter-hoist",
        "loop-counter-type",
        "pointer-base-call-loop",
        "pointer-walk-loop",
    ),
}


def _resolve_lifetime_layout_operator_filter(
    *,
    focus: str | None,
    operators: list[str] | None,
) -> tuple[str, ...] | None:
    selected: list[str] = []
    if focus:
        try:
            selected.extend(_LIFETIME_LAYOUT_FOCUSES[focus])
        except KeyError as exc:
            choices = ", ".join(sorted(_LIFETIME_LAYOUT_FOCUSES))
            raise typer.BadParameter(
                f"unknown focus {focus!r}; choices: {choices}"
            ) from exc
    for operator in operators or []:
        for item in operator.split(","):
            item = item.strip()
            if item:
                selected.append(item)
    if not selected:
        return None
    return tuple(dict.fromkeys(selected))


def _score_lifetime_layout_objective(
    delta,
    *,
    target_pairs: list[tuple[int, int]] | tuple[tuple[int, int], ...],
    match_percent: float | None = None,
    stack_slot_localizer: dict | None = None,
) -> dict[str, Any]:
    has_target_pairs = bool(target_pairs)
    target_virtuals = {
        virtual for pair in target_pairs for virtual in pair
    }
    target_spill_removed = tuple(
        sorted(virtual for virtual in delta.spill_removed if virtual in target_virtuals)
    )
    frame_gain = (
        -delta.frame_delta
        if delta.frame_delta is not None and delta.frame_delta < 0
        else 0
    )

    reasons: list[str] = []
    regressions: list[str] = []
    topology_changes: list[str] = []
    if frame_gain:
        reasons.append("frame_reduced")
    elif delta.frame_delta is not None and delta.frame_delta > 0:
        regressions.append("frame_grew")
    if target_spill_removed:
        reasons.append("target_spill_removed")
    elif delta.spill_removed:
        reasons.append("spill_removed")
    if delta.spill_added:
        regressions.append("spill_added")
    if delta.interference_removed:
        if has_target_pairs:
            reasons.append("interference_removed")
        else:
            topology_changes.append("interference_removed")
    if delta.interference_added:
        regressions.append("interference_added")
    if delta.coalesce_added:
        reasons.append("coalesce_added")
    if delta.coalesce_removed:
        regressions.append("coalesce_removed")

    if reasons:
        actionability = "improved"
    elif regressions:
        actionability = "regressed"
    else:
        actionability = "neutral"

    stack_slot_mismatch_count = None
    if stack_slot_localizer is not None:
        raw_count = stack_slot_localizer.get("mismatch_count")
        if isinstance(raw_count, int):
            stack_slot_mismatch_count = raw_count

    match_score = match_percent if match_percent is not None else -1.0
    interference_removed_score = (
        len(delta.interference_removed) if has_target_pairs else 0
    )
    sort_key = (
        float(actionability == "improved"),
        float(len(target_spill_removed)),
        float(len(delta.spill_removed)),
        float(interference_removed_score),
        float(len(delta.coalesce_added)),
        float(frame_gain),
        float(match_score),
        -float(len(delta.spill_added)),
        -float(len(delta.interference_added)),
        -float(len(delta.coalesce_removed)),
    )
    return {
        "target_pairs": [list(pair) for pair in target_pairs],
        "frame_delta": delta.frame_delta,
        "frame_before": delta.frame_before,
        "frame_after": delta.frame_after,
        "saved_removed": list(delta.saved_removed),
        "saved_added": list(delta.saved_added),
        "target_spill_removed": list(target_spill_removed),
        "spill_removed": list(delta.spill_removed),
        "spill_added": list(delta.spill_added),
        "interference_removed_count": len(delta.interference_removed),
        "interference_added_count": len(delta.interference_added),
        "coalesce_added_count": len(delta.coalesce_added),
        "coalesce_removed_count": len(delta.coalesce_removed),
        "match_percent": match_percent,
        "opcode_shape_preserved": None,
        "stack_slot_mismatch_count": stack_slot_mismatch_count,
        "actionability": actionability,
        "actionability_reasons": reasons,
        "actionability_regressions": regressions,
        "topology_changes": topology_changes,
        "sort_key": list(sort_key),
    }


def _rank_lifetime_layout_candidates(
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ranked = [dict(variant) for variant in variants]
    ranked.sort(key=_lifetime_layout_variant_sort_key, reverse=True)
    for idx, variant in enumerate(ranked, start=1):
        variant["rank"] = idx
    return ranked


def _lifetime_layout_variant_sort_key(variant: dict[str, Any]) -> tuple[float, ...]:
    if variant.get("status") != "ok":
        return (-1.0,)
    objective = variant.get("objective") or {}
    sort_key = objective.get("sort_key")
    if isinstance(sort_key, list):
        return tuple(float(item) for item in sort_key)
    if isinstance(sort_key, tuple):
        return tuple(float(item) for item in sort_key)
    return (0.0,)


_FRAME_TRANSFORM_RANKING = (
    "expected frame-size objective, final match percent tiebreaker"
)

_FRAME_DIRECTED_DEFAULT_OPERATORS = (
    "frame-local-dematerialize",
    "frame-direct-literal-at-final-fp-call",
    "frame-split-fp-const-lifetime",
    "frame-magic-scratch-relocation",
    "declaration-use-distance",
    "block-scope",
    "call-argument-tempization",
    "frame-reservation-pad-stack",
)


def _frame_transform_probe_plan(report: Mapping[str, Any]) -> dict[str, Any]:
    first_divergence = report.get("frame_first_divergence")
    if isinstance(first_divergence, Mapping):
        plan = first_divergence.get("frame_transform_probe_plan")
        if isinstance(plan, Mapping):
            return dict(plan)
    return {
        "status": "ready",
        "objective": "reduce current-vs-expected stack frame-size delta",
        "operator_priority": list(_FRAME_DIRECTED_DEFAULT_OPERATORS),
        "suggested_commands": [],
    }


def _frame_transform_semantic_lever_status(
    *,
    source_text: str | None,
    operator_filter: tuple[str, ...],
    frame_reservation_delta: int | None,
    probes: list[Any],
    scan_status: Mapping[str, Any] | None,
) -> dict:
    operator = "frame-local-dematerialize"
    if frame_reservation_delta is None or frame_reservation_delta >= 0:
        return {"status": "not-needed", "operator": operator}
    if source_text is None:
        return {"status": "unavailable-no-source", "operator": operator}
    if operator not in operator_filter:
        return {"status": "excluded-by-operator-filter", "operator": operator}
    if isinstance(scan_status, Mapping):
        status = scan_status.get("status")
        if status == "semantic-lever-generated":
            if any(getattr(probe, "operator", None) == operator for probe in probes):
                return dict(scan_status)
            return {
                "status": "semantic-lever-not-emitted",
                "operator": operator,
                "reason": (
                    "source scan found a safe semantic local dematerialization, "
                    "but it was not emitted by the selected probe budget"
                ),
            }
        return dict(scan_status)
    return {
        "status": "scan-unavailable",
        "operator": operator,
        "reason": "semantic local dematerialization scan did not run",
    }


def _resolve_frame_transform_operator_filter(
    *,
    probe_plan: Mapping[str, Any],
    operators: list[str] | None,
) -> tuple[str, ...]:
    selected: list[str] = []
    selected.extend(_FRAME_DIRECTED_DEFAULT_OPERATORS)
    raw_priority = probe_plan.get("operator_priority")
    if isinstance(raw_priority, list):
        selected.extend(
            str(item)
            for item in raw_priority
            if isinstance(item, str) and item
        )
    for operator in operators or []:
        for item in operator.split(","):
            item = item.strip()
            if item:
                selected.append(item)
    return tuple(dict.fromkeys(selected))


def _frame_transform_variant_frame_model(
    candidate_text: str,
    function: str,
) -> dict[str, Any]:
    if f"Starting function {function}" in candidate_text:
        return analyze_frame_reservations(candidate_text, function)["current"]
    if re.search(rf"\.fn\s+{re.escape(function)}\b", candidate_text):
        return analyze_frame_from_asm_text(candidate_text)
    if "Starting function " in candidate_text:
        raise ValueError(f"{function} not found in pcdump")
    return analyze_frame_from_asm_text(candidate_text)


def _frame_transform_variant_from_model(
    *,
    label: str,
    operator: str,
    path: Path,
    frame_model: Mapping[str, Any],
    current_frame_size: int | None = None,
    expected_frame_size: int | None = None,
    match_percent: float | None = None,
    match_percent_error: str | None = None,
    source_retained: Path | None = None,
) -> dict[str, Any]:
    frame_size = frame_model.get("frame_size")
    variant = {
        "label": label,
        "operator": operator,
        "status": "ok",
        "path": str(path),
        "frame": dict(frame_model),
        "frame_size": frame_size if isinstance(frame_size, int) else None,
        "candidate_frame_size": frame_size if isinstance(frame_size, int) else None,
        "current_frame_size": current_frame_size,
        "expected_frame_size": expected_frame_size,
    }
    if match_percent is not None:
        variant["match_percent"] = match_percent
        variant["final_match_percent"] = match_percent
    if match_percent_error is not None:
        variant["match_percent_error"] = match_percent_error
    if source_retained is not None:
        variant["source_retained"] = str(source_retained)
    return variant


def _attach_frame_transform_probe_payload(
    variant: dict[str, Any],
    probe_payload: Mapping[str, Any] | None,
) -> None:
    if probe_payload is None:
        return
    payload = dict(probe_payload)
    variant["probe"] = payload
    description = payload.get("description")
    if isinstance(description, str):
        variant["description"] = description
    provenance = payload.get("provenance")
    if isinstance(provenance, Mapping):
        variant["provenance"] = dict(provenance)


def _materialize_frame_transform_probe_sources(
    probes,
    *,
    output_dir: Path | None,
    json_out: bool,
) -> tuple[Path | None, dict[str, Path]]:
    if not probes or not (json_out or output_dir is not None):
        return None, {}
    probe_dir = (
        output_dir
        if output_dir is not None
        else Path(tempfile.mkdtemp(prefix="melee_frame_transform_"))
    )
    probe_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for probe in probes:
        path = probe_dir / f"{probe.label}.c"
        path.write_text(probe.source_text)
        paths[probe.label] = path
    return probe_dir, paths


def _pressure_signature_from_pcdump_or_exit(
    signature_func: Callable[..., object],
    pcdump_text: str,
    function: str,
    **kwargs,
):
    try:
        return signature_func(pcdump_text, function, **kwargs)
    except ValueError as exc:
        if "not found in pcdump" not in str(exc):
            raise
        available = [fn.name for fn in parse_pcdump(pcdump_text)]
        _abort_function_not_in_dump(function, available)


@debug_app.command(name="coalesce-search")
def debug_coalesce_search_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to explore.",
        ),
    ],
    target: Annotated[
        str,
        typer.Option(
            "--target",
            help="Target virtual pair(s), e.g. r37=r40 or r37=r40,r43=r33.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Baseline pcdump. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    allow_stale_pcdump: Annotated[
        bool,
        typer.Option(
            "--allow-stale-pcdump",
            help=(
                "Allow an auto-resolved baseline pcdump whose source is newer "
                "than the cache. Off by default so source scores cannot be "
                "mixed with stale allocator facts."
            ),
        ),
    ] = False,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file used to generate coalesce-directed probes.",
        ),
    ] = None,
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help=(
                "Candidate pcdump/source to score, repeatable. Format "
                "OPERATOR=path or LABEL:OPERATOR=path."
            ),
        ),
    ] = None,
    compile_probes: Annotated[
        bool,
        typer.Option(
            "--compile-probes/--no-compile-probes",
            help=(
                "Compile generated source probes. Enabled by default so the "
                "plain command emits ranked, scored candidates."
            ),
        ),
    ] = True,
    score_match_percent: Annotated[
        bool,
        typer.Option(
            "--score-match-percent/--no-score-match-percent",
            help=(
                "For source candidates, temporarily transfer into the real "
                "tree and read final report.json match percent. Enabled by "
                "default because ranking uses match percent as a tiebreaker; "
                "use --no-score-match-percent for faster pcdump-only scoring."
            ),
        ),
    ] = True,
    max_probes: Annotated[
        int,
        typer.Option(
            "--max-probes",
            help="Maximum generated probes to compile or list.",
        ),
    ] = 8,
    frame_reservation_bytes: Annotated[
        Optional[int],
        typer.Option(
            "--frame-reservation-bytes",
            help=(
                "Add a PAD_STACK(N) source probe for implicit no-access frame "
                "reservation gaps."
            ),
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Per-candidate compile timeout in seconds.",
        ),
    ] = 120,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Search source-shape probes by target coalescing/interference objective."""
    from ..mwcc_debug.coalesce_search import (
        rank_coalesce_candidates,
        render_coalesce_variant,
        score_coalesce_delta,
    )
    from ..mwcc_debug.diff_capture import DiffInput, compile_source_variant
    from ..mwcc_debug.pressure_explorer import (
        compare_pressure_signatures,
        generate_lifetime_layout_probes,
        pressure_signature_from_pcdump,
    )

    target_pairs = _parse_virtual_pair_csv(target)
    if not target_pairs:
        typer.echo("--target is required.", err=True)
        raise typer.Exit(2)

    baseline_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=not allow_stale_pcdump,
    )
    baseline_text = baseline_path.read_text()
    baseline = _pressure_signature_from_pcdump_or_exit(
        pressure_signature_from_pcdump,
        baseline_text,
        function,
        pairs=target_pairs,
    )

    source_text = None
    source_label = None
    if source_file is not None:
        source_file = _resolve_existing_cli_file(
            source_file,
            melee_root=DEFAULT_MELEE_ROOT,
            label="source file",
        )
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            src_path = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if src_path.exists():
                source_text = src_path.read_text()
                try:
                    source_label = str(src_path.relative_to(DEFAULT_MELEE_ROOT))
                except ValueError:
                    source_label = str(src_path)

    probes = (
        generate_lifetime_layout_probes(
            source_text,
            function,
            frame_reservation_bytes=frame_reservation_bytes,
            max_probes=max_probes,
        )
        if source_text
        else []
    )
    variants: list[dict] = []
    generated_source_dir: Path | None = None

    def _score_candidate(
        *,
        label: str,
        operator: str,
        path: Path,
        source_retained: Path | None = None,
    ) -> None:
        try:
            if path.suffix == ".txt":
                candidate_text = path.read_text(encoding="utf-8", errors="replace")
            elif path.suffix == ".c":
                candidate_text = compile_source_variant(
                    DiffInput(
                        label=label,
                        token=str(path),
                        kind="source",
                        path=path,
                    ),
                    function=function,
                    melee_root=DEFAULT_MELEE_ROOT,
                    timeout=timeout,
                )
            else:
                raise ValueError(f"expected .txt pcdump or .c source, got {path}")
            match_percent = None
            match_percent_error = None
            if score_match_percent and path.suffix == ".c":
                status = (
                    _make_real_score_status("coalesce-search", label)
                    if not json_out
                    else None
                )
                match_percent, match_percent_error = (
                    _select_order_source_match_percent(
                        path,
                        function=function,
                        melee_root=DEFAULT_MELEE_ROOT,
                        timeout=timeout,
                        status=status,
                    )
                )
            candidate_sig = pressure_signature_from_pcdump(
                candidate_text,
                function,
                pairs=target_pairs,
            )
            delta = compare_pressure_signatures(baseline, candidate_sig)
            objective = score_coalesce_delta(
                delta,
                target_pairs=target_pairs,
                match_percent=match_percent,
            )
            variant = {
                "label": label,
                "operator": operator,
                "status": "ok",
                "path": str(path),
                "signature": candidate_sig.to_dict(),
                "delta": delta.to_dict(),
                "objective": objective.to_dict(),
            }
            if match_percent_error is not None:
                variant["match_percent_error"] = match_percent_error
            if source_retained is not None:
                variant["source_retained"] = str(source_retained)
            variants.append(variant)
        except Exception as exc:
            failed = {
                "label": label,
                "operator": operator,
                "status": "failed",
                "path": str(path),
                "error": str(exc),
            }
            if source_retained is not None:
                failed["source_retained"] = str(source_retained)
            elif path.suffix == ".c" and path.exists():
                failed["source_retained"] = str(path)
            variants.append(failed)

    for spec in candidates or []:
        label, operator, path = _parse_lifetime_layout_candidate(spec)
        _score_candidate(label=label, operator=operator, path=path)

    if compile_probes:
        if not probes and not candidates:
            typer.echo(
                "source unavailable or no probes generated; pass --source-file "
                "or --candidate OPERATOR=path.",
                err=True,
            )
            raise typer.Exit(2)
        if probes:
            generated_source_dir = Path(tempfile.mkdtemp(prefix="melee_coalesce_search_"))
            for probe in probes:
                path = generated_source_dir / f"{probe.label}.c"
                path.write_text(probe.source_text)
                _score_candidate(
                    label=probe.label,
                    operator=probe.operator,
                    path=path,
                    source_retained=path,
                )

    ranked_variants = rank_coalesce_candidates(variants)
    if json_out:
        print(json.dumps({
            "function": function,
            "target_pairs": [list(pair) for pair in target_pairs],
            "ranking": (
                "target coalesce objective, final match percent tiebreaker"
            ),
            "baseline": baseline.to_dict(),
            "source": source_label,
            "generated_source_dir": (
                str(generated_source_dir) if generated_source_dir is not None else None
            ),
            "probes": [probe.to_dict() for probe in probes],
            "variants": ranked_variants,
        }, indent=2))
        return

    print(f"coalesce-search - {function}")
    print(
        "target: "
        + ", ".join(f"r{left}/r{right}" for left, right in target_pairs)
    )
    print("ranking: target coalesce objective, final match percent tiebreaker")
    print(
        f"baseline: frame={baseline.frame_size if baseline.frame_size is not None else '?'} "
        f"spills={','.join(str(v) for v in baseline.spill_set) or '-'}"
    )
    if generated_source_dir is not None:
        print(f"generated source dir: {generated_source_dir}")
    if ranked_variants:
        print("Variants:")
        for variant in ranked_variants:
            print(render_coalesce_variant(variant))
    elif probes:
        print("Probes:")
        for probe in probes:
            print(f"- {probe.label} [{probe.operator}]: {probe.description}")
        print("Variants: none; pass --compile-probes or --candidate OPERATOR=path.")
    else:
        print("Variants: none; pass --source-file or --candidate OPERATOR=path.")


@debug_app.command(name="select-order-search")
def debug_select_order_search_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to explore.",
        ),
    ],
    target: Annotated[
        str,
        typer.Option(
            "--target",
            help="Target select order(s), e.g. r32<r33 or r43<r33,r40<r33.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Baseline pcdump. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    allow_stale_pcdump: Annotated[
        bool,
        typer.Option(
            "--allow-stale-pcdump",
            help=(
                "Allow an auto-resolved baseline pcdump whose source is newer "
                "than the cache. Off by default so source scores cannot be "
                "mixed with stale allocator facts."
            ),
        ),
    ] = False,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file used to generate select-order-directed probes.",
        ),
    ] = None,
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help=(
                "Candidate pcdump/source to score, repeatable. Format "
                "OPERATOR=path or LABEL:OPERATOR=path."
            ),
        ),
    ] = None,
    probe_provenance: Annotated[
        Optional[list[str]],
        typer.Option(
            "--probe-provenance",
            help=(
                "JSON object describing the matching --candidate provenance. "
                "Repeat in candidate order."
            ),
        ),
    ] = None,
    class_id: Annotated[
        int,
        typer.Option(
            "--class",
            help="Register class id from COLORGRAPH DECISIONS.",
        ),
    ] = 0,
    compile_probes: Annotated[
        bool,
        typer.Option(
            "--compile-probes/--no-compile-probes",
            help=(
                "Compile generated source probes. Enabled by default so the "
                "plain command emits ranked, scored candidates."
            ),
        ),
    ] = True,
    score_match_percent: Annotated[
        bool,
        typer.Option(
            "--score-match-percent/--no-score-match-percent",
            help=(
                "For source candidates, temporarily transfer into the real "
                "tree and read final report.json match percent. Enabled by "
                "default because ranking uses match percent as a tiebreaker; "
                "use --no-score-match-percent for faster pcdump-only scoring."
            ),
        ),
    ] = True,
    max_probes: Annotated[
        int,
        typer.Option(
            "--max-probes",
            help="Maximum generated probes to compile or list.",
        ),
    ] = 8,
    frame_reservation_bytes: Annotated[
        Optional[int],
        typer.Option(
            "--frame-reservation-bytes",
            help=(
                "Add a PAD_STACK(N) source probe for implicit no-access frame "
                "reservation gaps."
            ),
        ),
    ] = None,
    beam_depth: Annotated[
        int,
        typer.Option(
            "--beam-depth",
            help=(
                "Compose generated source probes for N rounds. 0 keeps the "
                "single-probe search."
            ),
        ),
    ] = 0,
    beam_width: Annotated[
        int,
        typer.Option(
            "--beam-width",
            help="Number of real-score-ranked candidates to expand per beam round.",
        ),
    ] = 4,
    campaign_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--campaign-dir",
            help=(
                "Directory for composed probe sources and ledger. Defaults to "
                "a temporary melee_select_order_beam_* directory."
            ),
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Per-candidate compile timeout in seconds.",
        ),
    ] = 120,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Search source-shape probes by target COLORGRAPH select-order objective."""
    from ..mwcc_debug.diff_capture import (
        CompileFailure,
        DiffInput,
        compile_source_variant,
    )
    from ..mwcc_debug.pressure_explorer import (
        compare_pressure_signatures,
        generate_lifetime_layout_probes,
        pressure_signature_from_pcdump,
    )
    from ..mwcc_debug.select_order_search import (
        rank_select_order_candidates,
        render_select_order_variant,
        score_select_order_candidate,
    )

    target_orders = _parse_virtual_order_csv(target)
    if not target_orders:
        typer.echo("--target is required.", err=True)
        raise typer.Exit(2)

    baseline_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=not allow_stale_pcdump,
    )
    baseline_cache = _auto_pcdump_cache_metadata(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
    )
    baseline_text = baseline_path.read_text(encoding="utf-8", errors="replace")
    baseline = _pressure_signature_from_pcdump_or_exit(
        pressure_signature_from_pcdump,
        baseline_text,
        function,
        pairs=target_orders,
        class_id=class_id,
    )

    source_text = None
    source_label = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            src_path = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if src_path.exists():
                source_text = src_path.read_text()
                try:
                    source_label = str(src_path.relative_to(DEFAULT_MELEE_ROOT))
                except ValueError:
                    source_label = str(src_path)

    probes = (
        generate_lifetime_layout_probes(
            source_text,
            function,
            frame_reservation_bytes=frame_reservation_bytes,
            max_probes=max_probes,
        )
        if source_text
        else []
    )
    variants: list[dict] = []
    generated_source_dir: Path | None = None
    beam_campaign_dir: Path | None = None
    beam_ledger_path: Path | None = None
    beam_ledger: dict | None = None

    def _score_candidate(
        *,
        label: str,
        operator: str,
        path: Path,
        source_retained: Path | None = None,
        depth: int | None = None,
        parent_label: str | None = None,
        chain: list[str] | None = None,
        body_fingerprint: str | None = None,
        diff_fingerprint: str | None = None,
    ) -> None:
        try:
            candidate_source_text: str | None = None
            if path.suffix == ".txt":
                candidate_text = path.read_text(encoding="utf-8", errors="replace")
            elif path.suffix == ".c":
                candidate_source_text, _ = (
                    _prevalidate_lifetime_layout_source_candidate(
                        path,
                        function=function,
                    )
                )
                try:
                    candidate_text = compile_source_variant(
                        DiffInput(
                            label=label,
                            token=str(path),
                            kind="source",
                            path=path,
                        ),
                        function=function,
                        melee_root=DEFAULT_MELEE_ROOT,
                        timeout=timeout,
                    )
                except CompileFailure as exc:
                    detail = str(exc)
                    if (
                        exc.returncode == 3
                        and "not found in pcdump" in detail
                    ):
                        raise _MalformedSourceCandidate(
                            (
                                f"{detail}; compiled probe pcdump omitted the "
                                f"target function. Source retained at {path}"
                            ),
                            source_hunk=_compact_source_hunk_for_function(
                                candidate_source_text,
                                function,
                            ),
                        ) from exc
                    raise
            else:
                raise ValueError(f"expected .txt pcdump or .c source, got {path}")
            match_percent = None
            match_percent_error = None
            if score_match_percent and path.suffix == ".c":
                status = (
                    _make_real_score_status("select-order-search", label)
                    if not json_out
                    else None
                )
                match_percent, match_percent_error = (
                    _select_order_source_match_percent(
                        path,
                        function=function,
                        melee_root=DEFAULT_MELEE_ROOT,
                        timeout=timeout,
                        status=status,
                    )
                )
            try:
                candidate_sig = pressure_signature_from_pcdump(
                    candidate_text,
                    function,
                    pairs=target_orders,
                    class_id=class_id,
                )
            except ValueError as exc:
                if path.suffix == ".c":
                    raise _MalformedSourceCandidate(
                        f"{exc}; compiled probe pcdump omitted the target "
                        f"function. Source retained at {path}",
                        source_hunk=_compact_source_hunk_for_function(
                            candidate_source_text or path.read_text(
                                encoding="utf-8",
                                errors="replace",
                            ),
                            function,
                        ),
                    ) from exc
                raise
            delta = compare_pressure_signatures(baseline, candidate_sig)
            objective = score_select_order_candidate(
                baseline_text,
                candidate_text,
                function=function,
                target_orders=target_orders,
                class_id=class_id,
                delta=delta,
                match_percent=match_percent,
            )
            variant = {
                "label": label,
                "operator": operator,
                "status": "ok",
                "path": str(path),
                "signature": candidate_sig.to_dict(),
                "delta": delta.to_dict(),
                "objective": objective.to_dict(),
            }
            if depth is not None:
                variant["depth"] = depth
            if parent_label is not None:
                variant["parent_label"] = parent_label
            if chain:
                variant["chain"] = chain
            if body_fingerprint is not None:
                variant["body_fingerprint"] = body_fingerprint
            if diff_fingerprint is not None:
                variant["diff_fingerprint"] = diff_fingerprint
            probe_payload = candidate_probe_by_label.get(label)
            if probe_payload is not None:
                variant["probe"] = probe_payload
            if match_percent_error is not None:
                variant["match_percent_error"] = match_percent_error
            if source_retained is not None:
                variant["source_retained"] = str(source_retained)
            variants.append(variant)
            return variant
        except Exception as exc:
            failed_status = "failed"
            malformed_source = isinstance(exc, _MalformedSourceCandidate)
            if malformed_source:
                failed_status = "malformed-source"
            elif isinstance(exc, CompileFailure) or (
                path.suffix == ".c" and "not found in pcdump" in str(exc)
            ):
                failed_status = "build-failed"
            failed = {
                "label": label,
                "operator": operator,
                "status": failed_status,
                "path": str(path),
                "error": str(exc),
            }
            if depth is not None:
                failed["depth"] = depth
            if parent_label is not None:
                failed["parent_label"] = parent_label
            if chain:
                failed["chain"] = chain
            if body_fingerprint is not None:
                failed["body_fingerprint"] = body_fingerprint
            if diff_fingerprint is not None:
                failed["diff_fingerprint"] = diff_fingerprint
            probe_payload = candidate_probe_by_label.get(label)
            if probe_payload is not None:
                failed["probe"] = probe_payload
            if source_retained is not None:
                failed["source_retained"] = str(source_retained)
            elif path.suffix == ".c" and path.exists():
                failed["source_retained"] = str(path)
            if malformed_source and exc.source_hunk:
                failed["source_hunk"] = exc.source_hunk
            variants.append(failed)
            return failed

    candidate_probe_by_label: dict[str, dict] = {}
    provenance_values = probe_provenance or []
    for index, spec in enumerate(candidates or []):
        label, operator, path = _parse_lifetime_layout_candidate(spec)
        if index < len(provenance_values):
            candidate_probe_by_label[label] = {
                "label": label,
                "operator": operator,
                "description": "User-supplied candidate provenance.",
                "provenance": _parse_probe_provenance(provenance_values[index]),
            }
        _score_candidate(label=label, operator=operator, path=path)

    if compile_probes and beam_depth <= 0:
        if not probes and not candidates:
            typer.echo(
                "source unavailable or no probes generated; pass --source-file "
                "or --candidate OPERATOR=path.",
                err=True,
            )
            raise typer.Exit(2)
        if probes:
            generated_source_dir = Path(tempfile.mkdtemp(prefix="melee_select_order_"))
            for probe in probes:
                path = generated_source_dir / f"{probe.label}.c"
                path.write_text(probe.source_text)
                candidate_probe_by_label[probe.label] = probe.to_dict()
                _score_candidate(
                    label=probe.label,
                    operator=probe.operator,
                    path=path,
                    source_retained=path,
                )

    if beam_depth > 0:
        if beam_width <= 0:
            raise typer.BadParameter("--beam-width must be positive")
        if not source_text:
            typer.echo(
                "source unavailable; pass --source-file for --beam-depth.",
                err=True,
            )
            raise typer.Exit(2)
        beam_campaign_dir = (
            campaign_dir
            if campaign_dir is not None
            else Path(tempfile.mkdtemp(prefix="melee_select_order_beam_"))
        )
        beam_campaign_dir.mkdir(parents=True, exist_ok=True)
        (beam_campaign_dir / "seed.c").write_text(source_text)
        beam_ledger_path = beam_campaign_dir / "ledger.json"
        beam_ledger = {
            "function": function,
            "target_orders": [list(pair) for pair in target_orders],
            "class_id": class_id,
            "baseline_cache": baseline_cache,
            "beam_depth": beam_depth,
            "beam_width": beam_width,
            "ranking": "final match percent first, then target select-order objective",
            "entries": [],
            "deduped": [],
        }
        seen_body: set[str] = set()
        seen_diff: set[str] = set()
        seed_body, seed_diff = _select_order_source_fingerprints(
            base_source=source_text,
            candidate_source=source_text,
            function=function,
        )
        seen_body.add(seed_body)
        seen_diff.add(seed_diff)
        frontier: list[dict] = [{
            "label": "seed",
            "source_text": source_text,
            "chain": [],
        }]
        counter = 0
        for depth in range(1, beam_depth + 1):
            round_ok: list[tuple[dict, str]] = []
            round_dir = beam_campaign_dir / f"depth-{depth:02d}"
            round_dir.mkdir(parents=True, exist_ok=True)
            for parent in frontier:
                parent_source = str(parent["source_text"])
                parent_label = str(parent["label"])
                parent_chain = list(parent.get("chain") or [])
                for probe in generate_lifetime_layout_probes(
                    parent_source,
                    function,
                    frame_reservation_bytes=frame_reservation_bytes,
                    max_probes=max_probes,
                ):
                    body_hash, diff_hash = _select_order_source_fingerprints(
                        base_source=source_text,
                        candidate_source=probe.source_text,
                        function=function,
                    )
                    if body_hash in seen_body or diff_hash in seen_diff:
                        beam_ledger["deduped"].append({
                            "depth": depth,
                            "parent_label": parent_label,
                            "probe_label": probe.label,
                            "body_fingerprint": body_hash,
                            "diff_fingerprint": diff_hash,
                        })
                        continue
                    seen_body.add(body_hash)
                    seen_diff.add(diff_hash)
                    counter += 1
                    label = (
                        f"d{depth}-{counter:04d}-"
                        f"{_select_order_safe_label(probe.label)}"
                    )
                    path = round_dir / f"{label}.c"
                    path.write_text(probe.source_text)
                    chain = [*parent_chain, probe.label]
                    probe_payload = probe.to_dict()
                    probe_payload["parent_label"] = parent_label
                    probe_payload["chain"] = chain
                    candidate_probe_by_label[label] = probe_payload
                    variant = _score_candidate(
                        label=label,
                        operator=probe.operator,
                        path=path,
                        source_retained=path,
                        depth=depth,
                        parent_label=parent_label,
                        chain=chain,
                        body_fingerprint=body_hash,
                        diff_fingerprint=diff_hash,
                    )
                    entry = {
                        "label": label,
                        "depth": depth,
                        "parent_label": parent_label,
                        "chain": chain,
                        "status": variant.get("status"),
                        "path": str(path),
                        "body_fingerprint": body_hash,
                        "diff_fingerprint": diff_hash,
                        "match_percent": (
                            (variant.get("objective") or {}).get("match_percent")
                        ),
                        "objective": variant.get("objective"),
                        "error": variant.get("error"),
                    }
                    beam_ledger["entries"].append(entry)
                    if variant.get("status") == "ok":
                        round_ok.append((variant, probe.source_text))
            selected = _rank_select_order_candidates_real_first(
                [variant for variant, _source in round_ok]
            )[:beam_width]
            selected_labels = {variant["label"] for variant in selected}
            frontier = [
                {
                    "label": variant["label"],
                    "source_text": source,
                    "chain": variant.get("chain") or [],
                }
                for variant, source in round_ok
                if variant["label"] in selected_labels
            ]
            if not frontier:
                break
        beam_ledger_path.write_text(json.dumps(beam_ledger, indent=2))

    if beam_depth > 0:
        ranked_variants = _rank_select_order_candidates_real_first(variants)
        ranking = "final match percent first, then target select-order objective"
    else:
        ranked_variants = rank_select_order_candidates(variants)
        ranking = "target select-order objective, final match percent tiebreaker"
    if json_out:
        print(json.dumps({
            "function": function,
            "target_orders": [list(pair) for pair in target_orders],
            "class_id": class_id,
            "ranking": ranking,
            "baseline": baseline.to_dict(),
            "baseline_cache": baseline_cache,
            "source": source_label,
            "generated_source_dir": (
                str(generated_source_dir) if generated_source_dir is not None else None
            ),
            "beam_campaign_dir": (
                str(beam_campaign_dir) if beam_campaign_dir is not None else None
            ),
            "beam_ledger": (
                str(beam_ledger_path) if beam_ledger_path is not None else None
            ),
            "probes": [probe.to_dict() for probe in probes],
            "variants": ranked_variants,
        }, indent=2))
        return

    print(f"select-order-search - {function}")
    print(
        "target: "
        + ", ".join(f"r{first}<r{second}" for first, second in target_orders)
    )
    print(f"class: {class_id}")
    print(f"ranking: {ranking}")
    print(
        f"baseline: frame={baseline.frame_size if baseline.frame_size is not None else '?'} "
        f"spills={','.join(str(v) for v in baseline.spill_set) or '-'}"
    )
    if baseline_cache is not None:
        source_mtime = baseline_cache.get("source_mtime")
        cache_mtime = baseline_cache.get("cache_mtime")
        print(
            "baseline cache: "
            f"fresh={baseline_cache.get('fresh')} "
            f"src_mtime={source_mtime if source_mtime is not None else '?'} "
            f"cache_mtime={cache_mtime if cache_mtime is not None else '?'}"
        )
    if generated_source_dir is not None:
        print(f"generated source dir: {generated_source_dir}")
    if beam_campaign_dir is not None:
        print(f"beam campaign dir: {beam_campaign_dir}")
    if beam_ledger_path is not None:
        print(f"beam ledger: {beam_ledger_path}")
    if ranked_variants:
        print("Variants:")
        for variant in ranked_variants:
            print(render_select_order_variant(variant))
    elif probes:
        print("Probes:")
        for probe in probes:
            print(f"- {probe.label} [{probe.operator}]: {probe.description}")
        print("Variants: none; pass --compile-probes or --candidate OPERATOR=path.")
    else:
        print("Variants: none; pass --source-file or --candidate OPERATOR=path.")


@mutate_app.command(name="lifetime-layout")
def mutate_lifetime_layout_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to explore.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Baseline pcdump. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file used to generate lifetime/layout probes.",
        ),
    ] = None,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output-dir",
            help=(
                "Directory for generated --compile-probes source files. "
                "When omitted, JSON output retains a temp directory because "
                "variant paths are machine-readable follow-up inputs."
            ),
        ),
    ] = None,
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help=(
                "Candidate pcdump/source to score, repeatable. Format "
                "OPERATOR=path or LABEL:OPERATOR=path."
            ),
        ),
    ] = None,
    pairs: Annotated[
        str,
        typer.Option(
            "--pairs",
            help="Comma-separated target virtual pairs, e.g. r37/r40,r43/r33.",
        ),
    ] = "",
    compile_probes: Annotated[
        bool,
        typer.Option(
            "--compile-probes",
            help="Compile generated source probes and report pressure deltas.",
        ),
    ] = False,
    score_match_percent: Annotated[
        bool,
        typer.Option(
            "--score-match-percent/--no-score-match-percent",
            help=(
                "For source candidates, temporarily transfer into the real "
                "tree and read final report.json match percent plus "
                "checkdiff stack-slot deltas. Enabled by default; use "
                "--no-score-match-percent for faster pcdump-only scoring."
            ),
        ),
    ] = True,
    max_probes: Annotated[
        int,
        typer.Option(
            "--max-probes",
            help="Maximum generated probes to list or compile.",
        ),
    ] = 12,
    frame_reservation_bytes: Annotated[
        Optional[int],
        typer.Option(
            "--frame-reservation-bytes",
            help=(
                "Add a PAD_STACK(N) source probe for implicit no-access frame "
                "reservation gaps."
            ),
        ),
    ] = None,
    focus: Annotated[
        Optional[str],
        typer.Option(
            "--focus",
            help=(
                "Named probe-family bundle. `b4-tree-loop` focuses the "
                "x594_b4 tree loop problem space: pointer/indexed tree loops "
                "plus loop-counter declaration/type/scope probes."
            ),
        ),
    ] = None,
    operators: Annotated[
        Optional[list[str]],
        typer.Option(
            "--operator",
            help=(
                "Only generate/compile probes from this operator family. "
                "Repeat or pass comma-separated names; combines with --focus."
            ),
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Per-candidate compile timeout in seconds.",
        ),
    ] = 120,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Explore lifetime/layout source probes and attribute pressure deltas."""
    from ..mwcc_debug.diff_capture import DiffInput, compile_source_variant
    from ..mwcc_debug.pressure_explorer import (
        compare_pressure_signatures,
        generate_lifetime_layout_probes,
        pressure_signature_from_pcdump,
        render_pressure_delta,
    )

    pair_list = _parse_virtual_pair_csv(pairs)
    baseline_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=False,
    )
    baseline_text = baseline_path.read_text()
    baseline = _pressure_signature_from_pcdump_or_exit(
        pressure_signature_from_pcdump,
        baseline_text,
        function,
        pairs=pair_list,
    )
    operator_filter = _resolve_lifetime_layout_operator_filter(
        focus=focus,
        operators=operators,
    )

    source_text = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            src_path = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if src_path.exists():
                source_text = src_path.read_text()

    probes = (
        generate_lifetime_layout_probes(
            source_text,
            function,
            frame_reservation_bytes=frame_reservation_bytes,
            max_probes=max_probes,
            operator_filter=operator_filter,
        )
        if source_text
        else []
    )

    variants: list[dict] = []
    generated_source_dir: Path | None = None
    score_total = len(candidates or []) + (len(probes) if compile_probes else 0)
    score_index = 0

    def _emit_candidate_progress(
        event: str,
        *,
        index: int,
        label: str,
        operator: str,
        path: Path,
        error: str | None = None,
    ) -> None:
        payload = {
            "event": event,
            "index": index,
            "total": score_total,
            "label": label,
            "operator": operator,
            "path": str(path),
        }
        if error is not None:
            payload["error"] = error
        if json_out:
            print(json.dumps(payload), file=sys.stderr, flush=True)
        else:
            message = (
                f"[lifetime-layout] {index}/{score_total} {label} "
                f"[{operator}]: {path}"
            )
            if event.endswith("-failed") and error is not None:
                message += f" failed: {error}"
            elif event.endswith("-ok"):
                message += " ok"
            print(message, file=sys.stderr, flush=True)

    def _score_candidate(
        *,
        label: str,
        operator: str,
        path: Path,
    ) -> None:
        nonlocal score_index
        score_index += 1
        current_index = score_index
        _emit_candidate_progress(
            "lifetime-layout-candidate-start",
            index=current_index,
            label=label,
            operator=operator,
            path=path,
        )
        try:
            candidate_source_text: str | None = None
            if path.suffix == ".txt":
                candidate_text = path.read_text(encoding="utf-8", errors="replace")
            elif path.suffix == ".c":
                candidate_source_text, _ = (
                    _prevalidate_lifetime_layout_source_candidate(
                        path,
                        function=function,
                    )
                )
                try:
                    candidate_text = compile_source_variant(
                        DiffInput(
                            label=label,
                            token=str(path),
                            kind="source",
                            path=path,
                        ),
                        function=function,
                        melee_root=DEFAULT_MELEE_ROOT,
                        timeout=timeout,
                    )
                except CompileFailure as exc:
                    detail = str(exc)
                    if (
                        exc.returncode == 3
                        and "not found in pcdump" in detail
                    ):
                        raise _MalformedSourceCandidate(
                            (
                                f"{detail}; compiled probe pcdump omitted the "
                                f"target function. Source retained at {path}"
                            ),
                            source_hunk=_compact_source_hunk_for_function(
                                candidate_source_text,
                                function,
                            ),
                        ) from exc
                    raise
            else:
                raise ValueError(f"expected .txt pcdump or .c source, got {path}")
            real_score = _SourceCandidateRealScore(None, None)
            if score_match_percent and path.suffix == ".c":
                status = (
                    _make_real_score_status("lifetime-layout", label)
                    if not json_out
                    else None
                )
                real_score = _score_source_candidate_real_tree(
                    path,
                    function=function,
                    melee_root=DEFAULT_MELEE_ROOT,
                    timeout=timeout,
                    status=status,
                    include_stack_slot=True,
                )
            try:
                candidate_sig = pressure_signature_from_pcdump(
                    candidate_text,
                    function,
                    pairs=pair_list,
                )
            except ValueError as exc:
                if path.suffix == ".c":
                    raise _MalformedSourceCandidate(
                        f"{exc}; compiled probe pcdump omitted the target "
                        f"function. Source retained at {path}",
                        source_hunk=_compact_source_hunk_for_function(
                            candidate_source_text or path.read_text(
                                encoding="utf-8",
                                errors="replace",
                            ),
                            function,
                        ),
                    ) from exc
                raise
            delta = compare_pressure_signatures(baseline, candidate_sig)
            objective = _score_lifetime_layout_objective(
                delta,
                target_pairs=pair_list,
                match_percent=real_score.match_percent,
                stack_slot_localizer=real_score.stack_slot_localizer,
            )
            variant = {
                "label": label,
                "operator": operator,
                "status": "ok",
                "path": str(path),
                "signature": candidate_sig.to_dict(),
                "delta": delta.to_dict(),
                "objective": objective,
                "_text": render_pressure_delta(label, operator, delta),
            }
            if real_score.match_percent is not None:
                variant["final_match_percent"] = real_score.match_percent
                variant["match_percent"] = real_score.match_percent
            if real_score.match_percent_error is not None:
                variant["match_percent_error"] = real_score.match_percent_error
            if real_score.stack_slot_localizer is not None:
                variant["stack_slot_localizer"] = real_score.stack_slot_localizer
            if real_score.stack_slot_error is not None:
                variant["stack_slot_error"] = real_score.stack_slot_error
            if path.suffix == ".c":
                variant["source_retained"] = str(path)
            variants.append(variant)
            _emit_candidate_progress(
                "lifetime-layout-candidate-ok",
                index=current_index,
                label=label,
                operator=operator,
                path=path,
            )
        except Exception as exc:
            malformed_source = isinstance(exc, _MalformedSourceCandidate)
            failed = {
                "label": label,
                "operator": operator,
                "status": "malformed-source" if malformed_source else "failed",
                "path": str(path),
                "error": str(exc),
            }
            if path.suffix == ".c" and path.exists():
                failed["source_retained"] = str(path)
            if malformed_source and exc.source_hunk:
                failed["source_hunk"] = exc.source_hunk
            variants.append(failed)
            _emit_candidate_progress(
                "lifetime-layout-candidate-failed",
                index=current_index,
                label=label,
                operator=operator,
                path=path,
                error=str(exc),
            )

    for spec in candidates or []:
        label, operator, path = _parse_lifetime_layout_candidate(spec)
        _score_candidate(label=label, operator=operator, path=path)

    if compile_probes:
        if source_text is None:
            typer.echo("--compile-probes requires --source-file or repo source", err=True)
            raise typer.Exit(2)
        probe_dir = (
            output_dir
            if output_dir is not None
            else Path(tempfile.mkdtemp(prefix="melee_lifetime_layout_"))
        )
        probe_dir.mkdir(parents=True, exist_ok=True)
        generated_source_dir = probe_dir
        start_idx = len(variants)
        try:
            for probe in probes:
                path = probe_dir / f"{probe.label}.c"
                path.write_text(probe.source_text)
                _score_candidate(
                    label=probe.label,
                    operator=probe.operator,
                    path=path,
                )
        finally:
            generated_failed = any(
                variant["status"] != "ok" for variant in variants[start_idx:]
            )
            retain_generated = generated_failed or json_out or output_dir is not None
            if not retain_generated:
                shutil.rmtree(probe_dir, ignore_errors=True)

    ranked_variants = _rank_lifetime_layout_candidates(variants)
    if json_out:
        payload = {
            "function": function,
            "ranking": _LIFETIME_LAYOUT_RANKING,
            "baseline": baseline.to_dict(),
            "probes": [probe.to_dict() for probe in probes],
            "variants": [
                {k: v for k, v in variant.items() if k != "_text"}
                for variant in ranked_variants
            ],
        }
        if focus is not None:
            payload["focus"] = focus
        if operator_filter is not None:
            payload["operator_filter"] = list(operator_filter)
        if generated_source_dir is not None:
            payload["generated_source_dir"] = str(generated_source_dir)
        print(json.dumps(payload, indent=2))
        return

    print(f"lifetime-layout pressure explorer - {function}")
    if focus is not None:
        print(f"focus: {focus}")
    if operator_filter is not None:
        print("operator filter: " + ", ".join(operator_filter))
    print(
        f"baseline: frame={baseline.frame_size if baseline.frame_size is not None else '?'} "
        f"saved={','.join(baseline.saved_regs) or '-'} "
        f"spills={','.join(str(v) for v in baseline.spill_set) or '-'}"
    )
    if probes:
        print("Probes:")
        for probe in probes:
            print(f"- {probe.label} [{probe.operator}]: {probe.description}")
    elif source_text is None:
        print("Probes: source unavailable; pass --source-file to generate them.")
    if variants:
        print(f"ranking: {_LIFETIME_LAYOUT_RANKING}")
        print("Variants:")
        for variant in ranked_variants:
            if variant["status"] == "ok":
                print(
                    f"{variant.get('rank', '?')}. "
                    f"{variant['label']} [{variant['operator']}]"
                )
                objective = variant.get("objective") or {}
                target_spill_removed = ",".join(
                    "r" + str(v)
                    for v in objective.get("target_spill_removed", [])
                ) or "-"
                print(
                    "  objective: "
                    f"actionability={objective.get('actionability', '?')} "
                    f"frame_delta={objective.get('frame_delta')} "
                    f"target_spill_removed={target_spill_removed} "
                    f"interference_removed={objective.get('interference_removed_count', 0)} "
                    f"coalesce_added={objective.get('coalesce_added_count', 0)}"
                )
                print(variant["_text"])
                if variant.get("final_match_percent") is not None:
                    print(
                        f"  final_match_percent: "
                        f"{variant['final_match_percent']:.6g}"
                    )
                if variant.get("match_percent_error"):
                    print(f"  match_percent_error: {variant['match_percent_error']}")
                if variant.get("stack_slot_localizer"):
                    localizer = variant["stack_slot_localizer"]
                    deltas = ",".join(str(d) for d in localizer.get("deltas", []))
                    mismatch_count = localizer.get("mismatch_count", 0)
                    print(
                        f"  stack_slot_localizer: {mismatch_count} mismatch(es)"
                        + (f", deltas={deltas}" if deltas else "")
                    )
                if variant.get("stack_slot_error"):
                    print(f"  stack_slot_error: {variant['stack_slot_error']}")
            else:
                print(
                    f"- {variant['label']} [{variant['operator']}] failed: "
                    f"{variant['error']}"
                )
                if variant.get("source_retained"):
                    print(f"  source: {variant['source_retained']}")
    elif not compile_probes and not candidates:
        print("Variants: none; pass --compile-probes or --candidate OPERATOR=path.")


@mutate_app.command(name="frame-transform-search")
def mutate_frame_transform_search_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to explore.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Baseline pcdump. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    expected_asm: Annotated[
        Optional[Path],
        typer.Option(
            "--expected-asm",
            help="Path to expected target asm. Omit to extract via function.",
        ),
    ] = None,
    no_expected: Annotated[
        bool,
        typer.Option(
            "--no-expected",
            help="Allow planning without expected asm; validation will report no target.",
        ),
    ] = False,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file used to generate directed frame probes.",
        ),
    ] = None,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output-dir",
            help=(
                "Directory for generated --compile-probes source files. "
                "When omitted, JSON output retains a temp directory because "
                "variant paths are machine-readable follow-up inputs."
            ),
        ),
    ] = None,
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help=(
                "Candidate pcdump/source to score, repeatable. Format "
                "OPERATOR=path or LABEL:OPERATOR=path."
            ),
        ),
    ] = None,
    compile_probes: Annotated[
        bool,
        typer.Option(
            "--compile-probes/--no-compile-probes",
            help="Compile generated directed source probes.",
        ),
    ] = True,
    score_match_percent: Annotated[
        bool,
        typer.Option(
            "--score-match-percent/--no-score-match-percent",
            help=(
                "For source candidates, temporarily transfer into the real "
                "tree and read final report.json match percent. Enabled by "
                "default because ranking uses match percent as a tiebreaker."
            ),
        ),
    ] = True,
    max_probes: Annotated[
        int,
        typer.Option(
            "--max-probes",
            help="Maximum generated probes to list or compile.",
        ),
    ] = 12,
    operators: Annotated[
        Optional[list[str]],
        typer.Option(
            "--operator",
            help=(
                "Add an operator family to the directed search. Repeat or "
                "pass comma-separated names; values are unioned with the "
                "frame-divergence plan."
            ),
        ),
    ] = None,
    include_lifetime_fallback: Annotated[
        bool,
        typer.Option(
            "--include-lifetime-fallback/--no-include-lifetime-fallback",
            help=(
                "Also include existing lifetime-layout probes whose operator "
                "is selected by the frame-divergence plan."
            ),
        ),
    ] = True,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Per-candidate compile timeout in seconds.",
        ),
    ] = 120,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Compile and score directed source transforms for frame-size divergence."""
    from ..mwcc_debug.diff_capture import DiffInput, compile_source_variant
    from ..mwcc_debug.pressure_explorer import (
        generate_frame_directed_probes,
        generate_lifetime_layout_probes,
        scan_frame_local_dematerialization_probes,
    )

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        melee_root,
        require_fresh=False,
    )
    pcdump_text = pcdump_path.read_text(encoding="utf-8", errors="replace")
    expected_text = _read_frame_reservation_expected_asm(
        function,
        expected_asm=expected_asm,
        no_expected=no_expected,
        melee_root=melee_root,
    )
    current_text = (
        _read_frame_reservation_current_asm(function, melee_root=melee_root)
        if _pcdump_has_symbolic_stack_homes(pcdump_text)
        else None
    )
    try:
        frame_report = analyze_frame_reservations(
            pcdump_text,
            function,
            expected_asm_text=expected_text,
            current_asm_text=current_text,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    probe_plan = _frame_transform_probe_plan(frame_report)
    operator_filter = _resolve_frame_transform_operator_filter(
        probe_plan=probe_plan,
        operators=operators,
    )
    current_frame_size = (frame_report.get("current") or {}).get("frame_size")
    if not isinstance(current_frame_size, int):
        current_frame_size = None
    expected_frame_size = None
    expected_model = frame_report.get("expected")
    if isinstance(expected_model, Mapping):
        raw_expected_frame = expected_model.get("frame_size")
        if isinstance(raw_expected_frame, int):
            expected_frame_size = raw_expected_frame
    frame_reservation_delta = (
        expected_frame_size - current_frame_size
        if current_frame_size is not None
        and expected_frame_size is not None
        and current_frame_size != expected_frame_size
        else None
    )

    source_text = None
    source_label = None
    if source_file is not None:
        source_file = _resolve_existing_cli_file(
            source_file,
            melee_root=melee_root,
            label="source file",
        )
        source_text = source_file.read_text(encoding="utf-8", errors="replace")
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, melee_root)
        if unit is not None:
            src_path = melee_root / "src" / f"{unit}.c"
            if src_path.exists():
                source_text = src_path.read_text(encoding="utf-8", errors="replace")
                try:
                    source_label = str(src_path.relative_to(melee_root))
                except ValueError:
                    source_label = str(src_path)

    probes = []
    if source_text is not None:
        directed = generate_frame_directed_probes(
            source_text,
            function,
            current_frame=frame_report.get("current"),
            target_frame=frame_report.get("expected"),
            frame_reservation_delta=frame_reservation_delta,
            max_probes=max_probes,
        )
        allowed = frozenset(operator_filter)
        probes.extend(probe for probe in directed if probe.operator in allowed)
        if include_lifetime_fallback and len(probes) < max_probes:
            remaining = max_probes - len(probes)
            probes.extend(
                generate_lifetime_layout_probes(
                    source_text,
                    function,
                    max_probes=remaining,
                    operator_filter=operator_filter,
                )
            )
        probes = probes[:max_probes]

    semantic_scan_status: Mapping[str, Any] | None = None
    if (
        source_text is not None
        and frame_reservation_delta is not None
        and frame_reservation_delta < 0
        and "frame-local-dematerialize" in operator_filter
    ):
        _semantic_scan_probes, semantic_scan_status = (
            scan_frame_local_dematerialization_probes(source_text, function)
        )
    semantic_lever_status = _frame_transform_semantic_lever_status(
        source_text=source_text,
        operator_filter=operator_filter,
        frame_reservation_delta=frame_reservation_delta,
        probes=probes,
        scan_status=semantic_scan_status,
    )
    frame_report["semantic_lever_status"] = semantic_lever_status

    variants: list[dict[str, Any]] = []
    generated_source_dir, generated_probe_paths = (
        _materialize_frame_transform_probe_sources(
            probes,
            output_dir=output_dir,
            json_out=json_out,
        )
    )
    candidate_probe_by_label: dict[str, dict[str, Any]] = {}

    def _score_candidate(
        *,
        label: str,
        operator: str,
        path: Path,
        source_retained: Path | None = None,
    ) -> None:
        probe_payload = candidate_probe_by_label.get(label)
        try:
            candidate_source_text: str | None = None
            if path.suffix == ".txt":
                candidate_text = path.read_text(encoding="utf-8", errors="replace")
            elif path.suffix == ".c":
                candidate_source_text, _ = (
                    _prevalidate_lifetime_layout_source_candidate(
                        path,
                        function=function,
                    )
                )
                try:
                    candidate_text = compile_source_variant(
                        DiffInput(
                            label=label,
                            token=str(path),
                            kind="source",
                            path=path,
                        ),
                        function=function,
                        melee_root=melee_root,
                        timeout=timeout,
                    )
                except CompileFailure as exc:
                    detail = str(exc)
                    if exc.returncode == 3 and "not found in pcdump" in detail:
                        raise _MalformedSourceCandidate(
                            (
                                f"{detail}; compiled probe pcdump omitted the "
                                f"target function. Source retained at {path}"
                            ),
                            source_hunk=_compact_source_hunk_for_function(
                                candidate_source_text,
                                function,
                            ),
                        ) from exc
                    raise
            else:
                raise ValueError(f"expected .txt pcdump or .c source, got {path}")

            real_score = _SourceCandidateRealScore(None, None)
            if score_match_percent and path.suffix == ".c":
                status = (
                    _make_real_score_status("frame-transform-search", label)
                    if not json_out
                    else None
                )
                real_score = _score_source_candidate_real_tree(
                    path,
                    function=function,
                    melee_root=melee_root,
                    timeout=timeout,
                    status=status,
                    include_stack_slot=False,
                )
            frame_model = _frame_transform_variant_frame_model(
                candidate_text,
                function,
            )
            variant = _frame_transform_variant_from_model(
                label=label,
                operator=operator,
                path=path,
                frame_model=frame_model,
                current_frame_size=current_frame_size,
                expected_frame_size=expected_frame_size,
                match_percent=real_score.match_percent,
                match_percent_error=real_score.match_percent_error,
                source_retained=source_retained or (path if path.suffix == ".c" else None),
            )
            _attach_frame_transform_probe_payload(variant, probe_payload)
            variants.append(variant)
        except Exception as exc:
            malformed_source = isinstance(exc, _MalformedSourceCandidate)
            failed = {
                "label": label,
                "operator": operator,
                "status": "malformed-source" if malformed_source else "failed",
                "path": str(path),
                "error": str(exc),
            }
            if source_retained is not None:
                failed["source_retained"] = str(source_retained)
            elif path.suffix == ".c" and path.exists():
                failed["source_retained"] = str(path)
            if malformed_source and exc.source_hunk:
                failed["source_hunk"] = exc.source_hunk
            _attach_frame_transform_probe_payload(failed, probe_payload)
            variants.append(failed)

    for spec in candidates or []:
        label, operator, path = _parse_lifetime_layout_candidate(spec)
        _score_candidate(label=label, operator=operator, path=path)

    if compile_probes:
        if source_text is None and not candidates:
            typer.echo(
                "--compile-probes requires --source-file, repo source, or "
                "--candidate OPERATOR=path.",
                err=True,
            )
            raise typer.Exit(2)
        if probes:
            probe_dir = generated_source_dir
            if probe_dir is None:
                probe_dir = Path(tempfile.mkdtemp(prefix="melee_frame_transform_"))
                probe_dir.mkdir(parents=True, exist_ok=True)
                generated_source_dir = probe_dir
            start_idx = len(variants)
            try:
                for probe in probes:
                    path = generated_probe_paths.get(probe.label)
                    if path is None:
                        path = probe_dir / f"{probe.label}.c"
                        path.write_text(probe.source_text)
                        generated_probe_paths[probe.label] = path
                    candidate_probe_by_label[probe.label] = probe.to_dict()
                    _score_candidate(
                        label=probe.label,
                        operator=probe.operator,
                        path=path,
                        source_retained=path,
                    )
            finally:
                generated_failed = any(
                    variant["status"] != "ok" for variant in variants[start_idx:]
                )
                retain_generated = generated_failed or json_out or output_dir is not None
                if not retain_generated:
                    shutil.rmtree(probe_dir, ignore_errors=True)

    evaluation = evaluate_frame_transform_probe_results(frame_report, variants)
    ranked_variants = evaluation.get("variants")
    if not isinstance(ranked_variants, list):
        ranked_variants = variants
    elif not ranked_variants and variants:
        ranked_variants = variants
    stop_condition = evaluation.get("stop_condition")

    if json_out:
        payload = {
            "function": function,
            "ranking": _FRAME_TRANSFORM_RANKING,
            "baseline_pcdump": str(pcdump_path),
            "source": source_label,
            "frame_report": frame_report,
            "probe_plan": probe_plan,
            "operator_filter": list(operator_filter),
            "semantic_lever_status": semantic_lever_status,
            "generated_source_dir": (
                str(generated_source_dir) if generated_source_dir is not None else None
            ),
            "probes": [
                {
                    **probe.to_dict(),
                    **(
                        {"source_retained": str(generated_probe_paths[probe.label])}
                        if probe.label in generated_probe_paths
                        else {}
                    ),
                }
                for probe in probes
            ],
            "variants": ranked_variants,
            "frame_transform_probe_evaluation": evaluation,
            "stop_condition": stop_condition,
        }
        print(json.dumps(payload, indent=2))
        return

    current_frame = (frame_report.get("current") or {}).get("frame_size")
    expected_frame = (
        (frame_report.get("expected") or {}).get("frame_size")
        if isinstance(frame_report.get("expected"), Mapping)
        else None
    )
    print(f"frame-transform-search - {function}")
    print(f"ranking: {_FRAME_TRANSFORM_RANKING}")
    print(f"baseline: frame={current_frame if current_frame is not None else '?'}")
    print(f"expected: frame={expected_frame if expected_frame is not None else '?'}")
    print("operator filter: " + ", ".join(operator_filter))
    if semantic_lever_status.get("status") not in {"not-needed"}:
        print(
            "semantic lever: "
            f"{semantic_lever_status.get('status')}"
            f" [{semantic_lever_status.get('operator')}]"
        )
    if generated_source_dir is not None:
        print(f"generated source dir: {generated_source_dir}")
    print(
        "verdict: "
        f"{evaluation.get('verdict')} ({(stop_condition or {}).get('kind')})"
    )
    if stop_condition:
        print(f"stop condition: {stop_condition.get('reason')}")
    if ranked_variants:
        print("Variants:")
        for variant in ranked_variants:
            if variant.get("status") == "ok":
                print(
                    f"{variant.get('rank', '?')}. {variant['label']} "
                    f"[{variant['operator']}] frame="
                    f"{variant.get('candidate_frame_size')} remaining_delta="
                    f"{variant.get('remaining_frame_delta')} improvement="
                    f"{variant.get('frame_delta_improvement')}"
                )
                if variant.get("match_percent") is not None:
                    print(f"  match_percent: {variant['match_percent']:.6g}")
                if variant.get("description"):
                    print(f"  action: {variant['description']}")
                if variant.get("source_retained"):
                    print(f"  source: {variant['source_retained']}")
            else:
                print(
                    f"- {variant['label']} [{variant['operator']}] failed: "
                    f"{variant.get('error')}"
                )
                if variant.get("source_retained"):
                    print(f"  source: {variant['source_retained']}")
    elif probes:
        print("Probes:")
        for probe in probes:
            print(f"- {probe.label} [{probe.operator}]: {probe.description}")
        print("Variants: none; pass --compile-probes or --candidate OPERATOR=path.")
    else:
        print("Variants: none; pass --source-file or --candidate OPERATOR=path.")


def _render_gate_rejected_distribution(
    result,
    target: tuple[int, ...],
    *,
    top_n: int = 5,
) -> None:
    """Print the gate-rejected diagnostic: prefix-length histogram + top-N.

    Diagnostic is the answer to "did permuter ever produce a candidate that
    moved simplify-order toward target, even if it also disturbed precolor?"
    Without scoring rejected candidates we can't tell — the gate strips them
    out and we'd only see the count. This renderer surfaces:

      1. Histogram of `common_prefix_length` across all rejected candidates.
         A bin at len(target) means "permuter CAN produce the exact target
         order, just with precolor changes" — strong signal to consider a
         distance-metric gate.
      2. Top-N rejected candidates by `common_prefix_length` desc, with
         observed prefix and the gate's rejection reason for each.

    Renders nothing when `result.rejected_scored` is empty.

    Kept as a standalone function (not inline in the CLI command body) so
    it can be unit-tested directly and so a parallel per-adapter breakdown
    can land alongside without merge conflict.
    """
    rejected = result.rejected_scored
    if not rejected:
        return

    print(f"Gate-rejected diagnostic (n={len(rejected)}):")

    # Histogram by common_prefix_length. Build a sorted list of all bins
    # that appear plus the target-length bin so we always render it (even
    # at 0) since it's the headline signal.
    target_len = len(target)
    bins: dict[int, int] = {}
    for rc in rejected:
        bins[rc.score.common_prefix_length] = (
            bins.get(rc.score.common_prefix_length, 0) + 1
        )
    bins.setdefault(target_len, 0)

    print("  Common-prefix length distribution:")
    # Max width for column alignment, computed from the bins we'll print.
    max_count = max(bins.values()) if bins else 0
    count_width = max(3, len(str(max_count)))
    for length in sorted(bins):
        count = bins[length]
        label = f"prefix={length}"
        marker = "  <- target length" if length == target_len else ""
        # Pad label to a stable column width so the counts line up.
        print(f"    {label:<12} {count:>{count_width}} candidates{marker}")

    # Top-N by common_prefix_length descending. Ties broken by provenance
    # so the order is deterministic for tests.
    print()
    sorted_rejected = sorted(
        rejected,
        key=lambda rc: (-rc.score.common_prefix_length, rc.provenance),
    )
    shown = sorted_rejected[:top_n]
    print(f"  Best {len(shown)} gate-rejected by simplify-order:")
    for rc in shown:
        s = rc.score
        observed = ",".join(str(x) for x in s.observed_prefix) or "(empty)"
        # Annotate with precolor distance so the reader can spot
        # candidates that almost-preserved-precolor at a glance — pairs
        # naturally with the rank-combined ranking, but is a free
        # improvement to the existing diagnostic too.
        distance = rc.precolor_distance.total
        print(
            f"    {rc.provenance}: prefix={s.common_prefix_length}/"
            f"{len(s.target_prefix)} (observed: {observed}) "
            f"(distance={distance})"
        )
        print(f"       rejected: {rc.rejection_reason}")
    print()


class RankMode(str, Enum):
    """Ranking mode for `debug mutate simplify-order`'s headline output.

    `lex` (default, calibration-free): sort by common_prefix_length DESC
    then total precolor distance ASC. Surfaces target-hitting candidates
    first regardless of disturbance magnitude — robust across functions,
    target lengths, and mutation libraries.

    `combined` (legacy, requires α tuning): sort by
    `prefix_ratio - alpha * distance`. Useful when the user wants a
    continuous trade-off and is willing to calibrate alpha to the
    campaign's distance distribution.
    """

    lex = "lex"
    combined = "combined"


def _unified_candidates(
    result,
) -> list[tuple[str, object, object, str | None]]:
    """Merge gate-passing and gate-rejected candidates into a single list.

    Returns tuples of (provenance, simplify_score, precolor_distance,
    rejection_reason_or_None). `None` reason marks a passing candidate;
    a non-None string marks a gate-rejected one.

    Shared by both the lex and combined renderers so they can never drift
    on which buckets they pull from. The two modes only differ in their
    sort key and per-row rendering.
    """
    rows: list[tuple[str, object, object, str | None]] = []
    for sv in result.progress:
        rows.append((
            sv.variant.provenance,
            sv.score,
            sv.precolor_distance,
            None,
        ))
    for rc in result.rejected_scored:
        rows.append((
            rc.provenance,
            rc.score,
            rc.precolor_distance,
            rc.rejection_reason,
        ))
    return rows


def _render_combined_score_ranking(
    result,
    target: tuple[int, ...],
    *,
    alpha: float,
    top_n: int = 8,
) -> None:
    """Print the unified combined-score ranking across passing + rejected.

    Builds the combined score per candidate on the fly (so the alpha can
    change at render time without re-running the search). Pulls candidates
    from BOTH `result.progress` and `result.rejected_scored` — that's the
    point of the unified ranking: when permuter produces a candidate that
    hits the target simplify order but disturbs precolor by 1 edge, it
    should beat a candidate that preserves precolor but stays at prefix=0.

    Renders nothing when there are no compiled candidates to rank.
    """
    from ..mwcc_debug.simplify_search import combined_value

    rows = _unified_candidates(result)
    if not rows:
        return

    # Score on the fly via the shared helper so the renderer and the
    # `combined_score` function can never drift in formula or alpha
    # semantics.
    scored: list[tuple[float, str, object, object, str | None]] = []
    for prov, s, dist, reason in rows:
        combined = combined_value(s, dist, target, alpha)
        scored.append((combined, prov, s, dist, reason))

    # Sort: combined DESC, ties broken deterministically by provenance.
    scored.sort(key=lambda r: (-r[0], r[1]))
    shown = scored[:top_n]

    print(f"Best by combined score (alpha={alpha}, top {len(shown)}):")
    for combined, prov, s, dist, reason in shown:
        observed = ",".join(str(x) for x in s.observed_prefix) or "(empty)"
        print(
            f"  {prov}: combined={combined:.3f}  "
            f"prefix={s.common_prefix_length}/{len(s.target_prefix)} "
            f"(observed: {observed})"
        )
        print(
            f"     precolor distance: "
            f"IG +{dist.ig_added}/-{dist.ig_removed}, "
            f"coalesce +{dist.coalesce_added}/-{dist.coalesce_removed}, "
            f"spills +{dist.spill_added}/-{dist.spill_removed} "
            f"(total={dist.total})"
        )
        if reason:
            print(f"     gate rejected: {reason}")
        else:
            print(f"     gate passed")
    print()


def _render_lex_ranking(
    result,
    target: tuple[int, ...],
    *,
    top_n: int = 8,
) -> None:
    """Print the unified lexicographic ranking across passing + rejected.

    Sort key: `common_prefix_length` DESC primary, total precolor distance
    ASC secondary, provenance ASC tertiary (for deterministic ties).

    This is the calibration-free successor to combined-score ranking. The
    combined formula `ratio - alpha * distance` depends on knowing the
    campaign's distance scale to pick alpha; lex sidesteps that entirely
    by expressing "inspect target-hitting candidates first, lowest-
    disturbance variants of those next" directly as a sort key. No knob
    to tune across functions, target lengths, or mutation libraries.

    Pulls from BOTH `result.progress` and `result.rejected_scored` — same
    unified-list contract as the combined renderer. Renders nothing when
    there are no compiled candidates.
    """
    rows = _unified_candidates(result)
    if not rows:
        return

    # Sort: prefix DESC, distance ASC, provenance ASC. The lex contract
    # is "more prefix is always better; for equal prefix, less precolor
    # disturbance is better."
    rows.sort(key=lambda r: (-r[1].common_prefix_length, r[2].total, r[0]))
    shown = rows[:top_n]

    print(f"Best by simplify-order then distance (top {len(shown)}):")
    for prov, s, dist, reason in shown:
        observed = ",".join(str(x) for x in s.observed_prefix) or "(empty)"
        print(
            f"  {prov}: prefix={s.common_prefix_length}/{len(s.target_prefix)} "
            f"distance={dist.total} (observed: {observed})"
        )
        print(
            f"     precolor distance: "
            f"IG +{dist.ig_added}/-{dist.ig_removed}, "
            f"coalesce +{dist.coalesce_added}/-{dist.coalesce_removed}, "
            f"spills +{dist.spill_added}/-{dist.spill_removed}"
        )
        if reason:
            print(f"     gate rejected: {reason}")
        else:
            print(f"     gate passed")
    print()


def _render_force_phys_ranking(
    result,
    target_phys: dict[int, int],
    *,
    top_n: int = 8,
) -> None:
    """Print the unified force-phys ranking across passing + rejected."""
    rows = _unified_candidates(result)
    if not rows:
        return

    rows.sort(key=lambda r: (-r[1].common_prefix_length, r[2].total, r[0]))
    shown = rows[:top_n]

    target_text = ", ".join(
        f"ig{ig}->r{phys}" for ig, phys in target_phys.items()
    )
    print(f"Best by force-phys target then distance (top {len(shown)}):")
    print(f"  target: {target_text}")
    for prov, s, dist, reason in shown:
        observed = ", ".join(
            f"ig{ig}->r{target_phys[ig]}" for ig in s.observed_prefix
        ) or "(none)"
        print(
            f"  {prov}: hits={s.common_prefix_length}/{len(s.target_prefix)} "
            f"distance={dist.total} (matched: {observed})"
        )
        print(
            f"     precolor distance: "
            f"IG +{dist.ig_added}/-{dist.ig_removed}, "
            f"coalesce +{dist.coalesce_added}/-{dist.coalesce_removed}, "
            f"spills +{dist.spill_added}/-{dist.spill_removed}"
        )
        if reason:
            print(f"     gate rejected: {reason}")
        else:
            print("     gate passed")
    print()


# ---------------------------------------------------------------------------
# --triage post-search composition: real-tree match% ranking
# ---------------------------------------------------------------------------
#
# Layer A of the workflow integration described in
# docs/mwcc-debug-diff-roadmap.md. After the simplify-order search
# completes its harvest, optionally invoke `debug permute triage` on the
# permuter output dir to surface a second ranking by *actual* real-tree
# match% — the ground-truth metric. Closes the methodology gap exposed by
# the grVenom_80204284 campaign, where the manual survey ranked by
# simplify-order distance and missed output-180-1 (the real fix at 100%)
# because it lived below the inspection cutoff.
#
# Subprocess vs library call: the existing `debug permute triage` command
# is tightly coupled to typer/CLI internals (in-loop typer.echo, JSON-vs-
# text branching, apply_best side effects). Subprocess composition via its
# stable `--json` interface is the MVP-correct choice — it preserves the
# existing logic untouched, gives us a deterministic parsed result, and
# isolates triage failures from the main command's exit code. If the
# triage logic later needs to be reused in three+ places, refactor to a
# library function then; today, subprocess is the right tool.


@dataclasses.dataclass(frozen=True)
class _TriageResult:
    """Captured output of one `debug permute triage --json` invocation.

    `data` is the parsed JSON payload when the subprocess succeeded
    *and* produced valid JSON; `None` in every other case.

    `parse_error` distinguishes the two failure modes when `data is
    None`:

    - `None` means the subprocess itself failed (`returncode != 0`); the
      caller emits the "Triage subprocess failed" wording.
    - A non-`None` string means the subprocess returned exit 0 but its
      stdout wasn't parseable JSON; the caller emits a distinct
      "exited cleanly but produced unparseable JSON output" wording so
      the user isn't confused by "subprocess failed; exit code: 0".

    Without this split, both branches funnel into the same error message
    and the user can't tell whether the subprocess crashed or just
    produced garbage stdout (each has different remediation).
    """

    returncode: int
    stdout: str
    stderr: str
    data: Optional[dict]
    parse_error: Optional[str] = None


def _run_triage_subprocess(
    perm_dir: Path,
    function: str,
    melee_root: Path,
) -> _TriageResult:
    """Invoke `python -m src.cli debug permute triage <perm_dir> -f <fn> --json`.

    Returns a `_TriageResult` with the subprocess exit code, captured
    stdout/stderr, the parsed JSON payload (or None), and a
    `parse_error` string when the subprocess succeeded but stdout
    wasn't parseable JSON (see `_TriageResult` for why this is split
    from the generic "data is None" case).

    Isolated as its own function so tests can monkeypatch the subprocess
    invocation without intercepting `subprocess.run` globally — there are
    other subprocess calls in this file (ninja, objdiff-cli) that we don't
    want to fake.

    Cycle time: each triage candidate costs ~5-10s (ninja + report.json
    regen). A 200-candidate harvest is ~30 minutes; a 20-candidate harvest
    is ~3 minutes. The caller emits a progress message before invocation
    so the user knows what they're waiting on.
    """
    cli_root = Path(__file__).resolve().parent.parent.parent
    cmd = [
        sys.executable, "-m", "src.cli",
        "debug", "permute", "triage",
        str(perm_dir),
        "--function", function,
        "--json",
    ]
    proc = subprocess.run(
        cmd,
        cwd=cli_root,
        capture_output=True,
        text=True,
    )
    parsed: Optional[dict] = None
    parse_error: Optional[str] = None
    if proc.returncode == 0:
        try:
            parsed = json.loads(proc.stdout)
        except (ValueError, json.JSONDecodeError) as exc:
            # Subprocess succeeded but stdout wasn't JSON. Record the
            # parse error so the caller can emit the distinct
            # "unparseable JSON" wording rather than the misleading
            # "subprocess failed" wording.
            parse_error = str(exc)
            parsed = None
    return _TriageResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        data=parsed,
        parse_error=parse_error,
    )


def _render_triage_ranking(
    triage_data: dict,
    *,
    result,
    perm_dir: Path,
    top_n: int = 8,
    rank_mode: Optional["RankMode"] = None,
    combined_alpha: float = 0.001,
    target: tuple[int, ...] = (),
) -> None:
    """Print the 'Best by real-tree match%' section.

    Pulls candidates from `triage_data["results"]` (status='ok' only —
    build-failed and no-function rows have no match%), sorts by match%
    DESC, and renders the top N with provenance, match%, delta vs
    baseline, and the cross-ranking position of the same candidate in
    the simplify-order results above.

    The cross-ranking honors the user's `--rank-mode`:

    - `lex` (default): sort by lex key (`prefix DESC, distance ASC,
      provenance`), annotation label is `simplify-order rank #N`.
    - `combined`: sort by combined-score key (`combined DESC, provenance`),
      annotation label is `combined rank #N`.

    Mode-aware so the rank annotation points at the same table the user
    sees above. Without this, a user in combined mode would get a
    `simplify-order rank #N` annotation that disagrees with the
    "Best by combined score" table — confusing.

    `rank_mode=None` is treated as lex (backward-compatible default for
    callers that pre-date the rank-mode threading).

    If any candidate hit 100.00%, surface a *** FIX FOUND *** banner
    BEFORE the ranking section — the headline a campaign agent needs to
    see first.
    """
    # Late import to avoid a forward-reference loop with the RankMode
    # enum below this module's class-definition order.
    if rank_mode is None:
        rank_mode = RankMode.lex

    results = triage_data.get("results") or []
    baseline_pct = triage_data.get("baseline_pct") or 0.0

    # Drop non-ok rows (build-failed / no-function); we only rank
    # candidates that produced a usable real-tree match%.
    ok = [r for r in results if r.get("status") == "ok"
          and r.get("match_pct") is not None]

    if not ok:
        print("Triage: no candidates produced a usable real-tree match%.")
        if results:
            n_build_failed = sum(
                1 for r in results if r.get("status") == "build-failed"
            )
            n_no_fn = sum(
                1 for r in results if r.get("status") == "no-function"
            )
            print(f"  ({n_build_failed} build failed, {n_no_fn} missing function)")
        print()
        return

    # Sort by match% DESC; tiebreak by path so output is deterministic.
    ok_sorted = sorted(
        ok,
        key=lambda r: (-(r.get("match_pct") or 0.0), str(r.get("path") or "")),
    )

    # Build the cross-ranking lookup, keyed by output dir name. Sort key
    # matches whichever ranking table was rendered above so the
    # cross-references stay consistent. If a candidate isn't in the
    # simplify-order results (cross-source dedup, compile failure inside
    # search, etc.), report "n/a".
    from ..mwcc_debug.simplify_search import combined_value

    so_rank: dict[str, int] = {}
    so_rows = _unified_candidates(result)
    if rank_mode is RankMode.combined:
        # Same sort key as `_render_combined_score_ranking`:
        # (-combined_value, provenance ASC).
        so_rows_sorted = sorted(
            so_rows,
            key=lambda r: (-combined_value(r[1], r[2], target, combined_alpha),
                           r[0]),
        )
        rank_label = "combined rank"
    else:
        # Lex (default): same key as `_render_lex_ranking`.
        so_rows_sorted = sorted(
            so_rows,
            key=lambda r: (-r[1].common_prefix_length, r[2].total, r[0]),
        )
        rank_label = "simplify-order rank"
    for i, (prov, _s, _d, _r) in enumerate(so_rows_sorted, 1):
        # Provenance for permuter rows looks like
        # "permuter output-NNNN-N/source.c"; extract the output dir name.
        if prov.startswith("permuter "):
            out_name = prov[len("permuter "):].split("/", 1)[0]
            so_rank[out_name] = i

    # Headline: if any candidate is 100%, lead with the FIX FOUND banner
    # so a skimming reader can't miss it. Threshold uses the same
    # float-precision epsilon as the existing triage WIN check.
    EPS = 1e-9
    top_candidate = ok_sorted[0]
    top_pct = top_candidate.get("match_pct") or 0.0
    if top_pct >= 100.00 - EPS:
        top_path = Path(str(top_candidate.get("path") or ""))
        top_dir = top_path.parent.name
        print("=" * 70)
        print("*** FIX FOUND ***")
        print(f"permuter {top_dir} produces {top_pct:.2f}% match "
              f"(baseline {baseline_pct:.2f}%).")
        print(f"Apply with: cp {top_path} <real-source-path>")
        print(f"            (or use `debug permute verify --apply` to stage it)")
        print("=" * 70)
        print()

    shown = ok_sorted[:top_n]
    print(f"Best by real-tree match% "
          f"(top {len(shown)}, baseline {baseline_pct:.2f}%):")
    for i, r in enumerate(shown, 1):
        path = Path(str(r.get("path") or ""))
        out_dir = path.parent.name
        pct = r.get("match_pct") or 0.0
        delta = r.get("delta") or 0.0
        so_pos = so_rank.get(out_dir)
        so_pos_str = (
            f"{rank_label} #{so_pos}" if so_pos is not None
            else f"{rank_label} n/a"
        )
        print(f"  {i}. permuter {out_dir}: {pct:.2f}%  "
              f"(delta {delta:+.2f}%, {so_pos_str})")
    print()


def _maybe_run_triage(
    *,
    triage_enabled: bool,
    with_permuter: bool,
    permuter_dir_resolved: Optional[Path],
    function: str,
    melee_root: Path,
    result,
    rank_mode: Optional["RankMode"] = None,
    combined_alpha: float = 0.001,
    target: tuple[int, ...] = (),
) -> None:
    """Compose `debug permute triage` after the simplify-order search.

    Encapsulates the four prerequisite checks (triage flag set,
    --with-permuter set, permuter dir resolved & non-empty, search
    completed) plus error capture and section rendering. Called from the
    CLI command body after all the existing rendering, before its early
    exits.

    `rank_mode` / `combined_alpha` / `target` are threaded through to
    `_render_triage_ranking` so the triage section's cross-rank
    annotation references the same ordering as the headline ranking
    table the user already saw above. Defaults preserve the original
    lex-mode behavior for any test or future caller that doesn't supply
    the mode explicitly.

    Designed so failures here never crash the parent command — the
    simplify-order rankings already rendered are still useful even when
    triage is unavailable.
    """
    if not triage_enabled:
        return

    if not with_permuter:
        typer.echo(
            "--triage requires permuter candidates; "
            "pass --with-permuter to enable. Skipping triage.",
            err=True,
        )
        return

    if permuter_dir_resolved is None or not permuter_dir_resolved.is_dir():
        # The --with-permuter branch above already printed an explanation
        # for why the permuter dir wasn't usable; just record that triage
        # is skipped without re-explaining.
        typer.echo(
            "--triage: no permuter dir available; nothing to triage.",
            err=True,
        )
        return

    # Count candidates before invoking the subprocess so we can emit an
    # accurate progress estimate and skip cleanly when the harvest is empty.
    # Guards against OSError (permissions, racey reads) — the triage
    # subprocess would error out anyway, but a clean early-skip is friendlier.
    try:
        candidate_count = sum(
            1 for d in permuter_dir_resolved.iterdir()
            if d.is_dir() and (d / "source.c").exists()
        )
    except OSError as exc:
        typer.echo(
            f"--triage: could not enumerate {permuter_dir_resolved} ({exc}); "
            f"skipping triage.",
            err=True,
        )
        return
    if candidate_count == 0:
        typer.echo(
            f"--triage: no candidate sources in {permuter_dir_resolved}; "
            f"nothing to triage.",
            err=True,
        )
        return

    print("=" * 70)
    print(f"Running triage on {candidate_count} candidate(s); this may "
          f"take a few minutes...")
    print("=" * 70)
    print()

    triage = _run_triage_subprocess(
        permuter_dir_resolved, function, melee_root,
    )

    reproducer = (
        f"  reproduce: python -m src.cli debug permute triage "
        f"{permuter_dir_resolved} --function {function} --json"
    )

    if triage.data is None and triage.returncode == 0:
        # Subprocess exited cleanly but stdout wasn't parseable JSON
        # (`_run_triage_subprocess` sets `parse_error` in this case, but
        # we dispatch on `returncode == 0` for robustness against
        # external stubbing). Distinct from a subprocess failure — the
        # remediation is different (look at what the subprocess printed,
        # not its exit handling).
        print("Triage subprocess exited cleanly but produced unparseable "
              "JSON output; main report above is unaffected.")
        print(f"  exit code: {triage.returncode}")
        if triage.parse_error:
            print(f"  parse error: {triage.parse_error}")
        # Show a snippet of the stdout so the user can see what came out.
        # 200 chars is enough to recognize an error message / banner /
        # ANSI escape sequence without flooding the report.
        snippet = triage.stdout[:200].replace("\n", "\\n")
        more = "..." if len(triage.stdout) > 200 else ""
        print(f"  stdout (first 200 chars): {snippet}{more}")
        print(reproducer)
        print()
        return

    if triage.data is None:
        # Subprocess failed (non-zero exit). Surface what went wrong so
        # the user has a chance to debug, but don't crash — the main
        # report above is still useful.
        print("Triage subprocess failed; main report above is unaffected.")
        print(f"  exit code: {triage.returncode}")
        if triage.stderr.strip():
            # Cap stderr output to keep the report readable; reproducing
            # the full failure is what the exit code + reproducer command
            # is for.
            stderr_lines = triage.stderr.strip().splitlines()
            print("  stderr (first 5 lines):")
            for line in stderr_lines[:5]:
                print(f"    {line}")
        print(reproducer)
        print()
        return

    _render_triage_ranking(
        triage.data,
        result=result,
        perm_dir=permuter_dir_resolved,
        rank_mode=rank_mode,
        combined_alpha=combined_alpha,
        target=target,
    )


@mutate_app.command(name="simplify-order")
def mutate_simplify_order_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--fn", "--function", "-f",
            help="Function to search.",
        ),
    ],
    want_first: Annotated[
        Optional[str],
        typer.Option(
            "--want-first",
            help="Comma-separated target ig_idx sequence to land at the "
                 "head of simplify order (e.g. '42,32'). Mutually exclusive "
                 "with --want-late.",
        ),
    ] = None,
    want_late: Annotated[
        Optional[str],
        typer.Option(
            "--want-late",
            help="Comma-separated target ig_idx sequence to land at the "
                 "TAIL of simplify order (e.g. '46,44'). Mutually exclusive "
                 "with --want-first. Use when the target nodes must be "
                 "simplified last.",
        ),
    ] = None,
    class_id: Annotated[
        int,
        typer.Option(
            "--class",
            help="Register class to target. 0 = GPR (default).",
        ),
    ] = 0,
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help="Score variants by force-phys assignment hits instead of "
                 "simplify-order proximity. Accepts IG:PHYS or CLASS:IG:PHYS "
                 "pairs, e.g. '53:4' or '0:53:4'. Mutually exclusive with "
                 "--want-first/--want-late.",
        ),
    ] = None,
    preserve_precolor: Annotated[
        bool,
        typer.Option(
            "--preserve-precolor/--no-preserve-precolor",
            help="Reject variants that disturb the pre-coloring shape "
                 "(interference graph, coalesce mappings, spill set). "
                 "On by default.",
        ),
    ] = True,
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            help="Cap on variant compilation count.",
        ),
    ] = 100,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout", "-t",
            help="Per-compile timeout in seconds.",
        ),
    ] = 60,
    with_permuter: Annotated[
        bool,
        typer.Option(
            "--with-permuter",
            help="Also harvest pre-existing decomp-permuter output dirs "
                 "(<perm_root>/nonmatchings/<fn>/output-*/source.c). The "
                 "user runs permuter separately; this flag just adds the "
                 "permuter outputs to the variant stream. If no permuter "
                 "output is found a one-line hint is printed and the "
                 "search continues with the other adapters.",
        ),
    ] = False,
    permuter_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--permuter-dir",
            help="Override path resolution for --with-permuter. Defaults "
                 "to <perm_root>/nonmatchings/<fn>/ via MELEE_PERMUTER_ROOT "
                 "or ~/code/decomp-permuter.",
        ),
    ] = None,
    rank_mode: Annotated[
        RankMode,
        typer.Option(
            "--rank-mode",
            help="Ranking mode for the headline output. 'lex' (default, "
                 "calibration-free): sort all compiled candidates by "
                 "common_prefix_length DESC then total precolor distance "
                 "ASC. 'combined': sort by `prefix_ratio - alpha * distance` "
                 "(see --combined-alpha). Both pull from gate-passing AND "
                 "gate-rejected candidates uniformly; --preserve-precolor "
                 "still controls the binary gate.",
        ),
    ] = RankMode.lex,
    rank_combined: Annotated[
        bool,
        typer.Option(
            "--rank-combined/--no-rank-combined",
            help="Deprecated alias for --rank-mode combined. Kept for "
                 "backward compatibility with existing campaign scripts; "
                 "prefer --rank-mode combined in new code.",
        ),
    ] = False,
    combined_alpha: Annotated[
        float,
        typer.Option(
            "--combined-alpha",
            help="Weight on precolor distance in the combined score "
                 "(combined = prefix_ratio - alpha * distance). Higher alpha "
                 "punishes disturbance more. Only meaningful with "
                 "--rank-mode combined; ignored under lex. Default 0.001, "
                 "calibrated against observed permuter distance ranges "
                 "(100-300+) so prefix=N candidates outrank prefix=(N-1) "
                 "regardless of distance.",
        ),
    ] = 0.001,
    triage: Annotated[
        bool,
        typer.Option(
            "--triage/--no-triage",
            help="After the simplify-order harvest completes, invoke "
                 "`debug permute triage` on the permuter output dir and "
                 "append a second ranking by real-tree match% (the ground "
                 "truth). Requires --with-permuter. Closes the methodology "
                 "gap from the grVenom_80204284 campaign — where the actual "
                 "fix lived at output-180-1 but was buried below the "
                 "manual-inspection cutoff because the survey ranked by "
                 "simplify-order distance (a search-side proxy) instead of "
                 "match% (the ground-truth metric). If a 100% candidate is "
                 "found, the report surfaces a *** FIX FOUND *** banner so "
                 "future campaign agents can't miss it. Adds ~5-10s per "
                 "candidate to the run.",
        ),
    ] = False,
) -> None:
    """Search for source variants that produce a desired simplify order.

    Useful for stuck functions where the RA-input breakdown shows that
    simplify order is the only diverging input component. The search
    iterates variants from the existing source-mutation primitives
    (decl-orders, insert-alias, holder-lifetime, type-change), gates them on the
    preserve-precolor invariant, and ranks survivors by how much of the
    target prefix they reproduce.

    With ``--with-permuter``, pre-existing decomp-permuter output dirs
    are also harvested (no permuter is launched — run permuter
    separately first).

    Example:

      melee-agent debug mutate simplify-order \\
          --fn grVenom_80204284 --want-first '42,32'
    """
    from ..mwcc_debug.diff_capture import CompileFailure
    from ..mwcc_debug.simplify_search import (
        FunctionContext,
        baseline_signature,
        search,
    )
    from ..mwcc_debug.simplify_variants import (
        decl_orders_source,
        holder_lifetime_source,
        insert_alias_source,
        type_change_source,
    )
    from ..mwcc_debug.simplify_variants_permuter import (
        permuter_source,
        resolve_permuter_function_dir,
    )

    melee_root = DEFAULT_MELEE_ROOT

    # Mutual exclusion and at-least-one validation for objective selectors.
    if want_first is not None and want_late is not None:
        typer.echo(
            "error: --want-first and --want-late are mutually exclusive",
            err=True,
        )
        raise typer.Exit(2)
    objective_count = sum(
        option is not None for option in (want_first, want_late, force_phys)
    )
    if objective_count == 0:
        typer.echo(
            "error: must specify exactly one of --want-first, --want-late, "
            "or --force-phys",
            err=True,
        )
        raise typer.Exit(2)
    if objective_count > 1:
        typer.echo(
            "error: --want-first, --want-late, and --force-phys are "
            "mutually exclusive",
            err=True,
        )
        raise typer.Exit(2)

    # Parse the chosen flag into target / target_late tuples.
    target: tuple[int, ...] = ()
    target_late: tuple[int, ...] = ()
    force_phys_target: dict[int, int] = {}
    force_phys_normalized: Optional[str] = None

    if want_first is not None:
        raw = want_first.strip()
        if not raw:
            typer.echo("--want-first cannot be empty", err=True)
            raise typer.Exit(2)
        try:
            target = tuple(int(x.strip()) for x in raw.split(",") if x.strip())
        except ValueError:
            typer.echo(
                f"--want-first expects comma-separated integers; got {want_first!r}",
                err=True,
            )
            raise typer.Exit(2)
        if not target:
            typer.echo("--want-first parsed to an empty sequence", err=True)
            raise typer.Exit(2)

    if want_late is not None:
        raw_late = want_late.strip()
        if not raw_late:
            typer.echo("--want-late cannot be empty", err=True)
            raise typer.Exit(2)
        try:
            target_late = tuple(
                int(x.strip()) for x in raw_late.split(",") if x.strip()
            )
        except ValueError:
            typer.echo(
                f"--want-late expects comma-separated integers; got {want_late!r}",
                err=True,
            )
            raise typer.Exit(2)
        if not target_late:
            typer.echo("--want-late parsed to an empty sequence", err=True)
            raise typer.Exit(2)

    if force_phys is not None:
        try:
            entries, force_phys_normalized, _warnings = (
                _parse_diagnose_force_phys(force_phys)
            )
        except typer.BadParameter as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(2) from exc
        force_phys_target = {
            entry.virtual: entry.phys
            for entry in entries
            if (class_id if entry.class_id is None else entry.class_id) == class_id
        }
        if not force_phys_target:
            available = ", ".join(
                str(class_id if entry.class_id is None else entry.class_id)
                for entry in entries
            )
            typer.echo(
                f"error: --force-phys has no entries for class {class_id} "
                f"(entry classes: {available})",
                err=True,
            )
            raise typer.Exit(2)

    # Resolve the unit + source for the function.
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"function not found in report.json: {function}", err=True)
        raise typer.Exit(2)
    source_path = melee_root / "src" / f"{unit}.c"
    if not source_path.exists():
        typer.echo(f"source not found: {source_path}", err=True)
        raise typer.Exit(2)

    ctx = FunctionContext(
        function=function,
        unit=unit,
        source_path=source_path,
        melee_root=melee_root,
    )

    # Compile the baseline once to get its BaselineSignature.
    from ..mwcc_debug.diff_capture import DiffInput, compile_source_variant

    diff_input = DiffInput(
        label="baseline",
        token=str(source_path),
        kind="source",
        path=source_path,
    )
    try:
        baseline_pcdump = compile_source_variant(
            diff_input,
            function=function,
            melee_root=melee_root,
            timeout=timeout,
        )
    except CompileFailure as exc:
        typer.echo(f"baseline compile failed:\n{exc}", err=True)
        raise typer.Exit(3)

    baseline_events = parse_hook_events(baseline_pcdump)
    base_for_fn = next((e for e in baseline_events if e.name == function), None)
    if base_for_fn is None:
        typer.echo(
            f"baseline pcdump has no events for {function}; "
            "is the function actually compiled into this TU?",
            err=True,
        )
        raise typer.Exit(3)

    # Validate --class against what the function actually exercises. Union
    # of all sections so we surface classes that appear in any of
    # colorgraph / simplify / coalesce (some classes show up in coalesce
    # but not colorgraph if everything coalesced cleanly).
    available_classes = sorted({
        s.class_id for s in base_for_fn.colorgraph_sections
    } | {
        s.class_id for s in base_for_fn.simplify_sections
    } | {
        s.class_id for s in base_for_fn.coalesce_sections
    })
    if available_classes and class_id not in available_classes:
        ids = ", ".join(str(c) for c in available_classes)
        typer.echo(
            f"class {class_id} not present in {function}; "
            f"available class IDs: {ids}",
            err=True,
        )
        raise typer.Exit(3)

    baseline_sig = baseline_signature(base_for_fn, class_id=class_id)

    if not baseline_sig.simplify_order and not force_phys_target:
        typer.echo(
            f"baseline has no simplify-graph entries for class {class_id}; "
            "the function may not exercise that register class.",
            err=True,
        )
        raise typer.Exit(3)

    print(f"Function:        {function}")
    print(f"Source:          {source_path}")
    print(f"Class:           {class_id}")
    if force_phys_target:
        target_force_text = ",".join(
            f"{ig}:r{phys}" for ig, phys in force_phys_target.items()
        )
        print(f"Target force-phys: {target_force_text}")
        if force_phys_normalized is not None:
            print(f"Force-phys arg:  {force_phys_normalized}")
    elif target_late:
        print(f"Target suffix:   {','.join(str(x) for x in target_late)}")
    else:
        print(f"Target prefix:   {','.join(str(x) for x in target)}")
    print(f"Baseline order:  "
          f"{','.join(str(x) for x in baseline_sig.simplify_order[:8])}"
          f"{'...' if len(baseline_sig.simplify_order) > 8 else ''}")
    print(f"Preserve gate:   {'on' if preserve_precolor else 'off'}")
    print(f"Max candidates:  {max_candidates}")

    sources: list = [
        decl_orders_source,
        insert_alias_source,
        holder_lifetime_source,
        type_change_source,
    ]
    # Track the resolved permuter dir at function scope so the post-search
    # --triage composition can reuse the same path the search adapters
    # consumed — no risk of the two paths diverging.
    resolved_permuter_dir: Optional[Path] = None
    if with_permuter:
        # Resolve the permuter dir up front so we can warn (once) if it
        # doesn't exist. The adapter itself silently yields nothing on a
        # missing dir; the warning is what tells the user "you probably
        # meant to run permuter first."
        if permuter_dir is not None:
            harvest_dir: Optional[Path] = permuter_dir
        else:
            harvest_dir = resolve_permuter_function_dir(function)
        if harvest_dir is None or not harvest_dir.is_dir():
            # Different remediation text depending on whether the user
            # explicitly supplied --permuter-dir: pointing them at
            # `nonmatchings/<fn>/` when they already overrode the path
            # would be misleading.
            if permuter_dir is not None:
                typer.echo(
                    f"--permuter-dir {permuter_dir}: directory does not "
                    f"exist. Continuing with the primitive adapters only.",
                    err=True,
                )
            else:
                typer.echo(
                    f"--with-permuter: no permuter output found "
                    f"(looked under nonmatchings/{function}/). "
                    f"Run `./permuter.py nonmatchings/{function}` in your "
                    f"decomp-permuter clone first, or pass --permuter-dir. "
                    f"Continuing with the primitive adapters only.",
                    err=True,
                )
        else:
            print(f"Permuter dir:    {harvest_dir}")
            resolved_permuter_dir = harvest_dir

            def _permuter_adapter(ctx_):
                return permuter_source(ctx_, perm_dir_override=harvest_dir)

            sources.append(_permuter_adapter)
    print()

    def _simplify_progress(compiled: int, limit: int, provenance: str) -> None:
        typer.echo(
            f"[simplify-order] compiling {compiled}/{limit}: {provenance}",
            err=True,
        )

    result = search(
        sources=sources,
        ctx=ctx,
        baseline=baseline_sig,
        target=target,
        target_late=target_late,
        force_phys=force_phys_target or None,
        class_id=class_id,
        max_candidates=max_candidates,
        timeout=timeout,
        preserve_precolor_enabled=preserve_precolor,
        progress_callback=_simplify_progress,
    )

    print(f"Compiled:        {result.total_compiles} variant(s)")
    print(f"Compile fails:   {result.compile_failure_count}")
    print(f"Gate rejected:   {result.gate_rejected_count}")
    print(f"Progress hits:   {len(result.progress)}")
    print(f"Elapsed:         {result.elapsed_seconds:.1f}s")
    print()

    # Headline output: unified ranking of gate-passing + gate-rejected
    # candidates by the selected ranking mode. The campaign-3 use case
    # ("the 19 candidates that hit prefix=2 ranked by precolor disturbance")
    # only surfaces from this section — the existing progress / gate-rejected
    # sections split them by gate result.
    #
    # --rank-combined is a deprecated alias for --rank-mode combined; if the
    # user passes it, override rank_mode so existing scripts keep working.
    effective_rank_mode = (
        RankMode.combined if rank_combined else rank_mode
    )
    # In late-mode target is () and target_late carries the meaningful sequence;
    # pass the non-empty one to the renderers so their length checks are correct.
    effective_target = target_late if target_late else target
    if force_phys_target:
        _render_force_phys_ranking(result, force_phys_target)
        effective_target = tuple(force_phys_target.keys())
    elif effective_rank_mode is RankMode.combined:
        _render_combined_score_ranking(result, effective_target, alpha=combined_alpha)
    else:
        _render_lex_ranking(result, effective_target)

    if result.gate_rejection_reasons:
        print("Top gate-rejection reasons:")
        for reason in result.gate_rejection_reasons[:5]:
            print(f"  - {reason}")
        print()

    # Gate-rejected diagnostic: prefix-length distribution + top-N. Renders
    # nothing when there are no gate-rejected candidates; otherwise answers
    # "did any rejected candidate move simplify-order toward target?" — the
    # input for the harvest-vs-custom-scorer decision.
    if not force_phys_target:
        _render_gate_rejected_distribution(result, effective_target)

    # --triage composition: run `debug permute triage` after the harvest
    # to surface a second ranking by real-tree match% (the ground-truth
    # metric). Layer A of the workflow integration; closes the methodology
    # gap from the grVenom_80204284 campaign. Always runs before the early
    # exits below so progress=0 and exact-match paths still see the
    # ground-truth ranking.
    #
    # Thread `effective_rank_mode` + alpha + effective_target so the triage
    # section's cross-rank annotation references the same ordering as the
    # headline ranking table the user saw above — otherwise a user in
    # `--rank-mode combined` would see a "simplify-order rank #N"
    # annotation that disagrees with the "Best by combined score" table.
    _maybe_run_triage(
        triage_enabled=triage,
        with_permuter=with_permuter,
        permuter_dir_resolved=resolved_permuter_dir,
        function=function,
        melee_root=melee_root,
        result=result,
        rank_mode=effective_rank_mode,
        combined_alpha=combined_alpha,
        target=effective_target,
    )

    if result.exact_match is not None:
        print("EXACT MATCH found:")
        print(f"  provenance: {result.exact_match.provenance}")
        print(f"  parent:     {result.exact_match.parent_baseline}")
        print()
        print("Apply this variant manually to keep the change. Output is not "
              "auto-applied — review and commit by hand.")
        raise typer.Exit(0)

    if not result.progress:
        if force_phys_target:
            print("No variants improved force-phys assignments beyond baseline.")
        else:
            print("No variants made progress beyond baseline.")
        if not preserve_precolor and result.gate_rejected_count == 0:
            if force_phys_target:
                print("(Tried with --no-preserve-precolor — no candidate "
                      "changed the requested physical assignment.)")
            else:
                print("(Tried with --no-preserve-precolor — nothing changed the "
                      "simplify order at all.)")
        else:
            print("Consider:")
            if force_phys_target:
                print("  - Re-running with a wider candidate pool or more "
                      "source-shape levers while preserving the same "
                      "--force-phys objective.")
            else:
                print("  - Re-running with --no-preserve-precolor to see if any "
                      "variant produces the target order while disturbing other "
                      "RA inputs.")
            if not with_permuter:
                print("  - Running decomp-permuter (`./permuter.py "
                      f"nonmatchings/{function}`) then re-running this "
                      "command with --with-permuter to harvest its output.")
            else:
                print("  - Letting permuter run longer to grow the candidate "
                      "pool, then re-running the search.")
        raise typer.Exit(0)

    print(f"Top {min(3, len(result.progress))} progress candidate(s):")
    for i, scored in enumerate(result.progress[:3]):
        s = scored.score
        print(f"  {i + 1}. {scored.variant.provenance}")
        if force_phys_target:
            observed = ", ".join(
                f"ig{ig}->r{force_phys_target[ig]}"
                for ig in s.observed_prefix
            ) or "(none)"
            print(f"     force-phys hits: {s.common_prefix_length}/{len(s.target_prefix)}")
            print(f"     matched:         {observed}")
            print(f"     baseline:        {s.baseline_common_prefix_length}/"
                  f"{len(s.target_prefix)} matched")
        else:
            print(f"     prefix match:  {s.common_prefix_length}/{len(s.target_prefix)}")
            print(f"     observed:      {','.join(str(x) for x in s.observed_prefix)}")
            print(f"     baseline:      {s.baseline_common_prefix_length}/"
                  f"{len(s.target_prefix)} matched")
    print()
    if force_phys_target:
        print("These variants improve the force-phys objective but don't fully "
              "hit it. Inspect them with `debug inspect diff` to see what "
              "changed, then iterate.")
    else:
        print("These variants make partial progress but don't fully hit the "
              "target. Inspect them with `debug inspect diff` to see what "
              "changed, then iterate.")


@mutate_app.command(name="search")
def tier3_search(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to search (required).",
        ),
    ],
    budget: Annotated[
        int,
        typer.Option(
            "--budget",
            help="Maximum number of seed mutations to try. Hard cap "
                 "on seed count; truncated by priority order.",
        ),
    ] = 5,
    per_seed_time: Annotated[
        int,
        typer.Option(
            "--per-seed-time",
            help="Wall-clock seconds to permute each compiling seed. "
                 "The permuter runs against the seed's perm-dir for "
                 "this long, then is killed. Default 60s.",
        ),
    ] = 60,
    total_time: Annotated[
        int,
        typer.Option(
            "--total-time",
            help="Global wall-clock cap (seconds) across the whole "
                 "per-seed search. Stop early once exceeded, even if "
                 "seeds remain. Default 600s (10 minutes).",
        ),
    ] = 600,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Target spec; auto-derived if omitted.",
        ),
    ] = None,
    blend: Annotated[
        float,
        typer.Option("--blend", help="mwcc-score blend weight."),
    ] = 0.1,
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Minimum delta (% improvement, post-transfer) to "
                 "consider a seed's permuter run a win when applying "
                 "with --apply-best. Default 0.05 — matches the global "
                 "debug permute verify default.",
        ),
    ] = 0.05,
    apply_best: Annotated[
        bool,
        typer.Option(
            "--apply-best",
            help="After ranking, if the winning seed's best candidate "
                 "improves real-source match by >= --threshold, "
                 "transfer it to the real tree via the same debug permute verify "
                 "machinery (with the inline_fn placeholder guard). "
                 "Off by default — dry-run semantics.",
        ),
    ] = False,
    include_low_confidence: Annotated[
        bool,
        typer.Option(
            "--include-low-confidence",
            help="Also generate seeds from bindings the symbol-bridge "
                 "flagged as low-confidence (red flags present: nested "
                 "decls, statics, extra compiler-introduced virtuals). "
                 "Off by default — skip these to avoid bad seeds on "
                 "functions where the cursor heuristic is unreliable. "
                 "Verify the binding manually via "
                 "`debug inspect var-to-virtual <var> -f FN --basis` before "
                 "opting in.",
        ),
    ] = False,
) -> None:
    """Tier 3: multi-start search over targeted mutation seeds.

    Workflow:
      1. Resolve pcdump + target.
      2. Enumerate variable bindings via the symbol bridge.
      3. Plan up to --budget seed mutations.
      4. Materialize each seed inside
         nonmatchings/<fn>/tier3_seed_<idx>/.
      5. Smoke-compile each. If all seeds fail, exit non-zero with a
         clear message.
      6. For each compiling seed, launch decomp-permuter (with
         mwcc-debug score blending) for up to --per-seed-time seconds.
         The global --total-time cap stops the loop early once
         exceeded.
      7. Find the best candidate each permuter produced and rank
         seeds by delta (baseline score minus best candidate's score).
      8. Print the top result with full diff path.
      9. If --apply-best is set, transfer the winning candidate into
         the real source tree via the same debug permute verify machinery (with
         the inline_fn placeholder check still firing).
    """
    from ..mwcc_debug.symbol_bridge import list_bindings
    from ..mwcc_debug.tier3_search import (
        find_best_candidate,
        materialize_seed,
        plan_seeds,
        plan_seeds_from_lifetime_layout_probes,
        rank_seed_results,
        run_per_seed_permute,
        save_compile_failure,
        smoke_compile,
    )
    from ..mwcc_debug.pressure_explorer import (
        generate_frame_directed_probes,
        generate_lifetime_layout_probes,
    )

    melee_root = DEFAULT_MELEE_ROOT
    explicit_target = target is not None

    # Resolve unit + sources
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    src_rel = f"src/{unit}.c"
    src_path = melee_root / src_rel
    base_source = src_path.read_text()

    # Resolve pcdump for the bridge
    pcdump_path = _resolve_pcdump_path(None, function, melee_root)
    text = pcdump_path.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre = fn.last_precolor_pass()
    if pre is None:
        typer.echo(
            f"no pre-coloring pass for {function}", err=True,
        )
        raise typer.Exit(3)

    # Resolve/derive the target spec before seed planning. Frame-specific
    # targets can drive seed generation, not just later candidate scoring.
    if target is None:
        target = melee_root / "build" / "mwcc_debug_cache" / \
            f"{unit}_target.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            events_list = parse_hook_events(text)
            events = find_function(events_list, function)
            spec = derive_target_from_function(fn, events=events)
            target.write_text(json.dumps(spec, indent=2))
            print(f"[tier3] derived target -> {target}")
    try:
        target_spec = _load_target_spec(target)
    except typer.Exit:
        raw_target_text = target.read_text() if target.exists() else ""
        try:
            raw_target = json.loads(raw_target_text) if raw_target_text else None
        except json.JSONDecodeError:
            raw_target = None
        if raw_target == {}:
            target_spec = {}
        else:
            raise

    bindings = list_bindings(base_source, function, pre)
    plans = []
    target_frame = target_spec.get("frame")
    if isinstance(target_frame, dict):
        frame_probes = generate_frame_directed_probes(
            base_source,
            function,
            current_frame=analyze_frame_from_function(fn),
            target_frame=target_frame,
            max_probes=budget,
        )
        plans.extend(plan_seeds_from_lifetime_layout_probes(
            frame_probes,
            budget=budget,
        ))
        if plans:
            print(
                "[tier3] using frame-directed seed plans from target frame"
            )
    remaining_budget = max(0, budget - len(plans))
    if remaining_budget:
        plans.extend(plan_seeds(
            bindings, budget=remaining_budget,
            include_low_confidence=include_low_confidence,
        ))
    if not plans:
        probes = generate_lifetime_layout_probes(
            base_source,
            function,
            max_probes=budget,
        )
        plans = plan_seeds_from_lifetime_layout_probes(
            probes,
            budget=budget,
        )
        if plans:
            print(
                "[tier3] no symbol-bridge seed plans; using "
                "source-shape probe fallback"
            )
    if not plans:
        # Diagnostic: if there ARE low-confidence bindings, explain.
        n_low = sum(1 for b in bindings if b.confidence == "low-confidence")
        if n_low and not include_low_confidence:
            typer.echo(
                f"no Tier 3 targets — {n_low} local binding(s) demoted to "
                f"low-confidence by red flags. Run `debug inspect var-to-virtual "
                f"<var> -f {function} --basis` to audit, then re-run "
                f"with --include-low-confidence if mapping looks correct.",
                err=True,
            )
        else:
            typer.echo(
                "no Tier 3 targets; fall back to `debug permute run -f "
                f"{function}` for a vanilla Tier 2 run.",
                err=True,
            )
        raise typer.Exit(1)

    print(f"[tier3] {len(plans)} seed plans:")
    for i, p in enumerate(plans):
        print(f"  seed{i}: {p.description}")

    # Materialize + smoke-compile
    wibo = _find_wibo()
    debug_compiler = _find_compiler_dir() / "mwcceppc_debug.exe"
    if wibo is None or not wibo.exists() or not debug_compiler.exists():
        typer.echo(
            "wibo or patched compiler missing. "
            "Run `debug dump setup` first.",
            err=True,
        )
        raise typer.Exit(4)
    cflags, _mw = _ninja_cflags_for_unit(src_rel)

    perm_dir = _resolve_permuter_function_dir(
        function, perm_root=perm_root, melee_root=melee_root)
    if not perm_dir.exists():
        typer.echo(
            f"{perm_dir} not found.\n"
            + _permuter_import_hint(
                function,
                perm_root=perm_root,
                melee_root=melee_root,
                unit=unit,
            ),
            err=True,
        )
        raise typer.Exit(2)

    baseline_score: Optional[int] = None
    if explicit_target and target_spec:
        baseline_events_list = parse_hook_events(text)
        baseline_events = find_function(baseline_events_list, function)
        baseline_score = int(score_function(
            fn,
            target_spec,
            events=baseline_events,
        ).total)
        print(f"[tier3] target baseline score={baseline_score}")

    materialized: list = []
    for i, plan in enumerate(plans):
        seed_dir = perm_dir / f"tier3_seed_{i}"
        out_c = materialize_seed(base_source, function, plan, seed_dir)
        if out_c is None:
            print(f"[tier3] seed{i}: mutation unsupported; skipping")
            continue
        result = smoke_compile(
            out_c, wibo, debug_compiler, cflags, melee_root,
            extra_include_dirs=[src_path.parent],
        )
        if result.ok:
            print(f"[tier3] seed{i}: compile=ok")
        else:
            log_path = save_compile_failure(seed_dir, result)
            print(f"[tier3] seed{i}: compile=FAIL — {result.one_line_reason}")
            print(f"         (full output: {log_path}, seed source: "
                  f"{seed_dir / 'base.c'})")
        seed_score = None
        if (
            result.ok
            and explicit_target
            and target_spec
            and result.pcdump_text
        ):
            seed_fns = parse_pcdump(result.pcdump_text)
            seed_fn = next(
                (candidate for candidate in seed_fns if candidate.name == function),
                None,
            )
            if seed_fn is not None:
                seed_events_list = parse_hook_events(result.pcdump_text)
                seed_events = find_function(seed_events_list, function)
                seed_score = int(score_function(
                    seed_fn,
                    target_spec,
                    events=seed_events,
                ).total)
                print(f"[tier3] seed{i}: target score={seed_score}")
        materialized.append((plan, seed_dir, result, seed_score))

    compiled = [m for m in materialized if m[2].ok]
    if not compiled:
        typer.echo(
            f"all {len(materialized)} tier3 seeds failed to compile.",
            err=True,
        )
        typer.echo("", err=True)
        typer.echo("Failed seeds (inspect each):", err=True)
        for i, (plan, seed_dir, result, _seed_score) in enumerate(materialized):
            typer.echo(
                f"  seed{i} ({plan.mutator} on {plan.target_var}): "
                f"{result.one_line_reason}",
                err=True,
            )
            typer.echo(
                f"    sources: {seed_dir / 'base.c'}",
                err=True,
            )
            typer.echo(
                f"    error:   {seed_dir / 'compile_error.txt'}",
                err=True,
            )
        typer.echo("", err=True)
        typer.echo(
            "Common causes: (a) symbol-bridge mapping is wrong (check "
            "`debug inspect var-to-virtual -f FN --basis`); (b) the mutation "
            "produced invalid C (look at base.c); (c) the function uses "
            "a pattern the mutators don't handle yet.",
            err=True,
        )
        raise typer.Exit(5)

    print()
    print(
        f"[tier3] {len(compiled)}/{len(materialized)} seeds compiled. "
        f"Per-seed permute budget: {per_seed_time}s. "
        f"Global cap: {total_time}s."
    )

    # Stage each compiling seed_dir to look like a permuter perm-dir.
    # Inherit target.o/compile.sh/settings.toml from the parent perm_dir
    # so the permuter has everything it needs.
    inherited_files = ["target.o", "compile.sh", "settings.toml"]
    for plan, seed_dir, _result, _seed_score in compiled:
        for fname in inherited_files:
            src_file = perm_dir / fname
            dst_file = seed_dir / fname
            if src_file.exists() and not dst_file.exists():
                shutil.copy2(src_file, dst_file)
        # Make compile.sh executable in case the copy stripped mode.
        sh = seed_dir / "compile.sh"
        if sh.exists():
            sh.chmod(0o755)

    # Build the runner closure. It invokes the permute_with_mwcc.py
    # wrapper directly against the seed_dir for `time_seconds` seconds,
    # then SIGTERMs it. Output lands inside seed_dir/output-N-M/.
    wrapper = (
        melee_root / "tools" / "melee-agent" / "scripts"
        / "permute_with_mwcc.py"
    )
    if not wrapper.exists():
        typer.echo(f"wrapper not found: {wrapper}", err=True)
        raise typer.Exit(4)

    def _permute_runner(
        seed_dir_arg: Path, fn_name: str, time_seconds: int,
    ) -> None:
        env = os.environ.copy()
        env["MELEE_PERMUTER_ROOT"] = str(perm_root)
        env["MELEE_ROOT"] = str(melee_root)
        env["MWCC_DEBUG_TARGET"] = str(target)
        env["MWCC_DEBUG_FN"] = fn_name
        env["MWCC_DEBUG_UNIT"] = src_rel
        env["MWCC_DEBUG_BLEND"] = str(blend)
        cmd = ["python", str(wrapper), str(seed_dir_arg), "-j", "1"]
        # Use subprocess.Popen + wait(timeout) so we can kill on
        # expiry. permuter.py runs indefinitely; we want a hard cap.
        proc = subprocess.Popen(
            cmd, env=env, cwd=perm_root,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            proc.wait(timeout=time_seconds)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    # Read the baseline score from the parent perm_dir's first seeded
    # output (the unmutated base.c's score). We don't have a clean
    # source of truth pre-permute — use the parent perm_dir's lowest-
    # scoring `output-N-M` as a coarse baseline if it exists, else None.
    parent_best = find_best_candidate(perm_dir)
    if baseline_score is None and parent_best is not None:
        m = re.match(r"^output-(\d+)-\d+$", parent_best.parent.name)
        if m:
            baseline_score = int(m.group(1))

    # Per-seed loop, respecting the global time budget.
    print("[tier3] launching per-seed permuter runs...")
    results: list = []
    deadline = time.monotonic() + total_time
    for i, (plan, seed_dir, _result, seed_score) in enumerate(compiled):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(
                f"[tier3] global --total-time={total_time}s exhausted; "
                f"skipping {len(compiled) - i} remaining seed(s)."
            )
            break
        # Don't let a per-seed timer run past the global cap.
        slot = min(per_seed_time, int(remaining))
        print(
            f"[tier3] seed{i}: permuting for {slot}s "
            f"({plan.description})..."
        )
        res = run_per_seed_permute(
            seed_idx=i,
            plan=plan,
            seed_dir=seed_dir,
            fn_name=function,
            per_seed_time=slot,
            runner=_permute_runner,
            baseline_score=baseline_score,
            seed_score=seed_score,
        )
        if res.error:
            print(f"[tier3] seed{i}: runner error: {res.error}")
        elif res.best_candidate is None:
            print(
                f"[tier3] seed{i}: no improvement after "
                f"{res.ran_seconds:.1f}s."
            )
        else:
            print(
                f"[tier3] seed{i}: best score={res.best_score} "
                f"(baseline={res.baseline_score}, delta={res.delta}) "
                f"in {res.ran_seconds:.1f}s; "
                f"candidate={res.best_candidate}"
            )
        results.append(res)

    print()
    ranked = rank_seed_results(results)
    if not ranked or all(r.best_candidate is None for r in ranked):
        typer.echo(
            "[tier3] No seed produced a permuter improvement. "
            "Consider increasing --per-seed-time, widening --budget, "
            "or inspecting individual seed_dirs manually.",
            err=True,
        )
        return

    print("[tier3] Ranked results (best first):")
    for r in ranked:
        if r.best_candidate is None:
            print(
                f"  seed{r.seed_idx}: delta=0 (no improvement) — "
                f"{r.plan.description}"
            )
        else:
            print(
                f"  seed{r.seed_idx}: delta={r.delta} "
                f"(score {r.baseline_score}->{r.best_score}) — "
                f"{r.plan.description}"
            )
            print(f"      candidate: {r.best_candidate}")

    winner = next(
        (r for r in ranked if r.best_candidate is not None), None,
    )
    if winner is None:
        return

    print()
    print(
        f"[tier3] Top: seed{winner.seed_idx} delta={winner.delta} "
        f"({winner.plan.description})"
    )
    print(f"        candidate: {winner.best_candidate}")
    diff_path = winner.best_candidate.parent / "diff.diff"
    if diff_path.exists():
        print(f"        diff:      {diff_path}")

    if not apply_best:
        print()
        print(
            "[tier3] --apply-best not set; re-run with --apply-best to "
            "transfer the winner via debug permute verify, or run manually:\n"
            f"  melee-agent debug permute verify {winner.best_candidate} "
            f"-f {function} --keep"
        )
        return

    # --apply-best: invoke debug permute verify in-process so the inline_fn
    # placeholder guard + 3-way merge logic from commit f39e264a9
    # still fires.
    print()
    print("[tier3] --apply-best: invoking debug permute verify with --keep...")
    verify_perm(
        candidate=winner.best_candidate,
        function=function,
        keep=True,
        force=False,
        threshold=threshold,
        json_out=False,
    )


@util_app.command(name="verify-name-magic")
def verify_with_name_magic(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name"),
    ],
    name_map: Annotated[
        Optional[str],
        typer.Option(
            "--map", "-m",
            help="Mapping of magic constant → named symbol. E.g., "
                 "'s32=mnVibration_804DC018,u32=mnVibration_804DC010'. "
                 "Keys: 's32' (signed int-to-float bias), 'u32' (unsigned), "
                 "any hex literal, or '@N' for direct anonymous-symbol "
                 "rename. If omitted, the .o is built and anonymous "
                 "magic symbols are LISTED with a suggested map "
                 "(useful for figuring out what to pass).",
        ),
    ] = None,
    apply_auto: Annotated[
        bool,
        typer.Option(
            "--apply-auto",
            help="Automatically resolve and apply the full anonymous → "
                 "production-symbol rename, no --map needed. Cross-"
                 "references the production .o "
                 "(`build/GALE01/obj/<unit>.o`) by value, renames every "
                 "anonymous @N .sdata2 symbol whose backing bytes match a "
                 "named symbol in the production .o, then globalizes "
                 "(STB_GLOBAL) the new symbols. Makes the 'named SDA2 "
                 "magic constants' matching blocker invisible to "
                 "subsequent checkdiff runs without manually constructing "
                 "a map. Mutually exclusive with --map.",
        ),
    ] = False,
) -> None:
    """Compile, optionally rename anonymous SDA2 constants, then checkdiff.

    Separates 'this is just constant-label noise' from 'this is real
    codegen diff.' The agent runs this to confirm whether anonymous-vs-
    named SDA2 relocations are the only diff, or whether there's still
    a real .text mismatch.

    Common case: MWCC's int-to-float cast emits a magic constant
    (0x4330000080000000 signed, 0x4330000000000000 unsigned) into the
    .sdata2 literal pool under an anonymous `@N` name. The target .o
    references the same bytes via a named symbol (from symbols.txt).
    Reloc-target diff blocks byte matching even though the data is
    identical. `--map s32=<symname>,u32=<symname>` renames the @N
    symbols so checkdiff sees matching reloc targets. Or pass
    `--apply-auto` to do the lookup + rename automatically from the
    production .o, no map required.

    Flow:
      1. Build the function's TU object (`ninja build/GALE01/src/<unit>.o`)
      2. If `--map` given, rename anonymous @N .sdata2 symbols via objcopy.
         If `--apply-auto` given, auto-resolve via value lookup against the
         production .o and apply renames + globalize in one step.
         If neither given, list anonymous symbols and suggest the map format.
      3. Run `tools/checkdiff.py <function> --format plain` and forward
         its output verbatim.
    """
    if name_map and apply_auto:
        typer.echo(
            "--map and --apply-auto are mutually exclusive; pick one. "
            "Use --apply-auto to auto-resolve, or --map to supply an "
            "explicit mapping.",
            err=True,
        )
        raise typer.Exit(2)

    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        # Suggest similar names from report.json (mirrors debug permute verify)
        try:
            report_path = melee_root / "build" / "GALE01" / "report.json"
            if report_path.exists():
                with report_path.open() as f:
                    rdata = json.load(f)
                all_names = [fn.get("name") for u in rdata.get("units", [])
                             for fn in u.get("functions", []) if fn.get("name")]
                suggestions = _suggest_similar_functions(function, all_names)
            else:
                suggestions = []
        except Exception:
            suggestions = []
        msg = f"function {function!r} not in report.json."
        if suggestions:
            msg += "\n\nDid you mean one of these?"
            for s in suggestions:
                msg += f"\n  - {s}"
        msg += "\n\nTry `ninja build/GALE01/report.json` to regenerate, then retry."
        typer.echo(msg, err=True)
        raise typer.Exit(2)

    obj_rel = Path("build") / "GALE01" / "src" / f"{unit}.o"
    obj_path = melee_root / obj_rel

    # 1. Build the .o
    print(f"[verify] building {obj_rel}...")
    proc = subprocess.run(
        ["ninja", str(obj_rel)],
        cwd=melee_root, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        err_summary = _extract_ninja_error(proc.stdout, proc.stderr)
        typer.echo(f"ninja failed building {obj_rel}:", err=True)
        typer.echo(err_summary, err=True)
        raise typer.Exit(3)
    if not obj_path.exists():
        typer.echo(
            f"ninja reported success but {obj_rel} not found", err=True,
        )
        raise typer.Exit(3)

    # 2. Rename anonymous SDA2 symbols if --map / --apply-auto given,
    #    or surface what anonymous symbols exist so the agent can
    #    construct a map.
    if name_map:
        from ..mwcc_debug.o_rewriter import (
            parse_mapping,
            rename_magic_symbols,
        )
        try:
            mapping = parse_mapping(name_map)
        except ValueError as e:
            typer.echo(f"invalid --map: {e}", err=True)
            raise typer.Exit(2)
        try:
            renames = rename_magic_symbols(obj_path, mapping)
        except FileNotFoundError as e:
            typer.echo(
                f"objcopy not found: {e}. Install devkitPPC.",
                err=True,
            )
            raise typer.Exit(5)
        except subprocess.CalledProcessError as e:
            typer.echo(f"objcopy failed: {e}", err=True)
            raise typer.Exit(5)
        if renames:
            print(f"[verify] renamed {len(renames)} symbol(s):")
            for old, new in renames:
                print(f"          {old} -> {new}")
        else:
            print(
                "[verify] no matching anonymous symbols found to rename "
                "(use `debug util name-magic <o_file> --list` to inspect)"
            )
    elif apply_auto:
        from ..mwcc_debug.o_rewriter import apply_name_magic_auto

        target_o = melee_root / "build" / "GALE01" / "obj" / f"{unit}.o"
        if not target_o.exists():
            typer.echo(
                f"--apply-auto requires the production .o at "
                f"{target_o.relative_to(melee_root)} (not found). "
                f"Build it first (`ninja build/GALE01/obj/{unit}.o`) and "
                f"retry, or use --map to supply names manually.",
                err=True,
            )
            raise typer.Exit(2)
        try:
            result = apply_name_magic_auto(obj_path, target_o)
        except FileNotFoundError as e:
            typer.echo(
                f"objcopy not found: {e}. Install devkitPPC.",
                err=True,
            )
            raise typer.Exit(5)
        except subprocess.CalledProcessError as e:
            typer.echo(f"objcopy failed: {e}", err=True)
            raise typer.Exit(5)
        target_rel = target_o.relative_to(melee_root)
        if result.renames:
            print(
                f"[verify] --apply-auto: renamed {len(result.renames)} "
                f"symbol(s) via lookup against {target_rel}:"
            )
            globalized_set = set(result.globalized)
            for old, new in result.renames:
                glob_note = (
                    " (globalized)" if new in globalized_set else ""
                )
                print(f"          {old} -> {new}{glob_note}")
        else:
            print(
                f"[verify] --apply-auto: no anonymous .sdata2 symbols "
                f"matched named counterparts in {target_rel} "
                f"(found {len(result.anonymous_found)} anonymous; "
                f"unresolved {len(result.unresolved)})"
            )
        if result.unresolved:
            unresolved_names = ", ".join(
                s.name for s in result.unresolved[:8]
            )
            extra = (
                f" (+{len(result.unresolved) - 8} more)"
                if len(result.unresolved) > 8 else ""
            )
            print(
                f"[verify] --apply-auto: {len(result.unresolved)} "
                f"anonymous symbol(s) had no value-match in "
                f"{target_rel}: {unresolved_names}{extra}"
            )
    else:
        # No --map given. List anonymous magic constants in the freshly-
        # built .o so the agent can construct a map. Cross-reference with
        # the target .o (build/GALE01/obj/<unit>.o) to suggest concrete
        # named symbols instead of placeholders.
        try:
            from ..mwcc_debug.o_rewriter import suggest_name_magic_map
            target_o = melee_root / "build" / "GALE01" / "obj" / f"{unit}.o"
            syms, suggested = suggest_name_magic_map(obj_path, target_o)
        except Exception as e:
            syms, suggested = [], []
            print(f"[verify] no --map given (sym-list failed: {e})")
        if syms:
            named_for_sym: dict[str, str] = {s.name: n for s, n in suggested}
            print(f"[verify] no --map given; {len(syms)} anonymous .sdata2 "
                  f"symbol(s) found in {obj_rel}:")
            print(f"        {'name':<10}  {'sz':>2}  {'value':<18}  notes")
            print(f"        {'-'*10}  {'-'*2}  {'-'*18}  -----")
            import struct as _struct
            ready_pairs: list[str] = []
            placeholder_pairs: list[str] = []
            for s in syms:
                note = ""
                named = named_for_sym.get(s.name)
                if s.size == 8:
                    value_str = f"0x{s.value:016x}"
                    if s.value == 0x4330000080000000:
                        if named:
                            note = f"signed int-to-float bias → s32={named}"
                            ready_pairs.append(f"s32={named}")
                        else:
                            note = "int-to-float bias (signed) — try `s32=<sym>`"
                            placeholder_pairs.append("s32=<NAMED_SYMBOL>")
                    elif s.value == 0x4330000000000000:
                        if named:
                            note = f"unsigned int-to-float bias → u32={named}"
                            ready_pairs.append(f"u32={named}")
                        else:
                            note = "int-to-float bias (unsigned) — try `u32=<sym>`"
                            placeholder_pairs.append("u32=<NAMED_SYMBOL>")
                    elif named:
                        note = f"target named: {named}"
                        ready_pairs.append(f"{s.name}={named}")
                elif s.size == 4:
                    value_str = f"0x{s.value:08x}"
                    try:
                        f_val = _struct.unpack(">f", _struct.pack(">I", s.value))[0]
                        note = f"float ≈ {f_val:g}"
                    except Exception:
                        pass
                    if named:
                        note = f"{note + ' / ' if note else ''}target named: {named}"
                        ready_pairs.append(f"{s.name}={named}")
                else:
                    value_str = f"0x{s.value:x}"
                print(f"        {s.name:<10}  {s.size:>2}  {value_str:<18}  {note}")
            if ready_pairs:
                # Concrete map ready to copy-paste — built from target .o
                # cross-reference, so the agent doesn't have to grep
                # symbols.txt.
                print(
                    f"[verify] HINT: target .o ({target_o.relative_to(melee_root) if target_o.exists() else target_o}) "
                    f"has named counterparts. Re-run with:\n"
                    f"  --map '{','.join(ready_pairs)}'"
                )
                if placeholder_pairs:
                    print(
                        f"[verify] (some anonymous symbols had no target "
                        f"counterpart; fill in manually: "
                        f"{','.join(sorted(set(placeholder_pairs)))})"
                    )
            elif placeholder_pairs:
                print(
                    f"[verify] HINT: target .o not built or has no named "
                    f"counterparts at matching offsets. Build it first "
                    f"(`ninja build/GALE01/obj/{unit}.o`) for an auto-"
                    f"resolved map, or fill in manually: "
                    f"`--map '{','.join(sorted(set(placeholder_pairs)))}'`"
                )
            else:
                print(
                    "[verify] HINT: if checkdiff below complains about "
                    "@N relocs, you can pass `--map '@N=<sym>'` directly to "
                    "rename specific anonymous symbols."
                )
        else:
            print("[verify] no --map given; .o has no anonymous .sdata2 symbols")

    # 3. Run checkdiff — pass --no-build so its internal ninja invocation
    # doesn't clobber the objcopy rename we just made.
    print(f"[verify] running checkdiff.py {function}...")
    proc = subprocess.run(
        [
            "python", "tools/checkdiff.py", function,
            "--format", "plain", "--no-build",
        ],
        cwd=melee_root, capture_output=True, text=True,
        env=_checkdiff_env_without_fingerprint(),
    )
    # Forward stdout (the diff) and stderr verbatim
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        typer.echo(proc.stderr, err=True)
    raise typer.Exit(proc.returncode)
