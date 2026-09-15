"""Probe generation: fan out anchors across families into TransformProbes."""
from __future__ import annotations

import re
import difflib
from collections.abc import Iterable as IterableABC
from pathlib import Path
from src.mwcc_debug.source_field_attribution import build_source_field_context
from src.mwcc_debug.scheduler_order_realizer import SchedulerOrderTarget, iter_scheduler_order_source_anchors, parse_scheduler_order_target
from src.mwcc_debug.expression_interferer_repair import generate_source_repair_candidates
from src.mwcc_debug.pressure_explorer import LifetimeLayoutProbe
from src.search.directed.anchors import Anchor, iter_source_shape_anchors
from src.search.directed.mutators import apply_mutator
from src.search.directed.transform_corpus.common import _normalize_type_name, _source_file_for_unit, _split_top_level_csv, _target_function_body
from src.search.directed.transform_corpus.common_subexpr_coalesce import (
    MUTATOR_KEY as RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_MUTATOR_KEY,
    common_subexpr_coalesce_match_diagnostics,
    iter_common_subexpr_coalesce_anchors,
)
from src.search.directed.transform_corpus.contract_signature import _iter_unused_trailing_parameter_anchors
from src.search.directed.transform_corpus.float_literal import _iter_global_float_literal_anchors
from src.search.directed.transform_corpus.fp_reassoc import _iter_fp_subtraction_reassociation_anchors
from src.search.directed.transform_corpus.global_load_lifetime import (
    global_load_lifetime_match_diagnostics,
    iter_global_load_lifetime_anchors,
)
from src.search.directed.transform_corpus.helper_extract import _iter_helper_shape_anchors
from src.search.directed.transform_corpus.indexed_byte_address import _iter_indexed_byte_address_temp_anchors
from src.search.directed.transform_corpus.local_reuse import _iter_same_type_local_lifetime_reuse_anchors
from src.search.directed.transform_corpus.models import TransformExperimentPlan, TransformFamilyMaterializationDiagnostic, TransformProbe, TransformProbeGenerationReport
from src.search.directed.transform_corpus.named_zero_local import _iter_named_zero_local_anchors
from src.search.directed.transform_corpus.parameter_area import _iter_outgoing_parameter_area_shape_anchors
from src.search.directed.transform_corpus.pointer_alias import _iter_global_pointer_alias_anchors
from src.search.directed.transform_corpus.pragma_codegen import _iter_function_codegen_pragma_anchors
from src.search.directed.transform_corpus.ranked_cursor_iv import _iter_ranked_cursor_iv_unification_anchors
from src.search.directed.transform_corpus.retained_case_c_simplify_order import (
    MUTATOR_KEY as RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_MUTATOR_KEY,
    iter_retained_case_c_simplify_order_anchors,
    retained_case_c_simplify_order_match_diagnostics,
)
from src.search.directed.transform_corpus.register_steering import _callarg_local_structural_match_diagnostics, _iter_callarg_local_structural_repair_anchors, _iter_concrete_register_steering_body_anchors, _iter_coupled_fpr_product_callarg_repair_anchors, _iter_fpr_product_assignments, _iter_hsd_jobj_req_anim_all_call_args, _iter_mixed_pcode_fpr_lifetime_pressure_anchors, _iter_node_set_delta_steering_probes, _iter_pcode_only_fpr_callarg_temp_anchors, _iter_pcode_only_fpr_fsubs_cast_owner_anchors, _iter_pcode_only_fpr_fsubs_cast_owner_assignments, _iter_pcode_only_gpr_address_temp_anchors, _iter_pcode_only_gpr_bool_mask_temp_anchors, _iter_pcode_only_gpr_copy_product_case_c_anchors, _iter_register_steering_body_anchors, _iter_retained_gpr_case_c_sensitivity_anchors, _pcode_only_gpr_address_temp_match_diagnostics, _pcode_only_gpr_bool_mask_temp_match_diagnostics, _pcode_only_gpr_copy_product_case_c_match_diagnostics, _retained_gpr_case_c_sensitivity_match_diagnostics
from src.search.directed.transform_corpus.registry import _FAMILY_BY_ID, _FAMILY_IDS_BY_MUTATOR, plan_transform_experiments
from src.search.directed.transform_corpus.return_tail_call import _iter_return_tail_call_anchors
from src.search.directed.transform_corpus.statement_order import _iter_independent_statement_order_anchors
from src.search.directed.transform_corpus.string_data_field import _iter_string_data_field_anchors
from src.search.directed.transform_corpus.struct_field_access import _iter_data_table_indirection_anchors, _iter_raw_index_struct_field_anchors, _iter_raw_pointer_offset_anchors
from src.search.directed.transform_corpus.type_cast import _iter_type_cast_compatibility_anchors
from src.search.directed.window_order_source import (
    plan_alternate_source_owner_probes,
    plan_target_aware_live_range_repair_probes,
    plan_window_order_source_probes,
)
from typing import Any, Mapping


RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID = (
    "retained_gpr_case_c_window_order_continuation"
)
RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_MUTATOR_KEY = (
    "steer_retained_gpr_case_c_window_order_continuation"
)
RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_FAMILY_ID = (
    "retained_gpr_case_c_post_source_owner_backtrack"
)
RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_MUTATOR_KEY = (
    "steer_retained_gpr_case_c_post_source_owner_backtrack"
)
RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID = (
    "retained_gpr_case_c_target_live_range_repair"
)
RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_MUTATOR_KEY = (
    "steer_retained_gpr_case_c_target_live_range_repair"
)
RETAINED_FPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID = (
    "retained_fpr_case_c_target_live_range_repair"
)
RETAINED_FPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_MUTATOR_KEY = (
    "steer_retained_fpr_case_c_target_live_range_repair"
)
RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_FAMILY_ID = (
    "retained_case_c_alternate_source_owner_discovery"
)
RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_MUTATOR_KEY = (
    "steer_retained_case_c_alternate_source_owner"
)
RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID = (
    "retained_gpr_case_c_simplify_order_continuation"
)
RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID = (
    "retained_gpr_common_subexpr_coalesce_source"
)

_REGISTER_STEERING_ALIASES = {
    "reorder_local_decls": "steer_reorder_local_decls",
    "split_decl_init": "steer_split_decl_init",
    "reuse_loop_counter_scope": "steer_reuse_loop_counter_scope",
    "change_counter_width": "steer_change_counter_width",
    "reuse_same_type_local_lifetime": "steer_reuse_same_type_local_lifetime",
}


_DIRECT_REGISTER_STEERING_KEYS = frozenset({
    "steer_rotate_local_decl_window",
    "steer_demote_local_decl_to_first_use",
    "steer_reuse_dead_top_level_loop_counter",
    "steer_split_reused_loop_counter",
    "steer_widen_byte_local_type",
    "steer_fpr_dependent_product_recompute",
    "steer_fpr_dependent_product_reuse_temp",
    "steer_fpr_dependent_local_temp_split",
    "steer_fpr_product_assignment_order",
    "steer_fpr_product_cast_temp_split",
    "steer_fpr_product_argument_duplicate",
    "steer_fpr_product_temp_split",
    "steer_fpr_paired_product_temp_split",
    "steer_fpr_product_temp_plus_dependent",
    "steer_fpr_case_c_temp_order",
})

_SOURCE_FUNCTION_ALIASES = {
    "mnDiagram_SortNamesByKOs": ("mnDiagram_8023FC28",),
}


_FAMILY_FORCE_CLASSES = {
    "pcode_only_fpr_fsubs_cast_owner_repair": frozenset({1}),
    "pcode_only_fpr_callarg_temp_repair": frozenset({1}),
    "coupled_fpr_coalesce_product_repair": frozenset({1}),
    "mixed_pcode_fpr_lifetime_pressure_repair": frozenset({1}),
    "callarg_local_structural_repair": frozenset({1}),
    "pcode_only_gpr_address_temp_repair": frozenset({0}),
    "pcode_only_gpr_copy_product_case_c_repair": frozenset({0}),
    "pcode_only_gpr_bool_mask_temp_repair": frozenset({0}),
    "pcode_only_gpr_global_load_lifetime_repair": frozenset({0}),
    "retained_gpr_case_c_sensitivity_search": frozenset({0}),
    RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID: frozenset({0}),
    RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_FAMILY_ID: frozenset({0}),
    RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID: frozenset({0}),
    RETAINED_FPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID: frozenset({1}),
    RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_FAMILY_ID: frozenset({0, 1}),
    RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID: frozenset({0}),
    RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID: frozenset({0}),
    "indexed_byte_address_temp_steering": frozenset({0}),
    "coloring_register_steering": frozenset({0, 1}),
}


def _family_supports_force_class(
    family_id: str,
    force_class_id: int | None,
) -> bool:
    if force_class_id is None:
        return True
    supported = _FAMILY_FORCE_CLASSES.get(family_id)
    return supported is None or force_class_id in supported


def _diagnostic_family_ids(
    plan: TransformExperimentPlan,
    *,
    allowed: set[str],
    requested_family_ids: tuple[str, ...],
) -> tuple[str, ...]:
    family_ids = [family.family_id for family in plan.families]
    family_ids.extend(
        family_id for family_id in requested_family_ids if family_id in allowed
    )
    return tuple(dict.fromkeys(family_ids))


def _new_family_stat(plan: TransformExperimentPlan, family_id: str) -> dict[str, Any]:
    family = _FAMILY_BY_ID[family_id]
    return {
        "attempt_status": "skipped",
        "attempted": False,
        "candidate_anchor_count": 0,
        "applied_candidate_count": 0,
        "budget_limited": False,
        "no_probe_reason": None,
        "matcher_diagnostics": {
            "family_label": family.label,
            "mutator_keys": list(family.mutator_keys),
            "source_region_selector": family.source_region_selector,
            "supported_force_classes": sorted(_FAMILY_FORCE_CLASSES.get(family_id, ())),
            "source_regions": list(_region_for_family(plan, family_id)[0:1]),
        },
    }


def _seed_family_stats(
    plan: TransformExperimentPlan,
    *,
    allowed: set[str],
    requested_family_ids: tuple[str, ...],
    force_class_id: int | None,
    source_status: str,
) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for family_id in _diagnostic_family_ids(
        plan,
        allowed=allowed,
        requested_family_ids=requested_family_ids,
    ):
        stat = _new_family_stat(plan, family_id)
        diagnostics = stat["matcher_diagnostics"]
        diagnostics["requested_force_class"] = force_class_id
        diagnostics["source_status"] = source_status
        if source_status == "source-unavailable":
            stat["no_probe_reason"] = "source-unavailable"
        elif source_status == "source-pattern-not-found":
            stat["no_probe_reason"] = "source-pattern-not-found"
        elif family_id not in allowed:
            stat["attempt_status"] = "contextual-only"
            stat["no_probe_reason"] = "family-filtered-by-unit"
        elif not _family_supports_force_class(family_id, force_class_id):
            stat["attempt_status"] = "skipped"
            stat["no_probe_reason"] = "class-mismatch"
        else:
            stat["attempt_status"] = "attempted"
            stat["attempted"] = True
        stats[family_id] = stat
    return stats


def _candidate_counts_for_mutator(stat: dict[str, Any]) -> dict[str, int]:
    diagnostics = stat["matcher_diagnostics"]
    counts = diagnostics.get("candidate_mutator_counts")
    if not isinstance(counts, dict):
        counts = {}
        diagnostics["candidate_mutator_counts"] = counts
    return counts


def _note_family_candidate(
    stats: dict[str, dict[str, Any]],
    family_id: str,
    anchor: Anchor,
) -> None:
    stat = stats.get(family_id)
    if stat is None:
        return
    stat["candidate_anchor_count"] += 1
    counts = _candidate_counts_for_mutator(stat)
    key = anchor.mutator_key.split("@", 1)[0]
    counts[key] = counts.get(key, 0) + 1


def _note_family_applied(
    stats: dict[str, dict[str, Any]],
    family_id: str,
    anchor: Anchor,
) -> None:
    stat = stats.get(family_id)
    if stat is None:
        return
    stat["applied_candidate_count"] += 1
    diagnostics = stat["matcher_diagnostics"]
    counts = diagnostics.get("applied_mutator_counts")
    if not isinstance(counts, dict):
        counts = {}
        diagnostics["applied_mutator_counts"] = counts
    key = anchor.mutator_key.split("@", 1)[0]
    counts[key] = counts.get(key, 0) + 1


def _family_can_attempt(
    stats: dict[str, dict[str, Any]],
    allowed: set[str],
    family_id: str,
) -> bool:
    stat = stats.get(family_id)
    if stat is None:
        return family_id in allowed
    return bool(stat["attempted"]) and family_id in allowed


def _family_candidate_allowed(
    stats: dict[str, dict[str, Any]],
    counts: dict[str, int],
    allowed: set[str],
    family_id: str,
    anchor: Anchor,
    *,
    max_per_family: int,
) -> bool:
    if not _family_can_attempt(stats, allowed, family_id):
        return False
    _note_family_candidate(stats, family_id, anchor)
    if counts.get(family_id, 0) >= max_per_family:
        if family_id in stats:
            stats[family_id]["budget_limited"] = True
        return False
    return True


def _basic_pcode_callarg_diagnostics(
    body_text: str,
    function_header_text: str,
    *,
    anchor_count: int,
) -> dict[str, Any]:
    calls = _iter_hsd_jobj_req_anim_all_call_args(
        body_text,
        function_header_text,
    )
    return {
        "hsd_jobj_req_anim_all_calls": len(
            re.findall(r"\bHSD_JObjReqAnimAll\s*\(", body_text)
        ),
        "accepted_fpr_callarg_conversions": len(calls),
        "accepted_anchor_count": anchor_count,
        "call_arg_locals": sorted(
            {call.call_arg_local for call in calls if call.call_arg_local}
        ),
        "call_arg_operands": sorted({call.call_arg_operand for call in calls}),
    }


def _basic_pcode_fsubs_cast_owner_diagnostics(
    body_text: str,
    function_header_text: str,
    *,
    anchor_count: int,
) -> dict[str, Any]:
    assignments = _iter_pcode_only_fpr_fsubs_cast_owner_assignments(
        body_text,
        function_header_text,
    )
    return {
        "standalone_fpr_cast_owner_assignments": sum(
            1 for assignment in assignments if assignment.kind == "cast-owner"
        ),
        "standalone_fpr_subtraction_assignments": sum(
            1 for assignment in assignments if assignment.kind == "fsubs-owner"
        ),
        "accepted_anchor_count": anchor_count,
        "owner_locals": sorted({assignment.lhs for assignment in assignments}),
        "owner_operands": sorted(
            {
                operand
                for assignment in assignments
                for operand in assignment.operand_names
            }
        ),
    }


def _basic_coupled_fpr_diagnostics(
    body_text: str,
    function_header_text: str,
    *,
    anchor_count: int,
) -> dict[str, Any]:
    products = _iter_fpr_product_assignments(body_text, function_header_text)
    calls = _iter_hsd_jobj_req_anim_all_call_args(
        body_text,
        function_header_text,
    )
    ordered_pair_count = sum(
        1 for product in products for call in calls if call.start > product.end
    )
    row_product_shape = bool(
        re.search(r"\brow(?:_offset)?\b\s*=", body_text)
        and (
            re.search(r"\brow\b.*\*", body_text)
            or "HSD_JObjGetTranslationY" in body_text
        )
    )
    return {
        "fpr_product_assignments": len(products),
        "accepted_fpr_callarg_conversions": len(calls),
        "product_before_call_pairs": ordered_pair_count,
        "accepted_anchor_count": anchor_count,
        "product_locals": sorted({product.lhs for product in products}),
        "call_arg_locals": sorted(
            {call.call_arg_local for call in calls if call.call_arg_local}
        ),
        "row_product_shape_detected": row_product_shape,
    }


def _basic_mixed_pcode_fpr_lifetime_diagnostics(
    body_text: str,
    function_header_text: str,
    *,
    anchors: list[Anchor],
) -> dict[str, Any]:
    del function_header_text
    row_locals = sorted(
        {
            str(anchor.payload.get("row_local"))
            for anchor in anchors
            if anchor.payload.get("row_local")
        }
    )
    row_adj_locals = sorted(
        {
            str(anchor.payload.get("row_adj_local"))
            for anchor in anchors
            if anchor.payload.get("row_adj_local")
        }
    )
    row_adj_owner_locals = sorted(
        {
            str(anchor.payload.get("row_adj_owner_local"))
            for anchor in anchors
            if anchor.payload.get("row_adj_owner_local")
        }
    )
    call_arg_locals = sorted(
        {
            str(anchor.payload.get("call_arg_local"))
            for anchor in anchors
            if anchor.payload.get("call_arg_local")
        }
    )
    strategies = sorted(
        {
            str(anchor.payload.get("strategy"))
            for anchor in anchors
            if anchor.payload.get("strategy")
        }
    )
    return {
        "row_offset_mentions": len(re.findall(r"\brow_offset\b", body_text)),
        "row_offset_adj_mentions": len(
            re.findall(r"\brow_offset_adj\b", body_text)
        ),
        "hsd_jobj_set_translate_y_calls": len(
            re.findall(r"\bHSD_JObjSetTranslateY\s*\(", body_text)
        ),
        "hsd_jobj_req_anim_all_calls": len(
            re.findall(r"\bHSD_JObjReqAnimAll\s*\(", body_text)
        ),
        "accepted_mixed_case_count": 1 if anchors else 0,
        "accepted_anchor_count": len(anchors),
        "row_locals": row_locals,
        "row_adj_locals": row_adj_locals,
        "row_adj_owner_locals": row_adj_owner_locals,
        "call_arg_locals": call_arg_locals,
        "generated_strategies": strategies,
    }


def _iter_mixed_pcode_expression_repair_fallback_anchors(
    source_text: str,
    *,
    source_function: str,
    max_candidates: int,
) -> tuple[tuple[Anchor, str], ...]:
    target = _target_function_body(source_text, source_function)
    if target is None:
        return ()
    source_span, _source_body = target
    source_function_text = source_text[source_span.sig_start:source_span.full_end]
    terminal_summary = {
        "kind": "mixed-pcode-fpr-lifetime-expression-repair-fallback",
        "remaining_blockers": [
            {
                "case": "C2",
                "focus": "col_offset",
                "paired_source": "row_offset",
                "reason": (
                    "mixed-pcode FPR lifetime repair found no structural "
                    "anchors; row/col source shape remains a Case C2 "
                    "sticky-pool/source-order candidate"
                ),
            }
        ],
    }
    generation = generate_source_repair_candidates(
        source_text,
        function=source_function,
        terminal_summary=terminal_summary,
        include_source=True,
        max_candidates=max_candidates,
    )
    if generation.get("status") != "generated":
        return ()
    result: list[tuple[Anchor, str]] = []
    for row in generation.get("candidates", ()):
        if not isinstance(row, Mapping):
            continue
        candidate_text = row.get("source_text")
        if not isinstance(candidate_text, str) or candidate_text == source_text:
            continue
        candidate_target = _target_function_body(candidate_text, source_function)
        if candidate_target is None:
            continue
        candidate_span, _candidate_body = candidate_target
        replacement_text = candidate_text[
            candidate_span.sig_start:candidate_span.full_end
        ]
        if replacement_text == source_function_text:
            continue
        strategy = str(row.get("strategy") or row.get("candidate_id") or "candidate")
        anchor = Anchor(
            mutator_key="steer_mixed_pcode_fpr_lifetime_pressure",
            span=(source_span.sig_start, source_span.full_end),
            payload={
                "strategy": strategy,
                "candidate_id": row.get("candidate_id"),
                "family": row.get("family"),
                "source_generation_fallback": "expression-interferer-repair",
                "expected_effect": row.get("expected_effect"),
                "rationale": row.get("rationale"),
                "source_hunks": row.get("source_hunks", []),
                "blocker_cases": row.get("blocker_cases", []),
                "span_text": source_function_text,
                "replacement_text": replacement_text,
            },
        )
        result.append((anchor, candidate_text))
    return tuple(result)


def _basic_callarg_local_structural_diagnostics(
    body_text: str,
    *,
    anchors: list[Anchor],
    function_header_text: str = "",
) -> dict[str, Any]:
    strategies = sorted(
        {
            str(anchor.payload.get("strategy"))
            for anchor in anchors
            if anchor.payload.get("strategy")
        }
    )
    parsed = _callarg_local_structural_match_diagnostics(
        body_text,
        function_header_text=function_header_text,
    )
    rejection_reasons = list(parsed.get("rejection_reasons") or [])
    call_count = len(re.findall(r"\bHSD_JObjReqAnimAll\s*\(", body_text))
    if not anchors and not rejection_reasons:
        rejection_reasons.append("source-pattern-not-found")
    return {
        "hsd_jobj_req_anim_all_calls": call_count,
        "candidate_callarg_spans": len(anchors),
        "accepted_anchor_count": len(anchors),
        "rowf_locals": list(parsed.get("rowf_locals") or []),
        "call_arg_locals": list(parsed.get("call_arg_locals") or []),
        "call_arg_local_kinds": list(parsed.get("call_arg_local_kinds") or []),
        "has_existing_fresh_callarg_local": bool(
            parsed.get("has_existing_fresh_callarg_local")
        ),
        "generated_strategies": strategies,
        "rejection_reasons": rejection_reasons,
    }


def _basic_indexed_byte_diagnostics(
    source_text: str,
    body_text: str,
    *,
    force_class_id: int | None,
) -> dict[str, Any]:
    return {
        "requested_force_class": force_class_id,
        "byte_local_decls": len(re.findall(r"(?m)^[ \t]*(?:u8|s8)\s+\w+\s*;", body_text)),
        "byte_array_or_pointer_decls": len(
            re.findall(r"\b(?:u8|s8)\s*(?:\*|\w+\s*\[)", source_text)
        ),
        "indexed_byte_expressions": len(
            re.findall(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?\s*\[[^\]\n]+\]", body_text)
        ),
    }


def _window_order_context_mapping(
    window_order_continuation: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if window_order_continuation is None:
        return None
    return window_order_continuation


def _target_live_range_repair_goals(
    window_order_context: Mapping[str, Any] | None,
    *,
    function: str,
    force_phys: Mapping[int, int],
    source_text: str | None = None,
    virtual_explain_context: Mapping[str, Any] | None = None,
) -> list[Mapping[str, Any]]:
    goals: list[Mapping[str, Any]] = []
    blocker_chain_goals = _blocker_color_chain_repair_goals(
        virtual_explain_context,
        function=function,
        force_phys=force_phys,
        source_text=source_text,
    )
    if blocker_chain_goals:
        return blocker_chain_goals
    if window_order_context is not None:
        raw_goals = window_order_context.get("retained_case_c_repair_goals")
        if isinstance(raw_goals, list):
            goals.extend(goal for goal in raw_goals if isinstance(goal, Mapping))
    if goals:
        return goals
    if (
        function in {"mnDiagram_SortNamesByKOs", "mnDiagram_8023FC28"}
        and force_phys.get(34) == 27
        and force_phys.get(44) == 25
    ):
        value_expression, address_expression = _sort_case_c_source_expressions(
            source_text,
            function=function,
        )
        return [{
            "kind": "target-aware-live-range-interference",
            "target_ig": 44,
            "target_phys": 25,
            "protected_targets": {"34": 27},
            "interferer_ig": 39,
            "interferer_phys": 25,
            "source_expression": value_expression,
            "address_source_expression": address_expression,
            "address_index": "max_idx",
            "value_index": "j",
            "duplicate_value_ig": 41,
            "source_type": "u8",
            "required_delta": 6,
            "desired_effects": [
                "shrink-interferer-live-range",
                "increase-target-interference",
                "materialize-address-side-temp",
                "duplicate-value-side-temp",
                "test-coupled-address-value-relation",
            ],
            "evidence": {
                "kind": "issue-930-default",
                "summary": (
                    "r44 address temp and r39/r41 value temps need coupled "
                    "source probes after target-live-range probes exhausted"
                ),
            },
        }]
    if (
        function == "mnDiagram_DrawCellNumber"
        and force_phys.get(37) == 26
    ):
        return _draw_fpr_case_c_target_live_range_repair_goals(
            source_text,
            function=function,
            force_phys=force_phys,
        )
    return []


def _draw_fpr_case_c_target_live_range_repair_goals(
    source_text: str | None,
    *,
    function: str,
    force_phys: Mapping[int, int],
) -> list[Mapping[str, Any]]:
    protected_targets: dict[str, int] = {}
    if force_phys.get(32) is not None:
        protected_targets["32"] = int(force_phys[32])
    target_phys = force_phys.get(37)
    if target_phys is None:
        return []
    row_adjusted_local = _first_source_expression_candidate(
        source_text,
        function=function,
        candidates=("row_offset_adj",),
    )
    row_adjusted_owner = _first_source_expression_candidate(
        source_text,
        function=function,
        candidates=(
            "row_offset - 0.4f",
            "row_offset - 0.4F",
        ),
    )
    col_offset_local = _first_source_expression_candidate(
        source_text,
        function=function,
        candidates=("col_offset",),
    )
    goals: list[Mapping[str, Any]] = []

    def add_goal(
        *,
        source_expression: str | None,
        interferer_ig: int,
        interferer_phys: int | None,
        desired_effects: list[str],
        evidence_summary: str,
        paired_source_expression: str | None = None,
        paired_interferer_ig: int | None = None,
    ) -> None:
        if source_expression is None:
            return
        goal = {
            "kind": "target-aware-fpr-live-range-interference",
            "target_ig": 37,
            "target_phys": int(target_phys),
            "protected_targets": protected_targets,
            "interferer_ig": interferer_ig,
            "interferer_phys": interferer_phys,
            "source_expression": source_expression,
            "source_type": "f32",
            "required_delta": 1,
            "desired_effects": desired_effects,
            "target_order": [32, 37],
            "evidence": {
                "kind": "issue-945-default",
                "summary": evidence_summary,
            },
        }
        if paired_source_expression is not None:
            goal["paired_source_expression"] = paired_source_expression
        if paired_interferer_ig is not None:
            goal["paired_interferer_ig"] = paired_interferer_ig
        goals.append(goal)

    add_goal(
        source_expression=row_adjusted_local,
        interferer_ig=37,
        interferer_phys=target_phys,
        desired_effects=[
            "anchor-row-offset-adj-live-range",
            "increase-target-interference",
            "test-scalar-fpr-interference-shape",
        ],
        paired_source_expression=col_offset_local,
        paired_interferer_ig=32,
        evidence_summary=(
            "anchor retained IG37 row_offset_adj use so target order 32<37 can "
            "move IG37 from f27 to f26"
        ),
    )
    add_goal(
        source_expression=row_adjusted_owner,
        interferer_ig=37,
        interferer_phys=target_phys,
        desired_effects=[
            "materialize-row-offset-adj-owner-expression",
            "increase-target-interference",
            "test-scalar-fpr-interference-shape",
        ],
        paired_source_expression=col_offset_local,
        paired_interferer_ig=32,
        evidence_summary=(
            "materialize the row_offset_adj fsubs owner expression under the "
            "retained target-live-range scoring path"
        ),
    )
    add_goal(
        source_expression=col_offset_local,
        interferer_ig=32,
        interferer_phys=force_phys.get(32),
        desired_effects=[
            "reduce-col-offset-degree",
            "reshape-ig32-live-range",
            "test-scalar-fpr-interference-shape",
        ],
        paired_source_expression=row_adjusted_local,
        paired_interferer_ig=37,
        evidence_summary=(
            "reshape retained IG32 col_offset source use while preserving IG37"
        ),
    )
    return goals


def _target_live_range_family_id_for_goal(goal: Mapping[str, Any]) -> str:
    kind = str(goal.get("kind") or "")
    source_type = str(goal.get("source_type") or "").lower()
    if "fpr" in kind or source_type in {"f32", "float", "double"}:
        return RETAINED_FPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID
    return RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID


def _target_live_range_family_ids_for_goals(
    goals: IterableABC[Mapping[str, Any]],
) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_target_live_range_family_id_for_goal(goal) for goal in goals))


def _target_live_range_goals_for_family(
    goals: IterableABC[Mapping[str, Any]],
    family_id: str,
) -> list[Mapping[str, Any]]:
    return [
        goal
        for goal in goals
        if _target_live_range_family_id_for_goal(goal) == family_id
    ]


def _blocker_color_chain_repair_goals(
    virtual_explain_context: Mapping[str, Any] | None,
    *,
    function: str,
    force_phys: Mapping[int, int],
    source_text: str | None,
) -> list[Mapping[str, Any]]:
    if virtual_explain_context is None or not force_phys:
        return []
    payload_function = virtual_explain_context.get("function")
    if (
        isinstance(payload_function, str)
        and payload_function
        and payload_function not in {function, *_SOURCE_FUNCTION_ALIASES.get(function, ())}
    ):
        return []
    virtuals = virtual_explain_context.get("virtuals")
    if not isinstance(virtuals, list):
        return []
    by_virtual: dict[int, Mapping[str, Any]] = {}
    for entry in virtuals:
        if not isinstance(entry, Mapping):
            continue
        virtual = _int_or_none(entry.get("virtual", entry.get("ig_idx")))
        if virtual is not None:
            by_virtual[virtual] = entry

    goals: list[Mapping[str, Any]] = []
    for root_ig, root_phys in sorted(force_phys.items()):
        root_entry = by_virtual.get(root_ig)
        if root_entry is None:
            continue
        first_blocker = _assigned_interferer(root_entry, root_phys)
        if first_blocker is None:
            continue
        first_blocker_ig = _int_or_none(first_blocker.get("virtual"))
        if first_blocker_ig is None or first_blocker_ig not in force_phys:
            continue
        target_phys = int(force_phys[first_blocker_ig])
        target_entry = by_virtual.get(first_blocker_ig)
        if target_entry is None:
            continue
        second_blocker = _assigned_interferer(target_entry, target_phys)
        if second_blocker is None:
            continue
        second_blocker_ig = _int_or_none(second_blocker.get("virtual"))
        if second_blocker_ig is None:
            continue
        value_expression, address_expression = _sort_case_c_source_expressions(
            source_text,
            function=function,
        )
        chain = [
            _blocker_chain_edge(
                target_ig=root_ig,
                target_phys=root_phys,
                blocker=first_blocker,
                by_virtual=by_virtual,
            ),
            _blocker_chain_edge(
                target_ig=first_blocker_ig,
                target_phys=target_phys,
                blocker=second_blocker,
                by_virtual=by_virtual,
            ),
        ]
        goals.append({
            "kind": "target-aware-live-range-interference",
            "target_ig": first_blocker_ig,
            "target_phys": target_phys,
            "protected_targets": {
                str(ig): int(phys)
                for ig, phys in sorted(force_phys.items())
                if ig != first_blocker_ig
            },
            "interferer_ig": second_blocker_ig,
            "interferer_phys": target_phys,
            "source_expression": value_expression,
            "address_source_expression": address_expression,
            "address_index": "max_idx",
            "value_index": "j",
            "duplicate_value_ig": second_blocker_ig,
            "source_type": "u8",
            "required_delta": _blocker_chain_required_delta(
                target_entry,
                by_virtual.get(second_blocker_ig),
                fallback=6,
            ),
            "desired_effects": [
                "move-blocker-from-target-phys",
                "shrink-blocker-live-range",
                "materialize-blocker-source-owner",
                "test-coupled-address-value-relation",
            ],
            "blocker_color_chain": chain,
            "evidence": {
                "kind": "blocker-color-chain",
                "payload_path": virtual_explain_context.get("payload_path"),
                "summary": _blocker_chain_summary(chain),
            },
        })
        goals.extend(
            _blocker_operand_source_owner_repair_goals(
                chain,
                force_phys=force_phys,
            )
        )
    return goals


def _assigned_interferer(
    entry: Mapping[str, Any],
    assigned_reg: int,
) -> Mapping[str, Any] | None:
    interferers = entry.get("interferers")
    if not isinstance(interferers, list):
        return None
    matches = [
        interferer for interferer in interferers
        if isinstance(interferer, Mapping)
        and _int_or_none(interferer.get("assigned_reg")) == int(assigned_reg)
        and _int_or_none(interferer.get("virtual")) is not None
    ]
    matches.sort(key=lambda item: _int_or_none(item.get("virtual")) or 999999)
    return matches[0] if matches else None


def _blocker_chain_edge(
    *,
    target_ig: int,
    target_phys: int,
    blocker: Mapping[str, Any],
    by_virtual: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    source = blocker.get("source")
    blocker_ig = _int_or_none(blocker.get("virtual"))
    edge = {
        "target_ig": int(target_ig),
        "target_phys": int(target_phys),
        "blocker_ig": blocker_ig,
        "blocker_phys": _int_or_none(blocker.get("assigned_reg")),
        "blocker_source": dict(source) if isinstance(source, Mapping) else None,
    }
    if isinstance(source, Mapping):
        operands = _blocker_source_operand_sources(source, by_virtual)
        if operands:
            edge["blocker_operand_sources"] = operands
    return edge


_PCODE_VIRTUAL_REGISTER_RE = re.compile(r"\br(?P<virtual>\d+)\b")


def _blocker_source_operand_sources(
    source: Mapping[str, Any],
    by_virtual: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    operands_text = _pcode_source_operands_text(source)
    if operands_text is None:
        return []
    registers = [
        int(match.group("virtual"))
        for match in _PCODE_VIRTUAL_REGISTER_RE.finditer(operands_text)
    ]
    if len(registers) <= 1:
        return []
    out: list[dict[str, Any]] = []
    for operand_index, operand_virtual in enumerate(registers[1:], start=1):
        entry = by_virtual.get(operand_virtual)
        payload: dict[str, Any] = {
            "operand_index": operand_index,
            "operand_virtual": operand_virtual,
        }
        if isinstance(entry, Mapping):
            payload["operand_assigned_reg"] = _int_or_none(
                entry.get("assigned_reg")
            )
            live_range = entry.get("live_range")
            if isinstance(live_range, list):
                payload["operand_live_range"] = list(live_range)
            operand_source = entry.get("source")
            if isinstance(operand_source, Mapping):
                payload["source"] = dict(operand_source)
        out.append(payload)
    return out


def _pcode_source_operands_text(source: Mapping[str, Any]) -> str | None:
    first_def = source.get("first_def")
    if isinstance(first_def, Mapping):
        operands = first_def.get("operands")
        if isinstance(operands, str) and operands.strip():
            return operands.strip()
    expression = source.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        return None
    parts = expression.strip().split(None, 1)
    return parts[1].strip() if len(parts) == 2 else parts[0].strip()


def _blocker_operand_source_owner_repair_goals(
    chain: list[Mapping[str, Any]],
    *,
    force_phys: Mapping[int, int],
) -> list[Mapping[str, Any]]:
    goals: list[Mapping[str, Any]] = []
    for edge in chain:
        operand_sources = edge.get("blocker_operand_sources")
        if not isinstance(operand_sources, list):
            continue
        target_ig = _operand_owner_goal_target_ig(edge, force_phys)
        target_phys = _operand_owner_goal_target_phys(edge, force_phys, target_ig)
        if target_ig is None or target_phys is None:
            continue
        protected_targets = {
            str(ig): int(phys)
            for ig, phys in sorted(force_phys.items())
            if ig != target_ig
        }
        for operand in operand_sources:
            if not isinstance(operand, Mapping):
                continue
            operand_virtual = _int_or_none(operand.get("operand_virtual"))
            if operand_virtual is None:
                continue
            source = operand.get("source")
            expression = (
                _source_owner_expression(source)
                if isinstance(source, Mapping)
                else None
            )
            if expression is None:
                continue
            source_type = (
                source.get("type")
                if isinstance(source, Mapping)
                and isinstance(source.get("type"), str)
                else "int"
            )
            owner = {
                "target_ig": edge.get("target_ig"),
                "target_phys": edge.get("target_phys"),
                "blocker_ig": edge.get("blocker_ig"),
                "blocker_phys": edge.get("blocker_phys"),
                "operand_index": operand.get("operand_index"),
                "operand_virtual": operand_virtual,
                "operand_assigned_reg": operand.get("operand_assigned_reg"),
                "source": dict(source) if isinstance(source, Mapping) else None,
            }
            goals.append({
                "kind": "target-aware-live-range-interference",
                "target_ig": target_ig,
                "target_phys": target_phys,
                "protected_targets": protected_targets,
                "interferer_ig": operand_virtual,
                "interferer_phys": operand.get("operand_assigned_reg"),
                "source_expression": expression,
                "source_type": source_type,
                "required_delta": 4,
                "source_probe_kind": "target-aware-blocker-operand-source-anchor",
                "source_owner_strategy": "blocker-operand-source-temp",
                "operand_source_owner": owner,
                "desired_effects": [
                    "expand-implicit-blocker-operand-source-owner",
                    "materialize-operand-source-owner",
                    "move-blocker-from-target-phys",
                ],
                "blocker_color_chain": [dict(item) for item in chain],
                "evidence": {
                    "kind": "blocker-operand-source-owner",
                    "summary": (
                        f"ig{edge.get('blocker_ig')} operand "
                        f"r{operand_virtual} feeds implicit blocker pcode"
                    ),
                },
            })
    return goals


def _operand_owner_goal_target_ig(
    edge: Mapping[str, Any],
    force_phys: Mapping[int, int],
) -> int | None:
    blocker_ig = _int_or_none(edge.get("blocker_ig"))
    if blocker_ig is not None and blocker_ig in force_phys:
        return blocker_ig
    return _int_or_none(edge.get("target_ig"))


def _operand_owner_goal_target_phys(
    edge: Mapping[str, Any],
    force_phys: Mapping[int, int],
    target_ig: int | None,
) -> int | None:
    if target_ig is None:
        return None
    if target_ig in force_phys:
        return int(force_phys[target_ig])
    return _int_or_none(edge.get("target_phys"))


def _source_owner_expression(source: Mapping[str, Any]) -> str | None:
    for key in ("expression", "name", "var_name"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _blocker_chain_summary(chain: list[Mapping[str, Any]]) -> str:
    parts = []
    for edge in chain:
        parts.append(
            f"ig{edge.get('target_ig')} wants r{edge.get('target_phys')} "
            f"blocked by ig{edge.get('blocker_ig')}"
        )
    return "; ".join(parts)


def _blocker_chain_required_delta(
    target_entry: Mapping[str, Any],
    blocker_entry: Mapping[str, Any] | None,
    *,
    fallback: int,
) -> int:
    target_range = _live_range_tuple(target_entry)
    blocker_range = _live_range_tuple(blocker_entry)
    if target_range is None or blocker_range is None:
        return fallback
    overlap = min(target_range[1], blocker_range[1]) - max(
        target_range[0],
        blocker_range[0],
    )
    return max(1, overlap) if overlap > 0 else fallback


def _live_range_tuple(entry: Mapping[str, Any] | None) -> tuple[int, int] | None:
    if entry is None:
        return None
    raw = entry.get("live_range")
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    start = _int_or_none(raw[0])
    end = _int_or_none(raw[1])
    if start is None or end is None:
        return None
    return start, end


def _retained_case_c_value_source_expression(
    source_text: str | None,
    *,
    function: str,
) -> str | None:
    return _first_source_expression_candidate(
        source_text,
        function=function,
        candidates=(
            "sorted_names[j]",
            "sorted_names_base_probe[window_order_mnDiagram_804A076C_sorted_names_index_probe]",
            "mnDiagram_804A076C.sorted_names[(0, j)]",
            "mnDiagram_804A076C.sorted_names[j]",
            "mnDiagram_804A076C.sorted_names[window_order_mnDiagram_804A076C_sorted_names_index_probe_2]",
        ),
    )


def _retained_case_c_address_source_expression(
    source_text: str | None,
    *,
    function: str,
) -> str | None:
    return _first_source_expression_candidate(
        source_text,
        function=function,
        candidates=(
            "sorted_names[(max_idx)]",
            "sorted_names[max_idx]",
            "mnDiagram_804A076C.sorted_names[(max_idx)]",
            "mnDiagram_804A076C.sorted_names[max_idx]",
        ),
    )


def _sort_case_c_source_expressions(
    source_text: str | None,
    *,
    function: str,
) -> tuple[str, str]:
    value_expression = _retained_case_c_value_source_expression(
        source_text,
        function=function,
    )
    address_expression = _retained_case_c_address_source_expression(
        source_text,
        function=function,
    )
    return (
        value_expression or "mnDiagram_804A076C.sorted_names[j]",
        address_expression or "mnDiagram_804A076C.sorted_names[max_idx]",
    )


def _first_source_expression_candidate(
    source_text: str | None,
    *,
    function: str,
    candidates: IterableABC[str],
) -> str | None:
    if source_text is None:
        return None
    target = _resolve_target_function(
        source_text,
        function=function,
        function_aliases=_SOURCE_FUNCTION_ALIASES.get(function, ()),
    )
    if target is None:
        haystack = source_text
    else:
        span, _body = target[1]
        haystack = source_text[span.body_open:span.full_end]
    for candidate in candidates:
        if candidate in haystack:
            return candidate
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _repair_goals_attempted_targets(
    goals: IterableABC[Mapping[str, Any]],
    *,
    force_phys: Mapping[int, int],
) -> dict[str, int]:
    attempted: dict[str, int] = {}
    for goal in goals:
        target_ig = _int_or_none(goal.get("target_ig"))
        target_phys = _int_or_none(goal.get("target_phys"))
        if target_ig is None:
            continue
        if target_phys is None:
            target_phys = force_phys.get(target_ig)
        if target_phys is not None:
            attempted[str(target_ig)] = int(target_phys)
    return attempted


def _repair_goals_protected_targets(
    goals: IterableABC[Mapping[str, Any]],
    *,
    force_phys: Mapping[int, int],
) -> dict[str, int]:
    protected: dict[str, int] = {}
    attempted = _repair_goals_attempted_targets(goals, force_phys=force_phys)
    for goal in goals:
        raw = goal.get("protected_targets")
        if not isinstance(raw, Mapping):
            continue
        for key, value in raw.items():
            key_int = _int_or_none(key)
            value_int = _int_or_none(value)
            if key_int is not None and value_int is not None:
                protected[str(key_int)] = value_int
    if protected:
        return protected
    return {
        str(ig): int(phys)
        for ig, phys in sorted(force_phys.items())
        if str(ig) not in attempted
    }


def _simplify_order_continuation_goals(
    window_order_context: Mapping[str, Any] | None,
    *,
    function: str,
    force_phys: Mapping[int, int],
) -> list[Mapping[str, Any]]:
    goals: list[Mapping[str, Any]] = []
    if window_order_context is not None:
        raw_goals = window_order_context.get("retained_case_c_simplify_order_goals")
        if isinstance(raw_goals, list):
            goals.extend(
                _normalize_simplify_order_goal(goal, force_phys=force_phys)
                for goal in raw_goals
                if isinstance(goal, Mapping)
            )
        raw_residual = window_order_context.get("retained_case_c_lower_drift_residual")
        if isinstance(raw_residual, Mapping):
            goals.append(
                _normalize_lower_drift_residual_goal(
                    raw_residual,
                    force_phys=force_phys,
                )
            )
        elif isinstance(raw_residual, list):
            goals.extend(
                _normalize_lower_drift_residual_goal(goal, force_phys=force_phys)
                for goal in raw_residual
                if isinstance(goal, Mapping)
            )
    if goals:
        return goals
    if window_order_context is None:
        return []
    if (
        function in {"mnDiagram_SortNamesByKOs", "mnDiagram_8023FC28"}
        and force_phys.get(34) == 27
        and force_phys.get(44) == 25
    ):
        return [{
            "kind": "retained-case-c-simplify-order",
            "target_ig": 44,
            "target_phys": 25,
            "protected_targets": {"34": 27},
            "final_force_phys": _force_phys_summary(force_phys),
            "baseline_first_divergence": {
                "class_id": 0,
                "iter": 40,
                "ig_idx": 44,
                "case": "C",
            },
            "desired_effects": [
                "move-ig44-case-c-simplify-order",
                "preserve-protected-ig34",
                "avoid-pointer-walk-materialization",
            ],
            "evidence": {
                "kind": "issue-932-default",
                "summary": (
                    "target-live-range probes exhausted with IG34 preserved "
                    "and IG44 still diverging at Case-C iter 40"
                ),
            },
        }]
    return []


def _normalize_simplify_order_goal(
    goal: Mapping[str, Any],
    *,
    force_phys: Mapping[int, int],
) -> dict[str, Any]:
    normalized = dict(goal)
    if "final_force_phys" not in normalized:
        normalized["final_force_phys"] = _force_phys_summary(force_phys)
    return normalized


def _normalize_lower_drift_residual_goal(
    goal: Mapping[str, Any],
    *,
    force_phys: Mapping[int, int],
) -> dict[str, Any]:
    normalized = _normalize_simplify_order_goal(goal, force_phys=force_phys)
    normalized.setdefault("kind", "retained-case-c-lower-drift-residual")
    normalized.setdefault("target_ig", 34)
    if "target_phys" not in normalized and 34 in force_phys:
        normalized["target_phys"] = int(force_phys[34])
    normalized.setdefault("protected_targets", {"44": 26})
    normalized.setdefault("final_force_phys", _force_phys_summary(force_phys))
    return normalized


def _goal_attempted_targets(
    goals: IterableABC[Mapping[str, Any]],
    *,
    force_phys: Mapping[int, int],
) -> dict[str, int]:
    attempted: dict[str, int] = {}
    for goal in goals:
        try:
            target_ig = int(goal.get("target_ig"))
        except (TypeError, ValueError):
            continue
        target_phys = goal.get("target_phys")
        if target_phys is None:
            target_phys = force_phys.get(target_ig)
        try:
            attempted[str(target_ig)] = int(target_phys)
        except (TypeError, ValueError):
            continue
    return attempted


def _goal_protected_targets(
    goals: IterableABC[Mapping[str, Any]],
) -> dict[str, int]:
    protected: dict[str, int] = {}
    for goal in goals:
        protected.update(_normalized_target_mapping(goal.get("protected_targets")))
    return protected


def _window_order_source_attr_for_ig(
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None,
    target_ig: int,
) -> Any:
    if not isinstance(source_attributions, Mapping):
        return None
    for key in (target_ig, str(target_ig)):
        if key in source_attributions:
            return source_attributions[key]
    return None


def _window_order_attr_kind(source_attr: Any) -> str | None:
    if isinstance(source_attr, Mapping):
        kind = source_attr.get("kind")
        return str(kind) if kind is not None else None
    kind = getattr(source_attr, "kind", None)
    return str(kind) if kind is not None else None


def _window_order_lead_target_ig(lead: Any) -> int | None:
    if not isinstance(lead, Mapping):
        return None
    value = lead.get("target_ig")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _window_order_probe_target_ig(probe: LifetimeLayoutProbe) -> int | None:
    provenance = probe.provenance if isinstance(probe.provenance, Mapping) else {}
    lead = provenance.get("lead")
    return _window_order_lead_target_ig(lead)


def _window_order_probe_source_kind(probe: LifetimeLayoutProbe) -> str | None:
    provenance = probe.provenance if isinstance(probe.provenance, Mapping) else {}
    return _window_order_attr_kind(provenance.get("source_attribution"))


def _window_order_probe_ranked_indexed_candidate(
    probe: LifetimeLayoutProbe,
) -> Mapping[str, Any] | None:
    provenance = probe.provenance if isinstance(probe.provenance, Mapping) else {}
    if provenance.get("kind") != "window-order-ranked-indexed-byte-source-probe":
        return None
    candidate = provenance.get("ranked_indexed_byte_source_candidate")
    return candidate if isinstance(candidate, Mapping) else None


def _is_window_order_ranked_owner_probe(probe: LifetimeLayoutProbe) -> bool:
    return probe.label.startswith((
        "window-order-ranked-indexed-byte-",
        "window-order-ranked-end-pointer-",
        "window-order-li-constant-",
        "window-order-pointer-walk-add-",
        "window-order-field-load-",
        "window-order-call-return-",
    ))


def _ranked_indexed_candidate_rank(candidate: Mapping[str, Any] | None) -> int:
    if candidate is None:
        return 999999
    try:
        return int(candidate.get("rank"))
    except (TypeError, ValueError):
        return 999999


def _with_post_source_owner_backtrack_metadata(
    probe: LifetimeLayoutProbe,
    *,
    skipped_current_owner_labels: tuple[str, ...],
) -> LifetimeLayoutProbe:
    provenance = dict(probe.provenance or {})
    candidate = _window_order_probe_ranked_indexed_candidate(probe)
    post_metadata: dict[str, Any] = {
        "skipped_current_owner_labels": list(skipped_current_owner_labels),
    }
    if candidate is not None:
        post_metadata.update({
            "candidate_rank": candidate.get("rank"),
            "span_text": candidate.get("span_text"),
            "array_base": candidate.get("array_base"),
            "index_expr": candidate.get("index_expr"),
            "line_range": [
                candidate.get("line_start"),
                candidate.get("line_end"),
            ],
        })
    provenance["post_source_owner_backtrack"] = post_metadata
    return LifetimeLayoutProbe(
        label=probe.label,
        operator=probe.operator,
        description=(
            "Materialize an alternate ranked indexed-byte source-owner span "
            "after the current window-order owner was exhausted."
        ),
        source_text=probe.source_text,
        provenance=provenance,
    )


def _compact_source_diff(source_text: str, candidate_text: str) -> str:
    return "".join(
        difflib.unified_diff(
            source_text.splitlines(keepends=True),
            candidate_text.splitlines(keepends=True),
            fromfile="source",
            tofile="window-order-continuation",
            n=3,
        )
    )


def _force_phys_summary(force_phys: Mapping[int, int]) -> dict[str, int]:
    return {str(ig): int(phys) for ig, phys in sorted(force_phys.items())}


def _normalized_target_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, map_value in value.items():
        try:
            result[str(key)] = int(map_value)
        except (TypeError, ValueError):
            continue
    return result


def _lifetime_probe_mutator_key(family_id: str) -> str:
    if family_id == RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_FAMILY_ID:
        return RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_MUTATOR_KEY
    if family_id == RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID:
        return RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_MUTATOR_KEY
    if family_id == RETAINED_FPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID:
        return RETAINED_FPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_MUTATOR_KEY
    if family_id == RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_FAMILY_ID:
        return RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_MUTATOR_KEY
    return RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_MUTATOR_KEY


def _lifetime_layout_probe_to_transform_probe(
    probe: LifetimeLayoutProbe,
    *,
    family_id: str,
    index: int,
    source_text: str,
    plan: TransformExperimentPlan,
    force_phys: Mapping[int, int],
) -> TransformProbe:
    family = _FAMILY_BY_ID[family_id]
    region, target_assignments = _region_for_family(plan, family_id)
    provenance = probe.provenance if isinstance(probe.provenance, Mapping) else {}
    lead = provenance.get("lead")
    lead_dict = dict(lead) if isinstance(lead, Mapping) else {}
    target_ig = _window_order_lead_target_ig(lead)
    if target_ig is None:
        try:
            target_ig = int(provenance.get("target_ig"))
        except (TypeError, ValueError):
            target_ig = None
    source_attribution = provenance.get("source_attribution")
    protected_targets = _normalized_target_mapping(
        provenance.get("protected_targets")
    )
    if not protected_targets:
        protected_targets = {
            str(ig): int(phys)
            for ig, phys in sorted(force_phys.items())
            if target_ig is None or ig != target_ig
        }
    target_phys = provenance.get("target_phys")
    attempted_targets = {}
    if target_ig is not None:
        try:
            attempted_targets = {
                str(target_ig): int(
                    target_phys if target_phys is not None else force_phys[target_ig]
                )
            }
        except (KeyError, TypeError, ValueError):
            attempted_targets = {}
    payload = {
        "window_order_label": probe.label,
        "window_order_operator": probe.operator,
        "window_order_description": probe.description,
        "lead": lead_dict,
        "lead_target_ig": target_ig,
        "order_move": lead_dict.get("order_move"),
        "perturbed_reg": lead_dict.get("perturbed_reg"),
        "source_attribution": (
            dict(source_attribution)
            if isinstance(source_attribution, Mapping)
            else source_attribution
        ),
        "synthetic_source_probe": provenance.get("synthetic_source_probe"),
        "ranked_indexed_byte_source_candidate": provenance.get(
            "ranked_indexed_byte_source_candidate"
        ),
        "ranked_end_pointer_source_candidate": provenance.get(
            "ranked_end_pointer_source_candidate"
        ),
        "ranked_li_constant_source_candidate": provenance.get(
            "ranked_li_constant_source_candidate"
        ),
        "ranked_pointer_walk_add_source_candidate": provenance.get(
            "ranked_pointer_walk_add_source_candidate"
        ),
        "field_load_source_candidate": provenance.get(
            "field_load_source_candidate"
        ),
        "call_return_source_probe": provenance.get(
            "call_return_source_probe"
        ),
        "pcode_first_def": provenance.get("pcode_first_def"),
        "source_hunks": provenance.get("source_hunks"),
        "post_source_owner_backtrack": provenance.get(
            "post_source_owner_backtrack"
        ),
        "source_diff": provenance.get("source_diff")
        or _compact_source_diff(source_text, probe.source_text),
        "force_phys_targets": _force_phys_summary(force_phys),
        "protected_targets": protected_targets,
        "attempted_targets": attempted_targets,
        "source_probe_provenance_kind": provenance.get("kind"),
    }
    for key in (
        "repair_goal",
        "target_ig",
        "target_phys",
        "interferer_ig",
        "interferer_phys",
        "required_delta",
        "ranked_repair_candidate",
        "exhaustion_key",
        "current_owner_span",
        "alternate_source_owner",
        "owner_graph_path",
        "attempted_force_phys_targets",
        "protected_force_phys_targets",
        "selected_force_phys_targets",
    ):
        if key in provenance:
            payload[key] = provenance[key]
    return TransformProbe(
        probe_id=f"{family_id}@{index}",
        family_id=family_id,
        family_label=family.label,
        mutator_key=_lifetime_probe_mutator_key(family_id),
        semantic_risk=family.semantic_risk,
        source_region=region,
        expected_compiler_effect=family.expected_compiler_effect,
        generated_probe_form=family.generated_probe_form,
        target_assignments=target_assignments,
        span=(0, len(source_text)),
        payload=payload,
        candidate_text=probe.source_text,
    )


def _finalize_family_diagnostics(
    plan: TransformExperimentPlan,
    *,
    family_stats: dict[str, dict[str, Any]],
    counts: dict[str, int],
    source_status: str,
) -> tuple[TransformFamilyMaterializationDiagnostic, ...]:
    rows: list[TransformFamilyMaterializationDiagnostic] = []
    for family_id, stat in family_stats.items():
        materialized_count = counts.get(family_id, 0)
        reason = stat.get("no_probe_reason")
        if materialized_count:
            reason = None
        elif reason is None:
            diagnostics = stat["matcher_diagnostics"]
            if source_status != "resolved":
                reason = source_status
            elif not stat["attempted"]:
                reason = "family-filtered-by-unit"
            elif (
                family_id == "coupled_fpr_coalesce_product_repair"
                and diagnostics.get("row_product_shape_detected")
            ):
                reason = "unsupported-case-a-row-product"
            elif stat["budget_limited"] and not materialized_count:
                reason = "probe-budget-starved"
            elif stat["candidate_anchor_count"] and not stat["applied_candidate_count"]:
                reason = "mutator-application-failed"
            elif stat["applied_candidate_count"]:
                reason = "deduped-with-existing-probe"
            else:
                specific_rejections = [
                    str(item)
                    for item in diagnostics.get("rejection_reasons", [])
                    if item != "source-pattern-not-found"
                ]
                reason = (
                    specific_rejections[0]
                    if specific_rejections
                    else "source-pattern-not-found"
                )
        rows.append(
            TransformFamilyMaterializationDiagnostic(
                family_id=family_id,
                attempt_status=str(stat["attempt_status"]),
                attempted=bool(stat["attempted"]),
                materialized_count=materialized_count,
                candidate_anchor_count=int(stat["candidate_anchor_count"]),
                applied_candidate_count=int(stat["applied_candidate_count"]),
                no_probe_reason=reason,
                budget_limited=bool(stat["budget_limited"]),
                matcher_diagnostics=dict(stat["matcher_diagnostics"]),
            )
        )
    return tuple(rows)


def _region_for_family(plan: TransformExperimentPlan, family_id: str) -> tuple[str, tuple[str, ...]]:
    for cluster in plan.clusters:
        if family_id in cluster.family_ids:
            return "; ".join(cluster.source_regions), cluster.target_assignments
    return "unclustered source region", ()


def _family_ids_for_anchor(anchor: Anchor) -> tuple[str, ...]:
    base_key = anchor.mutator_key.split("@", 1)[0]
    return _FAMILY_IDS_BY_MUTATOR.get(base_key, ())


def _requested_family_ids(families: IterableABC[str] | None) -> tuple[str, ...]:
    if families is None:
        return ()
    requested: list[str] = []
    for family in families:
        if family not in _FAMILY_BY_ID:
            raise ValueError(f"unknown transform family: {family}")
        requested.append(family)
    return tuple(dict.fromkeys(requested))


_ZERO_RETURN_TYPE_RE = re.compile(
    r"\b(?:bool|BOOL|s8|s16|s32|s64|u8|u16|u32|u64|int|short|long)\b"
)


_RETURN_TYPE_QUALIFIER_RE = re.compile(
    r"\b(?:static|inline|extern|const|volatile|register)\b"
)


def _allows_explicit_zero_return(source_text: str, function: str) -> bool:
    target = _target_function_body(source_text, function)
    if target is None:
        return False
    span, _body_text = target
    header = source_text[span.sig_start:span.body_open]
    name_index = header.rfind(function)
    if name_index < 0:
        return False
    return_type = _RETURN_TYPE_QUALIFIER_RE.sub(" ", header[:name_index])
    if "*" in return_type or re.search(r"\bvoid\b", return_type):
        return False
    return _ZERO_RETURN_TYPE_RE.search(return_type) is not None


def _function_lookup_names(
    function: str,
    function_aliases: IterableABC[str] | None,
) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for name in (
        function,
        *_SOURCE_FUNCTION_ALIASES.get(function, ()),
        *(function_aliases or ()),
    ):
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return tuple(names)


def _resolve_target_function(
    source_text: str,
    *,
    function: str,
    function_aliases: IterableABC[str] | None,
):
    for candidate in _function_lookup_names(function, function_aliases):
        target = _target_function_body(source_text, candidate)
        if target is not None:
            return candidate, target
    return None


def _scheduler_order_target_assignments(
    target: SchedulerOrderTarget,
) -> tuple[str, ...]:
    by_label = {
        "target_first": target.target_first,
        "target_second": target.target_second,
    }
    desired_first, desired_second = target.desired_order
    return (f"{by_label[desired_first].opcode} before {by_label[desired_second].opcode}",)


def _prototype_param_type(param: str) -> str | None:
    param = param.strip()
    if not param or param == "void" or "*" in param:
        return None
    parts = param.split()
    if len(parts) < 2:
        return None
    return _normalize_type_name(" ".join(parts[:-1]))


def _source_local_callee_arg_type(
    source_text: str,
    callee: str,
    arg_index: int,
) -> str | None:
    pattern = re.compile(
        r"(?m)^[ \t]*(?:static\s+|extern\s+)?[A-Za-z_]\w*(?:\s+\*?)?\s+"
        + re.escape(callee)
        + r"\s*\((?P<params>[^()]*)\)\s*(?:;|{)"
    )
    for match in pattern.finditer(source_text):
        params = _split_top_level_csv(match.group("params"))
        if params is None or arg_index >= len(params):
            continue
        param_type = _prototype_param_type(params[arg_index])
        if param_type is not None:
            return param_type
    return None


def _body_anchor_allowed(anchor: Anchor, source_text: str, unit: str) -> bool:
    base_key = anchor.mutator_key.split("@", 1)[0]
    if base_key == "elide_numeric_cast":
        cast_type = _normalize_type_name(str(anchor.payload.get("cast_type", "")))
        arg_type = _source_local_callee_arg_type(
            source_text,
            str(anchor.payload.get("callee", "")),
            int(anchor.payload.get("arg_index", -1)),
        )
        return arg_type == cast_type
    if base_key == "collapse_hsd_assert":
        expected_file = _source_file_for_unit(unit).rsplit("/", 1)[-1]
        return anchor.payload.get("file_name") == expected_file
    return True


def _iter_full_source_anchors(source_text: str, *, function: str):
    target = _target_function_body(source_text, function)
    if target is None:
        return
    span, _body_text = target
    yield from _iter_helper_shape_anchors(source_text, function, span)
    yield from _iter_same_type_local_lifetime_reuse_anchors(source_text, span)
    yield from _iter_function_codegen_pragma_anchors(source_text, function, span)
    yield from _iter_return_tail_call_anchors(source_text, function, span)
    yield from _iter_string_data_field_anchors(source_text, function)
    yield from _iter_global_float_literal_anchors(source_text, function, span)
    yield from _iter_fp_subtraction_reassociation_anchors(source_text, function, span)
    yield from _iter_named_zero_local_anchors(source_text, function, span)
    yield from _iter_global_pointer_alias_anchors(source_text, function, span)
    yield from _iter_raw_pointer_offset_anchors(source_text, span)
    yield from _iter_raw_index_struct_field_anchors(source_text, span)
    yield from _iter_data_table_indirection_anchors(source_text, span)
    yield from _iter_type_cast_compatibility_anchors(source_text, function, span)
    yield from _iter_unused_trailing_parameter_anchors(source_text, function, span)
    yield from _iter_outgoing_parameter_area_shape_anchors(
        source_text,
        function,
        span,
    )
    yield from _iter_indexed_byte_address_temp_anchors(source_text, function, span)
    yield from _iter_independent_statement_order_anchors(source_text, span)
    yield from _iter_ranked_cursor_iv_unification_anchors(source_text, function, span)


def _iter_target_function_anchors(source_text: str, function: str):
    target = _target_function_body(source_text, function)
    if target is None:
        return
    span, body_text = target
    body_start = span.body_open
    allow_explicit_zero_return = _allows_explicit_zero_return(source_text, function)
    for anchor in iter_source_shape_anchors(body_text):
        if anchor.mutator_key == "add_explicit_zero_return" and not allow_explicit_zero_return:
            continue
        start, end = anchor.span
        yield Anchor(
            mutator_key=anchor.mutator_key,
            span=(body_start + start, body_start + end),
            payload=anchor.payload,
        )


def generate_transform_probe_report(
    source_text: str | None,
    *,
    function: str,
    unit: str,
    force_phys: Mapping[int, int],
    force_class_id: int | None = None,
    function_aliases: IterableABC[str] | None = None,
    families: IterableABC[str] | None = None,
    max_per_family: int = 3,
    node_set_delta: Mapping[str, Any] | None = None,
    scheduler_order_target: Mapping[str, Any] | SchedulerOrderTarget | str | None = None,
    window_order_continuation: Mapping[str, Any] | None = None,
    coalesce_suggestion: Mapping[str, Any] | None = None,
    virtual_explain_context: Mapping[str, Any] | None = None,
    current_owner_exhaustion_context: Mapping[str, Any] | None = None,
) -> TransformProbeGenerationReport:
    """Instantiate applicable corpus families with materialization diagnostics."""

    plan = plan_transform_experiments(
        function=function,
        unit=unit,
        force_phys=force_phys,
    )
    requested_family_ids = _requested_family_ids(families)
    allowed = (
        set(requested_family_ids)
        if requested_family_ids
        else {family.family_id for family in plan.families}
    )
    if node_set_delta is not None:
        allowed.add("coloring_register_steering")
    window_order_context = _window_order_context_mapping(window_order_continuation)
    common_subexpr_coalesce_context = coalesce_suggestion
    target_live_range_goals = _target_live_range_repair_goals(
        window_order_context,
        function=function,
        force_phys=force_phys,
        source_text=source_text,
        virtual_explain_context=virtual_explain_context,
    )
    simplify_order_goals = _simplify_order_continuation_goals(
        window_order_context,
        function=function,
        force_phys=force_phys,
    )
    if window_order_context is not None:
        if (
            not requested_family_ids
            or RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID
            in requested_family_ids
        ):
            allowed.add(RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID)
        if (
            not requested_family_ids
            or RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_FAMILY_ID
            in requested_family_ids
        ):
            allowed.add(RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_FAMILY_ID)
        if (
            target_live_range_goals
        ):
            for family_id in _target_live_range_family_ids_for_goals(
                target_live_range_goals
            ):
                if not requested_family_ids or family_id in requested_family_ids:
                    allowed.add(family_id)
        if (
            simplify_order_goals
            and (
                not requested_family_ids
                or RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID
                in requested_family_ids
            )
        ):
            allowed.add(RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID)
    elif not requested_family_ids:
        allowed.discard(RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID)
        allowed.discard(RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_FAMILY_ID)
        allowed.discard(RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID)
        allowed.discard(RETAINED_FPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID)
        allowed.discard(RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID)
    if virtual_explain_context is not None and target_live_range_goals:
        for family_id in _target_live_range_family_ids_for_goals(
            target_live_range_goals
        ):
            if not requested_family_ids or family_id in requested_family_ids:
                allowed.add(family_id)
    if current_owner_exhaustion_context is not None:
        if (
            not requested_family_ids
            or RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_FAMILY_ID
            in requested_family_ids
        ):
            allowed.add(RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_FAMILY_ID)
    elif not requested_family_ids:
        allowed.discard(RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_FAMILY_ID)
    if common_subexpr_coalesce_context is not None:
        if (
            not requested_family_ids
            or RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID
            in requested_family_ids
        ):
            allowed.add(RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID)
    elif not requested_family_ids:
        allowed.discard(RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID)
    parsed_scheduler_target: SchedulerOrderTarget | None = None
    if scheduler_order_target is not None:
        parsed_scheduler_target = (
            scheduler_order_target
            if isinstance(scheduler_order_target, SchedulerOrderTarget)
            else parse_scheduler_order_target(scheduler_order_target)
        )
        allowed.add("scheduler_order_source_realizer")
        if not force_phys and not requested_family_ids and node_set_delta is None:
            allowed = {"scheduler_order_source_realizer"}
    function_names_tried = _function_lookup_names(function, function_aliases)
    resolved_aliases = function_names_tried[1:]
    source_resolution = {
        "status": "source-unavailable" if source_text is None else "resolved",
        "source_function": None,
        "function_names_tried": list(function_names_tried),
        "requested_function": function,
        "force_class_id": force_class_id,
    }
    if window_order_context is not None:
        source_resolution["window_order_continuation"] = {
            "status": "select-order-json-loaded",
            "payload_path": window_order_context.get("payload_path"),
        }
        if target_live_range_goals:
            source_resolution["target_live_range_repair"] = {
                "status": "repair-goals-loaded",
                "repair_goal_count": len(target_live_range_goals),
            }
        if simplify_order_goals:
            source_resolution["simplify_order_continuation"] = {
                "status": "simplify-order-goals-loaded",
                "simplify_order_goal_count": len(simplify_order_goals),
            }
    if common_subexpr_coalesce_context is not None:
        source_resolution["common_subexpr_coalesce"] = {
            "status": "coalesce-suggest-json-loaded",
            "payload_path": common_subexpr_coalesce_context.get("payload_path"),
            "suggest_function": common_subexpr_coalesce_context.get("function"),
            "suggest_mode": common_subexpr_coalesce_context.get("mode"),
        }
    if virtual_explain_context is not None:
        source_resolution["virtual_explain"] = {
            "status": "virtual-explain-json-loaded",
            "payload_path": virtual_explain_context.get("payload_path"),
            "virtual_count": (
                len(virtual_explain_context.get("virtuals"))
                if isinstance(virtual_explain_context.get("virtuals"), list)
                else 0
            ),
        }
        if target_live_range_goals:
            source_resolution["target_live_range_repair"] = {
                "status": "blocker-color-chain-goals-loaded",
                "repair_goal_count": len(target_live_range_goals),
            }
    if (
        target_live_range_goals
        and "target_live_range_repair" not in source_resolution
    ):
        source_resolution["target_live_range_repair"] = {
            "status": "repair-goals-loaded",
            "repair_goal_count": len(target_live_range_goals),
        }
    if current_owner_exhaustion_context is not None:
        source_resolution["current_owner_exhaustion"] = {
            "status": "current-owner-exhaustion-json-loaded",
            "payload_path": current_owner_exhaustion_context.get("payload_path"),
            "source_owner_terminal_span_count": len(
                current_owner_exhaustion_context.get(
                    "source_owner_terminal_spans",
                    [],
                )
                if isinstance(
                    current_owner_exhaustion_context.get(
                        "source_owner_terminal_spans",
                    ),
                    list,
                )
                else []
            ),
        }
    if source_text is None:
        family_stats = _seed_family_stats(
            plan,
            allowed=allowed,
            requested_family_ids=requested_family_ids,
            force_class_id=force_class_id,
            source_status="source-unavailable",
        )
        return TransformProbeGenerationReport(
            plan=plan,
            probes=(),
            family_diagnostics=_finalize_family_diagnostics(
                plan,
                family_stats=family_stats,
                counts={},
                source_status="source-unavailable",
            ),
            source_resolution=source_resolution,
        )
    resolved_target = _resolve_target_function(
        source_text,
        function=function,
        function_aliases=resolved_aliases,
    )
    if resolved_target is None:
        source_resolution["status"] = "source-pattern-not-found"
        family_stats = _seed_family_stats(
            plan,
            allowed=allowed,
            requested_family_ids=requested_family_ids,
            force_class_id=force_class_id,
            source_status="source-pattern-not-found",
        )
        return TransformProbeGenerationReport(
            plan=plan,
            probes=(),
            family_diagnostics=_finalize_family_diagnostics(
                plan,
                family_stats=family_stats,
                counts={},
                source_status="source-pattern-not-found",
            ),
            source_resolution=source_resolution,
        )
    source_function, target = resolved_target
    source_resolution["source_function"] = source_function
    function_span, body_text = target
    body_start = function_span.body_open
    body_end = function_span.full_end
    function_header_text = source_text[function_span.sig_start:function_span.body_open]
    allow_explicit_zero_return = _allows_explicit_zero_return(
        source_text,
        source_function,
    )
    family_stats = _seed_family_stats(
        plan,
        allowed=allowed,
        requested_family_ids=requested_family_ids,
        force_class_id=force_class_id,
        source_status="resolved",
    )
    global_types: Mapping[str, str] = {}
    try:
        source_path = Path(_source_file_for_unit(unit))
        context = build_source_field_context(
            source_text,
            function=source_function,
            source_file=source_path if source_path.exists() else None,
            melee_root=Path.cwd(),
        )
        global_types = context.global_types
    except Exception:
        global_types = {}
    if "indexed_byte_address_temp_steering" in family_stats:
        family_stats["indexed_byte_address_temp_steering"][
            "matcher_diagnostics"
        ].update(
            _basic_indexed_byte_diagnostics(
                source_text,
                body_text,
                force_class_id=force_class_id,
            )
        )
    counts: dict[str, int] = {}
    probes: list[TransformProbe] = []
    seen_candidate_texts: set[str] = set()

    def append_probe(
        *,
        family_id: str,
        anchor: Anchor,
        candidate_text: str,
        target_assignments_override: tuple[str, ...] | None = None,
    ) -> bool:
        if candidate_text in seen_candidate_texts:
            return False
        seen_candidate_texts.add(candidate_text)
        family = _FAMILY_BY_ID[family_id]
        region, target_assignments = _region_for_family(plan, family_id)
        if target_assignments_override is not None:
            target_assignments = target_assignments_override
        ordinal = counts.get(family_id, 0)
        counts[family_id] = ordinal + 1
        payload = dict(anchor.payload)
        payload.pop("candidate_text", None)
        probes.append(
            TransformProbe(
                probe_id=f"{family_id}@{ordinal}",
                family_id=family_id,
                family_label=family.label,
                mutator_key=anchor.mutator_key,
                semantic_risk=family.semantic_risk,
                source_region=region,
                expected_compiler_effect=family.expected_compiler_effect,
                generated_probe_form=family.generated_probe_form,
                target_assignments=target_assignments,
                span=anchor.span,
                payload=payload,
                candidate_text=candidate_text,
            )
        )
        return True

    def append_steering_probe_from_body_anchor(local_anchor: Anchor) -> None:
        family_id = "coloring_register_steering"
        if not _family_can_attempt(family_stats, allowed, family_id):
            return
        alias_key = _REGISTER_STEERING_ALIASES.get(local_anchor.mutator_key)
        if alias_key is None and local_anchor.mutator_key in _DIRECT_REGISTER_STEERING_KEYS:
            alias_key = local_anchor.mutator_key
        if alias_key is None:
            return
        start, end = local_anchor.span
        alias_local_anchor = Anchor(
            mutator_key=alias_key,
            span=local_anchor.span,
            payload=local_anchor.payload,
        )
        if not _family_candidate_allowed(
            family_stats,
            counts,
            allowed,
            family_id,
            alias_local_anchor,
            max_per_family=max_per_family,
        ):
            return
        candidate_body = apply_mutator(alias_key, alias_local_anchor, body_text)
        if candidate_body is None or candidate_body == body_text:
            return
        _note_family_applied(family_stats, family_id, alias_local_anchor)
        alias_anchor = Anchor(
            mutator_key=alias_key,
            span=(body_start + start, body_start + end),
            payload=local_anchor.payload,
        )
        append_probe(
            family_id="coloring_register_steering",
            anchor=alias_anchor,
            candidate_text=source_text[:body_start] + candidate_body + source_text[body_end:],
        )

    def append_steering_probe_from_source_anchor(anchor: Anchor) -> None:
        family_id = "coloring_register_steering"
        if not _family_can_attempt(family_stats, allowed, family_id):
            return
        alias_key = _REGISTER_STEERING_ALIASES.get(anchor.mutator_key)
        if alias_key is None and anchor.mutator_key in _DIRECT_REGISTER_STEERING_KEYS:
            alias_key = anchor.mutator_key
        if alias_key is None:
            return
        alias_anchor = Anchor(
            mutator_key=alias_key,
            span=anchor.span,
            payload=anchor.payload,
        )
        if not _family_candidate_allowed(
            family_stats,
            counts,
            allowed,
            family_id,
            alias_anchor,
            max_per_family=max_per_family,
        ):
            return
        candidate_text = apply_mutator(alias_key, alias_anchor, source_text)
        if candidate_text is None or candidate_text == source_text:
            return
        _note_family_applied(family_stats, family_id, alias_anchor)
        append_probe(
            family_id="coloring_register_steering",
            anchor=alias_anchor,
            candidate_text=candidate_text,
        )

    def build_report() -> TransformProbeGenerationReport:
        return TransformProbeGenerationReport(
            plan=plan,
            probes=tuple(probes),
            family_diagnostics=_finalize_family_diagnostics(
                plan,
                family_stats=family_stats,
                counts=counts,
                source_status=str(source_resolution["status"]),
            ),
            source_resolution=source_resolution,
        )

    common_subexpr_family_id = RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID
    if _family_can_attempt(family_stats, allowed, common_subexpr_family_id):
        stat = family_stats[common_subexpr_family_id]
        diagnostics = stat["matcher_diagnostics"]
        if common_subexpr_coalesce_context is None:
            stat["no_probe_reason"] = "missing-coalesce-suggest-payload"
            diagnostics.update({
                "status": "blocked",
                "terminal_blocker": "missing-coalesce-suggest-payload",
            })
        else:
            common_anchors = iter_common_subexpr_coalesce_anchors(
                source_text,
                function=source_function,
                coalesce_suggestion=common_subexpr_coalesce_context,
                force_phys=force_phys,
                max_candidates=max_per_family,
            )
            diagnostics.update(
                common_subexpr_coalesce_match_diagnostics(
                    source_text,
                    function=source_function,
                    coalesce_suggestion=common_subexpr_coalesce_context,
                    anchors=common_anchors,
                )
            )
            for common_anchor in common_anchors:
                if not _family_candidate_allowed(
                    family_stats,
                    counts,
                    allowed,
                    common_subexpr_family_id,
                    common_anchor,
                    max_per_family=max_per_family,
                ):
                    break
                candidate_text = common_anchor.payload.get("candidate_text")
                if not isinstance(candidate_text, str):
                    continue
                if candidate_text == source_text or candidate_text in seen_candidate_texts:
                    continue
                appended = append_probe(
                    family_id=common_subexpr_family_id,
                    anchor=common_anchor,
                    candidate_text=candidate_text,
                )
                if appended:
                    _note_family_applied(
                        family_stats,
                        common_subexpr_family_id,
                        common_anchor,
                    )
            if counts.get(common_subexpr_family_id, 0):
                diagnostics["status"] = "materialized"
                diagnostics["emitted_common_subexpr_probe_count"] = counts.get(
                    common_subexpr_family_id,
                    0,
                )
            else:
                terminal_blocker = diagnostics.get("terminal_blocker") or (
                    "common-subexpr-source-span-not-found"
                )
                stat["no_probe_reason"] = str(terminal_blocker)
                diagnostics["status"] = "blocked"
                diagnostics["terminal_blocker"] = str(terminal_blocker)

    window_order_family_id = RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID
    if _family_can_attempt(family_stats, allowed, window_order_family_id):
        stat = family_stats[window_order_family_id]
        diagnostics = stat["matcher_diagnostics"]
        if window_order_context is None:
            stat["no_probe_reason"] = "missing-select-order-payload"
            diagnostics["status"] = "blocked"
            diagnostics["terminal_blocker"] = "missing-select-order-payload"
        else:
            fallback_leads_raw = window_order_context.get("fallback_leads")
            fallback_leads = (
                list(fallback_leads_raw) if isinstance(fallback_leads_raw, list) else []
            )
            source_attributions = window_order_context.get("source_attributions")
            probe_diagnostics = window_order_context.get("probe_diagnostics")
            diagnostics.update({
                "status": "attempted",
                "payload_path": window_order_context.get("payload_path"),
                "fallback_lead_count": len(fallback_leads),
                "source_attribution_count": (
                    len(source_attributions)
                    if isinstance(source_attributions, Mapping)
                    else 0
                ),
                "force_phys_targets": _force_phys_summary(force_phys),
                "protected_targets": {},
                "attempted_targets": {},
            })
            if isinstance(probe_diagnostics, Mapping):
                diagnostics["select_order_probe_diagnostics"] = dict(
                    probe_diagnostics
                )
            if not fallback_leads:
                stat["no_probe_reason"] = "missing-window-order-fallback-leads"
                diagnostics["status"] = "blocked"
                diagnostics["terminal_blocker"] = (
                    "missing-window-order-fallback-leads"
                )
            else:
                window_plan = plan_window_order_source_probes(
                    source_text,
                    function=source_function,
                    fallback_leads=fallback_leads,
                    source_attributions=source_attributions,
                    max_probes=max_per_family,
                )
                window_probes = [
                    probe for probe in window_plan.probes
                    if probe.operator == "window-order-source-steering"
                ]
                filtered_window_probe_reasons: list[dict[str, Any]] = []
                selected_window_probes = []
                for probe in window_probes:
                    probe_target_ig = _window_order_probe_target_ig(probe)
                    if probe_target_ig is None:
                        filtered_window_probe_reasons.append({
                            "label": probe.label,
                            "reason": "missing-lead-target-ig",
                        })
                        continue
                    if probe_target_ig not in force_phys:
                        filtered_window_probe_reasons.append({
                            "label": probe.label,
                            "target_ig": probe_target_ig,
                            "reason": "target-not-in-force-phys",
                        })
                        continue
                    selected_window_probes.append(probe)
                selected_window_probes.sort(
                    key=lambda probe: (
                        not _is_window_order_ranked_owner_probe(probe),
                        _window_order_probe_target_ig(probe) or 999999,
                        probe.label,
                    )
                )
                selected_targets = sorted({
                    target_ig for probe in selected_window_probes
                    if (target_ig := _window_order_probe_target_ig(probe))
                    is not None
                })
                attempted_targets = {
                    str(target_ig): int(force_phys[target_ig])
                    for target_ig in selected_targets
                    if target_ig in force_phys
                }
                protected_targets = {
                    str(ig): int(phys)
                    for ig, phys in sorted(force_phys.items())
                    if ig not in set(selected_targets)
                }
                diagnostics.update({
                    "planned_window_order_probe_count": len(window_plan.probes),
                    "window_order_source_steering_probe_count": len(window_probes),
                    "selected_window_order_probe_count": len(
                        selected_window_probes
                    ),
                    "selected_window_order_targets": selected_targets,
                    "filtered_window_order_probe_count": (
                        len(window_probes) - len(selected_window_probes)
                    ),
                    "filtered_window_order_probe_reasons": (
                        filtered_window_probe_reasons
                    ),
                    "emitted_window_order_probe_count": 0,
                    "attempted_targets": attempted_targets,
                    "protected_targets": protected_targets,
                    "lead_diagnostics": list(window_plan.lead_diagnostics),
                })
                window_probe_skip_reasons: list[dict[str, Any]] = []
                for window_probe in selected_window_probes:
                    anchor = Anchor(
                        mutator_key=(
                            RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_MUTATOR_KEY
                        ),
                        span=(0, len(source_text)),
                        payload={
                            "window_order_label": window_probe.label,
                            "lead_target_ig": _window_order_probe_target_ig(
                                window_probe
                            ),
                        },
                    )
                    if not _family_candidate_allowed(
                        family_stats,
                        counts,
                        allowed,
                        window_order_family_id,
                        anchor,
                        max_per_family=max_per_family,
                    ):
                        window_probe_skip_reasons.append({
                            "label": window_probe.label,
                            "reason": "probe-budget-starved",
                        })
                        break
                    if window_probe.source_text == source_text:
                        window_probe_skip_reasons.append({
                            "label": window_probe.label,
                            "reason": "window-order-probe-noop",
                        })
                        continue
                    if window_probe.source_text in seen_candidate_texts:
                        window_probe_skip_reasons.append({
                            "label": window_probe.label,
                            "reason": "window-order-probe-deduped",
                        })
                        continue
                    seen_candidate_texts.add(window_probe.source_text)
                    transform_probe = _lifetime_layout_probe_to_transform_probe(
                        window_probe,
                        family_id=window_order_family_id,
                        index=counts.get(window_order_family_id, 0),
                        source_text=source_text,
                        plan=plan,
                        force_phys=force_phys,
                    )
                    counts[window_order_family_id] = (
                        counts.get(window_order_family_id, 0) + 1
                    )
                    probes.append(transform_probe)
                    _note_family_applied(
                        family_stats,
                        window_order_family_id,
                        anchor,
                    )
                    diagnostics["emitted_window_order_probe_count"] = counts.get(
                        window_order_family_id,
                        0,
                    )
                if window_probe_skip_reasons:
                    diagnostics["window_order_probe_skip_reasons"] = (
                        window_probe_skip_reasons
                    )
                if counts.get(window_order_family_id, 0):
                    diagnostics["status"] = "materialized"
                elif selected_window_probes:
                    first_skip_reason = (
                        window_probe_skip_reasons[0]["reason"]
                        if window_probe_skip_reasons
                        else "selected-window-order-probes-unmaterialized"
                    )
                    stat["no_probe_reason"] = str(first_skip_reason)
                    diagnostics["status"] = "blocked"
                    diagnostics["terminal_blocker"] = str(first_skip_reason)
                elif window_probes:
                    stat["no_probe_reason"] = "all-window-order-probes-filtered"
                    diagnostics["status"] = "blocked"
                    diagnostics["terminal_blocker"] = (
                        "all-window-order-probes-filtered"
                    )
                elif window_plan.lead_diagnostics:
                    lead_blockers = [
                        str(item.get("terminal_blocker"))
                        for item in window_plan.lead_diagnostics
                        if isinstance(item, Mapping)
                        and item.get("terminal_blocker")
                    ]
                    diagnostics["lead_terminal_blockers"] = lead_blockers
                    terminal_blocker = (
                        lead_blockers[0] if lead_blockers else "planner-blocked"
                    )
                    stat["no_probe_reason"] = terminal_blocker
                    diagnostics["status"] = "blocked"
                    diagnostics["terminal_blocker"] = terminal_blocker
                else:
                    stat["no_probe_reason"] = "planner-returned-no-probes"
                    diagnostics["status"] = "blocked"
                    diagnostics["terminal_blocker"] = "planner-returned-no-probes"

    post_source_owner_family_id = (
        RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_FAMILY_ID
    )
    if _family_can_attempt(family_stats, allowed, post_source_owner_family_id):
        stat = family_stats[post_source_owner_family_id]
        diagnostics = stat["matcher_diagnostics"]
        if window_order_context is None:
            stat["no_probe_reason"] = "missing-select-order-payload"
            diagnostics["status"] = "blocked"
            diagnostics["terminal_blocker"] = "missing-select-order-payload"
        else:
            fallback_leads_raw = window_order_context.get("fallback_leads")
            fallback_leads = (
                list(fallback_leads_raw) if isinstance(fallback_leads_raw, list) else []
            )
            source_attributions = window_order_context.get("source_attributions")
            fallback_lead_targets = {
                target_ig for lead in fallback_leads
                if (target_ig := _window_order_lead_target_ig(lead)) is not None
            }
            diagnostics.update({
                "status": "attempted",
                "payload_path": window_order_context.get("payload_path"),
                "fallback_lead_count": len(fallback_leads),
                "source_attribution_count": (
                    len(source_attributions)
                    if isinstance(source_attributions, Mapping)
                    else 0
                ),
                "force_phys_targets": _force_phys_summary(force_phys),
                "attempted_targets": {
                    str(target_ig): int(force_phys[target_ig])
                    for target_ig in sorted(fallback_lead_targets)
                    if target_ig in force_phys
                },
                "protected_targets": {
                    str(ig): int(phys)
                    for ig, phys in sorted(force_phys.items())
                    if ig not in fallback_lead_targets
                },
                "skipped_current_owner_labels": [],
                "selected_alternate_probe_count": 0,
                "emitted_post_source_owner_probe_count": 0,
            })
            if not fallback_leads:
                stat["no_probe_reason"] = "missing-window-order-fallback-leads"
                diagnostics["status"] = "blocked"
                diagnostics["terminal_blocker"] = (
                    "missing-window-order-fallback-leads"
                )
            else:
                planner_target_count = max(1, len(fallback_lead_targets))
                window_plan = plan_window_order_source_probes(
                    source_text,
                    function=source_function,
                    fallback_leads=fallback_leads,
                    source_attributions=source_attributions,
                    max_probes=max(2, max_per_family + planner_target_count),
                    ranked_indexed_byte_candidates_per_target=max(
                        2,
                        max_per_family + 1,
                    ),
                )
                ranked_window_probes: list[LifetimeLayoutProbe] = []
                filtered_window_probe_reasons: list[dict[str, Any]] = []
                for probe in window_plan.probes:
                    candidate = _window_order_probe_ranked_indexed_candidate(
                        probe,
                    )
                    if candidate is None:
                        continue
                    probe_target_ig = _window_order_probe_target_ig(probe)
                    if probe_target_ig is None:
                        filtered_window_probe_reasons.append({
                            "label": probe.label,
                            "reason": "missing-lead-target-ig",
                        })
                        continue
                    if probe_target_ig not in force_phys:
                        filtered_window_probe_reasons.append({
                            "label": probe.label,
                            "target_ig": probe_target_ig,
                            "reason": "target-not-in-force-phys",
                        })
                        continue
                    ranked_window_probes.append(probe)
                ranked_window_probes.sort(
                    key=lambda probe: (
                        _window_order_probe_target_ig(probe) or 999999,
                        _ranked_indexed_candidate_rank(
                            _window_order_probe_ranked_indexed_candidate(probe)
                        ),
                        probe.label,
                    )
                )
                skipped_current_owner_by_target: dict[int, LifetimeLayoutProbe] = {}
                alternate_probes: list[LifetimeLayoutProbe] = []
                for probe in ranked_window_probes:
                    probe_target_ig = _window_order_probe_target_ig(probe)
                    if probe_target_ig is None:
                        continue
                    skipped_probe = skipped_current_owner_by_target.get(
                        probe_target_ig
                    )
                    if skipped_probe is None:
                        skipped_current_owner_by_target[probe_target_ig] = probe
                        continue
                    alternate_probes.append(
                        _with_post_source_owner_backtrack_metadata(
                            probe,
                            skipped_current_owner_labels=(skipped_probe.label,),
                        )
                    )
                selected_targets = sorted({
                    target_ig for probe in alternate_probes
                    if (target_ig := _window_order_probe_target_ig(probe))
                    is not None
                })
                attempted_targets = {
                    str(target_ig): int(force_phys[target_ig])
                    for target_ig in (
                        selected_targets
                        or sorted(skipped_current_owner_by_target)
                    )
                    if target_ig in force_phys
                }
                protected_targets = {
                    str(ig): int(phys)
                    for ig, phys in sorted(force_phys.items())
                    if str(ig) not in attempted_targets
                }
                skipped_labels = [
                    probe.label
                    for _, probe in sorted(skipped_current_owner_by_target.items())
                ]
                diagnostics.update({
                    "planned_window_order_probe_count": len(window_plan.probes),
                    "ranked_indexed_window_order_probe_count": len(
                        ranked_window_probes
                    ),
                    "filtered_window_order_probe_count": len(
                        filtered_window_probe_reasons
                    ),
                    "filtered_window_order_probe_reasons": (
                        filtered_window_probe_reasons
                    ),
                    "skipped_current_owner_labels": skipped_labels,
                    "skipped_current_owner_targets": sorted(
                        skipped_current_owner_by_target
                    ),
                    "selected_alternate_probe_count": len(alternate_probes),
                    "selected_alternate_targets": selected_targets,
                    "attempted_targets": attempted_targets,
                    "protected_targets": protected_targets,
                    "lead_diagnostics": list(window_plan.lead_diagnostics),
                })
                post_probe_skip_reasons: list[dict[str, Any]] = []
                for window_probe in alternate_probes:
                    anchor = Anchor(
                        mutator_key=(
                            RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_MUTATOR_KEY
                        ),
                        span=(0, len(source_text)),
                        payload={
                            "window_order_label": window_probe.label,
                            "lead_target_ig": _window_order_probe_target_ig(
                                window_probe
                            ),
                            "post_source_owner_backtrack": (
                                (window_probe.provenance or {}).get(
                                    "post_source_owner_backtrack"
                                )
                            ),
                        },
                    )
                    if not _family_candidate_allowed(
                        family_stats,
                        counts,
                        allowed,
                        post_source_owner_family_id,
                        anchor,
                        max_per_family=max_per_family,
                    ):
                        post_probe_skip_reasons.append({
                            "label": window_probe.label,
                            "reason": "probe-budget-starved",
                        })
                        break
                    if window_probe.source_text == source_text:
                        post_probe_skip_reasons.append({
                            "label": window_probe.label,
                            "reason": "post-source-owner-probe-noop",
                        })
                        continue
                    if window_probe.source_text in seen_candidate_texts:
                        post_probe_skip_reasons.append({
                            "label": window_probe.label,
                            "reason": "post-source-owner-probe-deduped",
                        })
                        continue
                    seen_candidate_texts.add(window_probe.source_text)
                    transform_probe = _lifetime_layout_probe_to_transform_probe(
                        window_probe,
                        family_id=post_source_owner_family_id,
                        index=counts.get(post_source_owner_family_id, 0),
                        source_text=source_text,
                        plan=plan,
                        force_phys=force_phys,
                    )
                    counts[post_source_owner_family_id] = (
                        counts.get(post_source_owner_family_id, 0) + 1
                    )
                    probes.append(transform_probe)
                    _note_family_applied(
                        family_stats,
                        post_source_owner_family_id,
                        anchor,
                    )
                    diagnostics["emitted_post_source_owner_probe_count"] = (
                        counts.get(post_source_owner_family_id, 0)
                    )
                if post_probe_skip_reasons:
                    diagnostics["post_source_owner_probe_skip_reasons"] = (
                        post_probe_skip_reasons
                    )
                if counts.get(post_source_owner_family_id, 0):
                    diagnostics["status"] = "materialized"
                elif alternate_probes:
                    stat["no_probe_reason"] = "post-source-owner-exhausted"
                    diagnostics["status"] = "blocked"
                    diagnostics["terminal_blocker"] = (
                        "post-source-owner-exhausted"
                    )
                elif skipped_current_owner_by_target:
                    stat["no_probe_reason"] = "no-alternate-source-owner"
                    diagnostics["status"] = "blocked"
                    diagnostics["terminal_blocker"] = (
                        "no-alternate-source-owner"
                    )
                elif ranked_window_probes:
                    stat["no_probe_reason"] = "post-source-owner-exhausted"
                    diagnostics["status"] = "blocked"
                    diagnostics["terminal_blocker"] = (
                        "post-source-owner-exhausted"
                    )
                elif window_plan.lead_diagnostics:
                    lead_blockers = [
                        str(item.get("terminal_blocker"))
                        for item in window_plan.lead_diagnostics
                        if isinstance(item, Mapping)
                        and item.get("terminal_blocker")
                    ]
                    diagnostics["lead_terminal_blockers"] = lead_blockers
                    terminal_blocker = (
                        lead_blockers[0] if lead_blockers else "planner-blocked"
                    )
                    stat["no_probe_reason"] = terminal_blocker
                    diagnostics["status"] = "blocked"
                    diagnostics["terminal_blocker"] = terminal_blocker
                else:
                    stat["no_probe_reason"] = "planner-returned-no-probes"
                    diagnostics["status"] = "blocked"
                    diagnostics["terminal_blocker"] = "planner-returned-no-probes"

    for target_live_range_family_id in (
        RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID,
        RETAINED_FPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID,
    ):
        if not _family_can_attempt(
            family_stats,
            allowed,
            target_live_range_family_id,
        ):
            continue
        family_repair_goals = _target_live_range_goals_for_family(
            target_live_range_goals,
            target_live_range_family_id,
        )
        stat = family_stats[target_live_range_family_id]
        diagnostics = stat["matcher_diagnostics"]
        source_attributions = (
            window_order_context.get("source_attributions")
            if window_order_context is not None
            else None
        )
        diagnostics.update({
            "status": "attempted",
            "payload_path": (
                window_order_context.get("payload_path")
                if window_order_context is not None
                else None
            ),
            "repair_goal_count": len(family_repair_goals),
            "source_attribution_count": (
                len(source_attributions)
                if isinstance(source_attributions, Mapping)
                else 0
            ),
            "protected_targets": _repair_goals_protected_targets(
                family_repair_goals,
                force_phys=force_phys,
            ),
            "attempted_targets": _repair_goals_attempted_targets(
                family_repair_goals,
                force_phys=force_phys,
            ),
            "emitted_repair_probe_count": 0,
        })
        if not family_repair_goals:
            stat["no_probe_reason"] = "missing-target-live-range-repair-goals"
            diagnostics["status"] = "blocked"
            diagnostics["terminal_blocker"] = (
                "missing-target-live-range-repair-goals"
            )
        else:
            repair_plan = plan_target_aware_live_range_repair_probes(
                source_text,
                function=source_function,
                repair_goals=family_repair_goals,
                source_attributions=source_attributions,
                max_probes=max_per_family,
            )
            selected_repair_probes = [
                probe for probe in repair_plan.probes
                if probe.operator == "target-aware-live-range-repair"
            ]
            diagnostics.update({
                "planned_repair_probe_count": len(repair_plan.probes),
                "target_live_range_repair_probe_count": len(
                    selected_repair_probes
                ),
                "repair_goal_diagnostics": list(repair_plan.lead_diagnostics),
            })
            for repair_probe in selected_repair_probes:
                provenance = (
                    repair_probe.provenance
                    if isinstance(repair_probe.provenance, Mapping)
                    else {}
                )
                anchor = Anchor(
                    mutator_key=_lifetime_probe_mutator_key(
                        target_live_range_family_id
                    ),
                    span=(0, len(source_text)),
                    payload={
                        "window_order_label": repair_probe.label,
                        "lead_target_ig": provenance.get("target_ig"),
                        "interferer_ig": provenance.get("interferer_ig"),
                    },
                )
                if not _family_candidate_allowed(
                    family_stats,
                    counts,
                    allowed,
                    target_live_range_family_id,
                    anchor,
                    max_per_family=max_per_family,
                ):
                    break
                if repair_probe.source_text == source_text:
                    continue
                if repair_probe.source_text in seen_candidate_texts:
                    continue
                seen_candidate_texts.add(repair_probe.source_text)
                transform_probe = _lifetime_layout_probe_to_transform_probe(
                    repair_probe,
                    family_id=target_live_range_family_id,
                    index=counts.get(target_live_range_family_id, 0),
                    source_text=source_text,
                    plan=plan,
                    force_phys=force_phys,
                )
                counts[target_live_range_family_id] = (
                    counts.get(target_live_range_family_id, 0) + 1
                )
                probes.append(transform_probe)
                _note_family_applied(
                    family_stats,
                    target_live_range_family_id,
                    anchor,
                )
                diagnostics["emitted_repair_probe_count"] = counts.get(
                    target_live_range_family_id,
                    0,
                )
            if counts.get(target_live_range_family_id, 0):
                diagnostics["status"] = "materialized"
            elif repair_plan.lead_diagnostics:
                stat["no_probe_reason"] = "planner-blocked"
                diagnostics["status"] = "blocked"
                diagnostics["terminal_blocker"] = "planner-blocked"
            else:
                stat["no_probe_reason"] = "planner-returned-no-probes"
                diagnostics["status"] = "blocked"
                diagnostics["terminal_blocker"] = "planner-returned-no-probes"

    alternate_owner_family_id = RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_FAMILY_ID
    if _family_can_attempt(family_stats, allowed, alternate_owner_family_id):
        stat = family_stats[alternate_owner_family_id]
        diagnostics = stat["matcher_diagnostics"]
        current_owner_spans = []
        if current_owner_exhaustion_context is not None:
            raw_spans = current_owner_exhaustion_context.get(
                "source_owner_terminal_spans"
            )
            if isinstance(raw_spans, list):
                current_owner_spans = [
                    span for span in raw_spans if isinstance(span, Mapping)
                ]
        diagnostics.update({
            "status": "attempted",
            "payload_path": (
                current_owner_exhaustion_context.get("payload_path")
                if current_owner_exhaustion_context is not None
                else None
            ),
            "current_owner_span_count": len(current_owner_spans),
            "emitted_repair_probe_count": 0,
        })
        if current_owner_exhaustion_context is None:
            stat["no_probe_reason"] = "missing-current-owner-exhaustion-json"
            diagnostics["status"] = "blocked"
            diagnostics["terminal_blocker"] = (
                "missing-current-owner-exhaustion-json"
            )
        elif not current_owner_spans:
            stat["no_probe_reason"] = "missing-current-owner-terminal-spans"
            diagnostics["status"] = "blocked"
            diagnostics["terminal_blocker"] = (
                "missing-current-owner-terminal-spans"
            )
        else:
            source_attributions = current_owner_exhaustion_context.get(
                "source_attributions"
            )
            alternate_plan = plan_alternate_source_owner_probes(
                source_text,
                function=source_function,
                current_owner_spans=current_owner_spans,
                source_attributions=(
                    source_attributions
                    if isinstance(source_attributions, Mapping)
                    else None
                ),
                max_probes=max_per_family,
            )
            plan_diagnostic = (
                alternate_plan.lead_diagnostics[0]
                if alternate_plan.lead_diagnostics
                else {}
            )
            diagnostics.update(plan_diagnostic)
            selected_alternate_probes = [
                probe for probe in alternate_plan.probes
                if probe.operator == "target-aware-alternate-source-owner"
            ]
            for alternate_probe in selected_alternate_probes:
                provenance = (
                    alternate_probe.provenance
                    if isinstance(alternate_probe.provenance, Mapping)
                    else {}
                )
                anchor = Anchor(
                    mutator_key=_lifetime_probe_mutator_key(
                        alternate_owner_family_id
                    ),
                    span=(0, len(source_text)),
                    payload={
                        "window_order_label": alternate_probe.label,
                        "lead_target_ig": provenance.get("target_ig"),
                        "interferer_ig": provenance.get("interferer_ig"),
                    },
                )
                if not _family_candidate_allowed(
                    family_stats,
                    counts,
                    allowed,
                    alternate_owner_family_id,
                    anchor,
                    max_per_family=max_per_family,
                ):
                    break
                if alternate_probe.source_text == source_text:
                    continue
                if alternate_probe.source_text in seen_candidate_texts:
                    continue
                seen_candidate_texts.add(alternate_probe.source_text)
                transform_probe = _lifetime_layout_probe_to_transform_probe(
                    alternate_probe,
                    family_id=alternate_owner_family_id,
                    index=counts.get(alternate_owner_family_id, 0),
                    source_text=source_text,
                    plan=plan,
                    force_phys=force_phys,
                )
                counts[alternate_owner_family_id] = (
                    counts.get(alternate_owner_family_id, 0) + 1
                )
                probes.append(transform_probe)
                _note_family_applied(
                    family_stats,
                    alternate_owner_family_id,
                    anchor,
                )
                diagnostics["emitted_repair_probe_count"] = counts.get(
                    alternate_owner_family_id,
                    0,
                )
            if counts.get(alternate_owner_family_id, 0):
                diagnostics["status"] = "materialized"
                diagnostics["materialized_alternate_probe_count"] = counts.get(
                    alternate_owner_family_id,
                    0,
                )
            else:
                terminal = str(
                    diagnostics.get("terminal_blocker")
                    or "next-source-owner-exhausted"
                )
                stat["no_probe_reason"] = terminal
                diagnostics["status"] = "blocked"
                diagnostics["terminal_blocker"] = terminal

    simplify_order_family_id = RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID
    if _family_can_attempt(family_stats, allowed, simplify_order_family_id):
        stat = family_stats[simplify_order_family_id]
        diagnostics = stat["matcher_diagnostics"]
        diagnostics.update({
            "status": "attempted",
            "payload_path": (
                window_order_context.get("payload_path")
                if window_order_context is not None
                else None
            ),
            "simplify_order_goal_count": len(simplify_order_goals),
            "protected_targets": _goal_protected_targets(simplify_order_goals),
            "attempted_targets": _goal_attempted_targets(
                simplify_order_goals,
                force_phys=force_phys,
            ),
            "emitted_simplify_order_probe_count": 0,
        })
        if not simplify_order_goals:
            stat["no_probe_reason"] = "missing-simplify-order-goals"
            diagnostics["status"] = "blocked"
            diagnostics["terminal_blocker"] = "missing-simplify-order-goals"
        else:
            simplify_anchors = iter_retained_case_c_simplify_order_anchors(
                source_text,
                function_span=(function_span.sig_start, function_span.full_end),
                goals=simplify_order_goals,
                force_phys=force_phys,
                max_candidates=max_per_family,
            )
            diagnostics.update(
                retained_case_c_simplify_order_match_diagnostics(
                    body_text,
                    anchors=simplify_anchors,
                    goals=simplify_order_goals,
                )
            )
            for simplify_anchor in simplify_anchors:
                if not _family_candidate_allowed(
                    family_stats,
                    counts,
                    allowed,
                    simplify_order_family_id,
                    simplify_anchor,
                    max_per_family=max_per_family,
                ):
                    break
                replacement_text = simplify_anchor.payload.get("replacement_text")
                span_text = simplify_anchor.payload.get("span_text")
                candidate_text_from_payload = simplify_anchor.payload.get(
                    "candidate_text"
                )
                start, end = simplify_anchor.span
                if (
                    not isinstance(replacement_text, str)
                    or not isinstance(span_text, str)
                    or source_text[start:end] != span_text
                ):
                    continue
                if isinstance(candidate_text_from_payload, str):
                    candidate_text = candidate_text_from_payload
                else:
                    candidate_text = (
                        source_text[:start] + replacement_text + source_text[end:]
                    )
                if candidate_text == source_text:
                    continue
                _note_family_applied(
                    family_stats,
                    simplify_order_family_id,
                    simplify_anchor,
                )
                if append_probe(
                    family_id=simplify_order_family_id,
                    anchor=simplify_anchor,
                    candidate_text=candidate_text,
                ):
                    diagnostics["emitted_simplify_order_probe_count"] = counts.get(
                        simplify_order_family_id,
                        0,
                    )
            if counts.get(simplify_order_family_id, 0):
                diagnostics["status"] = "materialized"
            elif diagnostics.get("rejection_reasons"):
                stat["no_probe_reason"] = diagnostics["rejection_reasons"][0]
                diagnostics["status"] = "blocked"
                diagnostics["terminal_blocker"] = stat["no_probe_reason"]
            else:
                stat["no_probe_reason"] = "planner-returned-no-probes"
                diagnostics["status"] = "blocked"
                diagnostics["terminal_blocker"] = "planner-returned-no-probes"

    if (
        node_set_delta is not None
        and _family_can_attempt(family_stats, allowed, "coloring_register_steering")
    ):
        remaining = max_per_family - counts.get("coloring_register_steering", 0)
        for anchor, candidate_text, target_assignments in (
            _iter_node_set_delta_steering_probes(
                source_text,
                function=source_function,
                node_set_delta=node_set_delta,
                remaining=remaining,
            )
        ):
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                "coloring_register_steering",
                anchor,
                max_per_family=max_per_family,
            ):
                break
            _note_family_applied(
                family_stats,
                "coloring_register_steering",
                anchor,
            )
            append_probe(
                family_id="coloring_register_steering",
                anchor=anchor,
                candidate_text=candidate_text,
                target_assignments_override=target_assignments,
            )
        if not requested_family_ids and parsed_scheduler_target is None:
            return build_report()

    if (
        parsed_scheduler_target is not None
        and _family_can_attempt(family_stats, allowed, "scheduler_order_source_realizer")
    ):
        remaining = max_per_family - counts.get("scheduler_order_source_realizer", 0)
        target_assignments = _scheduler_order_target_assignments(
            parsed_scheduler_target,
        )
        for anchor in iter_scheduler_order_source_anchors(
            source_text,
            function=source_function,
            target=parsed_scheduler_target,
            remaining=remaining,
        ):
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                "scheduler_order_source_realizer",
                anchor,
                max_per_family=max_per_family,
            ):
                break
            candidate_text = apply_mutator(anchor.mutator_key, anchor, source_text)
            if candidate_text is None or candidate_text == source_text:
                continue
            _note_family_applied(
                family_stats,
                "scheduler_order_source_realizer",
                anchor,
            )
            append_probe(
                family_id="scheduler_order_source_realizer",
                anchor=anchor,
                candidate_text=candidate_text,
                target_assignments_override=target_assignments,
            )

    gpr_bool_mask_family_id = "pcode_only_gpr_bool_mask_temp_repair"
    if _family_can_attempt(family_stats, allowed, gpr_bool_mask_family_id):
        gpr_bool_mask_anchors = _iter_pcode_only_gpr_bool_mask_temp_anchors(
            body_text,
            function_header_text=function_header_text,
            source_text=source_text,
        )
        family_stats[gpr_bool_mask_family_id]["matcher_diagnostics"].update(
            _pcode_only_gpr_bool_mask_temp_match_diagnostics(
                body_text,
                anchors=gpr_bool_mask_anchors,
                function_header_text=function_header_text,
                source_text=source_text,
            )
        )
        for local_anchor in gpr_bool_mask_anchors:
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                gpr_bool_mask_family_id,
                local_anchor,
                max_per_family=max_per_family,
            ):
                break
            candidate_body = apply_mutator(
                local_anchor.mutator_key,
                local_anchor,
                body_text,
            )
            if candidate_body is None or candidate_body == body_text:
                continue
            _note_family_applied(
                family_stats,
                gpr_bool_mask_family_id,
                local_anchor,
            )
            start, end = local_anchor.span
            anchor = Anchor(
                mutator_key=local_anchor.mutator_key,
                span=(body_start + start, body_start + end),
                payload=local_anchor.payload,
            )
            append_probe(
                family_id=gpr_bool_mask_family_id,
                anchor=anchor,
                candidate_text=(
                    source_text[:body_start]
                    + candidate_body
                    + source_text[body_end:]
                ),
            )

    global_load_family_id = "pcode_only_gpr_global_load_lifetime_repair"
    if _family_can_attempt(family_stats, allowed, global_load_family_id):
        global_load_anchors = iter_global_load_lifetime_anchors(
            source_text,
            function=source_function,
            force_phys=force_phys,
            max_candidates=max_per_family,
            global_types=global_types,
        )
        family_stats[global_load_family_id]["matcher_diagnostics"].update(
            global_load_lifetime_match_diagnostics(
                source_text,
                function=source_function,
                force_phys=force_phys,
                anchors=global_load_anchors,
                global_types=global_types,
            )
        )
        for anchor in global_load_anchors:
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                global_load_family_id,
                anchor,
                max_per_family=max_per_family,
            ):
                break
            candidate_text = anchor.payload.get("candidate_text")
            if not isinstance(candidate_text, str) or candidate_text == source_text:
                continue
            _note_family_applied(family_stats, global_load_family_id, anchor)
            append_probe(
                family_id=global_load_family_id,
                anchor=anchor,
                candidate_text=candidate_text,
            )

    gpr_family_id = "pcode_only_gpr_address_temp_repair"
    if _family_can_attempt(family_stats, allowed, gpr_family_id):
        gpr_anchors = _iter_pcode_only_gpr_address_temp_anchors(
            body_text,
            function_header_text=function_header_text,
        )
        family_stats[gpr_family_id]["matcher_diagnostics"].update(
            _pcode_only_gpr_address_temp_match_diagnostics(
                body_text,
                anchors=gpr_anchors,
            )
        )
        for local_anchor in gpr_anchors:
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                gpr_family_id,
                local_anchor,
                max_per_family=max_per_family,
            ):
                break
            candidate_body = apply_mutator(
                local_anchor.mutator_key,
                local_anchor,
                body_text,
            )
            if candidate_body is None or candidate_body == body_text:
                continue
            _note_family_applied(family_stats, gpr_family_id, local_anchor)
            start, end = local_anchor.span
            anchor = Anchor(
                mutator_key=local_anchor.mutator_key,
                span=(body_start + start, body_start + end),
                payload=local_anchor.payload,
            )
            append_probe(
                family_id=gpr_family_id,
                anchor=anchor,
                candidate_text=(
                    source_text[:body_start]
                    + candidate_body
                    + source_text[body_end:]
                ),
            )

    gpr_case_c_family_id = "pcode_only_gpr_copy_product_case_c_repair"
    if _family_can_attempt(family_stats, allowed, gpr_case_c_family_id):
        gpr_case_c_anchors = _iter_pcode_only_gpr_copy_product_case_c_anchors(
            body_text,
            function_header_text=function_header_text,
        )
        family_stats[gpr_case_c_family_id]["matcher_diagnostics"].update(
            _pcode_only_gpr_copy_product_case_c_match_diagnostics(
                body_text,
                anchors=gpr_case_c_anchors,
            )
        )
        for local_anchor in gpr_case_c_anchors:
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                gpr_case_c_family_id,
                local_anchor,
                max_per_family=max_per_family,
            ):
                break
            candidate_body = apply_mutator(
                local_anchor.mutator_key,
                local_anchor,
                body_text,
            )
            if candidate_body is None or candidate_body == body_text:
                continue
            _note_family_applied(
                family_stats,
                gpr_case_c_family_id,
                local_anchor,
            )
            start, end = local_anchor.span
            anchor = Anchor(
                mutator_key=local_anchor.mutator_key,
                span=(body_start + start, body_start + end),
                payload=local_anchor.payload,
            )
            append_probe(
                family_id=gpr_case_c_family_id,
                anchor=anchor,
                candidate_text=(
                    source_text[:body_start]
                    + candidate_body
                    + source_text[body_end:]
                ),
            )

    retained_case_c_family_id = "retained_gpr_case_c_sensitivity_search"
    if _family_can_attempt(family_stats, allowed, retained_case_c_family_id):
        retained_case_c_anchors = _iter_retained_gpr_case_c_sensitivity_anchors(
            body_text,
            function_header_text=function_header_text,
        )
        family_stats[retained_case_c_family_id]["matcher_diagnostics"].update(
            _retained_gpr_case_c_sensitivity_match_diagnostics(
                body_text,
                anchors=retained_case_c_anchors,
            )
        )
        for local_anchor in retained_case_c_anchors:
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                retained_case_c_family_id,
                local_anchor,
                max_per_family=max_per_family,
            ):
                break
            candidate_body = apply_mutator(
                local_anchor.mutator_key,
                local_anchor,
                body_text,
            )
            if candidate_body is None or candidate_body == body_text:
                continue
            _note_family_applied(
                family_stats,
                retained_case_c_family_id,
                local_anchor,
            )
            start, end = local_anchor.span
            anchor = Anchor(
                mutator_key=local_anchor.mutator_key,
                span=(body_start + start, body_start + end),
                payload=local_anchor.payload,
            )
            append_probe(
                family_id=retained_case_c_family_id,
                anchor=anchor,
                candidate_text=(
                    source_text[:body_start]
                    + candidate_body
                    + source_text[body_end:]
                ),
            )

    pcode_fsubs_family_id = "pcode_only_fpr_fsubs_cast_owner_repair"
    if _family_can_attempt(family_stats, allowed, pcode_fsubs_family_id):
        pcode_fsubs_anchors = _iter_pcode_only_fpr_fsubs_cast_owner_anchors(
            body_text,
            function_header_text=function_header_text,
        )
        family_stats[pcode_fsubs_family_id]["matcher_diagnostics"].update(
            _basic_pcode_fsubs_cast_owner_diagnostics(
                body_text,
                function_header_text,
                anchor_count=len(pcode_fsubs_anchors),
            )
        )
        for local_anchor in pcode_fsubs_anchors:
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                pcode_fsubs_family_id,
                local_anchor,
                max_per_family=max_per_family,
            ):
                break
            candidate_body = apply_mutator(
                local_anchor.mutator_key,
                local_anchor,
                body_text,
            )
            if candidate_body is None or candidate_body == body_text:
                continue
            _note_family_applied(family_stats, pcode_fsubs_family_id, local_anchor)
            start, end = local_anchor.span
            anchor = Anchor(
                mutator_key=local_anchor.mutator_key,
                span=(body_start + start, body_start + end),
                payload=local_anchor.payload,
            )
            append_probe(
                family_id=pcode_fsubs_family_id,
                anchor=anchor,
                candidate_text=(
                    source_text[:body_start]
                    + candidate_body
                    + source_text[body_end:]
                ),
            )

    pcode_family_id = "pcode_only_fpr_callarg_temp_repair"
    if _family_can_attempt(family_stats, allowed, pcode_family_id):
        pcode_anchors = _iter_pcode_only_fpr_callarg_temp_anchors(
            body_text,
            function_header_text=function_header_text,
        )
        family_stats[pcode_family_id]["matcher_diagnostics"].update(
            _basic_pcode_callarg_diagnostics(
                body_text,
                function_header_text,
                anchor_count=len(pcode_anchors),
            )
        )
        for local_anchor in pcode_anchors:
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                pcode_family_id,
                local_anchor,
                max_per_family=max_per_family,
            ):
                break
            candidate_body = apply_mutator(
                local_anchor.mutator_key,
                local_anchor,
                body_text,
            )
            if candidate_body is None or candidate_body == body_text:
                continue
            _note_family_applied(family_stats, pcode_family_id, local_anchor)
            start, end = local_anchor.span
            anchor = Anchor(
                mutator_key=local_anchor.mutator_key,
                span=(body_start + start, body_start + end),
                payload=local_anchor.payload,
            )
            append_probe(
                family_id=pcode_family_id,
                anchor=anchor,
                candidate_text=(
                    source_text[:body_start]
                    + candidate_body
                    + source_text[body_end:]
                ),
            )

    mixed_family_id = "mixed_pcode_fpr_lifetime_pressure_repair"
    if _family_can_attempt(family_stats, allowed, mixed_family_id):
        mixed_anchors = _iter_mixed_pcode_fpr_lifetime_pressure_anchors(
            body_text,
            function_header_text=function_header_text,
        )
        family_stats[mixed_family_id]["matcher_diagnostics"].update(
            _basic_mixed_pcode_fpr_lifetime_diagnostics(
                body_text,
                function_header_text,
                anchors=mixed_anchors,
            )
        )
        if not mixed_anchors:
            fallback_anchors = _iter_mixed_pcode_expression_repair_fallback_anchors(
                source_text,
                source_function=source_function,
                max_candidates=max_per_family,
            )
            family_stats[mixed_family_id]["matcher_diagnostics"].update({
                "expression_repair_fallback_status": (
                    "generated" if fallback_anchors else "no-supported-row-product-shape"
                ),
                "expression_repair_fallback_candidate_count": len(fallback_anchors),
                "expression_repair_fallback_source": "expression-interferer-repair",
            })
            for source_anchor, candidate_text in fallback_anchors:
                if not _family_candidate_allowed(
                    family_stats,
                    counts,
                    allowed,
                    mixed_family_id,
                    source_anchor,
                    max_per_family=max_per_family,
                ):
                    break
                if append_probe(
                    family_id=mixed_family_id,
                    anchor=source_anchor,
                    candidate_text=candidate_text,
                ):
                    _note_family_applied(
                        family_stats,
                        mixed_family_id,
                        source_anchor,
                    )
        for local_anchor in mixed_anchors:
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                mixed_family_id,
                local_anchor,
                max_per_family=max_per_family,
            ):
                break
            start, end = local_anchor.span
            replacement_text = local_anchor.payload.get("replacement_text")
            span_text = local_anchor.payload.get("span_text")
            if (
                not isinstance(replacement_text, str)
                or not isinstance(span_text, str)
                or body_text[start:end] != span_text
            ):
                continue
            candidate_body = body_text[:start] + replacement_text + body_text[end:]
            if candidate_body == body_text:
                continue
            _note_family_applied(family_stats, mixed_family_id, local_anchor)
            anchor = Anchor(
                mutator_key=local_anchor.mutator_key,
                span=(body_start + start, body_start + end),
                payload=local_anchor.payload,
            )
            append_probe(
                family_id=mixed_family_id,
                anchor=anchor,
                candidate_text=(
                    source_text[:body_start]
                    + candidate_body
                    + source_text[body_end:]
                ),
            )

    callarg_structural_family_id = "callarg_local_structural_repair"
    if _family_can_attempt(family_stats, allowed, callarg_structural_family_id):
        callarg_structural_anchors = _iter_callarg_local_structural_repair_anchors(
            body_text,
            function_header_text=function_header_text,
        )
        family_stats[callarg_structural_family_id]["matcher_diagnostics"].update(
            _basic_callarg_local_structural_diagnostics(
                body_text,
                anchors=callarg_structural_anchors,
                function_header_text=function_header_text,
            )
        )
        for local_anchor in callarg_structural_anchors:
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                callarg_structural_family_id,
                local_anchor,
                max_per_family=max_per_family,
            ):
                break
            candidate_body = apply_mutator(
                local_anchor.mutator_key,
                local_anchor,
                body_text,
            )
            if candidate_body is None or candidate_body == body_text:
                continue
            _note_family_applied(
                family_stats,
                callarg_structural_family_id,
                local_anchor,
            )
            start, end = local_anchor.span
            anchor = Anchor(
                mutator_key=local_anchor.mutator_key,
                span=(body_start + start, body_start + end),
                payload=local_anchor.payload,
            )
            append_probe(
                family_id=callarg_structural_family_id,
                anchor=anchor,
                candidate_text=(
                    source_text[:body_start]
                    + candidate_body
                    + source_text[body_end:]
                ),
            )

    coupled_family_id = "coupled_fpr_coalesce_product_repair"
    if _family_can_attempt(family_stats, allowed, coupled_family_id):
        coupled_anchors = _iter_coupled_fpr_product_callarg_repair_anchors(
            body_text,
            function_header_text=function_header_text,
        )
        family_stats[coupled_family_id]["matcher_diagnostics"].update(
            _basic_coupled_fpr_diagnostics(
                body_text,
                function_header_text,
                anchor_count=len(coupled_anchors),
            )
        )
        for local_anchor in coupled_anchors:
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                coupled_family_id,
                local_anchor,
                max_per_family=max_per_family,
            ):
                break
            candidate_body = apply_mutator(
                local_anchor.mutator_key,
                local_anchor,
                body_text,
            )
            if candidate_body is None or candidate_body == body_text:
                continue
            _note_family_applied(family_stats, coupled_family_id, local_anchor)
            start, end = local_anchor.span
            anchor = Anchor(
                mutator_key=local_anchor.mutator_key,
                span=(body_start + start, body_start + end),
                payload=local_anchor.payload,
            )
            append_probe(
                family_id=coupled_family_id,
                anchor=anchor,
                candidate_text=(
                    source_text[:body_start]
                    + candidate_body
                    + source_text[body_end:]
                ),
            )

    for local_anchor in _iter_concrete_register_steering_body_anchors(
        body_text,
        function_header_text=function_header_text,
    ):
        append_steering_probe_from_body_anchor(local_anchor)
    for local_anchor in iter_source_shape_anchors(body_text):
        if (
            local_anchor.mutator_key == "add_explicit_zero_return"
            and not allow_explicit_zero_return
        ):
            continue
        if not _body_anchor_allowed(local_anchor, source_text, unit):
            continue
        start, end = local_anchor.span
        anchor = Anchor(
            mutator_key=local_anchor.mutator_key,
            span=(body_start + start, body_start + end),
            payload=local_anchor.payload,
        )
        append_steering_probe_from_body_anchor(local_anchor)
        for family_id in _family_ids_for_anchor(anchor):
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                family_id,
                anchor,
                max_per_family=max_per_family,
            ):
                continue
            candidate_body = apply_mutator(
                local_anchor.mutator_key,
                local_anchor,
                body_text,
            )
            if candidate_body is None or candidate_body == body_text:
                continue
            _note_family_applied(family_stats, family_id, anchor)
            candidate_text = (
                source_text[:body_start] + candidate_body + source_text[body_end:]
            )
            append_probe(
                family_id=family_id,
                anchor=anchor,
                candidate_text=candidate_text,
            )
    for local_anchor in _iter_register_steering_body_anchors(body_text):
        append_steering_probe_from_body_anchor(local_anchor)
    for anchor in _iter_full_source_anchors(source_text, function=source_function):
        append_steering_probe_from_source_anchor(anchor)
        for family_id in _family_ids_for_anchor(anchor):
            if not _family_candidate_allowed(
                family_stats,
                counts,
                allowed,
                family_id,
                anchor,
                max_per_family=max_per_family,
            ):
                continue
            candidate_text = apply_mutator(anchor.mutator_key, anchor, source_text)
            if candidate_text is None or candidate_text == source_text:
                continue
            _note_family_applied(family_stats, family_id, anchor)
            append_probe(
                family_id=family_id,
                anchor=anchor,
                candidate_text=candidate_text,
            )
    return build_report()


def generate_transform_probes(
    source_text: str,
    *,
    function: str,
    unit: str,
    force_phys: Mapping[int, int],
    function_aliases: IterableABC[str] | None = None,
    families: IterableABC[str] | None = None,
    max_per_family: int = 3,
    node_set_delta: Mapping[str, Any] | None = None,
    scheduler_order_target: Mapping[str, Any] | SchedulerOrderTarget | str | None = None,
    window_order_continuation: Mapping[str, Any] | None = None,
    coalesce_suggestion: Mapping[str, Any] | None = None,
) -> tuple[TransformProbe, ...]:
    """Instantiate applicable corpus families into source probe candidates."""

    return generate_transform_probe_report(
        source_text,
        function=function,
        unit=unit,
        force_phys=force_phys,
        function_aliases=function_aliases,
        families=families,
        max_per_family=max_per_family,
        node_set_delta=node_set_delta,
        scheduler_order_target=scheduler_order_target,
        window_order_continuation=window_order_continuation,
        coalesce_suggestion=coalesce_suggestion,
    ).probes
