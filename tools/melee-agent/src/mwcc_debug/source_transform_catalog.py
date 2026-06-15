"""Inventory of targeted source-transform generators.

The catalogue is intentionally metadata-only: it documents which tooling
surfaces synthesize C-source variants, where their generator lives, and how
many operator families or strategies each surface can exercise.  It should not
be used as a dispatcher; the actual generators remain the source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.mwcc_debug.control_flow_shape import DEFAULT_CONTROL_FLOW_OPERATORS
from src.mwcc_debug.pressure_explorer import (
    SOURCE_LIFETIME_GENERIC_OPERATORS,
    SOURCE_LIFETIME_TARGETED_OPERATORS,
)
from src.search.directed.transform_corpus import DEFAULT_TRANSFORM_FAMILIES


LIFETIME_LAYOUT_OPERATORS: tuple[str, ...] = (
    "frame-reservation-pad-stack",
    "call-return-compare-chain",
    "expression-shape",
    "declaration-order",
    "loop-counter-hoist",
    "loop-counter-type",
    "indexed-pointer-loop",
    "pointer-walk-loop",
    "pointer-base-call-loop",
    "temp-introduction",
    "temp-removal",
    "type-width",
    "declaration-use-distance",
    "guard-shape",
    "early-guard-return",
    "block-scope",
    "loop-init",
    "condition-nesting",
    "call-argument-tempization",
)

FRAME_TRANSFORM_OPERATORS: tuple[str, ...] = (
    "frame-reservation-pad-stack",
    "frame-local-dematerialize",
    "frame-direct-literal-at-final-fp-call",
    "frame-split-fp-const-lifetime",
    "frame-magic-scratch-relocation",
)

NAME_MAGIC_OPERATORS: tuple[str, ...] = (
    "data-symbol-static-to-global",
    "bss-anchor-source-binding",
    "sdata2-named-float-load",
    "name-magic-source-combined",
)

DIRECT_MUTATOR_TECHNIQUES: tuple[str, ...] = (
    "type-change",
    "insert-alias-before-use",
    "preserve-lifetime-after-use",
)

DECL_ORDER_STRATEGIES: tuple[str, ...] = (
    "promote",
    "demote",
    "adjacent-swap",
    "full-permutation",
)

SIMPLIFY_ORDER_ADAPTERS: tuple[str, ...] = (
    "decl-orders-source",
    "insert-alias-source",
    "holder-lifetime-source",
    "type-change-source",
    "permuter-source-optional",
)

TIER3_SEARCH_SEEDS: tuple[str, ...] = (
    "insert-alias",
    "type-change",
    "source-shape",
)

STACK_HOME_LOCAL_ARRAY_SQRT_VARIANTS: tuple[str, ...] = (
    "local-array-sqrt-slot-1-index-0",
    "local-array-sqrt-slot-2-index-1",
    "branch-local-array-sqrt-slot-1-index-0",
    "branch-local-array-sqrt-slot-2-index-1",
)

STRUCTURE_SEARCH_AXIS_TECHNIQUES: tuple[str, ...] = (
    "decl-order:promote",
    "decl-order:demote",
    "decl-order:swap",
    *(f"control-flow:{operator}" for operator in DEFAULT_CONTROL_FLOW_OPERATORS),
    "case-order:adjacent-swap",
    "case-order:promote",
    "case-order:demote",
    "statement-order:hoist-sink",
    "statement-order:split-shift-or",
    "statement-order:fuse-shift-or",
    "statement-order:adjacent-swap",
    *(f"source-lifetime:{operator}" for operator in (
        *SOURCE_LIFETIME_TARGETED_OPERATORS,
        *SOURCE_LIFETIME_GENERIC_OPERATORS,
    )),
    "inline-boundary:axis-setter-wrapper",
    "inline-boundary:call-result-temp",
    "inline-boundary:popup-text-setup-helper",
    "inline-boundary:popup-number-format-helper",
    "inline-boundary:sort-entry-init-helper",
    "inline-boundary:call-arg-temp",
    "inline-boundary:user-data-cast",
    "inline-boundary:sislib-cleanup-helper",
    "loop-shape-expanded:direct-index",
    "loop-shape-expanded:predicate-temp",
    "loop-shape-expanded:inverted-predicate",
    "loop-shape-expanded:helper",
    "loop-shape-expanded:base-pointer",
)

DIRECTED_MUTATOR_KEYS: tuple[str, ...] = (
    "reorder_local_decls",
    "change_counter_width",
    "split_decl_init",
    "flatten_nested_if",
    "unflatten_else_if",
    "remove_branch_scope",
    "add_branch_scope",
    "widen_local_lifetime",
    "narrow_local_lifetime",
    "reuse_loop_counter_scope",
    "add_explicit_zero_return",
    "introduce_named_zero_local",
    "wrap_comma_noop_assignment_rhs",
    "insert_empty_do_while_barrier",
    "fold_assignment_expression_seed",
    "elide_numeric_cast",
    "swap_simple_switch_cases",
    "collapse_hsd_assert",
    "return_tail_call_value",
    "replace_string_literal_with_data_field",
    "introduce_global_pointer_alias",
    "rewrite_raw_pointer_offset_field",
    "rewrite_raw_index_struct_field",
    "rewrite_data_table_indirection",
    "rewrite_bool_accumulator_as_int",
    "rewrite_zero_compare_logical_not",
    "rewrite_abs_ternary_to_macro",
    "rewrite_minmax_macro_to_ternary",
    "replace_float_literal_with_global_constant",
    "replace_global_float_constant_with_literal",
    "reassociate_fp_subtraction_operands",
    "elide_redundant_pointer_cast",
    "elide_callback_cast",
    "remove_unused_trailing_parameter",
    "add_unused_trailing_parameter",
    "materialize_outgoing_parameter_area_call_args",
    "rewrite_vector_alias_type",
    "inline_simple_helper_call",
    "extract_repeated_assignment_helper",
    "reuse_same_type_local_lifetime",
    "add_dont_inline_pragma_pair",
    "remove_dont_inline_pragma_pair",
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
    "steer_node_set_delta_coupled_split",
    "steer_node_set_delta_introduce_binding_split",
    "steer_node_set_delta_split",
    "swap_independent_adjacent_statements",
    "scheduler_anchor_iv_init_before_bias",
    "scheduler_split_float_cast_temp",
    "scheduler_empty_barrier_before_float_cast",
    "unify_ranked_cursor_value_accumulator",
    "reuse_rank_pointer_return_field",
)

DIRECTED_TRANSFORM_FAMILY_IDS: tuple[str, ...] = tuple(
    family.family_id for family in DEFAULT_TRANSFORM_FAMILIES
)


@dataclass(frozen=True)
class SourceTransformCatalogEntry:
    surface: str
    entrypoint: str
    implementation: str
    purpose: str
    technique_basis: str
    techniques: tuple[str, ...]
    concrete_forms: tuple[str, ...] = ()
    reused_by: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def technique_count(self) -> int:
        return len(self.techniques)

    @property
    def concrete_form_count(self) -> int:
        return len(self.concrete_forms)


SOURCE_TRANSFORM_CATALOG: tuple[SourceTransformCatalogEntry, ...] = (
    SourceTransformCatalogEntry(
        surface="direct mutator functions",
        entrypoint="src.mwcc_debug.mutators",
        implementation=(
            "mutate_type_change, mutate_insert_alias_before_use, "
            "mutate_preserve_lifetime_after_use"
        ),
        purpose="Primitive single-edit source rewrites used by CLI commands and searches.",
        technique_basis="mutator functions",
        techniques=DIRECT_MUTATOR_TECHNIQUES,
        concrete_forms=(
            "type-change: rewrite one local declaration, splitting combined declarations when needed",
            "insert-alias-before-use: combined local alias at block top",
            "insert-alias-before-use: C89 split declaration plus assignment before use",
            "preserve-lifetime-after-use: volatile sink declaration plus post-use assignment",
        ),
        reused_by=(
            "debug mutate type-change",
            "debug mutate insert-alias",
            "debug mutate search",
            "debug mutate simplify-order",
        ),
    ),
    SourceTransformCatalogEntry(
        surface="debug mutate decl-orders",
        entrypoint="melee-agent debug mutate decl-orders",
        implementation="src.cli.debug.mutate_decl_orders_cmd",
        purpose="Brute-force small local declaration ordering changes.",
        technique_basis="ordering strategies",
        techniques=DECL_ORDER_STRATEGIES,
        concrete_forms=(
            "move each non-first declaration to the front",
            "move each non-last declaration to the end",
            "swap each adjacent declaration pair",
            "try every permutation for small scopes",
        ),
        reused_by=("debug mutate simplify-order", "debug search structure"),
    ),
    SourceTransformCatalogEntry(
        surface="debug mutate lifetime-layout",
        entrypoint="melee-agent debug mutate lifetime-layout",
        implementation="src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        purpose="Generate conservative lifetime, declaration, loop, and expression-shape probes.",
        technique_basis="operator families",
        techniques=LIFETIME_LAYOUT_OPERATORS,
        concrete_forms=(
            "call-return-compare-chain: switch, inverted chain, copy-in-else, split-direct, narrow-pointer",
            "expression-shape: assignment-expression CSE removal, dx/dy temps, abs discriminator split",
            "loop-counter-hoist: nested counter hoist/reuse and sibling-loop hoist",
            "indexed-pointer-loop: bound local, index temp, base alias, address temp",
            "pointer-walk-loop: index temp, base alias, address temp, value temp, induction pointer, end pointer",
            "pointer-base-call-loop: indexed call, value temp, address temp, induction pointer, end pointer",
        ),
        reused_by=(
            "debug select-order-search",
            "debug mutate control-flow-shape-search delegated operators",
            "debug mutate frame-transform-search lifetime fallbacks",
        ),
    ),
    SourceTransformCatalogEntry(
        surface="debug mutate control-flow-shape-search",
        entrypoint="melee-agent debug mutate control-flow-shape-search",
        implementation="src.mwcc_debug.control_flow_shape.generate_control_flow_shape_probes",
        purpose="Generate and score branch/control-flow spelling alternatives.",
        technique_basis="operator families",
        techniques=DEFAULT_CONTROL_FLOW_OPERATORS,
        concrete_forms=(
            "delegates eight operators to lifetime-layout",
            "ternary assignment to if/else assignment",
            "simple if/else assignment to ternary assignment",
            "boolean condition spelling toggles",
            "equality if to single-case switch",
        ),
        reused_by=("debug search structure control-flow axis",),
    ),
    SourceTransformCatalogEntry(
        surface="debug mutate indexed-struct-search",
        entrypoint="melee-agent debug mutate indexed-struct-search",
        implementation="src.mwcc_debug.pressure_explorer.generate_indexed_struct_pointer_probes",
        purpose="Dematerialize indexed struct pointers and split direct indexed accesses.",
        technique_basis="operator families",
        techniques=("indexed-struct-pointer",),
        concrete_forms=(
            "remove materialized pointer and rewrite field uses through the direct indexed expression",
            "split first direct indexed field into a scalar local",
            "split first direct indexed element into a scalar local",
        ),
    ),
    SourceTransformCatalogEntry(
        surface="debug mutate name-magic-source-declarations",
        entrypoint="melee-agent debug mutate name-magic-source-declarations",
        implementation="src.mwcc_debug.name_magic_source.generate_name_magic_source_probes",
        purpose="Create source edits for name-magic relocation mismatches.",
        technique_basis="operator families",
        techniques=NAME_MAGIC_OPERATORS,
        concrete_forms=(
            "remove static from a file-scope data definition",
            "bind a BSS anchor to an existing source declaration",
            "replace a unique float/double literal with a named extern symbol",
            "combine non-overlapping name-magic edits",
        ),
    ),
    SourceTransformCatalogEntry(
        surface="debug mutate frame-transform-search",
        entrypoint="melee-agent debug mutate frame-transform-search",
        implementation="src.mwcc_debug.pressure_explorer.generate_frame_directed_probes",
        purpose="Generate directed source variants for frame-size and local-area residuals.",
        technique_basis="operator families",
        techniques=FRAME_TRANSFORM_OPERATORS,
        concrete_forms=(
            "PAD_STACK insert/increase/decrease/remove",
            "inline one-use local into its use",
            "pass one-use FP literal directly at final FP call",
            "move FP-constant assignment next to its final use",
            "relocate int-to-float scratch assignment closer to final FP call",
        ),
    ),
    SourceTransformCatalogEntry(
        surface="debug mutate simplify-order",
        entrypoint="melee-agent debug mutate simplify-order",
        implementation="src.mwcc_debug.simplify_variants",
        purpose="Aggregate bounded source-variant streams and rank by simplify/select-order objectives.",
        technique_basis="variant-source adapters",
        techniques=SIMPLIFY_ORDER_ADAPTERS,
        concrete_forms=(
            "decl-orders source: promote, demote, adjacent swap",
            "insert-alias source: bounded reading-use alias insertion",
            "holder-lifetime source: bounded volatile lifetime sink insertion",
            "type-change source: eight signedness flip pairs",
            "optional permuter source: harvested pre-existing permuter output",
        ),
    ),
    SourceTransformCatalogEntry(
        surface="debug mutate search",
        entrypoint="melee-agent debug mutate search",
        implementation="src.mwcc_debug.tier3_search.plan_seeds",
        purpose="Seed short permuter runs from targeted source mutations.",
        technique_basis="seed mutator kinds",
        techniques=TIER3_SEARCH_SEEDS,
        concrete_forms=(
            "pointer locals: alias split before first use",
            "integer locals: bounded type widening/shrinking variants",
            "source-shape seeds: materialized lifetime/source-shape probes",
        ),
    ),
    SourceTransformCatalogEntry(
        surface="debug select-order-search",
        entrypoint="melee-agent debug select-order-search",
        implementation="src.cli.debug.debug_select_order_search_cmd",
        purpose="Score lifetime-layout probes against COLORGRAPH select-order targets.",
        technique_basis="reused lifetime-layout operators",
        techniques=LIFETIME_LAYOUT_OPERATORS,
        concrete_forms=(
            "single-probe lifetime-layout variants",
            "optional PAD_STACK frame reservation probe",
            "optional beam composition of generated lifetime-layout probes",
        ),
        reused_by=("debug target order-target follow-up workflows",),
    ),
    SourceTransformCatalogEntry(
        surface="debug search structure",
        entrypoint="melee-agent debug search structure",
        implementation="src.search.structure",
        purpose="Run broader source-structure axes and rank generated source candidates.",
        technique_basis="axis-specific operators",
        techniques=STRUCTURE_SEARCH_AXIS_TECHNIQUES,
        concrete_forms=(
            "decl-order axis: promote, demote, swap",
            "control-flow axis: control-flow-shape probe families",
            "case-order axis: adjacent swap, promote, demote switch arms",
            "statement-order axis: hoist/sink, split/fuse shift-or, adjacent swap",
            "source-lifetime axis: targeted and generic source-lifetime probes",
            "inline-boundary axis: eight helper/inline-boundary families",
            "loop-shape-expanded axis: five MN sorted-list scan rewrites",
        ),
    ),
    SourceTransformCatalogEntry(
        surface="debug search plan-transforms / directed",
        entrypoint="melee-agent debug search plan-transforms",
        implementation="src.search.directed.transform_corpus",
        purpose=(
            "Plan proof-vector-driven transform families and instantiate bounded "
            "source-shape probes for directed search and opt-in scoring commands."
        ),
        technique_basis="transform families",
        techniques=DIRECTED_TRANSFORM_FAMILY_IDS,
        concrete_forms=DIRECTED_MUTATOR_KEYS,
        reused_by=(
            "debug search directed",
            "debug search run --directed-force-phys",
            "debug mutate lifetime-layout --include-transform-corpus",
            "debug coalesce-search --include-transform-corpus",
            "debug select-order-search --include-transform-corpus",
            "debug mutate frame-transform-search --include-transform-corpus",
        ),
        notes=(
            "debug search directed and debug search run --directed-force-phys use transform-corpus probes for directed source-shape proposals.",
            "debug mutate lifetime-layout, debug coalesce-search, and debug select-order-search append transform-corpus probes only when --include-transform-corpus or --transform-family opts in.",
            "debug mutate frame-transform-search can append transform-corpus probes with the same opt-in flags and defaults to frame-relevant mined families when no family filter is supplied.",
            "helper_shape is backed by guarded scalar helper inline/extract probes.",
            "coloring_register_steering aliases guarded declaration/lifetime edits and FPR product recompute probes for mndiagram force-phys register-coloring residuals.",
            "node_set_delta materialized probes wrap guarded node-set-split CandidatePatch sources and are transform-corpus probe keys, not standalone apply_mutator dispatch keys.",
            "same_type_local_lifetime_reuse is backed by reuse_same_type_local_lifetime for simple non-overlapping same-type locals.",
            "independent_statement_order is backed by dependency-proven adjacent same-block assignment swaps.",
            "data_table_indirection_shape is backed by rewrite_data_table_indirection for source-local immutable pointer-table reads.",
            "explicit_zero_return is backed by add_explicit_zero_return for call-only wrapper bodies.",
            "named_zero_local_shape is backed by introduce_named_zero_local for paired NULL sentinel checks and resets.",
            "raw_index_struct_field_shape is backed by rewrite_raw_index_struct_field for typed pointer-parameter raw indexed byte-offset accesses.",
            "bool_int_accumulator_shape is backed by rewrite_bool_accumulator_as_int for guarded bool/BOOL OR-accumulators.",
            "global_float_literal_shape is backed by source-local unique float literal/constant swaps.",
            "fp_subtraction_operand_reassociation is backed by reassociate_fp_subtraction_operands for exact -X - C floating literal subtractions.",
            "abs_macro_expression_fold is backed by rewrite_abs_ternary_to_macro for simple side-effect-free ABS ternary operands.",
            "callback_cast_elision is backed by elide_callback_cast for call arguments with matching local callback signatures.",
            "zero_compare_logical_not is backed by rewrite_zero_compare_logical_not for single-evaluation zero comparisons.",
            "function_codegen_pragma_shape is backed by exact push/dont_inline/pop wrapper add/remove probes.",
            "redundant_pointer_cast_elision is backed by elide_redundant_pointer_cast for local pointer-compatible call arguments and assignments.",
            "unused_trailing_parameter is backed by static self-contained signature/call-site contract probes.",
            "outgoing_parameter_area_shape is backed by exact high-arity call-site materialization and immediate one-use argument-local dematerialization probes for outgoing parameter-area sizing.",
            "vector_alias_type_shape is backed by rewrite_vector_alias_type for local declarations using source-local identical struct aliases.",
            "minmax_macro_ternary_shape is backed by rewrite_minmax_macro_to_ternary for simple side-effect-free MIN/MAX operands.",
            "assert_macro_expansion_shape is backed by collapse_hsd_assert for file-proven HSD_ASSERTMSG collapses.",
            "assignment_expression_temp_seed is backed by fold_assignment_expression_seed for adjacent pure temp seeds.",
            "string_literal_data_blob_field_shape is backed by replace_string_literal_with_data_field for unique source-local data fields.",
            "raw_pointer_offset_struct_field_shape is backed by rewrite_raw_pointer_offset_field for exact local struct-layout proofs.",
            "comma_operator_noop_expression_shape is backed by wrap_comma_noop_assignment_rhs for simple assignment RHS expressions.",
            "numeric_cast_shape is backed by elide_numeric_cast for same-formal-type call-argument casts.",
            "void_to_value_return_shape is backed by return_tail_call_value for static void tail-call wrappers with local scalar helper proof.",
            "global_pointer_alias_shape is backed by introduce_global_pointer_alias for visible globals with repeated member access.",
            "empty_do_while_barrier is backed by insert_empty_do_while_barrier for simple statement boundaries.",
            "switch_case_order_default_shape is backed by swap_simple_switch_cases for adjacent break-terminated switch arms.",
            "ranked_cursor_iv_unification is backed by exact ranked selection-loop and rank-pointer return probes for mnDiagram2_GetRankedFighter.",
        ),
    ),
    SourceTransformCatalogEntry(
        surface="debug inspect stack-homes --compile-local-array-variants",
        entrypoint="melee-agent debug inspect stack-homes",
        implementation="src.mwcc_debug.stack_home_explorer.generate_local_array_sqrt_variants",
        purpose="Seed known local-array sqrtf stack-home layout variants.",
        technique_basis="fixed local-array sqrtf variants",
        techniques=STACK_HOME_LOCAL_ARRAY_SQRT_VARIANTS,
        concrete_forms=STACK_HOME_LOCAL_ARRAY_SQRT_VARIANTS,
    ),
)


def catalog_summary() -> dict[str, int]:
    """Return headline counts for docs/tests."""
    return {
        "surfaces": len(SOURCE_TRANSFORM_CATALOG),
        "techniques": sum(entry.technique_count for entry in SOURCE_TRANSFORM_CATALOG),
        "concrete_forms": sum(
            entry.concrete_form_count for entry in SOURCE_TRANSFORM_CATALOG
        ),
    }
