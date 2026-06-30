"""Control-flow source-shape probe generation."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.common import tree_sitter_c
from src.common.tree_sitter_c import find_function_definition, node_text

from .pressure_explorer import (
    LifetimeLayoutProbe,
    generate_lifetime_layout_probes,
)
from .source_spans import StatementSpan, list_statement_spans

DEFAULT_CONTROL_FLOW_OPERATORS = (
    "early-guard-return",
    "condition-nesting",
    "loop-init",
    "loop-counter-type",
    "guard-shape",
    "call-return-compare-chain",
    "pointer-walk-loop",
    "pointer-base-call-loop",
    "ternary-to-if-else",
    "if-else-to-ternary",
    "bool-condition-spelling",
    "if-equality-to-single-case-switch",
)

_DELEGATED_OPERATORS = frozenset(DEFAULT_CONTROL_FLOW_OPERATORS) - {
    "ternary-to-if-else",
    "if-else-to-ternary",
    "bool-condition-spelling",
    "if-equality-to-single-case-switch",
}
_LOCAL_OPERATORS = frozenset(DEFAULT_CONTROL_FLOW_OPERATORS) - _DELEGATED_OPERATORS

_IDENT = r"[A-Za-z_]\w*"
_SIMPLE_LHS_RE = re.compile(
    rf"^\s*{_IDENT}(?:(?:->|\.){_IDENT}|\[[A-Za-z0-9_+\-*/%&|^<>() \t]+\])*\s*$"
)
_ZERO_COMPARISON_RE = re.compile(r"^(.+?)\s*(==|!=)\s*0(?:[uUlL]*)?\s*$")
_CONTROL_FLOW_TOKENS = re.compile(r"\b(?:return|goto|break|continue)\b")
_ASSIGNMENT_TOKEN_RE = re.compile(r"(?<![=!<>])=(?!=)")
_PREPROCESSOR_IF_RE = re.compile(r"#\s*(?:if|ifdef|ifndef)\b")
_PREPROCESSOR_ENDIF_RE = re.compile(r"#\s*endif\b")
_FLOAT_LITERAL_RE = re.compile(
    r"^\s*(?:\d+\.\d*|\.\d+|\d+[eE][+-]?\d+|\d+\.\d*[eE][+-]?\d+|\.\d+[eE][+-]?\d+)(?:[fFlL])?\s*$"
)
_MOVED_BODY_REJECT_NODE_TYPES = {
    "labeled_statement",
    "case_statement",
    "break_statement",
    "continue_statement",
    "goto_statement",
}


@dataclass(frozen=True)
class _PointerWalkSourceRegion:
    owner_function: str
    owner_kind: str
    function_start: int
    body_start: int
    body_end: int
    source_lines: tuple[int, int]


@dataclass(frozen=True)
class _IndexTablePointerWalkAnchor:
    owner_function: str
    owner_kind: str
    anchor_kind: str
    span_start: int
    span_end: int
    statement_start: int
    statement_end: int
    indent: str
    base_expr: str
    base_local: str
    pointer_local: str | None
    index_expr: str
    byte_offset: str
    element_type: str
    source_lines: tuple[int, int]
    source_regions: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class _PointerWalkState:
    base_local: str
    index_expr: str
    byte_offset: str | None
    assignment_start: int
    assignment_end: int
    indent: str


def generate_control_flow_shape_probes(
    source: str,
    function: str,
    *,
    operator_filter: Iterable[str] | None = None,
    max_probes: int = 12,
) -> list[LifetimeLayoutProbe]:
    probes, _status = scan_control_flow_shape_probes(
        source,
        function,
        operator_filter=operator_filter,
        max_probes=max_probes,
    )
    return probes


def scan_control_flow_shape_probes(
    source: str,
    function: str,
    *,
    operator_filter: Iterable[str] | None = None,
    max_probes: int = 12,
    suggestions: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[LifetimeLayoutProbe], dict[str, object]]:
    selected = tuple(dict.fromkeys(operator_filter or DEFAULT_CONTROL_FLOW_OPERATORS))
    unsupported = [op for op in selected if op not in DEFAULT_CONTROL_FLOW_OPERATORS]
    if unsupported:
        return [], {
            "blocker": "unsupported-control-flow-shape",
            "reason": f"unsupported control-flow operators: {', '.join(unsupported)}",
            "supported_candidate_count": 0,
            "rejected_candidate_count": len(unsupported),
        }

    if suggestions is not None:
        return materialize_control_flow_suggestions(
            source,
            function,
            suggestions,
            operator_filter=selected,
            max_probes_per_family=max(1, max_probes),
        )

    parsed = _parse_function(source, function)
    if parsed is None:
        return [], {
            "blocker": "ambiguous-control-flow-source-region",
            "reason": "function definition could not be located",
            "supported_candidate_count": 0,
            "rejected_candidate_count": 0,
        }

    source_bytes, function_node = parsed
    try:
        statement_spans = list_statement_spans(source, function)
    except Exception:
        statement_spans = []

    probes: list[LifetimeLayoutProbe] = []
    family_results: list[dict[str, Any]] = []
    terminal_proofs: list[dict[str, Any]] = []
    rejected_candidate_count = 0
    delegated = tuple(
        op
        for op in selected
        if op in _DELEGATED_OPERATORS
        and op not in {"loop-init", "pointer-walk-loop"}
    )
    if delegated:
        probes.extend(
            _retag_control_flow_probe(probe)
            for probe in generate_lifetime_layout_probes(
                source,
                function,
                operator_filter=delegated,
                max_probes=max_probes,
            )
        )

    if len(probes) < max_probes and "pointer-walk-loop" in selected:
        family_id = _control_flow_family_id(
            "pointer-walk-loop",
            "pointer-walk-indexed-shape",
        )
        pointer_probes, proof, exhausted_dimensions = (
            _materialize_pointer_walk_indexed_family(
                source,
                function,
                family_id=family_id,
                max_probes=max_probes - len(probes),
            )
        )
        family_results.append(
            _family_result(
                family_id=family_id,
                operator="pointer-walk-loop",
                suggestion_kind="pointer-walk-indexed-shape",
                status="materialized" if pointer_probes else "terminal",
                probe_count=len(pointer_probes),
                terminal_proof=proof,
                exhausted_dimensions=exhausted_dimensions,
            )
        )
        probes.extend(pointer_probes)
        rejected_candidate_count += len(exhausted_dimensions)
        if proof is not None:
            terminal_proofs.append(proof)

    if len(probes) < max_probes and "loop-init" in selected:
        family_id = _control_flow_family_id("loop-init", "loop-peel-unroll")
        loop_probes, proof, exhausted_dimensions = _materialize_loop_init_family(
            source,
            function,
            family_id=family_id,
            max_probes=max_probes - len(probes),
        )
        family_results.append(
            _family_result(
                family_id=family_id,
                operator="loop-init",
                suggestion_kind="loop-peel-unroll",
                status="materialized" if loop_probes else "terminal",
                probe_count=len(loop_probes),
                terminal_proof=proof,
                exhausted_dimensions=exhausted_dimensions,
            )
        )
        probes.extend(loop_probes)
        rejected_candidate_count += len(exhausted_dimensions)
        if proof is not None:
            terminal_proofs.append(proof)

    if len(probes) < max_probes:
        probes.extend(
            _local_control_flow_probes(
                source,
                function,
                source_bytes,
                function_node,
                statement_spans,
                tuple(op for op in selected if op in _LOCAL_OPERATORS),
                max_probes=max_probes - len(probes),
            )
        )

    probes = probes[:max_probes]
    if not probes:
        status: dict[str, object] = {
            "blocker": "no-control-flow-shape-probes",
            "reason": "no safe control-flow source transform matched",
            "supported_candidate_count": 0,
            "rejected_candidate_count": rejected_candidate_count,
        }
        if family_results:
            status["families"] = family_results
        if terminal_proofs:
            status["terminal_proofs"] = terminal_proofs
        return [], status
    status = {
        "blocker": None,
        "reason": "source scan generated safe control-flow shape probes",
        "supported_candidate_count": len(probes),
        "rejected_candidate_count": rejected_candidate_count,
    }
    if family_results:
        status["families"] = family_results
    if terminal_proofs:
        status["terminal_proofs"] = terminal_proofs
    return probes, status


def materialize_control_flow_suggestions(
    source: str,
    function: str,
    suggestions: Sequence[Mapping[str, Any]],
    *,
    operator_filter: Iterable[str] | None = None,
    max_probes_per_family: int = 4,
) -> tuple[list[LifetimeLayoutProbe], dict[str, Any]]:
    """Materialize bounded probes or terminal proofs for ranked suggestions."""
    selected = frozenset(operator_filter or DEFAULT_CONTROL_FLOW_OPERATORS)
    probes: list[LifetimeLayoutProbe] = []
    family_results: list[dict[str, Any]] = []
    terminal_proofs: list[dict[str, Any]] = []
    rejected_candidate_count = 0

    for suggestion in suggestions:
        if not isinstance(suggestion, Mapping):
            continue
        operator = suggestion.get("operator")
        if not isinstance(operator, str) or not operator:
            continue
        if operator not in selected:
            continue
        kind = str(suggestion.get("kind") or "unspecified")
        family_id = _control_flow_family_id(operator, kind)
        if operator not in DEFAULT_CONTROL_FLOW_OPERATORS:
            proof = _terminal_proof(
                family_id=family_id,
                operator=operator,
                suggestion_kind=kind,
                blocker="unsupported-control-flow-shape",
                reason=f"unsupported control-flow operator: {operator}",
                exhausted_dimensions=[
                    {
                        "dimension_id": "operator",
                        "reason": "unsupported-control-flow-shape",
                    }
                ],
            )
            result = _family_result(
                family_id=family_id,
                operator=operator,
                suggestion_kind=kind,
                status="unsupported",
                probe_count=0,
                terminal_proof=proof,
            )
            family_results.append(result)
            terminal_proofs.append(proof)
            rejected_candidate_count += 1
            continue

        family_probes, proof, exhausted_dimensions = _materialize_suggestion_family(
            source,
            function,
            suggestion,
            operator=operator,
            suggestion_kind=kind,
            family_id=family_id,
            max_probes=max(1, max_probes_per_family),
        )
        family_probes = family_probes[: max(1, max_probes_per_family)]
        status = "materialized" if family_probes else "terminal"
        result = _family_result(
            family_id=family_id,
            operator=operator,
            suggestion_kind=kind,
            status=status,
            probe_count=len(family_probes),
            terminal_proof=proof,
            exhausted_dimensions=exhausted_dimensions,
        )
        family_results.append(result)
        probes.extend(family_probes)
        rejected_candidate_count += len(exhausted_dimensions)
        if status == "terminal" and proof is not None:
            terminal_proofs.append(proof)

    if not family_results:
        return [], {
            "blocker": "no-control-flow-shape-suggestions",
            "reason": "no suggested control-flow family matched the operator filter",
            "families": [],
            "terminal_proofs": [],
            "supported_candidate_count": 0,
            "rejected_candidate_count": 0,
        }

    blocker = None if probes else "control-flow-shape-families-terminal"
    reason = (
        "suggested control-flow families produced safe source probes"
        if probes
        else "all selected control-flow families reached terminal source proofs"
    )
    return probes, {
        "blocker": blocker,
        "reason": reason,
        "families": family_results,
        "terminal_proofs": terminal_proofs,
        "supported_candidate_count": len(probes),
        "rejected_candidate_count": rejected_candidate_count,
    }


def _control_flow_family_id(operator: str, suggestion_kind: str) -> str:
    return f"{operator}/{suggestion_kind}"


def _family_result(
    *,
    family_id: str,
    operator: str,
    suggestion_kind: str,
    status: str,
    probe_count: int,
    terminal_proof: Mapping[str, Any] | None = None,
    exhausted_dimensions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "family_id": family_id,
        "operator": operator,
        "suggestion_kind": suggestion_kind,
        "status": status,
        "probe_count": probe_count,
        "terminal_proof": dict(terminal_proof) if terminal_proof is not None else None,
    }
    if exhausted_dimensions:
        result["exhausted_dimensions"] = [dict(item) for item in exhausted_dimensions]
    return result


def _terminal_proof(
    *,
    family_id: str,
    operator: str,
    suggestion_kind: str,
    blocker: str,
    reason: str,
    source_model_proof: Mapping[str, Any] | None = None,
    exhausted_dimensions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    proof: dict[str, Any] = {
        "family_id": family_id,
        "operator": operator,
        "suggestion_kind": suggestion_kind,
        "terminal_blocker": blocker,
        "terminal_reason": reason,
    }
    if source_model_proof is not None:
        proof["source_model_proof"] = dict(source_model_proof)
    if exhausted_dimensions:
        proof["exhausted_dimensions"] = [
            dict(item) for item in exhausted_dimensions
        ]
    return proof


def _materialize_suggestion_family(
    source: str,
    function: str,
    suggestion: Mapping[str, Any],
    *,
    operator: str,
    suggestion_kind: str,
    family_id: str,
    max_probes: int,
) -> tuple[list[LifetimeLayoutProbe], dict[str, Any] | None, list[dict[str, Any]]]:
    if operator == "pointer-base-call-loop" and suggestion_kind == "call-hoist":
        return _materialize_call_hoist_family(
            source,
            function,
            suggestion,
            family_id=family_id,
            max_probes=max_probes,
        )
    if (
        operator == "pointer-walk-loop"
        and suggestion_kind == "pointer-walk-indexed-shape"
    ):
        return _materialize_pointer_walk_indexed_family(
            source,
            function,
            family_id=family_id,
            max_probes=max_probes,
        )
    if operator == "loop-init" and suggestion_kind == "loop-peel-unroll":
        return _materialize_loop_init_family(
            source,
            function,
            family_id=family_id,
            max_probes=max_probes,
        )

    generic_probes, generic_status = scan_control_flow_shape_probes(
        source,
        function,
        operator_filter=(operator,),
        max_probes=max_probes,
    )
    tagged = [
        _retag_suggestion_probe(
            probe,
            family_id=family_id,
            suggestion_kind=suggestion_kind,
        )
        for probe in generic_probes[:max_probes]
    ]
    if tagged:
        return tagged, None, []
    proof = _terminal_proof(
        family_id=family_id,
        operator=operator,
        suggestion_kind=suggestion_kind,
        blocker=str(generic_status.get("blocker") or "no-control-flow-shape-probes"),
        reason=str(
            generic_status.get("reason")
            or "no safe source transform matched this suggestion"
        ),
        exhausted_dimensions=[
            {
                "dimension_id": "generic-source-scan",
                "reason": str(
                    generic_status.get("blocker")
                    or "no-control-flow-shape-probes"
                ),
            }
        ],
    )
    return [], proof, list(proof.get("exhausted_dimensions", []))


def _retag_suggestion_probe(
    probe: LifetimeLayoutProbe,
    *,
    family_id: str,
    suggestion_kind: str,
    label: str | None = None,
) -> LifetimeLayoutProbe:
    provenance = dict(probe.provenance or {})
    provenance["kind"] = "control-flow-shape"
    provenance["operator"] = probe.operator
    provenance["family_id"] = family_id
    provenance["suggestion_kind"] = suggestion_kind
    return LifetimeLayoutProbe(
        label=label or probe.label,
        operator=probe.operator,
        description=probe.description,
        source_text=probe.source_text,
        provenance=provenance,
    )


def _materialize_call_hoist_family(
    source: str,
    function: str,
    suggestion: Mapping[str, Any],
    *,
    family_id: str,
    max_probes: int,
) -> tuple[list[LifetimeLayoutProbe], dict[str, Any] | None, list[dict[str, Any]]]:
    evidence = suggestion.get("evidence")
    symbol = evidence.get("symbol") if isinstance(evidence, Mapping) else None
    if not isinstance(symbol, str) or not symbol:
        proof = _terminal_proof(
            family_id=family_id,
            operator="pointer-base-call-loop",
            suggestion_kind="call-hoist",
            blocker="call-anchor-not-found",
            reason="call-hoist suggestion did not include a source call symbol",
            exhausted_dimensions=[
                {"dimension_id": "source-call-anchor", "reason": "symbol-missing"}
            ],
        )
        return [], proof, list(proof["exhausted_dimensions"])

    probes: list[LifetimeLayoutProbe] = []
    exhausted_dimensions: list[dict[str, Any]] = []
    source_model: dict[str, Any] = {
        "symbol": symbol,
        "call_return_type": "int",
        "loop_counter_args": [],
        "call_result_used": False,
        "branch_returns_after_call": False,
    }
    call_found = False

    for loop in _iter_simple_for_loops(source, function):
        call = _first_standalone_call_statement(
            source,
            loop["body_start"],
            loop["body_end"],
            symbol,
        )
        if call is None:
            continue
        call_found = True
        args_text = call["args"]
        counter = str(loop["counter"])
        if re.search(rf"\b{re.escape(counter)}\b", args_text):
            source_model["loop_counter_args"] = sorted(
                set([*source_model["loop_counter_args"], counter])
            )
            exhausted_dimensions.append(
                {
                    "dimension_id": "true_pre_loop_hoist",
                    "reason": "loop-counter-dependent-call-args",
                    "source_lines": list(loop["source_lines"]),
                }
            )
        source_model["branch_returns_after_call"] = bool(
            source_model["branch_returns_after_call"]
            or re.search(r"\breturn\b", _mask_c_non_code_text(call["tail_in_loop"]))
        )
        exhausted_dimensions.append(
            {
                "dimension_id": "cache_for_loop_condition",
                "reason": "call-result-not-used-in-condition",
                "source_lines": list(loop["source_lines"]),
            }
        )
        probes.extend(
            _call_hoist_return_value_probes(
                source,
                call,
                family_id=family_id,
                index=len(probes),
            )
        )
        if len(probes) >= max_probes:
            break

    if not call_found:
        proof = _terminal_proof(
            family_id=family_id,
            operator="pointer-base-call-loop",
            suggestion_kind="call-hoist",
            blocker="call-anchor-not-found",
            reason=f"no standalone `{symbol}` call inside a simple counted loop",
            source_model_proof=source_model,
            exhausted_dimensions=[
                {
                    "dimension_id": "source-call-anchor",
                    "reason": "call-anchor-not-found",
                }
            ],
        )
        return [], proof, list(proof["exhausted_dimensions"])

    if not exhausted_dimensions:
        exhausted_dimensions.append(
            {
                "dimension_id": "true_pre_loop_hoist",
                "reason": "side-effectful-call-placement-not-proven-safe",
            }
        )
    proof = _terminal_proof(
        family_id=family_id,
        operator="pointer-base-call-loop",
        suggestion_kind="call-hoist",
        blocker="true-hoist-not-source-preserving",
        reason=(
            f"`{symbol}` is side-effectful source, and the suggested true "
            "pre-loop hoist is not proven source-preserving for this loop."
        ),
        source_model_proof=source_model,
        exhausted_dimensions=exhausted_dimensions,
    )
    return probes[:max_probes], proof, exhausted_dimensions


def _call_hoist_return_value_probes(
    source: str,
    call: Mapping[str, Any],
    *,
    family_id: str,
    index: int,
) -> list[LifetimeLayoutProbe]:
    indent = str(call["indent"])
    call_expr = str(call["call_expr"])
    line_start = int(call["statement_start"])
    line_end = int(call["statement_end"])
    lines = list(_line_range_char(source, line_start, line_end))
    newline = "\n" if line_end > line_start and source[line_end - 1] == "\n" else ""
    result_name = f"ll_probe_call_result_{index}"
    decl_name = f"ll_probe_call_result_{index + 1}"
    first = LifetimeLayoutProbe(
        label=f"call-hoist-result-temp-{index}",
        operator="pointer-base-call-loop",
        description="Name the call result at the suggested call-hoist site.",
        source_text=_replace_char_slice(
            source,
            line_start,
            line_end,
            (
                f"{indent}s32 {result_name} = {call_expr};\n"
                f"{indent}(void) {result_name};{newline}"
            ),
        ),
        provenance={
            "kind": "control-flow-shape",
            "operator": "pointer-base-call-loop",
            "family_id": family_id,
            "suggestion_kind": "call-hoist",
            "variant": "return-value-temp",
            "symbol": call["symbol"],
            "source_lines": lines,
        },
    )
    second = LifetimeLayoutProbe(
        label=f"call-hoist-result-decl-{index}",
        operator="pointer-base-call-loop",
        description="Declare the call result before assigning at the call site.",
        source_text=_replace_char_slice(
            source,
            line_start,
            line_end,
            (
                f"{indent}s32 {decl_name};\n"
                f"{indent}{decl_name} = {call_expr};\n"
                f"{indent}(void) {decl_name};{newline}"
            ),
        ),
        provenance={
            "kind": "control-flow-shape",
            "operator": "pointer-base-call-loop",
            "family_id": family_id,
            "suggestion_kind": "call-hoist",
            "variant": "declaration-before-use",
            "symbol": call["symbol"],
            "source_lines": lines,
        },
    )
    return [first, second]


def _materialize_pointer_walk_indexed_family(
    source: str,
    function: str,
    *,
    family_id: str,
    max_probes: int,
) -> tuple[list[LifetimeLayoutProbe], dict[str, Any] | None, list[dict[str, Any]]]:
    probes: list[LifetimeLayoutProbe] = []
    exhausted_dimensions: list[dict[str, Any]] = []
    member_anchor_seen = False

    for loop in _iter_simple_for_loops(source, function):
        anchors = _pointer_walk_loop_anchors(str(loop["body"]), str(loop["counter"]))
        if not anchors:
            continue
        member_anchor_seen = True
        rejection = _safe_loop_rejection(loop)
        if rejection is not None:
            exhausted_dimensions.append(
                {
                    "dimension_id": f"loop@{loop['source_lines'][0]}",
                    "reason": rejection,
                    "anchors": anchors,
                    "source_lines": list(loop["source_lines"]),
                }
            )
            continue
        probes.extend(
            _pointer_walk_member_array_probes(
                source,
                loop,
                family_id=family_id,
                start_index=len(probes),
            )
        )
        if len(probes) >= max_probes:
            break

    if len(probes) < max_probes:
        index_table_probes, index_table_dimensions, index_table_anchor_seen = (
            _pointer_walk_index_table_probes(
                source,
                function,
                family_id=family_id,
                start_index=len(probes),
                max_probes=max_probes - len(probes),
            )
        )
        probes.extend(index_table_probes)
        exhausted_dimensions.extend(index_table_dimensions)
    else:
        index_table_anchor_seen = False

    if probes:
        return probes[:max_probes], None, exhausted_dimensions

    blocker = "member-array-anchor-not-found"
    reason = (
        "no member-array or index-table anchor matched the pointer-walk suggestion"
    )
    if exhausted_dimensions:
        blocker = str(exhausted_dimensions[0]["reason"])
        reason = "all pointer-walk source anchors were rejected as unsafe"
    elif not member_anchor_seen and not index_table_anchor_seen:
        exhausted_dimensions.append(
            {
                "dimension_id": "member-array-anchor",
                "reason": "member-array-anchor-not-found",
            }
        )
        exhausted_dimensions.append(
            {
                "dimension_id": "u8-index-table-anchor",
                "reason": "u8-index-table-anchor-not-found",
            }
        )
    proof = _terminal_proof(
        family_id=family_id,
        operator="pointer-walk-loop",
        suggestion_kind="pointer-walk-indexed-shape",
        blocker=blocker,
        reason=reason,
        exhausted_dimensions=exhausted_dimensions,
    )
    return [], proof, exhausted_dimensions


def _pointer_walk_member_array_probes(
    source: str,
    loop: Mapping[str, Any],
    *,
    family_id: str,
    start_index: int,
) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    counter = str(loop["counter"])
    body_start = int(loop["body_start"])
    body_end = int(loop["body_end"])
    body = source[body_start:body_end]
    table_expr = _index_table_expr_pattern(counter)
    jobjs_re = re.compile(
        rf"\b(?P<data>[A-Za-z_]\w*)\s*->\s*jobjs\s*\[\s*(?P<table>{table_expr})\s*\]"
    )
    member_re = re.compile(
        rf"\b(?P<data>[A-Za-z_]\w*)\s*->\s*x0\s*\[\s*(?P<index>{_counter_plus_two_pattern(counter)})\s*\]"
    )

    jobjs_match = jobjs_re.search(body)
    if jobjs_match is not None:
        stmt_start, stmt_end = _line_bounds_for_offset(
            source,
            body_start + jobjs_match.start(),
        )
        line = source[stmt_start:stmt_end]
        rel_table_start = body_start + jobjs_match.start("table") - stmt_start
        rel_table_end = body_start + jobjs_match.end("table") - stmt_start
        indent = re.match(r"[ \t]*", line).group(0)
        lines = list(_line_range_char(source, stmt_start, stmt_end))
        index_name = f"ll_probe_jobj_index_{start_index}"
        table_name = f"ll_probe_index_table_{start_index}"
        table_source = jobjs_match.group("table")
        probes.append(
            LifetimeLayoutProbe(
                label=f"pointer-walk-member-index-temp-{start_index}",
                operator="pointer-walk-loop",
                description="Name the mnVibration index table result before jobj lookup.",
                source_text=_replace_char_slice(
                    source,
                    stmt_start,
                    stmt_end,
                    (
                        f"{indent}u16 {index_name} = {table_source};\n"
                        f"{line[:rel_table_start]}{index_name}{line[rel_table_end:]}"
                    ),
                ),
                provenance={
                    "kind": "control-flow-shape",
                    "operator": "pointer-walk-loop",
                    "family_id": family_id,
                    "suggestion_kind": "pointer-walk-indexed-shape",
                    "variant": "member-index-temp",
                    "counter": counter,
                    "anchors": ["mnVibration_804D4FE8", "jobjs"],
                    "source_lines": lines,
                },
            )
        )
        table_start = body_start + jobjs_match.start("table")
        table_end = body_start + jobjs_match.end("table")
        table_line_start = source.find("mnVibration_804D4FE8", table_start, table_end)
        if table_line_start >= 0:
            table_line_end = table_line_start + len("mnVibration_804D4FE8")
            rel_name_start = table_line_start - stmt_start
            rel_name_end = table_line_end - stmt_start
            probes.append(
                LifetimeLayoutProbe(
                    label=f"pointer-walk-member-index-table-{start_index}",
                    operator="pointer-walk-loop",
                    description="Alias the mnVibration index table before jobj lookup.",
                    source_text=_replace_char_slice(
                        source,
                        stmt_start,
                        stmt_end,
                        (
                            f"{indent}u16* {table_name} = mnVibration_804D4FE8;\n"
                            f"{line[:rel_name_start]}{table_name}{line[rel_name_end:]}"
                        ),
                    ),
                    provenance={
                        "kind": "control-flow-shape",
                        "operator": "pointer-walk-loop",
                        "family_id": family_id,
                        "suggestion_kind": "pointer-walk-indexed-shape",
                        "variant": "member-index-table",
                        "counter": counter,
                        "anchors": ["mnVibration_804D4FE8", "jobjs"],
                        "source_lines": lines,
                    },
                )
            )

    member_match = member_re.search(body)
    if member_match is not None:
        stmt_start, stmt_end = _line_bounds_for_offset(
            source,
            body_start + member_match.start(),
        )
        line = source[stmt_start:stmt_end]
        expr_start = body_start + member_match.start() - stmt_start
        expr_end = body_start + member_match.end() - stmt_start
        indent = re.match(r"[ \t]*", line).group(0)
        data_name = member_match.group("data")
        expr = member_match.group(0)
        lines = list(_line_range_char(source, stmt_start, stmt_end))
        value_name = f"ll_probe_member_value_{start_index}"
        probes.append(
            LifetimeLayoutProbe(
                label=f"pointer-walk-member-array-value-temp-{start_index}",
                operator="pointer-walk-loop",
                description="Name the member-array value before its use.",
                source_text=_replace_char_slice(
                    source,
                    stmt_start,
                    stmt_end,
                    (
                        f"{indent}u8 {value_name} = {expr};\n"
                        f"{line[:expr_start]}{value_name}{line[expr_end:]}"
                    ),
                ),
                provenance={
                    "kind": "control-flow-shape",
                    "operator": "pointer-walk-loop",
                    "family_id": family_id,
                    "suggestion_kind": "pointer-walk-indexed-shape",
                    "variant": "member-array-value-temp",
                    "counter": counter,
                    "anchors": [f"{data_name}->x0"],
                    "source_lines": lines,
                },
            )
        )
        raw_expr = f"((u8*) {data_name})[(u8) {counter} + 2]"
        probes.append(
            LifetimeLayoutProbe(
                label=f"pointer-walk-member-array-byte-base-{start_index}",
                operator="pointer-walk-loop",
                description="Spell the member-array access through a raw byte base.",
                source_text=_replace_char_slice(
                    source,
                    stmt_start + expr_start,
                    stmt_start + expr_end,
                    raw_expr,
                ),
                provenance={
                    "kind": "control-flow-shape",
                    "operator": "pointer-walk-loop",
                    "family_id": family_id,
                    "suggestion_kind": "pointer-walk-indexed-shape",
                    "variant": "member-array-byte-base",
                    "counter": counter,
                    "anchors": [f"{data_name}->x0"],
                    "source_lines": lines,
                },
            )
        )
    return probes


def _pointer_walk_index_table_probes(
    source: str,
    function: str,
    *,
    family_id: str,
    start_index: int,
    max_probes: int,
) -> tuple[list[LifetimeLayoutProbe], list[dict[str, Any]], bool]:
    probes: list[LifetimeLayoutProbe] = []
    exhausted_dimensions: list[dict[str, Any]] = []
    regions = _pointer_walk_source_regions(source, function)
    if not regions:
        exhausted_dimensions.append(
            {
                "dimension_id": "source-owner-region",
                "reason": "source-owner-region-not-found",
            }
        )
        return [], exhausted_dimensions, False

    anchors: list[_IndexTablePointerWalkAnchor] = []
    for region in regions:
        region_anchors, region_dimensions = (
            _iter_u8_index_table_pointer_walk_anchors(source, region)
        )
        anchors.extend(region_anchors)
        exhausted_dimensions.extend(region_dimensions)

    if not anchors:
        if not exhausted_dimensions:
            exhausted_dimensions.append(
                {
                    "dimension_id": "u8-index-table-anchor",
                    "reason": "u8-index-table-anchor-not-found",
                }
            )
        return [], exhausted_dimensions, bool(exhausted_dimensions)

    seen: set[tuple[int, int, str]] = set()
    for anchor in anchors:
        for variant, probe in _index_table_anchor_probes(
            source,
            anchor,
            family_id=family_id,
            start_index=start_index + len(probes),
        ):
            key = (anchor.span_start, anchor.span_end, variant)
            if key in seen:
                continue
            seen.add(key)
            if probe.source_text == source:
                continue
            probes.append(probe)
            if len(probes) >= max_probes:
                return probes, exhausted_dimensions, True

    if not probes:
        exhausted_dimensions.append(
            {
                "dimension_id": "u8-index-table-anchor",
                "reason": "u8-index-table-probes-would-be-noop",
            }
        )
    return probes, exhausted_dimensions, True


def _pointer_walk_source_regions(
    source: str,
    function: str,
) -> list[_PointerWalkSourceRegion]:
    try:
        parser = tree_sitter_c.get_parser()
        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)
    except Exception:
        return []

    target_node = find_function_definition(tree.root_node, source_bytes, function)
    if target_node is None:
        return []
    target_region = _region_from_function_definition(
        source,
        source_bytes,
        target_node,
        owner_function=function,
        owner_kind="target-function",
    )
    if target_region is None:
        return []

    regions = [target_region]
    target_body = source[target_region.body_start:target_region.body_end]
    target_code = _mask_c_non_code_text(target_body)
    added_helpers: set[str] = set()
    for node in _walk_nodes(tree.root_node, {"function_definition"}):
        helper_name = _function_definition_name(source_bytes, node)
        if (
            helper_name is None
            or helper_name == function
            or helper_name in added_helpers
        ):
            continue
        helper_region = _region_from_function_definition(
            source,
            source_bytes,
            node,
            owner_function=helper_name,
            owner_kind="static-inline-helper",
        )
        if helper_region is None or not _function_definition_is_static_inline(
            source,
            helper_region,
        ):
            continue
        if not re.search(rf"\b{re.escape(helper_name)}\s*\(", target_code):
            continue
        regions.append(helper_region)
        added_helpers.add(helper_name)
    return regions


def _region_from_function_definition(
    source: str,
    source_bytes: bytes,
    node: Any,
    *,
    owner_function: str,
    owner_kind: str,
) -> _PointerWalkSourceRegion | None:
    body = node.child_by_field_name("body")
    if body is None:
        for child in node.children:
            if child.type == "compound_statement":
                body = child
                break
    if body is None:
        return None
    function_start = _byte_to_char_range(source, node.start_byte, node.start_byte)[0]
    body_start, body_end = _byte_to_char_range(source, body.start_byte, body.end_byte)
    body_text = source[body_start:body_end]
    open_rel = body_text.find("{")
    close_rel = body_text.rfind("}")
    if open_rel < 0 or close_rel <= open_rel:
        return None
    open_brace = body_start + open_rel
    close_brace = body_start + close_rel
    return _PointerWalkSourceRegion(
        owner_function=owner_function,
        owner_kind=owner_kind,
        function_start=function_start,
        body_start=open_brace + 1,
        body_end=close_brace,
        source_lines=_line_range_char(source, function_start, close_brace + 1),
    )


def _function_definition_name(source_bytes: bytes, node: Any) -> str | None:
    declarator = node.child_by_field_name("declarator")
    while declarator is not None:
        if declarator.type == "identifier":
            return node_text(source_bytes, declarator).strip()
        child = declarator.child_by_field_name("declarator")
        if child is not None:
            declarator = child
            continue
        for candidate in declarator.children:
            if candidate.type == "identifier":
                return node_text(source_bytes, candidate).strip()
        return None
    return None


def _function_definition_is_static_inline(
    source: str,
    region: _PointerWalkSourceRegion,
) -> bool:
    header = _mask_c_non_code_text(source[region.function_start:region.body_start])
    return bool(re.search(r"\bstatic\b", header) and re.search(r"\binline\b", header))


def _iter_u8_index_table_pointer_walk_anchors(
    source: str,
    region: _PointerWalkSourceRegion,
) -> tuple[list[_IndexTablePointerWalkAnchor], list[dict[str, Any]]]:
    u8_ptrs = _u8_pointer_locals(source, region)
    anchors: list[_IndexTablePointerWalkAnchor] = []
    exhausted_dimensions: list[dict[str, Any]] = []
    seen_spans: set[tuple[int, int, str]] = set()

    for anchor in _direct_u8_index_table_anchors(
        source,
        region,
        u8_ptrs,
        exhausted_dimensions,
    ):
        key = (anchor.span_start, anchor.span_end, anchor.anchor_kind)
        if key not in seen_spans:
            seen_spans.add(key)
            anchors.append(anchor)

    for anchor in _pointer_chain_u8_index_table_anchors(
        source,
        region,
        u8_ptrs,
        exhausted_dimensions,
    ):
        key = (anchor.span_start, anchor.span_end, anchor.anchor_kind)
        if key not in seen_spans:
            seen_spans.add(key)
            anchors.append(anchor)

    return anchors, exhausted_dimensions


def _u8_pointer_locals(
    source: str,
    region: _PointerWalkSourceRegion,
) -> dict[str, str]:
    text = source[region.function_start:region.body_end]
    code = _mask_c_non_code_text(text)
    pattern = re.compile(
        rf"\b(?P<type>(?:const\s+)?(?:u8|unsigned\s+char)(?:\s+const)?)"
        rf"\s*\*\s*(?P<name>{_IDENT})\b"
    )
    pointers: dict[str, str] = {}
    for match in pattern.finditer(code):
        pointer_type = "unsigned char*" if "unsigned" in match.group("type") else "u8*"
        pointers.setdefault(match.group("name"), pointer_type)
    return pointers


def _direct_u8_index_table_anchors(
    source: str,
    region: _PointerWalkSourceRegion,
    u8_ptrs: Mapping[str, str],
    exhausted_dimensions: list[dict[str, Any]],
) -> list[_IndexTablePointerWalkAnchor]:
    body = source[region.body_start:region.body_end]
    code = _mask_c_non_code_text(body)
    anchors: list[_IndexTablePointerWalkAnchor] = []
    array_re = re.compile(
        rf"\b(?P<base>{_IDENT})\s*\[\s*(?P<index>[^\]\n;]+?)\s*\]"
    )
    for match in array_re.finditer(code):
        base = match.group("base")
        index_text = source[
            region.body_start + match.start("index"):
            region.body_start + match.end("index")
        ].strip()
        span_start = region.body_start + match.start()
        span_end = region.body_start + match.end()
        stmt_start, stmt_end = _line_bounds_for_offset(source, span_start)
        source_lines = _line_range_char(source, stmt_start, stmt_end)
        if _inline_control_flow_prefix(source, stmt_start, span_start):
            _append_index_table_rejection(
                exhausted_dimensions,
                "inline-control-flow-statement",
                "inline-control-flow-statement",
                region,
                source_lines,
                base_expr=base,
                index_expr=index_text,
            )
            continue
        if _index_table_ref_is_write_target(source, span_start, span_end):
            _append_index_table_rejection(
                exhausted_dimensions,
                "write-target",
                "write-target",
                region,
                source_lines,
                base_expr=base,
                index_expr=index_text,
            )
            continue
        split = _split_index_expr_with_offset(index_text)
        if split is None:
            reason = _index_table_rejection_reason(index_text)
            if reason not in {"constant-offset-only", "byte-offset-not-found"}:
                _append_index_table_rejection(
                    exhausted_dimensions,
                    reason,
                    reason,
                    region,
                    source_lines,
                    base_expr=base,
                    index_expr=index_text,
                )
            continue
        index_expr, byte_offset = split
        if base not in u8_ptrs:
            _append_index_table_rejection(
                exhausted_dimensions,
                "unsafe-non-u8-base",
                "unsafe-non-u8-base",
                region,
                source_lines,
                base_expr=base,
                index_expr=index_text,
            )
            continue
        if not _safe_index_table_index_expr(index_expr):
            _append_index_table_rejection(
                exhausted_dimensions,
                "unsafe-index-expression",
                "unsafe-index-expression",
                region,
                source_lines,
                base_expr=base,
                index_expr=index_expr,
            )
            continue
        anchors.append(
            _make_index_table_anchor(
                region,
                anchor_kind="u8-index-table-direct-load",
                span_start=span_start,
                span_end=span_end,
                statement_start=stmt_start,
                statement_end=stmt_end,
                indent=_line_indent_char(source, stmt_start),
                base_expr=base,
                base_local=base,
                pointer_local=None,
                index_expr=index_expr,
                byte_offset=byte_offset,
                element_type=u8_ptrs[base],
                source_lines=source_lines,
            )
        )

    deref_re = re.compile(r"\*\s*\(\s*(?P<expr>[^;\n()]+?)\s*\)")
    for match in deref_re.finditer(code):
        expr_text = source[
            region.body_start + match.start("expr"):
            region.body_start + match.end("expr")
        ].strip()
        parsed = _parse_pointer_sum_index_table_expr(expr_text, u8_ptrs)
        span_start = region.body_start + match.start()
        span_end = region.body_start + match.end()
        stmt_start, stmt_end = _line_bounds_for_offset(source, span_start)
        source_lines = _line_range_char(source, stmt_start, stmt_end)
        if _inline_control_flow_prefix(source, stmt_start, span_start):
            _append_index_table_rejection(
                exhausted_dimensions,
                "inline-control-flow-statement",
                "inline-control-flow-statement",
                region,
                source_lines,
                index_expr=expr_text,
            )
            continue
        if _index_table_ref_is_write_target(source, span_start, span_end):
            _append_index_table_rejection(
                exhausted_dimensions,
                "write-target",
                "write-target",
                region,
                source_lines,
                index_expr=expr_text,
            )
            continue
        if parsed is None:
            if "++" in expr_text or "--" in expr_text or re.search(
                rf"\b{_IDENT}\s*\(",
                _remove_integer_casts(expr_text),
            ):
                _append_index_table_rejection(
                    exhausted_dimensions,
                    "unsafe-index-expression",
                    "unsafe-index-expression",
                    region,
                    source_lines,
                    index_expr=expr_text,
                )
            continue
        base, index_expr, byte_offset = parsed
        anchors.append(
            _make_index_table_anchor(
                region,
                anchor_kind="u8-index-table-direct-load",
                span_start=span_start,
                span_end=span_end,
                statement_start=stmt_start,
                statement_end=stmt_end,
                indent=_line_indent_char(source, stmt_start),
                base_expr=base,
                base_local=base,
                pointer_local=None,
                index_expr=index_expr,
                byte_offset=byte_offset,
                element_type=u8_ptrs[base],
                source_lines=source_lines,
            )
        )
    return anchors


def _pointer_chain_u8_index_table_anchors(
    source: str,
    region: _PointerWalkSourceRegion,
    u8_ptrs: Mapping[str, str],
    exhausted_dimensions: list[dict[str, Any]],
) -> list[_IndexTablePointerWalkAnchor]:
    body = source[region.body_start:region.body_end]
    code = _mask_c_non_code_text(body)
    statement_re = re.compile(r"(?m)^(?P<indent>[ \t]*)(?P<statement>[^;\n{}]*;)")
    states: dict[str, _PointerWalkState] = {}
    anchors: list[_IndexTablePointerWalkAnchor] = []
    last_statement_end = region.body_start

    for match in statement_re.finditer(code):
        stmt_start = region.body_start + match.start()
        stmt_end = region.body_start + match.end("statement")
        if _pointer_state_gap_is_unsafe(source[last_statement_end:stmt_start]):
            states.clear()
        statement = source[stmt_start:stmt_end]
        source_lines = _line_range_char(source, stmt_start, stmt_end)
        indent = match.group("indent")

        anchors.extend(
            _pointer_load_anchors_from_statement(
                source,
                region,
                statement,
                stmt_start,
                stmt_end,
                indent,
                source_lines,
                states,
                u8_ptrs,
                exhausted_dimensions,
            )
        )

        for pointer in tuple(states):
            if re.search(
                rf"(?:\+\+|--)\s*{re.escape(pointer)}\b|"
                rf"\b{re.escape(pointer)}\b\s*(?:\+\+|--)",
                statement,
            ):
                states.pop(pointer, None)

        assign = re.fullmatch(
            rf"\s*(?P<lhs>{_IDENT})\s*=\s*(?P<rhs>.+?)\s*;\s*",
            statement,
        )
        add_assign = re.fullmatch(
            rf"\s*(?P<lhs>{_IDENT})\s*\+=\s*(?P<rhs>.+?)\s*;\s*",
            statement,
        )
        if assign is None and add_assign is None:
            if _pointer_state_statement_is_unsafe(statement):
                states.clear()
            last_statement_end = stmt_end
            continue
        lhs = (assign or add_assign).group("lhs")
        rhs = (assign or add_assign).group("rhs").strip()
        if lhs not in u8_ptrs:
            if _pointer_state_statement_is_unsafe(statement):
                states.clear()
            last_statement_end = stmt_end
            continue

        previous = states.get(lhs)
        added_expr = None
        if add_assign is not None:
            added_expr = rhs
        elif assign is not None:
            added_expr = _self_pointer_addend(lhs, rhs)
        if (
            previous is not None
            and added_expr is not None
            and _is_integer_constant_expression(added_expr)
            and previous.index_expr
            and _safe_index_table_index_expr(previous.index_expr)
            and source[previous.assignment_end:stmt_start].strip() == ""
        ):
            total_offset = _combine_byte_offsets(previous.byte_offset, added_expr)
            anchors.append(
                _make_index_table_anchor(
                    region,
                    anchor_kind="u8-index-table-pointer-offset-chain",
                    span_start=previous.assignment_start,
                    span_end=stmt_end,
                    statement_start=previous.assignment_start,
                    statement_end=stmt_end,
                    indent=previous.indent,
                    base_expr=previous.base_local,
                    base_local=previous.base_local,
                    pointer_local=lhs,
                    index_expr=previous.index_expr,
                    byte_offset=total_offset,
                    element_type=u8_ptrs[previous.base_local],
                    source_lines=_line_range_char(
                        source,
                        previous.assignment_start,
                        stmt_end,
                    ),
                )
            )

        new_state = _updated_pointer_walk_state(
            lhs=lhs,
            rhs=f"{lhs} + {rhs}" if add_assign is not None else rhs,
            statement_start=stmt_start,
            statement_end=stmt_end,
            indent=indent,
            states=states,
            u8_ptrs=u8_ptrs,
        )
        if new_state is None:
            states.pop(lhs, None)
        else:
            states[lhs] = new_state
        if _pointer_state_statement_is_unsafe(statement):
            states.clear()
        last_statement_end = stmt_end
    return anchors


def _pointer_load_anchors_from_statement(
    source: str,
    region: _PointerWalkSourceRegion,
    statement: str,
    stmt_start: int,
    stmt_end: int,
    indent: str,
    source_lines: tuple[int, int],
    states: Mapping[str, _PointerWalkState],
    u8_ptrs: Mapping[str, str],
    exhausted_dimensions: list[dict[str, Any]],
) -> list[_IndexTablePointerWalkAnchor]:
    anchors: list[_IndexTablePointerWalkAnchor] = []
    load_re = re.compile(
        rf"\b(?P<pointer>{_IDENT})\s*\[\s*(?P<offset>[^\]\n;]+?)\s*\]"
    )
    for match in load_re.finditer(_mask_c_non_code_text(statement)):
        pointer = match.group("pointer")
        offset_expr = statement[match.start("offset"):match.end("offset")].strip()
        span_start = stmt_start + match.start()
        span_end = stmt_start + match.end()
        if pointer not in u8_ptrs:
            continue
        if _inline_control_flow_prefix(source, stmt_start, span_start):
            _append_index_table_rejection(
                exhausted_dimensions,
                "inline-control-flow-statement",
                "inline-control-flow-statement",
                region,
                source_lines,
                base_expr=pointer,
                index_expr=offset_expr,
            )
            continue
        if _index_table_ref_is_write_target(source, span_start, span_end):
            _append_index_table_rejection(
                exhausted_dimensions,
                "write-target",
                "write-target",
                region,
                source_lines,
                base_expr=pointer,
                index_expr=offset_expr,
            )
            continue
        state = states.get(pointer)
        if not _is_integer_constant_expression(offset_expr):
            if re.search(rf"\b{_IDENT}\s*\(", _remove_integer_casts(offset_expr)):
                _append_index_table_rejection(
                    exhausted_dimensions,
                    "unsafe-index-expression",
                    "unsafe-index-expression",
                    region,
                    source_lines,
                    base_expr=pointer,
                    index_expr=offset_expr,
                )
            continue
        if state is None or not state.index_expr:
            continue
        if not _safe_index_table_index_expr(state.index_expr):
            _append_index_table_rejection(
                exhausted_dimensions,
                "unsafe-index-expression",
                "unsafe-index-expression",
                region,
                source_lines,
                base_expr=state.base_local,
                index_expr=state.index_expr,
            )
            continue
        byte_offset = _combine_byte_offsets(state.byte_offset, offset_expr)
        anchor_kind = (
            "u8-index-table-helper-return"
            if region.owner_kind == "static-inline-helper"
            and statement.lstrip().startswith("return ")
            else "u8-index-table-pointer-offset-chain"
        )
        anchors.append(
            _make_index_table_anchor(
                region,
                anchor_kind=anchor_kind,
                span_start=span_start,
                span_end=span_end,
                statement_start=stmt_start,
                statement_end=stmt_end,
                indent=indent,
                base_expr=state.base_local,
                base_local=state.base_local,
                pointer_local=pointer,
                index_expr=state.index_expr,
                byte_offset=byte_offset,
                element_type=u8_ptrs[state.base_local],
                source_lines=source_lines,
            )
        )
    return anchors


def _updated_pointer_walk_state(
    *,
    lhs: str,
    rhs: str,
    statement_start: int,
    statement_end: int,
    indent: str,
    states: Mapping[str, _PointerWalkState],
    u8_ptrs: Mapping[str, str],
) -> _PointerWalkState | None:
    rhs = _strip_outer_parens(rhs.strip())
    if rhs in u8_ptrs:
        existing = states.get(rhs)
        if existing is not None:
            return _PointerWalkState(
                base_local=existing.base_local,
                index_expr=existing.index_expr,
                byte_offset=existing.byte_offset,
                assignment_start=statement_start,
                assignment_end=statement_end,
                indent=indent,
            )
        return _PointerWalkState(
            base_local=rhs,
            index_expr="",
            byte_offset=None,
            assignment_start=statement_start,
            assignment_end=statement_end,
            indent=indent,
        )

    operands = _split_top_level_plus_operands(rhs)
    if len(operands) < 2:
        return None
    pointer_operand = next(
        (operand for operand in operands if _strip_outer_parens(operand) in u8_ptrs),
        None,
    )
    if pointer_operand is None:
        return None
    pointer_name = _strip_outer_parens(pointer_operand)
    base_state = states.get(pointer_name)
    base_local = base_state.base_local if base_state is not None else pointer_name
    if base_local not in u8_ptrs:
        return None
    index_expr = base_state.index_expr if base_state is not None else ""
    byte_offset = base_state.byte_offset if base_state is not None else None

    for operand in operands:
        operand = operand.strip()
        if _strip_outer_parens(operand) == pointer_name:
            continue
        if _is_integer_constant_expression(operand):
            byte_offset = _combine_byte_offsets(byte_offset, operand)
            continue
        if not _safe_index_table_index_expr(operand):
            return None
        index_expr = _combine_index_expr(index_expr, operand)
    return _PointerWalkState(
        base_local=base_local,
        index_expr=index_expr,
        byte_offset=byte_offset,
        assignment_start=statement_start,
        assignment_end=statement_end,
        indent=indent,
    )


def _self_pointer_addend(pointer: str, rhs: str) -> str | None:
    operands = _split_top_level_plus_operands(rhs)
    if len(operands) != 2:
        return None
    left, right = (_strip_outer_parens(operand) for operand in operands)
    if left == pointer:
        return operands[1].strip()
    if right == pointer:
        return operands[0].strip()
    return None


def _make_index_table_anchor(
    region: _PointerWalkSourceRegion,
    *,
    anchor_kind: str,
    span_start: int,
    span_end: int,
    statement_start: int,
    statement_end: int,
    indent: str,
    base_expr: str,
    base_local: str,
    pointer_local: str | None,
    index_expr: str,
    byte_offset: str,
    element_type: str,
    source_lines: tuple[int, int],
) -> _IndexTablePointerWalkAnchor:
    return _IndexTablePointerWalkAnchor(
        owner_function=region.owner_function,
        owner_kind=region.owner_kind,
        anchor_kind=anchor_kind,
        span_start=span_start,
        span_end=span_end,
        statement_start=statement_start,
        statement_end=statement_end,
        indent=indent,
        base_expr=base_expr,
        base_local=base_local,
        pointer_local=pointer_local,
        index_expr=index_expr,
        byte_offset=byte_offset,
        element_type=element_type,
        source_lines=source_lines,
        source_regions=(
            {
                "owner_function": region.owner_function,
                "owner_kind": region.owner_kind,
                "source_lines": list(region.source_lines),
            },
        ),
    )


def _index_table_anchor_probes(
    source: str,
    anchor: _IndexTablePointerWalkAnchor,
    *,
    family_id: str,
    start_index: int,
) -> list[tuple[str, LifetimeLayoutProbe]]:
    if (
        anchor.anchor_kind == "u8-index-table-pointer-offset-chain"
        and anchor.span_start == anchor.statement_start
    ):
        return _index_table_pointer_owner_split_probe(
            source,
            anchor,
            family_id=family_id,
            start_index=start_index,
        )

    probes: list[tuple[str, LifetimeLayoutProbe]] = []
    direct_expr = _index_table_direct_expr(anchor)
    if direct_expr is not None:
        probes.append(
            (
                "index-table-direct-index-load",
                _index_table_probe(
                    source,
                    anchor,
                    family_id=family_id,
                    start_index=start_index + len(probes),
                    variant="index-table-direct-index-load",
                    description=(
                        "Spell the byte-table load as a direct base/index/offset load."
                    ),
                    source_text=_replace_char_slice(
                        source,
                        anchor.span_start,
                        anchor.span_end,
                        direct_expr,
                    ),
                ),
            )
        )

    alias_name = f"ll_probe_{_safe_probe_name(anchor.base_local)}_offset_base_{start_index}"
    alias_expr = f"{alias_name}[{anchor.index_expr}]"
    probes.append(
        (
            "index-table-offset-base-alias",
            _index_table_probe(
                source,
                anchor,
                family_id=family_id,
                start_index=start_index + len(probes),
                variant="index-table-offset-base-alias",
                description="Alias the byte-offset table base before the load.",
                source_text=_replace_statement_with_probe_prefix(
                    source,
                    anchor,
                    (
                        f"{anchor.indent}{anchor.element_type} {alias_name};\n"
                        f"{anchor.indent}{alias_name} = "
                        f"{anchor.base_expr} + {anchor.byte_offset};\n"
                    ),
                    alias_expr,
                ),
            ),
        )
    )

    index_name = f"ll_probe_{_safe_probe_name(anchor.base_local)}_index_{start_index}"
    probes.append(
        (
            "index-table-index-temp",
            _index_table_probe(
                source,
                anchor,
                family_id=family_id,
                start_index=start_index + len(probes),
                variant="index-table-index-temp",
                description="Name the combined byte-table index before the load.",
                source_text=_replace_statement_with_probe_prefix(
                    source,
                    anchor,
                    (
                        f"{anchor.indent}int {index_name};\n"
                        f"{anchor.indent}{index_name} = "
                        f"{_combine_index_offset(anchor.index_expr, anchor.byte_offset)};\n"
                    ),
                    f"{anchor.base_expr}[{index_name}]",
                ),
            ),
        )
    )
    return probes


def _index_table_pointer_owner_split_probe(
    source: str,
    anchor: _IndexTablePointerWalkAnchor,
    *,
    family_id: str,
    start_index: int,
) -> list[tuple[str, LifetimeLayoutProbe]]:
    if not anchor.pointer_local:
        return []
    replacement = (
        f"{anchor.indent}{anchor.pointer_local} = {anchor.base_expr} + "
        f"{_combine_index_offset(anchor.index_expr, anchor.byte_offset)};"
    )
    if anchor.statement_end > anchor.span_end:
        replacement += source[anchor.span_end:anchor.statement_end]
    source_text = _replace_char_slice(
        source,
        anchor.span_start,
        anchor.statement_end,
        replacement,
    )
    return [
        (
            "index-table-pointer-owner-split",
            _index_table_probe(
                source,
                anchor,
                family_id=family_id,
                start_index=start_index,
                variant="index-table-pointer-owner-split",
                description="Split byte-table offset ownership from the cursor index.",
                source_text=source_text,
            ),
        )
    ]


def _index_table_probe(
    source: str,
    anchor: _IndexTablePointerWalkAnchor,
    *,
    family_id: str,
    start_index: int,
    variant: str,
    description: str,
    source_text: str,
) -> LifetimeLayoutProbe:
    label_variant = variant
    if label_variant.startswith("index-table-"):
        label_variant = label_variant[len("index-table-") :]
    return LifetimeLayoutProbe(
        label=f"pointer-walk-index-table-{label_variant.replace('_', '-')}-{start_index}",
        operator="pointer-walk-loop",
        description=description,
        source_text=source_text,
        provenance={
            "kind": "control-flow-shape",
            "operator": "pointer-walk-loop",
            "family_id": family_id,
            "suggestion_kind": "pointer-walk-indexed-shape",
            "variant": variant,
            "base_expr": anchor.base_expr,
            "base_local": anchor.base_local,
            "pointer_local": anchor.pointer_local,
            "index_expr": anchor.index_expr,
            "byte_offset": anchor.byte_offset,
            "element_type": anchor.element_type,
            "owner_function": anchor.owner_function,
            "owner_kind": anchor.owner_kind,
            "anchors": ["u8-index-table"],
            "anchor_kind": anchor.anchor_kind,
            "source_lines": list(anchor.source_lines),
            "source_regions": [dict(item) for item in anchor.source_regions],
        },
    )


def _replace_statement_with_probe_prefix(
    source: str,
    anchor: _IndexTablePointerWalkAnchor,
    prefix: str,
    replacement_expr: str,
) -> str:
    statement = source[anchor.statement_start:anchor.statement_end]
    rel_start = anchor.span_start - anchor.statement_start
    rel_end = anchor.span_end - anchor.statement_start
    replacement_statement = (
        statement[:rel_start] + replacement_expr + statement[rel_end:]
    )
    return _replace_char_slice(
        source,
        anchor.statement_start,
        anchor.statement_end,
        prefix + replacement_statement,
    )


def _index_table_direct_expr(anchor: _IndexTablePointerWalkAnchor) -> str | None:
    if not anchor.index_expr:
        return None
    return f"{anchor.base_expr}[{_combine_index_offset(anchor.index_expr, anchor.byte_offset)}]"


def _append_index_table_rejection(
    exhausted_dimensions: list[dict[str, Any]],
    dimension_id: str,
    reason: str,
    region: _PointerWalkSourceRegion,
    source_lines: tuple[int, int],
    *,
    base_expr: str | None = None,
    index_expr: str | None = None,
) -> None:
    item: dict[str, Any] = {
        "dimension_id": dimension_id,
        "reason": reason,
        "owner_function": region.owner_function,
        "owner_kind": region.owner_kind,
        "source_lines": list(source_lines),
    }
    if base_expr:
        item["base_expr"] = base_expr
    if index_expr:
        item["index_expr"] = index_expr
    if item not in exhausted_dimensions:
        exhausted_dimensions.append(item)


def _index_table_rejection_reason(index_expr: str) -> str:
    stripped = index_expr.strip()
    if _is_integer_constant_expression(stripped):
        return "constant-offset-only"
    without_casts = _remove_integer_casts(stripped)
    if (
        "++" in stripped
        or "--" in stripped
        or "?" in stripped
        or ":" in stripped
        or "," in stripped
        or "[" in stripped
        or "]" in stripped
        or _ASSIGNMENT_TOKEN_RE.search(stripped)
        or re.search(rf"\b{_IDENT}\s*\(", without_casts)
    ):
        return "unsafe-index-expression"
    if re.search(r"[+\-]", stripped):
        return "nonconstant-byte-offset"
    if re.fullmatch(r"(?:\([^()]*\)\s*)?[A-Za-z_]\w*", stripped):
        return "byte-offset-not-found"
    return "unsafe-index-expression"


def _inline_control_flow_prefix(source: str, statement_start: int, span_start: int) -> bool:
    prefix = _mask_c_non_code_text(source[statement_start:span_start])
    return bool(
        re.search(
            r"\b(?:if|else|while|for|do|switch)\b|"
            r"\b(?:return|goto|break|continue)\b.*\S",
            prefix,
        )
    )


def _pointer_state_gap_is_unsafe(gap: str) -> bool:
    code = _mask_c_non_code_text(gap)
    stripped = code.strip()
    if not stripped:
        return False
    if re.search(r"(?m)^[ \t]*(?!case\b|default\b)[A-Za-z_]\w*\s*:", code):
        return True
    if "{" in code or "}" in code:
        return True
    if re.search(r"\b(?:if|else|while|for|do|switch|goto|return|break|continue)\b", code):
        return True
    return True


def _pointer_state_statement_is_unsafe(statement: str) -> bool:
    code = _mask_c_non_code_text(statement)
    if re.search(r"\b(?:if|else|while|for|do|switch|goto|return|break|continue)\b", code):
        return True
    if re.search(rf"\b{_IDENT}\s*\(", _remove_integer_casts(code)):
        return True
    return False


def _split_index_expr_with_offset(index_expr: str) -> tuple[str, str] | None:
    index_expr = index_expr.strip()
    if _is_integer_constant_expression(index_expr):
        return None
    parts = _split_top_level_binary(index_expr, "+")
    if parts is None:
        parts = _split_top_level_binary(index_expr, "-")
        if parts is None:
            return None
        left, right = parts
        if not _is_integer_constant_expression(right):
            return None
        return left.strip(), f"-{_strip_integer_suffix(right.strip())}"
    left, right = parts
    if _is_integer_constant_expression(right):
        return left.strip(), _strip_integer_suffix(right.strip())
    if _is_integer_constant_expression(left):
        return right.strip(), _strip_integer_suffix(left.strip())
    return None


def _parse_pointer_sum_index_table_expr(
    expr: str,
    u8_ptrs: Mapping[str, str],
) -> tuple[str, str, str] | None:
    operands = _split_top_level_plus_operands(expr)
    if len(operands) < 3:
        return None
    base = next(
        (
            _strip_outer_parens(operand)
            for operand in operands
            if _strip_outer_parens(operand) in u8_ptrs
        ),
        None,
    )
    if base is None:
        return None
    constants = [
        _strip_integer_suffix(operand.strip())
        for operand in operands
        if _is_integer_constant_expression(operand)
    ]
    if len(constants) != 1:
        return None
    index_parts = [
        operand.strip()
        for operand in operands
        if _strip_outer_parens(operand) != base
        and not _is_integer_constant_expression(operand)
    ]
    if not index_parts:
        return None
    index_expr = " + ".join(index_parts)
    if not _safe_index_table_index_expr(index_expr):
        return None
    return base, index_expr, constants[0]


def _safe_index_table_index_expr(expr: str) -> bool:
    expr = expr.strip()
    if not expr:
        return False
    if not _balanced_delimiters(expr):
        return False
    if any(token in expr for token in ("++", "--", "?", ":", ",", "[", "]", "*")):
        return False
    if _ASSIGNMENT_TOKEN_RE.search(expr):
        return False
    without_casts = _remove_integer_casts(expr)
    if re.search(rf"\b{_IDENT}\s*\(", without_casts):
        return False
    if re.search(r"\b(?:sizeof|return|goto|break|continue)\b", without_casts):
        return False
    return re.fullmatch(r"[A-Za-z0-9_xXa-fA-F()+\-\s]+", without_casts) is not None


def _remove_integer_casts(expr: str) -> str:
    cast_type = (
        r"(?:u8|s8|u16|s16|u32|s32|u64|s64|int|char|short|long|"
        r"unsigned\s+char|unsigned\s+short|unsigned\s+int|unsigned\s+long|"
        r"signed\s+char|signed\s+short|signed\s+int|signed\s+long)"
    )
    previous = None
    stripped = expr
    while previous != stripped:
        previous = stripped
        stripped = re.sub(rf"\(\s*{cast_type}\s*\)\s*", "", stripped)
    return stripped


def _split_top_level_binary(expr: str, operator: str) -> tuple[str, str] | None:
    depth = 0
    for idx, char in enumerate(expr):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == operator and depth == 0 and idx > 0:
            if operator == "-" and expr[idx - 1] in "+-*/(":
                continue
            left = expr[:idx].strip()
            right = expr[idx + 1 :].strip()
            if left and right:
                return left, right
    return None


def _split_top_level_plus_operands(expr: str) -> list[str]:
    operands: list[str] = []
    depth = 0
    start = 0
    for idx, char in enumerate(expr):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "+" and depth == 0:
            operand = expr[start:idx].strip()
            if operand:
                operands.append(operand)
            start = idx + 1
    tail = expr[start:].strip()
    if tail:
        operands.append(tail)
    return operands


def _is_integer_constant_expression(expr: str) -> bool:
    return (
        re.fullmatch(
            r"-?(?:0[xX][0-9A-Fa-f]+|[0-9]+)(?:[uUlL]*)?",
            expr.strip(),
        )
        is not None
    )


def _strip_integer_suffix(expr: str) -> str:
    return re.sub(r"[uUlL]+$", "", expr.strip())


def _combine_byte_offsets(existing: str | None, added: str) -> str:
    if existing is None or not existing:
        return _strip_integer_suffix(added)
    existing_value = _integer_constant_value(existing)
    added_value = _integer_constant_value(added)
    if existing_value is None or added_value is None:
        return _strip_integer_suffix(added)
    combined = existing_value + added_value
    if combined < 0:
        return f"-0x{abs(combined):X}"
    return f"0x{combined:X}"


def _combine_index_expr(existing: str, added: str) -> str:
    if not existing:
        return added.strip()
    return f"{existing} + {added.strip()}"


def _combine_index_offset(index_expr: str, byte_offset: str) -> str:
    byte_offset = byte_offset.strip()
    if byte_offset.startswith("-"):
        return f"{index_expr} - {byte_offset[1:]}"
    return f"{index_expr} + {byte_offset}"


def _index_table_ref_is_write_target(
    source: str,
    span_start: int,
    span_end: int,
) -> bool:
    line_start = source.rfind("\n", 0, span_start) + 1
    before = source[line_start:span_start].rstrip()
    if before.endswith("++") or before.endswith("--"):
        return True
    rest = source[span_end:]
    stripped = rest.lstrip()
    if not stripped:
        return False
    return bool(
        re.match(
            r"(?:\)+\s*)?(?:\+\+|--|=|\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<=|>>=)(?!=)",
            stripped,
        )
    )


def _line_indent_char(source: str, offset: int) -> str:
    line_start = source.rfind("\n", 0, offset) + 1
    match = re.match(r"[ \t]*", source[line_start:offset])
    return match.group(0) if match is not None else ""


def _safe_probe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "index_table"


def _materialize_loop_init_family(
    source: str,
    function: str,
    *,
    family_id: str,
    max_probes: int,
) -> tuple[list[LifetimeLayoutProbe], dict[str, Any] | None, list[dict[str, Any]]]:
    probes: list[LifetimeLayoutProbe] = []
    exhausted_dimensions: list[dict[str, Any]] = []
    loop_seen = False
    for loop in _iter_simple_for_loops(source, function):
        loop_seen = True
        rejection = _safe_loop_rejection(loop)
        if rejection is not None:
            exhausted_dimensions.append(
                {
                    "dimension_id": f"loop@{loop['source_lines'][0]}",
                    "reason": rejection,
                    "source_lines": list(loop["source_lines"]),
                }
            )
            continue
        probes.extend(
            _loop_init_probes_for_loop(
                source,
                loop,
                family_id=family_id,
                start_index=len(probes),
            )
        )
        if len(probes) >= max_probes:
            break

    if probes:
        return probes[:max_probes], None, exhausted_dimensions

    if not loop_seen:
        exhausted_dimensions.append(
            {
                "dimension_id": "simple-counted-loop",
                "reason": "simple-counted-loop-not-found",
            }
        )
    blocker = (
        str(exhausted_dimensions[0]["reason"])
        if exhausted_dimensions
        else "simple-counted-loop-not-found"
    )
    proof = _terminal_proof(
        family_id=family_id,
        operator="loop-init",
        suggestion_kind="loop-peel-unroll",
        blocker=blocker,
        reason="no safe loop-init or loop-peel source variant matched",
        exhausted_dimensions=exhausted_dimensions,
    )
    return [], proof, exhausted_dimensions


def _loop_init_probes_for_loop(
    source: str,
    loop: Mapping[str, Any],
    *,
    family_id: str,
    start_index: int,
) -> list[LifetimeLayoutProbe]:
    if loop.get("decl_type"):
        return []
    counter = str(loop["counter"])
    init = str(loop["init"]).strip()
    if init != "0":
        return []
    header_start = int(loop["header_start"])
    header_end = int(loop["header_end"])
    header = source[header_start:header_end]
    init_match = re.search(
        rf"for\s*\(\s*{re.escape(counter)}\s*=\s*0\s*;",
        header,
    )
    if init_match is None:
        return []
    indent = str(loop["indent"])
    lines = list(loop["source_lines"])
    init_outside_header = (
        header[: init_match.start()]
        + f"{counter} = 0;\n{indent}for (;"
        + header[init_match.end():]
    )
    probes = [
        LifetimeLayoutProbe(
            label=f"loop-init-outside-for-{start_index}",
            operator="loop-init",
            description="Move the loop counter initialization before the for header.",
            source_text=_replace_char_slice(
                source,
                header_start,
                header_end,
                init_outside_header,
            ),
            provenance={
                "kind": "control-flow-shape",
                "operator": "loop-init",
                "family_id": family_id,
                "suggestion_kind": "loop-peel-unroll",
                "variant": "init-outside-for",
                "counter": counter,
                "source_lines": lines,
            },
        )
    ]

    loop_text = source[int(loop["loop_start"]): int(loop["loop_end"])]
    renamed = f"ll_probe_{counter}_{start_index}"
    renamed_loop = re.sub(rf"\b{re.escape(counter)}\b", renamed, loop_text)
    block = (
        f"{indent}{{\n"
        f"{indent}    s32 {renamed};\n"
        f"{_indent_block_lines(renamed_loop, indent)}"
        f"{indent}    {counter} = {renamed};\n"
        f"{indent}}}"
    )
    probes.append(
        LifetimeLayoutProbe(
            label=f"loop-init-renamed-counter-block-{start_index}",
            operator="loop-init",
            description="Use a renamed block-local counter for one counted loop.",
            source_text=_replace_char_slice(
                source,
                int(loop["loop_start"]),
                int(loop["loop_end"]),
                block,
            ),
            provenance={
                "kind": "control-flow-shape",
                "operator": "loop-init",
                "family_id": family_id,
                "suggestion_kind": "loop-peel-unroll",
                "variant": "renamed-counter-block",
                "counter": counter,
                "source_lines": lines,
            },
        )
    )
    return probes


def _function_body_span(source: str, function: str) -> tuple[int, int] | None:
    parsed = _parse_function(source, function)
    if parsed is None:
        return None
    source_bytes, function_node = parsed
    body = function_node.child_by_field_name("body")
    if body is None:
        for child in function_node.children:
            if child.type == "compound_statement":
                body = child
                break
    if body is None:
        return None
    body_start, body_end = _byte_to_char_range(source, body.start_byte, body.end_byte)
    open_brace = source.find("{", body_start, body_end)
    close_brace = source.rfind("}", body_start, body_end)
    if open_brace < 0 or close_brace <= open_brace:
        return None
    return open_brace + 1, close_brace


def _iter_simple_for_loops(source: str, function: str) -> list[dict[str, Any]]:
    span = _function_body_span(source, function)
    if span is None:
        return []
    body_start, body_end = span
    body = source[body_start:body_end]
    code_body = _mask_c_non_code_text(body)
    loop_re = re.compile(
        r"(?m)^(?P<indent>[ \t]*)for\s*\(\s*"
        r"(?:(?P<decl_type>int|s32)\s+)?"
        r"(?P<counter>[A-Za-z_]\w*)\s*=\s*(?P<init>[^;]+?)\s*;\s*"
        r"(?P<condition>(?P=counter)\s*<\s*(?P<bound>[^;]+?))\s*;\s*"
        r"(?P<increment>(?:(?P=counter)\s*\+\+|\+\+\s*(?P=counter)|"
        r"(?P=counter)\s*\+=\s*1))\s*"
        r"\)\s*\{"
    )
    loops: list[dict[str, Any]] = []
    for match in loop_re.finditer(code_body):
        loop_start = body_start + match.start()
        loop_open = body_start + match.end() - 1
        loop_close = _find_matching_brace_char(source, loop_open)
        if loop_close is None or loop_close > body_end:
            continue
        loop_end = loop_close + 1
        loop_body_start = loop_open + 1
        loop_body_end = loop_close
        loops.append(
            {
                "loop_start": loop_start,
                "loop_open": loop_open,
                "loop_close": loop_close,
                "loop_end": loop_end,
                "body_start": loop_body_start,
                "body_end": loop_body_end,
                "body": source[loop_body_start:loop_body_end],
                "header_start": loop_start,
                "header_end": loop_open + 1,
                "indent": match.group("indent"),
                "decl_type": match.group("decl_type"),
                "counter": match.group("counter"),
                "init": match.group("init"),
                "condition": match.group("condition"),
                "bound": match.group("bound").strip(),
                "increment": match.group("increment"),
                "source_lines": _line_range_char(source, loop_start, loop_end),
            }
        )
    return loops


def _first_standalone_call_statement(
    source: str,
    start: int,
    end: int,
    symbol: str,
) -> dict[str, Any] | None:
    region = source[start:end]
    code_region = _mask_c_non_code_text(region)
    call_re = re.compile(
        rf"(?m)^(?P<indent>[ \t]*)(?:\(void\)\s*)?"
        rf"(?P<expr>{re.escape(symbol)}\s*\((?P<args>[^;\n]*)\))\s*;"
    )
    match = call_re.search(code_region)
    if match is None:
        return None
    statement_start = start + match.start()
    statement_end = start + match.end()
    if statement_end < len(source) and source[statement_end] == "\n":
        statement_end += 1
    return {
        "symbol": symbol,
        "indent": match.group("indent"),
        "call_expr": source[start + match.start("expr"): start + match.end("expr")],
        "args": source[start + match.start("args"): start + match.end("args")],
        "statement_start": statement_start,
        "statement_end": statement_end,
        "tail_in_loop": source[statement_end:end],
    }


def _pointer_walk_loop_anchors(loop_body: str, counter: str) -> list[str]:
    code = _mask_c_non_code_text(loop_body)
    token = re.escape(counter)
    anchors: list[str] = []
    if re.search(
        rf"\b[A-Za-z_]\w*\s*->\s*x0\s*\[\s*{_counter_plus_two_pattern(counter)}\s*\]",
        code,
    ):
        anchors.append("member-array-x0")
    if re.search(
        rf"\b[A-Za-z_]\w*\s*->\s*jobjs\s*\[\s*{_index_table_expr_pattern(counter)}\s*\]",
        code,
    ):
        anchors.append("jobjs-index-table")
    if re.search(_index_table_expr_pattern(counter), code):
        anchors.append("mnVibration_804D4FE8")
    if re.search(
        rf"\bHSD_PadCopyStatus\s*\[\s*(?:\(u8\)\s*)?{token}\s*\]\s*\.\s*err\b",
        code,
    ):
        anchors.append("HSD_PadCopyStatus")
    return sorted(set(anchors))


def _index_table_expr_pattern(counter: str) -> str:
    token = re.escape(counter)
    return rf"mnVibration_804D4FE8\s*\[\s*(?:\(u8\)\s*)?{token}\s*\]"


def _counter_plus_two_pattern(counter: str) -> str:
    token = re.escape(counter)
    return rf"(?:{token}\s*\+\s*2|\(u8\)\s*{token}\s*\+\s*2)"


def _safe_loop_rejection(loop: Mapping[str, Any]) -> str | None:
    loop_text = str(loop["body"])
    if _span_has_preprocessor(loop_text):
        return "preprocessor-region"
    control_flow = _loop_body_control_flow_reason(loop_text)
    if control_flow is not None:
        return control_flow
    if _counter_has_body_side_effect(loop_text, str(loop["counter"])):
        return "unsafe-counter-side-effect"
    return None


def _span_has_preprocessor(text: str) -> bool:
    return any(line.lstrip().startswith("#") for line in text.splitlines())


def _loop_body_control_flow_reason(loop_body: str) -> str | None:
    code = _mask_c_non_code_text(loop_body)
    if re.search(r"\b(?:return|goto|break|continue)\b", code):
        return "loop-body-control-flow"
    if re.search(r"(?m)^[ \t]*(?!case\b|default\b)[A-Za-z_]\w*\s*:", code):
        return "loop-body-control-flow"
    return None


def _counter_has_body_side_effect(loop_body: str, counter: str) -> bool:
    code = _mask_c_non_code_text(loop_body)
    token = re.escape(counter)
    if re.search(rf"(?<![A-Za-z0-9_])&\s*\(*\s*{token}\b", code):
        return True
    if re.search(rf"\b{token}\b\s*(?:[+\-*/%&|^]=|<<=|>>=|=(?!=))", code):
        return True
    if re.search(rf"(?:\+\+|--)\s*{token}\b|\b{token}\b\s*(?:\+\+|--)", code):
        return True
    return False


def _mask_c_non_code_text(text: str) -> str:
    masked = list(text)
    idx = 0

    def blank(pos: int) -> None:
        if masked[pos] != "\n":
            masked[pos] = " "

    while idx < len(text):
        char = text[idx]
        nxt = text[idx + 1] if idx + 1 < len(text) else ""
        if char == "/" and nxt == "/":
            blank(idx)
            blank(idx + 1)
            idx += 2
            while idx < len(text) and text[idx] != "\n":
                blank(idx)
                idx += 1
            continue
        if char == "/" and nxt == "*":
            blank(idx)
            blank(idx + 1)
            idx += 2
            while idx < len(text):
                end = text[idx] == "*" and idx + 1 < len(text) and text[idx + 1] == "/"
                blank(idx)
                if end:
                    blank(idx + 1)
                    idx += 2
                    break
                idx += 1
            continue
        if char in {'"', "'"}:
            quote = char
            blank(idx)
            idx += 1
            escaped = False
            while idx < len(text):
                current = text[idx]
                blank(idx)
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == quote:
                    idx += 1
                    break
                idx += 1
            continue
        idx += 1
    return "".join(masked)


def _find_matching_brace_char(source: str, open_idx: int) -> int | None:
    masked = _mask_c_non_code_text(source)
    depth = 0
    for idx in range(open_idx, len(masked)):
        char = masked[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return idx
    return None


def _line_bounds_for_offset(source: str, offset: int) -> tuple[int, int]:
    start = source.rfind("\n", 0, offset) + 1
    end = source.find("\n", offset)
    if end == -1:
        end = len(source)
    else:
        end += 1
    return start, end


def _line_range_char(source: str, start: int, end: int) -> tuple[int, int]:
    return source.count("\n", 0, start) + 1, source.count("\n", 0, max(start, end - 1)) + 1


def _replace_char_slice(source: str, start: int, end: int, replacement: str) -> str:
    return source[:start] + replacement + source[end:]


def _indent_block_lines(text: str, indent: str) -> str:
    inner_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if not line.strip():
            inner_lines.append(line)
        elif line.startswith(indent):
            inner_lines.append(f"{indent}    {line[len(indent):]}")
        else:
            inner_lines.append(f"{indent}    {line}")
    return "".join(inner_lines)


def _parse_function(source: str, function: str) -> tuple[bytes, Any] | None:
    try:
        parser = tree_sitter_c.get_parser()
        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)
    except Exception:
        return None
    function_node = find_function_definition(tree.root_node, source_bytes, function)
    if function_node is None:
        return None
    return source_bytes, function_node


def _retag_control_flow_probe(probe: LifetimeLayoutProbe) -> LifetimeLayoutProbe:
    provenance = dict(probe.provenance or {})
    provenance.setdefault("delegated_kind", provenance.get("kind", probe.operator))
    provenance["kind"] = "control-flow-shape"
    return LifetimeLayoutProbe(
        label=f"control-flow-{probe.label}",
        operator=probe.operator,
        description=probe.description,
        source_text=probe.source_text,
        provenance=provenance,
    )


def _local_control_flow_probes(
    source: str,
    function: str,
    source_bytes: bytes,
    function_node: Any,
    statement_spans: list[StatementSpan],
    operators: tuple[str, ...],
    *,
    max_probes: int,
) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    for operator in operators:
        if operator == "ternary-to-if-else":
            candidates = _ternary_to_if_else_probes(source, source_bytes, statement_spans)
        elif operator == "if-else-to-ternary":
            candidates = _if_else_to_ternary_probes(source, source_bytes, function_node)
        elif operator == "bool-condition-spelling":
            candidates = _bool_condition_spelling_probes(source, source_bytes, function_node)
        elif operator == "if-equality-to-single-case-switch":
            candidates = _if_equality_to_single_case_switch_probes(
                source, source_bytes, function_node
            )
        else:
            candidates = []
        probes.extend(candidates[: max_probes - len(probes)])
        if len(probes) >= max_probes:
            break
    return probes


def _ternary_to_if_else_probes(
    source: str,
    source_bytes: bytes,
    statement_spans: list[StatementSpan],
) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    for span in statement_spans:
        if span.kind != "expression_statement":
            continue
        start, end = span.byte_range
        if _span_touches_preprocessor(source, start, end):
            continue
        statement_node = _parse_statement_node(source, span)
        if statement_node is None:
            continue
        assignment = _plain_assignment_expression_statement(statement_node, source_bytes)
        if assignment is None:
            continue
        lhs = assignment.child_by_field_name("left")
        rhs = assignment.child_by_field_name("right")
        if lhs is None or rhs is None or rhs.type != "conditional_expression":
            continue
        cond = rhs.child_by_field_name("condition")
        true_expr = rhs.child_by_field_name("consequence")
        false_expr = rhs.child_by_field_name("alternative")
        if cond is None or true_expr is None or false_expr is None:
            continue

        lhs_text = node_text(source_bytes, lhs).strip()
        cond_text = node_text(source_bytes, cond).strip()
        true_text = node_text(source_bytes, true_expr).strip()
        false_text = node_text(source_bytes, false_expr).strip()
        if not (
            _safe_expr(lhs_text, allow_lhs=True)
            and _safe_expr(cond_text)
            and _safe_expr(true_text)
            and _safe_expr(false_text)
        ):
            continue

        indent = _line_indent(source, start)
        replacement = (
            f"{indent}if ({cond_text}) {{\n"
            f"{indent}    {lhs_text} = {true_text};\n"
            f"{indent}}} else {{\n"
            f"{indent}    {lhs_text} = {false_text};\n"
            f"{indent}}}"
        )
        probes.append(
            _probe(
                "ternary-to-if-else",
                len(probes),
                "Expand ternary assignment to an if/else assignment.",
                _replace_slice(source, start, end, replacement),
                source,
                start,
                end,
            )
        )
    return probes


def _if_else_to_ternary_probes(source: str, source_bytes: bytes, function_node: Any) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    for node in _walk_nodes(function_node, {"if_statement"}):
        start, end = node.start_byte, node.end_byte
        if _span_touches_preprocessor(source, start, end):
            continue
        condition = node.child_by_field_name("condition")
        consequence = node.child_by_field_name("consequence")
        alternative = node.child_by_field_name("alternative")
        alt_compound = _else_compound(alternative)
        if (
            condition is None
            or consequence is None
            or consequence.type != "compound_statement"
            or alt_compound is None
        ):
            continue
        true_assign = _single_assignment_statement(consequence, source_bytes)
        false_assign = _single_assignment_statement(alt_compound, source_bytes)
        if true_assign is None or false_assign is None:
            continue
        lhs, true_expr = true_assign
        false_lhs, false_expr = false_assign
        cond_text = _strip_outer_parens(node_text(source_bytes, condition).strip())
        if lhs != false_lhs:
            continue
        if not (
            _safe_expr(lhs, allow_lhs=True)
            and _safe_expr(cond_text)
            and _safe_expr(true_expr)
            and _safe_expr(false_expr)
        ):
            continue

        indent = _line_indent(source, start)
        replacement = f"{indent}{lhs} = {cond_text} ? {true_expr} : {false_expr};"
        probes.append(
            _probe(
                "if-else-to-ternary",
                len(probes),
                "Collapse simple if/else assignment to a ternary assignment.",
                _replace_slice(source, start, end, replacement),
                source,
                start,
                end,
            )
        )
    return probes


def _bool_condition_spelling_probes(source: str, source_bytes: bytes, function_node: Any) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    for node in _walk_nodes(function_node, {"if_statement", "while_statement"}):
        condition = node.child_by_field_name("condition")
        if condition is None:
            continue
        start, end = condition.start_byte, condition.end_byte
        if _span_touches_preprocessor(source, start, end):
            continue
        cond_text = _strip_outer_parens(node_text(source_bytes, condition).strip())
        replacement_inner = _boolean_condition_alternative(cond_text)
        if replacement_inner is None:
            continue
        replacement = f"({replacement_inner})"
        probes.append(
            _probe(
                "bool-condition-spelling",
                len(probes),
                "Spell boolean condition as an explicit zero comparison.",
                _replace_slice(source, start, end, replacement),
                source,
                start,
                end,
            )
        )
    return probes


def _if_equality_to_single_case_switch_probes(
    source: str,
    source_bytes: bytes,
    function_node: Any,
) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    for node in _walk_nodes(function_node, {"if_statement"}):
        start, end = node.start_byte, node.end_byte
        if _span_touches_preprocessor(source, start, end):
            continue
        condition = node.child_by_field_name("condition")
        consequence = node.child_by_field_name("consequence")
        alternative = node.child_by_field_name("alternative")
        if (
            condition is None
            or consequence is None
            or consequence.type != "compound_statement"
            or alternative is not None
        ):
            continue
        comparison = _if_equality_operands(condition, source_bytes)
        if comparison is None:
            continue
        switch_case = _if_equality_switch_case(comparison)
        if switch_case is None or _compound_body_has_unsafe_control_flow(consequence):
            continue
        switch_expr, case_expr = switch_case

        indent = _line_indent(source, start)
        body = _compound_body_text(source, consequence).rstrip()
        replacement = _render_single_case_switch(indent, switch_expr, case_expr, body)
        probes.append(
            _probe(
                "if-equality-to-single-case-switch",
                len(probes),
                "Rewrite equality if statement as a single-case switch.",
                _replace_slice(source, start, end, replacement),
                source,
                start,
                end,
            )
        )
    return probes


def _boolean_condition_alternative(cond_text: str) -> str | None:
    cond_text = cond_text.strip()
    if cond_text.startswith("!"):
        inner = cond_text[1:].strip()
        inner = _strip_outer_parens(inner)
        if _safe_bool_operand(inner):
            return f"{inner} == 0"
        return None
    comparison = _ZERO_COMPARISON_RE.fullmatch(cond_text)
    if comparison is not None:
        inner = _strip_outer_parens(comparison.group(1).strip())
        operator = comparison.group(2)
        if not _safe_bool_operand(inner):
            return None
        if operator == "==":
            return f"!{inner}"
        return inner
    if _safe_bool_operand(cond_text):
        return f"{cond_text} != 0"
    return None


def _safe_bool_operand(expr: str) -> bool:
    expr = _strip_outer_parens(expr.strip())
    return _safe_expr(expr, allow_lhs=True)


def _parse_statement_node(source: str, span: StatementSpan) -> Any | None:
    try:
        source_bytes = source.encode("utf-8")
        tree = tree_sitter_c.get_parser().parse(source_bytes)
    except Exception:
        return None
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.start_byte == span.byte_range[0] and node.end_byte == span.byte_range[1]:
            return node
        stack.extend(reversed(node.children))
    return None


def _single_assignment_statement(compound: Any, source_bytes: bytes) -> tuple[str, str] | None:
    statements = [
        child
        for child in compound.children
        if child.type not in {"{", "}", "comment"} and child.is_named
    ]
    if len(statements) != 1 or statements[0].type != "expression_statement":
        return None
    assignment = _plain_assignment_expression_statement(statements[0], source_bytes)
    if assignment is None:
        return None
    lhs = assignment.child_by_field_name("left")
    rhs = assignment.child_by_field_name("right")
    if lhs is None or rhs is None:
        return None
    return node_text(source_bytes, lhs).strip(), node_text(source_bytes, rhs).strip()


def _if_equality_operands(condition: Any, source_bytes: bytes) -> tuple[str, str] | None:
    comparison = condition
    while comparison is not None and comparison.type == "parenthesized_expression":
        comparison = _single_named_child(comparison)
    if comparison is None or comparison.type != "binary_expression":
        return None
    operator = comparison.child_by_field_name("operator")
    left = comparison.child_by_field_name("left")
    right = comparison.child_by_field_name("right")
    if (
        operator is None
        or left is None
        or right is None
        or node_text(source_bytes, operator).strip() != "=="
    ):
        return None
    return node_text(source_bytes, left).strip(), node_text(source_bytes, right).strip()


def _if_equality_switch_case(comparison: tuple[str, str]) -> tuple[str, str] | None:
    left, right = comparison
    if _integer_constant_like_expression(right) and _safe_switch_case_pair(left, right):
        return left, right
    if _integer_constant_like_expression(left) and _safe_switch_case_pair(right, left):
        return right, left
    return None


def _single_named_child(node: Any) -> Any | None:
    named_children = [
        child for child in node.children if child.is_named and child.type != "comment"
    ]
    if len(named_children) != 1:
        return None
    return named_children[0]


def _integer_constant_like_expression(expr: str) -> bool:
    return re.fullmatch(r"(?:0[xX][0-9A-Fa-f]+|[0-9]+)(?:[uUlL]*)?", expr.strip()) is not None


def _safe_switch_case_pair(switch_expr: str, case_expr: str) -> bool:
    switch_expr = _strip_outer_parens(switch_expr.strip())
    case_expr = case_expr.strip()
    if _integer_constant_value(case_expr) == 0 and not _safe_unary_deref_switch_expression(switch_expr):
        return False
    return _safe_switch_expression(switch_expr)


def _integer_constant_value(expr: str) -> int | None:
    text = re.sub(r"[uUlL]+$", "", expr.strip())
    try:
        return int(text, 0)
    except ValueError:
        return None


def _safe_switch_expression(expr: str) -> bool:
    expr = _strip_outer_parens(expr.strip())
    if expr in {"NULL", "nullptr"}:
        return False
    if expr.startswith('"') or expr.startswith('L"') or _FLOAT_LITERAL_RE.fullmatch(expr):
        return False
    if _safe_unary_deref_switch_expression(expr):
        return True
    if re.fullmatch(_IDENT, expr):
        return False
    return _safe_expr(expr, allow_lhs=True)


def _safe_unary_deref_switch_expression(expr: str) -> bool:
    if not expr.startswith("*"):
        return False
    operand = expr[1:].strip()
    if not operand or operand.startswith("*"):
        return False
    return _safe_expr(operand, allow_lhs=True)


def _compound_body_has_unsafe_control_flow(compound: Any) -> bool:
    return bool(_walk_nodes(compound, _MOVED_BODY_REJECT_NODE_TYPES))


def _compound_body_text(source: str, compound: Any) -> str:
    start = _byte_to_char_range(source, compound.start_byte, compound.start_byte)[0]
    end = _byte_to_char_range(source, compound.end_byte, compound.end_byte)[0]
    text = source[start:end]
    open_brace = text.find("{")
    close_brace = text.rfind("}")
    if open_brace == -1 or close_brace == -1 or close_brace <= open_brace:
        return ""
    return text[open_brace + 1 : close_brace]


def _render_single_case_switch(indent: str, switch_expr: str, case_expr: str, body: str) -> str:
    return (
        f"{indent}switch ({switch_expr}) {{\n"
        f"{indent}case {case_expr}: {{{body}\n"
        f"{indent}    break;\n"
        f"{indent}}}\n"
        f"{indent}}}"
    )


def _safe_expr(expr: str, *, allow_lhs: bool = False) -> bool:
    expr = expr.strip()
    if not expr:
        return False
    if _CONTROL_FLOW_TOKENS.search(expr):
        return False
    if any(token in expr for token in ("++", "--", "{", "}", ":")):
        return False
    if "," in expr or _ASSIGNMENT_TOKEN_RE.search(expr):
        return False
    if not _balanced_delimiters(expr):
        return False
    if allow_lhs:
        return _SIMPLE_LHS_RE.fullmatch(expr) is not None and "(" not in expr and ")" not in expr
    if re.search(r"\b[A-Za-z_]\w*\s*\(", expr):
        return False
    return True


def _span_touches_preprocessor(source: str, start: int, end: int) -> bool:
    char_start, char_end = _byte_to_char_range(source, start, end)
    line_start = source.rfind("\n", 0, char_start) + 1
    line_end = source.find("\n", char_end)
    if line_end == -1:
        line_end = len(source)
    covered = source[line_start:line_end]
    if any(re.match(r"\s*#", line) for line in covered.splitlines()):
        return True

    return _inside_preprocessor_region(source, char_start)


def _inside_preprocessor_region(source: str, char_index: int) -> bool:
    depth = 0
    for line in source[:char_index].splitlines():
        stripped = line.lstrip()
        if _PREPROCESSOR_IF_RE.match(stripped):
            depth += 1
        elif _PREPROCESSOR_ENDIF_RE.match(stripped) and depth:
            depth -= 1
    return depth > 0


def _is_plain_assignment(assignment: Any, source_bytes: bytes) -> bool:
    operator = assignment.child_by_field_name("operator")
    return operator is not None and node_text(source_bytes, operator).strip() == "="


def _plain_assignment_expression_statement(statement: Any, source_bytes: bytes) -> Any | None:
    named_children = [
        child
        for child in statement.children
        if child.is_named and child.type != "comment"
    ]
    if len(named_children) != 1 or named_children[0].type != "assignment_expression":
        return None
    assignment = named_children[0]
    if not _is_plain_assignment(assignment, source_bytes):
        return None
    return assignment


def _line_range(source: str, start: int, end: int) -> tuple[int, int]:
    char_start, char_end = _byte_to_char_range(source, start, end)
    return source.count("\n", 0, char_start) + 1, source.count("\n", 0, char_end) + 1


def _replace_slice(source: str, start: int, end: int, replacement: str) -> str:
    char_start, char_end = _byte_to_char_range(source, start, end)
    return source[:char_start] + replacement + source[char_end:]


def _probe(
    operator: str,
    index: int,
    description: str,
    source_text: str,
    original_source: str,
    start: int,
    end: int,
) -> LifetimeLayoutProbe:
    return LifetimeLayoutProbe(
        label=f"control-flow-{operator}-{index}",
        operator=operator,
        description=description,
        source_text=source_text,
        provenance={
            "kind": "control-flow-shape",
            "operator": operator,
            "lines": list(_line_range(original_source, start, end)),
            "byte_range": [start, end],
        },
    )


def _walk_nodes(node: Any, types: set[str]) -> list[Any]:
    out: list[Any] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in types:
            out.append(current)
        stack.extend(reversed(current.children))
    return sorted(out, key=lambda item: item.start_byte)


def _first_child_of_type(node: Any, node_type: str) -> Any | None:
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == node_type:
            return current
        stack.extend(reversed(current.children))
    return None


def _else_compound(alternative: Any | None) -> Any | None:
    if alternative is None or alternative.type != "else_clause":
        return None
    for child in alternative.children:
        if child.type == "compound_statement":
            return child
    return None


def _line_indent(source: str, start: int) -> str:
    char_start = _byte_to_char_range(source, start, start)[0]
    line_start = source.rfind("\n", 0, char_start) + 1
    indent = source[line_start:char_start]
    if indent:
        return indent
    return "    "


def _strip_outer_parens(expr: str) -> str:
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")") and _outer_parens_wrap(expr):
        expr = expr[1:-1].strip()
    return expr


def _outer_parens_wrap(expr: str) -> bool:
    depth = 0
    for idx, char in enumerate(expr):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and idx != len(expr) - 1:
                return False
        if depth < 0:
            return False
    return depth == 0


def _balanced_delimiters(expr: str) -> bool:
    pairs = {")": "(", "]": "["}
    stack: list[str] = []
    for char in expr:
        if char in "([":
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                return False
    return not stack


def _byte_to_char_range(source: str, start: int, end: int) -> tuple[int, int]:
    encoded = source.encode("utf-8")
    prefix_start = encoded[:start].decode("utf-8", errors="ignore")
    prefix_end = encoded[:end].decode("utf-8", errors="ignore")
    return len(prefix_start), len(prefix_end)
