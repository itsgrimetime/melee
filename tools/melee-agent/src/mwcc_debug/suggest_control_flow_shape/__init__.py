"""Control-flow shape analysis for Melee function matching.

Public API: analyze_control_flow_shape, render_json, render_text,
annotate_source_materialization.
"""

from __future__ import annotations

from ._helpers import *  # noqa: F403 — re-export dataclasses, constants, utilities
from ._helpers import (  # noqa: F401
    _Instruction,
    _LoopRegion,
    _StackHomeCall,
    _PRIORITY,
    _BOOL_CAST_OPS,
    _COMPARE_OPS,
    _CONDITIONAL_BRANCH_PREFIXES,
    _INDEXED_OPS,
    _STRIDE_OPS,
    _CALL_OPS,
    _LOOP_START_OPS,
    _LOOP_END_OPS,
    _ARG_REGS,
    _VOLATILE_REGS,
)

def analyze_control_flow_shape(
    *,
    function: str,
    target_asm: list[str],
    current_asm: list[str],
    classification: dict | None = None,
    top: int = 5,
) -> dict[str, Any]:
    classification_payload = classification if isinstance(classification, dict) else {}
    target = _parse_asm(target_asm)
    current = _parse_asm(current_asm)
    applicability = _applicability(classification_payload)

    suggestions: list[dict[str, Any]] = []
    for detector in (
        _detect_branch_idiom,
        _detect_call_hoist,
        _detect_pointer_walk,
        _detect_concurrent_buffer_lifetime,
        _detect_loop_peel_unroll,
        _detect_missing_extra_call_layer,
    ):
        suggestion = detector(
            function=function,
            target=target,
            current=current,
            classification=classification_payload,
        )
        if suggestion is not None:
            suggestions.append(suggestion)

    suggestions.sort(
        key=lambda item: (
            _PRIORITY.get(str(item["kind"]), 100),
            -float(item["confidence"]),
            str(item["kind"]),
        )
    )
    clipped = suggestions[: max(0, top)]
    for rank, suggestion in enumerate(clipped, start=1):
        suggestion["rank"] = rank

    return {
        "function": function,
        "classification": classification_payload,
        "applicability": applicability,
        "summary": _summary(applicability, clipped, len(suggestions)),
        "suggestions": clipped,
    }


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)


def render_text(report: dict[str, Any]) -> str:
    function = report.get("function") or "(unknown)"
    classification = report.get("classification") or {}
    applicability = report.get("applicability") or {}
    primary = classification.get("primary") or "(unknown)"
    lines = [
        f"control-flow-shape suggestions - {function}",
        f"classification: {primary}",
        "applicability: "
        f"{str(bool(applicability.get('is_control_flow_shape'))).lower()} "
        f"({', '.join(applicability.get('reasons') or ['no matching signals'])})",
        f"summary: {report.get('summary')}",
    ]

    suggestions = report.get("suggestions") or []
    if not suggestions:
        lines.append("no control-flow-shape suggestions")
        return "\n".join(lines)

    for suggestion in suggestions:
        lines.extend(
            [
                "",
                f"#{suggestion['rank']} {suggestion['kind']} "
                f"confidence={suggestion['confidence']:.2f}",
                f"recommendation: {suggestion['recommendation']}",
            ]
        )
        evidence = suggestion.get("evidence") or {}
        if evidence:
            lines.append("evidence:")
            for key, value in evidence.items():
                lines.append(f"  - {key}: {_format_evidence_value(value)}")
        materialization = suggestion.get("source_materialization")
        if isinstance(materialization, dict):
            status = materialization.get("status") or "unknown"
            reason = materialization.get("reason") or materialization.get("blocker")
            detail = f"source-preflight: {status}"
            if reason:
                detail += f" ({reason})"
            lines.append(detail)
        commands = suggestion.get("follow_up_commands") or []
        if commands:
            lines.append("follow-up:")
            for command in commands:
                lines.append(f"  - {command}")
    return "\n".join(lines)


def _parse_asm(lines: list[str]) -> list[_Instruction]:
    parsed: list[_Instruction] = []
    pending_relocation: str | None = None
    for raw_index, line in enumerate(lines):
        relocation = _relocation_symbol(line)
        if relocation is not None:
            if parsed and parsed[-1].opcode in _CALL_OPS:
                previous = parsed[-1]
                parsed[-1] = _Instruction(
                    previous.index,
                    previous.offset,
                    previous.line,
                    previous.opcode,
                    previous.operands,
                    relocation,
                )
            else:
                pending_relocation = relocation
            continue

        text = _instruction_text(line)
        if not text or text.endswith(":"):
            continue
        parts = text.split(None, 1)
        if not parts:
            continue
        opcode = parts[0].lower()
        if not re.match(r"^[a-z][a-z0-9_.+-]*$", opcode):
            continue
        operands = parts[1].strip() if len(parts) > 1 else ""
        parsed.append(
            _Instruction(
                index=raw_index,
                offset=_line_offset(line),
                line=line.strip(),
                opcode=opcode,
                operands=operands,
                relocation_symbol=pending_relocation,
            )
        )
        pending_relocation = None
    return parsed


def _instruction_text(line: str) -> str:
    text = line.strip()
    text = re.sub(r"^[+-]\s*", "", text)
    text = re.sub(r"^/\*\s*[0-9A-Fa-fx]+\s*\*/\s*", "", text)
    if "\t" in text:
        text = text.split("\t")[-1].strip()
    match = re.match(
        r"^(?:[0-9A-Fa-f]+|\+[0-9A-Fa-f]+):(?:\s+[0-9A-Fa-f]{2})*\s+(.*)$",
        text,
    )
    if match:
        text = match.group(1).strip()
    return text


def _relocation_symbol(line: str) -> str | None:
    text = line.strip()
    if "R_PPC_" not in text:
        return None
    parts = re.split(r"\s+|\t+", text)
    for token in reversed(parts):
        if token and not token.startswith("R_PPC_") and not token.endswith(":"):
            return token
    return None


def _line_offset(line: str) -> int | None:
    text = line.strip()
    match = re.match(r"^[+-]?([0-9A-Fa-f]+):", text)
    if match:
        return int(match.group(1), 16)
    match = re.match(r"^/\*\s*(0x[0-9A-Fa-f]+|[0-9A-Fa-f]+)\s*\*/", text)
    if match:
        value = match.group(1)
        return int(value, 16)
    return None


def _applicability(classification: dict[str, Any]) -> dict[str, Any]:
    primary = classification.get("primary")
    reasons: list[str] = []
    if primary == "control-flow-source-shape":
        reasons.append("primary=control-flow-source-shape")
    for reason in classification.get("reasons") or []:
        if not isinstance(reason, str):
            continue
        lowered = reason.lower()
        if (
            "control-flow-source-shape" in lowered
            or "control-flow/source shape" in lowered
        ):
            reasons.append(reason)
    if _metadata_dict(
        classification,
        "indexed_struct_pointer_materialization",
        "indexed-struct-pointer-materialization",
        "indexed_struct",
    ) is not None:
        reasons.append("indexed-struct-pointer-materialization evidence")
    if _metadata_dict(
        classification,
        "inline_boundary_artifact",
        "inline-boundary-artifact",
        "inline_boundary",
    ) is not None:
        reasons.append("inline-boundary call-shape evidence")

    return {
        "primary": primary,
        "is_control_flow_shape": bool(reasons),
        "reasons": reasons,
    }


def _summary(
    applicability: dict[str, Any],
    suggestions: list[dict[str, Any]],
    total_suggestions: int,
) -> str:
    if not applicability.get("is_control_flow_shape") and not suggestions:
        return "not classified as control-flow-source-shape and no ASM shape signals found"
    if not suggestions:
        return "control-flow-shape signals present, but no ranked transform matched"
    if len(suggestions) < total_suggestions:
        return (
            f"{len(suggestions)} of {total_suggestions} ranked "
            "control-flow-shape suggestions shown"
        )
    return f"{len(suggestions)} ranked control-flow-shape suggestion(s)"


def _detect_branch_idiom(
    *,
    function: str,
    target: list[_Instruction],
    current: list[_Instruction],
    classification: dict[str, Any],
) -> dict[str, Any] | None:
    target_ops = [item.opcode for item in target]
    current_ops = [item.opcode for item in current]
    target_has_explicit_branch = any(op in _COMPARE_OPS for op in target_ops) and any(
        _is_conditional_branch(op) for op in target_ops
    )
    target_li_values = _li_values(target)
    current_bool_cast_ops = sorted(set(current_ops) & _BOOL_CAST_OPS)
    if (
        not target_has_explicit_branch
        or not {"0", "1"}.issubset(target_li_values)
        or len(current_bool_cast_ops) < 2
    ):
        return None

    return _suggestion(
        function=function,
        kind="branch-idiom",
        confidence=0.86,
        recommendation=(
            "rewrite the boolean expression as an explicit if/else assigning "
            "0/1 so MWCC emits cmp/branch plus li 1/li 0 instead of a boolean cast"
        ),
        evidence={
            "target_branch_lines": _first_lines(
                target,
                lambda item: item.opcode in _COMPARE_OPS
                or _is_conditional_branch(item.opcode)
                or item.opcode == "li",
            ),
            "current_boolean_cast_ops": current_bool_cast_ops,
            "current_boolean_cast_lines": _first_lines(
                current,
                lambda item: item.opcode in _BOOL_CAST_OPS,
            ),
        },
        operator="bool-condition-spelling",
    )


def _detect_call_hoist(
    *,
    function: str,
    target: list[_Instruction],
    current: list[_Instruction],
    classification: dict[str, Any],
) -> dict[str, Any] | None:
    target_regions = _loop_regions(target)
    current_regions = _loop_regions(current)
    if not target_regions or not current_regions:
        return None

    target_calls = _calls(target)
    current_calls = _calls(current)
    candidates: list[tuple[tuple[int, str], dict[str, Any]]] = []
    for symbol in sorted(set(target_calls) & set(current_calls)):
        target_hit = _call_before_loop(target_calls[symbol], target_regions)
        current_hit = _call_inside_loop(current_calls[symbol], current_regions)
        if target_hit is not None and current_hit is not None:
            target_index, target_region = target_hit
            current_index, current_region = current_hit
            condition_lines = _loop_condition_lines_after_call(
                current,
                current_index,
                current_region,
            )
            confidence = 0.84 + (0.08 if condition_lines else 0.0)
            suggestion = _suggestion(
                function=function,
                kind="call-hoist",
                confidence=min(confidence, 0.95),
                recommendation=(
                    f"cache {symbol} before the loop and use the cached value "
                    "for the loop condition/trip count"
                ),
                evidence={
                    "symbol": symbol,
                    "target_placement": "before-loop",
                    "current_placement": "inside-loop",
                    "target_call_lines": _call_lines(target, symbol),
                    "current_call_lines": _call_lines(current, symbol),
                    "current_condition_lines": condition_lines,
                    "target_call_index": target_index,
                    "current_call_index": current_index,
                    "target_loop_bounds": target_region.to_payload(),
                    "current_loop_bounds": current_region.to_payload(),
                },
                operator="pointer-base-call-loop",
            )
            candidates.append(((1 if condition_lines else 0, symbol), suggestion))
    if candidates:
        candidates.sort(key=lambda item: (-item[0][0], item[0][1]))
        return candidates[0][1]
    return None


def _detect_pointer_walk(
    *,
    function: str,
    target: list[_Instruction],
    current: list[_Instruction],
    classification: dict[str, Any],
) -> dict[str, Any] | None:
    class_evidence = _metadata_dict(
        classification,
        "indexed_struct_pointer_materialization",
        "indexed-struct-pointer-materialization",
        "indexed_struct",
    )
    if isinstance(class_evidence, dict):
        return _suggestion(
            function=function,
            kind="pointer-walk-indexed-shape",
            confidence=0.82,
            recommendation=(
                "try a direct indexed array walk using base + index * stride + "
                "field offset instead of routing through a materialized element pointer"
            ),
            evidence={"classification": class_evidence},
            operator="pointer-walk-loop",
        )

    target_indexed = _first_lines(
        target,
        lambda item: item.opcode in _INDEXED_OPS or item.opcode in _STRIDE_OPS,
    )
    current_materialized = _current_materialized_pointer_lines(current)
    if not target_indexed or not current_materialized:
        return None
    return _suggestion(
        function=function,
        kind="pointer-walk-indexed-shape",
        confidence=0.70,
        recommendation=(
            "spell the loop as a direct indexed walk over the backing array, "
            "then access the field offset from that computed address"
        ),
        evidence={
            "target_indexed_or_stride_lines": target_indexed,
            "current_materialized_pointer_lines": current_materialized,
        },
        operator="pointer-walk-loop",
    )


def _detect_loop_peel_unroll(
    *,
    function: str,
    target: list[_Instruction],
    current: list[_Instruction],
    classification: dict[str, Any],
) -> dict[str, Any] | None:
    target_repeats = _repeated_body_signatures(target)
    current_repeats = _repeated_body_signatures(current)
    best_side = "target" if target_repeats[0] >= current_repeats[0] else "current"
    repeat_count, signature = max(target_repeats, current_repeats, key=lambda item: item[0])
    if repeat_count < 2:
        return None
    return _suggestion(
        function=function,
        kind="loop-peel-unroll",
        confidence=0.64,
        recommendation=(
            "test a first-iteration peel or small manual unroll that repeats "
            "the loop body shape before entering the counted loop"
        ),
        evidence={
            "side": best_side,
            "repeated_signature": signature,
            "repeated_signature_count": repeat_count,
        },
        operator="loop-init",
    )


def _detect_concurrent_buffer_lifetime(
    *,
    function: str,
    target: list[_Instruction],
    current: list[_Instruction],
    classification: dict[str, Any],
) -> dict[str, Any] | None:
    target_homes = _stack_home_calls_by_symbol(target)
    current_homes = _stack_home_calls_by_symbol(current)
    target_calls = _calls(target)
    current_calls = _calls(current)

    candidates: list[tuple[float, str, dict[str, Any]]] = []
    for symbol in sorted(target_homes):
        if symbol not in current_calls:
            continue
        target_call_count = len(target_calls.get(symbol, []))
        current_call_count = len(current_calls.get(symbol, []))
        if target_call_count != current_call_count:
            continue

        target_home_items = target_homes.get(symbol, [])
        current_home_items = current_homes.get(symbol, [])
        target_offsets = [item.offset for item in target_home_items]
        current_offsets = [item.offset for item in current_home_items]
        target_home_call_count = len({item.call_index for item in target_home_items})
        current_home_call_count = len({item.call_index for item in current_home_items})
        if len(set(target_offsets)) < 3:
            continue
        if current_home_call_count < 2:
            continue

        repeated = sorted(
            offset for offset, count in Counter(current_offsets).items() if count > 1
        )
        if len(set(current_offsets)) >= len(set(target_offsets)):
            continue
        if not repeated:
            continue
        alignment = _alignment(target_offsets)
        confidence = 0.88 if repeated and alignment >= 8 else 0.74
        candidates.append(
            (
                confidence,
                symbol,
                _suggestion(
                    function=function,
                    kind="concurrent-buffer-lifetime",
                    confidence=confidence,
                    recommendation=(
                        f"test a source reshape where {symbol} command buffers "
                        "are concurrently live before consumption; this can "
                        "prevent MWCC from coalescing mutually exclusive stack homes"
                    ),
                    evidence={
                        "consumer_symbol": symbol,
                        "target_call_count": target_call_count,
                        "current_call_count": current_call_count,
                        "target_home_bearing_call_count": target_home_call_count,
                        "current_home_bearing_call_count": current_home_call_count,
                        "target_unique_home_count": len(set(target_offsets)),
                        "current_unique_home_count": len(set(current_offsets)),
                        "current_repeated_offsets": repeated,
                        "target_alignment": alignment,
                        "target_stride_candidates": _stride_candidates(target_offsets),
                        "target_home_lines": [
                            item.line for item in target_homes[symbol]
                        ][:6],
                        "current_home_lines": [
                            item.line for item in current_homes[symbol]
                        ][:6],
                    },
                    operator=None,
                    follow_up_commands=[
                        f"tools/checkdiff.py {function} --format json",
                        f"melee-agent debug inspect frame-reservations -f {function} --json",
                    ],
                ),
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2]


def _detect_missing_extra_call_layer(
    *,
    function: str,
    target: list[_Instruction],
    current: list[_Instruction],
    classification: dict[str, Any],
) -> dict[str, Any] | None:
    inline_evidence = _metadata_dict(
        classification,
        "inline_boundary_artifact",
        "inline-boundary-artifact",
        "inline_boundary",
    )
    if isinstance(inline_evidence, dict):
        missing = _string_list(inline_evidence.get("missing_ref_calls"))
        extra = _string_list(inline_evidence.get("extra_current_calls"))
        if missing or extra:
            return _suggestion(
                function=function,
                kind="missing-extra-call-layer",
                confidence=0.78,
                recommendation=(
                    "restore the missing helper/call layer or remove the extra "
                    "call layer before chasing downstream frame/register deltas"
                ),
                evidence={
                    "missing_ref_calls": missing,
                    "extra_current_calls": extra,
                },
                operator="call-return-compare-chain",
            )

    target_calls = _calls(target)
    current_calls = _calls(current)
    target_total = sum(len(indices) for indices in target_calls.values())
    current_total = sum(len(indices) for indices in current_calls.values())
    if abs(target_total - current_total) < 2:
        return None
    return _suggestion(
        function=function,
        kind="missing-extra-call-layer",
        confidence=0.60,
        recommendation=(
            "compare helper layering: one side has materially more calls, so "
            "the source may be missing a wrapper/helper boundary"
        ),
        evidence={
            "target_call_count": target_total,
            "current_call_count": current_total,
            "target_calls": {key: len(value) for key, value in target_calls.items()},
            "current_calls": {key: len(value) for key, value in current_calls.items()},
        },
        operator="call-return-compare-chain",
    )


def _suggestion(
    *,
    function: str,
    kind: str,
    confidence: float,
    recommendation: str,
    evidence: dict[str, Any],
    operator: str | None,
    follow_up_commands: list[str] | None = None,
) -> dict[str, Any]:
    commands = follow_up_commands
    if commands is None and operator:
        commands = [
            "melee-agent debug mutate control-flow-shape-search "
            f"-f {function} --operator {operator} --json"
        ]
    payload = {
        "kind": kind,
        "confidence": confidence,
        "recommendation": recommendation,
        "evidence": evidence,
        "follow_up_commands": commands or [],
    }
    if operator:
        payload["operator"] = operator
    return payload


def annotate_source_materialization(
    report: dict[str, Any],
    *,
    function: str | None = None,
    source_text: str,
    max_probes_per_operator: int = 1,
) -> dict[str, Any]:
    """Annotate generated-operator suggestions with source probe availability."""
    from ..control_flow_shape import scan_control_flow_shape_probes

    report_function = function or report.get("function")
    if not isinstance(report_function, str) or not report_function:
        return report
    suggestions = report.get("suggestions")
    if not isinstance(suggestions, list):
        return report

    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        operator = suggestion.get("operator")
        if not isinstance(operator, str) or not operator:
            continue
        probes, scan_status = scan_control_flow_shape_probes(
            source_text,
            report_function,
            operator_filter=(operator,),
            max_probes=max(1, max_probes_per_operator),
        )
        reason = str(scan_status.get("reason") or "")
        blocker = scan_status.get("blocker")
        materialization = {
            "operator": operator,
            "status": "materializable" if probes else "non-materializable",
            "probe_count": len(probes),
            "blocker": blocker,
            "reason": reason,
        }
        if probes:
            materialization["example_probe_label"] = probes[0].label
        else:
            non_materializable_reason = reason or str(blocker or "no probes")
            suggestion["follow_up_commands"] = []
            suggestion["non_materializable_reason"] = non_materializable_reason
        suggestion["source_materialization"] = materialization
    return report


def _is_conditional_branch(opcode: str) -> bool:
    return opcode.startswith(_CONDITIONAL_BRANCH_PREFIXES) and opcode != "b"


def _li_values(instructions: list[_Instruction]) -> set[str]:
    values: set[str] = set()
    for item in instructions:
        if item.opcode != "li":
            continue
        pieces = [piece.strip() for piece in item.operands.split(",")]
        if len(pieces) >= 2:
            values.add(pieces[1].lower())
    return values


def _first_lines(
    instructions: list[_Instruction],
    predicate,
    *,
    limit: int = 6,
) -> list[str]:
    return [item.line for item in instructions if predicate(item)][:limit]


def _loop_regions(instructions: list[_Instruction]) -> list[_LoopRegion]:
    regions: list[_LoopRegion] = []
    for start, item in enumerate(instructions):
        if item.opcode not in _LOOP_START_OPS:
            continue
        end = next(
            (
                index
                for index, candidate in enumerate(
                    instructions[start + 1 :],
                    start=start + 1,
                )
                if candidate.opcode in _LOOP_END_OPS
            ),
            None,
        )
        if end is None:
            continue
        regions.append(_LoopRegion(start=start, end=end, kind="counted"))

    offset_to_index = {
        item.offset: index
        for index, item in enumerate(instructions)
        if item.offset is not None
    }
    sorted_offsets = sorted(offset_to_index)
    for end, item in enumerate(instructions):
        if item.offset is None or not _is_conditional_branch(item.opcode):
            continue
        target_offset = _branch_target_offset(item.operands)
        if target_offset is None or target_offset >= item.offset:
            continue
        start = _nearest_offset_index(target_offset, sorted_offsets, offset_to_index)
        if start is not None and start < end:
            regions.append(_LoopRegion(start=start, end=end, kind="backward-branch"))

    unique: dict[tuple[int, int, str], _LoopRegion] = {}
    for region in regions:
        unique[(region.start, region.end, region.kind)] = region
    return sorted(unique.values(), key=lambda item: (item.start, item.end, item.kind))


def _branch_target_offset(operands: str) -> int | None:
    match = re.search(r"\+0x([0-9A-Fa-f]+)>", operands)
    if match:
        return int(match.group(1), 16)
    match = re.search(r"\b0x([0-9A-Fa-f]+)\b", operands)
    if match:
        return int(match.group(1), 16)
    return None


def _nearest_offset_index(
    target_offset: int,
    sorted_offsets: list[int],
    offset_to_index: dict[int, int],
) -> int | None:
    best: int | None = None
    for offset in sorted_offsets:
        if offset > target_offset:
            break
        best = offset
    if best is None:
        return None
    return offset_to_index[best]


def _call_before_loop(
    call_indices: list[int],
    regions: list[_LoopRegion],
) -> tuple[int, _LoopRegion] | None:
    for call_index in call_indices:
        for region in regions:
            if call_index < region.start:
                return call_index, region
    return None


def _call_inside_loop(
    call_indices: list[int],
    regions: list[_LoopRegion],
) -> tuple[int, _LoopRegion] | None:
    for call_index in call_indices:
        for region in regions:
            if region.start <= call_index <= region.end:
                return call_index, region
    return None


def _loop_condition_lines_after_call(
    instructions: list[_Instruction],
    call_index: int,
    region: _LoopRegion,
) -> list[str]:
    window = instructions[
        call_index + 1 : min(len(instructions), region.end + 1, call_index + 5)
    ]
    for index, item in enumerate(window):
        if item.opcode not in _COMPARE_OPS:
            continue
        for branch in window[index + 1 : index + 3]:
            if _is_backward_branch_instruction(branch):
                return [item.line, branch.line]
    return []


def _is_backward_branch_instruction(item: _Instruction) -> bool:
    if item.offset is None or not _is_conditional_branch(item.opcode):
        return False
    target_offset = _branch_target_offset(item.operands)
    return target_offset is not None and target_offset < item.offset


def _stack_home_calls_by_symbol(
    instructions: list[_Instruction],
    *,
    window_size: int = 8,
) -> dict[str, list[_StackHomeCall]]:
    grouped: dict[str, list[_StackHomeCall]] = {}
    for index, item in enumerate(instructions):
        if item.opcode not in _CALL_OPS:
            continue
        symbol = item.relocation_symbol or _call_symbol(item.operands)
        if symbol is None:
            continue
        homes = _stack_homes_before_call(instructions, index, window_size=window_size)
        for offset, line in homes:
            grouped.setdefault(symbol, []).append(
                _StackHomeCall(index, symbol, offset, line)
            )
    return grouped


def _stack_homes_before_call(
    instructions: list[_Instruction],
    call_index: int,
    *,
    window_size: int,
) -> list[tuple[int, str]]:
    constants: dict[str, int] = {}
    homes: dict[str, tuple[int, str]] = {}
    for item in instructions[max(0, call_index - window_size) : call_index]:
        if item.opcode in _CALL_OPS:
            for reg in _VOLATILE_REGS:
                _clear_register(constants, homes, reg)
            continue
        dest = _destination_register(item)
        if dest is None:
            continue
        if item.opcode == "li":
            value = _second_immediate(item.operands)
            _set_or_clear(constants, homes, dest, value=value)
            continue
        if item.opcode == "addi":
            parsed = _parse_addi(item.operands)
            if parsed is None:
                _clear_register(constants, homes, dest)
                continue
            dst, base, imm = parsed
            if base == "r1":
                homes[dst] = (imm, item.line)
                constants.pop(dst, None)
            elif base in {"r0", "0"}:
                constants[dst] = imm
                homes.pop(dst, None)
            else:
                _clear_register(constants, homes, dst)
            continue
        if item.opcode == "add":
            parsed_add = _parse_add(item.operands)
            if parsed_add is None:
                _clear_register(constants, homes, dest)
                continue
            dst, left, right = parsed_add
            if left == "r1" and right in constants:
                homes[dst] = (constants[right], item.line)
                constants.pop(dst, None)
            elif right == "r1" and left in constants:
                homes[dst] = (constants[left], item.line)
                constants.pop(dst, None)
            else:
                _clear_register(constants, homes, dst)
            continue
        if item.opcode == "mr":
            regs = _registers(item.operands)
            if len(regs) >= 2 and regs[1] in homes:
                homes[regs[0]] = homes[regs[1]]
                constants.pop(regs[0], None)
            elif len(regs) >= 2 and regs[1] in constants:
                constants[regs[0]] = constants[regs[1]]
                homes.pop(regs[0], None)
            else:
                _clear_register(constants, homes, dest)
            continue
        _clear_register(constants, homes, dest)

    result: list[tuple[int, str]] = []
    seen_offsets: set[int] = set()
    for reg in _ARG_REGS:
        if reg not in homes:
            continue
        offset, line = homes[reg]
        if offset in seen_offsets:
            continue
        seen_offsets.add(offset)
        result.append((offset, line))
    return result


def _registers(operands: str) -> list[str]:
    return re.findall(r"\br\d+\b", operands.lower())


def _destination_register(item: _Instruction) -> str | None:
    if item.opcode.startswith("st") or item.opcode in _COMPARE_OPS:
        return None
    regs = _registers(item.operands)
    return regs[0] if regs else None


def _parse_int(value: str) -> int | None:
    try:
        return int(value.strip(), 0)
    except ValueError:
        return None


def _second_immediate(operands: str) -> int | None:
    pieces = [piece.strip() for piece in operands.split(",")]
    if len(pieces) < 2:
        return None
    return _parse_int(pieces[1])


def _parse_addi(operands: str) -> tuple[str, str, int] | None:
    pieces = [piece.strip().lower() for piece in operands.split(",")]
    if len(pieces) != 3:
        return None
    imm = _parse_int(pieces[2])
    if imm is None:
        return None
    return pieces[0], pieces[1], imm


def _parse_add(operands: str) -> tuple[str, str, str] | None:
    pieces = [piece.strip().lower() for piece in operands.split(",")]
    if len(pieces) != 3:
        return None
    return pieces[0], pieces[1], pieces[2]


def _clear_register(
    constants: dict[str, int],
    homes: dict[str, tuple[int, str]],
    reg: str,
) -> None:
    constants.pop(reg, None)
    homes.pop(reg, None)


def _set_or_clear(
    constants: dict[str, int],
    homes: dict[str, tuple[int, str]],
    reg: str,
    *,
    value: int | None,
) -> None:
    if value is None:
        _clear_register(constants, homes, reg)
        return
    constants[reg] = value
    homes.pop(reg, None)


def _alignment(offsets: list[int]) -> int:
    if not offsets:
        return 0
    alignment = 0
    for offset in offsets:
        lowbit = offset & -offset if offset else 0
        if lowbit:
            alignment = lowbit if alignment == 0 else min(alignment, lowbit)
    return alignment


def _stride_candidates(offsets: list[int]) -> list[int]:
    unique = sorted(set(offsets))
    strides = [
        right - left for left, right in zip(unique, unique[1:]) if right > left
    ]
    if not strides:
        return []
    counts = Counter(strides)
    return [stride for stride, _count in counts.most_common(3)]


def _calls(instructions: list[_Instruction]) -> dict[str, list[int]]:
    calls: dict[str, list[int]] = {}
    for index, item in enumerate(instructions):
        if item.opcode not in _CALL_OPS:
            continue
        symbol = item.relocation_symbol or _call_symbol(item.operands)
        if symbol is None:
            continue
        calls.setdefault(symbol, []).append(index)
    return calls


def _call_lines(instructions: list[_Instruction], symbol: str) -> list[str]:
    lines: list[str] = []
    for item in instructions:
        if item.opcode not in _CALL_OPS:
            continue
        if (item.relocation_symbol or _call_symbol(item.operands)) == symbol:
            lines.append(item.line)
    return lines


def _call_symbol(operands: str) -> str | None:
    cleaned = operands.strip()
    if not cleaned or cleaned.startswith("0x") or "<" in cleaned:
        return None
    return cleaned.split()[0]


def _current_materialized_pointer_lines(instructions: list[_Instruction]) -> list[str]:
    lines: list[str] = []
    for item in instructions:
        if item.opcode in {"add", "addi"}:
            lines.append(item.line)
        elif re.search(r"\b0\([^)]*\)", item.operands):
            lines.append(item.line)
    return lines[:6]


def _repeated_body_signatures(instructions: list[_Instruction]) -> tuple[int, str]:
    signatures = [
        _signature(item)
        for item in instructions
        if item.opcode
        not in {
            "b",
            "blr",
            "mtctr",
            "mflr",
            "stwu",
            "stw",
        }
    ]
    if len(signatures) < 2:
        return 0, ""

    pair_counter: Counter[tuple[str, str]] = Counter()
    for left, right in zip(signatures, signatures[1:]):
        if left == right:
            continue
        pair_counter[(left, right)] += 1
    if not pair_counter:
        return 0, ""
    (left, right), count = pair_counter.most_common(1)[0]
    return count, f"{left}; {right}"


def _signature(item: _Instruction) -> str:
    operands = re.sub(r"\br\d+\b", "rN", item.operands)
    operands = re.sub(r"\bf\d+\b", "fN", operands)
    operands = re.sub(r"0x[0-9A-Fa-f]+", "imm", operands)
    operands = re.sub(r"\b\d+\b", "imm", operands)
    return f"{item.opcode} {operands}".strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _format_evidence_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _metadata_dict(classification: dict[str, Any], *names: str) -> dict[str, Any] | None:
    normalized_names = {_normalize_key(name) for name in names}
    stack: list[Any] = [classification]
    while stack:
        value = stack.pop()
        if not isinstance(value, dict):
            continue
        for key, child in value.items():
            if _normalize_key(str(key)) in normalized_names and isinstance(child, dict):
                return child
            if isinstance(child, dict):
                stack.append(child)
    return None


def _normalize_key(key: str) -> str:
    return key.replace("-", "_")
