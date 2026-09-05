"""Candidate generation and rendering for `debug suggest inlines`."""
from __future__ import annotations

import difflib
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, Mapping, Optional, Sequence

from .ast_walker import walk_function
from .source_patch import find_function as find_source_function
from .source_shape import (
    CandidatePatch,
    InlineCandidate,
    SourceAnchor,
    SourceShapeReport,
    rank_scores,
)
from .source_hunks import diff_line_hunks
from .source_spans import (
    CallArgumentSpan,
    StatementSpan,
    SpanGroup,
    find_call_argument_spans,
    find_repeated_call_groups,
    list_statement_spans,
    reject_reason_for_span_group,
)


def _candidate_id(kind: str, idx: int) -> str:
    return f"{kind}-{idx:04d}"


def _char_index_for_byte(source: str, byte_offset: int) -> int:
    """Convert a tree-sitter UTF-8 byte offset to a Python string index."""
    return len(source.encode("utf-8")[:byte_offset].decode("utf-8"))


def _char_range_for_bytes(source: str, byte_range: tuple[int, int]) -> tuple[int, int]:
    start, end = byte_range
    return (
        _char_index_for_byte(source, start),
        _char_index_for_byte(source, end),
    )


def _helper_name(function: str, kind: str, idx: int) -> str:
    safe_kind = kind.replace("-", "_")
    return f"{function}_{safe_kind}_{idx:04d}"


_TRANSLATE_CALLS = (
    "HSD_JObjSetTranslateX",
    "HSD_JObjSetTranslateY",
    "HSD_JObjSetTranslateZ",
)
_ALL_INLINE_HELPER_CANDIDATES_REJECTED = "all-inline-helper-candidates-rejected"
_INLINE_LOCAL_WRITE_FAMILY = "inline-local-write-helper"
_INLINE_LOCAL_WRITE_TERMINAL_KIND = "inline-local-write-source-shape-exhausted"
_INLINE_LOCAL_WRITE_TERMINAL_REASON = (
    "inline-local-write-helper-family-exhausted/"
    "no-target-or-expression-improvement"
)


@dataclass(frozen=True)
class SpanAssignment:
    statement: StatementSpan
    lhs_text: str
    rhs_text: str
    lhs_kind: str
    name: str


@dataclass(frozen=True)
class SpanLocalWritePlan:
    statements: tuple[StatementSpan, ...]
    input_names: tuple[str, ...]
    simple_outputs: tuple[str, ...]
    pointee_store_params: tuple[str, ...]
    unknown_outputs: tuple[str, ...]
    read_before_write_outputs: tuple[str, ...]
    macro_args: tuple[str, ...]
    has_declaration: bool
    assignments: tuple[SpanAssignment, ...]
    blockers: tuple[str, ...]


def _anchor_from_group(function: str, group: SpanGroup) -> SourceAnchor:
    return SourceAnchor(
        function=function,
        scope_path=group.scope_path,
        byte_range=group.byte_range,
        line_range=group.line_range,
        kind="repeated",
        reason=group.reason,
    )


def _call_names_for_spans(spans: tuple[StatementSpan, ...]) -> set[str]:
    return {
        match.group(1)
        for span in spans
        for match in _CALL_NAME_RE.finditer(span.text)
        if match.group(1) not in _CALL_NAME_KEYWORDS
    }


def _reads_for_spans(
    spans: tuple[StatementSpan, ...],
    call_names: set[str],
) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        name
        for span in spans
        for name in span.reads
        if name not in call_names
    ))


def _candidate_from_group(
    function: str,
    idx: int,
    group: SpanGroup,
    *,
    kind: str = "void-helper",
    helper_name: Optional[str] = None,
    reads: Optional[tuple[str, ...]] = None,
    writes: Optional[tuple[str, ...]] = None,
    rejection_reason: Optional[str] = None,
    metadata: Optional[dict[str, object]] = None,
) -> InlineCandidate:
    call_names = {
        match.group(1)
        for span in group.spans
        for match in _CALL_NAME_RE.finditer(span.text)
        if match.group(1) not in _CALL_NAME_KEYWORDS
    }
    return InlineCandidate(
        candidate_id=_candidate_id(kind, idx),
        kind=kind,
        anchor=_anchor_from_group(function, group),
        helper_name=(
            helper_name
            if helper_name is not None
            else _helper_name(function, kind.replace("-", "_"), idx)
        ),
        reads=reads if reads is not None else _reads_for_spans(group.spans, call_names),
        writes=(
            writes
            if writes is not None
            else tuple(dict.fromkeys(
                name for span in group.spans for name in span.writes
            ))
        ),
        source_excerpt="\n".join(span.text for span in group.spans),
        rejection_reason=rejection_reason,
        metadata={} if metadata is None else metadata,
    )


def _candidate_from_arg(function: str, idx: int, arg: CallArgumentSpan) -> InlineCandidate:
    anchor = SourceAnchor(
        function=function,
        scope_path=arg.scope_path,
        byte_range=arg.byte_range,
        line_range=arg.line_range,
        kind="pattern",
        reason=f"short-lived argument temp for {arg.call_name}",
    )
    return InlineCandidate(
        candidate_id=_candidate_id("arg-temp", idx),
        kind="arg-temp",
        anchor=anchor,
        helper_name=_helper_name(function, "arg_temp", idx),
        reads=(arg.text,),
        writes=(),
        source_excerpt=arg.statement.text,
    )


def _candidate_from_hidden_dirty_arg(
    function: str,
    idx: int,
    arg: CallArgumentSpan,
    *,
    helper_function: Optional[str] = None,
) -> InlineCandidate:
    anchor = SourceAnchor(
        function=function,
        scope_path=arg.scope_path,
        byte_range=arg.byte_range,
        line_range=arg.line_range,
        kind="pattern",
        reason=(
            f"short-lived argument temp for hidden HSD_JObjSetMtxDirtySub "
            f"inside {arg.call_name}"
        ),
    )
    metadata = {
        "visible_call": arg.call_name,
        "hidden_call": "HSD_JObjSetMtxDirtySub",
    }
    if helper_function is not None:
        metadata["helper_function"] = helper_function
    return InlineCandidate(
        candidate_id=_candidate_id("hidden-dirty-arg-temp", idx),
        kind="hidden-dirty-arg-temp",
        anchor=anchor,
        helper_name=_helper_name(function, "hidden_dirty_arg_temp", idx),
        reads=(arg.text,),
        writes=(),
        source_excerpt=arg.statement.text,
        metadata=metadata,
    )


def _candidate_from_hidden_dirty_group(
    function: str,
    idx: int,
    args: list[CallArgumentSpan],
    *,
    helper_function: Optional[str] = None,
) -> InlineCandidate:
    first = args[0]
    last = args[-1]
    visible_calls = tuple(dict.fromkeys(arg.call_name for arg in args))
    metadata = {
        "visible_calls": ",".join(visible_calls),
        "hidden_call": "HSD_JObjSetMtxDirtySub",
        "arg_text": first.text,
    }
    if helper_function is not None:
        metadata["helper_function"] = helper_function
    return InlineCandidate(
        candidate_id=_candidate_id("hidden-dirty-arg-temp-group", idx),
        kind="hidden-dirty-arg-temp-group",
        anchor=SourceAnchor(
            function=function,
            scope_path=first.scope_path,
            byte_range=(first.byte_range[0], last.byte_range[1]),
            line_range=(first.line_range[0], last.line_range[1]),
            kind="pattern",
            reason=(
                "grouped short-lived argument temp for hidden "
                "HSD_JObjSetMtxDirtySub inside translate X/Y/Z calls"
            ),
        ),
        helper_name=_helper_name(function, "hidden_dirty_arg_temp_group", idx),
        reads=(first.text,),
        writes=(),
        source_excerpt="\n".join(
            dict.fromkeys(arg.statement.text for arg in args)
        ),
        metadata=metadata,
    )


def _is_first_call_argument(source: str, arg: CallArgumentSpan) -> bool:
    arg_start, _ = _char_range_for_bytes(source, arg.byte_range)
    call_start = source.rfind(f"{arg.call_name}(", 0, arg_start)
    if call_start < 0:
        return False
    prefix_end = call_start + len(arg.call_name) + 1
    return source[prefix_end:arg_start].strip() == ""


def _hidden_dirty_arg_candidates(
    source: str,
    function: str,
    start_idx: int,
    *,
    report_function: Optional[str] = None,
) -> list[InlineCandidate]:
    out: list[InlineCandidate] = []
    idx = start_idx
    report_fn = function if report_function is None else report_function
    for call_name in _TRANSLATE_CALLS:
        for arg in find_call_argument_spans(source, function, call_name):
            if not arg.text or not _is_first_call_argument(source, arg):
                continue
            out.append(_candidate_from_hidden_dirty_arg(
                report_fn,
                idx,
                arg,
                helper_function=None if report_fn == function else function,
            ))
            idx += 1
    return out


def _hidden_dirty_group_candidates(
    source: str,
    function: str,
    start_idx: int,
    *,
    report_function: Optional[str] = None,
) -> list[InlineCandidate]:
    grouped: dict[tuple[tuple[str, ...], str], list[CallArgumentSpan]] = {}
    for call_name in _TRANSLATE_CALLS:
        for arg in find_call_argument_spans(source, function, call_name):
            if not arg.text or not _is_first_call_argument(source, arg):
                continue
            grouped.setdefault((arg.scope_path, arg.text), []).append(arg)

    out: list[InlineCandidate] = []
    idx = start_idx
    report_fn = function if report_function is None else report_function
    for args in grouped.values():
        visible = {arg.call_name for arg in args}
        if not set(_TRANSLATE_CALLS).issubset(visible):
            continue
        args = sorted(args, key=lambda arg: arg.byte_range)
        out.append(_candidate_from_hidden_dirty_group(
            report_fn,
            idx,
            args,
            helper_function=None if report_fn == function else function,
        ))
        idx += 1
    return out


_CALL_NAME_RE = re.compile(r"\b([A-Za-z_][A-Za-z_0-9]*)\s*\(")
_CALL_NAME_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
}


def _add_unique(names: list[str], name: str) -> None:
    if name not in names:
        names.append(name)


def _classify_assignment(span: StatementSpan) -> Optional[SpanAssignment]:
    simple = re.match(
        r"^\s*(?P<lhs>[A-Za-z_][A-Za-z_0-9]*)\s*=\s*(?P<rhs>.+);\s*$",
        span.text,
        re.DOTALL,
    )
    if simple is not None:
        lhs = simple.group("lhs")
        return SpanAssignment(
            statement=span,
            lhs_text=lhs,
            rhs_text=simple.group("rhs").strip(),
            lhs_kind="simple-local",
            name=lhs,
        )

    pointee = re.match(
        r"^\s*\*\s*(?P<lhs>[A-Za-z_][A-Za-z_0-9]*)\s*=\s*(?P<rhs>.+);\s*$",
        span.text,
        re.DOTALL,
    )
    if pointee is not None:
        lhs = pointee.group("lhs")
        return SpanAssignment(
            statement=span,
            lhs_text=f"*{lhs}",
            rhs_text=pointee.group("rhs").strip(),
            lhs_kind="pointee-store",
            name=lhs,
        )
    return None


def _rhs_reads_output(assignment: SpanAssignment) -> bool:
    return re.search(
        r"\b" + re.escape(assignment.name) + r"\b",
        assignment.rhs_text,
    ) is not None


def _local_write_plan(
    group: SpanGroup,
    call_names: set[str],
) -> SpanLocalWritePlan:
    assignments = tuple(
        assignment for assignment in (
            _classify_assignment(span) for span in group.spans
        )
        if assignment is not None
    )
    assignment_by_range = {
        assignment.statement.byte_range: assignment for assignment in assignments
    }

    simple_outputs: list[str] = []
    pointee_store_params: list[str] = []
    unknown_outputs: list[str] = []
    blockers: list[str] = []
    has_declaration = any(span.kind == "declaration" for span in group.spans)
    if has_declaration:
        blockers.append("span contains declaration")

    for assignment in assignments:
        if assignment.lhs_kind == "simple-local":
            _add_unique(simple_outputs, assignment.name)
        elif assignment.lhs_kind == "pointee-store":
            _add_unique(pointee_store_params, assignment.name)

    for span in group.spans:
        assignment = assignment_by_range.get(span.byte_range)
        if assignment is None and span.writes:
            for name in span.writes:
                _add_unique(unknown_outputs, name)
            blockers.append(f"unsupported assignment lhs: {span.text}")

    for name in tuple(unknown_outputs):
        if name in simple_outputs or name in pointee_store_params:
            unknown_outputs.remove(name)

    assigned: set[str] = set()
    input_names: list[str] = []
    read_before_write_outputs: list[str] = []
    macro_args: list[str] = []
    simple_output_set = set(simple_outputs)

    for span in group.spans:
        assignment = assignment_by_range.get(span.byte_range)
        if assignment is not None:
            _add_unique(macro_args, assignment.name)
            if (
                assignment.lhs_kind == "pointee-store"
                and assignment.name not in assigned
            ):
                _add_unique(input_names, assignment.name)

        for name in span.reads:
            if name in call_names:
                continue
            if name not in assigned:
                _add_unique(input_names, name)
                if name in simple_output_set:
                    _add_unique(read_before_write_outputs, name)
            _add_unique(macro_args, name)

        if (
            assignment is not None
            and assignment.lhs_kind == "simple-local"
            and _rhs_reads_output(assignment)
            and assignment.name not in assigned
        ):
            _add_unique(input_names, assignment.name)
            _add_unique(read_before_write_outputs, assignment.name)

        if assignment is not None and assignment.lhs_kind == "simple-local":
            assigned.add(assignment.name)

    return SpanLocalWritePlan(
        statements=group.spans,
        input_names=tuple(input_names),
        simple_outputs=tuple(simple_outputs),
        pointee_store_params=tuple(pointee_store_params),
        unknown_outputs=tuple(unknown_outputs),
        read_before_write_outputs=tuple(read_before_write_outputs),
        macro_args=tuple(
            name for name in macro_args
            if name not in call_names and name not in _CALL_NAME_KEYWORDS
        ),
        has_declaration=has_declaration,
        assignments=assignments,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _unsafe_out_param_type(type_name: str) -> bool:
    return (
        not type_name
        or "[" in type_name
        or "]" in type_name
        or "(*" in type_name
    )


def _unknown_output_types(
    plan: SpanLocalWritePlan,
    visible_types: dict[str, str],
) -> tuple[str, ...]:
    return tuple(
        name for name in plan.simple_outputs
        if _unsafe_out_param_type(visible_types.get(name, ""))
    )


def _scalar_return_blocker(
    plan: SpanLocalWritePlan,
    visible_types: dict[str, str],
) -> Optional[str]:
    if plan.has_declaration:
        return "span contains declaration"
    if plan.unknown_outputs:
        return f"unsupported output lhs: {', '.join(plan.unknown_outputs)}"
    simple_assignments = [
        assignment for assignment in plan.assignments
        if assignment.lhs_kind == "simple-local"
    ]
    if len(simple_assignments) != 1 or len(plan.assignments) != 1:
        return "requires exactly one simple local assignment"
    output = simple_assignments[0].name
    if output not in visible_types:
        return f"unknown output type for {output}"
    if _unsafe_out_param_type(visible_types[output]):
        return f"unsafe output type for {output}: {visible_types[output]}"
    return None


def _out_param_blocker(
    plan: SpanLocalWritePlan,
    visible_types: dict[str, str],
) -> Optional[str]:
    if plan.has_declaration:
        return "span contains declaration"
    if plan.unknown_outputs:
        return f"unsupported output lhs: {', '.join(plan.unknown_outputs)}"
    if not plan.simple_outputs:
        return "no caller-local outputs"
    if len(plan.assignments) == 1 and len(plan.simple_outputs) == 1:
        return "single assignment uses scalar-return-helper"
    unknown = _unknown_output_types(plan, visible_types)
    if unknown:
        return f"unknown or unsafe output type for {', '.join(unknown)}"
    return None


def _block_macro_blocker(plan: SpanLocalWritePlan) -> Optional[str]:
    if plan.has_declaration:
        return "span contains declaration"
    if plan.unknown_outputs:
        return f"unsupported output lhs: {', '.join(plan.unknown_outputs)}"
    text = "\n".join(span.text for span in plan.statements)
    if "/*" in text or "//" in text or "\\" in text or '"' in text or "'" in text:
        return "span contains comments, strings, or backslashes"
    return None


def _variant_blockers(
    plan: SpanLocalWritePlan,
    visible_types: dict[str, str],
) -> dict[str, str]:
    blockers: dict[str, str] = {}
    scalar = _scalar_return_blocker(plan, visible_types)
    if scalar is not None:
        blockers["scalar-return-helper"] = scalar
    out_param = _out_param_blocker(plan, visible_types)
    if out_param is not None:
        blockers["out-param-helper"] = out_param
    macro = _block_macro_blocker(plan)
    if macro is not None:
        blockers["block-macro"] = macro
    return blockers


def _local_write_metadata(
    plan: SpanLocalWritePlan,
    *,
    variant_rank: int,
    skipped_variant_blockers: Optional[dict[str, str]] = None,
    extra: Optional[dict[str, object]] = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "transform_family": "local-write-helper",
        "variant_rank": variant_rank,
        "outputs": plan.simple_outputs,
        "pointee_stores": plan.pointee_store_params,
        "input_names": plan.input_names,
        "output_count": len(plan.simple_outputs),
        "read_before_write_outputs": plan.read_before_write_outputs,
    }
    if plan.blockers:
        metadata["blockers"] = plan.blockers
    if skipped_variant_blockers:
        metadata["skipped_variant_blockers"] = tuple(
            f"{variant}: {reason}"
            for variant, reason in sorted(skipped_variant_blockers.items())
        )
    if extra:
        metadata.update(extra)
    return metadata


def _unique_helper_name(source: str, function: str, kind: str, idx: int) -> str:
    base = _helper_name(function, kind, idx)
    name = base
    suffix = 1
    while re.search(r"\b" + re.escape(name) + r"\b", source):
        suffix += 1
        name = f"{base}_{suffix}"
    return name


def _local_write_candidates_from_group(
    source: str,
    function: str,
    idx: int,
    group: SpanGroup,
    plan: SpanLocalWritePlan,
    *,
    visible_types: Optional[dict[str, str]] = None,
) -> list[InlineCandidate]:
    if visible_types is None:
        visible_types = _visible_type_map(source, function)
    blockers = _variant_blockers(plan, visible_types)
    out: list[InlineCandidate] = []

    if (
        not plan.has_declaration
        and not plan.simple_outputs
        and not plan.unknown_outputs
        and plan.pointee_store_params
    ):
        out.append(_candidate_from_group(
            function,
            idx,
            group,
            kind="void-helper",
            helper_name=_unique_helper_name(source, function, "void_helper", idx),
            reads=plan.input_names,
            writes=(),
            metadata=_local_write_metadata(
                plan,
                variant_rank=1,
                skipped_variant_blockers=blockers,
            ),
        ))
        return out

    scalar_blocker = blockers.get("scalar-return-helper")
    if scalar_blocker is None:
        assignment = next(
            assignment for assignment in plan.assignments
            if assignment.lhs_kind == "simple-local"
        )
        out.append(_candidate_from_group(
            function,
            idx,
            group,
            kind="scalar-return-helper",
            helper_name=_unique_helper_name(
                source, function, "scalar_return_helper", idx,
            ),
            reads=plan.input_names,
            writes=plan.simple_outputs,
            metadata=_local_write_metadata(
                plan,
                variant_rank=1,
                skipped_variant_blockers=blockers,
                extra={
                    "return_type": visible_types[assignment.name],
                    "rhs": assignment.rhs_text,
                    "lhs": assignment.name,
                },
            ),
        ))

    out_param_blocker = blockers.get("out-param-helper")
    if out_param_blocker is None:
        out.append(_candidate_from_group(
            function,
            idx,
            group,
            kind="out-param-helper",
            helper_name=_unique_helper_name(
                source, function, "out_param_helper", idx,
            ),
            reads=plan.input_names,
            writes=plan.simple_outputs,
            metadata=_local_write_metadata(
                plan,
                variant_rank=2,
                skipped_variant_blockers=blockers,
            ),
        ))

    macro_blocker = blockers.get("block-macro")
    if macro_blocker is None and plan.simple_outputs:
        out.append(_candidate_from_group(
            function,
            idx,
            group,
            kind="block-macro",
            helper_name=_unique_helper_name(source, function, "BLOCK_MACRO", idx),
            reads=plan.macro_args,
            writes=plan.simple_outputs,
            metadata=_local_write_metadata(
                plan,
                variant_rank=3,
                skipped_variant_blockers=blockers,
                extra={"macro_args": plan.macro_args},
            ),
        ))

    if out:
        return out

    reason_parts = [
        f"{variant}: {reason}" for variant, reason in sorted(blockers.items())
    ]
    reason = "local-write extraction unsupported"
    if reason_parts:
        reason += ": " + "; ".join(reason_parts)
    return [_candidate_from_group(
        function,
        idx,
        group,
        kind="void-helper",
        helper_name=_unique_helper_name(source, function, "void_helper", idx),
        reads=plan.input_names,
        writes=tuple(dict.fromkeys(
            name for span in group.spans for name in span.writes
        )),
        rejection_reason=reason,
        metadata=_local_write_metadata(
            plan,
            variant_rank=0,
            extra={"variant_blockers": tuple(reason_parts)},
        ),
    )]


def _candidates_from_group(
    source: str,
    function: str,
    idx: int,
    group: SpanGroup,
    *,
    visible_type_map: Optional[Callable[[], dict[str, str]]] = None,
) -> list[InlineCandidate]:
    rejection = reject_reason_for_span_group(list(group.spans))
    call_names = _call_names_for_spans(group.spans)
    if rejection is not None:
        return [_candidate_from_group(
            function,
            idx,
            group,
            rejection_reason=rejection,
        )]

    writes = tuple(dict.fromkeys(name for span in group.spans for name in span.writes))
    has_declaration = any(span.kind == "declaration" for span in group.spans)
    if not writes and not has_declaration:
        return [_candidate_from_group(function, idx, group)]

    plan = _local_write_plan(group, call_names)
    visible_types = visible_type_map() if visible_type_map is not None else None
    return _local_write_candidates_from_group(
        source,
        function,
        idx,
        group,
        plan,
        visible_types=visible_types,
    )


def _direct_call_names(source: str, function: str) -> tuple[str, ...]:
    names: list[str] = []
    for span in list_statement_spans(source, function):
        for match in _CALL_NAME_RE.finditer(span.text):
            name = match.group(1)
            if name in _CALL_NAME_KEYWORDS:
                continue
            if name not in names:
                names.append(name)
    return tuple(names)


def _hidden_dirty_arg_candidates_from_direct_helpers(
    source: str,
    function: str,
    start_idx: int,
) -> list[InlineCandidate]:
    out: list[InlineCandidate] = []
    idx = start_idx
    for helper_name in _direct_call_names(source, function):
        if helper_name == function:
            continue
        helper_candidates = _hidden_dirty_arg_candidates(
            source,
            helper_name,
            idx,
            report_function=function,
        )
        out.extend(helper_candidates)
        idx += len(helper_candidates)
    return out


def _hidden_dirty_group_candidates_from_direct_helpers(
    source: str,
    function: str,
    start_idx: int,
) -> list[InlineCandidate]:
    out: list[InlineCandidate] = []
    idx = start_idx
    for helper_name in _direct_call_names(source, function):
        if helper_name == function:
            continue
        helper_candidates = _hidden_dirty_group_candidates(
            source,
            helper_name,
            idx,
            report_function=function,
        )
        out.extend(helper_candidates)
        idx += len(helper_candidates)
    return out


def _local_type_map(source: str, function: str) -> dict[str, str]:
    return {decl.name: decl.type_str for decl in walk_function(source, function, path=None)}


def _normalize_type(type_str: str) -> str:
    type_str = re.sub(r"\s+", " ", type_str.strip())
    type_str = re.sub(r"\s*\*\s*", "*", type_str)
    return type_str


def _parameter_type_map(source: str, function: str) -> dict[str, str]:
    pattern = re.compile(
        r"\b" + re.escape(function) + r"\s*\((?P<params>[^)]*)\)\s*"
        r"(?:[A-Za-z_][A-Za-z_0-9]*\s*)*\{",
        re.DOTALL,
    )
    match = pattern.search(source)
    if match is None:
        return {}
    out: dict[str, str] = {}
    for param in match.group("params").split(","):
        param = param.strip()
        if not param or param == "void" or "..." in param:
            continue
        param = param.split("=", 1)[0].strip()
        m = re.match(
            r"(?P<type>.+?)(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
            r"(?:\s*\[[^\]]*\])?$",
            param,
            re.DOTALL,
        )
        if m is None:
            continue
        out[m.group("name")] = _normalize_type(m.group("type"))
    return out


def _visible_type_map(source: str, function: str) -> dict[str, str]:
    types = _parameter_type_map(source, function)
    types.update(_local_type_map(source, function))
    return types


def _return_helper_candidates(
    source: str,
    function: str,
    start_idx: int,
) -> list[InlineCandidate]:
    local_types = _local_type_map(source, function)
    out: list[InlineCandidate] = []
    idx = start_idx
    assign_re = re.compile(
        r"^\s*(?P<lhs>[A-Za-z_][A-Za-z_0-9]*)\s*=\s*(?P<rhs>.+);\s*$",
        re.DOTALL,
    )
    for span in list_statement_spans(source, function):
        m = assign_re.match(span.text)
        if m is None:
            continue
        lhs = m.group("lhs")
        rhs = m.group("rhs").strip()
        if lhs not in local_types:
            continue
        if "(" not in rhs or ")" not in rhs:
            continue
        reads = tuple(name for name in span.reads if name != lhs)
        anchor = SourceAnchor(
            function=function,
            scope_path=span.scope_path,
            byte_range=span.byte_range,
            line_range=span.line_range,
            kind="pattern",
            reason=f"single-output helper for {lhs}",
        )
        out.append(InlineCandidate(
            candidate_id=_candidate_id("return-helper", idx),
            kind="return-helper",
            anchor=anchor,
            helper_name=_helper_name(function, "return_helper", idx),
            reads=reads,
            writes=(lhs,),
            source_excerpt=span.text,
            metadata={
                "return_type": local_types[lhs],
                "rhs": rhs,
                "lhs": lhs,
            },
        ))
        idx += 1
    return out


def generate_candidates(
    *,
    source: str,
    function: str,
    seed_source: str = "all",
    max_span_statements: int = 6,
    budget: int = 8,
) -> list[InlineCandidate]:
    candidates: list[InlineCandidate] = []
    idx = 1
    repeated_visible_types: Optional[dict[str, str]] = None

    def get_repeated_visible_types() -> dict[str, str]:
        nonlocal repeated_visible_types
        if repeated_visible_types is None:
            repeated_visible_types = _visible_type_map(source, function)
        return repeated_visible_types

    if seed_source in {"all", "repeated"}:
        for group in find_repeated_call_groups(
            source, function, max_span_statements=max_span_statements,
        ):
            candidates.extend(_candidates_from_group(
                source,
                function,
                idx,
                group,
                visible_type_map=get_repeated_visible_types,
            ))
            idx += 1
    if seed_source in {"all", "patterns", "coalesce", "guide"}:
        for arg in find_call_argument_spans(source, function, "HSD_JObjSetMtxDirtySub"):
            if not arg.text:
                continue
            candidates.append(_candidate_from_arg(function, idx, arg))
            idx += 1
        for candidate in _hidden_dirty_arg_candidates(source, function, idx):
            candidates.append(candidate)
            idx += 1
        for candidate in _hidden_dirty_group_candidates(source, function, idx):
            candidates.append(candidate)
            idx += 1
        for candidate in _hidden_dirty_arg_candidates_from_direct_helpers(
            source, function, idx,
        ):
            candidates.append(candidate)
            idx += 1
        for candidate in _hidden_dirty_group_candidates_from_direct_helpers(
            source, function, idx,
        ):
            candidates.append(candidate)
            idx += 1
        for candidate in _return_helper_candidates(source, function, idx):
            candidates.append(candidate)
            idx += 1
    return candidates[:budget]


def _target_function_for_patch(function: str, candidate: InlineCandidate) -> str:
    if candidate.anchor.scope_path:
        return candidate.anchor.scope_path[0]
    helper_function = candidate.metadata.get("helper_function")
    if isinstance(helper_function, str):
        return helper_function
    return function


def _helper_insert_pos(source: str, target_function: str, fallback_function: str) -> int:
    span = find_source_function(source, target_function)
    if span is not None:
        return span.sig_start
    for name in (target_function, fallback_function):
        insert_pos = source.find(f"void {name}")
        if insert_pos >= 0:
            return insert_pos
    return 0


def _temp_type_for_arg(source: str, function: str, arg_text: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z_0-9]*$", arg_text):
        return "void*"
    return _visible_type_map(source, function).get(arg_text, "void*")


def _line_start(source: str, char_index: int) -> int:
    return source.rfind("\n", 0, char_index) + 1


def _line_indent_at(source: str, char_index: int) -> str:
    line_start = _line_start(source, char_index)
    indent_match = re.match(r"[ \t]*", source[line_start:char_index])
    return "" if indent_match is None else indent_match.group(0)


def _declaration_insert_pos_and_indent(
    source: str,
    function: str,
    scope_path: tuple[str, ...],
) -> tuple[int, str]:
    spans = [
        span for span in list_statement_spans(source, function)
        if span.scope_path == scope_path
    ]
    if not spans:
        fn_pos = source.find(function)
        brace_pos = source.find("{", fn_pos if fn_pos >= 0 else 0)
        if brace_pos >= 0:
            return brace_pos + 1, "    "
        return 0, ""

    first_non_decl = next(
        (span for span in spans if span.kind != "declaration"),
        None,
    )
    if first_non_decl is not None:
        stmt_char_start = _char_index_for_byte(
            source,
            first_non_decl.byte_range[0],
        )
        pos = _line_start(source, stmt_char_start)
        return pos, _line_indent_at(source, stmt_char_start)

    last = spans[-1]
    pos = _char_index_for_byte(source, last.byte_range[1])
    newline = source.find("\n", pos)
    if newline >= 0:
        pos = newline + 1
    return pos, _line_indent_at(
        source,
        _char_index_for_byte(source, last.byte_range[0]),
    )


def _patch_argument_temps(
    source: str,
    function: str,
    candidate: InlineCandidate,
    args: list[CallArgumentSpan],
) -> CandidatePatch:
    arg_text = candidate.reads[0]
    temp_name = f"{arg_text}_arg_temp"
    target_function = _target_function_for_patch(function, candidate)
    temp_type = _temp_type_for_arg(source, target_function, arg_text)

    modifications: list[tuple[int, int, str]] = []
    statement_insertions: dict[int, str] = {}
    for arg in args:
        call_start, call_end = _char_range_for_bytes(source, arg.byte_range)
        modifications.append((call_start, call_end, temp_name))
        stmt_char_start = _char_index_for_byte(
            source,
            arg.statement.byte_range[0],
        )
        stmt_start = _line_start(source, stmt_char_start)
        statement_insertions[stmt_start] = _line_indent_at(source, stmt_char_start)

    for stmt_start, indent in sorted(statement_insertions.items(), reverse=True):
        modifications.append((
            stmt_start,
            stmt_start,
            f"{indent}{temp_name} = {arg_text};\n",
        ))

    out = source
    for start, end, replacement in sorted(
        modifications, key=lambda item: (item[0], item[1]), reverse=True,
    ):
        out = out[:start] + replacement + out[end:]

    decl_pos, decl_indent = _declaration_insert_pos_and_indent(
        source,
        target_function,
        candidate.anchor.scope_path,
    )
    decl = f"{decl_indent}{temp_type} {temp_name};\n"
    out = out[:decl_pos] + decl + out[decl_pos:]
    return CandidatePatch(
        candidate_id=candidate.candidate_id,
        patched_source=out,
        summary=f"introduce short-lived temp {temp_name}",
        touched_ranges=tuple(arg.byte_range for arg in args),
        hunk=_patch_hunk(source, out, candidate.candidate_id),
    )


def _patch_arg_temp(source: str, candidate: InlineCandidate) -> CandidatePatch:
    target_function = _target_function_for_patch(candidate.anchor.function, candidate)
    matching_arg = None
    for call_name in (
        "HSD_JObjSetMtxDirtySub",
        *list(_TRANSLATE_CALLS),
    ):
        for arg in find_call_argument_spans(source, target_function, call_name):
            if arg.byte_range == candidate.anchor.byte_range:
                matching_arg = arg
                break
        if matching_arg is not None:
            break
    if matching_arg is None:
        return _patch_argument_temps(
            source,
            target_function,
            candidate,
            [CallArgumentSpan(
                function_name=target_function,
                call_name="",
                text=candidate.reads[0],
                byte_range=candidate.anchor.byte_range,
                line_range=candidate.anchor.line_range,
                scope_path=candidate.anchor.scope_path,
                statement=next(
                    span for span in list_statement_spans(source, target_function)
                    if span.byte_range[0] <= candidate.anchor.byte_range[0]
                    <= candidate.anchor.byte_range[1] <= span.byte_range[1]
                ),
            )],
        )
    return _patch_argument_temps(
        source,
        target_function,
        candidate,
        [matching_arg],
    )


def _patch_hidden_dirty_group(source: str, function: str, candidate: InlineCandidate) -> CandidatePatch:
    target_function = _target_function_for_patch(function, candidate)
    arg_text = candidate.metadata.get("arg_text", candidate.reads[0])
    args: list[CallArgumentSpan] = []
    for call_name in _TRANSLATE_CALLS:
        for arg in find_call_argument_spans(source, target_function, call_name):
            if (
                arg.scope_path == candidate.anchor.scope_path
                and arg.text == arg_text
                and _is_first_call_argument(source, arg)
            ):
                args.append(arg)
    args = sorted(args, key=lambda arg: arg.byte_range)
    return _patch_argument_temps(source, target_function, candidate, args)



def _helper_param_decls(
    source: str,
    function: str,
    candidate: InlineCandidate,
) -> tuple[str, ...]:
    visible_types = _visible_type_map(source, function)
    params: list[str] = []
    for name in candidate.reads:
        type_name = visible_types.get(name, "int")
        params.append(f"{type_name} {name}")
    return tuple(params)


def _patch_void_helper(source: str, function: str, candidate: InlineCandidate) -> CandidatePatch:
    target_function = _target_function_for_patch(function, candidate)
    params = _helper_param_decls(source, target_function, candidate)
    param_text = ", ".join(params) if params else "void"
    helper_lines = [
        f"static inline void {candidate.helper_name}({param_text})",
        "{",
    ]
    for line in candidate.source_excerpt.splitlines():
        helper_lines.append(f"    {line}")
    helper_lines.append("}")
    helper = "\n".join(helper_lines) + "\n\n"
    insert_pos = _helper_insert_pos(source, target_function, function)
    call_args = ", ".join(candidate.reads)
    call = f"{candidate.helper_name}({call_args});"
    start, end = _char_range_for_bytes(source, candidate.anchor.byte_range)
    out = source[:start] + call + source[end:]
    out = out[:insert_pos] + helper + out[insert_pos:]
    return CandidatePatch(
        candidate_id=candidate.candidate_id,
        patched_source=out,
        summary=f"extract {candidate.helper_name}",
        touched_ranges=(candidate.anchor.byte_range,),
        hunk=_patch_hunk(source, out, candidate.candidate_id),
    )


def _patch_return_helper(source: str, function: str, candidate: InlineCandidate) -> CandidatePatch:
    target_function = _target_function_for_patch(function, candidate)
    return_type = candidate.metadata["return_type"]
    rhs = candidate.metadata["rhs"]
    lhs = candidate.metadata["lhs"]
    params = _helper_param_decls(source, target_function, candidate)
    param_text = ", ".join(params) if params else "void"
    call_args = ", ".join(candidate.reads)
    helper = (
        f"static inline {return_type} {candidate.helper_name}({param_text})\n"
        "{\n"
        f"    return {rhs};\n"
        "}\n\n"
    )
    insert_pos = _helper_insert_pos(source, target_function, function)
    start, end = _char_range_for_bytes(source, candidate.anchor.byte_range)
    replacement = f"{lhs} = {candidate.helper_name}({call_args});"
    out = source[:start] + replacement + source[end:]
    out = out[:insert_pos] + helper + out[insert_pos:]
    return CandidatePatch(
        candidate_id=candidate.candidate_id,
        patched_source=out,
        summary=f"extract {candidate.helper_name}",
        touched_ranges=(candidate.anchor.byte_range,),
        hunk=_patch_hunk(source, out, candidate.candidate_id),
    )


def _metadata_tuple(candidate: InlineCandidate, key: str) -> tuple[str, ...]:
    value = candidate.metadata.get(key, ())
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    if isinstance(value, str):
        return (value,) if value else ()
    return ()


def _patch_out_param_helper(
    source: str,
    function: str,
    candidate: InlineCandidate,
) -> CandidatePatch:
    target_function = _target_function_for_patch(function, candidate)
    visible_types = _visible_type_map(source, target_function)
    outputs = _metadata_tuple(candidate, "outputs")
    read_before_write = set(_metadata_tuple(
        candidate, "read_before_write_outputs",
    ))

    params: list[str] = []
    for name in candidate.reads:
        type_name = visible_types.get(name, "int")
        param_name = f"{name}_in" if name in outputs else name
        params.append(f"{type_name} {param_name}")
    for name in outputs:
        type_name = visible_types.get(name, "int")
        params.append(f"{type_name}* {name}_out")

    helper_lines = [
        f"static inline void {candidate.helper_name}({', '.join(params)})",
        "{",
    ]
    for name in outputs:
        helper_lines.append(f"    {visible_types.get(name, 'int')} {name};")
    helper_lines.append("")
    for name in outputs:
        if name in read_before_write:
            helper_lines.append(f"    {name} = {name}_in;")
    if read_before_write:
        helper_lines.append("")
    for line in candidate.source_excerpt.splitlines():
        helper_lines.append(f"    {line}")
    helper_lines.append("")
    for name in outputs:
        helper_lines.append(f"    *{name}_out = {name};")
    helper_lines.append("}")
    helper = "\n".join(helper_lines) + "\n\n"

    insert_pos = _helper_insert_pos(source, target_function, function)
    call_args = [*candidate.reads, *(f"&{name}" for name in outputs)]
    call = f"{candidate.helper_name}({', '.join(call_args)});"
    start, end = _char_range_for_bytes(source, candidate.anchor.byte_range)
    out = source[:start] + call + source[end:]
    out = out[:insert_pos] + helper + out[insert_pos:]
    return CandidatePatch(
        candidate_id=candidate.candidate_id,
        patched_source=out,
        summary=f"extract {candidate.helper_name} with output params",
        touched_ranges=(candidate.anchor.byte_range,),
        hunk=_patch_hunk(source, out, candidate.candidate_id),
    )


def _patch_block_macro(
    source: str,
    function: str,
    candidate: InlineCandidate,
) -> CandidatePatch:
    target_function = _target_function_for_patch(function, candidate)
    macro_args = _metadata_tuple(candidate, "macro_args") or candidate.reads
    helper_lines = [
        f"#define {candidate.helper_name}({', '.join(macro_args)}) \\",
        "do { \\",
    ]
    for line in candidate.source_excerpt.splitlines():
        helper_lines.append(f"    {line} \\")
    helper_lines.append("} while (0)")
    helper = "\n".join(helper_lines) + "\n\n"

    insert_pos = _helper_insert_pos(source, target_function, function)
    call = f"{candidate.helper_name}({', '.join(macro_args)});"
    start, end = _char_range_for_bytes(source, candidate.anchor.byte_range)
    out = source[:start] + call + source[end:]
    out = out[:insert_pos] + helper + out[insert_pos:]
    return CandidatePatch(
        candidate_id=candidate.candidate_id,
        patched_source=out,
        summary=f"extract block macro {candidate.helper_name}",
        touched_ranges=(candidate.anchor.byte_range,),
        hunk=_patch_hunk(source, out, candidate.candidate_id),
    )


def _patch_hunk(source: str, patched_source: str, candidate_id: str) -> str:
    return "\n".join(difflib.unified_diff(
        source.splitlines(),
        patched_source.splitlines(),
        fromfile="before",
        tofile=candidate_id,
        lineterm="",
    ))


def generate_patches(
    source: str,
    function: str,
    candidates: list[InlineCandidate],
) -> list[CandidatePatch]:
    patches: list[CandidatePatch] = []
    for candidate in candidates:
        if candidate.is_rejected:
            continue
        patch = None
        if candidate.kind == "arg-temp":
            patch = _patch_arg_temp(source, candidate)
        elif candidate.kind == "hidden-dirty-arg-temp":
            patch = _patch_arg_temp(source, candidate)
        elif candidate.kind == "hidden-dirty-arg-temp-group":
            patch = _patch_hidden_dirty_group(source, function, candidate)
        elif candidate.kind == "void-helper":
            patch = _patch_void_helper(source, function, candidate)
        elif candidate.kind in {"return-helper", "scalar-return-helper"}:
            patch = _patch_return_helper(source, function, candidate)
        elif candidate.kind == "out-param-helper":
            patch = _patch_out_param_helper(source, function, candidate)
        elif candidate.kind == "block-macro":
            patch = _patch_block_macro(source, function, candidate)
        if patch is not None:
            patches.append(_attach_patch_metadata(source, candidate, patch))
    return patches


def _attach_patch_metadata(
    source: str,
    candidate: InlineCandidate,
    patch: CandidatePatch,
) -> CandidatePatch:
    metadata = dict(candidate.metadata)
    metadata.setdefault("kind", candidate.kind)
    metadata.setdefault("helper_name", candidate.helper_name)
    metadata.setdefault("strategy", candidate.kind)
    if metadata.get("transform_family") == "local-write-helper":
        metadata.setdefault("family", _INLINE_LOCAL_WRITE_FAMILY)
        metadata.setdefault("source_model_layer_dimension_id", _INLINE_LOCAL_WRITE_FAMILY)
        metadata.setdefault("dimension_id", f"{_INLINE_LOCAL_WRITE_FAMILY}-{candidate.kind}")
    metadata.setdefault("candidate_size", len(patch.patched_source.splitlines()))
    metadata.setdefault("helper_param_count", len(candidate.reads))
    metadata["source_hunks"] = [
        hunk.to_dict()
        for hunk in diff_line_hunks(
            source,
            patch.patched_source,
            hunk_prefix=f"{candidate.candidate_id}-h",
        )
    ]
    return replace(patch, metadata=metadata)


def run(
    *,
    source: str,
    function: str,
    pcdump_text: str,
    seed_source: str = "all",
    budget: int = 8,
    max_span_statements: int = 6,
    verify: bool = False,
    verifier=None,
) -> SourceShapeReport:
    candidates = generate_candidates(
        source=source,
        function=function,
        seed_source=seed_source,
        max_span_statements=max_span_statements,
        budget=budget,
    )
    patches = generate_patches(source, function, candidates)
    scores = []
    if verify and verifier is not None:
        scores = verifier(patches)
        scores = rank_scores(scores)
    messages = []
    if not candidates:
        messages.append("no source-shape candidates found")
    status = "ok"
    terminal_blocker = None
    terminal_blockers: list[dict[str, object]] = []
    if candidates and not patches and all(candidate.is_rejected for candidate in candidates):
        status = "terminal"
        terminal_blocker = _ALL_INLINE_HELPER_CANDIDATES_REJECTED
        by_reason: dict[str, list[str]] = defaultdict(list)
        for candidate in candidates:
            reason = candidate.rejection_reason or "candidate-rejected"
            by_reason[reason].append(candidate.candidate_id)
        terminal_blockers = [
            {
                "reason": reason,
                "count": len(candidate_ids),
                "candidate_ids": candidate_ids,
            }
            for reason, candidate_ids in sorted(by_reason.items())
        ]
        messages.append(
            "all inline/helper candidates were rejected; verification has no "
            "accepted patches to score"
        )
    return SourceShapeReport(
        function=function,
        candidates=candidates,
        patches=patches,
        scores=scores,
        messages=messages,
        status=status,
        terminal_blocker=terminal_blocker,
        terminal_blockers=terminal_blockers,
    )


def build_inline_local_write_terminal_summary(
    report: SourceShapeReport,
) -> dict[str, Any] | None:
    if report.score_mode != "score-source":
        return None
    local_write_patches = [
        patch for patch in report.patches
        if _patch_is_inline_local_write(patch)
    ]
    if not local_write_patches:
        return None
    score_rows = _score_rows_for_report(report)
    rows_by_id = {
        str(row.get("candidate_id")): row
        for row in score_rows
        if row.get("candidate_id") is not None
    }
    candidate_ids = [patch.candidate_id for patch in local_write_patches]
    if any(candidate_id not in rows_by_id for candidate_id in candidate_ids):
        return None
    rows = [dict(rows_by_id[candidate_id]) for candidate_id in candidate_ids]
    if any(not row.get("terminal_safe") for row in rows):
        return None
    has_target_or_expression = any(
        _score_row_has_target_or_expression_score(row) for row in rows
    )
    has_checkdiff_evidence = any(_score_row_has_checkdiff_evidence(row) for row in rows)
    if not has_target_or_expression and not has_checkdiff_evidence:
        return None
    if has_target_or_expression:
        if any(_score_row_exact_target_match(row) for row in rows):
            return None
        if any(_score_row_has_target_expression_progress(row) for row in rows):
            return None
    if any(_score_row_has_checkdiff_progress(row) for row in rows):
        return None

    best = _best_terminal_score_row(rows)
    target_anchors = _target_anchors_from_score_row(best)
    expression_anchors = _expression_anchors_from_score_row(best)
    final_force = {
        str(anchor["virtual"]): anchor["expected"]
        for anchor in target_anchors
        if anchor.get("virtual") is not None and anchor.get("expected") is not None
    }
    attempted = _attempted_dimensions_from_rows(rows)
    exhausted_dimensions = [
        {
            "dimension_id": dimension,
            "status": "terminal",
            "exhaustion_reason": _INLINE_LOCAL_WRITE_TERMINAL_REASON,
        }
        for dimension in attempted
    ]
    terminal_blockers = [
        {
            "reason": (
                "no-target-or-expression-improvement"
                if has_target_or_expression
                else "no-checkdiff-improvement"
            ),
            "count": len(rows),
            "candidate_ids": candidate_ids,
        }
    ]
    terminal_summary: dict[str, Any] = {
        "kind": "no-post-ceiling-source-family",
        "candidate_count": len(candidate_ids),
        "scored_count": len(rows),
        "best_candidate_id": best.get("candidate_id"),
        "best_target_matched": best.get("target_matched"),
        "best_target_targeted": best.get("target_targeted"),
        "best_target_virtual_distance": best.get("target_virtual_distance"),
        "best_expression_matched": best.get("expression_matched"),
        "best_expression_targeted": best.get("expression_targeted"),
        "best_expression_virtual_distance": best.get(
            "expression_virtual_distance"
        ),
        "best_checkdiff_match_percent": _score_row_checkdiff_pct(best),
        "best_checkdiff_delta": _score_row_checkdiff_delta(best),
        "best_classification_primary": _score_row_classification_primary(best),
        "best_normalized_diff_lines": _score_row_normalized_diff_lines(best),
        "terminal_blocker": "current-source-shape-ceiling",
        "terminal_reason": _INLINE_LOCAL_WRITE_TERMINAL_REASON,
        "target_anchors": target_anchors,
        "expression_anchors": expression_anchors,
        "final_force_phys": final_force,
        "attempted_targets": final_force,
    }
    source_family_synthesis = {
        "status": "synthesis-exhausted",
        "evidence_status": "artifact-score-rows",
        "attempted_equivalence_classes": attempted,
        "exhausted_dimensions": exhausted_dimensions,
        "scored_candidate_ids": candidate_ids,
        "all_candidate_ids": candidate_ids,
        "candidate_count": len(candidate_ids),
        "retained_scored_probes": rows,
        "source_hunks_by_candidate": {
            str(row.get("candidate_id")): row.get("source_hunks") or []
            for row in rows
        },
        "terminal_blockers": terminal_blockers,
        "terminal_blocker": "current-source-shape-ceiling",
        "terminal_reason": _INLINE_LOCAL_WRITE_TERMINAL_REASON,
        "next_unsupported_source_dimension": attempted[0] if attempted else None,
        "next_unsupported_source_family": _INLINE_LOCAL_WRITE_FAMILY,
        "next_unsupported_source_model": (
            "Inline local-write helper/macro source-shape family exhausted "
            "without target/expression progress or fresh checkdiff improvement. "
            "Next handoff: try a source-level rewrite outside this bounded "
            "inline-local-write helper/macro extraction family."
        ),
    }
    source_model_proof = {
        "kind": _INLINE_LOCAL_WRITE_TERMINAL_KIND,
        "status": "terminal",
        "terminal_reason": _INLINE_LOCAL_WRITE_TERMINAL_REASON,
        "terminal_blocker": "current-source-shape-ceiling",
        "terminal_blockers": terminal_blockers,
        "attempted_equivalence_classes": attempted,
        "exhausted_dimensions": exhausted_dimensions,
        "target_anchors": target_anchors,
        "expression_anchors": expression_anchors,
        "candidate_scores": rows,
        "retained_scored_probes": rows,
        "source_family_synthesis": source_family_synthesis,
        "next_unsupported_source_dimension": attempted[0] if attempted else None,
        "next_unsupported_source_family": _INLINE_LOCAL_WRITE_FAMILY,
        "next_unsupported_source_model": (
            "Inline local-write helper/macro source-shape family exhausted "
            "without target/expression progress or fresh checkdiff improvement. "
            "Next handoff: try a source-level rewrite outside this bounded "
            "inline-local-write helper/macro extraction family."
        ),
    }
    return {
        "function": report.function,
        "status": "terminal",
        "terminal": True,
        "kind": _INLINE_LOCAL_WRITE_TERMINAL_KIND,
        "terminal_reason": _INLINE_LOCAL_WRITE_TERMINAL_REASON,
        "family_id": "post-ceiling-source-model-proof",
        "terminal_blocker": "current-source-shape-ceiling",
        "terminal_blockers": terminal_blockers,
        "terminal_summary": terminal_summary,
        "score_rows": rows,
        "source_model_proof": source_model_proof,
    }


def _patch_is_inline_local_write(patch: CandidatePatch) -> bool:
    return (
        patch.metadata.get("family") == _INLINE_LOCAL_WRITE_FAMILY
        or patch.metadata.get("transform_family") == "local-write-helper"
    )


def _score_rows_for_report(report: SourceShapeReport) -> list[dict[str, Any]]:
    if report.score_rows:
        return [dict(row) for row in report.score_rows]
    rows: list[dict[str, Any]] = []
    for score in report.scores:
        row = asdict(score)
        rows.append(row)
    return rows


def _score_row_exact_target_match(row: Mapping[str, Any]) -> bool:
    matched = _int_or_none(row.get("target_matched"))
    targeted = _int_or_none(row.get("target_targeted"))
    return targeted is not None and targeted > 0 and matched == targeted


def _score_row_has_target_expression_progress(row: Mapping[str, Any]) -> bool:
    for key in (
        "target_delta_matched",
        "expression_delta_matched",
        "target_matched",
        "expression_matched",
    ):
        value = _int_or_none(row.get(key))
        if value is not None and value > 0:
            return True
    return False


def _score_row_has_target_or_expression_score(row: Mapping[str, Any]) -> bool:
    return isinstance(row.get("target_score"), Mapping) or isinstance(
        row.get("expression_score"),
        Mapping,
    )


def _score_row_has_checkdiff_evidence(row: Mapping[str, Any]) -> bool:
    return (
        _score_row_checkdiff_pct(row) is not None
        or isinstance(row.get("structural_guard"), Mapping)
    )


def _score_row_has_checkdiff_progress(row: Mapping[str, Any]) -> bool:
    delta = _score_row_checkdiff_delta(row)
    return delta is not None and delta > 0


def _score_row_checkdiff_pct(row: Mapping[str, Any]) -> float | None:
    for key in ("checkdiff_pct", "checkdiff_match_percent", "match_percent"):
        value = _float_or_none(row.get(key))
        if value is not None:
            return value
    return None


def _score_row_checkdiff_delta(row: Mapping[str, Any]) -> float | None:
    return _float_or_none(row.get("checkdiff_delta"))


def _score_row_classification_primary(row: Mapping[str, Any]) -> str | None:
    guard = row.get("structural_guard")
    if isinstance(guard, Mapping):
        value = guard.get("classification_primary")
        if value is not None:
            return str(value)
    return None


def _score_row_normalized_diff_lines(row: Mapping[str, Any]) -> int | None:
    guard = row.get("structural_guard")
    if not isinstance(guard, Mapping):
        return None
    return _int_or_none(guard.get("normalized_diff_lines"))


def _best_terminal_score_row(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def key(row: Mapping[str, Any]) -> tuple[int, int, float, int, int, int, str]:
        expr_distance = _int_or_none(row.get("expression_virtual_distance"))
        target_distance = _int_or_none(row.get("target_virtual_distance"))
        checkdiff_delta = _score_row_checkdiff_delta(row)
        normalized_diff = _score_row_normalized_diff_lines(row)
        return (
            -(_int_or_none(row.get("expression_matched")) or 0),
            -(_int_or_none(row.get("target_matched")) or 0),
            -(checkdiff_delta if checkdiff_delta is not None else -999999.0),
            normalized_diff if normalized_diff is not None else 999999,
            expr_distance if expr_distance is not None else 999999,
            target_distance if target_distance is not None else 999999,
            str(row.get("candidate_id") or ""),
        )

    return dict(sorted(rows, key=key)[0])


def _attempted_dimensions_from_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    values: list[str] = []
    for row in rows:
        for key in ("source_model_layer_dimension_id", "dimension_id"):
            value = row.get(key)
            if isinstance(value, str) and value and value not in values:
                values.append(value)
        if values:
            continue
        family = row.get("family")
        strategy = row.get("strategy")
        if isinstance(family, str) and family:
            value = family
            if isinstance(strategy, str) and strategy:
                value = f"{family}-{strategy}"
            if value not in values:
                values.append(value)
    return values or [_INLINE_LOCAL_WRITE_FAMILY]


def _target_anchors_from_score_row(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _anchors_from_score(row.get("target_score"))


def _expression_anchors_from_score_row(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _anchors_from_score(row.get("expression_score"))


def _anchors_from_score(score: Any) -> list[dict[str, Any]]:
    if not isinstance(score, Mapping):
        return []
    virtuals = score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return []
    anchors: list[dict[str, Any]] = []
    for virtual, payload in virtuals.items():
        if not isinstance(payload, Mapping):
            continue
        parsed_virtual = _int_or_none(virtual)
        anchors.append({
            "virtual": parsed_virtual,
            "baseline_virtual": _int_or_none(
                payload.get("baseline_virtual")
            ) or parsed_virtual,
            "name": payload.get("name") or f"ig{virtual}",
            "expression": payload.get("expression"),
            "expected": _register_num(payload.get("expected")),
            "actual": _register_num(payload.get("actual")),
            "matched": bool(payload.get("matched")),
        })
    return anchors


def _register_num(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = re.search(r"(\d+)$", value)
        if match is not None:
            return int(match.group(1))
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def render_text(report: SourceShapeReport) -> str:
    lines = [f"suggest-inlines — {report.function}", ""]
    if report.terminal_blocker:
        lines.append(f"terminal_blocker: {report.terminal_blocker}")
        for blocker in report.terminal_blockers:
            reason = blocker.get("reason")
            count = blocker.get("count")
            lines.append(f"  - {reason}: {count}")
        lines.append("")
    if report.messages:
        for message in report.messages:
            lines.append(message)
        lines.append("")
    lines.append(f"Candidates: {len(report.candidates)}")
    for candidate in report.candidates:
        status = "rejected" if candidate.is_rejected else "accepted"
        lines.append(f"- {candidate.candidate_id} [{candidate.kind}] {status}")
        lines.append(f"  reason: {candidate.anchor.reason}")
        lines.append(f"  scope: {'/'.join(candidate.anchor.scope_path)}")
        lines.append(f"  lines: {candidate.anchor.line_range[0]}-{candidate.anchor.line_range[1]}")
        if candidate.rejection_reason:
            lines.append(f"  rejection: {candidate.rejection_reason}")
        lines.append("  source:")
        for line in candidate.source_excerpt.splitlines():
            lines.append(f"    {line}")
    if report.scores:
        lines.append("")
        lines.append("Scores:")
        for score in report.scores:
            delta = score.checkdiff_delta
            delta_text = "n/a" if delta is None else f"{delta:+.3f}"
            baseline = score.checkdiff_baseline_pct
            candidate = score.checkdiff_pct
            if baseline is not None or candidate is not None:
                baseline_text = (
                    "n/a" if baseline is None else f"{baseline:.3f}"
                )
                candidate_text = (
                    "n/a" if candidate is None else f"{candidate:.3f}"
                )
                lines.append(
                    f"- {score.candidate_id}: status={score.status} "
                    f"compile={score.compile_ok} "
                    f"baseline={baseline_text} candidate={candidate_text} "
                    f"delta={delta_text}"
                )
            else:
                lines.append(
                    f"- {score.candidate_id}: status={score.status} "
                    f"compile={score.compile_ok} "
                    f"delta={delta_text}"
                )
            if score.score_reason:
                lines.append(f"  reason: {score.score_reason}")
            display_traces = score.copy_trace_highlights or score.copy_traces
            total_traces = score.copy_trace_total_count or len(display_traces)
            if total_traces:
                omitted_count = (
                    score.copy_trace_omitted_count
                    or max(0, total_traces - len(display_traces))
                )
                if omitted_count:
                    lines.append(
                        f"  copy traces: showing {len(display_traces)}/"
                        f"{total_traces} candidate-relevant traces "
                        f"({omitted_count} omitted)"
                    )
                else:
                    lines.append(
                        f"  copy traces: showing {len(display_traces)}/"
                        f"{total_traces} traces"
                    )
            for trace in display_traces:
                from_text = (
                    "?" if trace.from_virtual is None
                    else f"r{trace.from_virtual}"
                )
                to_text = (
                    "?" if trace.to_virtual is None
                    else f"r{trace.to_virtual}"
                )
                line = (
                    f"  copy {to_text}<-{from_text}: "
                    f"status={trace.status} cause={trace.likely_cause}"
                )
                if trace.interest_reasons:
                    line = (
                        f"  copy {to_text}<-{from_text} "
                        f"[{', '.join(trace.interest_reasons)}]: "
                        f"status={trace.status} cause={trace.likely_cause}"
                    )
                if trace.first_copy_block is not None:
                    line += f" block={trace.first_copy_block}"
                if trace.first_absent_pass:
                    line += f" first_absent={trace.first_absent_pass}"
                if trace.transform_category:
                    line += f" transform={trace.transform_category}"
                if trace.note:
                    line += f" note={trace.note}"
                lines.append(line)
    return "\n".join(lines)


def render_json(
    report: SourceShapeReport,
    *,
    emit_patches: bool = False,
    emit_hunks: bool = False,
) -> str:
    payload = asdict(report)
    if not emit_patches:
        payload["patches"] = [
            {
                "candidate_id": patch.candidate_id,
                "summary": patch.summary,
                "touched_ranges": patch.touched_ranges,
                **({"hunk": patch.hunk} if emit_hunks else {}),
            }
            for patch in report.patches
        ]
    return json.dumps(payload, indent=2, default=str)
