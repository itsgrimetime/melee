"""Materialize bounded source probes for explicit scheduler-order targets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.mwcc_debug.asm_windows import AsmInstruction, parse_asm_lines
from src.mwcc_debug.source_patch import find_function
from src.search.directed.anchors import Anchor


@dataclass(frozen=True)
class SchedulerOrderInstruction:
    opcode: str
    operands: str | None = None
    operands_contains: str | None = None
    code_offset: int | None = None
    instruction_class: str | None = None
    source_expression: str | None = None


@dataclass(frozen=True)
class SchedulerOrderTarget:
    function: str
    target_first: SchedulerOrderInstruction
    target_second: SchedulerOrderInstruction
    desired_order: tuple[str, str] = ("target_first", "target_second")
    source_region: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SchedulerOrderEvaluation:
    status: str
    first_index: int | None
    second_index: int | None
    rationale: str


def parse_scheduler_order_target(payload: Mapping[str, Any] | str | Path) -> SchedulerOrderTarget:
    """Parse a two-instruction scheduler-order target from a dict, JSON, or path."""

    raw = _load_payload(payload)
    kind = raw.get("kind")
    if kind is not None and kind != "scheduler-order-target":
        raise ValueError("scheduler-order target kind must be 'scheduler-order-target'")
    function = raw.get("function")
    if not isinstance(function, str) or not function.strip():
        raise ValueError("scheduler-order target requires function")
    if "target_first" not in raw or "target_second" not in raw:
        raise ValueError("scheduler-order target requires target_first and target_second")

    desired_raw = raw.get("desired_order", ("target_first", "target_second"))
    if not isinstance(desired_raw, (list, tuple)):
        raise ValueError("desired_order must contain target_first and target_second")
    desired_order = tuple(desired_raw)
    if (
        len(desired_order) != 2
        or any(not isinstance(item, str) for item in desired_order)
        or set(desired_order) != {"target_first", "target_second"}
    ):
        raise ValueError("desired_order must contain target_first and target_second")

    source_region = raw.get("source_region", {})
    if source_region is None:
        source_region = {}
    if not isinstance(source_region, dict):
        raise ValueError("source_region must be an object when present")

    return SchedulerOrderTarget(
        function=function,
        target_first=_parse_instruction(raw["target_first"], label="target_first"),
        target_second=_parse_instruction(raw["target_second"], label="target_second"),
        desired_order=desired_order,
        source_region=dict(source_region),
    )


def evaluate_scheduler_order_in_asm(
    lines: Sequence[str],
    target: SchedulerOrderTarget,
) -> SchedulerOrderEvaluation:
    """Evaluate whether parsed asm emits the target pair in target order."""

    instructions = parse_asm_lines(lines)
    first_matches = _matching_instructions(instructions, target.target_first)
    second_matches = _matching_instructions(instructions, target.target_second)
    if not first_matches or not second_matches:
        missing = []
        if not first_matches:
            missing.append("target_first")
        if not second_matches:
            missing.append("target_second")
        return SchedulerOrderEvaluation(
            status="missing",
            first_index=None,
            second_index=None,
            rationale=f"missing {', '.join(missing)}",
        )
    if len(first_matches) != 1 or len(second_matches) != 1:
        return SchedulerOrderEvaluation(
            status="ambiguous",
            first_index=None,
            second_index=None,
            rationale=(
                "target instruction matches are not unique "
                f"(first={len(first_matches)}, second={len(second_matches)})"
            ),
        )
    first = first_matches[0]
    second = second_matches[0]
    if first.index == second.index:
        return SchedulerOrderEvaluation(
            status="ambiguous",
            first_index=first.index,
            second_index=second.index,
            rationale="target instructions resolve to the same asm instruction",
        )
    positions = {
        "target_first": first.index,
        "target_second": second.index,
    }
    desired_first, desired_second = target.desired_order
    if positions[desired_first] < positions[desired_second]:
        return SchedulerOrderEvaluation(
            status="target-order",
            first_index=first.index,
            second_index=second.index,
            rationale=f"{desired_first} appears before {desired_second}",
        )
    return SchedulerOrderEvaluation(
        status="observed-order",
        first_index=first.index,
        second_index=second.index,
        rationale=f"{desired_second} appears before {desired_first}",
    )


def iter_scheduler_order_source_anchors(
    source_text: str,
    function: str,
    target: SchedulerOrderTarget,
    remaining: int,
):
    """Yield conservative exact-span anchors for a scheduler-order source window."""

    if remaining <= 0 or function != target.function:
        return
    located = _locate_unique_safe_region(source_text, function, target)
    if located is None:
        return
    _body_start, region_start, region_end = located
    region_text = source_text[region_start:region_end]
    yielded = 0
    for anchor in (
        _anchor_iv_init_before_bias(source_text, region_text, region_start),
        _anchor_split_float_cast_temp(source_text, region_text, region_start),
        _anchor_empty_barrier_before_float_cast(source_text, region_text, region_start),
    ):
        if anchor is None:
            continue
        yield anchor
        yielded += 1
        if yielded >= remaining:
            return


def _load_payload(payload: Mapping[str, Any] | str | Path) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    if isinstance(payload, Path):
        loaded = json.loads(payload.read_text(encoding="utf-8"))
    elif isinstance(payload, str):
        stripped = payload.lstrip()
        if stripped.startswith("{"):
            loaded = json.loads(payload)
        else:
            maybe_path = Path(payload).expanduser()
            try:
                if maybe_path.exists():
                    loaded = json.loads(maybe_path.read_text(encoding="utf-8"))
                else:
                    loaded = json.loads(payload)
            except OSError:
                loaded = json.loads(payload)
    else:
        raise TypeError("scheduler-order target must be a mapping, JSON string, or path")
    if not isinstance(loaded, Mapping):
        raise ValueError("scheduler-order target JSON must be an object")
    return loaded


def _parse_instruction(raw: Any, *, label: str) -> SchedulerOrderInstruction:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be an object")
    opcode = raw.get("opcode")
    if not isinstance(opcode, str) or not opcode.strip():
        raise ValueError(f"{label} requires opcode")
    operands = raw.get("operands")
    operands_contains = raw.get("operands_contains")
    if operands is not None and not isinstance(operands, str):
        raise ValueError(f"{label}.operands must be a string")
    if operands_contains is not None and not isinstance(operands_contains, str):
        raise ValueError(f"{label}.operands_contains must be a string")
    return SchedulerOrderInstruction(
        opcode=opcode.strip().lower(),
        operands=operands,
        operands_contains=operands_contains,
        code_offset=_parse_code_offset(raw.get("code_offset")),
        instruction_class=_optional_str(raw.get("instruction_class"), label, "instruction_class"),
        source_expression=_optional_str(raw.get("source_expression"), label, "source_expression"),
    )


def _optional_str(value: Any, label: str, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label}.{field_name} must be a string")
    return value


def _parse_code_offset(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return int(value.strip(), 0)
    raise ValueError("code_offset must be an integer or numeric string")


def _matching_instructions(
    instructions: Sequence[AsmInstruction],
    target: SchedulerOrderInstruction,
) -> list[AsmInstruction]:
    matches: list[AsmInstruction] = []
    for inst in instructions:
        if target.code_offset is not None and inst.offset != target.code_offset:
            continue
        if inst.opcode.lower() != target.opcode.lower():
            continue
        operands = _normalize_operands(inst.operands)
        if target.operands is not None and operands != _normalize_operands(target.operands):
            continue
        if (
            target.operands_contains is not None
            and _normalize_operands(target.operands_contains) not in operands
        ):
            continue
        matches.append(inst)
    return matches


def _normalize_operands(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _locate_unique_safe_region(
    source_text: str,
    function: str,
    target: SchedulerOrderTarget,
) -> tuple[int, int, int] | None:
    span = find_function(source_text, function)
    if span is None:
        return None
    body_text = source_text[span.body_open:span.full_end]
    contains = target.source_region.get("contains")
    if not isinstance(contains, list) or not contains:
        return None
    needles = [item for item in contains if isinstance(item, str) and item]
    if len(needles) != len(contains):
        return None

    first = needles[0]
    starts = [m.start() for m in re.finditer(re.escape(first), body_text)]
    matches: list[tuple[int, int]] = []
    for start in starts:
        cursor = start
        ok = True
        for needle in needles:
            found = body_text.find(needle, cursor)
            if found < 0:
                ok = False
                break
            cursor = found + len(needle)
        if ok:
            matches.append((start, cursor))
    if len(matches) != 1:
        return None
    local_start, local_end = matches[0]
    local_start, local_end = _expand_to_safe_line_window(body_text, local_start, local_end)
    region_start = span.body_open + local_start
    region_end = span.body_open + local_end
    window = source_text[region_start:region_end]
    if not _is_safe_source_window(window):
        return None
    return span.body_open, region_start, region_end


def _expand_to_safe_line_window(
    body_text: str,
    local_start: int,
    local_end: int,
) -> tuple[int, int]:
    line_start = body_text.rfind("\n", 0, local_start) + 1
    line_end = body_text.find("\n", local_end)
    if line_end < 0:
        line_end = len(body_text)
    else:
        line_end += 1

    while _brace_delta(body_text[line_start:line_end]) > 0 and line_end < len(body_text):
        next_end = body_text.find("\n", line_end)
        if next_end < 0:
            line_end = len(body_text)
        else:
            line_end = next_end + 1
    return line_start, line_end


def _is_safe_source_window(window: str) -> bool:
    if "#" in window:
        return False
    if re.search(r"^\s*[A-Za-z_]\w*\s*:", window, re.MULTILINE):
        return False
    if re.search(r"\b(?:goto|return|break|continue|case|default)\b", window):
        return False
    depth = 0
    for ch in window:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _brace_delta(window: str) -> int:
    depth = 0
    for ch in window:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    return depth


def _anchor_iv_init_before_bias(
    source_text: str,
    region_text: str,
    region_start: int,
) -> Anchor | None:
    match = re.search(
        r"^(?P<indent>[ \t]*)i\s*=\s*0;\n",
        region_text,
        re.MULTILINE,
    )
    if match is None:
        return None
    span_start = region_start + match.start()
    span_end = region_start + match.end()
    span_text = source_text[span_start:span_end]
    replacement_text = f"{span_text}{match.group('indent')}do {{ }} while (0);\n"
    return Anchor(
        mutator_key="scheduler_anchor_iv_init_before_bias",
        span=(span_start, span_end),
        payload={
            "span_text": span_text,
            "replacement_text": replacement_text,
        },
    )


def _anchor_split_float_cast_temp(
    source_text: str,
    region_text: str,
    region_start: int,
) -> Anchor | None:
    match = re.search(
        r"^(?P<indent>[ \t]*)f32\s+fi\s*=\s*\(f32\)\s*i;",
        region_text,
        re.MULTILINE,
    )
    if match is None:
        return None
    span_start = region_start + match.start()
    span_end = region_start + match.end()
    if span_end < len(source_text) and source_text[span_end] == "\n":
        span_end += 1
    span_text = source_text[span_start:span_end]
    indent = match.group("indent")
    replacement_text = f"{indent}f32 fi;\n{indent}fi = (f32) i;\n"
    return Anchor(
        mutator_key="scheduler_split_float_cast_temp",
        span=(span_start, span_end),
        payload={
            "span_text": span_text,
            "replacement_text": replacement_text,
        },
    )


def _anchor_empty_barrier_before_float_cast(
    source_text: str,
    region_text: str,
    region_start: int,
) -> Anchor | None:
    match = re.search(
        r"^(?P<indent>[ \t]*)f32\s+fi\s*=\s*\(f32\)\s*i;",
        region_text,
        re.MULTILINE,
    )
    if match is None:
        return None
    span_start = region_start + match.start()
    span_end = region_start + match.end()
    if span_end < len(source_text) and source_text[span_end] == "\n":
        span_end += 1
    span_text = source_text[span_start:span_end]
    indent = match.group("indent")
    replacement_text = f"{indent}do {{ }} while (0);\n{span_text}"
    return Anchor(
        mutator_key="scheduler_empty_barrier_before_float_cast",
        span=(span_start, span_end),
        payload={
            "span_text": span_text,
            "replacement_text": replacement_text,
        },
    )
