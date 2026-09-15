from __future__ import annotations

import re
import shlex
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .post_source_context_discovery import (
    DISCOVERY_FAMILY as POST_SOURCE_CONTEXT_DISCOVERY_FAMILY,
)
from .post_source_context_discovery import (
    DISCOVERY_KIND as POST_SOURCE_CONTEXT_DISCOVERY_KIND,
)
from .post_source_context_discovery import (
    DRAW_POST_SOURCE_CONTEXT_DIMENSION,
)
from .retained_frontier_triage import (
    retained_frontier_meta_ceiling_from_payloads,
    retained_frontier_meta_rank,
    synthesize_retained_frontier_meta_ceiling,
)


class EvidenceFunctionMismatch(ValueError):
    """Raised when evidence names a function different from the requested one."""


class EvidenceFormatError(ValueError):
    """Raised when an evidence payload is not a JSON object or list of objects."""


_REMOTE_RETAINED_SOURCE_STOP_KINDS = {
    "remote-retained-source-stdin-transport-timeout",
    "remote-retained-source-file-transport-timeout",
    "remote-retained-source-compile-timeout",
    "remote-retained-source-file-staging-failed",
    "remote-retained-source-staging-failed",
    "remote-retained-source-dependency-context-mismatch",
    "remote-retained-source-compile-failed",
}
_BOUNDED_STOP_KINDS = {
    "candidate-limit",
    "budget-exhausted",
    "unsafe-local-pcdump-lane",
    "remote-pcdump-failed",
    *_REMOTE_RETAINED_SOURCE_STOP_KINDS,
}
_EXPRESSION_INTERFERER_KIND = "expression-scored-fpr-case-a-c2-exhaustion"
_EXPRESSION_POST_BRIDGE_KIND = (
    "no-expression-progress-after-row-fsubs-and-support-orders"
)
_EXPRESSION_ALLOCATOR_BLOCKER = "current-source-shape-allocator-ceiling"
_TARGET_ONLY_ADDI_COPY_PRODUCT_RESOLVER_KIND = (
    "target-only-backprojection-addi-copy-product-source-resolver"
)
_SORT_FUNCTION = "mnDiagram_SortNamesByKOs"
_SORT_PROTECTED_STRUCTURAL_TARGETS = {"34": 27, "44": 25}
_DRAW_FPR_CASE_C_SOURCE_EXHAUSTION_KIND = (
    "degree-zero-fpr-case-c-source-exhaustion"
)
_DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION = (
    "draw-post-all-known-frontiers-source-context-hypothesis"
)
_DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION = (
    "draw-post-all-known-loop-product-translate-expression-graph"
)
_DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION = (
    "draw-post-product-translate-stack-clean-no-anchor-recovery"
)
_DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-product-translate-"
    "stack-clean-no-anchor-recovery"
)
_DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL = (
    "Draw post-product/translate stack-clean/no-anchor recovery exhausted "
    "bounded row-delta, digit fsubs, col-product owner-transfer, and "
    "frame-clean owner-prune probes without recovering IG32/IG37/IG46 "
    "expression anchors or eliminating the stack-frame drift while preserving "
    "the normalized opcode shape."
)
_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION = (
    "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis"
)
_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL = (
    "Draw post-stack-clean/no-anchor FPR source-shape synthesis from the "
    "stack-clean final proof, testing declaration packing, row/column owner "
    "reuse, digit base lifetime, and frame-neutral owner coalescing against "
    "IG32/IG37/IG46 plus the +8 frame drift."
)
_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-stack-clean-no-anchor-"
    "fpr-source-shape-hypothesis"
)
_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL = (
    "Draw post-stack-clean/no-anchor FPR source-shape synthesis exhausted "
    "bounded declaration-packing, row/column owner reuse, digit base lifetime, "
    "coupled row/column, and frame-neutral coalescing probes without recovering "
    "IG32/IG37/IG46 expression anchors or eliminating the stack-frame drift "
    "under the structural guard."
)
_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON = (
    "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis-exhausted/"
    "no-floor-improvement"
)
_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_BLOCKER = (
    "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis/"
    "no-source-actionable-anchor-or-frame-recovery"
)
_DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION = (
    "draw-coupled-fpr-expression-lifetime-helper-boundary-handoff"
)
_DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON = (
    "all-inline-helper-candidates-rejected"
)
_DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON = (
    "draw-coupled-fpr-expression-lifetime-helper-boundary-exhausted/"
    "no-expression-progress"
)
_DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASONS = {
    _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON,
    _DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON,
}
_EXPRESSION_REQUIRED_EXHAUSTED_ROUTES = (
    "row_fsubs_owner_repair",
    "non_satisfied_select_order",
)
_FPR_CLASS_ID = 1
_FORCE_VECTOR_TARGET_RE = re.compile(
    r"^class(?P<class_id>\d+):ig(?P<ig_idx>\d+):phys="
    r"(?P<prefix>[rf])?(?P<phys>\d+)$"
)
_SHORT_FORCE_VECTOR_TARGET_RE = re.compile(
    r"^(?P<class_id>\d+):(?P<ig_idx>\d+):(?P<phys>\d+)$"
)
_ADDI_SOURCE_LEVER_RE = re.compile(
    r"^addi\s+r(?P<dst>\d+),\s*r(?P<base>\d+),\s*(?P<imm>-?\d+)$"
)


def flatten_evidence_items(items: Iterable[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, list):
            out.extend(flatten_evidence_items(item))
        elif isinstance(item, Mapping):
            out.append(dict(item))
        else:
            raise EvidenceFormatError(
                "evidence must be a JSON object or a list of JSON objects"
            )
    return out


def classify_allocator_ceiling(
    evidence: Iterable[Mapping[str, Any]],
    *,
    function: str,
) -> dict[str, Any]:
    items = flatten_evidence_items(evidence)
    _validate_function_scope(items, function=function)

    positive = _positive_proofs(items)
    retained_meta = _retained_frontiers_meta_ceiling(items, function=function)
    directed = _directed_summary(items)
    bounded = _dedupe([*_bounded_reasons(items), *directed["bounded_reasons"]])
    bounded_resume_commands = _bounded_resume_commands(items)
    node_delta = _node_set_delta(items)
    force_vector = _force_vector_status(items)
    node_set_exhaustion = _node_set_exhaustion(items)
    wrong_register = bool(node_set_exhaustion["complete"])
    transform_exhausted = _transform_exhausted(items)
    select_order_fpr_case_c = _select_order_fpr_case_c_exhaustion(
        items,
        node_delta=node_delta,
    )
    node_set_frontier = _node_set_frontier_coverage(
        items,
        node_delta=node_delta,
    )
    if select_order_fpr_case_c.get("complete") is True:
        transform_exhausted = True
    if node_set_frontier.get("complete") is True:
        wrong_register = True
    residual_case_c = _residual_case_c_source_repair(
        items,
        node_delta=node_delta,
    )
    expression_terminal = _expression_interferer_terminal(items)
    skipped_count = _skipped_source_evidence_count(items)

    legacy_missing: list[str] = []
    if node_delta is None:
        legacy_missing.append(
            "solve-coloring structurally-different-virtual node_set_delta"
        )
    frontier_missing = [
        entry for entry in node_set_frontier.get("missing_evidence", [])
        if isinstance(entry, str)
    ]
    if frontier_missing:
        legacy_missing.extend(frontier_missing)
    force_vector_probe_complete = _force_vector_probe_evidence_complete(
        force_vector,
        node_set_frontier=node_set_frontier,
        select_order_fpr_case_c=select_order_fpr_case_c,
    )
    force_vector_no_match_after_draw_frontier = (
        force_vector.get("ran") is True
        and force_vector.get("union_status") == "no_match"
        and force_vector_probe_complete
    )
    if not force_vector_probe_complete:
        legacy_missing.append("force-phys verification with union status match")
    if not wrong_register and not frontier_missing:
        legacy_missing.append("node-set-split exhaustive all-wrong-register evidence")
    if not transform_exhausted:
        legacy_missing.append("transform-corpus exhausted negative validation evidence")
    legacy_missing = _dedupe(legacy_missing)
    if legacy_missing:
        target_only_backprojection = _empty_target_only_backprojection()
    else:
        target_only_backprojection = _target_only_allocator_backprojection(
            items,
            function=function,
            node_delta=node_delta,
        )

    directed_complete = bool(directed["complete"])
    directed_missing = _directed_missing_evidence(directed)
    if expression_terminal["status"] == "incomplete":
        missing = expression_terminal["missing_evidence"]
    elif directed["present"] and not directed_complete:
        missing = directed_missing
    else:
        missing = legacy_missing
    if (
        residual_case_c.get("status") == "incomplete"
        and residual_case_c.get("terminal_stack_candidate")
        == "live-implicit-temp-copy-survived"
    ):
        residual_missing = [
            entry for entry in residual_case_c.get("missing_evidence", [])
            if isinstance(entry, str)
        ]
        missing = _dedupe([*missing, *residual_missing])

    target_only_source_probe = _target_only_source_probe_continuation(
        items,
        target_only_backprojection=target_only_backprojection,
    )
    target_only_sticky_pool = _target_only_c2_sticky_pool_attribution(
        items,
        target_only_backprojection=target_only_backprojection,
    )
    if (
        target_only_source_probe.get("status") != "not-present"
        or target_only_sticky_pool.get("status") != "not-present"
    ):
        target_only_backprojection = dict(target_only_backprojection)
        if target_only_source_probe.get("status") != "not-present":
            target_only_backprojection["source_probe_continuation"] = (
                target_only_source_probe
            )
        if target_only_sticky_pool.get("status") != "not-present":
            target_only_backprojection["c2_sticky_pool_attribution"] = (
                target_only_sticky_pool
            )

    if positive:
        status = "actionable"
        reason = "positive-proof"
        exit_code = 0
    elif bounded:
        status = "bounded"
        reason = "bounded-evidence"
        exit_code = 4
    elif directed_complete:
        status = "practical-ceiling"
        reason = "directed-source-exhausted"
        exit_code = 3
        missing = []
    elif (
        not legacy_missing
        and target_only_source_probe.get("complete") is True
    ):
        status = "practical-ceiling"
        reason = "target-only-backprojection-source-probe-continuation-terminal"
        exit_code = 3
        missing = []
    elif (
        not legacy_missing
        and target_only_sticky_pool.get("complete") is True
    ):
        status = "practical-ceiling"
        reason = "target-only-c2-sticky-pool-source-attribution-terminal"
        exit_code = 3
        missing = []
    elif residual_case_c.get("complete") is True:
        status = "practical-ceiling"
        reason = "residual-case-c-source-repair-exhausted"
        exit_code = 3
        missing = []
    elif expression_terminal.get("complete") is True:
        status = "practical-ceiling"
        reason = "expression-scored-fpr-allocator-ceiling"
        exit_code = 3
        missing = []
    elif (
        not legacy_missing
        and force_vector_no_match_after_draw_frontier
    ):
        status = "practical-ceiling"
        reason = "force-vector-no-match-after-draw-frontier-exhaustion"
        exit_code = 3
        missing = []
    elif (
        not legacy_missing
        and target_only_backprojection.get("status") == "source-actionable"
    ):
        status = "actionable"
        reason = "target-only-allocator-rotation-backprojection"
        exit_code = 0
        missing = []
    elif (
        not legacy_missing
        and target_only_backprojection.get("status")
        == "terminal-non-source-expressible"
    ):
        status = "practical-ceiling"
        reason = "target-only-allocator-rotation-backprojection-terminal"
        exit_code = 3
        missing = []
    elif _retained_meta_post_source_context_actionable(retained_meta):
        status = "actionable"
        reason = "post-source-context-next-dimension-source-actionable-lane"
        exit_code = 0
        missing = []
    elif retained_meta.get("status") == "actionable":
        status = "actionable"
        reason = "retained-frontiers-next-source-actionable-lane"
        exit_code = 0
        missing = []
    elif (
        retained_meta.get("status") == "terminal-current-source-shape-ceiling"
    ):
        status = "practical-ceiling"
        reason = (
            "retained-frontiers-all-known-frontiers-exhausted/"
            "current-source-shape-ceiling"
        )
        exit_code = 3
        missing = []
    elif (
        not legacy_missing
        and target_only_backprojection.get("status") == "incomplete"
    ):
        status = "incomplete"
        reason = "missing-required-evidence"
        exit_code = 3
        missing = list(target_only_backprojection.get("missing_evidence") or [])
    elif expression_terminal["status"] == "incomplete":
        status = "incomplete"
        reason = "missing-required-evidence"
        exit_code = 3
    elif not legacy_missing:
        status = "practical-ceiling"
        reason = "target-only-allocator-rotation"
        exit_code = 3
        missing = []
    else:
        status = "incomplete"
        reason = "missing-required-evidence"
        exit_code = 3

    directed_source_exhausted = (
        status == "practical-ceiling" and reason == "directed-source-exhausted"
    )
    expression_source_exhausted = (
        status == "practical-ceiling"
        and reason == "expression-scored-fpr-allocator-ceiling"
    )
    target_only_source_probe_exhausted = (
        status == "practical-ceiling"
        and reason == "target-only-backprojection-source-probe-continuation-terminal"
    )
    target_only_sticky_pool_exhausted = (
        status == "practical-ceiling"
        and reason == "target-only-c2-sticky-pool-source-attribution-terminal"
    )
    retained_frontiers_source_exhausted = (
        status == "practical-ceiling"
        and reason
        == "retained-frontiers-all-known-frontiers-exhausted/current-source-shape-ceiling"
    )
    backend_blockers = (
        directed["backend_blockers"]
        if directed_source_exhausted
        else expression_terminal["backend_blockers"]
        if expression_source_exhausted
        else []
    )

    return {
        "function": function,
        "status": status,
        "terminal_reason": reason,
        "exit_code": exit_code,
        "positive_proofs": positive,
        "source_shape_exhausted": bool(
            transform_exhausted
            or directed_source_exhausted
            or residual_case_c.get("complete") is True
            or expression_terminal.get("complete") is True
            or target_only_source_probe_exhausted
            or target_only_sticky_pool_exhausted
            or retained_frontiers_source_exhausted
            or retained_meta.get("source_shape_exhausted") is True
        ),
        "directed_source_exhausted": directed_source_exhausted,
        "residual_case_c_source_repair": residual_case_c,
        "expression_interferer_terminal": expression_terminal,
        "select_order_fpr_case_c_exhaustion": select_order_fpr_case_c,
        "backend_blockers": backend_blockers,
        "node_set_delta": node_delta,
        "force_vector": force_vector,
        "target_only_allocator_backprojection": target_only_backprojection,
        "retained_frontiers_meta_ceiling": retained_meta,
        "next_frontier": _next_frontier_from_retained_meta(retained_meta),
        "post_source_context_next_dimension": (
            _post_source_context_next_dimension_from_retained_meta(retained_meta)
        ),
        "current_ceiling": (
            retained_meta.get("terminal_proof")
            if retained_frontiers_source_exhausted
            else None
        ),
        "target_only_backprojection_source_probe_continuation": (
            target_only_source_probe
        ),
        "target_only_c2_sticky_pool_attribution": target_only_sticky_pool,
        "wrong_register_exhausted": bool(wrong_register),
        "node_set_exhaustion": node_set_exhaustion,
        "node_set_frontier_coverage": node_set_frontier,
        "bounded_reasons": bounded,
        "bounded_resume_commands": bounded_resume_commands,
        "missing_evidence": missing,
        "skipped_source_evidence_count": skipped_count,
        "evidence_count": len(items),
        "next_steps": _next_steps(
            function=function,
            status=status,
            bounded=bounded,
            bounded_resume_commands=bounded_resume_commands,
            missing=missing,
            residual_case_c=residual_case_c,
            expression_terminal=expression_terminal,
            target_only_backprojection=target_only_backprojection,
            node_delta=node_delta,
            node_set_frontier=node_set_frontier,
            select_order_fpr_case_c=select_order_fpr_case_c,
            retained_meta=retained_meta,
        ),
    }


def _validate_function_scope(items: list[dict[str, Any]], *, function: str) -> None:
    for idx, item in enumerate(items):
        if _is_retained_frontiers_aggregate(item):
            names = _retained_frontiers_aggregate_function_names(item)
            if function in names:
                continue
            if not names:
                raise EvidenceFunctionMismatch(
                    f"evidence item {idx} has no function scope for {function}"
                )
            sample = sorted(names)[0]
            raise EvidenceFunctionMismatch(
                f"evidence item {idx} is for {sample}, not {function}"
            )
        names = _function_names(item)
        if not names:
            if _is_expression_interferer_terminal_candidate(item):
                continue
            if _is_unscoped_first_divergence_advisory(item):
                continue
            if _is_unscoped_sort_protected_structural_recombine(
                item,
                function=function,
            ):
                continue
            raise EvidenceFunctionMismatch(
                f"evidence item {idx} has no function scope for {function}"
            )
        for name in names:
            if name != function:
                raise EvidenceFunctionMismatch(
                    f"evidence item {idx} is for {name}, not {function}"
                )


def _function_names(item: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    value = item.get("function")
    if isinstance(value, str) and value:
        names.add(value)
    for key in (
        "functions",
        "node_set_delta",
        "plan",
        "request",
        "validation_summary",
        "node_set_delta_summary",
        "force_vector_verify",
        "validator_payload",
        "evidence",
        "source_generation",
    ):
        nested = item.get(key)
        if isinstance(nested, Mapping):
            names.update(_function_names(nested))
        elif isinstance(nested, list):
            for child in nested:
                if isinstance(child, Mapping):
                    names.update(_function_names(child))
    for key in ("validation", "validation_results", "directed_telemetry"):
        nested_list = item.get(key)
        if isinstance(nested_list, list):
            for nested in nested_list:
                if isinstance(nested, Mapping):
                    names.update(_function_names(nested))
    return names


def _is_unscoped_first_divergence_advisory(item: Mapping[str, Any]) -> bool:
    return item.get("kind") == "allocator-first-divergence"


def _is_unscoped_sort_protected_structural_recombine(
    item: Mapping[str, Any],
    *,
    function: str,
) -> bool:
    if function != _SORT_FUNCTION:
        return False
    synthesis = item.get("protected_structural_synthesis")
    if not isinstance(synthesis, Mapping):
        return False
    if _normalized_int_mapping(synthesis.get("required_assignments")) != (
        _SORT_PROTECTED_STRUCTURAL_TARGETS
    ):
        return False
    combinations = item.get("combinations")
    if not isinstance(combinations, list):
        return False
    return any(
        isinstance(row, Mapping)
        and row.get("status") == "ok"
        and isinstance(row.get("target_score"), Mapping)
        for row in combinations
    )


def _is_retained_frontiers_aggregate(item: Mapping[str, Any]) -> bool:
    functions = item.get("functions")
    return isinstance(functions, list) and (
        item.get("status") in {
            "actionable",
            "all-known-frontiers-exhausted",
            "no-frontiers-found",
        }
        or "next_frontier" in item
    )


def _retained_frontiers_aggregate_function_names(
    item: Mapping[str, Any],
) -> set[str]:
    names: set[str] = set()
    functions = item.get("functions")
    if isinstance(functions, list):
        for entry in functions:
            if isinstance(entry, Mapping):
                value = entry.get("function")
                if isinstance(value, str) and value:
                    names.add(value)
    return names


def _retained_frontiers_meta_ceiling(
    items: list[dict[str, Any]],
    *,
    function: str,
) -> dict[str, Any]:
    best = retained_frontier_meta_ceiling_from_payloads(items, function=function)
    combined_present = best.get("status") != "not-present"
    if best.get("status") == "not-present":
        best = _empty_retained_frontiers_meta(function)
    for item in items:
        if combined_present and (
            _is_retained_frontiers_aggregate(item)
            or _is_retained_frontiers_function_entry(item)
        ):
            continue
        meta = _retained_meta_evidence_item(item, function=function)
        if meta.get("status") == "not-present":
            continue
        if _retained_meta_rank(meta) >= _retained_meta_rank(best):
            best = meta
    return best


def _retained_meta_evidence_item(
    item: Mapping[str, Any],
    *,
    function: str,
) -> dict[str, Any]:
    if item.get("kind") == POST_SOURCE_CONTEXT_DISCOVERY_KIND:
        return _post_source_context_discovery_meta(item, function=function)
    if item.get("kind") == "retained-frontiers-meta-ceiling":
        if item.get("function") == function:
            return dict(item)
        return _empty_retained_frontiers_meta(function)
    if _is_retained_frontiers_aggregate(item) or _is_retained_frontiers_function_entry(item):
        return synthesize_retained_frontier_meta_ceiling(item, function=function)
    return _empty_retained_frontiers_meta(function)


def _retained_meta_rank(meta: Mapping[str, Any]) -> tuple[int, int, int, int]:
    return retained_frontier_meta_rank(meta)


def _post_source_context_discovery_meta(
    item: Mapping[str, Any],
    *,
    function: str,
) -> dict[str, Any]:
    if item.get("function") != function:
        return _empty_retained_frontiers_meta(function)
    if item.get("status") == "source-actionable":
        next_frontier = (
            dict(item.get("next_frontier"))
            if isinstance(item.get("next_frontier"), Mapping)
            else {}
        )
        next_frontier.setdefault("kind", POST_SOURCE_CONTEXT_DISCOVERY_KIND)
        next_frontier.setdefault("family_id", POST_SOURCE_CONTEXT_DISCOVERY_FAMILY)
        next_frontier.setdefault("actionable", True)
        return {
            "kind": "retained-frontiers-meta-ceiling",
            "function": function,
            "status": "actionable",
            "retained_frontiers_status": "actionable",
            "next_frontier": next_frontier,
            "ranked_next_lanes": [next_frontier],
            "closed_families": [],
            "terminal_groups": [],
        }
    if item.get("status") not in {
        "unsupported-source-dimension",
        "unsupported-source-family",
    }:
        return _empty_retained_frontiers_meta(function)
    evidence = [
        dict(row) for row in item.get("retained_evidence") or []
        if isinstance(row, Mapping)
    ]
    proof = {
        "kind": POST_SOURCE_CONTEXT_DISCOVERY_KIND,
        "status": "complete",
        "reason": "post-source-context-next-dimension-discovered",
        "terminal_reason": (
            "post-source-context-next-dimension/"
            f"{item.get('status') or 'unsupported-source-dimension'}"
        ),
        "next_unsupported_source_family": item.get(
            "next_unsupported_source_family"
        ),
        "next_unsupported_source_model": item.get("next_unsupported_source_model"),
        "next_unsupported_source_spans": [
            dict(row) for row in item.get("source_spans") or []
            if isinstance(row, Mapping)
        ],
        "source_spans": [
            dict(row) for row in item.get("source_spans") or []
            if isinstance(row, Mapping)
        ],
        "candidate_scores": evidence,
        "retained_scored_probes": evidence,
    }
    exhausted_dimensions = _post_source_context_exhausted_dimensions(item)
    next_dimension = item.get("next_unsupported_source_dimension")
    if (
        isinstance(next_dimension, str)
        and next_dimension
        and next_dimension not in set(exhausted_dimensions)
    ):
        proof["next_unsupported_source_dimension"] = next_dimension
    for key in (
        "exhausted_source_dimension",
        "exhausted_dimensions",
        "unsupported_source_expression_class",
        "unsupported_source_expression_model",
    ):
        value = item.get(key)
        if value is not None:
            proof[key] = value
    if evidence:
        first = evidence[0]
        for key in ("target_score", "expression_score", "pcdump_path"):
            if first.get(key) is not None:
                proof[key] = first[key]
    return {
        "kind": "retained-frontiers-meta-ceiling",
        "function": function,
        "status": "terminal-current-source-shape-ceiling",
        "terminal_reason": (
            "retained-frontiers-all-known-frontiers-exhausted/"
            "current-source-shape-ceiling"
        ),
        "terminal_blocker": "current-source-shape-ceiling",
        "source_shape_exhausted": True,
        "retained_frontiers_status": "all-known-frontiers-exhausted",
        "next_frontier": None,
        "summary": {},
        "closed_families": [POST_SOURCE_CONTEXT_DISCOVERY_FAMILY],
        "terminal_groups": [
            {
                "family_id": POST_SOURCE_CONTEXT_DISCOVERY_FAMILY,
                "terminal_reason": item.get("status"),
                "suppression_family": POST_SOURCE_CONTEXT_DISCOVERY_FAMILY,
                "count": 1,
                "source_spans": proof["source_spans"],
                "next_unsupported_source_model": proof[
                    "next_unsupported_source_model"
                ],
                "next_unsupported_source_family": proof[
                    "next_unsupported_source_family"
                ],
            }
        ],
        "ranked_next_lanes": [],
        "terminal_proof": proof,
    }


def _post_source_context_exhausted_dimensions(
    item: Mapping[str, Any],
) -> list[str]:
    values: list[str] = []
    for value in (item.get("exhausted_source_dimension"),):
        if isinstance(value, str) and value and value not in values:
            values.append(value)
    exhausted = item.get("exhausted_dimensions")
    if isinstance(exhausted, list):
        for row in exhausted:
            if isinstance(row, Mapping):
                value = row.get("dimension_id")
            else:
                value = row
            if isinstance(value, str) and value and value not in values:
                values.append(value)
    return values


def _retained_meta_post_source_context_actionable(
    retained_meta: Mapping[str, Any],
) -> bool:
    if retained_meta.get("status") != "actionable":
        return False
    next_frontier = retained_meta.get("next_frontier")
    if not isinstance(next_frontier, Mapping):
        return False
    return (
        next_frontier.get("kind") == POST_SOURCE_CONTEXT_DISCOVERY_KIND
        or next_frontier.get("family_id") == POST_SOURCE_CONTEXT_DISCOVERY_FAMILY
    )


def _retained_meta_post_all_known_actionable(
    retained_meta: Mapping[str, Any],
) -> bool:
    if retained_meta.get("status") != "actionable":
        return False
    next_frontier = retained_meta.get("next_frontier")
    if not isinstance(next_frontier, Mapping):
        return False
    return (
        _retained_meta_frontier_dimension(next_frontier)
        == _DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION
    )


def _retained_meta_product_translate_actionable(
    retained_meta: Mapping[str, Any],
) -> bool:
    if retained_meta.get("status") != "actionable":
        return False
    next_frontier = retained_meta.get("next_frontier")
    if not isinstance(next_frontier, Mapping):
        return False
    return (
        _retained_meta_frontier_dimension(next_frontier)
        == _DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION
    )


def _retained_meta_stack_clean_no_anchor_actionable(
    retained_meta: Mapping[str, Any],
) -> bool:
    if retained_meta.get("status") != "actionable":
        return False
    next_frontier = retained_meta.get("next_frontier")
    if not isinstance(next_frontier, Mapping):
        return False
    return (
        _retained_meta_frontier_dimension(next_frontier)
        == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )


def _retained_meta_draw_helper_boundary_actionable(
    retained_meta: Mapping[str, Any],
) -> bool:
    if retained_meta.get("status") != "actionable":
        return False
    next_frontier = retained_meta.get("next_frontier")
    if not isinstance(next_frontier, Mapping):
        return False
    return (
        _retained_meta_frontier_dimension(next_frontier)
        == _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )


def _retained_meta_draw_helper_boundary_terminal(
    proof: Mapping[str, Any],
) -> bool:
    if not _retained_meta_proof_mentions_dimension(
        proof,
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION,
    ) and proof.get("next_unsupported_source_family") != (
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
    ):
        return False
    return any(
        _retained_meta_proof_has_terminal_blocker(proof, reason)
        or proof.get("terminal_blocker") == reason
        or proof.get("terminal_reason") == reason
        for reason in _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASONS
    )


def _retained_meta_stack_clean_final_terminal(proof: Mapping[str, Any]) -> bool:
    if _retained_meta_post_stack_clean_source_shape_terminal(proof):
        return False
    if proof.get("next_unsupported_source_family") == (
        _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    ):
        return True
    if proof.get("next_unsupported_source_model") == (
        _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
    ):
        return True
    if proof.get("terminal_reason") == (
        "draw-post-product-translate-stack-clean-no-anchor-recovery-"
        "exhausted/no-anchor-recovery"
    ):
        return True
    return (
        _retained_meta_proof_mentions_dimension(
            proof,
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        )
        and proof.get("next_unsupported_source_dimension")
        != _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )


def _retained_meta_post_stack_clean_source_shape_terminal(
    proof: Mapping[str, Any],
) -> bool:
    for source in (proof, proof.get("source_family_synthesis")):
        if not isinstance(source, Mapping):
            continue
        if source.get("next_unsupported_source_family") == (
            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
        ):
            return True
        if source.get("next_unsupported_source_model") == (
            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL
        ):
            return True
        if source.get("terminal_reason") == (
            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
        ):
            return True
        if source.get("terminal_blocker") == (
            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_BLOCKER
        ):
            return True
        exhausted = source.get("exhausted_dimensions")
        if not isinstance(exhausted, list):
            exhausted = []
        for row in exhausted:
            if not isinstance(row, Mapping):
                continue
            if row.get("exhaustion_reason") == (
                _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
            ):
                return True
            if (
                row.get("dimension_id")
                == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
                and row.get("status")
                in {"terminal", "scored-terminal", "exhausted"}
            ):
                return True
    return False


def _retained_meta_proof_has_terminal_blocker(
    proof: Mapping[str, Any],
    blocker: str,
) -> bool:
    for source in (proof, proof.get("source_family_synthesis")):
        if not isinstance(source, Mapping):
            continue
        for key in ("terminal_blocker", "terminal_reason", "reason"):
            if source.get(key) == blocker:
                return True
        rows = source.get("terminal_blockers")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, Mapping):
                reason = row.get("reason") or row.get("terminal_blocker")
            else:
                reason = row
            if reason == blocker:
                return True
    return False


def _retained_meta_terminal_blocker_summaries(
    proof: Mapping[str, Any],
) -> list[str]:
    out: list[str] = []

    def append(reason: Any, count: Any = None) -> None:
        if not isinstance(reason, str) or not reason:
            return
        text = reason
        parsed_count = _int_value(count)
        if parsed_count is not None:
            text = f"{text} ({parsed_count} candidates)"
            for index, existing in enumerate(out):
                if existing == reason:
                    out[index] = text
                    return
        elif any(existing.startswith(f"{reason} (") for existing in out):
            return
        if text not in out:
            out.append(text)

    for source in (proof, proof.get("source_family_synthesis")):
        if not isinstance(source, Mapping):
            continue
        append(source.get("terminal_blocker"))
        rows = source.get("terminal_blockers")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, Mapping):
                append(
                    row.get("reason") or row.get("terminal_blocker"),
                    row.get("count"),
                )
            else:
                append(row)
    return out


def _retained_meta_frontier_dimension(frontier: Mapping[str, Any]) -> str | None:
    for key in ("dimension_id", "source_model_layer_dimension_id"):
        value = frontier.get(key)
        if isinstance(value, str) and value:
            return value
    proof = frontier.get("source_model_proof")
    if isinstance(proof, Mapping):
        for key in (
            "exhausted_source_dimension",
            "next_unsupported_source_dimension",
        ):
            value = proof.get(key)
            if isinstance(value, str) and value:
                return value
        exhausted = proof.get("exhausted_dimensions")
        if isinstance(exhausted, list):
            for row in exhausted:
                if isinstance(row, Mapping):
                    value = row.get("dimension_id")
                else:
                    value = row
                if isinstance(value, str) and value:
                    return value
        synthesis = proof.get("source_family_synthesis")
        if isinstance(synthesis, Mapping):
            for key in (
                "exhausted_source_dimension",
                "next_unsupported_source_dimension",
            ):
                value = synthesis.get(key)
                if isinstance(value, str) and value:
                    return value
            exhausted = synthesis.get("exhausted_dimensions")
            if isinstance(exhausted, list):
                for row in exhausted:
                    if isinstance(row, Mapping):
                        value = row.get("dimension_id")
                    else:
                        value = row
                    if isinstance(value, str) and value:
                        return value
    continuation = frontier.get("continuation")
    if isinstance(continuation, Mapping):
        for key in (
            "dimension_id",
            "source_model_layer_dimension_id",
            "next_unsupported_source_dimension",
        ):
            value = continuation.get(key)
            if isinstance(value, str) and value:
                return value
        route = continuation.get("route")
        if route in {
            DRAW_POST_SOURCE_CONTEXT_DIMENSION,
            _DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION,
            _DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION,
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        }:
            return route
    return None


def _retained_meta_proof_mentions_dimension(
    proof: Mapping[str, Any],
    dimension: str,
) -> bool:
    for key in (
        "exhausted_source_dimension",
        "next_unsupported_source_dimension",
    ):
        if proof.get(key) == dimension:
            return True
    exhausted = proof.get("exhausted_dimensions")
    if isinstance(exhausted, list):
        for row in exhausted:
            if isinstance(row, Mapping):
                value = row.get("dimension_id")
            else:
                value = row
            if value == dimension:
                return True
    synthesis = proof.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        if _retained_meta_proof_mentions_dimension(synthesis, dimension):
            return True
    return False


def _post_source_context_next_dimension_from_retained_meta(
    retained_meta: Mapping[str, Any],
) -> dict[str, Any] | None:
    if _retained_meta_post_source_context_actionable(retained_meta):
        return dict(retained_meta.get("next_frontier") or {})
    proof = retained_meta.get("terminal_proof")
    if not isinstance(proof, Mapping):
        return None
    if (
        proof.get("kind") == POST_SOURCE_CONTEXT_DISCOVERY_KIND
        or proof.get("next_unsupported_source_dimension")
        == DRAW_POST_SOURCE_CONTEXT_DIMENSION
    ):
        return dict(proof)
    return None


def _next_frontier_from_retained_meta(
    retained_meta: Mapping[str, Any],
) -> dict[str, Any] | None:
    if retained_meta.get("status") != "actionable":
        return None
    next_frontier = retained_meta.get("next_frontier")
    if isinstance(next_frontier, Mapping):
        return dict(next_frontier)
    return None


def _is_retained_frontiers_function_entry(item: Mapping[str, Any]) -> bool:
    return (
        isinstance(item.get("function"), str)
        and (
            isinstance(item.get("frontiers"), list)
            or isinstance(item.get("terminal_frontiers"), list)
            or "next_frontier" in item
        )
    )


def _empty_retained_frontiers_meta(function: str) -> dict[str, Any]:
    return {
        "kind": "retained-frontiers-meta-ceiling",
        "function": function,
        "status": "not-present",
        "ranked_next_lanes": [],
    }


def _is_expression_interferer_terminal_candidate(item: Mapping[str, Any]) -> bool:
    return _expression_terminal_summary(item) is not None


def _expression_interferer_terminal(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    fallback: dict[str, Any] | None = None
    for item in items:
        payload = _expression_interferer_terminal_item(item)
        if payload["status"] == "not-present":
            continue
        if payload["complete"]:
            return payload
        if fallback is None or len(payload["missing_evidence"]) < len(
            fallback["missing_evidence"]
        ):
            fallback = payload
    if fallback is not None:
        return fallback
    return _empty_expression_interferer_terminal()


def _expression_interferer_terminal_item(
    item: Mapping[str, Any],
) -> dict[str, Any]:
    terminal = _expression_terminal_summary(item)
    if terminal is None:
        return _empty_expression_interferer_terminal()

    source_generation = _expression_source_generation(item)
    evidence_raw = terminal.get("evidence")
    evidence = dict(evidence_raw) if isinstance(evidence_raw, Mapping) else {}
    exhausted_routes = _string_list(terminal.get("exhausted_routes"))
    terminal_kind = terminal.get("kind")
    terminal_blocker = terminal.get("terminal_blocker")

    missing: list[str] = []
    if (
        terminal.get("status") != "blocked"
        or terminal_kind != _EXPRESSION_POST_BRIDGE_KIND
    ):
        missing.append("expression-interferer post_bridge_terminal_summary")
    if terminal_blocker != _EXPRESSION_ALLOCATOR_BLOCKER:
        missing.append(
            "expression-interferer terminal blocker "
            f"{_EXPRESSION_ALLOCATOR_BLOCKER}"
        )
    if not set(_EXPRESSION_REQUIRED_EXHAUSTED_ROUTES).issubset(
        set(exhausted_routes)
    ):
        missing.append(
            "expression-interferer exhausted routes: "
            + ", ".join(_EXPRESSION_REQUIRED_EXHAUSTED_ROUTES)
        )
    if not _expression_scored_no_progress(evidence):
        missing.append("expression-interferer scored no-progress evidence")
    if not _expression_fpr_swap_evidence_present(evidence):
        missing.append("expression-interferer FPR swap evidence")
    if source_generation is not None and not _expression_source_generation_matches(
        source_generation
    ):
        missing.append(
            "expression-interferer source_generation blocked terminal handoff"
        )

    complete = not missing
    return {
        "status": (
            "terminal-current-source-shape-ceiling" if complete else "incomplete"
        ),
        "complete": complete,
        "kind": terminal_kind,
        "terminal_blocker": terminal_blocker,
        "exhausted_routes": exhausted_routes,
        "attempted_families": _string_list(item.get("attempted_families")),
        "source_generation": source_generation,
        "evidence": evidence,
        "backend_blockers": (
            _expression_backend_blockers(evidence, exhausted_routes)
            if complete else []
        ),
        "missing_evidence": _dedupe(missing),
        "suppressed_families": _expression_suppressed_families(
            item,
            source_generation,
        ),
    }


def _empty_expression_interferer_terminal() -> dict[str, Any]:
    return {
        "status": "not-present",
        "complete": False,
        "kind": None,
        "terminal_blocker": None,
        "exhausted_routes": [],
        "attempted_families": [],
        "source_generation": None,
        "evidence": {},
        "backend_blockers": [],
        "missing_evidence": [],
        "suppressed_families": [],
    }


def _expression_terminal_summary(
    item: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    if item.get("kind") == _EXPRESSION_INTERFERER_KIND:
        terminal = item.get("post_bridge_terminal_summary")
        if isinstance(terminal, Mapping):
            return terminal
    if item.get("kind") == _EXPRESSION_POST_BRIDGE_KIND:
        return item
    return None


def _expression_source_generation(
    item: Mapping[str, Any],
) -> dict[str, Any] | None:
    source_generation = item.get("source_generation")
    if isinstance(source_generation, Mapping):
        return dict(source_generation)
    return None


def _expression_source_generation_matches(source_generation: Mapping[str, Any]) -> bool:
    return (
        source_generation.get("status") == "blocked"
        and source_generation.get("terminal_blocker") == _EXPRESSION_ALLOCATOR_BLOCKER
    )


def _expression_scored_no_progress(evidence: Mapping[str, Any]) -> bool:
    return (
        _positive_int(evidence.get("candidate_count")) > 0
        and _int_value(evidence.get("best_expression_matched")) == 0
        and _positive_int(evidence.get("best_expression_targeted")) > 0
    )


def _expression_fpr_swap_evidence_present(evidence: Mapping[str, Any]) -> bool:
    return all(
        evidence.get(key) is not None
        for key in (
            "focus_ig",
            "paired_ig",
            "current_focus_reg",
            "current_paired_reg",
            "target_reg",
            "paired_target_reg",
        )
    )


def _expression_backend_blockers(
    evidence: Mapping[str, Any],
    exhausted_routes: list[str],
) -> list[dict[str, Any]]:
    mutators = [
        f"expression-interferer:{route}"
        for route in _EXPRESSION_REQUIRED_EXHAUSTED_ROUTES
        if route in exhausted_routes
    ]
    return [
        {
            "class_id": _FPR_CLASS_ID,
            "original_ig": evidence.get("focus_ig"),
            "new_ig": evidence.get("focus_ig"),
            "desired_phys": evidence.get("target_reg"),
            "assigned_phys": evidence.get("current_focus_reg"),
            "mutators": mutators,
            "source": evidence.get("focus"),
        },
        {
            "class_id": _FPR_CLASS_ID,
            "original_ig": evidence.get("paired_ig"),
            "new_ig": evidence.get("paired_ig"),
            "desired_phys": evidence.get("paired_target_reg"),
            "assigned_phys": evidence.get("current_paired_reg"),
            "mutators": mutators,
            "source": evidence.get("paired_source"),
        },
    ]


def _expression_suppressed_families(
    item: Mapping[str, Any],
    source_generation: Mapping[str, Any] | None,
) -> list[str]:
    if source_generation is not None:
        families = _string_list(source_generation.get("suppressed_families"))
        if families:
            return families
    return _string_list(item.get("suppressed_families"))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, str)]


def _positive_int(value: Any) -> int:
    raw = _int_value(value)
    return raw if raw is not None and raw > 0 else 0


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _positive_proofs(items: list[dict[str, Any]]) -> list[str]:
    proofs: list[str] = []
    for item in items:
        if item.get("byte_match") is True:
            proofs.append("byte_match")
        if item.get("status") == "improved":
            proofs.append("status improved")
        delta = item.get("best_checkdiff_delta")
        if isinstance(delta, (int, float)) and not isinstance(delta, bool) and delta > 0:
            proofs.append(f"best_checkdiff_delta {delta:g}")
        validation = item.get("validation") or []
        if isinstance(validation, list):
            for result in validation:
                if (
                    isinstance(result, Mapping)
                    and result.get("outcome") == "retained-source-improvement"
                ):
                    proofs.append("validation retained-source-improvement")
                    break
        summary = item.get("validation_summary")
        if (
            isinstance(summary, Mapping)
            and summary.get("stop_condition") == "retained-source-improvement"
        ):
            proofs.append("validation_summary retained-source-improvement")
        telemetry = item.get("directed_telemetry")
        if isinstance(telemetry, list):
            for row in telemetry:
                if not isinstance(row, Mapping):
                    continue
                if row.get("checkdiff_gate") == "byte_match":
                    proofs.append("directed byte_match")
                    break
                byte_score = row.get("byte_score")
                if (
                    isinstance(byte_score, (int, float))
                    and not isinstance(byte_score, bool)
                    and byte_score == 0
                ):
                    proofs.append("directed byte_match")
                    break
        gate = item.get("gate")
        if isinstance(gate, Mapping) and gate.get("passed") is True:
            reason = gate.get("reason")
            if isinstance(reason, str) and reason:
                proofs.append(f"directed {reason}")
            else:
                proofs.append("directed gate passed")
    return proofs


def _directed_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "present": False,
        "complete": False,
        "source_rows": 0,
        "compiled": 0,
        "telemetry_rows": 0,
        "byte_mismatch_rows": 0,
        "unknown_byte_rows": 0,
        "source_shape_drained": False,
        "has_blocked_assignments": False,
        "has_no_smooth_gradient_gate": False,
        "bounded_reasons": [],
        "backend_blockers": [],
    }
    blockers: dict[tuple[Any, Any, Any, Any, Any], dict[str, Any]] = {}

    for item in items:
        run = _directed_item_summary(item)
        if not run["present"]:
            continue
        summary["present"] = True
        summary["source_rows"] += run["source_rows"]
        summary["compiled"] += run["compiled"]
        summary["telemetry_rows"] += run["telemetry_rows"]
        summary["byte_mismatch_rows"] += run["byte_mismatch_rows"]
        summary["unknown_byte_rows"] += run["unknown_byte_rows"]
        summary["source_shape_drained"] = (
            summary["source_shape_drained"] or run["source_shape_drained"]
        )
        summary["has_blocked_assignments"] = (
            summary["has_blocked_assignments"] or run["has_blocked_assignments"]
        )
        summary["has_no_smooth_gradient_gate"] = (
            summary["has_no_smooth_gradient_gate"]
            or run["has_no_smooth_gradient_gate"]
        )
        summary["bounded_reasons"].extend(run["bounded_reasons"])
        _merge_backend_blockers(blockers, run["backend_blockers"])
        if run["complete"]:
            summary["complete"] = True

    summary["bounded_reasons"] = _dedupe(summary["bounded_reasons"])
    summary["backend_blockers"] = list(blockers.values())
    return summary


def _directed_item_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    telemetry = item.get("directed_telemetry")
    if not isinstance(telemetry, list):
        return {
            "present": False,
            "complete": False,
            "source_rows": 0,
            "compiled": 0,
            "telemetry_rows": 0,
            "byte_mismatch_rows": 0,
            "unknown_byte_rows": 0,
            "source_shape_drained": False,
            "has_blocked_assignments": False,
            "has_no_smooth_gradient_gate": False,
            "bounded_reasons": [],
            "backend_blockers": [],
        }

    bounded_reasons = _directed_bounded_reasons(item)
    compiled = 0
    accounting = item.get("accounting")
    source_shape_drained = False
    if isinstance(accounting, Mapping):
        compiled = _nonnegative_int(accounting.get("compiled"))
        source_shape_drained = accounting.get("source_shape_drained") is True

    gate = item.get("gate")
    has_no_smooth_gradient_gate = (
        isinstance(gate, Mapping)
        and gate.get("passed") is False
        and gate.get("reason") == "no_smooth_gradient"
    )
    source_rows = 0
    byte_mismatch_rows = 0
    unknown_byte_rows = 0
    invalid_rows = 0
    blockers: dict[tuple[Any, Any, Any, Any, Any], dict[str, Any]] = {}
    telemetry_rows = 0
    for row in telemetry:
        if not isinstance(row, Mapping):
            continue
        telemetry_rows += 1
        if row.get("valid") is False:
            invalid_rows += 1
        if _has_byte_mismatch_outcome(row):
            byte_mismatch_rows += 1
        elif row.get("valid") is not False:
            unknown_byte_rows += 1
        if _is_source_transform_row(row):
            source_rows += 1
        _merge_backend_blockers(blockers, _directed_backend_blockers(row))

    if invalid_rows:
        bounded_reasons.append("directed search invalid directed telemetry")

    backend_blockers = list(blockers.values())
    complete = (
        telemetry_rows > 0
        and compiled > 0
        and source_rows > 0
        and byte_mismatch_rows > 0
        and unknown_byte_rows == 0
        and source_shape_drained
        and bool(backend_blockers)
        and has_no_smooth_gradient_gate
        and not bounded_reasons
    )
    return {
        "present": True,
        "complete": complete,
        "source_rows": source_rows,
        "compiled": compiled,
        "telemetry_rows": telemetry_rows,
        "byte_mismatch_rows": byte_mismatch_rows,
        "unknown_byte_rows": unknown_byte_rows,
        "source_shape_drained": source_shape_drained,
        "has_blocked_assignments": bool(backend_blockers),
        "has_no_smooth_gradient_gate": has_no_smooth_gradient_gate,
        "bounded_reasons": bounded_reasons,
        "backend_blockers": backend_blockers,
    }


def _directed_bounded_reasons(item: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    accounting = item.get("accounting")
    if not isinstance(accounting, Mapping):
        return reasons
    if accounting.get("budget_exhausted") is True:
        reasons.append("directed search budget exhausted")
    stop_reason = accounting.get("stop_reason")
    if stop_reason in _BOUNDED_STOP_KINDS:
        reasons.append(f"directed search {stop_reason}")
    stop_condition = accounting.get("stop_condition")
    if isinstance(stop_condition, Mapping):
        kind = stop_condition.get("kind")
        if kind in _BOUNDED_STOP_KINDS:
            reasons.append(f"directed search {kind}")
    producer_failed = _nonnegative_int(accounting.get("producer_failed"))
    producer_failures = accounting.get("producer_failures")
    if producer_failed or (
        isinstance(producer_failures, list) and len(producer_failures) > 0
    ):
        reasons.append("directed search producer failed")
    if _nonnegative_int(accounting.get("score_failed")):
        reasons.append("directed search score failed")
    if _nonnegative_int(accounting.get("directed_invalid")):
        reasons.append("directed search invalid directed telemetry")
    return _dedupe(reasons)


def _directed_backend_blockers(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    if row.get("valid") is False:
        return []
    assignments = row.get("proof_assignments")
    if not isinstance(assignments, Mapping):
        return []
    blocked = assignments.get("blocked")
    if not isinstance(blocked, list):
        return []
    mutator = row.get("applied_mutator")
    class_id = row.get("class_id")
    out: list[dict[str, Any]] = []
    for entry in blocked:
        if not isinstance(entry, Mapping):
            continue
        blocker = {
            "original_ig": entry.get("original_ig"),
            "new_ig": entry.get("new_ig"),
            "desired_phys": entry.get("desired_phys"),
            "assigned_phys": entry.get("assigned_phys"),
            "mutators": [],
        }
        if class_id is not None:
            blocker["class_id"] = class_id
        if isinstance(mutator, str) and mutator:
            blocker["mutators"].append(mutator)
        out.append(blocker)
    return out


def _merge_backend_blockers(
    target: dict[tuple[Any, Any, Any, Any, Any], dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> None:
    for blocker in blockers:
        key = (
            blocker.get("class_id"),
            blocker.get("original_ig"),
            blocker.get("new_ig"),
            blocker.get("desired_phys"),
            blocker.get("assigned_phys"),
        )
        merged_payload = {
            "original_ig": key[1],
            "new_ig": key[2],
            "desired_phys": key[3],
            "assigned_phys": key[4],
            "mutators": [],
        }
        if key[0] is not None:
            merged_payload["class_id"] = key[0]
        merged = target.setdefault(key, merged_payload)
        for mutator in blocker.get("mutators", []):
            if mutator not in merged["mutators"]:
                merged["mutators"].append(mutator)


def _is_source_transform_row(row: Mapping[str, Any]) -> bool:
    mutator = row.get("applied_mutator")
    return isinstance(mutator, str) and mutator.startswith("transform-corpus:")


def _has_byte_mismatch_outcome(row: Mapping[str, Any]) -> bool:
    if row.get("checkdiff_gate") == "byte_mismatch":
        return True
    byte_score = row.get("byte_score")
    return (
        isinstance(byte_score, (int, float))
        and not isinstance(byte_score, bool)
        and byte_score > 0
    )


def _directed_missing_evidence(summary: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    if not summary.get("telemetry_rows"):
        missing.append("directed telemetry rows")
    if not summary.get("compiled"):
        missing.append("directed telemetry with compiled candidates")
    if not summary.get("byte_mismatch_rows") or summary.get("unknown_byte_rows"):
        missing.append("directed byte-mismatch outcomes")
    if not summary.get("source_shape_drained"):
        missing.append("directed source-shape drained signal")
    if not summary.get("source_rows"):
        missing.append("directed telemetry from source-transform candidates")
    if not summary.get("has_blocked_assignments"):
        missing.append("directed telemetry with blocked proof assignments")
    if not summary.get("has_no_smooth_gradient_gate"):
        missing.append("directed no_smooth_gradient gate verdict")
    return missing


def _bounded_reasons(items: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for item in items:
        stop_reason = item.get("stop_reason")
        if stop_reason in _BOUNDED_STOP_KINDS:
            reasons.append(f"{stop_reason} stop_reason")

        stop_condition = item.get("stop_condition")
        if isinstance(stop_condition, Mapping):
            kind = stop_condition.get("kind")
            if kind in _BOUNDED_STOP_KINDS:
                reasons.append(f"{kind} stop_condition")

        validation_summary = item.get("validation_summary")
        if isinstance(validation_summary, Mapping):
            remaining = validation_summary.get("remaining_probe_ids")
            if isinstance(remaining, list) and remaining:
                reasons.append(
                    _count_reason(
                        "transform-corpus has",
                        len(remaining),
                        "remaining probe",
                    )
                )

        node_summary = item.get("node_set_delta_summary")
        if isinstance(node_summary, Mapping):
            omitted = _nonnegative_int(node_summary.get("omitted_count"))
            if omitted:
                reasons.append(
                    _count_reason(
                        "transform-corpus omitted",
                        omitted,
                        "node-set probe",
                    )
                )
            capped = _nonnegative_int(node_summary.get("capped_count"))
            if capped:
                reasons.append(
                    _count_reason(
                        "transform-corpus capped",
                        capped,
                        "node-set probe",
                    )
                )
    return reasons


def _bounded_resume_commands(items: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for item in items:
        stop_condition = item.get("stop_condition")
        if not isinstance(stop_condition, Mapping):
            continue
        kind = stop_condition.get("kind")
        command = stop_condition.get("resume_command")
        if kind in _BOUNDED_STOP_KINDS and isinstance(command, str) and command:
            commands.append(command)
    return _dedupe(commands)


def _node_set_delta(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in items:
        nested = item.get("node_set_delta")
        if isinstance(nested, Mapping) and _is_required_node_set_delta(nested):
            return dict(nested)
        if _is_required_node_set_delta(item):
            return dict(item)
    return None


def _is_required_node_set_delta(item: Mapping[str, Any]) -> bool:
    return (
        item.get("kind") == "node-set-delta"
        and item.get("blocker") == "structurally-different-virtual"
    )


def _force_vector_status(items: list[dict[str, Any]]) -> dict[str, Any]:
    fallback: dict[str, Any] | None = None
    for item in items:
        prior = item.get("force_vector")
        if isinstance(prior, Mapping):
            result = {
                "ran": prior.get("ran") is True,
                "union_status": prior.get("union_status"),
                "returncode": prior.get("returncode"),
            }
            if result["ran"] and result["union_status"] == "match":
                return result
            if (
                fallback is None
                or (result["ran"] is True and fallback.get("ran") is not True)
            ):
                fallback = result
        verify = item.get("force_vector_verify")
        if not isinstance(verify, Mapping):
            continue
        union = verify.get("union")
        union_status = union.get("status") if isinstance(union, Mapping) else None
        ran = verify.get("ran") is True
        result = {
            "ran": ran,
            "union_status": union_status,
            "returncode": union.get("returncode") if isinstance(union, Mapping) else None,
        }
        if ran and union_status == "match":
            return result
        if (
            fallback is None
            or (result["ran"] is True and fallback.get("ran") is not True)
        ):
            fallback = result
    if fallback is not None:
        return fallback
    return {"ran": False, "union_status": None, "returncode": None}


def _force_vector_probe_evidence_complete(
    force_vector: Mapping[str, Any],
    *,
    node_set_frontier: Mapping[str, Any],
    select_order_fpr_case_c: Mapping[str, Any],
) -> bool:
    if force_vector.get("ran") is not True:
        return False
    union_status = force_vector.get("union_status")
    if union_status == "match":
        return True
    if union_status != "no_match":
        return False
    return (
        node_set_frontier.get("complete") is True
        and select_order_fpr_case_c.get("complete") is True
    )


def _empty_target_only_backprojection() -> dict[str, Any]:
    return {
        "status": "not-present",
        "force_targets": [],
        "missing_evidence": [],
    }


def _target_only_allocator_backprojection(
    items: list[dict[str, Any]],
    *,
    function: str,
    node_delta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    prior = _prior_target_only_backprojection(items)
    targets = _force_vector_targets(items)
    if not targets:
        if prior is not None and prior.get("status") != "not-present":
            return dict(prior)
        return {
            "status": "not-present",
            "force_targets": [],
            "missing_evidence": ["force-vector target map"],
        }

    natural_path, forced_path = _backprojection_pcdump_paths(items)
    missing: list[str] = []
    if natural_path is None:
        missing.append("natural pcdump")
    if forced_path is None:
        missing.append("forced pcdump")
    if missing:
        if prior is not None and prior.get("status") != "not-present":
            return dict(prior)
        return {
            "status": "missing-pcdump-evidence",
            "force_targets": targets,
            "missing_evidence": missing,
        }

    assert natural_path is not None
    assert forced_path is not None
    try:
        natural_text = natural_path.read_text(errors="replace")
        forced_text = forced_path.read_text(errors="replace")
    except OSError as exc:
        if prior is not None and prior.get("status") != "not-present":
            return dict(prior)
        return {
            "status": "missing-pcdump-evidence",
            "force_targets": targets,
            "natural_pcdump": str(natural_path),
            "forced_pcdump": str(forced_path),
            "missing_evidence": [str(exc)],
        }

    return _classify_target_only_allocator_backprojection(
        function=function,
        targets=targets,
        natural_text=natural_text,
        forced_text=forced_text,
        natural_path=natural_path,
        forced_path=forced_path,
        node_delta=node_delta,
    )


def _force_vector_targets(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int]] = set()
    prior = _prior_target_only_backprojection(items)
    if prior is not None:
        for target in prior.get("force_targets", []) or []:
            if not isinstance(target, Mapping):
                continue
            class_id = _int_or_none(target.get("class_id"))
            ig_idx = _int_or_none(target.get("ig_idx"))
            desired_phys = _int_or_none(target.get("desired_phys"))
            if class_id is None or ig_idx is None or desired_phys is None:
                continue
            key = (class_id, ig_idx, desired_phys)
            if key in seen:
                continue
            seen.add(key)
            targets.append({
                "class_id": class_id,
                "ig_idx": ig_idx,
                "desired_phys": desired_phys,
                "register": target.get("register")
                or f"{'f' if class_id == _FPR_CLASS_ID else 'r'}{desired_phys}",
            })
    for mapping in _matching_force_vector_mappings(items):
        value = mapping.get("force_vector")
        if not isinstance(value, str):
            continue
        for token in value.split(","):
            parsed = _parse_force_vector_target(token.strip())
            if parsed is None:
                continue
            key = (
                int(parsed["class_id"]),
                int(parsed["ig_idx"]),
                int(parsed["desired_phys"]),
            )
            if key in seen:
                continue
            seen.add(key)
            targets.append(parsed)
    return targets


def _prior_target_only_backprojection(
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for item in items:
        payload = item.get("target_only_allocator_backprojection")
        if isinstance(payload, Mapping):
            return dict(payload)
    return None


def _parse_force_vector_target(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    match = _FORCE_VECTOR_TARGET_RE.match(token)
    if match:
        class_id = int(match.group("class_id"))
        prefix = match.group("prefix") or ("f" if class_id == _FPR_CLASS_ID else "r")
        return {
            "class_id": class_id,
            "ig_idx": int(match.group("ig_idx")),
            "desired_phys": int(match.group("phys")),
            "register": f"{prefix}{int(match.group('phys'))}",
        }
    match = _SHORT_FORCE_VECTOR_TARGET_RE.match(token)
    if match:
        class_id = int(match.group("class_id"))
        phys = int(match.group("phys"))
        return {
            "class_id": class_id,
            "ig_idx": int(match.group("ig_idx")),
            "desired_phys": phys,
            "register": f"{'f' if class_id == _FPR_CLASS_ID else 'r'}{phys}",
        }
    return None


def _backprojection_pcdump_paths(
    items: list[dict[str, Any]],
) -> tuple[Path | None, Path | None]:
    explicit_natural: list[str] = []
    explicit_forced: list[str] = []
    natural_candidates: list[str] = []
    forced_candidates: list[str] = []
    matching_force_mappings = list(_matching_force_vector_mappings(items))

    for item in items:
        for mapping in _walk_mappings(item):
            for key in (
                "natural_pcdump",
                "natural_pcdump_path",
                "baseline_pcdump",
                "baseline_pcdump_path",
            ):
                value = mapping.get(key)
                if isinstance(value, str) and value:
                    explicit_natural.append(value)
            for key in ("forced_pcdump", "forced_pcdump_path"):
                value = mapping.get(key)
                if (
                    isinstance(value, str)
                    and value
                    and _accept_explicit_forced_pcdump(mapping)
                ):
                    explicit_forced.append(value)
            if _looks_like_retained_natural_pcdump(mapping):
                natural_candidates.extend(_pcdump_values(mapping))
    for mapping in matching_force_mappings:
        forced_candidates.extend(_recursive_pcdump_values(mapping))

    roots = _pcdump_roots(
        [
            *explicit_natural,
            *explicit_forced,
            *natural_candidates,
            *forced_candidates,
        ]
    )
    natural_path = _first_existing_path([*explicit_natural, *natural_candidates], roots)
    forced_path = _first_existing_path([*explicit_forced, *forced_candidates], roots)
    return natural_path, forced_path


def _accept_explicit_forced_pcdump(mapping: Mapping[str, Any]) -> bool:
    return (
        mapping.get("kind") == "target-only-allocator-backprojection-input"
        or _is_matching_force_vector_mapping(mapping)
    )


def _matching_force_vector_mappings(
    items: list[dict[str, Any]],
) -> list[Mapping[str, Any]]:
    mappings: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    for item in items:
        for mapping in _walk_mappings(item):
            if not _is_matching_force_vector_mapping(mapping):
                continue
            identity = id(mapping)
            if identity in seen:
                continue
            seen.add(identity)
            mappings.append(mapping)
    return mappings


def _is_matching_force_vector_mapping(mapping: Mapping[str, Any]) -> bool:
    verify = mapping.get("force_vector_verify")
    if not isinstance(verify, Mapping):
        return False
    union = verify.get("union")
    return (
        verify.get("ran") is True
        and isinstance(union, Mapping)
        and union.get("status") == "match"
    )


def _looks_like_retained_natural_pcdump(mapping: Mapping[str, Any]) -> bool:
    if not _pcdump_values(mapping):
        return False
    return (
        isinstance(mapping.get("target_score"), Mapping)
        or isinstance(mapping.get("structural_guard"), Mapping)
        or mapping.get("score") is not None
    )


def _pcdump_values(mapping: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("pcdump", "pcdump_path"):
        value = mapping.get(key)
        if isinstance(value, str) and value:
            values.append(value)
    return values


def _recursive_pcdump_values(mapping: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for nested in _walk_mappings(mapping):
        values.extend(_pcdump_values(nested))
    return values


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for nested in value.values():
            yield from _walk_mappings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_mappings(nested)


def _pcdump_roots(values: list[str]) -> list[Path]:
    roots = [Path.cwd()]
    seen = {str(Path.cwd())}
    for value in values:
        path = Path(value)
        if not path.is_absolute():
            continue
        candidates = [path.parent]
        parts = path.parts
        if "build" in parts:
            idx = parts.index("build")
            if idx > 0:
                candidates.append(Path(*parts[:idx]))
        for candidate in candidates:
            key = str(candidate)
            if key not in seen:
                roots.append(candidate)
                seen.add(key)
    return roots


def _first_existing_path(values: list[str], roots: list[Path]) -> Path | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        path = _resolve_existing_path(value, roots)
        if path is not None:
            return path
    return None


def _resolve_existing_path(value: str, roots: list[Path]) -> Path | None:
    path = Path(value)
    if path.is_absolute():
        return path if path.exists() else None
    for root in roots:
        candidate = root / path
        if candidate.exists():
            return candidate
    return None


def _classify_target_only_allocator_backprojection(
    *,
    function: str,
    targets: list[dict[str, Any]],
    natural_text: str,
    forced_text: str,
    natural_path: Path,
    forced_path: Path,
    node_delta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    from . import first_divergence
    from .colorgraph_parser import find_function, parse_hook_events

    if natural_path.resolve() == forced_path.resolve():
        return {
            "status": "incomplete",
            "force_targets": targets,
            "natural_pcdump": str(natural_path),
            "forced_pcdump": str(forced_path),
            "missing_evidence": ["forced pcdump must differ from natural pcdump"],
        }

    natural_fev = find_function(parse_hook_events(natural_text), function)
    forced_fev = find_function(parse_hook_events(forced_text), function)
    missing: list[str] = []
    if natural_fev is None:
        missing.append(f"natural pcdump function {function}")
    if forced_fev is None:
        missing.append(f"forced pcdump function {function}")
    if missing:
        return {
            "status": "incomplete",
            "force_targets": targets,
            "natural_pcdump": str(natural_path),
            "forced_pcdump": str(forced_path),
            "missing_evidence": missing,
        }

    assert natural_fev is not None
    assert forced_fev is not None
    source_by_ig = _node_delta_source_by_ig(node_delta)
    divergences: list[dict[str, Any]] = []
    source_levers: list[dict[str, Any]] = []
    errors: list[str] = []

    for class_id, force_phys in _targets_by_class(targets).items():
        try:
            report = first_divergence.analyze_first_divergence(
                natural_fev,
                first_divergence.TargetColoring(
                    class_id=class_id,
                    force_phys=force_phys,
                ),
            )
        except (NotImplementedError, ValueError) as exc:
            errors.append(f"class {class_id}: {exc}")
            continue

        fact = report.fact
        natural_decision = _decision_payload(
            natural_fev,
            class_id=class_id,
            ig_idx=fact.ig_idx,
        )
        forced_decision = _decision_payload(
            forced_fev,
            class_id=class_id,
            ig_idx=fact.ig_idx,
        )
        desired_phys = force_phys.get(fact.ig_idx, fact.target_reg)
        divergence = {
            "class_id": class_id,
            "case": fact.case.value,
            "target_ig": fact.ig_idx,
            "target_phys": desired_phys,
            "baseline_phys": fact.baseline_reg,
            "iter_idx": fact.iter_idx,
            "blocker_ig": fact.blocker_ig,
            "local_target": fact.local_target,
            "natural_decision": natural_decision,
            "forced_decision": forced_decision,
            "force_phys": dict(force_phys),
        }
        forced_error = _forced_decision_validation_error(
            forced_decision,
            desired_phys=desired_phys,
            class_id=class_id,
            ig_idx=fact.ig_idx,
        )
        if forced_error is not None:
            errors.append(forced_error)
            continue
        divergences.append(divergence)

        source = _source_for_backprojection(
            fact.ig_idx,
            source_by_ig=source_by_ig,
        )
        if source is None:
            continue
        source_levers.append({
            "rank": len(source_levers) + 1,
            "class_id": class_id,
            "target_ig": fact.ig_idx,
            "case": fact.case.value,
            "local_target": fact.local_target,
            "source": source,
        })

    if source_levers:
        status = "source-actionable"
    elif divergences:
        status = "terminal-non-source-expressible"
    else:
        status = "incomplete"
        if not errors:
            errors.append("first-divergence produced no allocator decision")

    return {
        "status": status,
        "force_targets": targets,
        "natural_pcdump": str(natural_path),
        "forced_pcdump": str(forced_path),
        "divergences": divergences,
        "source_levers": source_levers,
        "missing_evidence": errors,
    }


def _forced_decision_validation_error(
    forced_decision: Mapping[str, Any] | None,
    *,
    desired_phys: int | None,
    class_id: int,
    ig_idx: int,
) -> str | None:
    if desired_phys is None:
        return f"class {class_id} ig{ig_idx}: missing force target"
    if forced_decision is None:
        return f"class {class_id} ig{ig_idx}: forced pcdump has no decision"
    assigned = forced_decision.get("assigned_phys")
    if assigned != desired_phys:
        return (
            f"class {class_id} ig{ig_idx}: forced pcdump assigned "
            f"{assigned}, expected {desired_phys}"
        )
    return None


def _targets_by_class(
    targets: list[dict[str, Any]],
) -> dict[int, dict[int, int]]:
    by_class: dict[int, dict[int, int]] = {}
    for target in targets:
        class_id = int(target["class_id"])
        by_class.setdefault(class_id, {})[
            int(target["ig_idx"])
        ] = int(target["desired_phys"])
    return by_class


def _decision_payload(
    fev: Any,
    *,
    class_id: int,
    ig_idx: int,
) -> dict[str, Any] | None:
    from . import first_divergence

    section = first_divergence.select_class_section(fev, class_id)
    if section is None:
        return None
    for view in first_divergence.decision_views(section, fev):
        if view.ig_idx != ig_idx:
            continue
        return {
            "iter_idx": view.iter_idx,
            "assigned_phys": view.assigned_reg,
            "degree": view.n_interferers,
            "interferer_count": len(view.interferers),
            "interferers": [
                {"ig_idx": ig, "assigned_phys": phys}
                for ig, phys in view.interferers[:12]
            ],
        }
    return None


def _node_delta_source_by_ig(
    node_delta: Mapping[str, Any] | None,
) -> dict[int, dict[str, Any]]:
    if node_delta is None:
        return {}
    missing = node_delta.get("missing_virtuals")
    if not isinstance(missing, list):
        return {}
    sources: dict[int, dict[str, Any]] = {}
    for entry in missing:
        if not isinstance(entry, Mapping):
            continue
        source = entry.get("source")
        if not isinstance(source, Mapping):
            continue
        ig_idx = _entry_ig_idx(entry)
        if ig_idx is None:
            continue
        sources[ig_idx] = dict(source)
    return sources


def _entry_ig_idx(entry: Mapping[str, Any]) -> int | None:
    for key in ("target_ig", "ig_idx", "original_ig", "new_ig", "virtual"):
        value = entry.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _source_for_backprojection(
    fact_ig: int,
    *,
    source_by_ig: Mapping[int, dict[str, Any]],
) -> dict[str, Any] | None:
    if fact_ig in source_by_ig:
        return dict(source_by_ig[fact_ig])
    return None


def _target_only_source_probe_continuation(
    items: list[dict[str, Any]],
    *,
    target_only_backprojection: Mapping[str, Any],
) -> dict[str, Any]:
    lever = _target_only_addi_source_lever(target_only_backprojection)
    if lever is None:
        return _empty_target_only_terminal(
            "target-only-backprojection-source-probe-continuation"
        )

    source = lever.get("source")
    if not isinstance(source, Mapping):
        source = {}
    parsed = _parse_addi_source_lever(source.get("expression"))
    if parsed is None:
        return _empty_target_only_terminal(
            "target-only-backprojection-source-probe-continuation"
        )

    target_ig = _int_or_none(lever.get("target_ig"))
    class_id = _int_or_none(lever.get("class_id"))
    final_force = _target_only_force_phys(
        target_only_backprojection,
        class_id=class_id,
    )
    attempted, protected = _target_only_attempted_protected_targets(
        final_force,
        target_ig=target_ig,
    )
    exhaustion = _target_only_simplify_probe_exhaustion(
        items,
        expected_force_phys=final_force,
    )
    if exhaustion is None:
        return {
            "status": "incomplete",
            "complete": False,
            "kind": "target-only-backprojection-source-probe-continuation",
            "missing_evidence": [
                "matching target-only retained source-probe exhaustion"
            ],
            "source_lever": source.get("expression"),
            "source_kind": source.get("kind"),
            "source_confidence": source.get("confidence"),
            "pcode_lever": parsed,
            "final_force_phys": final_force,
        }

    resolver = _target_only_addi_copy_product_source_resolver(
        items,
        source_lever=source.get("expression"),
        pcode_lever=parsed,
        final_force_phys=final_force,
        attempted_targets=attempted,
        protected_targets=protected,
    )
    if resolver is not None:
        return _target_only_addi_copy_product_resolver_continuation(
            resolver,
            source=source,
            parsed=parsed,
            target_ig=target_ig,
            class_id=class_id,
            attempted_targets=attempted,
            protected_targets=protected,
            final_force_phys=final_force,
            exhaustion=exhaustion,
        )

    return {
        "status": "incomplete",
        "complete": False,
        "kind": "target-only-backprojection-source-probe-continuation",
        "required_evidence_kind": _TARGET_ONLY_ADDI_COPY_PRODUCT_RESOLVER_KIND,
        "source_lever": source.get("expression"),
        "source_kind": source.get("kind"),
        "source_confidence": source.get("confidence"),
        "source_span_status": (
            "pcode-only" if _source_span_missing(source) else "retained-exhausted"
        ),
        "pcode_lever": parsed,
        "target_ig": target_ig,
        "class_id": class_id,
        "attempted_targets": attempted,
        "protected_targets": protected,
        "final_force_phys": final_force,
        "source_file": exhaustion.get("source_file"),
        "retained_probe_count": exhaustion.get("retained_probe_count"),
        "compiled": exhaustion.get("compiled"),
        "skipped": exhaustion.get("skipped"),
        "compile_failures": exhaustion.get("compile_failures"),
        "gate_rejected": exhaustion.get("gate_rejected"),
        "progress_hits": exhaustion.get("progress_hits"),
        "bounded_terminal_blocker": exhaustion.get("terminal_blocker"),
        "resume": exhaustion.get("resume"),
        "missing_evidence": [
            "target-only addi/copy-product source resolver evidence"
        ],
    }


def _target_only_attempted_protected_targets(
    final_force: Mapping[str, int],
    *,
    target_ig: int | None,
) -> tuple[dict[str, int], dict[str, int]]:
    attempted = (
        {str(target_ig): final_force[str(target_ig)]}
        if target_ig is not None and str(target_ig) in final_force
        else {}
    )
    protected = {
        ig: phys for ig, phys in final_force.items() if ig not in attempted
    }
    return attempted, protected


def _target_only_addi_copy_product_source_resolver(
    items: list[dict[str, Any]],
    *,
    source_lever: Any,
    pcode_lever: Mapping[str, int],
    final_force_phys: Mapping[str, int],
    attempted_targets: Mapping[str, int],
    protected_targets: Mapping[str, int],
) -> dict[str, Any] | None:
    if not isinstance(source_lever, str) or not source_lever:
        return None
    expected_force = dict(final_force_phys)
    expected_attempted = dict(attempted_targets)
    expected_protected = dict(protected_targets)
    for item in items:
        for mapping in _walk_mappings(item):
            if mapping.get("kind") != _TARGET_ONLY_ADDI_COPY_PRODUCT_RESOLVER_KIND:
                continue
            if mapping.get("source_lever") != source_lever:
                continue
            resolver_pcode = _normalized_addi_pcode_lever(
                mapping.get("pcode_lever")
            )
            if resolver_pcode != dict(pcode_lever):
                continue
            resolver_force = _normalized_int_mapping(
                mapping.get("final_force_phys")
            )
            if resolver_force != expected_force:
                continue
            resolver_attempted = _normalized_int_mapping(
                mapping.get("attempted_targets")
            )
            if resolver_attempted and resolver_attempted != expected_attempted:
                continue
            resolver_protected = _normalized_int_mapping(
                mapping.get("protected_targets")
            )
            if resolver_protected and resolver_protected != expected_protected:
                continue
            return dict(mapping)
    return None


def _target_only_addi_copy_product_resolver_continuation(
    resolver: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    parsed: Mapping[str, int],
    target_ig: int | None,
    class_id: int | None,
    attempted_targets: Mapping[str, int],
    protected_targets: Mapping[str, int],
    final_force_phys: Mapping[str, int],
    exhaustion: Mapping[str, Any] | None,
) -> dict[str, Any]:
    status = resolver.get("status")
    if not isinstance(status, str) or not status:
        status = "incomplete"
    copy_product_chain = _copy_product_chain(resolver.get("copy_product_chain"))
    source_visible_variants = _source_visible_variants(
        resolver.get("source_visible_variants")
    )
    complete = bool(
        resolver.get("complete") is True
        and status.startswith("terminal")
        and copy_product_chain
        and source_visible_variants
    )
    payload = {
        "status": status,
        "complete": complete,
        "kind": "target-only-backprojection-source-probe-continuation",
        "resolver_kind": _TARGET_ONLY_ADDI_COPY_PRODUCT_RESOLVER_KIND,
        "terminal_blocker": resolver.get("terminal_blocker"),
        "source_lever": source.get("expression"),
        "source_kind": source.get("kind"),
        "source_confidence": source.get("confidence"),
        "source_span_status": (
            "pcode-only" if _source_span_missing(source) else "retained-tested"
        ),
        "pcode_lever": dict(parsed),
        "target_ig": target_ig,
        "class_id": class_id,
        "attempted_targets": dict(attempted_targets),
        "protected_targets": dict(protected_targets),
        "final_force_phys": dict(final_force_phys),
        "copy_product_chain": copy_product_chain,
        "source_visible_variants": source_visible_variants,
        "source_file": resolver.get("source_file"),
        "pcdump": resolver.get("pcdump") or resolver.get("pcdump_path"),
        "baseline_score": resolver.get("baseline_score"),
        "best_score": resolver.get("best_score"),
        "missing_evidence": [],
    }
    if exhaustion is not None:
        payload.update({
            "retained_probe_count": exhaustion.get("retained_probe_count"),
            "compiled": exhaustion.get("compiled"),
            "skipped": exhaustion.get("skipped"),
            "compile_failures": exhaustion.get("compile_failures"),
            "gate_rejected": exhaustion.get("gate_rejected"),
            "progress_hits": exhaustion.get("progress_hits"),
            "bounded_terminal_blocker": exhaustion.get("terminal_blocker"),
            "resume": exhaustion.get("resume"),
        })
    if not complete:
        missing = _string_list(resolver.get("missing_evidence"))
        if not copy_product_chain:
            missing.append("addi/copy-product resolver copy_product_chain")
        if not source_visible_variants:
            missing.append("addi/copy-product resolver source_visible_variants")
        if resolver.get("complete") is not True or not status.startswith("terminal"):
            missing.append("complete terminal addi/copy-product resolver evidence")
        payload["missing_evidence"] = missing or [
            "complete terminal addi/copy-product resolver evidence"
        ]
    return payload


def _normalized_addi_pcode_lever(value: Any) -> dict[str, int] | None:
    if isinstance(value, str):
        return _parse_addi_source_lever(value)
    if not isinstance(value, Mapping):
        return None
    dst = _int_or_none(value.get("dst_virtual"))
    base = _int_or_none(value.get("base_virtual"))
    imm = _int_or_none(value.get("immediate"))
    if dst is None or base is None or imm is None:
        return None
    return {"dst_virtual": dst, "base_virtual": base, "immediate": imm}


def _copy_product_chain(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        expression = raw.get("expression")
        if not isinstance(expression, str) or not expression:
            continue
        entry: dict[str, Any] = {"expression": expression}
        target_ig = _int_or_none(raw.get("target_ig"))
        if target_ig is not None:
            entry["target_ig"] = target_ig
        kind = raw.get("kind")
        if isinstance(kind, str) and kind:
            entry["kind"] = kind
        if raw.get("protected") is True:
            entry["protected"] = True
        if raw.get("source_visible") is not None:
            entry["source_visible"] = bool(raw.get("source_visible"))
        out.append(entry)
    return out


def _source_visible_variants(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        entry: dict[str, Any] = {}
        label = raw.get("label")
        if isinstance(label, str) and label:
            entry["label"] = label
        score = _int_or_none(raw.get("score"))
        if score is not None:
            entry["score"] = score
        target_score = raw.get("target_score")
        if isinstance(target_score, Mapping):
            entry["target_score"] = dict(target_score)
        elif target_score is not None:
            entry["target_score"] = target_score
        target_hits = _int_or_none(raw.get("target_hits"))
        if target_hits is not None:
            entry["target_hits"] = target_hits
        if raw.get("protected_preserved") is not None:
            entry["protected_preserved"] = bool(raw.get("protected_preserved"))
        source_file = raw.get("source_file")
        if isinstance(source_file, str) and source_file:
            entry["source_file"] = source_file
        pcdump = raw.get("pcdump") or raw.get("pcdump_path")
        if isinstance(pcdump, str) and pcdump:
            entry["pcdump"] = pcdump
        if entry:
            out.append(entry)
    return out


def _target_only_c2_sticky_pool_attribution(
    items: list[dict[str, Any]],
    *,
    target_only_backprojection: Mapping[str, Any],
) -> dict[str, Any]:
    divergence = _target_only_c2_terminal_divergence(target_only_backprojection)
    if divergence is None:
        return _empty_target_only_terminal(
            "target-only-c2-sticky-pool-source-attribution"
        )

    lanes = _target_only_sticky_pool_lanes(items, divergence=divergence)
    if not lanes:
        return {
            "status": "incomplete",
            "complete": False,
            "kind": "target-only-c2-sticky-pool-source-attribution",
            "missing_evidence": [
                "matching retained sticky-pool source attribution exhaustion"
            ],
            "target_ig": divergence.get("target_ig"),
            "target_phys": divergence.get("target_phys"),
            "local_target": divergence.get("local_target"),
        }

    source_expressions = _dedupe([
        expression
        for lane in lanes
        for expression in lane.get("source_expressions", [])
        if isinstance(expression, str) and expression
    ])
    upstream_virtuals = sorted({
        int(value)
        for lane in lanes
        for value in lane.get("upstream_virtuals", [])
        if isinstance(value, int) and not isinstance(value, bool)
    })
    return {
        "status": "terminal-non-source-tunable",
        "complete": True,
        "kind": "target-only-c2-sticky-pool-source-attribution",
        "terminal_blocker": "target-only-c2-sticky-pool-source-attribution-terminal",
        "target_ig": divergence.get("target_ig"),
        "target_phys": divergence.get("target_phys"),
        "baseline_phys": divergence.get("baseline_phys"),
        "class_id": divergence.get("class_id"),
        "case": divergence.get("case"),
        "local_target": divergence.get("local_target"),
        "final_force_phys": _normalized_int_mapping(divergence.get("force_phys")),
        "source_expressions": source_expressions,
        "upstream_virtuals": upstream_virtuals,
        "lane_count": len(lanes),
        "evaluated_probe_count": sum(
            _int_count(lane.get("evaluated_probe_count")) for lane in lanes
        ),
        "exact_count": sum(_int_count(lane.get("exact_count")) for lane in lanes),
        "protected_negative_count": sum(
            _int_count(lane.get("protected_negative_count")) for lane in lanes
        ),
        "lost_protected_count": sum(
            _int_count(lane.get("lost_protected_count")) for lane in lanes
        ),
        "no_target_progress_count": sum(
            _int_count(lane.get("no_target_progress_count")) for lane in lanes
        ),
        "lanes": lanes,
        "missing_evidence": [],
    }


def _empty_target_only_terminal(kind: str) -> dict[str, Any]:
    return {
        "status": "not-present",
        "complete": False,
        "kind": kind,
        "missing_evidence": [],
    }


def _target_only_addi_source_lever(
    target_only_backprojection: Mapping[str, Any],
) -> dict[str, Any] | None:
    if target_only_backprojection.get("status") != "source-actionable":
        return None
    for lever in target_only_backprojection.get("source_levers", []) or []:
        if not isinstance(lever, Mapping):
            continue
        source = lever.get("source")
        if not isinstance(source, Mapping):
            continue
        if source.get("kind") != "implicit-temp":
            continue
        if _parse_addi_source_lever(source.get("expression")) is None:
            continue
        return dict(lever)
    return None


def _target_only_c2_terminal_divergence(
    target_only_backprojection: Mapping[str, Any],
) -> dict[str, Any] | None:
    if target_only_backprojection.get("status") != "terminal-non-source-expressible":
        return None
    if target_only_backprojection.get("source_levers"):
        return None
    for divergence in target_only_backprojection.get("divergences", []) or []:
        if not isinstance(divergence, Mapping):
            continue
        if divergence.get("case") == "C2":
            return dict(divergence)
    return None


def _parse_addi_source_lever(value: Any) -> dict[str, int] | None:
    if not isinstance(value, str):
        return None
    match = _ADDI_SOURCE_LEVER_RE.match(value.strip())
    if match is None:
        return None
    return {
        "dst_virtual": int(match.group("dst")),
        "base_virtual": int(match.group("base")),
        "immediate": int(match.group("imm")),
    }


def _source_span_missing(source: Mapping[str, Any]) -> bool:
    return not any(
        source.get(key) is not None
        for key in ("source_file", "source_line", "source_col")
    )


def _target_only_force_phys(
    target_only_backprojection: Mapping[str, Any],
    *,
    class_id: int | None,
) -> dict[str, int]:
    for divergence in target_only_backprojection.get("divergences", []) or []:
        if not isinstance(divergence, Mapping):
            continue
        if class_id is not None and divergence.get("class_id") != class_id:
            continue
        force_phys = _normalized_int_mapping(divergence.get("force_phys"))
        if force_phys:
            return force_phys
    force: dict[str, int] = {}
    for target in target_only_backprojection.get("force_targets", []) or []:
        if not isinstance(target, Mapping):
            continue
        if class_id is not None and target.get("class_id") != class_id:
            continue
        ig_idx = _int_or_none(target.get("ig_idx"))
        desired = _int_or_none(target.get("desired_phys"))
        if ig_idx is not None and desired is not None:
            force[str(ig_idx)] = desired
    return force


def _target_only_simplify_probe_exhaustion(
    items: list[dict[str, Any]],
    *,
    expected_force_phys: Mapping[str, int],
) -> dict[str, Any] | None:
    for item in items:
        for mapping in _walk_mappings(item):
            if mapping.get("terminal_blocker") != (
                "no-retained-candidate-improved-residual-force-phys"
            ):
                continue
            if mapping.get("retained_mode") is not True:
                continue
            residual_force_phys = mapping.get("residual_force_phys")
            if not isinstance(residual_force_phys, Mapping) or not residual_force_phys:
                continue
            normalized_residual_force = _normalized_int_mapping(residual_force_phys)
            if normalized_residual_force != dict(expected_force_phys):
                continue
            summary = mapping.get("summary")
            if not isinstance(summary, Mapping):
                continue
            compiled = _int_count(summary.get("compiled"))
            if compiled <= 0:
                continue
            progress_hits = _int_count(summary.get("progress_hits"))
            if progress_hits != 0:
                continue
            ranked = mapping.get("ranked_probes")
            return {
                "terminal_blocker": mapping.get("terminal_blocker"),
                "source_file": mapping.get("source_file"),
                "retained_probe_count": len(ranked) if isinstance(ranked, list) else 0,
                "compiled": compiled,
                "skipped": _int_count(summary.get("skipped")),
                "compile_failures": _int_count(summary.get("compile_failures")),
                "gate_rejected": _int_count(summary.get("gate_rejected")),
                "progress_hits": progress_hits,
                "residual_force_phys": normalized_residual_force,
                "resume": mapping.get("resume") if isinstance(
                    mapping.get("resume"), Mapping
                ) else None,
            }
    return None


def _target_only_sticky_pool_lanes(
    items: list[dict[str, Any]],
    *,
    divergence: Mapping[str, Any],
) -> list[dict[str, Any]]:
    target_ig = _int_or_none(divergence.get("target_ig"))
    target_phys = _int_or_none(divergence.get("target_phys"))
    if target_ig is None or target_phys is None:
        return []
    expected_force_phys = _normalized_int_mapping(divergence.get("force_phys"))
    expected_protected = {
        ig: phys for ig, phys in expected_force_phys.items() if ig != str(target_ig)
    }
    lanes: list[dict[str, Any]] = []
    for item in items:
        for summary in _iter_target_live_range_summaries(item):
            if summary.get("kind") != _TARGET_LIVE_RANGE_KIND:
                continue
            if summary.get("status") != "blocked":
                continue
            terminal_blocker = summary.get("terminal_blocker")
            if terminal_blocker not in _TARGET_LIVE_RANGE_BLOCKERS:
                continue
            attempted = _normalized_int_mapping(summary.get("attempted_targets"))
            if attempted.get(str(target_ig)) != target_phys:
                continue
            protected = _normalized_int_mapping(summary.get("protected_targets"))
            if any(
                protected.get(ig) != phys
                for ig, phys in expected_protected.items()
            ):
                continue
            evaluated = _int_count(summary.get("evaluated_probe_count"))
            unscoreable = _int_count(summary.get("unscoreable_count"))
            if evaluated <= 0 or evaluated <= unscoreable:
                continue
            if _int_count(summary.get("exact_count")):
                continue
            lane = {
                "kind": summary.get("kind"),
                "status": summary.get("status"),
                "terminal_blocker": terminal_blocker,
                "attempted_targets": attempted,
                "protected_targets": protected,
                "evaluated_probe_count": evaluated,
                "unscoreable_count": unscoreable,
                "exact_count": _int_count(summary.get("exact_count")),
                "protected_negative_count": _int_count(
                    summary.get("protected_negative_count")
                ),
                "lost_protected_count": _int_count(
                    summary.get("lost_protected_count")
                ),
                "no_target_progress_count": _int_count(
                    summary.get("no_target_progress_count")
                ),
                "source_expressions": _sticky_pool_source_expressions(summary),
                "upstream_virtuals": _sticky_pool_upstream_virtuals(summary),
                "probe_labels": _sticky_pool_probe_labels(summary),
                "source_owner_terminal_spans": [
                    dict(span)
                    for span in summary.get("source_owner_terminal_spans", []) or []
                    if isinstance(span, Mapping)
                ],
            }
            lanes.append(lane)
    return lanes


def _sticky_pool_source_expressions(summary: Mapping[str, Any]) -> list[str]:
    expressions: list[str] = []
    for raw_span in summary.get("exhausted_strategy_spans", []) or []:
        if not isinstance(raw_span, Mapping):
            continue
        ranked = raw_span.get("ranked_repair_candidate")
        if not isinstance(ranked, Mapping):
            continue
        for key in (
            "source_expression",
            "paired_source_expression",
            "address_expression",
            "rewritten_expression",
        ):
            value = ranked.get(key)
            if isinstance(value, str) and value and value not in expressions:
                expressions.append(value)
    for raw_span in summary.get("source_owner_terminal_spans", []) or []:
        if not isinstance(raw_span, Mapping):
            continue
        for key in ("source_expression", "paired_source_expression"):
            value = raw_span.get(key)
            if isinstance(value, str) and value and value not in expressions:
                expressions.append(value)
    for candidate in summary.get("best_retained_candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        ranked = candidate.get("ranked_repair_candidate")
        if not isinstance(ranked, Mapping):
            continue
        value = ranked.get("source_expression")
        if isinstance(value, str) and value and value not in expressions:
            expressions.append(value)
    return expressions


def _sticky_pool_upstream_virtuals(summary: Mapping[str, Any]) -> list[int]:
    virtuals: set[int] = set()
    for mapping_key in ("attempted_targets", "protected_targets"):
        for key in _normalized_int_mapping(summary.get(mapping_key)):
            value = _int_or_none(key)
            if value is not None:
                virtuals.add(value)
    for raw_span in summary.get("source_owner_terminal_spans", []) or []:
        if not isinstance(raw_span, Mapping):
            continue
        for key in ("target_ig", "interferer_ig"):
            value = _int_or_none(raw_span.get(key))
            if value is not None:
                virtuals.add(value)
    for candidate in summary.get("best_retained_candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        goal = candidate.get("repair_goal")
        if not isinstance(goal, Mapping):
            continue
        for key in ("target_ig", "interferer_ig", "paired_interferer_ig"):
            value = _int_or_none(goal.get(key))
            if value is not None:
                virtuals.add(value)
    return sorted(virtuals)


def _sticky_pool_probe_labels(summary: Mapping[str, Any]) -> list[str]:
    labels: list[str] = []
    for candidate in summary.get("best_retained_candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        probe_id = candidate.get("probe_id")
        if isinstance(probe_id, str) and probe_id and probe_id not in labels:
            labels.append(probe_id)
    return labels


def _node_set_exhaustion(items: list[dict[str, Any]]) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for item in items:
        if item.get("wrong_register_exhausted") is True:
            summaries.append(_node_set_exhaustion_summary(
                item,
                terminal_reason=str(
                    item.get("terminal_reason") or "all-wrong-register"
                ),
            ))
            continue
        summary = _mixed_negative_node_set_exhaustion(item)
        if summary is not None:
            summaries.append(summary)

    return {
        "complete": bool(summaries),
        "terminal_reason": (
            summaries[0]["terminal_reason"] if summaries else None
        ),
        "summaries": summaries,
        "objective_counts": (
            summaries[0].get("objective_counts") if summaries else None
        ),
    }


def _mixed_negative_node_set_exhaustion(
    item: Mapping[str, Any],
) -> dict[str, Any] | None:
    if item.get("status") != "exhausted":
        return None
    if item.get("exhaustive") is not True:
        return None
    if item.get("stop_reason") is not None:
        return None
    if _nonnegative_int(item.get("pending_count")) != 0:
        return None
    if _nonnegative_int(item.get("realized_count")) != 0:
        return None

    objective_counts_raw = item.get("objective_counts")
    if not isinstance(objective_counts_raw, Mapping):
        return None
    objective_counts = {
        str(key): _nonnegative_int(value)
        for key, value in objective_counts_raw.items()
    }
    allowed = {"wrong-register", "missing-target"}
    if not objective_counts or any(
        key not in allowed for key, value in objective_counts.items() if value
    ):
        return None

    negative_count = sum(objective_counts.values())
    if negative_count <= 0:
        return None
    evaluated_count = _nonnegative_int(
        item.get("evaluated_count", item.get("scored_count"))
    )
    generated_count = _nonnegative_int(item.get("generated_count"))
    if evaluated_count and negative_count != evaluated_count:
        return None
    if generated_count and negative_count != generated_count:
        return None

    terminal_reason = (
        "all-wrong-register"
        if objective_counts.get("missing-target", 0) == 0
        else "wrong-register-or-missing-target"
    )
    return _node_set_exhaustion_summary(
        item,
        terminal_reason=terminal_reason,
        objective_counts=objective_counts,
    )


def _node_set_exhaustion_summary(
    item: Mapping[str, Any],
    *,
    terminal_reason: str,
    objective_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    counts = objective_counts
    if counts is None:
        raw_counts = item.get("objective_counts")
        counts = {
            str(key): _nonnegative_int(value)
            for key, value in raw_counts.items()
        } if isinstance(raw_counts, Mapping) else {}
    request = item.get("request")
    request_summary = dict(request) if isinstance(request, Mapping) else None
    return {
        "function": item.get("function"),
        "terminal_reason": terminal_reason,
        "objective_counts": dict(counts),
        "generated_count": item.get("generated_count"),
        "evaluated_count": item.get("evaluated_count", item.get("scored_count")),
        "pending_count": item.get("pending_count"),
        "request": request_summary,
    }


def _transform_exhausted(items: list[dict[str, Any]]) -> bool:
    for item in items:
        if (
            item.get("source_shape_exhausted") is True
            and item.get("status") in {"actionable", "practical-ceiling"}
            and not item.get("missing_evidence")
        ):
            return True
        summary = item.get("validation_summary")
        if not isinstance(summary, Mapping):
            continue
        if summary.get("stop_condition") != "exhausted-negative-evidence":
            continue
        remaining = summary.get("remaining_probe_ids")
        if remaining not in ([], ()):
            continue
        node_summary = item.get("node_set_delta_summary")
        if isinstance(node_summary, Mapping):
            if _nonnegative_int(node_summary.get("omitted_count")):
                continue
            if _nonnegative_int(node_summary.get("capped_count")):
                continue
        return True
    return False


def _select_order_fpr_case_c_exhaustion(
    items: list[dict[str, Any]],
    *,
    node_delta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    expected_targets = _node_delta_force_phys_targets(node_delta)
    fallback: dict[str, Any] | None = None
    for item in items:
        for mapping in _walk_mappings(item):
            summary = mapping.get("terminal_exhaustion_summary")
            if not isinstance(summary, Mapping):
                continue
            if summary.get("kind") != _DRAW_FPR_CASE_C_SOURCE_EXHAUSTION_KIND:
                continue
            targets = _normalized_int_mapping(
                summary.get("force_phys_targets")
                or mapping.get("force_phys_targets")
            )
            payload = {
                "status": summary.get("status"),
                "kind": summary.get("kind"),
                "complete": False,
                "force_phys_targets": targets,
                "expected_force_phys_targets": expected_targets,
                "diagnostic_bucket_counts": summary.get(
                    "diagnostic_bucket_counts"
                ),
                "best_retained_variants": summary.get("best_retained_variants"),
                "next_source_lever_classes": summary.get(
                    "next_source_lever_classes"
                ),
                "terminal_blocker": summary.get("terminal_blocker"),
                "covered": False,
            }
            if fallback is None:
                fallback = payload
            if (
                summary.get("status") == "blocked"
                and expected_targets
                and targets == expected_targets
            ):
                payload["complete"] = True
                payload["covered"] = True
                return payload
    if fallback is not None:
        return fallback
    return {
        "status": "not-present",
        "kind": _DRAW_FPR_CASE_C_SOURCE_EXHAUSTION_KIND,
        "complete": False,
        "covered": False,
        "force_phys_targets": {},
        "expected_force_phys_targets": expected_targets,
    }


def _node_set_frontier_coverage(
    items: list[dict[str, Any]],
    *,
    node_delta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    missing = _node_set_missing_virtuals(node_delta)
    if not missing:
        return {
            "status": "not-present",
            "complete": False,
            "missing_evidence": [],
        }
    bindable: list[int] = []
    pcode_only: list[int] = []
    for entry in missing:
        ig_idx = _entry_ig_idx(entry)
        if ig_idx is None:
            continue
        if _is_pcode_only_implicit_temp_missing(entry):
            pcode_only.append(ig_idx)
        else:
            bindable.append(ig_idx)
    class_id = _int_or_none(node_delta.get("class_id")) if node_delta else None
    draw_like = (
        class_id == _FPR_CLASS_ID
        and len(bindable) >= 2
        and bool(pcode_only)
    )
    if not draw_like:
        return {
            "status": "not-present",
            "complete": False,
            "bindable_targets": bindable,
            "pcode_only_targets": pcode_only,
            "missing_evidence": [],
        }

    exhaustive_by_ig = _node_set_exhaustive_targets(items)
    covered_bindable = [
        ig_idx for ig_idx in bindable if exhaustive_by_ig.get(ig_idx) is not None
    ]
    coupled = _coupled_node_set_summary(items, bindable)
    missing_evidence: list[str] = []
    if len(bindable) >= 2:
        if coupled is None:
            missing_evidence.append(
                "coupled node-set-split evidence for bindable Draw FPR targets"
            )
        elif coupled.get("bounded") is True:
            missing_evidence.append(
                "bounded coupled node-set-split evidence for bindable Draw FPR targets"
            )

    complete = (
        bool(bindable)
        and set(covered_bindable) == set(bindable)
        and (
            len(bindable) < 2
            or (
                coupled is not None
                and coupled.get("bounded") is not True
                and coupled.get("exhaustive") is True
            )
        )
    )
    return {
        "status": "complete" if complete else "incomplete",
        "complete": complete,
        "bindable_targets": bindable,
        "pcode_only_targets": pcode_only,
        "covered_bindable_targets": covered_bindable,
        "missing_bindable_targets": [
            ig_idx for ig_idx in bindable if ig_idx not in covered_bindable
        ],
        "coupled_summary": coupled,
        "missing_evidence": missing_evidence,
    }


def _node_delta_force_phys_targets(
    node_delta: Mapping[str, Any] | None,
) -> dict[str, int]:
    targets: dict[str, int] = {}
    for entry in _node_set_missing_virtuals(node_delta):
        ig_idx = _entry_ig_idx(entry)
        desired = _entry_desired_phys(entry)
        if ig_idx is not None and desired is not None:
            targets[str(ig_idx)] = desired
    return targets


def _entry_desired_phys(entry: Mapping[str, Any]) -> int | None:
    for key in ("desired_phys", "target_phys", "target_reg_num"):
        value = _int_or_none(entry.get(key))
        if value is not None:
            return value
    desired_registers = entry.get("desired_registers")
    if isinstance(desired_registers, list):
        for value in desired_registers:
            parsed = _register_num(value)
            if parsed is not None:
                return parsed
    return _register_num(entry.get("target_reg"))


def _register_num(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped[0] in {"r", "f"}:
        stripped = stripped[1:]
    return int(stripped) if stripped.isdigit() else None


def _node_set_exhaustive_targets(
    items: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    covered: dict[int, dict[str, Any]] = {}
    for item in items:
        summary = None
        if item.get("wrong_register_exhausted") is True:
            summary = _node_set_exhaustion_summary(
                item,
                terminal_reason=str(
                    item.get("terminal_reason") or "all-wrong-register"
                ),
            )
        else:
            summary = _mixed_negative_node_set_exhaustion(item)
        if summary is None:
            continue
        request = summary.get("request")
        if not isinstance(request, Mapping):
            continue
        ig_idx = _int_or_none(request.get("target_ig"))
        if ig_idx is not None:
            covered[ig_idx] = summary
    return covered


def _coupled_node_set_summary(
    items: list[dict[str, Any]],
    bindable_targets: list[int],
) -> dict[str, Any] | None:
    required = set(bindable_targets)
    if len(required) < 2:
        return None
    for item in items:
        coupled_requests = item.get("coupled_requests")
        if not isinstance(coupled_requests, list) or len(coupled_requests) < 2:
            continue
        request_targets = {
            _int_or_none(req.get("target_ig"))
            for req in coupled_requests
            if isinstance(req, Mapping)
        }
        request_targets.discard(None)
        if not required.issubset(request_targets):
            continue
        stop_condition = item.get("stop_condition")
        stop_kind = (
            stop_condition.get("kind") if isinstance(stop_condition, Mapping)
            else item.get("stop_reason")
        )
        return {
            "status": item.get("status"),
            "exhaustive": (
                item.get("exhaustive") is True
                and stop_kind is None
                and _nonnegative_int(item.get("pending_count")) == 0
            ),
            "bounded": stop_kind in _BOUNDED_STOP_KINDS,
            "stop_reason": stop_kind,
            "resume_command": (
                stop_condition.get("resume_command")
                if isinstance(stop_condition, Mapping)
                else None
            ),
            "target_igs": sorted(int(ig) for ig in request_targets),
            "generated_count": item.get("generated_count"),
            "evaluated_count": item.get(
                "evaluated_count",
                item.get("scored_count"),
            ),
        }
    return None


def _skipped_source_evidence_count(items: list[dict[str, Any]]) -> int:
    count = 0
    for item in items:
        summary = item.get("node_set_delta_summary")
        if isinstance(summary, Mapping):
            count += _nonnegative_int(summary.get("skipped_count"))
    return count


def _copy_survived_repair_terminal(
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for item in items:
        for mapping in _walk_mappings(item):
            candidate_raw = mapping.get("copy_survived_repair")
            if isinstance(candidate_raw, Mapping):
                candidate = candidate_raw
            elif mapping.get("transform_category") == "copy-survived":
                candidate = mapping
            else:
                continue
            if candidate.get("status") != "terminal-blocker":
                continue
            if candidate.get("trace_status") not in (None, "copy-found"):
                continue
            if candidate.get("transform_category") not in (None, "copy-survived"):
                continue
            terminal_blocker = _non_empty_str(candidate.get("terminal_blocker"))
            if terminal_blocker is None:
                continue
            return {
                "status": "terminal-blocker",
                "terminal_blocker": terminal_blocker,
                "trace_status": candidate.get("trace_status"),
                "transform_category": candidate.get("transform_category"),
                "likely_cause": candidate.get("likely_cause"),
                "register_class": candidate.get("register_class"),
                "class_id": _int_or_none(candidate.get("class_id")),
                "from_virtual": _first_int(
                    candidate.get("from_virtual"),
                    candidate.get("from_ig_idx"),
                ),
                "to_virtual": _first_int(
                    candidate.get("to_virtual"),
                    candidate.get("to_ig_idx"),
                ),
                "from_assigned_reg": _int_or_none(
                    candidate.get("from_assigned_reg")
                ),
                "to_assigned_reg": _int_or_none(candidate.get("to_assigned_reg")),
                "scored_count": _int_or_none(candidate.get("scored_count")),
                "failed_count": _int_or_none(candidate.get("failed_count")),
                "pointer_reset_probe_count": _int_or_none(
                    candidate.get("pointer_reset_probe_count")
                ),
                "pointer_reset_failed_count": _int_or_none(
                    candidate.get("pointer_reset_failed_count")
                ),
            }
    return None


def _node_set_unsplittable_implicit_temp_frontier(
    items: list[dict[str, Any]],
    node_delta: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    missing = _node_set_missing_virtuals(node_delta)
    if not missing:
        return None
    if not all(_is_pcode_only_implicit_temp_missing(entry) for entry in missing):
        return None

    for item in items:
        for mapping in _walk_mappings(item):
            if mapping.get("stop_reason") != "no-coupled-probes":
                continue
            reason = _non_empty_str(mapping.get("blocked_reason")) or ""
            request = mapping.get("request")
            if not reason and isinstance(request, Mapping):
                reason = _non_empty_str(request.get("blocked_reason")) or ""
            in_place = mapping.get("in_place_recolor")
            in_place_status = (
                in_place.get("status") if isinstance(in_place, Mapping) else None
            )
            if "found 0" not in reason and (
                in_place_status != "insufficient-source-bindings"
            ):
                continue
            coupled_requests = mapping.get("coupled_requests")
            if isinstance(coupled_requests, list) and coupled_requests:
                continue
            if coupled_requests not in (None, [], ()):
                continue
            if any(
                key in mapping and _int_count(mapping.get(key)) != 0
                for key in (
                    "generated_count",
                    "scored_count",
                    "evaluated_count",
                    "pending_count",
                    "realized_count",
                )
            ):
                continue
            return {
                "status": "not-applicable",
                "reason": "zero-bindable-implicit-temp-frontier",
                "stop_reason": mapping.get("stop_reason"),
                "blocked_reason": reason,
                "target_igs": [
                    ig for ig in (_entry_ig_idx(entry) for entry in missing)
                    if ig is not None
                ],
                "missing_count": len(missing),
                "in_place_recolor_status": in_place_status,
            }
    return None


def _node_set_missing_virtuals(
    node_delta: Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    if not isinstance(node_delta, Mapping):
        return []
    missing = node_delta.get("missing_virtuals")
    if not isinstance(missing, list):
        return []
    return [entry for entry in missing if isinstance(entry, Mapping)]


def _is_pcode_only_implicit_temp_missing(entry: Mapping[str, Any]) -> bool:
    source = entry.get("source")
    if not isinstance(source, Mapping):
        source = entry
    source_kind = source.get("kind") or entry.get("source_kind")
    if source_kind not in {"implicit-temp", "fpr-temp", "copy/coalesce-product"}:
        return False
    if any(
        _non_empty_str(source.get(key) or entry.get(key)) is not None
        for key in ("name", "source_name", "var_name", "type", "source_type")
    ):
        return False
    if any(
        _int_or_none(source.get(key, entry.get(key))) is not None
        for key in ("source_line", "line", "source_col")
    ):
        return False
    expression = _non_empty_str(
        source.get("expression")
        or entry.get("expression")
        or entry.get("source_expression")
    )
    if expression is None:
        return False
    first_def = source.get("first_def") or entry.get("first_def")
    pcode_first_def = source.get("pcode_first_def") or entry.get("pcode_first_def")
    return (
        isinstance(first_def, Mapping)
        or pcode_first_def is not None
        or source.get("confidence") == "pcode-first-def"
        or entry.get("confidence") == "pcode-first-def"
    )


def _residual_case_c_source_repair(
    items: list[dict[str, Any]],
    *,
    node_delta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    blocked_spans: list[dict[str, Any]] = []
    materialized_actions: list[dict[str, Any]] = []
    unsupported_source_owner_spans: list[dict[str, Any]] = []
    bridge_present = False
    bridge_source_files: list[str] = []
    terminal_exhaustion: dict[str, Any] | None = None
    post_source_owner = _post_source_owner_exhaustion(items)
    common_subexpr = _common_subexpr_coalesce_exhaustion(items)
    target_live_range = _target_live_range_repair_exhaustion(items)
    copy_survived = _copy_survived_repair_terminal(items)
    unsplittable = _node_set_unsplittable_implicit_temp_frontier(
        items,
        node_delta,
    )

    for item in items:
        bridge = item.get("source_bridge_summary")
        if not isinstance(bridge, Mapping):
            continue
        bridge_present = True
        if (
            bridge.get("status") != "blocked"
            or bridge.get("dominant_blocker") != "source-probes-exhausted"
        ):
            continue
        for lead in bridge.get("leads", []) or []:
            if not isinstance(lead, Mapping):
                continue
            source = _lead_source_mapping(lead)
            if source is None:
                continue
            source_file = source.get("source_file")
            if isinstance(source_file, str) and source_file not in bridge_source_files:
                bridge_source_files.append(source_file)
            if lead.get("source_actionable") is True:
                action = _residual_case_c_materialized_action(lead, source)
                if action is not None:
                    materialized_actions.append(action)
                continue
            terminal_blocker = _lead_terminal_blocker(lead)
            source_kind = source.get("kind")
            if (
                terminal_blocker == "implicit-temp-no-safe-source-move"
                and source_kind in {"implicit-temp", "copy/coalesce-product"}
            ):
                blocked_spans.append(
                    _residual_case_c_blocked_span(lead, source, terminal_blocker)
                )
        summary = item.get("terminal_exhaustion_summary")
        if (
            isinstance(summary, Mapping)
            and summary.get("terminal_blocker") == "transform-family-exhausted"
        ):
            terminal_exhaustion = {
                "terminal_blocker": summary.get("terminal_blocker"),
                "dominant_blocker": summary.get("dominant_blocker"),
                "blocker_targets": summary.get("blocker_targets"),
            }
            bridge_source_files.extend(_bridge_retained_source_files(summary))

    if post_source_owner is not None:
        materialized_actions.extend(post_source_owner["materialized_actions"])
        bridge_source_files.extend(post_source_owner["source_files"])
        if terminal_exhaustion is None:
            terminal_exhaustion = {
                "terminal_blocker": post_source_owner["terminal_blocker"],
                "dominant_blocker": "post-source-owner-backtrack",
                "blocker_targets": list(post_source_owner["attempted_targets"]),
            }

    if common_subexpr is not None:
        materialized_actions.extend(common_subexpr["materialized_actions"])
        bridge_source_files.extend(common_subexpr["source_files"])
        if terminal_exhaustion is None:
            terminal_exhaustion = {
                "terminal_blocker": common_subexpr["terminal_blocker"],
                "dominant_blocker": "common-subexpr-coalesce-source",
                "blocker_targets": list(common_subexpr["attempted_targets"]),
            }

    if target_live_range is not None:
        materialized_actions.extend(target_live_range["materialized_actions"])
        unsupported_source_owner_spans.extend(
            target_live_range["unsupported_source_owner_spans"]
        )
        bridge_source_files.extend(target_live_range["source_files"])
        if terminal_exhaustion is None:
            terminal_exhaustion = {
                "terminal_blocker": target_live_range["terminal_blocker"],
                "dominant_blocker": (
                    target_live_range.get("dominant_blocker")
                    or target_live_range["terminal_blocker"]
                ),
                "blocker_targets": list(target_live_range["attempted_targets"]),
            }

    blocked_spans = _dedupe_residual_case_c_spans(blocked_spans)
    materialized_actions = _dedupe_residual_case_c_actions(materialized_actions)
    unsupported_source_owner_spans = (
        _dedupe_residual_case_c_unsupported_source_owner_spans(
            unsupported_source_owner_spans
        )
    )
    simplify = _residual_case_c_simplify_exhaustion(
        items,
        bridge_source_files=bridge_source_files,
    )
    live_implicit_temp_terminal = bool(
        terminal_exhaustion is not None
        and materialized_actions
        and copy_survived is not None
        and unsplittable is not None
    )
    live_implicit_temp_candidate = bool(
        terminal_exhaustion is not None
        and materialized_actions
        and (copy_survived is not None or unsplittable is not None)
    )
    complete = bool(
        post_source_owner is not None
        or common_subexpr is not None
        or target_live_range is not None
        or live_implicit_temp_terminal
        or (
            blocked_spans
            and bridge_source_files
            and terminal_exhaustion is not None
            and simplify is not None
        )
    )
    if (
        not bridge_present
        and simplify is None
        and post_source_owner is None
        and common_subexpr is None
        and target_live_range is None
    ):
        return {
            "status": "not-present",
            "complete": False,
            "terminal_blocker": None,
            "blocked_source_spans": [],
            "materialized_actions": [],
            "unsupported_source_owner_spans": [],
            "simplify_order_exhaustion": None,
            "terminal_exhaustion": None,
            "post_source_owner_exhaustion": None,
            "common_subexpr_coalesce_exhaustion": None,
            "target_live_range_repair_exhaustion": None,
            "copy_survived_repair": None,
            "node_set_unsplittable_frontier": None,
            "terminal_stack": None,
            "terminal_stack_candidate": None,
            "missing_evidence": [],
        }

    missing: list[str] = []
    if (
        post_source_owner is None
        and common_subexpr is None
        and target_live_range is None
    ):
        if not bridge_present:
            missing.append("select-order source_bridge_summary")
        elif not blocked_spans:
            missing.append("blocked implicit-temp/copy-product source span")
        if bridge_present and not bridge_source_files:
            missing.append("select-order best retained source identity")
        if simplify is None:
            missing.append("matching retained simplify-order no-improvement exhaustion")
        if live_implicit_temp_candidate:
            if unsplittable is None:
                missing.append("zero-bindable implicit-temp node-set split evidence")
            if copy_survived is None:
                missing.append("copy-survived pointer-reset terminal evidence")
    if complete:
        missing = []

    status = (
        "terminal-current-source-shape-ceiling"
        if complete else (
            "incomplete" if bridge_present or simplify is not None else "not-present"
        )
    )
    return {
        "status": status,
        "complete": complete,
        "terminal_blocker": (
            "current-source-shape-allocator-ceiling" if complete else None
        ),
        "blocked_source_spans": blocked_spans,
        "materialized_actions": materialized_actions,
        "unsupported_source_owner_spans": unsupported_source_owner_spans,
        "simplify_order_exhaustion": simplify,
        "terminal_exhaustion": terminal_exhaustion,
        "post_source_owner_exhaustion": post_source_owner,
        "common_subexpr_coalesce_exhaustion": common_subexpr,
        "target_live_range_repair_exhaustion": target_live_range,
        "copy_survived_repair": copy_survived,
        "node_set_unsplittable_frontier": unsplittable,
        "terminal_stack": (
            "live-implicit-temp-copy-survived"
            if live_implicit_temp_terminal else None
        ),
        "terminal_stack_candidate": (
            "live-implicit-temp-copy-survived"
            if live_implicit_temp_candidate else None
        ),
        "missing_evidence": missing,
    }


_POST_SOURCE_OWNER_KIND = "retained-source-case-c-post-source-owner-backtrack"
_POST_SOURCE_OWNER_BLOCKERS = {
    "no-alternate-source-owner",
    "post-source-owner-exhausted",
}
_COMMON_SUBEXPR_COALESCE_KIND = "retained-gpr-common-subexpr-coalesce-source"
_COMMON_SUBEXPR_COALESCE_BLOCKERS = {
    "common-subexpr-coalesce-source-probes-exhausted",
    "common-subexpr-source-owner-probes-exhausted",
}
_TARGET_LIVE_RANGE_KIND = "retained-source-case-c-target-live-range-interference"
_TARGET_LIVE_RANGE_BLOCKERS = {
    "blocker-color-chain-source-probes-exhausted",
    "target-aware-live-range-interference-probes-exhausted",
}


def _iter_post_source_owner_summaries(
    item: Mapping[str, Any],
) -> Iterable[Mapping[str, Any]]:
    summary = item.get("retained_case_c_post_source_owner_backtrack_summary")
    if isinstance(summary, Mapping):
        yield summary
    validation_summary = item.get("validation_summary")
    if isinstance(validation_summary, Mapping):
        nested = validation_summary.get(
            "retained_case_c_post_source_owner_backtrack_summary"
        )
        if isinstance(nested, Mapping):
            yield nested


def _post_source_owner_exhaustion(
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for item in items:
        for summary in _iter_post_source_owner_summaries(item):
            if summary.get("kind") != _POST_SOURCE_OWNER_KIND:
                continue
            terminal_blocker = summary.get("terminal_blocker")
            if terminal_blocker not in _POST_SOURCE_OWNER_BLOCKERS:
                continue
            status = summary.get("status")
            evaluated = _int_count(summary.get("evaluated_probe_count"))
            unscoreable = _int_count(summary.get("unscoreable_count"))
            if status == "scored-negative" and evaluated <= unscoreable:
                continue
            if status not in {"scored-negative", "terminal-blocked"}:
                continue
            attempted_targets = _normalized_int_mapping(
                summary.get("attempted_targets")
            )
            protected_targets = _normalized_int_mapping(
                summary.get("protected_targets")
            )
            candidates = [
                candidate
                for candidate in summary.get("best_retained_candidates", []) or []
                if isinstance(candidate, Mapping)
            ]
            actions = _post_source_owner_materialized_actions(
                candidates,
                attempted_targets=attempted_targets,
            )
            source_files = _post_source_owner_source_files(candidates)
            skipped_labels = _post_source_owner_skipped_labels(candidates)
            return {
                "kind": summary.get("kind"),
                "status": status,
                "terminal_blocker": terminal_blocker,
                "evaluated_probe_count": evaluated,
                "exact_count": _int_count(summary.get("exact_count")),
                "lost_protected_count": _int_count(
                    summary.get("lost_protected_count")
                ),
                "unscoreable_count": unscoreable,
                "attempted_targets": attempted_targets,
                "protected_targets": protected_targets,
                "skipped_current_owner_labels": skipped_labels,
                "materialized_actions": actions,
                "source_files": source_files,
                "best_retained_candidates": [dict(candidate) for candidate in candidates],
            }
    return None


def _iter_common_subexpr_coalesce_summaries(
    item: Mapping[str, Any],
) -> Iterable[Mapping[str, Any]]:
    summary = item.get("retained_gpr_common_subexpr_coalesce_source_summary")
    if isinstance(summary, Mapping):
        yield summary
    validation_summary = item.get("validation_summary")
    if isinstance(validation_summary, Mapping):
        nested = validation_summary.get(
            "retained_gpr_common_subexpr_coalesce_source_summary"
        )
        if isinstance(nested, Mapping):
            yield nested


def _common_subexpr_coalesce_exhaustion(
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for item in items:
        for summary in _iter_common_subexpr_coalesce_summaries(item):
            if summary.get("kind") != _COMMON_SUBEXPR_COALESCE_KIND:
                continue
            terminal_blocker = summary.get("terminal_blocker")
            if terminal_blocker not in _COMMON_SUBEXPR_COALESCE_BLOCKERS:
                continue
            status = summary.get("status")
            if status not in {"scored-negative", "terminal-blocked"}:
                continue
            evaluated = _int_count(summary.get("evaluated_probe_count"))
            if status == "scored-negative" and evaluated <= 0:
                continue
            attempted_targets = _normalized_int_mapping(
                summary.get("attempted_targets")
            )
            protected_targets = _normalized_int_mapping(
                summary.get("protected_targets")
            )
            candidates = [
                candidate
                for candidate in summary.get("best_retained_candidates", []) or []
                if isinstance(candidate, Mapping)
            ]
            if not candidates:
                candidates = [
                    candidate
                    for candidate in summary.get("coalesce_candidates", []) or []
                    if isinstance(candidate, Mapping)
                ]
            return {
                "kind": summary.get("kind"),
                "status": status,
                "terminal_blocker": terminal_blocker,
                "evaluated_probe_count": evaluated,
                "exact_count": _int_count(summary.get("exact_count")),
                "materialized_probe_count": _int_count(
                    summary.get("materialized_probe_count")
                ),
                "attempted_targets": attempted_targets,
                "protected_targets": protected_targets,
                "materialized_actions": (
                    _common_subexpr_coalesce_materialized_actions(
                        candidates,
                        attempted_targets=attempted_targets,
                    )
                ),
                "source_files": _post_source_owner_source_files(candidates),
                "best_retained_candidates": [dict(candidate) for candidate in candidates],
            }
    return None


def _common_subexpr_coalesce_materialized_actions(
    candidates: list[Mapping[str, Any]],
    *,
    attempted_targets: Mapping[str, int],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    target_igs = sorted(int(key) for key in attempted_targets)
    for candidate in candidates:
        probe_id = candidate.get("probe_id")
        if not isinstance(probe_id, str) or not probe_id:
            continue
        source_hunks = candidate.get("source_hunks")
        source_expression = None
        if isinstance(source_hunks, list):
            for hunk in source_hunks:
                if not isinstance(hunk, Mapping):
                    continue
                replacement = hunk.get("replacement_text")
                if isinstance(replacement, str) and replacement:
                    source_expression = replacement
                    break
        actions.append({
            "target_igs": target_igs,
            "source_kind": candidate.get("source_owner_strategy"),
            "source_expression": source_expression,
            "probe_labels": [probe_id],
        })
    return actions


def _iter_target_live_range_summaries(
    item: Mapping[str, Any],
) -> Iterable[Mapping[str, Any]]:
    summary = item.get("retained_case_c_target_live_range_repair_summary")
    if isinstance(summary, Mapping):
        yield summary
    validation_summary = item.get("validation_summary")
    if isinstance(validation_summary, Mapping):
        nested = validation_summary.get(
            "retained_case_c_target_live_range_repair_summary"
        )
        if isinstance(nested, Mapping):
            yield nested


def _target_live_range_repair_exhaustion(
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for item in items:
        for summary in _iter_target_live_range_summaries(item):
            if summary.get("kind") != _TARGET_LIVE_RANGE_KIND:
                continue
            terminal_blocker = summary.get("terminal_blocker")
            if terminal_blocker not in _TARGET_LIVE_RANGE_BLOCKERS:
                continue
            if summary.get("status") != "blocked":
                continue
            evaluated = _int_count(summary.get("evaluated_probe_count"))
            unscoreable = _int_count(summary.get("unscoreable_count"))
            if evaluated <= 0 or evaluated <= unscoreable:
                continue
            attempted_targets = _normalized_int_mapping(
                summary.get("attempted_targets")
            )
            if _target_live_range_missing_required_scalar_fpr_evidence(
                summary,
                attempted_targets=attempted_targets,
            ):
                continue
            if _target_live_range_missing_alternate_source_owner_evidence(summary):
                continue
            protected_targets = _normalized_int_mapping(
                summary.get("protected_targets")
            )
            candidates = [
                candidate
                for candidate in summary.get("best_retained_candidates", []) or []
                if isinstance(candidate, Mapping)
            ]
            return {
                "kind": summary.get("kind"),
                "status": summary.get("status"),
                "terminal_blocker": terminal_blocker,
                "dominant_blocker": summary.get("dominant_blocker"),
                "evaluated_probe_count": evaluated,
                "unscoreable_count": unscoreable,
                "exact_count": _int_count(summary.get("exact_count")),
                "attempted_targets": attempted_targets,
                "protected_targets": protected_targets,
                "blocker_color_chains": [
                    list(chain)
                    for chain in summary.get("blocker_color_chains", []) or []
                    if isinstance(chain, list)
                ],
                "exhausted_strategy_spans": [
                    dict(span)
                    for span in summary.get("exhausted_strategy_spans", []) or []
                    if isinstance(span, Mapping)
                ],
                "source_owner_terminal_spans": [
                    dict(span)
                    for span in summary.get("source_owner_terminal_spans", []) or []
                    if isinstance(span, Mapping)
                ],
                "unsupported_source_owner_spans": (
                    _target_live_range_unsupported_source_owner_spans(
                        summary,
                        terminal_blocker=terminal_blocker,
                    )
                ),
                "materialized_actions": (
                    _target_live_range_materialized_actions(
                        candidates,
                        attempted_targets=attempted_targets,
                    )
                ),
                "source_files": _post_source_owner_source_files(candidates),
                "best_retained_candidates": [dict(candidate) for candidate in candidates],
            }
    return None


_REQUIRED_FPR_SCALAR_REPAIR_KINDS = {
    "target-aware-scalar-interference-shape",
    "target-aware-scalar-pair-overlap",
}


def _target_live_range_missing_required_scalar_fpr_evidence(
    summary: Mapping[str, Any],
    *,
    attempted_targets: Mapping[str, int],
) -> bool:
    if attempted_targets != {"37": 26}:
        return False
    spans = [
        span
        for span in summary.get("exhausted_strategy_spans", []) or []
        if isinstance(span, Mapping)
    ]
    kinds = {
        span.get("source_probe_provenance_kind")
        for span in spans
        if isinstance(span.get("source_probe_provenance_kind"), str)
    }
    return not _REQUIRED_FPR_SCALAR_REPAIR_KINDS <= kinds


def _target_live_range_missing_alternate_source_owner_evidence(
    summary: Mapping[str, Any],
) -> bool:
    spans = [
        span
        for span in summary.get("source_owner_terminal_spans", []) or []
        if isinstance(span, Mapping)
        and span.get("source_owner_status")
        == "current-source-owner-probes-exhausted"
    ]
    if not spans:
        return False
    for span in spans:
        next_status = span.get("next_source_owner_status")
        if next_status in {None, "not-discovered", "not-requested"}:
            return True
        if next_status == "materialized":
            return True
        if next_status == "terminal-next-source-owner-exhausted":
            inspected = span.get("inspected_owner_nodes")
            if not isinstance(inspected, list) or not inspected:
                return True
            continue
        return True
    return False


def _target_live_range_materialized_actions(
    candidates: list[Mapping[str, Any]],
    *,
    attempted_targets: Mapping[str, int],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    target_igs = sorted(int(key) for key in attempted_targets)
    for candidate in candidates:
        probe_id = candidate.get("probe_id")
        if not isinstance(probe_id, str) or not probe_id:
            continue
        ranked = candidate.get("ranked_repair_candidate")
        if not isinstance(ranked, Mapping):
            ranked = {}
        source_expression = (
            ranked.get("source_expression")
            or ranked.get("address_expression")
            or ranked.get("rewritten_expression")
        )
        actions.append({
            "target_igs": target_igs,
            "source_kind": ranked.get("strategy"),
            "source_expression": source_expression,
            "blocker_color_chain": candidate.get("blocker_color_chain"),
            "probe_labels": [probe_id],
        })
    return actions


def _target_live_range_unsupported_source_owner_spans(
    summary: Mapping[str, Any],
    *,
    terminal_blocker: str,
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for chain in summary.get("blocker_color_chains", []) or []:
        if not isinstance(chain, list):
            continue
        for edge in chain:
            if not isinstance(edge, Mapping):
                continue
            span = _blocker_chain_source_owner_span(
                edge,
                terminal_blocker=terminal_blocker,
            )
            if span is not None:
                spans.append(span)
            operand_sources = edge.get("blocker_operand_sources")
            if not isinstance(operand_sources, list):
                continue
            for operand in operand_sources:
                if not isinstance(operand, Mapping):
                    continue
                operand_span = _blocker_chain_operand_source_owner_span(
                    edge,
                    operand,
                    terminal_blocker=terminal_blocker,
                )
                if operand_span is not None:
                    spans.append(operand_span)

    for raw_span in summary.get("exhausted_strategy_spans", []) or []:
        if not isinstance(raw_span, Mapping):
            continue
        span = _exhausted_repair_strategy_span(
            raw_span,
            terminal_blocker=terminal_blocker,
        )
        if span is not None:
            spans.append(span)
    for raw_span in summary.get("source_owner_terminal_spans", []) or []:
        if not isinstance(raw_span, Mapping):
            continue
        span = _source_owner_terminal_span(
            raw_span,
            terminal_blocker=terminal_blocker,
        )
        if span is not None:
            spans.append(span)
    return _dedupe_residual_case_c_unsupported_source_owner_spans(spans)


_UNSUPPORTED_OWNER_SOURCE_KINDS = {
    "implicit-temp",
    "copy/coalesce-product",
}


def _blocker_chain_source_owner_span(
    edge: Mapping[str, Any],
    *,
    terminal_blocker: str,
) -> dict[str, Any] | None:
    source = edge.get("blocker_source")
    if not isinstance(source, Mapping):
        return None
    source_kind = source.get("kind")
    if source_kind not in _UNSUPPORTED_OWNER_SOURCE_KINDS:
        return None
    payload: dict[str, Any] = {
        "kind": "blocker-chain-source-owner",
        "target_ig": edge.get("target_ig"),
        "target_phys": edge.get("target_phys"),
        "blocker_ig": edge.get("blocker_ig"),
        "blocker_phys": edge.get("blocker_phys"),
        "terminal_blocker": terminal_blocker,
        "source_kind": source_kind,
        "source_expression": source.get("expression"),
        "source_file": source.get("source_file"),
        "source_line": source.get("source_line"),
        "confidence": source.get("confidence"),
    }
    first_def = source.get("first_def")
    if isinstance(first_def, Mapping):
        payload["first_def"] = {
            key: first_def.get(key)
            for key in ("pass_name", "block_idx", "instr_idx", "opcode", "operands")
            if key in first_def
        }
    return payload


def _blocker_chain_operand_source_owner_span(
    edge: Mapping[str, Any],
    operand: Mapping[str, Any],
    *,
    terminal_blocker: str,
) -> dict[str, Any] | None:
    source = operand.get("source")
    if not isinstance(source, Mapping):
        return None
    source_expression = source.get("expression") or source.get("name")
    if source_expression is None:
        return None
    payload: dict[str, Any] = {
        "kind": "blocker-chain-operand-source-owner",
        "target_ig": edge.get("target_ig"),
        "target_phys": edge.get("target_phys"),
        "blocker_ig": edge.get("blocker_ig"),
        "blocker_phys": edge.get("blocker_phys"),
        "operand_index": operand.get("operand_index"),
        "operand_virtual": operand.get("operand_virtual"),
        "operand_assigned_reg": operand.get("operand_assigned_reg"),
        "terminal_blocker": terminal_blocker,
        "source_kind": source.get("kind"),
        "source_expression": source_expression,
        "source_file": source.get("source_file"),
        "source_line": source.get("source_line"),
        "confidence": source.get("confidence"),
    }
    first_def = source.get("first_def")
    if isinstance(first_def, Mapping):
        payload["first_def"] = {
            key: first_def.get(key)
            for key in ("pass_name", "block_idx", "instr_idx", "opcode", "operands")
            if key in first_def
        }
    return payload


def _exhausted_repair_strategy_span(
    raw_span: Mapping[str, Any],
    *,
    terminal_blocker: str,
) -> dict[str, Any] | None:
    ranked = raw_span.get("ranked_repair_candidate")
    if not isinstance(ranked, Mapping):
        ranked = {}
    probe_id = raw_span.get("probe_id")
    strategy = ranked.get("strategy")
    source_expression = ranked.get("source_expression")
    address_expression = ranked.get("address_expression")
    rewritten_expression = ranked.get("rewritten_expression")
    if not any(
        value is not None
        for value in (
            probe_id,
            strategy,
            source_expression,
            address_expression,
            rewritten_expression,
            raw_span.get("exhaustion_key"),
        )
    ):
        return None
    return {
        "kind": "exhausted-repair-strategy",
        "probe_id": probe_id,
        "terminal_blocker": terminal_blocker,
        "source_probe_provenance_kind": raw_span.get(
            "source_probe_provenance_kind"
        ),
        "strategy": strategy,
        "source_expression": source_expression,
        "address_expression": address_expression,
        "rewritten_expression": rewritten_expression,
        "exhaustion_key": raw_span.get("exhaustion_key"),
    }


def _source_owner_terminal_span(
    raw_span: Mapping[str, Any],
    *,
    terminal_blocker: str,
) -> dict[str, Any] | None:
    source_expression = raw_span.get("source_expression")
    if not isinstance(source_expression, str) or not source_expression:
        return None
    blocker = raw_span.get("terminal_blocker") or terminal_blocker
    payload = {
        "kind": "target-live-range-source-owner-terminal",
        "family_id": raw_span.get("family_id"),
        "target_ig": raw_span.get("target_ig"),
        "target_phys": raw_span.get("target_phys"),
        "interferer_ig": raw_span.get("interferer_ig"),
        "interferer_phys": raw_span.get("interferer_phys"),
        "terminal_blocker": blocker,
        "source_expression": source_expression,
        "address_source_expression": raw_span.get("address_source_expression"),
        "paired_source_expression": raw_span.get("paired_source_expression"),
        "source_type": raw_span.get("source_type"),
        "source_owner_kind": raw_span.get("source_owner_kind"),
        "source_owner_confidence": raw_span.get("source_owner_confidence"),
        "source_owner_base_virtual": raw_span.get("source_owner_base_virtual"),
        "source_owner_first_def": raw_span.get("source_owner_first_def"),
        "stack_symbol": raw_span.get("stack_symbol"),
        "operand_index": raw_span.get("operand_index"),
        "operand_virtual": raw_span.get("operand_virtual"),
        "operand_assigned_reg": raw_span.get("operand_assigned_reg"),
        "operand_live_range": raw_span.get("operand_live_range"),
        "evidence_kind": raw_span.get("evidence_kind"),
        "status": raw_span.get("status"),
        "source_owner_status": raw_span.get("source_owner_status"),
        "next_source_owner_status": raw_span.get("next_source_owner_status"),
        "candidate_count": raw_span.get("candidate_count"),
        "materialized_count": raw_span.get("materialized_count"),
        "rejection_reasons": raw_span.get("rejection_reasons"),
        "materialized_probe_labels": raw_span.get("materialized_probe_labels"),
        "alternate_source_owner_probe_labels": raw_span.get(
            "alternate_source_owner_probe_labels"
        ),
        "inspected_owner_nodes": raw_span.get("inspected_owner_nodes"),
        "ranked_alternate_owner_candidates": raw_span.get(
            "ranked_alternate_owner_candidates"
        ),
    }
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, [], {})
    }


def _normalized_int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, int] = {}
    for key, raw in value.items():
        try:
            out[str(int(key))] = int(raw)
        except (TypeError, ValueError):
            continue
    return out


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _non_empty_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _int_count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    return 0


def _post_source_owner_materialized_actions(
    candidates: list[Mapping[str, Any]],
    *,
    attempted_targets: Mapping[str, int],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    fallback_target = None
    if len(attempted_targets) == 1:
        fallback_target = next(iter(attempted_targets))
    for candidate in candidates:
        label = candidate.get("window_order_label")
        if not isinstance(label, str) or not label:
            continue
        target_ig = _target_ig_from_window_order_label(label)
        if target_ig is None and fallback_target is not None:
            target_ig = int(fallback_target)
        actions.append({
            "target_ig": target_ig,
            "source_kind": candidate.get("source_attribution_kind"),
            "source_expression": candidate.get("source_attribution_expression"),
            "probe_labels": [label],
        })
    return actions


def _target_ig_from_window_order_label(label: str) -> int | None:
    marker = "-ig"
    start = label.find(marker)
    if start < 0:
        return None
    cursor = start + len(marker)
    end = cursor
    while end < len(label) and label[end].isdigit():
        end += 1
    if end == cursor:
        return None
    return int(label[cursor:end])


def _post_source_owner_source_files(candidates: list[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for candidate in candidates:
        for key in ("source_retained", "source_file", "path"):
            value = candidate.get(key)
            if isinstance(value, str) and value and value not in out:
                out.append(value)
    return out


def _post_source_owner_skipped_labels(
    candidates: list[Mapping[str, Any]],
) -> list[str]:
    out: list[str] = []
    for candidate in candidates:
        metadata = candidate.get("post_source_owner_backtrack")
        if not isinstance(metadata, Mapping):
            continue
        labels = metadata.get("skipped_current_owner_labels")
        if not isinstance(labels, list):
            continue
        for label in labels:
            if isinstance(label, str) and label and label not in out:
                out.append(label)
    return out


def _lead_source_mapping(lead: Mapping[str, Any]) -> Mapping[str, Any] | None:
    source = lead.get("source")
    merged = dict(source) if isinstance(source, Mapping) else {}
    diagnostic = lead.get("source_probe_diagnostic")
    if isinstance(diagnostic, Mapping):
        diagnostic_source = diagnostic.get("source_attribution")
        if isinstance(diagnostic_source, Mapping):
            for key, value in diagnostic_source.items():
                if key not in merged or merged[key] in (None, ""):
                    merged[key] = value
    return merged or None


def _bridge_retained_source_files(summary: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for collection_key in ("best_retained_variants", "best_retained_candidates"):
        for variant in summary.get(collection_key, []) or []:
            if not isinstance(variant, Mapping):
                continue
            for key in ("source_retained", "source_file", "path"):
                value = variant.get(key)
                if isinstance(value, str) and value and value not in out:
                    out.append(value)
    return out


def _dedupe_residual_case_c_actions(
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for action in actions:
        labels = action.get("probe_labels")
        label_key = tuple(labels) if isinstance(labels, list) else ()
        key = (
            action.get("target_ig"),
            action.get("source_kind"),
            action.get("source_expression"),
            label_key,
        )
        merged.setdefault(key, dict(action))
    return list(merged.values())


def _dedupe_residual_case_c_spans(
    spans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for span in spans:
        source = span.get("source")
        if not isinstance(source, Mapping):
            source = {}
        first_def = source.get("first_def")
        if not isinstance(first_def, Mapping):
            first_def = {}
        key = (
            span.get("target_ig"),
            span.get("desired_phys"),
            span.get("terminal_blocker"),
            source.get("kind"),
            source.get("expression"),
            source.get("source_file"),
            source.get("source_line"),
            first_def.get("opcode"),
            first_def.get("operands"),
            source.get("base_virtual"),
        )
        current = merged.setdefault(key, dict(span))
        order_move = span.get("order_move")
        if order_move is None:
            continue
        order_moves = current.setdefault("order_moves", [])
        if order_move not in order_moves:
            order_moves.append(order_move)
    return list(merged.values())


def _dedupe_residual_case_c_unsupported_source_owner_spans(
    spans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for span in spans:
        first_def = span.get("first_def")
        if not isinstance(first_def, Mapping):
            first_def = {}
        key = (
            span.get("kind"),
            span.get("target_ig"),
            span.get("target_phys"),
            span.get("blocker_ig"),
            span.get("blocker_phys"),
            span.get("operand_index"),
            span.get("operand_virtual"),
            span.get("operand_assigned_reg"),
            span.get("probe_id"),
            span.get("terminal_blocker"),
            span.get("source_probe_provenance_kind"),
            span.get("strategy"),
            span.get("source_kind"),
            span.get("source_expression"),
            span.get("address_expression"),
            span.get("rewritten_expression"),
            span.get("source_file"),
            span.get("source_line"),
            span.get("confidence"),
            span.get("exhaustion_key"),
            first_def.get("opcode"),
            first_def.get("operands"),
        )
        merged.setdefault(key, dict(span))
    return list(merged.values())


def _lead_terminal_blocker(lead: Mapping[str, Any]) -> str | None:
    blocker = lead.get("terminal_blocker")
    if isinstance(blocker, str) and blocker:
        return blocker
    diagnostic = lead.get("source_probe_diagnostic")
    if isinstance(diagnostic, Mapping):
        blocker = diagnostic.get("terminal_blocker")
        if isinstance(blocker, str) and blocker:
            return blocker
    return None


def _residual_case_c_blocked_span(
    lead: Mapping[str, Any],
    source: Mapping[str, Any],
    terminal_blocker: str,
) -> dict[str, Any]:
    first_def = source.get("first_def")
    payload = {
        "target_ig": lead.get("target_ig"),
        "desired_phys": _lead_checkdiff_target_reg(lead),
        "order_move": lead.get("order_move"),
        "terminal_blocker": terminal_blocker,
        "source": {
            "kind": source.get("kind"),
            "expression": source.get("expression"),
            "source_file": source.get("source_file"),
            "source_line": source.get("source_line"),
            "confidence": source.get("confidence"),
        },
    }
    if isinstance(first_def, Mapping):
        payload["source"]["first_def"] = {
            key: first_def.get(key)
            for key in ("pass_name", "block_idx", "instr_idx", "opcode", "operands")
            if key in first_def
        }
    base_virtual = source.get("base_virtual")
    if base_virtual is not None:
        payload["source"]["base_virtual"] = base_virtual
    return payload


def _lead_checkdiff_target_reg(lead: Mapping[str, Any]) -> Any:
    value = lead.get("checkdiff_target_reg")
    if value is not None:
        return value
    diagnostic = lead.get("source_probe_diagnostic")
    if not isinstance(diagnostic, Mapping):
        return None
    diagnostic_lead = diagnostic.get("lead")
    if not isinstance(diagnostic_lead, Mapping):
        return None
    return diagnostic_lead.get("checkdiff_target_reg")


def _residual_case_c_materialized_action(
    lead: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any] | None:
    labels = lead.get("materialized_probe_labels")
    if isinstance(labels, list) and labels:
        probe_labels = labels
    else:
        probe_labels = None
    diagnostic = lead.get("source_probe_diagnostic")
    if isinstance(diagnostic, Mapping):
        diagnostic_labels = diagnostic.get("materialized_probe_labels")
        if isinstance(diagnostic_labels, list) and diagnostic_labels:
            probe_labels = diagnostic_labels
    if not probe_labels:
        return None
    return {
        "target_ig": lead.get("target_ig"),
        "source_kind": source.get("kind"),
        "source_expression": source.get("expression"),
        "probe_labels": list(probe_labels),
    }


def _residual_case_c_simplify_exhaustion(
    items: list[dict[str, Any]],
    *,
    bridge_source_files: list[str],
) -> dict[str, Any] | None:
    plan_transform = _plan_transform_simplify_exhaustion(
        items,
        bridge_source_files=bridge_source_files,
    )
    if plan_transform is not None:
        return plan_transform
    for item in items:
        if item.get("terminal_blocker") != (
            "no-retained-candidate-improved-residual-force-phys"
        ):
            continue
        source_file = item.get("source_file")
        if not isinstance(source_file, str) or not _path_matches_any(
            source_file,
            bridge_source_files,
        ):
            continue
        if item.get("retained_mode") is not True:
            continue
        residual_force_phys = item.get("residual_force_phys")
        if not isinstance(residual_force_phys, Mapping) or not residual_force_phys:
            continue
        ranked_probes = item.get("ranked_probes")
        if not isinstance(ranked_probes, list) or not ranked_probes:
            continue
        summary = item.get("summary")
        return {
            "terminal_blocker": item.get("terminal_blocker"),
            "source_file": source_file,
            "retained_probe_count": len(ranked_probes),
            "compiled": (
                summary.get("compiled") if isinstance(summary, Mapping) else None
            ),
            "progress_hits": (
                summary.get("progress_hits") if isinstance(summary, Mapping) else None
            ),
        }
    return None


_PLAN_TRANSFORM_SIMPLIFY_KINDS = {
    "retained-source-case-c-simplify-order-continuation",
    "retained-source-case-c-lower-drift-residual",
}


_PLAN_TRANSFORM_SIMPLIFY_BLOCKERS = {
    "bounded-remote-scored-exhaustion-no-simplify-order-movement",
    "bounded-remote-scored-exhaustion-lost-protected-only",
    "bounded-remote-scored-exhaustion-no-ig34-residual-repair",
    "bounded-remote-scored-exhaustion-unsupported-source-spans",
}


def _iter_plan_transform_simplify_summaries(
    item: Mapping[str, Any],
) -> Iterable[Mapping[str, Any]]:
    summary = item.get("retained_case_c_simplify_order_continuation_summary")
    if isinstance(summary, Mapping):
        yield summary
    validation_summary = item.get("validation_summary")
    if isinstance(validation_summary, Mapping):
        nested = validation_summary.get(
            "retained_case_c_simplify_order_continuation_summary"
        )
        if isinstance(nested, Mapping):
            yield nested


def _plan_transform_summary_sources(summary: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    source_file = summary.get("source_file")
    if isinstance(source_file, str) and source_file:
        out.append(source_file)
    for candidate in summary.get("best_retained_candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        for key in ("source_retained", "source_file", "path"):
            value = candidate.get(key)
            if isinstance(value, str) and value and value not in out:
                out.append(value)
    return out


def _plan_transform_simplify_exhaustion(
    items: list[dict[str, Any]],
    *,
    bridge_source_files: list[str],
) -> dict[str, Any] | None:
    for item in items:
        for summary in _iter_plan_transform_simplify_summaries(item):
            if summary.get("status") not in {"exhausted", "blocked"}:
                continue
            kind = summary.get("kind")
            if kind not in _PLAN_TRANSFORM_SIMPLIFY_KINDS:
                continue
            terminal_blocker = summary.get("terminal_blocker")
            if terminal_blocker not in _PLAN_TRANSFORM_SIMPLIFY_BLOCKERS:
                continue
            source_files = _plan_transform_summary_sources(summary)
            source_file = None
            if source_files:
                for candidate in source_files:
                    if not bridge_source_files or _path_matches_any(
                        candidate,
                        bridge_source_files,
                    ):
                        source_file = candidate
                        break
                if source_file is None and bridge_source_files:
                    continue
            elif bridge_source_files:
                source_file = bridge_source_files[0]
            if source_file is None and source_files:
                source_file = source_files[0]
            candidates = summary.get("best_retained_candidates")
            return {
                "source_file": source_file,
                "kind": kind,
                "terminal_blocker": terminal_blocker,
                "evaluated_probe_count": summary.get("evaluated_probe_count"),
                "exact_count": summary.get("exact_count"),
                "residual_hit_count": summary.get("residual_hit_count"),
                "lost_lower_drift_count": summary.get("lost_lower_drift_count"),
                "first_divergence_moved_count": summary.get(
                    "first_divergence_moved_count"
                ),
                "best_retained_candidates": (
                    list(candidates) if isinstance(candidates, list) else []
                ),
            }
    return None


def _path_matches_any(source_file: str, candidates: list[str]) -> bool:
    normalized_source = source_file.rstrip("/")
    for candidate in candidates:
        normalized_candidate = candidate.rstrip("/")
        if not normalized_candidate:
            continue
        if normalized_source == normalized_candidate:
            return True
        if normalized_source.endswith("/" + normalized_candidate):
            return True
        if normalized_candidate.endswith("/" + normalized_source):
            return True
    return False


def _draw_coupled_node_set_command(
    *,
    function: str,
    node_delta: Mapping[str, Any] | None,
) -> str:
    class_id = _int_or_none(node_delta.get("class_id")) if node_delta else None
    register_class = "fpr" if class_id == _FPR_CLASS_ID else "gpr"
    force_phys = _node_delta_force_phys_targets(node_delta)
    command = [
        "melee-agent",
        "debug",
        "solve",
        "node-set-split",
        "-f",
        function,
        "--class",
        register_class,
        "--node-set-delta",
        "NODE_SET_DELTA.json",
        "--source-file",
        "SOURCE.c",
        "--coupled",
    ]
    if force_phys:
        command.extend([
            "--force-phys",
            ",".join(f"{ig}:{phys}" for ig, phys in sorted(force_phys.items())),
        ])
    command.extend([
        "--max-candidates",
        "8",
        "--budget",
        "60",
        "--retain-generated",
        "--json",
    ])
    return shlex.join(command)


def _draw_force_vector_command(
    *,
    function: str,
    node_delta: Mapping[str, Any] | None,
) -> str:
    class_id = _int_or_none(node_delta.get("class_id")) if node_delta else None
    register_class = "fpr" if class_id == _FPR_CLASS_ID else "gpr"
    return shlex.join([
        "melee-agent",
        "debug",
        "solve",
        "coloring",
        "-f",
        function,
        "--class",
        register_class,
        "--pcdump",
        "NATURAL.pcdump.txt",
        "--force-vector-probes",
        "--json",
    ])


def _next_steps(
    *,
    function: str,
    status: str,
    bounded: list[str],
    bounded_resume_commands: list[str],
    missing: list[str],
    residual_case_c: Mapping[str, Any],
    expression_terminal: Mapping[str, Any],
    target_only_backprojection: Mapping[str, Any],
    node_delta: Mapping[str, Any] | None = None,
    node_set_frontier: Mapping[str, Any] | None = None,
    select_order_fpr_case_c: Mapping[str, Any] | None = None,
    retained_meta: Mapping[str, Any] | None = None,
) -> list[str]:
    retained_meta = retained_meta or {}
    source_probe = target_only_backprojection.get("source_probe_continuation")
    if (
        isinstance(source_probe, Mapping)
        and source_probe.get("status") == "incomplete"
        and source_probe.get("required_evidence_kind")
        == _TARGET_ONLY_ADDI_COPY_PRODUCT_RESOLVER_KIND
    ):
        return [
            (
                f"Run or provide target-only addi/copy-product source resolver "
                f"evidence for {function}'s lever "
                f"{source_probe.get('source_lever')}."
            )
        ]
    if isinstance(source_probe, Mapping) and source_probe.get("complete") is True:
        if source_probe.get("resolver_kind") == (
            _TARGET_ONLY_ADDI_COPY_PRODUCT_RESOLVER_KIND
        ):
            blocker = source_probe.get("terminal_blocker")
            suffix = f": {blocker}" if blocker else "."
            return [
                (
                    f"Treat {function}'s target-only addi/copy-product "
                    "backprojection as terminal after source-visible variants "
                    f"were tested{suffix}"
                )
            ]
        return [
            (
                f"Treat {function}'s target-only backprojection lever "
                f"{source_probe.get('source_lever')} as a terminal unsupported "
                "source-span family unless a new C-source resolver is added."
            )
        ]
    sticky_pool = target_only_backprojection.get("c2_sticky_pool_attribution")
    if isinstance(sticky_pool, Mapping) and sticky_pool.get("complete") is True:
        return [
            (
                f"Treat {function}'s Case-C2 sticky-pool register target as "
                "terminal for the exhausted retained source-owner lanes unless "
                "a new source lever class appears."
            )
        ]
    if status == "actionable":
        if retained_meta.get("status") == "actionable":
            steps: list[str] = []
            next_frontier = retained_meta.get("next_frontier")
            continuation = (
                next_frontier.get("continuation")
                if isinstance(next_frontier, Mapping)
                else None
            )
            if isinstance(continuation, Mapping):
                command = continuation.get("command")
                if isinstance(command, str) and command:
                    steps.append(command)
                if _retained_meta_post_source_context_actionable(retained_meta):
                    steps.append(
                        "Continue post-source-context next-dimension lane "
                        f"{continuation.get('route') or DRAW_POST_SOURCE_CONTEXT_DIMENSION}."
                    )
                    pcdump = continuation.get("pcdump_path")
                    if isinstance(pcdump, str) and pcdump:
                        steps.append(f"Representative pcdump: {pcdump}.")
                    if continuation.get("target_score") is not None:
                        steps.append(
                            "Target score: "
                            f"{continuation.get('target_score')}."
                        )
                    if continuation.get("expression_score") is not None:
                        steps.append(
                            "Expression score: "
                            f"{continuation.get('expression_score')}."
                        )
                if _retained_meta_post_all_known_actionable(retained_meta):
                    steps.append(
                        "Continue post-all-known frontiers source-context "
                        "hypothesis lane "
                        f"{continuation.get('route') or _DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION}."
                    )
                if _retained_meta_product_translate_actionable(retained_meta):
                    steps.append(
                        "Continue post-all-known product/translate "
                        "expression-graph lane "
                        f"{continuation.get('route') or _DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION}."
                    )
                if _retained_meta_stack_clean_no_anchor_actionable(retained_meta):
                    steps.append(
                        "Continue stack-clean/no-anchor recovery from "
                        f"seed {continuation.get('seed_candidate_id') or continuation.get('candidate_id')} "
                        f"via {continuation.get('route') or _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION}."
                    )
                    pcdump = continuation.get("pcdump_path")
                    if isinstance(pcdump, str) and pcdump:
                        steps.append(f"Representative pcdump: {pcdump}.")
                    source_retained = continuation.get("source_retained")
                    if isinstance(source_retained, str) and source_retained:
                        steps.append(f"Seed source: {source_retained}.")
                    frame = continuation.get("stack_frame_facts")
                    if isinstance(frame, Mapping):
                        steps.append(
                            "Stack frame facts: "
                            f"expected={frame.get('expected_frame')} "
                            f"current={frame.get('current_frame')} "
                            f"delta={frame.get('frame_delta')} "
                            f"ndiff={frame.get('normalized_diff_lines')} "
                            f"opcode={frame.get('opcode_similarity')}."
                        )
                    if continuation.get("target_score") is not None:
                        steps.append(
                            "Target score: "
                            f"{continuation.get('target_score')}."
                        )
                    if continuation.get("expression_score") is not None:
                        steps.append(
                            "Expression score: "
                            f"{continuation.get('expression_score')}."
                        )
                if _retained_meta_draw_helper_boundary_actionable(retained_meta):
                    steps.append(
                        "Continue Draw coupled FPR expression lifetime "
                        "helper/inline-boundary handoff via "
                        f"{continuation.get('route') or _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION}."
                    )
                    unsupported = continuation.get(
                        "unsupported_source_expression_class"
                    )
                    if isinstance(unsupported, str) and unsupported:
                        steps.append(
                            f"Unsupported source expression class: {unsupported}."
                        )
                    next_model = continuation.get("next_unsupported_source_model")
                    if isinstance(next_model, str) and next_model:
                        steps.append(f"Next unsupported source model: {next_model}.")
                    pcdump = continuation.get("pcdump_path")
                    if isinstance(pcdump, str) and pcdump:
                        steps.append(f"Representative pcdump: {pcdump}.")
                    source_retained = continuation.get("source_retained")
                    if isinstance(source_retained, str) and source_retained:
                        steps.append(f"Seed source: {source_retained}.")
                    if continuation.get("target_score") is not None:
                        steps.append(
                            "Target score: "
                            f"{continuation.get('target_score')}."
                        )
                    if continuation.get("expression_score") is not None:
                        steps.append(
                            "Expression score: "
                            f"{continuation.get('expression_score')}."
                        )
                source_hunk = continuation.get("source_hunk")
                if source_hunk is not None:
                    steps.append("Apply retained-frontier source hunk.")
                source_hunks = continuation.get("source_hunks")
                if isinstance(source_hunks, list) and source_hunks:
                    steps.append(
                        "Apply retained-frontier source hunks "
                        f"({len(source_hunks)} hunks)."
                    )
            if steps:
                return steps
            return [f"Inspect retained-frontier actionable lane for {function}."]
        if target_only_backprojection.get("status") == "source-actionable":
            return [
                (
                    f"Inspect {function}'s target-only allocator "
                    "backprojection source levers."
                )
            ]
        return [f"Inspect positive allocator evidence for {function}."]
    if status == "bounded":
        return [
            *[f"Resolve bounded evidence: {reason}." for reason in bounded],
            *bounded_resume_commands,
        ]
    if status == "incomplete":
        steps: list[str] = []
        for entry in missing:
            if "coupled node-set-split evidence" in entry:
                steps.append(
                    _draw_coupled_node_set_command(
                        function=function,
                        node_delta=node_delta,
                    )
                )
            elif entry == "force-phys verification with union status match":
                steps.append(
                    _draw_force_vector_command(
                        function=function,
                        node_delta=node_delta,
                    )
                )
            elif (
                entry
                == "transform-corpus exhausted negative validation evidence"
                and isinstance(select_order_fpr_case_c, Mapping)
                and select_order_fpr_case_c.get("complete") is True
            ):
                continue
            else:
                steps.append(f"Collect missing evidence: {entry}.")
        return _dedupe(steps)
    if retained_meta.get("status") == "terminal-current-source-shape-ceiling":
        proof = retained_meta.get("terminal_proof")
        steps = ["No modeled retained-frontier source-actionable lanes remain."]
        if isinstance(proof, Mapping) and _retained_meta_post_stack_clean_source_shape_terminal(
            proof
        ):
            steps.append(
                "Post-stack-clean/no-anchor source-shape synthesis is terminal "
                "for the current modeled source lane."
            )
            evidence = proof.get("post_stack_clean_no_anchor_evidence")
            if isinstance(evidence, Mapping):
                ranked = evidence.get("ranked_post_stack_clean_probes")
                if isinstance(ranked, list) and ranked:
                    first = ranked[0]
                    if isinstance(first, Mapping) and first.get("candidate_id"):
                        steps.append(
                            "Representative post-stack-clean seed: "
                            f"{first.get('candidate_id')}."
                        )
            retained = proof.get("retained_scored_probes")
            if isinstance(retained, list):
                for row in retained:
                    if not isinstance(row, Mapping):
                        continue
                    pcdump = row.get("pcdump_path")
                    if isinstance(pcdump, str) and pcdump:
                        steps.append(f"Representative pcdump: {pcdump}.")
                        break
            steps.append(
                "Next unsupported source model: "
                f"{_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL}."
            )
            steps.append(
                "Next unsupported source family: "
                f"{_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY}."
            )
            return steps
        if isinstance(proof, Mapping) and _retained_meta_stack_clean_final_terminal(
            proof
        ):
            steps.append(
                "Stack-clean/no-anchor recovery is terminal for the current "
                "modeled source lane."
            )
            evidence = proof.get("stack_clean_no_anchor_evidence")
            if isinstance(evidence, Mapping):
                seed = evidence.get("seed_candidate_id")
                if seed:
                    steps.append(f"Terminal stack-clean seed: {seed}.")
                frame = evidence.get("stack_frame_facts")
                if isinstance(frame, Mapping):
                    steps.append(
                        "Terminal stack frame facts: "
                        f"expected={frame.get('expected_frame')} "
                        f"current={frame.get('current_frame')} "
                        f"delta={frame.get('frame_delta')} "
                        f"ndiff={frame.get('normalized_diff_lines')}."
                    )
            retained = proof.get("retained_scored_probes")
            if isinstance(retained, list):
                for row in retained:
                    if not isinstance(row, Mapping):
                        continue
                    pcdump = row.get("pcdump_path")
                    if isinstance(pcdump, str) and pcdump:
                        steps.append(f"Representative pcdump: {pcdump}.")
                        break
            next_dimension = proof.get("next_unsupported_source_dimension")
            if isinstance(next_dimension, str) and next_dimension:
                steps.append(
                    "Active next modeled source dimension: "
                    f"{next_dimension}."
                )
            next_model = proof.get("next_unsupported_source_model")
            if not isinstance(next_model, str) or not next_model:
                next_model = _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
            next_family = proof.get("next_unsupported_source_family")
            if not isinstance(next_family, str) or not next_family:
                next_family = _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
            steps.append(f"Next unsupported source model: {next_model}.")
            steps.append(f"Next unsupported source family: {next_family}.")
            groups = retained_meta.get("terminal_groups")
            if isinstance(groups, list):
                for group in groups[:3]:
                    if isinstance(group, Mapping):
                        steps.append(
                            "retained-frontier terminal group: "
                            f"{group.get('family_id')} "
                            f"({group.get('terminal_reason')}) x{group.get('count')}"
                        )
            return steps
        if isinstance(proof, Mapping) and (
            proof.get("kind") == POST_SOURCE_CONTEXT_DISCOVERY_KIND
            or proof.get("next_unsupported_source_dimension")
            == DRAW_POST_SOURCE_CONTEXT_DIMENSION
        ):
            steps = [
                (
                    "Post source context next dimension is unsupported by the "
                    "current generator."
                )
            ]
            dimension = proof.get("next_unsupported_source_dimension")
            if isinstance(dimension, str) and dimension:
                steps.append(f"Next unsupported source dimension: {dimension}.")
            family = proof.get("next_unsupported_source_family")
            if isinstance(family, str) and family:
                steps.append(f"Next unsupported source family: {family}.")
            unsupported = proof.get("unsupported_source_expression_class")
            if isinstance(unsupported, str) and unsupported:
                steps.append(
                    f"Unsupported source expression class: {unsupported}."
                )
            pcdump = proof.get("pcdump_path")
            if not pcdump:
                retained = proof.get("retained_scored_probes")
                if isinstance(retained, list):
                    for row in retained:
                        if isinstance(row, Mapping) and row.get("pcdump_path"):
                            pcdump = row.get("pcdump_path")
                            break
            if isinstance(pcdump, str) and pcdump:
                steps.append(f"Representative pcdump: {pcdump}.")
            if proof.get("target_score") is not None:
                steps.append(f"Target score: {proof.get('target_score')}.")
            if proof.get("expression_score") is not None:
                steps.append(
                    f"Expression score: {proof.get('expression_score')}."
                )
            if proof.get("terminal_reason") != (
                "post-source-context-next-dimension/unsupported-source-family"
            ):
                steps.append(
                    "Run retained-frontiers with the explicit "
                    "post-source-context-next-dimension JSON, then pass that "
                    "retained-frontiers output to allocator-ceiling."
                )
        if isinstance(proof, Mapping) and (
            _retained_meta_proof_mentions_dimension(
                proof,
                _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
            )
            or proof.get("next_unsupported_source_family")
            == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
        ):
            steps.append(
                "Stack-clean/no-anchor recovery is terminal for the current "
                "modeled source lane."
            )
            evidence = proof.get("stack_clean_no_anchor_evidence")
            if isinstance(evidence, Mapping):
                seed = evidence.get("seed_candidate_id")
                if seed:
                    steps.append(f"Terminal stack-clean seed: {seed}.")
                frame = evidence.get("stack_frame_facts")
                if isinstance(frame, Mapping):
                    steps.append(
                        "Terminal stack frame facts: "
                        f"expected={frame.get('expected_frame')} "
                        f"current={frame.get('current_frame')} "
                        f"delta={frame.get('frame_delta')} "
                        f"ndiff={frame.get('normalized_diff_lines')}."
                    )
        if isinstance(proof, Mapping) and _retained_meta_draw_helper_boundary_terminal(
            proof
        ):
            steps.append(
                "Draw helper/inline-boundary handoff is terminal for the "
                "current modeled source lane."
            )
            for summary in _retained_meta_terminal_blocker_summaries(proof):
                steps.append(f"Terminal helper-boundary blocker: {summary}.")
        groups = retained_meta.get("terminal_groups")
        if isinstance(groups, list):
            for group in groups[:3]:
                if isinstance(group, Mapping):
                    steps.append(
                        "retained-frontier terminal group: "
                        f"{group.get('family_id')} "
                        f"({group.get('terminal_reason')}) x{group.get('count')}"
                    )
        if isinstance(proof, Mapping):
            next_model = proof.get("next_unsupported_source_model")
            if isinstance(next_model, str) and next_model:
                steps.append(f"Next unsupported source model: {next_model}.")
            next_family = proof.get("next_unsupported_source_family")
            if isinstance(next_family, str) and next_family:
                steps.append(f"Next unsupported source family: {next_family}.")
        return steps
    if residual_case_c.get("complete") is True:
        if residual_case_c.get("terminal_stack") == (
            "live-implicit-temp-copy-survived"
        ):
            return [
                (
                    f"Treat {function} as a current-source-shape allocator "
                    "ceiling: remaining live missing virtuals are pcode-only "
                    "implicit temps, coupled node-set split has zero bindable "
                    "source variables, select-order source probes are "
                    "exhausted, and copy-survived pointer-reset repair is "
                    "terminal."
                )
            ]
        return [
            (
                f"Treat {function}'s residual Case-C/copy-product span as a "
                "current source-shape allocator ceiling unless a new source "
                "owner is identified."
            )
        ]
    if expression_terminal.get("complete") is True:
        swap = _expression_swap_next_step(expression_terminal.get("evidence"))
        return [
            (
                f"Treat {function}'s expression-scored FPR swap {swap} as a "
                "current source-shape allocator ceiling unless a new "
                "expression source family appears."
            )
        ]
    return [
        f"Treat {function} as a practical allocator-rotation ceiling unless new positive evidence appears."
    ]


def render_allocator_ceiling_text(result: Mapping[str, Any]) -> str:
    lines = [
        (
            f"allocator-ceiling {result.get('function')}: "
            f"{result.get('status')} ({result.get('terminal_reason')})"
        ),
        f"evidence: {result.get('evidence_count', 0)} item(s)",
    ]

    force_vector = result.get("force_vector")
    if isinstance(force_vector, Mapping):
        lines.append(
            "force-vector: "
            f"ran={force_vector.get('ran')} "
            f"union={force_vector.get('union_status')}"
        )
    lines.append(
        "source-shape exhausted: "
        f"{bool(result.get('source_shape_exhausted'))}"
    )
    lines.append(
        "wrong-register exhausted: "
        f"{bool(result.get('wrong_register_exhausted'))}"
    )
    node_set_exhaustion = result.get("node_set_exhaustion")
    if isinstance(node_set_exhaustion, Mapping):
        lines.append(
            "node-set exhaustion: "
            f"complete={bool(node_set_exhaustion.get('complete'))} "
            f"reason={node_set_exhaustion.get('terminal_reason')}"
        )
    skipped_count = result.get("skipped_source_evidence_count")
    if skipped_count:
        lines.append(f"skipped source evidence: {skipped_count}")

    _extend_section(lines, "positive proofs", result.get("positive_proofs"))
    _extend_expression_interferer_terminal(
        lines,
        result.get("expression_interferer_terminal"),
    )
    _extend_target_only_backprojection(
        lines,
        result.get("target_only_allocator_backprojection"),
    )
    _extend_target_only_source_probe_continuation(
        lines,
        result.get("target_only_backprojection_source_probe_continuation"),
    )
    _extend_target_only_sticky_pool_attribution(
        lines,
        result.get("target_only_c2_sticky_pool_attribution"),
    )
    _extend_retained_frontiers_meta_ceiling(
        lines,
        result.get("retained_frontiers_meta_ceiling"),
    )
    _extend_backend_blockers(lines, result.get("backend_blockers"))
    _extend_residual_case_c(lines, result.get("residual_case_c_source_repair"))
    _extend_section(lines, "bounded reasons", result.get("bounded_reasons"))
    _extend_section(lines, "missing evidence", result.get("missing_evidence"))
    _extend_section(lines, "next steps", result.get("next_steps"))
    return "\n".join(lines)


def _extend_section(lines: list[str], title: str, entries: Any) -> None:
    if not isinstance(entries, list) or not entries:
        return
    lines.append(f"{title}:")
    for entry in entries:
        lines.append(f"- {entry}")


def _extend_retained_frontiers_meta_ceiling(lines: list[str], payload: Any) -> None:
    if not isinstance(payload, Mapping) or payload.get("status") == "not-present":
        return
    lines.append("retained-frontiers meta-ceiling:")
    lines.append(f"- status: {payload.get('status')}")
    reason = payload.get("terminal_reason")
    if reason:
        lines.append(f"- reason: {reason}")
    groups = payload.get("terminal_groups")
    if isinstance(groups, list) and groups:
        lines.append("- terminal groups:")
        for group in groups[:5]:
            if not isinstance(group, Mapping):
                continue
            lines.append(
                "  - "
                f"{group.get('family_id')} "
                f"({group.get('terminal_reason')}) x{group.get('count')}"
            )
    next_frontier = payload.get("next_frontier")
    continuation = (
        next_frontier.get("continuation")
        if isinstance(next_frontier, Mapping)
        else None
    )
    if isinstance(continuation, Mapping):
        command = continuation.get("command")
        if isinstance(command, str) and command:
            lines.append(f"- next lane command: {command}")
    if isinstance(next_frontier, Mapping):
        dimension = _retained_meta_frontier_dimension(next_frontier)
        if isinstance(dimension, str) and dimension:
            lines.append(f"- next lane dimension: {dimension}")
    proof = payload.get("terminal_proof")
    if not isinstance(proof, Mapping):
        return
    post_stack_clean_final = _retained_meta_post_stack_clean_source_shape_terminal(
        proof
    )
    stack_clean_final = _retained_meta_stack_clean_final_terminal(proof)
    if (
        proof.get("kind") == POST_SOURCE_CONTEXT_DISCOVERY_KIND
        or proof.get("next_unsupported_source_dimension")
        == DRAW_POST_SOURCE_CONTEXT_DIMENSION
    ):
        lines.append("- post source context next dimension: present")
    if _retained_meta_proof_mentions_dimension(
        proof,
        _DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION,
    ):
        lines.append("- post-all-known source-context hypothesis: present")
    if _retained_meta_proof_mentions_dimension(
        proof,
        _DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION,
    ):
        lines.append("- product/translate expression graph: present")
    if post_stack_clean_final:
        lines.append("- post-stack-clean/no-anchor source-shape: terminal")
    if (
        not post_stack_clean_final
        and (
            _retained_meta_proof_mentions_dimension(
                proof,
                _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
            )
            or proof.get("stack_clean_no_anchor_evidence") is not None
            or proof.get("next_unsupported_source_family")
            == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
        )
    ):
        lines.append(
            "- stack-clean/no-anchor recovery: "
            + ("terminal" if stack_clean_final else "present")
        )
    if (
        not stack_clean_final
        and _retained_meta_draw_helper_boundary_terminal(proof)
    ):
        lines.append("- helper/inline-boundary handoff: terminal")
        for summary in _retained_meta_terminal_blocker_summaries(proof)[:4]:
            lines.append(f"- helper-boundary blocker: {summary}")
    next_dimension = proof.get("next_unsupported_source_dimension")
    if (
        isinstance(next_dimension, str)
        and next_dimension
        and not (
            stack_clean_final
            and next_dimension == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        )
    ):
        lines.append(f"- next unsupported source dimension: {next_dimension}")
    unsupported = proof.get("unsupported_source_expression_class")
    if isinstance(unsupported, str) and unsupported:
        lines.append(f"- unsupported source expression class: {unsupported}")
    next_model = proof.get("next_unsupported_source_model")
    if isinstance(next_model, str) and next_model:
        lines.append(f"- next unsupported source model: {next_model}")
    next_family = proof.get("next_unsupported_source_family")
    if isinstance(next_family, str) and next_family:
        lines.append(f"- next unsupported source family: {next_family}")
    next_spans = proof.get("next_unsupported_source_spans")
    if isinstance(next_spans, list) and next_spans:
        rendered_next_spans = [
            _retained_frontiers_next_source_span_text(span)
            for span in next_spans
            if isinstance(span, Mapping)
        ]
        rendered_next_spans = [item for item in rendered_next_spans if item]
        if rendered_next_spans:
            lines.append(
                "- next unsupported source spans: "
                + "; ".join(rendered_next_spans[:5])
            )
    facts = proof.get("allocator_facts")
    if isinstance(facts, list) and facts:
        rendered = [
            _retained_frontiers_allocator_fact_text(fact)
            for fact in facts
            if isinstance(fact, Mapping)
        ]
        rendered = [item for item in rendered if item]
        if rendered:
            lines.append("- allocator facts: " + "; ".join(rendered[:8]))
    spans = proof.get("source_spans")
    if isinstance(spans, list) and spans:
        rendered_spans = [
            _retained_frontiers_source_span_text(span)
            for span in spans
            if isinstance(span, Mapping)
        ]
        rendered_spans = [item for item in rendered_spans if item]
        if rendered_spans:
            lines.append("- source spans: " + "; ".join(rendered_spans[:8]))


def _retained_frontiers_allocator_fact_text(fact: Mapping[str, Any]) -> str | None:
    virtual = _int_or_none(fact.get("virtual"))
    expected = _register_num(fact.get("expected"))
    actual = _register_num(fact.get("actual"))
    if virtual is None or expected is None:
        return None
    text = f"ig{virtual} wants r{expected}"
    if actual is not None:
        text += f" got r{actual}"
    name = fact.get("name")
    if isinstance(name, str) and name and name != f"ig{virtual}":
        text = f"{name} {text}"
    return text


def _retained_frontiers_source_span_text(span: Mapping[str, Any]) -> str | None:
    source_file = span.get("source_file")
    source_line = _int_or_none(span.get("source_line"))
    name = span.get("name") or span.get("hunk_id")
    if isinstance(source_file, str) and source_file:
        text = source_file
        if source_line is not None:
            text += f":{source_line}"
    elif source_line is not None:
        text = f"line {source_line}"
    else:
        return str(name) if name else None
    if isinstance(name, str) and name:
        text += f" {name}"
    return text


def _retained_frontiers_next_source_span_text(
    span: Mapping[str, Any],
) -> str | None:
    candidate_id = span.get("candidate_id")
    dimension_id = span.get("dimension_id")
    components = span.get("source_components")
    hunks = span.get("source_hunks")
    parts: list[str] = []
    if isinstance(candidate_id, str) and candidate_id:
        parts.append(candidate_id)
    if isinstance(dimension_id, str) and dimension_id:
        parts.append(f"dimension={dimension_id}")
    if isinstance(components, list) and components:
        component_ids = [
            row.get("component_id")
            for row in components
            if isinstance(row, Mapping) and isinstance(row.get("component_id"), str)
        ]
        if component_ids:
            parts.append("components=" + ",".join(component_ids[:4]))
    if isinstance(hunks, list) and hunks:
        parts.append(f"hunks={len(hunks)}")
    return " ".join(parts) if parts else None


def _extend_expression_interferer_terminal(lines: list[str], payload: Any) -> None:
    if not isinstance(payload, Mapping) or payload.get("status") == "not-present":
        return
    lines.append("expression terminal:")
    kind = payload.get("kind")
    if kind:
        lines.append(f"- kind: {kind}")
    routes = payload.get("exhausted_routes")
    if isinstance(routes, list) and routes:
        lines.append(
            "- exhausted routes: " + ", ".join(str(route) for route in routes)
        )
    evidence = payload.get("evidence")
    if not isinstance(evidence, Mapping):
        evidence = {}
    candidate_count = evidence.get("candidate_count")
    matched = evidence.get("best_expression_matched")
    targeted = evidence.get("best_expression_targeted")
    if any(value is not None for value in (candidate_count, matched, targeted)):
        lines.append(
            "- candidate score: "
            f"{matched}/{targeted} expression matches across "
            f"{candidate_count} candidate(s)"
        )
    swap = _expression_swap_text(evidence)
    if swap:
        lines.append(f"- FPR swap: {swap}")
    suppressed = payload.get("suppressed_families")
    if isinstance(suppressed, list) and suppressed:
        lines.append(
            "- suppressed source families: "
            + ", ".join(str(family) for family in suppressed)
        )


def _extend_target_only_backprojection(lines: list[str], payload: Any) -> None:
    if not isinstance(payload, Mapping):
        return
    status = payload.get("status")
    if status in (None, "not-present"):
        return
    lines.append("target-only backprojection:")
    lines.append(f"- status: {status}")
    divergences = payload.get("divergences")
    if isinstance(divergences, list) and divergences:
        first = divergences[0]
        if isinstance(first, Mapping):
            lines.append(
                "- first divergence: "
                f"class={first.get('class_id')} "
                f"ig{first.get('target_ig')} "
                f"case={first.get('case')} "
                f"baseline={first.get('baseline_phys')} "
                f"target={first.get('target_phys')}"
            )
            local_target = first.get("local_target")
            if local_target:
                lines.append(f"- allocator target: {local_target}")
    levers = payload.get("source_levers")
    if isinstance(levers, list) and levers:
        lines.append("target-only source levers:")
        for lever in levers[:3]:
            if not isinstance(lever, Mapping):
                continue
            source = lever.get("source")
            if not isinstance(source, Mapping):
                source = {}
            expression = (
                source.get("expression")
                or source.get("name")
                or source.get("kind")
            )
            lines.append(
                f"- ig{lever.get('target_ig')} "
                f"{source.get('kind')} {expression} "
                f"-> {lever.get('local_target')}"
            )


def _extend_target_only_source_probe_continuation(
    lines: list[str],
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping) or payload.get("status") == "not-present":
        return
    lines.append("target-only source-probe continuation:")
    lines.append(f"- status: {payload.get('status')}")
    if payload.get("source_lever"):
        lines.append(f"- source lever: {payload.get('source_lever')}")
    pcode = _pcode_lever_text(payload.get("pcode_lever"))
    if pcode:
        lines.append(f"- pcode lever: {pcode}")
    if payload.get("terminal_blocker"):
        lines.append(f"- terminal blocker: {payload.get('terminal_blocker')}")
    if payload.get("unsupported_source_span_family"):
        lines.append(
            "- unsupported source span family: "
            f"{payload.get('unsupported_source_span_family')}"
        )
    attempted = _int_mapping_text(payload.get("attempted_targets"))
    if attempted:
        lines.append(f"- attempted targets: {attempted}")
    protected = _int_mapping_text(payload.get("protected_targets"))
    if protected:
        lines.append(f"- protected targets: {protected}")
    force = _int_mapping_text(payload.get("final_force_phys"))
    if force:
        lines.append(f"- final force-phys: {force}")
    _extend_copy_product_chain(lines, payload.get("copy_product_chain"))
    _extend_source_visible_variants(
        lines,
        payload.get("source_visible_variants"),
    )
    missing = payload.get("missing_evidence")
    if isinstance(missing, list) and missing:
        lines.append(
            "- missing evidence: " + ", ".join(str(entry) for entry in missing)
        )
    if payload.get("bounded_terminal_blocker"):
        lines.append(f"- bounded blocker: {payload.get('bounded_terminal_blocker')}")
    compiled = payload.get("compiled")
    progress_hits = payload.get("progress_hits")
    if compiled is not None or progress_hits is not None:
        lines.append(
            "- retained probes: "
            f"{payload.get('retained_probe_count')} retained, "
            f"{compiled} compiled, {progress_hits} progress hits"
        )


def _pcode_lever_text(value: Any) -> str | None:
    parsed = _normalized_addi_pcode_lever(value)
    if parsed is None:
        return None
    return (
        f"addi r{parsed['dst_virtual']},"
        f"r{parsed['base_virtual']},{parsed['immediate']}"
    )


def _int_mapping_text(value: Any) -> str | None:
    mapping = _normalized_int_mapping(value)
    if not mapping:
        return None
    return ", ".join(f"ig{ig}->{phys}" for ig, phys in mapping.items())


def _extend_copy_product_chain(lines: list[str], value: Any) -> None:
    if not isinstance(value, list) or not value:
        return
    lines.append("copy-product chain:")
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        expression = entry.get("expression")
        if not expression:
            continue
        prefix = ""
        target_ig = entry.get("target_ig")
        if target_ig is not None:
            prefix = f"ig{target_ig} "
        text = f"{prefix}{expression}"
        if entry.get("protected") is True:
            text += " protected"
        kind = entry.get("kind")
        if kind:
            text += f" ({kind})"
        lines.append(f"- {text}")


def _extend_source_visible_variants(lines: list[str], value: Any) -> None:
    if not isinstance(value, list) or not value:
        return
    scores = [
        str(entry.get("score"))
        for entry in value
        if isinstance(entry, Mapping) and entry.get("score") is not None
    ]
    if scores:
        lines.append("- source-visible variant scores: " + "/".join(scores))
    lines.append("source-visible variants:")
    for entry in value[:6]:
        if not isinstance(entry, Mapping):
            continue
        parts: list[str] = []
        label = entry.get("label")
        if label:
            parts.append(str(label))
        if entry.get("score") is not None:
            parts.append(f"score={entry.get('score')}")
        target_score = _target_score_text(entry.get("target_score"))
        if target_score:
            parts.append(f"target_score={target_score}")
        if entry.get("target_hits") is not None:
            parts.append(f"target_hits={entry.get('target_hits')}")
        if entry.get("protected_preserved") is not None:
            parts.append(
                f"protected_preserved={entry.get('protected_preserved')}"
            )
        if parts:
            lines.append("- " + " ".join(parts))


def _target_score_text(value: Any) -> str | None:
    if isinstance(value, Mapping):
        matched = value.get("matched")
        targeted = value.get("targeted")
        if matched is not None and targeted is not None:
            return f"{matched}/{targeted}"
        score = value.get("score")
        if score is not None:
            return str(score)
        return None
    if value is None:
        return None
    return str(value)


def _extend_target_only_sticky_pool_attribution(
    lines: list[str],
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping) or payload.get("status") == "not-present":
        return
    lines.append("target-only C2 sticky-pool attribution:")
    lines.append(f"- status: {payload.get('status')}")
    lines.append(
        "- target: "
        f"ig{payload.get('target_ig')} "
        f"baseline={payload.get('baseline_phys')} "
        f"target={payload.get('target_phys')}"
    )
    lines.append(
        "- retained lanes: "
        f"{payload.get('lane_count')} lane(s), "
        f"{payload.get('evaluated_probe_count')} evaluated, "
        f"{payload.get('exact_count')} exact"
    )
    expressions = payload.get("source_expressions")
    if isinstance(expressions, list) and expressions:
        lines.append(
            "- source expressions: "
            + ", ".join(str(expression) for expression in expressions[:6])
        )
    upstream = payload.get("upstream_virtuals")
    if isinstance(upstream, list) and upstream:
        lines.append(
            "- upstream virtuals: "
            + ", ".join(f"ig{value}" for value in upstream[:8])
        )


def _extend_backend_blockers(lines: list[str], entries: Any) -> None:
    if not isinstance(entries, list) or not entries:
        return
    lines.append("backend blockers:")
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        text = (
            f"ig{entry.get('original_ig')}->ig{entry.get('new_ig')} "
            f"wants {entry.get('desired_phys')} got {entry.get('assigned_phys')}"
        )
        mutators = entry.get("mutators")
        if isinstance(mutators, list) and mutators:
            text += " via " + ", ".join(str(mutator) for mutator in mutators)
        lines.append(f"- {text}")


def _extend_residual_case_c(lines: list[str], payload: Any) -> None:
    if not isinstance(payload, Mapping) or payload.get("complete") is not True:
        return
    if payload.get("terminal_stack") == "live-implicit-temp-copy-survived":
        lines.append("live implicit-temp terminal stack:")
        unsplittable = payload.get("node_set_unsplittable_frontier")
        if isinstance(unsplittable, Mapping):
            targets = unsplittable.get("target_igs")
            target_text = ""
            if isinstance(targets, list) and targets:
                target_text = " for " + ", ".join(
                    f"ig{target}" for target in targets
                )
            reason = unsplittable.get("blocked_reason") or unsplittable.get(
                "reason"
            )
            lines.append(
                f"- zero-bindable node-set split{target_text}: {reason}"
            )
        copy = payload.get("copy_survived_repair")
        if isinstance(copy, Mapping):
            pair = (
                f"ig{copy.get('from_virtual')}->ig{copy.get('to_virtual')}"
            )
            regs = ""
            if (
                copy.get("from_assigned_reg") is not None
                and copy.get("to_assigned_reg") is not None
            ):
                regs = (
                    f" assigned r{copy.get('from_assigned_reg')}->"
                    f"r{copy.get('to_assigned_reg')}"
                )
            counts: list[str] = []
            if copy.get("scored_count") is not None:
                counts.append(f"scored={copy.get('scored_count')}")
            if copy.get("failed_count") is not None:
                counts.append(f"failed={copy.get('failed_count')}")
            if copy.get("pointer_reset_probe_count") is not None:
                counts.append(
                    f"pointer_reset={copy.get('pointer_reset_probe_count')}"
                )
            if copy.get("pointer_reset_failed_count") is not None:
                counts.append(
                    "pointer_reset_failed="
                    f"{copy.get('pointer_reset_failed_count')}"
                )
            suffix = f" ({', '.join(counts)})" if counts else ""
            lines.append(f"- copy-survived: {pair}{regs}{suffix}")
            blocker = copy.get("terminal_blocker")
            if blocker:
                lines.append(f"- terminal blocker: {blocker}")
    blocked_spans = payload.get("blocked_source_spans")
    if isinstance(blocked_spans, list) and blocked_spans:
        lines.append("residual Case-C source blockers:")
    for span in blocked_spans or []:
        if not isinstance(span, Mapping):
            continue
        source = span.get("source")
        if not isinstance(source, Mapping):
            source = {}
        text = (
            f"ig{span.get('target_ig')} {source.get('kind')} "
            f"{source.get('expression')} -> {span.get('terminal_blocker')}"
        )
        first_def = source.get("first_def")
        if isinstance(first_def, Mapping):
            text += (
                f" ({first_def.get('opcode')} {first_def.get('operands')})"
            )
        lines.append(f"- {text}")
    unsupported = payload.get("unsupported_source_owner_spans")
    if isinstance(unsupported, list) and unsupported:
        lines.append("unsupported source-owner spans:")
        for span in unsupported:
            if not isinstance(span, Mapping):
                continue
            text = _unsupported_source_owner_span_text(span)
            if text:
                lines.append(f"- {text}")
    simplify = payload.get("simplify_order_exhaustion")
    if isinstance(simplify, Mapping):
        lines.append(
            "retained simplify-order exhausted: "
            f"{simplify.get('retained_probe_count')} retained, "
            f"{simplify.get('compiled')} compiled, "
            f"{simplify.get('progress_hits')} progress hits"
        )


def _unsupported_source_owner_span_text(span: Mapping[str, Any]) -> str | None:
    if span.get("kind") == "blocker-chain-source-owner":
        text = (
            f"ig{span.get('blocker_ig')} {span.get('source_kind')} "
            f"{span.get('source_expression')} blocks "
            f"ig{span.get('target_ig')}->r{span.get('target_phys')}"
        )
        blocker_phys = span.get("blocker_phys")
        if blocker_phys is not None:
            text += f" on r{blocker_phys}"
        text += f" -> {span.get('terminal_blocker')}"
        first_def = span.get("first_def")
        if isinstance(first_def, Mapping):
            text += f" ({first_def.get('opcode')} {first_def.get('operands')})"
        return text
    if span.get("kind") == "blocker-chain-operand-source-owner":
        text = (
            f"ig{span.get('blocker_ig')} operand "
            f"r{span.get('operand_virtual')} {span.get('source_kind')} "
            f"{span.get('source_expression')} feeds blocker for "
            f"ig{span.get('target_ig')}->r{span.get('target_phys')}"
        )
        operand_phys = span.get("operand_assigned_reg")
        if operand_phys is not None:
            text += f" on r{operand_phys}"
        text += f" -> {span.get('terminal_blocker')}"
        first_def = span.get("first_def")
        if isinstance(first_def, Mapping):
            text += f" ({first_def.get('opcode')} {first_def.get('operands')})"
        return text
    if span.get("kind") == "exhausted-repair-strategy":
        probe_id = span.get("probe_id")
        strategy = span.get("strategy")
        source_expression = span.get("source_expression")
        address_expression = span.get("address_expression")
        text = f"{probe_id} {strategy}"
        if source_expression:
            text += f" value={source_expression}"
        if address_expression:
            text += f" address={address_expression}"
        text += f" -> {span.get('terminal_blocker')}"
        return text
    if span.get("kind") == "target-live-range-source-owner-terminal":
        owner_kind = span.get("source_owner_kind") or "source-owner"
        text = (
            f"ig{span.get('target_ig')} {owner_kind} "
            f"{span.get('source_expression')} -> {span.get('terminal_blocker')}"
        )
        base_virtual = span.get("source_owner_base_virtual")
        if base_virtual is not None:
            text += f" base r{base_virtual}"
        stack_symbol = span.get("stack_symbol")
        if stack_symbol is not None:
            text += f" stack {stack_symbol}"
        materialized = span.get("materialized_count")
        candidate_count = span.get("candidate_count")
        if materialized is not None and candidate_count is not None:
            text += f" ({materialized}/{candidate_count} materialized)"
        reasons = span.get("rejection_reasons")
        if isinstance(reasons, Mapping) and reasons:
            reason_text = ", ".join(
                f"{reason}={count}" for reason, count in sorted(reasons.items())
            )
            text += f" reasons[{reason_text}]"
        first_def = span.get("source_owner_first_def")
        if isinstance(first_def, Mapping):
            text += f" ({first_def.get('opcode')} {first_def.get('operands')})"
        return text
    return None


def _expression_swap_next_step(evidence: Any) -> str:
    if not isinstance(evidence, Mapping):
        return "unknown"
    return (
        f"{evidence.get('focus')} ig{evidence.get('focus_ig')} "
        f"f{evidence.get('current_focus_reg')}->f{evidence.get('target_reg')} / "
        f"{evidence.get('paired_source')} ig{evidence.get('paired_ig')} "
        f"f{evidence.get('current_paired_reg')}->"
        f"f{evidence.get('paired_target_reg')}"
    )


def _expression_swap_text(evidence: Mapping[str, Any]) -> str | None:
    if not _expression_fpr_swap_evidence_present(evidence):
        return None
    return (
        f"{evidence.get('focus')} ig{evidence.get('focus_ig')} "
        f"wants f{evidence.get('target_reg')} "
        f"got f{evidence.get('current_focus_reg')}; "
        f"{evidence.get('paired_source')} ig{evidence.get('paired_ig')} "
        f"wants f{evidence.get('paired_target_reg')} "
        f"got f{evidence.get('current_paired_reg')}"
    )


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value > 0:
        return value
    return 0


def _count_reason(prefix: str, count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{prefix} {count} {noun}{suffix}"


def _dedupe(entries: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        out.append(entry)
    return out
