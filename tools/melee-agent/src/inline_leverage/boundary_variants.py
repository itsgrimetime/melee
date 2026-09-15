from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
import re
from typing import Any

from .deinline import (
    _terminal_return_local,
    build_deinline_patch,
)
from .detect import (
    _find_matching,
    _signature_start,
    find_call_sites,
    parse_inline_defs,
)
from .types import CallSite, InlineDef
from src.mwcc_debug.source_hunks import diff_line_hunks

FAMILY_ID = "inline-leverage-helper-boundary-continuation"
TERMINAL_KIND = "inline-leverage-helper-boundary-exhausted"
TERMINAL_REASON = "inline-leverage-helper-boundary-exhausted/no-ig34-ig44-progress"

DIMENSIONS: tuple[str, ...] = (
    "signature",
    "local_declarations",
    "loop_init",
    "call_argument",
    "return_local_materialization",
    "scalar_assignment_splice_boundary",
)
VOID_DIMENSIONS: tuple[str, ...] = (
    "void_statement_splice_boundary",
    "void_value_argument_temp",
    "void_direct_helper_call",
)

DEFAULT_SORT_TARGETS: dict[str, int] = {"34": 27, "44": 25}
_SCORE_ID_KEYS = ("candidate_id", "id", "probe_id")
_SCORE_PATH_KEYS = (
    "score_json",
    "pcdump_path",
    "source_path",
    "source_file",
    "path",
    "candidate_path",
)
_KNOWN_SCORE_SUFFIXES = (
    ".checkdiff.json",
    "_checkdiff.json",
    ".score.json",
    "_score.json",
    ".pcdump.txt",
    ".pcdump",
    ".json",
    ".txt",
    ".score",
    "_score",
    ".c",
)
_HEX_TOKEN_RE = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{16,64})(?![0-9A-Fa-f])")

_IDENT = r"[A-Za-z_][A-Za-z_0-9]*"
_SORT_FUNCTIONS = {"mnDiagram_SortNamesByKOs", "mnDiagram_8023FC28"}
_FUNCTION_ALIASES = {
    "mnDiagram_SortNamesByKOs": ("mnDiagram_8023FC28",),
    "mnDiagram_8023FC28": ("mnDiagram_SortNamesByKOs",),
}
_SCALAR_STRICT_RECORD_FIELDS = {
    "verdict": "lever",
    "expansion_form": "scalar_assignment_splice",
    "shape_return": "scalar",
    "shape_body": "multi_statement",
}
_VOID_STRICT_RECORD_FIELDS = {
    "verdict": "lever",
    "expansion_form": "statement_splice",
    "shape_return": "void",
    "shape_body": "multi_statement",
}


@dataclass(frozen=True)
class _InlineOccurrence:
    name: str
    signature_start: int
    brace_index: int
    close_index: int

    @property
    def body_start(self) -> int:
        return self.brace_index + 1

    @property
    def body_end(self) -> int:
        return self.close_index


class _DimensionBlocked(ValueError):
    pass


def default_sort_target_map() -> dict[str, int]:
    return dict(DEFAULT_SORT_TARGETS)


def default_target_map(function: str | None = None) -> dict[str, int]:
    if function is None or function in _SORT_FUNCTIONS:
        return default_sort_target_map()
    return {}


def parse_target_map(
    raw: Mapping[str, Any] | str | None = None,
    *,
    function: str | None = None,
) -> dict[str, int]:
    if raw is None:
        return default_target_map(function)
    if isinstance(raw, Mapping):
        return _normalize_target_mapping(raw)

    text = str(raw).strip()
    if not text:
        return default_target_map(function)
    if text.startswith("{"):
        parsed = json.loads(text)
        if not isinstance(parsed, Mapping):
            raise ValueError("target map JSON must be an object")
        return _normalize_target_mapping(parsed)

    out: dict[str, int] = {}
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        match = re.fullmatch(r"(?P<ig>\d+)\s*[:=]\s*r?(?P<reg>\d+)", item)
        if match is None:
            raise ValueError(f"malformed target map entry: {item!r}")
        out[match.group("ig")] = int(match.group("reg"))
    return out


def inline_boundary_candidate_file_stem(candidate: Mapping[str, Any]) -> str:
    candidate_id = str(candidate.get("candidate_id") or "candidate")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate_id)
    return f"{_candidate_order_value(candidate):02d}_{safe_name}"


def generate_boundary_candidates(
    source_text: str,
    record: Mapping[str, Any],
    function: str,
    *,
    target_map: Mapping[str, Any] | str | None = None,
    max_candidates: int | None = None,
) -> dict[str, Any]:
    targets = parse_target_map(target_map, function=function)
    diagnostics: list[dict[str, Any]] = []

    strict_problem = _strict_record_problem(record)
    inline_name = str(record.get("inline_name") or "")
    if strict_problem is not None:
        return _blocked_result(
            function=function,
            inline_name=inline_name,
            targets=targets,
            reason=strict_problem,
        )
    if not inline_name:
        return _blocked_result(
            function=function,
            inline_name="",
            targets=targets,
            reason="strict inline-leverage record is missing inline_name",
            dimensions=_record_dimensions(record),
        )

    resolved_inline = _resolve_inline(source_text, inline_name)
    if isinstance(resolved_inline, str):
        return _blocked_result(
            function=function,
            inline_name=inline_name,
            targets=targets,
            reason=resolved_inline,
            dimensions=_record_dimensions(record),
        )
    inline_def, occurrence = resolved_inline

    resolved_call = _resolve_call_site(source_text, function, inline_name)
    if isinstance(resolved_call, str):
        return _blocked_result(
            function=function,
            inline_name=inline_name,
            targets=targets,
            reason=resolved_call,
            dimensions=_record_dimensions(record),
        )
    source_function, call_site = resolved_call

    context = {
        "inline_def": inline_def,
        "occurrence": occurrence,
        "call_site": call_site,
        "source_function": source_function,
    }
    dimensions = _record_dimensions(record)
    builders = _record_builders(record)

    candidates: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    limit = len(dimensions) if max_candidates is None else max(0, max_candidates)
    for dimension in dimensions:
        if len(candidates) >= limit:
            break
        try:
            variant, candidate_source = builders[dimension](source_text, context)
        except _DimensionBlocked as exc:
            diagnostics.append(_blocked_diagnostic(
                dimension,
                str(exc),
                function=function,
                inline_name=inline_name,
            ))
            continue
        if candidate_source == source_text:
            diagnostics.append(_blocked_diagnostic(
                dimension,
                "candidate source was unchanged",
                function=function,
                inline_name=inline_name,
            ))
            continue
        if candidate_source in seen_sources:
            diagnostics.append(_blocked_diagnostic(
                dimension,
                "candidate source duplicated an earlier dimension",
                function=function,
                inline_name=inline_name,
            ))
            continue
        seen_sources.add(candidate_source)
        candidates.append(_candidate_dict(
            base_source_text=source_text,
            source_text=candidate_source,
            function=function,
            source_function=source_function,
            inline_name=inline_name,
            expansion_form=str(record.get("expansion_form") or ""),
            dimension=dimension,
            variant=variant,
            order=len(candidates),
            target_map=targets,
        ))

    return {
        "status": "ok" if candidates else "blocked",
        "family_id": FAMILY_ID,
        "function": function,
        "source_function": source_function,
        "inline_name": inline_name,
        "expansion_form": record.get("expansion_form"),
        "target_map": dict(targets),
        "dimensions": list(dimensions),
        "candidates": candidates,
        "blocked_diagnostics": diagnostics,
    }


def generate_helper_boundary_candidates(
    source_text: str,
    record: Mapping[str, Any],
    function: str,
    *,
    target_map: Mapping[str, Any] | str | None = None,
    max_candidates: int | None = None,
) -> dict[str, Any]:
    return generate_boundary_candidates(
        source_text,
        record,
        function,
        target_map=target_map,
        max_candidates=max_candidates,
    )


def candidate_dicts(
    source_text: str,
    record: Mapping[str, Any],
    function: str,
    *,
    target_map: Mapping[str, Any] | str | None = None,
    max_candidates: int | None = None,
) -> list[dict[str, Any]]:
    return list(
        generate_boundary_candidates(
            source_text,
            record,
            function,
            target_map=target_map,
            max_candidates=max_candidates,
        )["candidates"]
    )


def rank_score_payloads(
    score_payloads: Sequence[Mapping[str, Any]],
    *,
    target_map: Mapping[str, Any] | str | None = None,
    candidates: Sequence[Mapping[str, Any]] | None = None,
    candidate_order: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    targets = parse_target_map(target_map)
    order_by_id = _candidate_order_map(candidates, candidate_order)
    rows = correlate_score_payloads(
        score_payloads,
        candidates=candidates,
        candidate_order=candidate_order,
    )
    rows.sort(key=lambda row: _score_rank_key(row, targets, order_by_id))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        row["rank_score"] = _rank_score_summary(row, targets, order_by_id)
    return rows


def correlate_score_payloads(
    score_payloads: Sequence[Mapping[str, Any]],
    *,
    candidates: Sequence[Mapping[str, Any]] | None = None,
    candidate_order: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in score_payloads]
    if not candidates:
        return rows

    index = _candidate_match_index(candidates, candidate_order)
    correlated: list[dict[str, Any]] = []
    for row in rows:
        match, diagnostic = _match_score_candidate(row, index)
        out = dict(row)
        if match is not None:
            canonical_id = str(match.get("candidate_id") or "")
            original_id = out.get("candidate_id")
            if original_id is not None and str(original_id) != canonical_id:
                out.setdefault("score_candidate_id", str(original_id))
            if canonical_id:
                out["candidate_id"] = canonical_id
            if match.get("candidate_order") is not None:
                out["candidate_order"] = _candidate_order_value(match)
            dimension = match.get("dimension_id") or match.get("dimension")
            if dimension is not None:
                out.setdefault("candidate_dimension", str(dimension))
            variant = match.get("variant")
            if variant is not None:
                out.setdefault("candidate_variant", str(variant))
        if diagnostic is not None:
            out["candidate_correlation"] = diagnostic
        correlated.append(out)
    return correlated


def build_terminal_proof(
    *,
    function: str,
    record: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    score_payloads: Sequence[Mapping[str, Any]],
    target_map: Mapping[str, Any] | str | None = None,
) -> dict[str, Any] | None:
    targets = parse_target_map(target_map, function=function)
    candidate_ids = [
        str(candidate.get("candidate_id") or "")
        for candidate in candidates
        if candidate.get("candidate_id")
    ]
    if not candidate_ids:
        return None

    correlated_scores = correlate_score_payloads(
        score_payloads,
        candidates=candidates,
    )
    candidate_id_set = set(candidate_ids)
    scores_by_id: dict[str, Mapping[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for row in correlated_scores:
        candidate_id = str(row.get("candidate_id") or "")
        if candidate_id not in candidate_id_set:
            continue
        if candidate_id in scores_by_id:
            duplicate_ids.add(candidate_id)
            continue
        scores_by_id[candidate_id] = row
    if duplicate_ids:
        return None
    if any(candidate_id not in scores_by_id for candidate_id in candidate_ids):
        return None
    if any(
        not _has_exhaustion_evidence(scores_by_id[candidate_id])
        for candidate_id in candidate_ids
    ):
        return None
    if any(
        _target_or_expression_score_improved(scores_by_id[candidate_id], targets)
        for candidate_id in candidate_ids
    ):
        return None

    ranked = rank_score_payloads(
        [scores_by_id[candidate_id] for candidate_id in candidate_ids],
        target_map=targets,
        candidates=candidates,
    )
    dimensions = _dimension_exhaustion_rows(
        candidates,
        scores_by_id,
        targets,
        dimensions=_candidate_dimensions(candidates),
    )
    inline_name = str(record.get("inline_name") or "")
    expansion_form = str(record.get("expansion_form") or "")
    compact_force = json.dumps(targets, sort_keys=True, separators=(",", ":"))
    terminal_reason = _terminal_reason_for_targets(targets)
    return {
        "function": function,
        "frontier_id": (
            f"{function}|{FAMILY_ID}|inline=\"{inline_name}\"|"
            f"expansion=\"{expansion_form}\"|force={compact_force}"
        ),
        "family_id": FAMILY_ID,
        "kind": TERMINAL_KIND,
        "status": "terminal",
        "terminal": True,
        "terminal_reason": terminal_reason,
        "attempted_targets": dict(targets),
        "protected_targets": {},
        "final_force_phys": dict(targets),
        "inline_name": inline_name,
        "expansion_form": expansion_form,
        "exhausted_dimensions": dimensions,
        "candidate_count": len(candidate_ids),
        "scored_count": len(candidate_ids),
        "ranked_candidates": [
            _score_row_summary(row, targets)
            for row in ranked
        ],
    }


def terminal_proof(
    candidates: Sequence[Mapping[str, Any]],
    score_payloads: Sequence[Mapping[str, Any]],
    *,
    function: str,
    record: Mapping[str, Any],
    target_map: Mapping[str, Any] | str | None = None,
) -> dict[str, Any] | None:
    return build_terminal_proof(
        function=function,
        record=record,
        candidates=candidates,
        score_payloads=score_payloads,
        target_map=target_map,
    )


build_terminal_frontier = build_terminal_proof


def _normalize_target_mapping(raw: Mapping[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, value in raw.items():
        text = str(value)
        if text.startswith("r") and text[1:].isdigit():
            text = text[1:]
        out[str(key)] = int(text)
    return out


def _strict_record_problem(record: Mapping[str, Any]) -> str | None:
    if _record_matches_fields(record, _SCALAR_STRICT_RECORD_FIELDS):
        return None
    if _record_matches_fields(record, _VOID_STRICT_RECORD_FIELDS):
        return None
    if record.get("verdict") != "lever":
        return f"inline-leverage record is not a structural lever: {record.get('verdict')!r}"
    return (
        "inline-leverage record is not a supported helper-boundary shape: "
        f"expansion_form={record.get('expansion_form')!r}, "
        f"shape_return={record.get('shape_return')!r}, "
        f"shape_body={record.get('shape_body')!r}"
    )


def _record_matches_fields(
    record: Mapping[str, Any],
    fields: Mapping[str, str],
) -> bool:
    return all(record.get(key) == expected for key, expected in fields.items())


def _record_dimensions(record: Mapping[str, Any]) -> tuple[str, ...]:
    if _record_matches_fields(record, _VOID_STRICT_RECORD_FIELDS):
        return VOID_DIMENSIONS
    return DIMENSIONS


def _record_builders(record: Mapping[str, Any]) -> dict[str, Any]:
    if _record_matches_fields(record, _VOID_STRICT_RECORD_FIELDS):
        return {
            "void_statement_splice_boundary": _void_statement_splice_variant,
            "void_value_argument_temp": _void_value_argument_temp_variant,
            "void_direct_helper_call": _void_direct_helper_call_variant,
        }
    return {
        "signature": _signature_variant,
        "local_declarations": _local_declarations_variant,
        "loop_init": _loop_init_variant,
        "call_argument": _call_argument_variant,
        "return_local_materialization": _return_local_materialization_variant,
        "scalar_assignment_splice_boundary": _scalar_assignment_splice_variant,
    }


def _blocked_result(
    *,
    function: str,
    inline_name: str,
    targets: Mapping[str, int],
    reason: str,
    dimensions: Sequence[str] = DIMENSIONS,
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "family_id": FAMILY_ID,
        "function": function,
        "inline_name": inline_name,
        "target_map": dict(targets),
        "dimensions": list(dimensions),
        "candidates": [],
        "blocked_diagnostics": [
            _blocked_diagnostic(
                dimension,
                reason,
                function=function,
                inline_name=inline_name,
            )
            for dimension in dimensions
        ],
    }


def _blocked_diagnostic(
    dimension: str,
    reason: str,
    *,
    function: str,
    inline_name: str,
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "family_id": FAMILY_ID,
        "dimension_id": dimension,
        "function": function,
        "inline_name": inline_name,
        "reason": reason,
    }


def _inline_occurrences(source_text: str) -> list[_InlineOccurrence]:
    occurrences: list[_InlineOccurrence] = []
    for match in re.finditer(r"\binline\b", source_text):
        brace = source_text.find("{", match.end())
        if brace < 0:
            continue
        sig_start = _signature_start(source_text, match.start())
        signature = source_text[sig_start:brace].strip()
        if ";" in signature:
            continue
        sig_flat = " ".join(signature.split())
        fn_match = re.search(
            rf"(?P<name>{_IDENT})\s*\((?P<params>.*)\)\s*$",
            sig_flat,
        )
        if fn_match is None:
            continue
        close = _find_matching(source_text, brace, "{", "}")
        if close < 0:
            continue
        occurrences.append(_InlineOccurrence(
            name=fn_match.group("name"),
            signature_start=sig_start,
            brace_index=brace,
            close_index=close,
        ))
    return occurrences


def _resolve_inline(
    source_text: str,
    inline_name: str,
) -> tuple[InlineDef, _InlineOccurrence] | str:
    defs = [
        item for item in parse_inline_defs(source_text, "<source>")
        if item.name == inline_name
    ]
    spans = [
        item for item in _inline_occurrences(source_text)
        if item.name == inline_name
    ]
    if not defs or not spans:
        return f"missing inline definition for {inline_name}"
    if len(defs) != 1 or len(spans) != 1:
        return f"ambiguous inline definition for {inline_name}"
    inline_def = defs[0]
    if (
        inline_def.return_class not in {"scalar", "void"}
        or inline_def.body_kind != "multi_statement"
    ):
        return "inline definition is not scalar/void multi-statement"
    return inline_def, spans[0]


def _resolve_call_site(
    source_text: str,
    function: str,
    inline_name: str,
) -> tuple[str, CallSite] | str:
    function_names = [function]
    function_names.extend(
        alias for alias in _FUNCTION_ALIASES.get(function, ())
        if alias not in function_names
    )
    matches: list[tuple[str, list[CallSite]]] = []
    for candidate_function in function_names:
        calls = find_call_sites(source_text, candidate_function, inline_name)
        if calls:
            matches.append((candidate_function, calls))
    if not matches:
        return f"missing call site for {inline_name} in {function}"
    if len(matches) != 1 or len(matches[0][1]) != 1:
        return f"ambiguous call site for {inline_name} in {function}"
    return matches[0][0], matches[0][1][0]


def _signature_variant(
    source_text: str,
    context: Mapping[str, Any],
) -> tuple[str, str]:
    inline_def: InlineDef = context["inline_def"]
    occurrence: _InlineOccurrence = context["occurrence"]
    if len(inline_def.params) != 1 or not inline_def.params[0][1]:
        raise _DimensionBlocked("signature variant requires one named parameter")
    type_text, param_name = inline_def.params[0]
    replacement_type = "int" if type_text.strip() != "int" else "u8"
    signature = source_text[occurrence.signature_start:occurrence.brace_index]
    pattern = rf"(?<![A-Za-z_0-9]){re.escape(type_text)}\s+{re.escape(param_name)}\b"
    replacement = f"{replacement_type} {param_name}"
    new_signature, count = re.subn(pattern, replacement, signature, count=1)
    if count != 1:
        raise _DimensionBlocked("could not rewrite inline signature parameter")
    return (
        f"param_type_{replacement_type}",
        _replace_span(
            source_text,
            occurrence.signature_start,
            occurrence.brace_index,
            new_signature,
        ),
    )


def _local_declarations_variant(
    source_text: str,
    context: Mapping[str, Any],
) -> tuple[str, str]:
    occurrence: _InlineOccurrence = context["occurrence"]
    body = source_text[occurrence.body_start:occurrence.body_end]
    declarations = _declaration_line_matches(body)
    if len(declarations) < 2:
        raise _DimensionBlocked("local declaration variant requires two declarations")
    first = declarations[0]
    second = declarations[1]
    replacement = f"{second.group(0)}\n{first.group(0)}"
    start = occurrence.body_start + first.start()
    end = occurrence.body_start + second.end()
    return (
        "swap_first_two_declarations",
        _replace_span(source_text, start, end, replacement),
    )


def _loop_init_variant(
    source_text: str,
    context: Mapping[str, Any],
) -> tuple[str, str]:
    inline_def: InlineDef = context["inline_def"]
    occurrence: _InlineOccurrence = context["occurrence"]
    return_local, error = _terminal_return_local(inline_def.body_text)
    if return_local is None:
        raise _DimensionBlocked(error or "could not identify return local")
    body = source_text[occurrence.body_start:occurrence.body_end]
    match = re.search(
        rf"for\s*\(\s*(?P<counter>{_IDENT})\s*=\s*{re.escape(return_local)}\s*;",
        body,
    )
    if match is None:
        raise _DimensionBlocked("could not find loop initialized from return local")
    replacement = f"for ({match.group('counter')} = 0;"
    start = occurrence.body_start + match.start()
    end = occurrence.body_start + match.end()
    return (
        "zero_literal_loop_init",
        _replace_span(source_text, start, end, replacement),
    )


def _call_argument_variant(
    source_text: str,
    context: Mapping[str, Any],
) -> tuple[str, str]:
    inline_def: InlineDef = context["inline_def"]
    call_site: CallSite = context["call_site"]
    if len(inline_def.params) != 1 or len(call_site.args) != 1:
        raise _DimensionBlocked("call argument variant requires one argument")
    new_arg = _materialized_u8_arg(call_site.args[0])
    call_text = source_text[call_site.byte_start:call_site.byte_end]
    new_call = re.sub(
        rf"\b{re.escape(inline_def.name)}\s*\(.*\)\s*$",
        f"{inline_def.name}({new_arg})",
        call_text,
        count=1,
    )
    if new_call == call_text:
        raise _DimensionBlocked("could not rewrite call argument")
    return (
        "cast_to_u8_at_call",
        _replace_span(source_text, call_site.byte_start, call_site.byte_end, new_call),
    )


def _return_local_materialization_variant(
    source_text: str,
    context: Mapping[str, Any],
) -> tuple[str, str]:
    inline_def: InlineDef = context["inline_def"]
    occurrence: _InlineOccurrence = context["occurrence"]
    return_local, error = _terminal_return_local(inline_def.body_text)
    if return_local is None:
        raise _DimensionBlocked(error or "could not identify return local")

    body = source_text[occurrence.body_start:occurrence.body_end]
    result_local = _fresh_local_name(body, ("result", "sum_result", "return_value"))
    insert_at, indent = _leading_declaration_insert(body)
    if insert_at is None:
        raise _DimensionBlocked("return materialization requires leading declarations")
    body_with_decl = (
        body[:insert_at]
        + f"{indent}int {result_local};\n"
        + body[insert_at:]
    )
    return_matches = list(
        re.finditer(
            rf"(?m)^(?P<indent>[ \t]*)return\s+"
            rf"{re.escape(return_local)}\s*;[ \t]*$",
            body_with_decl,
        )
    )
    if not return_matches:
        raise _DimensionBlocked("could not find terminal return local statement")
    match = return_matches[-1]
    replacement = (
        f"{match.group('indent')}{result_local} = {return_local};\n"
        f"{match.group('indent')}return {result_local};"
    )
    new_body = (
        body_with_decl[:match.start()]
        + replacement
        + body_with_decl[match.end():]
    )
    return (
        "explicit_return_local",
        _replace_span(source_text, occurrence.body_start, occurrence.body_end, new_body),
    )


def _scalar_assignment_splice_variant(
    source_text: str,
    context: Mapping[str, Any],
) -> tuple[str, str]:
    inline_def: InlineDef = context["inline_def"]
    call_site: CallSite = context["call_site"]
    source_function = str(context["source_function"])
    patch = build_deinline_patch(source_text, source_function, inline_def, [call_site])
    if not patch.ok or patch.new_source is None:
        raise _DimensionBlocked(
            patch.unsupported_reason or "scalar assignment splice failed"
        )
    return "deinline_scalar_assignment_splice", patch.new_source


def _void_statement_splice_variant(
    source_text: str,
    context: Mapping[str, Any],
) -> tuple[str, str]:
    inline_def: InlineDef = context["inline_def"]
    call_site: CallSite = context["call_site"]
    source_function = str(context["source_function"])
    patch = build_deinline_patch(source_text, source_function, inline_def, [call_site])
    if not patch.ok or patch.new_source is None:
        raise _DimensionBlocked(
            patch.unsupported_reason or "void statement splice failed"
        )
    return "deinline_void_statement_splice", patch.new_source


def _void_value_argument_temp_variant(
    source_text: str,
    context: Mapping[str, Any],
) -> tuple[str, str]:
    inline_def: InlineDef = context["inline_def"]
    call_site: CallSite = context["call_site"]
    for index, ((type_text, name), arg) in enumerate(
        zip(inline_def.params, call_site.args)
    ):
        if not name or not type_text.strip() or not _nontrivial_call_arg(arg):
            continue
        span = _call_statement_line_span(source_text, call_site)
        if span is None:
            raise _DimensionBlocked("void call argument temp requires standalone call")
        line_start, line_end, indent = span
        temp_name = _fresh_inline_temp_name(source_text, f"inline_{name}_arg")
        args = list(call_site.args)
        args[index] = temp_name
        call_text = source_text[call_site.byte_start:call_site.byte_end]
        callee_match = re.match(rf"\s*(?P<callee>{_IDENT})\s*\(", call_text)
        if callee_match is None:
            raise _DimensionBlocked("could not identify void inline call callee")
        args = [_one_line_expression(item) for item in args]
        arg_expr = _one_line_expression(arg)
        new_statement = (
            f"{indent}{{\n"
            f"{indent}    {type_text.strip()} {temp_name} = {arg_expr};\n"
            f"{indent}    {callee_match.group('callee')}({', '.join(args)});\n"
            f"{indent}}}"
        )
        return (
            f"temp_arg_{index}_{name}",
            _replace_span(source_text, line_start, line_end, new_statement),
        )
    raise _DimensionBlocked("void value-temp variant found no nontrivial argument")


def _void_direct_helper_call_variant(
    source_text: str,
    context: Mapping[str, Any],
) -> tuple[str, str]:
    inline_def: InlineDef = context["inline_def"]
    call_site: CallSite = context["call_site"]
    if not inline_def.name.endswith("_Fake"):
        raise _DimensionBlocked("direct helper variant requires *_Fake inline name")
    direct_name = inline_def.name.removesuffix("_Fake")
    call_text = source_text[call_site.byte_start:call_site.byte_end]
    if not re.match(rf"\s*{re.escape(inline_def.name)}\s*\(", call_text):
        raise _DimensionBlocked("could not identify fake helper call")
    return (
        f"direct_{direct_name}",
        _replace_span(
            source_text,
            call_site.byte_start,
            call_site.byte_start + len(inline_def.name),
            direct_name,
        ),
    )


def _call_statement_line_span(
    source_text: str,
    call_site: CallSite,
) -> tuple[int, int, str] | None:
    line_start = source_text.rfind("\n", 0, call_site.byte_start) + 1
    line_end = source_text.find("\n", call_site.byte_end)
    if line_end < 0:
        line_end = len(source_text)
    prefix = source_text[line_start:call_site.byte_start]
    suffix = source_text[call_site.byte_end:line_end]
    if prefix.strip() or suffix.strip() != ";":
        return None
    return line_start, line_end, prefix


def _nontrivial_call_arg(arg: str) -> bool:
    text = arg.strip()
    if re.fullmatch(_IDENT, text):
        return False
    if re.fullmatch(r"(0x[0-9A-Fa-f]+|\d+|'.'|\".*\")", text):
        return False
    return True


def _fresh_inline_temp_name(source_text: str, base: str) -> str:
    names = set(re.findall(rf"\b{_IDENT}\b", source_text))
    name = base
    suffix = 0
    while name in names:
        suffix += 1
        name = f"{base}_{suffix}"
    return name


def _one_line_expression(text: str) -> str:
    return " ".join(text.strip().split())


def _materialized_u8_arg(arg: str) -> str:
    text = " ".join(arg.strip().split())
    if re.fullmatch(r"\(u8\)\s*.+", text):
        raise _DimensionBlocked("call argument is already materialized as u8")
    mask = re.fullmatch(r"(?P<expr>.+?)\s*&\s*0xFF", text)
    if mask is not None:
        return f"(u8) {mask.group('expr').strip()}"
    if re.fullmatch(_IDENT, text):
        return f"(u8) {text}"
    return f"(u8) ({text})"


def _replace_span(source_text: str, start: int, end: int, replacement: str) -> str:
    return source_text[:start] + replacement + source_text[end:]


def _declaration_line_matches(body: str) -> list[re.Match[str]]:
    pattern = re.compile(
        rf"(?m)^[ \t]*(?:const\s+)?(?:unsigned\s+|signed\s+)?"
        rf"{_IDENT}(?:\s*\*)?\s+{_IDENT}\s*;[ \t]*$"
    )
    return list(pattern.finditer(body))


def _leading_declaration_insert(body: str) -> tuple[int | None, str]:
    pos = 0
    insert_at: int | None = None
    indent = "    "
    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            pos += len(line)
            continue
        if re.fullmatch(
            rf"[ \t]*(?:const\s+)?(?:unsigned\s+|signed\s+)?"
            rf"{_IDENT}(?:\s*\*)?\s+{_IDENT}\s*;[ \t]*(?:\n)?",
            line,
        ):
            match = re.match(r"[ \t]*", line)
            indent = match.group(0) if match is not None else indent
            pos += len(line)
            insert_at = pos
            continue
        break
    return insert_at, indent


def _fresh_local_name(body: str, choices: Sequence[str]) -> str:
    names = set(re.findall(rf"\b{_IDENT}\b", body))
    for choice in choices:
        if choice not in names:
            return choice
    index = 2
    while f"result_{index}" in names:
        index += 1
    return f"result_{index}"


def _candidate_dict(
    *,
    base_source_text: str,
    source_text: str,
    function: str,
    source_function: str,
    inline_name: str,
    expansion_form: str,
    dimension: str,
    variant: str,
    order: int,
    target_map: Mapping[str, int],
) -> dict[str, Any]:
    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    candidate_id = (
        f"{FAMILY_ID}:{function}:{inline_name}:{dimension}:{variant}:"
        f"{digest[:16]}"
    )
    hunks = diff_line_hunks(
        base_source_text,
        source_text,
        hunk_prefix=re.sub(r"[^A-Za-z0-9_]+", "_", dimension).strip("_") + "_h",
    )
    return {
        "candidate_id": candidate_id,
        "family_id": FAMILY_ID,
        "function": function,
        "source_function": source_function,
        "inline_name": inline_name,
        "expansion_form": expansion_form,
        "dimension": dimension,
        "dimension_id": dimension,
        "variant": variant,
        "candidate_order": order,
        "target_map": dict(target_map),
        "source_sha256": digest,
        "source_text": source_text,
        "source_hunks": [hunk.to_dict() for hunk in hunks],
    }


def _candidate_order_map(
    candidates: Sequence[Mapping[str, Any]] | None,
    candidate_order: Mapping[str, int] | None,
) -> dict[str, int]:
    out: dict[str, int] = {}
    if candidate_order is not None:
        out.update({str(key): int(value) for key, value in candidate_order.items()})
    if candidates is not None:
        for index, candidate in enumerate(candidates):
            candidate_id = candidate.get("candidate_id")
            if candidate_id is None:
                continue
            value = candidate.get("candidate_order", index)
            out.setdefault(str(candidate_id), int(value))
    return out


def _candidate_order_value(
    candidate: Mapping[str, Any],
    default: int = 0,
) -> int:
    value = candidate.get("candidate_order", default)
    if value is None:
        value = default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _candidate_match_index(
    candidates: Sequence[Mapping[str, Any]],
    candidate_order: Mapping[str, int] | None,
) -> dict[str, dict[str, list[Mapping[str, Any]]]]:
    index: dict[str, dict[str, list[Mapping[str, Any]]]] = {
        "ids": {},
        "stems": {},
        "hashes": {},
        "orders": {},
    }
    for position, candidate in enumerate(candidates):
        candidate_id = str(candidate.get("candidate_id") or "")
        if candidate_id:
            _append_index_match(index["ids"], candidate_id, candidate)

        order = _candidate_order_value(candidate, position)
        if (
            candidate_id
            and candidate_order is not None
            and candidate_id in candidate_order
        ):
            order = int(candidate_order[candidate_id])
        _append_index_match(index["orders"], str(order), candidate)

        _append_index_match(
            index["stems"],
            inline_boundary_candidate_file_stem({
                **dict(candidate),
                "candidate_order": order,
            }),
            candidate,
        )
        for _field, value in _candidate_path_values(candidate):
            for stem in _lookup_stems(value):
                _append_index_match(index["stems"], stem, candidate)

        source_hash = candidate.get("source_sha256")
        if isinstance(source_hash, str) and source_hash:
            _append_index_match(index["hashes"], source_hash.lower(), candidate)
            _append_index_match(index["hashes"], source_hash[:16].lower(), candidate)
        for token in _hash_tokens(str(candidate_id)):
            _append_index_match(index["hashes"], token.lower(), candidate)
    return index


def _append_index_match(
    table: dict[str, list[Mapping[str, Any]]],
    key: str,
    candidate: Mapping[str, Any],
) -> None:
    if not key:
        return
    rows = table.setdefault(key, [])
    candidate_id = candidate.get("candidate_id")
    if any(existing.get("candidate_id") == candidate_id for existing in rows):
        return
    rows.append(candidate)


def _candidate_path_values(
    candidate: Mapping[str, Any],
) -> Iterator[tuple[str, Any]]:
    for field in ("path", "source_path", "source_file", "candidate_path"):
        if candidate.get(field) is not None:
            yield field, candidate.get(field)
    score_source = candidate.get("score_source")
    if isinstance(score_source, Mapping) and score_source.get("path") is not None:
        yield "score_source.path", score_source.get("path")


def _score_lookup_values(row: Mapping[str, Any]) -> Iterator[tuple[str, Any]]:
    for field in (*_SCORE_ID_KEYS, *_SCORE_PATH_KEYS):
        if row.get(field) is not None:
            yield field, row.get(field)
    score_source = row.get("score_source")
    if isinstance(score_source, Mapping) and score_source.get("path") is not None:
        yield "score_source.path", score_source.get("path")


def _match_score_candidate(
    row: Mapping[str, Any],
    index: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
) -> tuple[Mapping[str, Any] | None, dict[str, Any] | None]:
    exact_matches: list[tuple[str, str, Mapping[str, Any]]] = []
    for field in _SCORE_ID_KEYS:
        value = row.get(field)
        if value is None:
            continue
        key = str(value)
        exact_matches.extend(
            (field, key, candidate)
            for candidate in index["ids"].get(key, ())
        )
    match, diagnostic = _unique_score_match(exact_matches)
    if match is not None or diagnostic is not None:
        return match, diagnostic

    stem_matches: list[tuple[str, str, Mapping[str, Any]]] = []
    for field, value in _score_lookup_values(row):
        for stem in _lookup_stems(value):
            stem_matches.extend(
                (f"{field}_stem", stem, candidate)
                for candidate in index["stems"].get(stem, ())
            )
    match, diagnostic = _unique_score_match(stem_matches)
    if match is not None or diagnostic is not None:
        return match, diagnostic

    hash_matches: list[tuple[str, str, Mapping[str, Any]]] = []
    for field, value in _score_lookup_values(row):
        for token in _hash_tokens(str(value)):
            hash_matches.extend(
                (f"{field}_hash", token, candidate)
                for candidate in index["hashes"].get(token.lower(), ())
            )
    match, diagnostic = _unique_score_match(hash_matches)
    if match is not None or diagnostic is not None:
        return match, diagnostic

    explicit_order = row.get("candidate_order")
    if explicit_order is None:
        return None, {"status": "uncorrelated"}
    try:
        order_key = str(int(explicit_order))
    except (TypeError, ValueError):
        return None, {"status": "uncorrelated"}
    order_matches = [
        ("candidate_order", order_key, candidate)
        for candidate in index["orders"].get(order_key, ())
    ]
    return _unique_score_match(order_matches)


def _unique_score_match(
    matches: Sequence[tuple[str, str, Mapping[str, Any]]],
) -> tuple[Mapping[str, Any] | None, dict[str, Any] | None]:
    if not matches:
        return None, None
    by_id: dict[str, tuple[str, str, Mapping[str, Any]]] = {}
    for method, key, candidate in matches:
        candidate_id = str(candidate.get("candidate_id") or "")
        if candidate_id:
            by_id.setdefault(candidate_id, (method, key, candidate))
    if len(by_id) == 1:
        candidate_id, (method, key, candidate) = next(iter(by_id.items()))
        return candidate, {
            "status": "correlated",
            "method": method,
            "key": key,
            "candidate_id": candidate_id,
        }
    return None, {
        "status": "ambiguous",
        "candidate_ids": sorted(by_id),
    }


def _lookup_stems(value: Any) -> set[str]:
    if value is None:
        return set()
    text = str(value).strip()
    if not text:
        return set()
    names = {text, Path(text).name, Path(text).stem}
    stems: set[str] = set()
    pending = list(names)
    while pending:
        item = pending.pop()
        if not item or item in stems:
            continue
        stems.add(item)
        for suffix in _KNOWN_SCORE_SUFFIXES:
            if item.endswith(suffix):
                pending.append(item[: -len(suffix)])
    return stems


def _hash_tokens(text: str) -> set[str]:
    return {match.group(1).lower() for match in _HEX_TOKEN_RE.finditer(text)}


def _score_rank_key(
    row: Mapping[str, Any],
    targets: Mapping[str, int],
    order_by_id: Mapping[str, int],
) -> tuple[float, float, float, float, int]:
    expression_score = _score_container(row, "expression_score")
    target_score = _score_container(row, "target_score")
    target_matched = _score_matched(target_score, targets)
    expression_matched = _score_matched(expression_score, targets)
    target_distance = _score_distance(target_score, targets)
    expression_distance = _score_distance(expression_score, targets)
    order = _score_candidate_order(row, order_by_id)
    return (
        -float(target_matched),
        -float(expression_matched),
        target_distance if target_distance is not None else float("inf"),
        expression_distance if expression_distance is not None else float("inf"),
        order,
    )


def _rank_score_summary(
    row: Mapping[str, Any],
    targets: Mapping[str, int],
    order_by_id: Mapping[str, int],
) -> dict[str, Any]:
    expression_score = _score_container(row, "expression_score")
    target_score = _score_container(row, "target_score")
    return {
        "target_matched": _score_matched(target_score, targets),
        "target_virtual_distance": _score_distance(target_score, targets),
        "expression_matched": _score_matched(expression_score, targets),
        "expression_virtual_distance": _score_distance(expression_score, targets),
        "candidate_order": _score_candidate_order(row, order_by_id),
    }


def _score_candidate_order(
    row: Mapping[str, Any],
    order_by_id: Mapping[str, int],
) -> int:
    candidate_id = row.get("candidate_id")
    if candidate_id is not None and str(candidate_id) in order_by_id:
        return order_by_id[str(candidate_id)]
    value = row.get("candidate_order")
    if value is not None:
        return int(value)
    return len(order_by_id)


def _score_container(row: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    direct = row.get(key)
    if isinstance(direct, Mapping):
        return direct
    payload = row.get("validator_payload")
    if isinstance(payload, Mapping):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            return nested
    return None


def _score_matched(
    score: Mapping[str, Any] | None,
    targets: Mapping[str, int],
) -> int:
    if not isinstance(score, Mapping):
        return 0
    matched = _int_or_none(score.get("matched"))
    if matched is not None:
        return matched
    virtuals = score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return 0
    keys = targets.keys() if targets else virtuals.keys()
    count = 0
    for key in keys:
        entry = virtuals.get(str(key))
        if isinstance(entry, Mapping) and entry.get("matched") is True:
            count += 1
    return count


def _score_distance(
    score: Mapping[str, Any] | None,
    targets: Mapping[str, int],
) -> float | None:
    if not isinstance(score, Mapping):
        return None
    for key in ("virtual_distance", "distance", "score"):
        value = _float_or_none(score.get(key))
        if value is not None:
            return value
    virtuals = score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return None
    keys = targets.keys() if targets else virtuals.keys()
    total = 0.0
    seen = False
    for key in keys:
        entry = virtuals.get(str(key))
        if not isinstance(entry, Mapping):
            continue
        expected = _float_or_none(entry.get("expected", targets.get(str(key))))
        actual = _float_or_none(entry.get("actual"))
        if expected is None or actual is None:
            continue
        total += abs(actual - expected)
        seen = True
    return total if seen else None


def _target_or_expression_score_improved(
    row: Mapping[str, Any],
    targets: Mapping[str, int],
) -> bool:
    if _checkdiff_score_improved(row):
        return True
    return max(
        _score_matched(_score_container(row, "target_score"), targets),
        _score_matched(_score_container(row, "expression_score"), targets),
    ) > 0


def _has_exhaustion_evidence(row: Mapping[str, Any]) -> bool:
    return (
        _score_container(row, "target_score") is not None
        or _score_container(row, "expression_score") is not None
        or _checkdiff_container(row) is not None
    )


def _checkdiff_container(row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    direct = row.get("checkdiff")
    if isinstance(direct, Mapping):
        return direct
    payload = row.get("validator_payload")
    if isinstance(payload, Mapping):
        nested = payload.get("checkdiff")
        if isinstance(nested, Mapping):
            return nested
    if any(key in row for key in ("match", "fuzzy_match_percent", "classification")):
        return row
    return None


def _checkdiff_score_improved(row: Mapping[str, Any]) -> bool:
    checkdiff = _checkdiff_container(row)
    if not isinstance(checkdiff, Mapping):
        return False
    if checkdiff.get("match") is True:
        return True
    current = _float_or_none(
        checkdiff.get("fuzzy_match_percent")
        or checkdiff.get("match_percent")
        or checkdiff.get("percent")
    )
    baseline = _float_or_none(
        checkdiff.get("baseline_fuzzy_match_percent")
        or checkdiff.get("baseline_match_percent")
        or row.get("baseline_fuzzy_match_percent")
        or row.get("baseline_match_percent")
    )
    return current is not None and baseline is not None and current > baseline


def _checkdiff_summary(row: Mapping[str, Any]) -> dict[str, Any] | None:
    checkdiff = _checkdiff_container(row)
    if not isinstance(checkdiff, Mapping):
        return None
    classification = checkdiff.get("classification")
    if isinstance(classification, Mapping):
        classification_primary = classification.get("primary")
    else:
        classification_primary = classification
    return {
        "match": checkdiff.get("match"),
        "fuzzy_match_percent": _float_or_none(
            checkdiff.get("fuzzy_match_percent")
            or checkdiff.get("match_percent")
            or checkdiff.get("percent")
        ),
        "baseline_fuzzy_match_percent": _float_or_none(
            checkdiff.get("baseline_fuzzy_match_percent")
            or checkdiff.get("baseline_match_percent")
            or row.get("baseline_fuzzy_match_percent")
            or row.get("baseline_match_percent")
        ),
        "classification": classification_primary,
        "path": row.get("checkdiff_json") or row.get("score_json"),
    }


def _candidate_dimensions(
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    seen: list[str] = []
    for candidate in candidates:
        dimension = str(
            candidate.get("dimension_id") or candidate.get("dimension") or ""
        )
        if dimension and dimension not in seen:
            seen.append(dimension)
    return tuple(seen) or DIMENSIONS


def _terminal_reason_for_targets(targets: Mapping[str, int]) -> str:
    if {"34", "44"}.issubset(set(targets)):
        return TERMINAL_REASON
    return "inline-leverage-helper-boundary-exhausted/no-target-progress"


def _dimension_exhaustion_rows(
    candidates: Sequence[Mapping[str, Any]],
    scores_by_id: Mapping[str, Mapping[str, Any]],
    targets: Mapping[str, int],
    *,
    dimensions: Sequence[str] = DIMENSIONS,
) -> list[dict[str, Any]]:
    by_dimension: dict[str, list[Mapping[str, Any]]] = {
        dimension: [] for dimension in dimensions
    }
    for candidate in candidates:
        dimension = str(
            candidate.get("dimension_id") or candidate.get("dimension") or ""
        )
        if dimension in by_dimension:
            by_dimension[dimension].append(candidate)
    rows: list[dict[str, Any]] = []
    exhaustion_reason = _terminal_reason_for_targets(targets).rsplit("/", 1)[-1]
    for dimension in dimensions:
        dim_candidates = by_dimension[dimension]
        if not dim_candidates:
            continue
        matched_values = []
        distances = []
        checkdiff_values = []
        for candidate in dim_candidates:
            score = scores_by_id[str(candidate.get("candidate_id"))]
            target_score = _score_container(score, "target_score")
            matched_values.append(_score_matched(target_score, targets))
            distance = _score_distance(target_score, targets)
            if distance is not None:
                distances.append(distance)
            checkdiff_summary = _checkdiff_summary(score)
            if checkdiff_summary is not None:
                value = checkdiff_summary.get("fuzzy_match_percent")
                if value is not None:
                    checkdiff_values.append(float(value))
        rows.append(
            {
                "dimension_id": dimension,
                "candidate_count": len(dim_candidates),
                "scored_count": len(dim_candidates),
                "best_target_matched": max(matched_values) if matched_values else 0,
                "best_target_virtual_distance": (
                    min(distances) if distances else None
                ),
                "best_checkdiff_fuzzy_match_percent": (
                    max(checkdiff_values) if checkdiff_values else None
                ),
                "exhaustion_reason": exhaustion_reason,
            }
        )
    return rows


def _score_row_summary(
    row: Mapping[str, Any],
    targets: Mapping[str, int],
) -> dict[str, Any]:
    target_score = _score_container(row, "target_score")
    expression_score = _score_container(row, "expression_score")
    out: dict[str, Any] = {
        "candidate_id": row.get("candidate_id"),
        "rank": row.get("rank"),
        "target_matched": _score_matched(target_score, targets),
        "target_virtual_distance": _score_distance(target_score, targets),
        "expression_matched": _score_matched(expression_score, targets),
        "expression_virtual_distance": _score_distance(expression_score, targets),
    }
    if isinstance(target_score, Mapping) and isinstance(
        target_score.get("virtuals"), Mapping
    ):
        out["target_virtuals"] = {
            str(key): dict(value)
            for key, value in target_score["virtuals"].items()
            if isinstance(value, Mapping)
        }
    checkdiff_summary = _checkdiff_summary(row)
    if checkdiff_summary is not None:
        out["checkdiff"] = checkdiff_summary
    return out


def _int_or_none(value: Any) -> int | None:
    number = _float_or_none(value)
    if number is None:
        return None
    return int(number)


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
