"""Candidate generation and rendering for `debug suggest-inlines`."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Optional

from .ast_walker import walk_function
from .source_shape import (
    CandidatePatch,
    InlineCandidate,
    SourceAnchor,
    SourceShapeReport,
    rank_scores,
)
from .source_spans import (
    CallArgumentSpan,
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


def _anchor_from_group(function: str, group: SpanGroup) -> SourceAnchor:
    return SourceAnchor(
        function=function,
        scope_path=group.scope_path,
        byte_range=group.byte_range,
        line_range=group.line_range,
        kind="repeated",
        reason=group.reason,
    )


def _candidate_from_group(function: str, idx: int, group: SpanGroup) -> InlineCandidate:
    rejection = reject_reason_for_span_group(list(group.spans))
    reads = tuple(dict.fromkeys(name for span in group.spans for name in span.reads))
    writes = tuple(dict.fromkeys(name for span in group.spans for name in span.writes))
    return InlineCandidate(
        candidate_id=_candidate_id("void-helper", idx),
        kind="void-helper",
        anchor=_anchor_from_group(function, group),
        helper_name=_helper_name(function, "void_helper", idx),
        reads=reads,
        writes=writes,
        source_excerpt="\n".join(span.text for span in group.spans),
        rejection_reason=rejection,
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
    for call_name in (
        "HSD_JObjSetTranslateX",
        "HSD_JObjSetTranslateY",
        "HSD_JObjSetTranslateZ",
    ):
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


_CALL_NAME_RE = re.compile(r"\b([A-Za-z_][A-Za-z_0-9]*)\s*\(")
_CALL_NAME_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
}


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


def _local_type_map(source: str, function: str) -> dict[str, str]:
    return {decl.name: decl.type_str for decl in walk_function(source, function, path=None)}


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
    if seed_source in {"all", "repeated"}:
        for group in find_repeated_call_groups(
            source, function, max_span_statements=max_span_statements,
        ):
            candidates.append(_candidate_from_group(function, idx, group))
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
        for candidate in _hidden_dirty_arg_candidates_from_direct_helpers(
            source, function, idx,
        ):
            candidates.append(candidate)
            idx += 1
        for candidate in _return_helper_candidates(source, function, idx):
            candidates.append(candidate)
            idx += 1
    return candidates[:budget]


def _patch_arg_temp(source: str, candidate: InlineCandidate) -> CandidatePatch:
    arg_text = candidate.reads[0]
    temp_name = f"{arg_text}_arg_temp"
    call_start, call_end = _char_range_for_bytes(source, candidate.anchor.byte_range)
    statement_start = source.rfind("\n", 0, call_start) + 1
    line_prefix = source[statement_start:call_start]
    indent_match = re.match(r"[ \t]*", line_prefix)
    indent = "" if indent_match is None else indent_match.group(0)
    decl = f"{indent}void* {temp_name};\n"
    assign = f"{indent}{temp_name} = {arg_text};\n"
    patched_arg = temp_name
    out = source[:call_start] + patched_arg + source[call_end:]
    out = out[:statement_start] + decl + assign + out[statement_start:]
    return CandidatePatch(
        candidate_id=candidate.candidate_id,
        patched_source=out,
        summary=f"introduce short-lived temp {temp_name}",
        touched_ranges=(candidate.anchor.byte_range,),
    )


def _patch_void_helper(source: str, function: str, candidate: InlineCandidate) -> CandidatePatch:
    helper_lines = [
        f"static inline void {candidate.helper_name}(void)",
        "{",
    ]
    for line in candidate.source_excerpt.splitlines():
        helper_lines.append(f"    {line}")
    helper_lines.append("}")
    helper = "\n".join(helper_lines) + "\n\n"
    insert_pos = source.find(f"void {function}")
    if insert_pos < 0:
        insert_pos = 0
    call = f"{candidate.helper_name}();"
    start, end = _char_range_for_bytes(source, candidate.anchor.byte_range)
    out = source[:start] + call + source[end:]
    out = out[:insert_pos] + helper + out[insert_pos:]
    return CandidatePatch(
        candidate_id=candidate.candidate_id,
        patched_source=out,
        summary=f"extract {candidate.helper_name}",
        touched_ranges=(candidate.anchor.byte_range,),
    )


def _patch_return_helper(source: str, function: str, candidate: InlineCandidate) -> CandidatePatch:
    return_type = candidate.metadata["return_type"]
    rhs = candidate.metadata["rhs"]
    lhs = candidate.metadata["lhs"]
    helper = (
        f"static inline {return_type} {candidate.helper_name}(void)\n"
        "{\n"
        f"    return {rhs};\n"
        "}\n\n"
    )
    insert_pos = source.find(f"void {function}")
    if insert_pos < 0:
        insert_pos = 0
    start, end = _char_range_for_bytes(source, candidate.anchor.byte_range)
    replacement = f"{lhs} = {candidate.helper_name}();"
    out = source[:start] + replacement + source[end:]
    out = out[:insert_pos] + helper + out[insert_pos:]
    return CandidatePatch(
        candidate_id=candidate.candidate_id,
        patched_source=out,
        summary=f"extract {candidate.helper_name}",
        touched_ranges=(candidate.anchor.byte_range,),
    )


def generate_patches(
    source: str,
    function: str,
    candidates: list[InlineCandidate],
) -> list[CandidatePatch]:
    patches: list[CandidatePatch] = []
    for candidate in candidates:
        if candidate.is_rejected:
            continue
        if candidate.kind == "arg-temp":
            patches.append(_patch_arg_temp(source, candidate))
        elif candidate.kind == "hidden-dirty-arg-temp":
            patches.append(_patch_arg_temp(source, candidate))
        elif candidate.kind == "void-helper":
            patches.append(_patch_void_helper(source, function, candidate))
        elif candidate.kind == "return-helper":
            patches.append(_patch_return_helper(source, function, candidate))
    return patches


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
    return SourceShapeReport(
        function=function,
        candidates=candidates,
        patches=patches,
        scores=scores,
        messages=messages,
    )


def render_text(report: SourceShapeReport) -> str:
    lines = [f"suggest-inlines — {report.function}", ""]
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
            lines.append(f"- {score.candidate_id}: compile={score.compile_ok} delta={delta_text}")
    return "\n".join(lines)


def render_json(report: SourceShapeReport, *, emit_patches: bool = False) -> str:
    payload = asdict(report)
    if not emit_patches:
        payload["patches"] = [
            {
                "candidate_id": patch.candidate_id,
                "summary": patch.summary,
                "touched_ranges": patch.touched_ranges,
            }
            for patch in report.patches
        ]
    return json.dumps(payload, indent=2, default=str)
