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
from src.search.directed.mutators import _DISPATCH
from src.search.directed.transform_corpus import DEFAULT_TRANSFORM_FAMILIES


NODE_SET_DELTA_MATERIALIZED_PROBE_KEYS = frozenset({
    "steer_node_set_delta_coupled_split",
    "steer_node_set_delta_introduce_binding_split",
    "steer_node_set_delta_split",
})


def _entry(surface: str):
    return next(row for row in SOURCE_TRANSFORM_CATALOG if row.surface == surface)


def test_catalog_has_expected_headline_counts() -> None:
    summary = catalog_summary()

    assert summary["surfaces"] == 13
    assert summary["techniques"] == 169
    assert summary["concrete_forms"] == 120


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
    assert entry.technique_count == 41
    assert entry.concrete_form_count == 67
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
