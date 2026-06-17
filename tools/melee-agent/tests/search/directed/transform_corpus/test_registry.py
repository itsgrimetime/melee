"""Tests for the transform-family registry and planner (transform_corpus.registry)."""
from __future__ import annotations

import pytest

from src.search.directed.anchors import Anchor
from src.search.directed.mutators import apply_mutator
from src.search.directed.transform_corpus import (
    DEFAULT_TRANSFORM_FAMILIES,
    generate_transform_probes,
    plan_transform_experiments,
)
from src.search.directed.transform_probe_adapter import transform_probe_key
from src.mwcc_debug.source_shape import CandidatePatch


def test_default_corpus_names_required_transform_families() -> None:
    family_ids = {family.family_id for family in DEFAULT_TRANSFORM_FAMILIES}

    assert "condition_split_merge" in family_ids
    assert "declaration_use_boundary" in family_ids
    assert "loop_index_pointer_walk_split" in family_ids
    assert "reload_branch_scope" in family_ids
    assert "lifetime_preserve_shorten" in family_ids
    assert "same_type_local_lifetime_reuse" in family_ids
    assert "independent_statement_order" in family_ids
    assert "data_table_indirection_shape" in family_ids
    assert "explicit_zero_return" in family_ids
    assert "raw_index_struct_field_shape" in family_ids
    assert "bool_int_accumulator_shape" in family_ids
    assert "global_float_literal_shape" in family_ids
    assert "abs_macro_expression_fold" in family_ids
    assert "callback_cast_elision" in family_ids
    assert "zero_compare_logical_not" in family_ids
    assert "indexed_byte_address_temp_steering" in family_ids
    assert "function_codegen_pragma_shape" in family_ids
    assert "redundant_pointer_cast_elision" in family_ids
    assert "unused_trailing_parameter" in family_ids
    assert "outgoing_parameter_area_shape" in family_ids
    assert "vector_alias_type_shape" in family_ids
    assert "minmax_macro_ternary_shape" in family_ids
    assert "fp_subtraction_operand_reassociation" in family_ids
    assert "named_zero_local_shape" in family_ids
    assert "ranked_cursor_iv_unification" in family_ids
    assert all(family.semantic_risk for family in DEFAULT_TRANSFORM_FAMILIES)
    assert all(family.expected_compiler_effect for family in DEFAULT_TRANSFORM_FAMILIES)


def test_helper_shape_metadata_is_executable() -> None:
    by_id = {family.family_id: family for family in DEFAULT_TRANSFORM_FAMILIES}

    helper = by_id["helper_shape"]

    assert helper.mutator_keys == (
        "inline_simple_helper_call",
        "extract_repeated_assignment_helper",
    )
    assert "record-only" not in helper.generated_probe_form


def test_same_type_local_lifetime_reuse_metadata_is_executable() -> None:
    family = next(
        family
        for family in DEFAULT_TRANSFORM_FAMILIES
        if family.family_id == "same_type_local_lifetime_reuse"
    )

    assert family.mutator_keys == ("reuse_same_type_local_lifetime",)
    assert family.semantic_risk == "medium"
    assert "same-type local declarations" in family.source_region_selector
    assert "reduce local count" in family.expected_compiler_effect
    assert "record-only" not in family.generated_probe_form
    assert {"same-type", "lifetime", "reuse", "cur", "prev"} <= set(family.keywords)


def test_coloring_register_steering_metadata_is_executable() -> None:
    family = next(
        family
        for family in DEFAULT_TRANSFORM_FAMILIES
        if family.family_id == "coloring_register_steering"
    )

    assert family.mutator_keys == (
        "steer_reorder_local_decls",
        "steer_split_decl_init",
        "steer_reuse_loop_counter_scope",
        "steer_change_counter_width",
        "steer_reuse_same_type_local_lifetime",
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
        "steer_node_set_delta_coupled_split",
        "steer_node_set_delta_introduce_binding_split",
        "steer_node_set_delta_split",
    )
    assert family.semantic_risk == "medium"
    assert "declaration order" in family.source_region_selector
    assert "register-coloring" in family.expected_compiler_effect
    assert "record-only" not in family.generated_probe_form
    assert {"coloring", "register", "force-phys"} <= set(family.keywords)


def test_indexed_byte_address_temp_metadata_is_executable() -> None:
    family = next(
        family
        for family in DEFAULT_TRANSFORM_FAMILIES
        if family.family_id == "indexed_byte_address_temp_steering"
    )

    assert family.mutator_keys == (
        "steer_indexed_byte_same_line_expr",
        "steer_indexed_byte_value_temp",
        "steer_indexed_byte_index_temp",
        "steer_indexed_byte_base_alias",
    )
    assert family.semantic_risk == "medium"
    assert "non-struct byte-array" in family.source_region_selector
    assert "implicit base+index address temps" in family.expected_compiler_effect
    assert "record-only" not in family.generated_probe_form


def test_independent_statement_order_metadata_is_executable() -> None:
    family = next(
        family
        for family in DEFAULT_TRANSFORM_FAMILIES
        if family.family_id == "independent_statement_order"
    )

    assert family.mutator_keys == ("swap_independent_adjacent_statements",)
    assert family.semantic_risk == "medium"
    assert "adjacent independent statements" in family.source_region_selector
    assert "store ordering" in family.expected_compiler_effect
    assert "record-only" not in family.generated_probe_form
    assert {"statement", "order", "store", "independent"} <= set(family.keywords)


def test_data_table_indirection_shape_metadata_is_executable() -> None:
    family = next(
        family
        for family in DEFAULT_TRANSFORM_FAMILIES
        if family.family_id == "data_table_indirection_shape"
    )

    assert family.mutator_keys == ("rewrite_data_table_indirection",)
    assert family.semantic_risk == "high"
    assert "table expressions" in family.source_region_selector
    assert "outer data-table indirection" in family.expected_compiler_effect
    assert "record-only" not in family.generated_probe_form
    assert {"data", "table", "indirection", "index"} <= set(family.keywords)


def test_raw_index_struct_field_shape_metadata_is_executable() -> None:
    by_id = {family.family_id: family for family in DEFAULT_TRANSFORM_FAMILIES}

    raw_index = by_id["raw_index_struct_field_shape"]
    assert raw_index.mutator_keys == ("rewrite_raw_index_struct_field",)
    assert raw_index.semantic_risk == "high"
    assert "recovered struct field map" in raw_index.source_region_selector
    assert "typed struct field accesses" in raw_index.expected_compiler_effect
    assert "record-only" not in raw_index.generated_probe_form


def test_second_wave_harvested_families_are_record_only_with_guards() -> None:
    by_id = {family.family_id: family for family in DEFAULT_TRANSFORM_FAMILIES}

    explicit = by_id["explicit_zero_return"]
    assert explicit.mutator_keys == ("add_explicit_zero_return",)
    assert explicit.semantic_risk == "medium"
    assert "non-void side-effect wrappers" in explicit.source_region_selector
    assert "zero return value" in explicit.expected_compiler_effect

    accumulator = by_id["bool_int_accumulator_shape"]
    assert accumulator.mutator_keys == ("rewrite_bool_accumulator_as_int",)
    assert accumulator.semantic_risk == "medium"
    assert "OR-assigned" in accumulator.source_region_selector
    assert "integer-width predicate accumulation" in accumulator.expected_compiler_effect
    assert "record-only" not in accumulator.generated_probe_form


def test_third_wave_harvested_families_are_record_only_with_guards() -> None:
    by_id = {family.family_id: family for family in DEFAULT_TRANSFORM_FAMILIES}

    global_float = by_id["global_float_literal_shape"]
    assert global_float.mutator_keys == (
        "replace_float_literal_with_global_constant",
        "replace_global_float_constant_with_literal",
    )
    assert global_float.semantic_risk == "high"
    assert "floating-point literals" in global_float.source_region_selector
    assert "constant materialization" in global_float.expected_compiler_effect
    assert "record-only" not in global_float.generated_probe_form

    fp_subtract = by_id["fp_subtraction_operand_reassociation"]
    assert fp_subtract.mutator_keys == ("reassociate_fp_subtraction_operands",)
    assert fp_subtract.semantic_risk == "low"
    assert "true FP subtraction expressions" in fp_subtract.source_region_selector
    assert "-X - C" in fp_subtract.generated_probe_form
    assert "record-only" not in fp_subtract.generated_probe_form

    named_zero = by_id["named_zero_local_shape"]
    assert named_zero.mutator_keys == ("introduce_named_zero_local",)
    assert named_zero.semantic_risk == "medium"
    assert "NULL sentinel" in named_zero.source_region_selector
    assert "zero-CSE" in named_zero.expected_compiler_effect
    assert "record-only" not in named_zero.generated_probe_form

    abs_fold = by_id["abs_macro_expression_fold"]
    assert abs_fold.mutator_keys == ("rewrite_abs_ternary_to_macro",)
    assert abs_fold.semantic_risk == "medium"
    assert "absolute-value spelling" in abs_fold.source_region_selector
    assert "inline compare/negate shape" in abs_fold.expected_compiler_effect
    assert "record-only" not in abs_fold.generated_probe_form

    callback_cast = by_id["callback_cast_elision"]
    assert callback_cast.mutator_keys == ("elide_callback_cast",)
    assert callback_cast.semantic_risk == "medium"
    assert "callback or function-pointer casts" in callback_cast.source_region_selector
    assert "call target type materialization" in callback_cast.expected_compiler_effect
    assert "record-only" not in callback_cast.generated_probe_form

    zero_compare = by_id["zero_compare_logical_not"]
    assert zero_compare.mutator_keys == ("rewrite_zero_compare_logical_not",)
    assert zero_compare.semantic_risk == "low"
    assert "zero comparisons" in zero_compare.source_region_selector
    assert "predicate spelling" in zero_compare.expected_compiler_effect
    assert "record-only" not in zero_compare.generated_probe_form


def test_repeated_later_harvested_families_are_record_only_with_guards() -> None:
    by_id = {family.family_id: family for family in DEFAULT_TRANSFORM_FAMILIES}

    pragma = by_id["function_codegen_pragma_shape"]
    assert pragma.mutator_keys == (
        "add_dont_inline_pragma_pair",
        "remove_dont_inline_pragma_pair",
    )
    assert pragma.semantic_risk == "high"
    assert "function-local codegen pragmas" in pragma.source_region_selector
    assert "inlining/codegen contract" in pragma.expected_compiler_effect
    assert "record-only" not in pragma.generated_probe_form

    pointer_cast = by_id["redundant_pointer_cast_elision"]
    assert pointer_cast.mutator_keys == ("elide_redundant_pointer_cast",)
    assert pointer_cast.semantic_risk == "medium"
    assert "non-callback pointer casts" in pointer_cast.source_region_selector
    assert "argument materialization" in pointer_cast.expected_compiler_effect
    assert "record-only" not in pointer_cast.generated_probe_form

    unused_param = by_id["unused_trailing_parameter"]
    assert unused_param.mutator_keys == (
        "remove_unused_trailing_parameter",
        "add_unused_trailing_parameter",
    )
    assert unused_param.semantic_risk == "high"
    assert "unused trailing function parameters" in unused_param.source_region_selector
    assert "call contract" in unused_param.expected_compiler_effect
    assert "record-only" not in unused_param.generated_probe_form

    param_area = by_id["outgoing_parameter_area_shape"]
    assert param_area.mutator_keys == (
        "materialize_outgoing_parameter_area_call_args",
    )
    assert param_area.semantic_risk == "medium"
    assert "high-arity call sites" in param_area.source_region_selector
    assert "outgoing parameter area" in param_area.expected_compiler_effect
    assert "record-only" not in param_area.generated_probe_form


def test_repeated_type_and_expression_families_are_record_only_with_guards() -> None:
    by_id = {family.family_id: family for family in DEFAULT_TRANSFORM_FAMILIES}

    vector_alias = by_id["vector_alias_type_shape"]
    assert vector_alias.mutator_keys == ("rewrite_vector_alias_type",)
    assert vector_alias.semantic_risk == "medium"
    assert "equivalent vector/point alias types" in vector_alias.source_region_selector
    assert "API/prototype type shape" in vector_alias.expected_compiler_effect
    assert "record-only" not in vector_alias.generated_probe_form

    minmax = by_id["minmax_macro_ternary_shape"]
    assert minmax.mutator_keys == ("rewrite_minmax_macro_to_ternary",)
    assert minmax.semantic_risk == "medium"
    assert "MIN/MAX-style macro calls" in minmax.source_region_selector
    assert "conditional expression materialization" in minmax.expected_compiler_effect
    assert "record-only" not in minmax.generated_probe_form


def test_mined_transform_families_have_concrete_mutators() -> None:
    by_id = {family.family_id: family for family in DEFAULT_TRANSFORM_FAMILIES}
    expected = {
        "assert_macro_expansion_shape": "collapse_hsd_assert",
        "assignment_expression_temp_seed": "fold_assignment_expression_seed",
        "string_literal_data_blob_field_shape": "replace_string_literal_with_data_field",
        "raw_pointer_offset_struct_field_shape": "rewrite_raw_pointer_offset_field",
        "comma_operator_noop_expression_shape": "wrap_comma_noop_assignment_rhs",
        "numeric_cast_shape": "elide_numeric_cast",
        "void_to_value_return_shape": "return_tail_call_value",
        "global_pointer_alias_shape": "introduce_global_pointer_alias",
        "named_zero_local_shape": "introduce_named_zero_local",
        "empty_do_while_barrier": "insert_empty_do_while_barrier",
        "switch_case_order_default_shape": "swap_simple_switch_cases",
        "bool_int_accumulator_shape": "rewrite_bool_accumulator_as_int",
        "zero_compare_logical_not": "rewrite_zero_compare_logical_not",
        "abs_macro_expression_fold": "rewrite_abs_ternary_to_macro",
        "minmax_macro_ternary_shape": "rewrite_minmax_macro_to_ternary",
        "global_float_literal_shape": "replace_float_literal_with_global_constant",
        "callback_cast_elision": "elide_callback_cast",
        "redundant_pointer_cast_elision": "elide_redundant_pointer_cast",
        "vector_alias_type_shape": "rewrite_vector_alias_type",
        "unused_trailing_parameter": "remove_unused_trailing_parameter",
        "outgoing_parameter_area_shape": (
            "materialize_outgoing_parameter_area_call_args"
        ),
    }

    for family_id, mutator_key in expected.items():
        family = by_id[family_id]
        assert mutator_key in family.mutator_keys
        assert "record-only" not in family.generated_probe_form


def test_plan_transform_experiments_groups_e7b4_force_phys_clusters() -> None:
    plan = plan_transform_experiments(
        function="ftCo_8009E7B4",
        unit="melee/ft/ftcommon",
        force_phys={58: 4, 44: 4, 42: 3, 35: 29, 56: 30, 34: 31},
    )

    assert plan.function == "ftCo_8009E7B4"
    assert plan.source_file == "src/melee/ft/ftcommon.c"
    assert {cluster.cluster_id for cluster in plan.clusters} == {
        "early_flag_reload",
        "late_field_loop_tree",
    }
    early = next(cluster for cluster in plan.clusters if cluster.cluster_id == "early_flag_reload")
    assert early.target_assignments == ("ig58->r4", "ig44->r4", "ig42->r3")
    assert "reload_branch_scope" in early.family_ids
    late = next(cluster for cluster in plan.clusters if cluster.cluster_id == "late_field_loop_tree")
    assert "loop_index_pointer_walk_split" in late.family_ids


def test_plan_transform_experiments_names_mndiagram_coloring_cluster() -> None:
    plan = plan_transform_experiments(
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={58: 4, 35: 29},
    )

    assert plan.function == "mnDiagram2_Create"
    assert plan.source_file == "src/melee/mn/mndiagram2.c"
    assert {cluster.cluster_id for cluster in plan.clusters} == {
        "mndiagram_coloring_register_steering"
    }
    cluster = plan.clusters[0]
    assert cluster.target_assignments == ("ig35->r29", "ig58->r4")
    assert cluster.family_ids == (
        "coloring_register_steering",
        "indexed_byte_address_temp_steering",
    )
    assert [family.family_id for family in plan.families] == [
        "coloring_register_steering",
        "indexed_byte_address_temp_steering",
    ]
    assert "register-coloring" in cluster.rationale


def test_plan_transform_experiments_routes_ranked_fighter_to_cursor_iv_family() -> None:
    plan = plan_transform_experiments(
        function="mnDiagram2_GetRankedFighter",
        unit="melee/mn/mndiagram2",
        force_phys={},
    )

    assert plan.source_file == "src/melee/mn/mndiagram2.c"
    assert [family.family_id for family in plan.families] == [
        "ranked_cursor_iv_unification"
    ]
    assert plan.clusters[0].cluster_id == "ranked_cursor_iv_unification"


def test_plan_transform_experiments_keeps_ranked_fighter_force_phys_coloring() -> None:
    plan = plan_transform_experiments(
        function="mnDiagram2_GetRankedFighter",
        unit="melee/mn/mndiagram2",
        force_phys={58: 4, 35: 29},
    )

    assert [family.family_id for family in plan.families] == [
        "coloring_register_steering",
        "indexed_byte_address_temp_steering",
        "ranked_cursor_iv_unification",
    ]
    clusters = {cluster.cluster_id: cluster for cluster in plan.clusters}
    assert set(clusters) == {
        "ranked_cursor_iv_unification",
        "mndiagram_coloring_register_steering",
    }
    coloring = clusters["mndiagram_coloring_register_steering"]
    assert coloring.family_ids == (
        "coloring_register_steering",
        "indexed_byte_address_temp_steering",
    )
    assert coloring.target_assignments == ("ig35->r29", "ig58->r4")


def test_plan_transform_experiments_keeps_generic_fallback_for_other_force_phys() -> None:
    plan = plan_transform_experiments(
        function="ftCo_8009FFFF",
        unit="melee/ft/ftcommon",
        force_phys={58: 4, 35: 29},
    )

    assert {cluster.cluster_id for cluster in plan.clusters} == {
        "generic_allocator_shape"
    }
    assert "coloring_register_steering" not in {
        family.family_id for family in plan.families
    }


def test_requested_scalar_family_can_extend_named_plan_allow_list() -> None:
    source = (
        "void ftCo_8009E7B4(void) {\n"
        "    if (status == 0) {\n"
        "        use_status();\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="ftCo_8009E7B4",
        unit="melee/ft/ftcommon",
        force_phys={58: 4},
        families=("zero_compare_logical_not",),
        max_per_family=1,
    )

    assert "zero_compare_logical_not" in {probe.family_id for probe in probes}
