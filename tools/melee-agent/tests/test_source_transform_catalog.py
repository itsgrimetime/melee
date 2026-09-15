from __future__ import annotations

from src.mwcc_debug.control_flow_shape import DEFAULT_CONTROL_FLOW_OPERATORS
from src.mwcc_debug.pressure_explorer import (
    SOURCE_LIFETIME_GENERIC_OPERATORS,
    SOURCE_LIFETIME_TARGETED_OPERATORS,
)
from src.mwcc_debug.simplify_variants import _TYPE_FLIPS
from src.mwcc_debug.source_transform_catalog import (
    DIRECTED_MUTATOR_KEYS,
    LIFETIME_LAYOUT_OPERATORS,
    SOURCE_TRANSFORM_CATALOG,
    STRUCTURE_SEARCH_AXIS_TECHNIQUES,
    catalog_summary,
)
from src.search.cli import (
    _summarize_transform_validations,
    _transform_validation_evidence,
)
from src.search.directed.mutators import _DISPATCH
from src.search.directed.transform_corpus import DEFAULT_TRANSFORM_FAMILIES


NODE_SET_DELTA_MATERIALIZED_PROBE_KEYS = frozenset({
    "steer_node_set_delta_coupled_split",
    "steer_node_set_delta_introduce_binding_split",
    "steer_node_set_delta_split",
    "steer_retained_gpr_case_c_window_order_continuation",
    "steer_retained_gpr_case_c_post_source_owner_backtrack",
    "steer_retained_gpr_case_c_target_live_range_repair",
    "steer_retained_gpr_case_c_simplify_order_continuation",
    "steer_retained_gpr_common_subexpr_coalesce_source",
})


def _entry(surface: str):
    return next(row for row in SOURCE_TRANSFORM_CATALOG if row.surface == surface)


def test_catalog_has_expected_headline_counts() -> None:
    summary = catalog_summary()

    assert summary["surfaces"] == 13
    assert summary["techniques"] == 186
    assert summary["concrete_forms"] == 154


def test_control_flow_catalog_tracks_default_operator_tuple() -> None:
    entry = _entry("debug mutate control-flow-shape-search")

    assert entry.techniques == DEFAULT_CONTROL_FLOW_OPERATORS
    assert entry.technique_count == 12


def test_source_lifetime_structure_axis_tracks_pressure_operator_tuples() -> None:
    expected = {
        f"source-lifetime:{operator}"
        for operator in (
            *SOURCE_LIFETIME_TARGETED_OPERATORS,
            *SOURCE_LIFETIME_GENERIC_OPERATORS,
        )
    }

    assert expected <= set(STRUCTURE_SEARCH_AXIS_TECHNIQUES)
    assert len(expected) == 14


def test_lifetime_layout_catalog_covers_source_lifetime_generic_operators() -> None:
    assert set(SOURCE_LIFETIME_GENERIC_OPERATORS) <= set(LIFETIME_LAYOUT_OPERATORS)
    assert len(LIFETIME_LAYOUT_OPERATORS) == 19


def test_directed_catalog_tracks_dispatch_and_families() -> None:
    entry = _entry("debug search plan-transforms / directed")
    dispatch_keys = set(_DISPATCH)
    materialized_probe_keys = set(NODE_SET_DELTA_MATERIALIZED_PROBE_KEYS)

    assert set(entry.techniques) == {
        family.family_id for family in DEFAULT_TRANSFORM_FAMILIES
    }
    assert {
        "inline_simple_helper_call",
        "extract_repeated_assignment_helper",
        "reuse_same_type_local_lifetime",
        "add_dont_inline_pragma_pair",
        "remove_dont_inline_pragma_pair",
        "replace_float_literal_with_global_constant",
        "replace_global_float_constant_with_literal",
        "reassociate_fp_subtraction_operands",
        "elide_redundant_pointer_cast",
        "elide_callback_cast",
        "rewrite_vector_alias_type",
        "remove_unused_trailing_parameter",
        "add_unused_trailing_parameter",
        "materialize_outgoing_parameter_area_call_args",
        "steer_reorder_local_decls",
        "steer_split_decl_init",
        "steer_reuse_loop_counter_scope",
        "steer_change_counter_width",
        "steer_reuse_same_type_local_lifetime",
        "steer_rotate_local_decl_window",
        "steer_demote_local_decl_to_first_use",
        "steer_reuse_dead_top_level_loop_counter",
        "steer_split_reused_loop_counter",
        "steer_fpr_dependent_product_recompute",
        "steer_fpr_product_temp_split",
        "steer_fpr_paired_product_temp_split",
        "steer_coupled_fpr_product_callarg_repair",
        "steer_pcode_only_fpr_callarg_temp",
        "steer_mixed_pcode_fpr_lifetime_pressure",
        "steer_callarg_local_preserving_structural_repair",
        "steer_pcode_only_fpr_fsubs_cast_owner",
        "steer_pcode_only_gpr_address_temp",
        "steer_pcode_only_gpr_copy_product_case_c",
        "steer_retained_gpr_case_c_sensitivity",
        "steer_retained_gpr_case_c_window_order_continuation",
        "steer_retained_gpr_case_c_post_source_owner_backtrack",
        "steer_retained_gpr_case_c_target_live_range_repair",
        "steer_retained_gpr_case_c_simplify_order_continuation",
            "steer_retained_gpr_common_subexpr_coalesce_source",
            "steer_indexed_byte_index_temp",
            "steer_indexed_byte_base_alias",
            "steer_indexed_byte_helper_result_temp",
            "introduce_named_zero_local",
            "swap_independent_adjacent_statements",
        "rewrite_raw_index_struct_field",
        "rewrite_data_table_indirection",
        "scheduler_anchor_iv_init_before_bias",
        "scheduler_split_float_cast_temp",
        "scheduler_empty_barrier_before_float_cast",
        "unify_ranked_cursor_value_accumulator",
        "reuse_rank_pointer_return_field",
    } <= set(DIRECTED_MUTATOR_KEYS)
    assert set(DIRECTED_MUTATOR_KEYS) == dispatch_keys | materialized_probe_keys
    assert materialized_probe_keys.isdisjoint(dispatch_keys)
    assert set(entry.concrete_forms) == set(DIRECTED_MUTATOR_KEYS)
    assert entry.technique_count == 58
    assert entry.concrete_form_count == 101
    assert "pcode_only_gpr_address_temp_repair" in entry.techniques
    assert "pcode_only_gpr_copy_product_case_c_repair" in entry.techniques
    assert "retained_gpr_case_c_sensitivity_search" in entry.techniques
    assert "retained_gpr_case_c_window_order_continuation" in entry.techniques
    assert "retained_gpr_case_c_post_source_owner_backtrack" in entry.techniques
    assert "retained_gpr_case_c_target_live_range_repair" in entry.techniques
    assert "retained_gpr_case_c_simplify_order_continuation" in entry.techniques
    assert "retained_gpr_common_subexpr_coalesce_source" in entry.techniques
    assert "pcode_only_fpr_callarg_temp_repair" in entry.techniques
    assert "callarg_local_structural_repair" in entry.techniques
    assert "pcode_only_fpr_fsubs_cast_owner_repair" in entry.techniques
    assert "coupled_fpr_coalesce_product_repair" in entry.techniques
    assert "coloring_register_steering" in entry.techniques
    assert "same_type_local_lifetime_reuse" in entry.techniques
    assert "independent_statement_order" in entry.techniques
    assert "data_table_indirection_shape" in entry.techniques
    assert "helper_shape" in entry.techniques
    assert "explicit_zero_return" in entry.techniques
    assert "named_zero_local_shape" in entry.techniques
    assert "raw_index_struct_field_shape" in entry.techniques
    assert "bool_int_accumulator_shape" in entry.techniques
    assert "global_float_literal_shape" in entry.techniques
    assert "fp_subtraction_operand_reassociation" in entry.techniques
    assert "abs_macro_expression_fold" in entry.techniques
    assert "callback_cast_elision" in entry.techniques
    assert "zero_compare_logical_not" in entry.techniques
    assert "function_codegen_pragma_shape" in entry.techniques
    assert "redundant_pointer_cast_elision" in entry.techniques
    assert "unused_trailing_parameter" in entry.techniques
    assert "outgoing_parameter_area_shape" in entry.techniques
    assert "vector_alias_type_shape" in entry.techniques
    assert "minmax_macro_ternary_shape" in entry.techniques
    assert "assert_macro_expansion_shape" in entry.techniques
    assert "assignment_expression_temp_seed" in entry.techniques
    assert "string_literal_data_blob_field_shape" in entry.techniques
    assert "raw_pointer_offset_struct_field_shape" in entry.techniques
    assert "comma_operator_noop_expression_shape" in entry.techniques
    assert "numeric_cast_shape" in entry.techniques
    assert "void_to_value_return_shape" in entry.techniques
    assert "global_pointer_alias_shape" in entry.techniques
    assert "empty_do_while_barrier" in entry.techniques
    assert "scheduler_order_source_realizer" in entry.techniques
    assert "switch_case_order_default_shape" in entry.techniques
    assert "ranked_cursor_iv_unification" in entry.techniques
    assert {
        "debug search directed",
        "debug search run --directed-force-phys",
        "debug mutate lifetime-layout --include-transform-corpus",
        "debug coalesce-search --include-transform-corpus",
        "debug select-order-search --include-transform-corpus",
        "debug mutate frame-transform-search --include-transform-corpus",
    } <= set(entry.reused_by)


def test_transform_validation_evidence_preserves_target_score_and_guard() -> None:
    probe = {
        "probe_id": "coupled_fpr_coalesce_product_repair@0",
        "family_id": "coupled_fpr_coalesce_product_repair",
        "family_label": "coupled FPR coalesce/product repair",
        "semantic_risk": "medium",
        "source_region": "column product/conversion",
        "target_assignments": ["ig32->r28", "ig33->r26", "ig46->r26"],
        "expected_compiler_effect": "joint FPR repair",
    }
    validator_payload = {
        "target_score": {
            "matched": 4,
            "virtual_distance": 2,
            "virtuals": {
                "32": {"target": 28, "actual": 28, "matched": True},
                "33": {"target": 26, "actual": 30, "matched": False},
            },
        },
        "expression_score": {
            "matched": 3,
            "virtual_distance": 3,
            "false_positive_virtual_id_hit_count": 1,
        },
        "structural_guard": {"accepted": True, "frame_delta": 0},
        "structural_guard_error": "guard stderr was empty",
    }
    result = {
        "probe_id": probe["probe_id"],
        "family_id": probe["family_id"],
        "outcome": "negative-evidence",
        "match_percent": 87.5,
        "target_assignment_movement": None,
        "recommendation": None,
        "source_regions": None,
        "uncovered_transform_classes": None,
        "validator_payload": validator_payload,
    }

    evidence = _transform_validation_evidence(probe, result)

    assert evidence["target_score"]["virtuals"] == (
        validator_payload["target_score"]["virtuals"]
    )
    assert evidence["expression_score"] == validator_payload["expression_score"]
    assert evidence["structural_guard"] == {"accepted": True, "frame_delta": 0}
    assert evidence["structural_guard_error"] == "guard stderr was empty"


def test_transform_validation_summary_ranks_guarded_partials() -> None:
    probes = [
        {"probe_id": "coupled_fpr_coalesce_product_repair@0"},
        {"probe_id": "coupled_fpr_coalesce_product_repair@1"},
    ]
    accepted_partial = {
        "probe_id": "coupled_fpr_coalesce_product_repair@0",
        "family_id": "coupled_fpr_coalesce_product_repair",
        "outcome": "negative-evidence",
        "target_score": {"matched": 4, "virtual_distance": 2},
        "expression_score": {"matched": 4, "virtual_distance": 2},
        "structural_guard": {"accepted": True, "frame_delta": 0},
    }
    misleading_raw_virtual_hit = {
        "probe_id": "coupled_fpr_coalesce_product_repair@2",
        "family_id": "coupled_fpr_coalesce_product_repair",
        "outcome": "negative-evidence",
        "target_score": {"matched": 5, "virtual_distance": 1},
        "expression_score": {"matched": 3, "virtual_distance": 3},
        "structural_guard": {"accepted": True, "frame_delta": 0},
    }
    rejected_higher_match = {
        "probe_id": "coupled_fpr_coalesce_product_repair@1",
        "family_id": "coupled_fpr_coalesce_product_repair",
        "outcome": "negative-evidence",
        "target_score": {"matched": 5, "virtual_distance": 1},
        "structural_guard": {"accepted": False, "frame_delta": 0},
    }
    for result in (accepted_partial, misleading_raw_virtual_hit, rejected_higher_match):
        result["evidence"] = {
            "probe_id": result["probe_id"],
            "family_id": result["family_id"],
            "outcome": result["outcome"],
            "target_score": result["target_score"],
            "expression_score": result.get("expression_score"),
            "structural_guard": result["structural_guard"],
        }

    summary = _summarize_transform_validations(
        probes,
        [rejected_higher_match, misleading_raw_virtual_hit, accepted_partial],
    )

    assert summary["ranked_guarded_partials"][0]["probe_id"] == (
        "coupled_fpr_coalesce_product_repair@0"
    )
    assert summary["terminal_blockers"] == [
        "exhausted-coupled-fpr-coalesce-product-repair",
        "structural-guard-rejected",
    ]


def test_transform_validation_summary_reports_pcode_callarg_terminal_blocker() -> None:
    probes = [
        {"probe_id": "pcode_only_fpr_callarg_temp_repair@0"},
    ]
    result = {
        "probe_id": "pcode_only_fpr_callarg_temp_repair@0",
        "family_id": "pcode_only_fpr_callarg_temp_repair",
        "outcome": "negative-evidence",
        "validator_payload": {
            "expression_score": {"matched": 4, "virtual_distance": 2},
            "structural_guard": {"accepted": False, "frame_delta": 8},
        },
        "evidence": {
            "probe_id": "pcode_only_fpr_callarg_temp_repair@0",
            "family_id": "pcode_only_fpr_callarg_temp_repair",
            "outcome": "negative-evidence",
            "expression_score": {"matched": 4, "virtual_distance": 2},
            "structural_guard": {"accepted": False, "frame_delta": 8},
        },
    }

    summary = _summarize_transform_validations(probes, [result])

    assert "exhausted-pcode-only-fpr-callarg-temp-repair" in (
        summary["terminal_blockers"]
    )
    assert "structural-guard-rejected" in summary["terminal_blockers"]


def test_transform_validation_summary_reports_callarg_local_structural_blocker() -> None:
    probes = [
        {"probe_id": "callarg_local_structural_repair@0"},
        {"probe_id": "callarg_local_structural_repair@1"},
    ]
    preserved_but_structural_ceiling = {
        "probe_id": "callarg_local_structural_repair@0",
        "family_id": "callarg_local_structural_repair",
        "outcome": "negative-evidence",
        "validator_payload": {
            "expression_score": {"matched": 6, "targeted": 6},
            "structural_guard": {
                "accepted": False,
                "normalized_diff_lines": 32,
            },
        },
        "evidence": {
            "probe_id": "callarg_local_structural_repair@0",
            "family_id": "callarg_local_structural_repair",
            "outcome": "negative-evidence",
            "expression_score": {"matched": 6, "targeted": 6},
            "structural_guard": {
                "accepted": False,
                "normalized_diff_lines": 32,
            },
        },
    }
    structural_but_anchor_regressed = {
        "probe_id": "callarg_local_structural_repair@1",
        "family_id": "callarg_local_structural_repair",
        "outcome": "negative-evidence",
        "validator_payload": {
            "expression_score": {"matched": 4, "targeted": 6},
            "structural_guard": {
                "accepted": True,
                "normalized_diff_lines": 18,
            },
        },
        "evidence": {
            "probe_id": "callarg_local_structural_repair@1",
            "family_id": "callarg_local_structural_repair",
            "outcome": "negative-evidence",
            "expression_score": {"matched": 4, "targeted": 6},
            "structural_guard": {
                "accepted": True,
                "normalized_diff_lines": 18,
            },
        },
    }

    summary = _summarize_transform_validations(
        probes,
        [preserved_but_structural_ceiling, structural_but_anchor_regressed],
    )

    assert "exhausted-callarg-local-structural-repair" in (
        summary["terminal_blockers"]
    )
    assert "structural-guard-rejected" in summary["terminal_blockers"]


def _callarg_local_validation_case(
    probe_id: str,
    *,
    strategy: str,
    target_matched: int = 5,
    expression_matched: int = 6,
    expression_targeted: int = 6,
    false_positive_virtual_id_hit_count: int = 0,
    normalized_diff_lines: int = 30,
    opcode_similarity: float = 0.81,
    classification_primary: str = "inline-boundary-opcode-drift",
    line_delta: int = 3,
    hunk_count: int = 2,
) -> tuple[dict, dict]:
    probe = {
        "probe_id": probe_id,
        "family_id": "callarg_local_structural_repair",
        "payload": {"strategy": strategy},
    }
    result = {
        "probe_id": probe_id,
        "family_id": "callarg_local_structural_repair",
        "outcome": "negative-evidence",
        "validator_payload": {
            "target_score": {
                "matched": target_matched,
                "targeted": 6,
                "virtual_distance": 6 - target_matched,
            },
            "expression_score": {
                "matched": expression_matched,
                "targeted": expression_targeted,
                "virtual_distance": expression_targeted - expression_matched,
                "false_positive_virtual_id_hit_count": (
                    false_positive_virtual_id_hit_count
                ),
            },
            "structural_guard": {
                "accepted": False,
                "classification_primary": classification_primary,
                "normalized_diff_lines": normalized_diff_lines,
                "opcode_similarity": opcode_similarity,
                "line_delta": line_delta,
                "hunk_count": hunk_count,
            },
        },
    }
    result["evidence"] = _transform_validation_evidence(probe, result)
    return probe, result


def test_callarg_local_summary_reports_sub30_success() -> None:
    probe, result = _callarg_local_validation_case(
        "callarg_local_structural_repair@0",
        strategy="fresh-local-call-schedule-after-add",
        normalized_diff_lines=28,
    )

    summary = _summarize_transform_validations([probe], [result])
    frontier = summary["callarg_local_frontier_summary"]

    assert frontier["threshold_normalized_diff_lines"] == 30
    assert frontier["stop_condition_met"] is True
    assert frontier["best_expression_preserving"]["probe_id"] == probe["probe_id"]
    assert frontier["best_expression_preserving"]["strategy"] == (
        "fresh-local-call-schedule-after-add"
    )
    assert "structural-ceiling-with-protected-anchors" not in (
        frontier["terminal_blockers"]
    )
    assert "terminal_blockers" not in summary


def test_callarg_local_summary_reports_structural_ceiling() -> None:
    preserving_probe, preserving = _callarg_local_validation_case(
        "callarg_local_structural_repair@0",
        strategy="continue-existing-fresh-callarg-local",
        normalized_diff_lines=30,
        opcode_similarity=0.809,
        line_delta=5,
        hunk_count=3,
    )
    structural_probe, structural = _callarg_local_validation_case(
        "callarg_local_structural_repair@1",
        strategy="fresh-local-call-schedule-after-add",
        expression_matched=4,
        false_positive_virtual_id_hit_count=1,
        normalized_diff_lines=18,
        opcode_similarity=0.86,
    )

    summary = _summarize_transform_validations(
        [preserving_probe, structural_probe],
        [preserving, structural],
    )
    frontier = summary["callarg_local_frontier_summary"]

    assert frontier["stop_condition_met"] is False
    assert frontier["best_expression_preserving"]["probe_id"] == (
        preserving_probe["probe_id"]
    )
    assert frontier["best_structural"]["probe_id"] == structural_probe["probe_id"]
    assert {
        "structural-ceiling-with-protected-anchors",
        "sub30-candidates-lost-protected-anchors",
        "inline-boundary-opcode-drift",
    } <= set(frontier["terminal_blockers"])
    assert frontier["inline_boundary_opcode_drift"] == {
        "classification_primary": "inline-boundary-opcode-drift",
        "normalized_diff_lines": 30,
        "opcode_similarity": 0.809,
        "line_delta": 5,
        "hunk_count": 3,
    }


def test_callarg_local_summary_reports_raw_target_false_progress() -> None:
    probe, result = _callarg_local_validation_case(
        "callarg_local_structural_repair@0",
        strategy="fresh-local-call-schedule-after-add",
        expression_matched=4,
        false_positive_virtual_id_hit_count=1,
        normalized_diff_lines=18,
    )

    summary = _summarize_transform_validations([probe], [result])
    frontier = summary["callarg_local_frontier_summary"]

    assert frontier["raw_target_false_progress"][0]["probe_id"] == probe["probe_id"]
    assert frontier["raw_target_false_progress"][0]["strategy"] == (
        "fresh-local-call-schedule-after-add"
    )
    assert "raw-target-progress-expression-regressed" in (
        frontier["terminal_blockers"]
    )


def test_callarg_local_summary_ranks_expression_before_raw_target() -> None:
    raw_probe, raw_false_progress = _callarg_local_validation_case(
        "callarg_local_structural_repair@0",
        strategy="fresh-local-call-schedule-after-add",
        expression_matched=4,
        false_positive_virtual_id_hit_count=1,
        normalized_diff_lines=18,
        opcode_similarity=0.9,
    )
    preserving_probe, preserving = _callarg_local_validation_case(
        "callarg_local_structural_repair@1",
        strategy="continue-existing-fresh-callarg-local",
        expression_matched=6,
        false_positive_virtual_id_hit_count=0,
        normalized_diff_lines=30,
        opcode_similarity=0.81,
    )

    summary = _summarize_transform_validations(
        [raw_probe, preserving_probe],
        [raw_false_progress, preserving],
    )
    frontier = summary["callarg_local_frontier_summary"]

    assert frontier["best_expression_preserving"]["probe_id"] == (
        preserving_probe["probe_id"]
    )
    assert frontier["best_structural"]["probe_id"] == raw_probe["probe_id"]
    assert frontier["best_expression_preserving"]["probe_id"] != (
        frontier["best_structural"]["probe_id"]
    )


def test_transform_validation_summary_ranks_callarg_local_expression_preserving_progress() -> None:
    probes = [
        {
            "probe_id": "callarg_local_structural_repair@0",
            "family_id": "callarg_local_structural_repair",
        },
        {
            "probe_id": "callarg_local_structural_repair@1",
            "family_id": "callarg_local_structural_repair",
        },
    ]
    raw_false_progress = {
        "probe_id": "callarg_local_structural_repair@0",
        "family_id": "callarg_local_structural_repair",
        "outcome": "negative-evidence",
        "match_percent": 88.0,
        "target_assignment_movement": None,
        "recommendation": None,
        "source_regions": None,
        "uncovered_transform_classes": None,
        "validator_payload": {
            "target_score": {"matched": 5, "targeted": 6, "virtual_distance": 1},
            "expression_score": {
                "matched": 4,
                "targeted": 6,
                "virtual_distance": 2,
                "false_positive_virtual_id_hit_count": 1,
            },
        },
    }
    retained_fresh_local = {
        "probe_id": "callarg_local_structural_repair@1",
        "family_id": "callarg_local_structural_repair",
        "outcome": "negative-evidence",
        "match_percent": 88.0,
        "target_assignment_movement": None,
        "recommendation": None,
        "source_regions": None,
        "uncovered_transform_classes": None,
        "validator_payload": {
            "target_score": {"matched": 5, "targeted": 6, "virtual_distance": 1},
            "expression_score": {
                "matched": 6,
                "targeted": 6,
                "virtual_distance": 0,
                "false_positive_virtual_id_hit_count": 0,
            },
        },
    }
    for probe, result in zip(probes, (raw_false_progress, retained_fresh_local)):
        result["evidence"] = _transform_validation_evidence(probe, result)

    summary = _summarize_transform_validations(
        probes,
        [raw_false_progress, retained_fresh_local],
    )

    ranked = summary["ranked_guarded_partials"]
    assert ranked[0]["probe_id"] == "callarg_local_structural_repair@1"
    assert ranked[0]["false_positive_virtual_id_hit_count"] == 0
    assert ranked[1]["probe_id"] == "callarg_local_structural_repair@0"
    assert ranked[1]["false_positive_virtual_id_hit_count"] == 1
    assert "raw-target-progress-expression-regressed" not in (
        summary["terminal_blockers"]
    )


def test_transform_validation_summary_reports_callarg_local_raw_false_progress() -> None:
    probes = [
        {
            "probe_id": "callarg_local_structural_repair@0",
            "family_id": "callarg_local_structural_repair",
        },
        {
            "probe_id": "callarg_local_structural_repair@1",
            "family_id": "callarg_local_structural_repair",
        },
    ]
    raw_regressed = {
        "probe_id": "callarg_local_structural_repair@0",
        "family_id": "callarg_local_structural_repair",
        "outcome": "negative-evidence",
        "validator_payload": {
            "target_score": {"matched": 5, "targeted": 6, "virtual_distance": 1},
            "expression_score": {
                "matched": 4,
                "targeted": 6,
                "false_positive_virtual_id_hit_count": 0,
            },
        },
    }
    raw_false_positive = {
        "probe_id": "callarg_local_structural_repair@1",
        "family_id": "callarg_local_structural_repair",
        "outcome": "negative-evidence",
        "validator_payload": {
            "target_score": {"matched": 5, "targeted": 6, "virtual_distance": 1},
            "expression_score": {
                "matched": 6,
                "targeted": 6,
                "false_positive_virtual_id_hit_count": 1,
            },
        },
    }
    for probe, result in zip(probes, (raw_regressed, raw_false_positive)):
        result["evidence"] = _transform_validation_evidence(probe, result)

    summary = _summarize_transform_validations(
        probes,
        [raw_regressed, raw_false_positive],
    )

    assert "raw-target-progress-expression-regressed" in (
        summary["terminal_blockers"]
    )


def test_plan_transforms_catalog_documents_node_set_delta_materialized_probes() -> None:
    entry = _entry("debug search plan-transforms / directed")

    assert NODE_SET_DELTA_MATERIALIZED_PROBE_KEYS <= set(entry.concrete_forms)
    assert any(
        "node_set_delta" in note
        and "materialized" in note
        and "CandidatePatch" in note
        and "apply_mutator" in note
        for note in entry.notes
    )


def test_simplify_order_catalog_tracks_type_flip_budget() -> None:
    entry = _entry("debug mutate simplify-order")

    assert "type-change-source" in entry.techniques
    assert len(_TYPE_FLIPS) == 8
    assert any("eight signedness flip pairs" in form for form in entry.concrete_forms)
