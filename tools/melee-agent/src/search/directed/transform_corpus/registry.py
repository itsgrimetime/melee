"""Transform-family registry and static experiment planner."""
from __future__ import annotations

from src.search.directed.transform_corpus.common import _source_file_for_unit
from src.search.directed.transform_corpus.models import TransformCluster, TransformExperimentPlan, TransformFamily
from typing import Iterable, Mapping


DEFAULT_TRANSFORM_FAMILIES: tuple[TransformFamily, ...] = (
    TransformFamily(
        family_id="temp_sink_hoist",
        label="temp sink/hoist",
        mutator_keys=("widen_local_lifetime", "narrow_local_lifetime"),
        semantic_risk="low",
        source_region_selector="local temporary declarations near reload/call boundaries",
        expected_compiler_effect="change temp live-range overlap and allocator pressure",
        generated_probe_form="move a local declaration across a nearby control boundary",
        keywords=("temp", "sink", "hoist", "reload"),
    ),
    TransformFamily(
        family_id="condition_split_merge",
        label="condition split/merge",
        mutator_keys=("flatten_nested_if", "unflatten_else_if"),
        semantic_risk="low",
        source_region_selector="adjacent if/else-if predicate blocks",
        expected_compiler_effect="change predicate-temp and branch-reload lifetimes",
        generated_probe_form="toggle nested else-if and explicit else { if (...) } forms",
        keywords=("condition", "predicate", "split", "merge"),
    ),
    TransformFamily(
        family_id="scoped_alias",
        label="scoped alias",
        mutator_keys=("split_decl_init",),
        semantic_risk="medium",
        source_region_selector="single local declaration with initializer",
        expected_compiler_effect="introduce a source-visible alias/use boundary",
        generated_probe_form="split declaration initializers before later use-site rewrites",
        keywords=("alias", "scope", "initializer"),
    ),
    TransformFamily(
        family_id="declaration_use_boundary",
        label="declaration/use boundary movement",
        mutator_keys=("reorder_local_decls", "split_decl_init"),
        semantic_risk="low",
        source_region_selector="adjacent local declarations and declaration initializers",
        expected_compiler_effect="change declaration-order and first-use tie-breaks",
        generated_probe_form="swap adjacent declarations or split declaration initializers",
        keywords=("decl", "order", "boundary", "use"),
    ),
    TransformFamily(
        family_id="coloring_register_steering",
        label="coloring register steering",
        mutator_keys=(
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
        ),
        semantic_risk="medium",
        source_region_selector=(
            "declaration order, initializer boundaries, loop counters, and "
            "same-type locals near force-phys coloring residuals"
        ),
        expected_compiler_effect=(
            "steer MWCC register-coloring tie-breaks by changing source-visible "
            "virtual-register order and live-range overlap"
        ),
        generated_probe_form=(
            "emit guarded declaration-window, declaration-demotion, loop-counter "
            "split, or aliased source edits as register-steering probes"
        ),
        keywords=("coloring", "register", "force-phys", "decl", "loop", "lifetime"),
    ),
    TransformFamily(
        family_id="ranked_cursor_iv_unification",
        label="ranked cursor/value IV unification",
        mutator_keys=(
            "unify_ranked_cursor_value_accumulator",
            "reuse_rank_pointer_return_field",
        ),
        semantic_risk="medium",
        source_region_selector=(
            "selection-sort cursor loops with an indexed max-value read and "
            "a cursor-derived selected-value accumulator"
        ),
        expected_compiler_effect=(
            "unify indexed selection reads with the existing cursor/value IV "
            "so MWCC can share the holder instead of materializing a separate "
            "base-plus-index value read"
        ),
        generated_probe_form=(
            "rewrite the selected-value comparison to use and update the "
            "cursor accumulator, or reuse the rank pointer for the final field return"
        ),
        keywords=("ranked", "cursor", "iv", "selection", "accumulator"),
    ),
    TransformFamily(
        family_id="loop_index_pointer_walk_split",
        label="loop index vs pointer-walk role split",
        mutator_keys=("reuse_loop_counter_scope",),
        semantic_risk="medium",
        source_region_selector="nested loop counter declarations",
        expected_compiler_effect="change loop-index and pointer-walk holder overlap",
        generated_probe_form="reuse an outer loop counter instead of redeclaring an inner one",
        keywords=("loop", "index", "pointer", "walk"),
    ),
    TransformFamily(
        family_id="helper_shape",
        label="helper inline/extract and argument shape",
        mutator_keys=("inline_simple_helper_call", "extract_repeated_assignment_helper"),
        semantic_risk="high",
        source_region_selector="helper call and candidate inline boundaries",
        expected_compiler_effect="change call-adjacent temp materialization",
        generated_probe_form=(
            "inline a scalar single-expression helper call or extract repeated "
            "scalar assignment expressions into a file-local helper"
        ),
        keywords=("helper", "inline", "extract", "argument"),
    ),
    TransformFamily(
        family_id="counter_type_shape",
        label="int vs s32 loop counter",
        mutator_keys=("change_counter_width",),
        semantic_risk="low",
        source_region_selector="loop counter declarations",
        expected_compiler_effect="change MWCC loop and induction-variable heuristics",
        generated_probe_form="toggle counter width/type where source-compatible",
        keywords=("int", "s32", "loop", "counter"),
    ),
    TransformFamily(
        family_id="reload_branch_scope",
        label="reload branch scope",
        mutator_keys=("add_branch_scope", "remove_branch_scope"),
        semantic_risk="low",
        source_region_selector="branch bodies around reloads and predicate tests",
        expected_compiler_effect="change reload lifetime and branch-local pressure",
        generated_probe_form="add or remove one brace-only branch-local scope",
        keywords=("reload", "branch", "scope"),
    ),
    TransformFamily(
        family_id="lifetime_preserve_shorten",
        label="lifetime preserve/shorten around calls/loops",
        mutator_keys=("widen_local_lifetime", "narrow_local_lifetime"),
        semantic_risk="medium",
        source_region_selector="local declarations near call, loop, or branch boundaries",
        expected_compiler_effect="extend or shorten holder lifetime across allocator pressure points",
        generated_probe_form="move a local declaration outward or inward across a boundary",
        keywords=("lifetime", "preserve", "shorten", "call", "loop"),
    ),
    TransformFamily(
        family_id="same_type_local_lifetime_reuse",
        label="same-type local lifetime reuse",
        mutator_keys=("reuse_same_type_local_lifetime",),
        semantic_risk="medium",
        source_region_selector=(
            "same-type local declarations whose live ranges do not overlap"
        ),
        expected_compiler_effect=(
            "reduce local count and register pressure by reusing one temp "
            "after its prior lifetime ends"
        ),
        generated_probe_form=(
            "delete a later same-type local declaration and reuse an earlier "
            "local after its proven non-overlapping lifetime"
        ),
        keywords=("same-type", "local", "lifetime", "reuse", "cur", "prev", "next", "iter"),
    ),
    TransformFamily(
        family_id="independent_statement_order",
        label="independent statement order",
        mutator_keys=("swap_independent_adjacent_statements",),
        semantic_risk="medium",
        source_region_selector=(
            "adjacent independent statements or stores in the same block"
        ),
        expected_compiler_effect=(
            "change store ordering, scheduling, and live-range overlap without "
            "changing data dependencies"
        ),
        generated_probe_form=(
            "swap adjacent same-block assignment statements when local read/write "
            "sets prove independence"
        ),
        keywords=("statement", "order", "store", "independent", "schedule", "swap"),
    ),
    TransformFamily(
        family_id="data_table_indirection_shape",
        label="data table indirection shape",
        mutator_keys=("rewrite_data_table_indirection",),
        semantic_risk="high",
        source_region_selector=(
            "source-local immutable pointer-table expressions with known outer table layout"
        ),
        expected_compiler_effect=(
            "change expression addressing by adding a typed outer data-table "
            "indirection while preserving the inner dynamic index"
        ),
        generated_probe_form=(
            "rewrite a direct table read through a source-local immutable outer table"
        ),
        keywords=("data", "table", "indirection", "global", "index", "expression"),
    ),
    TransformFamily(
        family_id="explicit_zero_return",
        label="explicit zero return",
        mutator_keys=("add_explicit_zero_return",),
        semantic_risk="medium",
        source_region_selector=(
            "non-void side-effect wrappers that fall through without a value"
        ),
        expected_compiler_effect=(
            "materialize a zero return value after side effects in wrapper functions"
        ),
        generated_probe_form=(
            "insert an explicit zero return after a one-call wrapper body"
        ),
        keywords=("return", "zero", "nonvoid", "wrapper", "side-effect"),
    ),
    TransformFamily(
        family_id="named_zero_local_shape",
        label="named zero/NULL local",
        mutator_keys=("introduce_named_zero_local",),
        semantic_risk="medium",
        source_region_selector=(
            "paired NULL sentinel checks and assignments in one local block"
        ),
        expected_compiler_effect=(
            "split or join zero-CSE web membership by naming the NULL value "
            "as a source-visible local"
        ),
        generated_probe_form=(
            "insert a typed pointer NULL local and replace one matched = NULL reset"
        ),
        keywords=("zero", "NULL", "sentinel", "CSE", "local"),
    ),
    TransformFamily(
        family_id="raw_index_struct_field_shape",
        label="raw index to struct field shape",
        mutator_keys=("rewrite_raw_index_struct_field",),
        semantic_risk="high",
        source_region_selector=(
            "raw indexed storage accesses with a recovered struct field map"
        ),
        expected_compiler_effect=(
            "replace integer index loads/stores with typed struct field accesses"
        ),
        generated_probe_form=(
            "rewrite a raw indexed byte-offset expression to a typed struct field access"
        ),
        keywords=("raw", "index", "struct", "field", "typed", "user_data"),
    ),
    TransformFamily(
        family_id="bool_int_accumulator_shape",
        label="bool vs int accumulator shape",
        mutator_keys=("rewrite_bool_accumulator_as_int",),
        semantic_risk="medium",
        source_region_selector=(
            "predicate accumulators initialized from int-returning helpers and OR-assigned"
        ),
        expected_compiler_effect=(
            "preserve integer-width predicate accumulation and compare against zero"
        ),
        generated_probe_form=(
            "rewrite a guarded bool/BOOL OR-accumulator local to s32 spelling"
        ),
        keywords=("bool", "int", "accumulator", "predicate", "or", "zero"),
    ),
    TransformFamily(
        family_id="global_float_literal_shape",
        label="global float literal shape",
        mutator_keys=(
            "replace_float_literal_with_global_constant",
            "replace_global_float_constant_with_literal",
        ),
        semantic_risk="high",
        source_region_selector=(
            "named global floating-point constants and equivalent floating-point literals"
        ),
        expected_compiler_effect=(
            "change constant materialization and relocation shape for FP loads"
        ),
        generated_probe_form=(
            "swap inline floating literals with unique source-local constant symbols"
        ),
        keywords=("float", "literal", "global", "sdata2", "constant"),
    ),
    TransformFamily(
        family_id="fp_subtraction_operand_reassociation",
        label="FP subtraction operand reassociation",
        mutator_keys=("reassociate_fp_subtraction_operands",),
        semantic_risk="low",
        source_region_selector=(
            "true FP subtraction expressions of the form -X - C with a "
            "positive floating-point literal RHS and float evidence for X"
        ),
        expected_compiler_effect=(
            "change fneg/fsubs operand materialization while preserving the "
            "two-term negative floating-point sum"
        ),
        generated_probe_form=(
            "rewrite expression-start -X - C as -C - X for one exact span"
        ),
        keywords=("float", "subtraction", "reassociate", "literal", "fsubs"),
    ),
    TransformFamily(
        family_id="abs_macro_expression_fold",
        label="abs macro expression fold",
        mutator_keys=("rewrite_abs_ternary_to_macro",),
        semantic_risk="medium",
        source_region_selector=(
            "absolute-value spelling around simple scalar expressions"
        ),
        expected_compiler_effect=(
            "toggle inline compare/negate shape versus helper or macro-like spelling"
        ),
        generated_probe_form=(
            "rewrite a simple absolute-value ternary to ABS(expr)"
        ),
        keywords=("abs", "macro", "expression", "fold", "negate"),
    ),
    TransformFamily(
        family_id="callback_cast_elision",
        label="callback cast elision",
        mutator_keys=("elide_callback_cast",),
        semantic_risk="medium",
        source_region_selector=(
            "callback or function-pointer casts at call arguments and table entries"
        ),
        expected_compiler_effect=(
            "change call target type materialization and temporary pressure"
        ),
        generated_probe_form=(
            "elide a call-argument callback cast when local signatures match exactly"
        ),
        keywords=("callback", "function-pointer", "cast", "elision"),
    ),
    TransformFamily(
        family_id="zero_compare_logical_not",
        label="zero compare vs logical not",
        mutator_keys=("rewrite_zero_compare_logical_not",),
        semantic_risk="low",
        source_region_selector=(
            "zero comparisons on scalar predicates and helper return values"
        ),
        expected_compiler_effect=(
            "change predicate spelling between explicit compare and logical-not forms"
        ),
        generated_probe_form=(
            "rewrite a single-evaluation zero comparison to logical-not/direct spelling"
        ),
        keywords=("zero", "compare", "logical-not", "predicate", "condition"),
    ),
    TransformFamily(
        family_id="function_codegen_pragma_shape",
        label="function codegen pragma shape",
        mutator_keys=("add_dont_inline_pragma_pair", "remove_dont_inline_pragma_pair"),
        semantic_risk="high",
        source_region_selector=(
            "function-local codegen pragmas such as dont_inline around tiny wrappers"
        ),
        expected_compiler_effect=(
            "change inlining/codegen contract without changing the function body"
        ),
        generated_probe_form=(
            "add or remove an exact #pragma push / dont_inline on / pop wrapper"
        ),
        keywords=("pragma", "dont_inline", "codegen", "inline", "wrapper"),
    ),
    TransformFamily(
        family_id="redundant_pointer_cast_elision",
        label="redundant pointer cast elision",
        mutator_keys=("elide_redundant_pointer_cast",),
        semantic_risk="medium",
        source_region_selector=(
            "non-callback pointer casts at call arguments and pointer assignments"
        ),
        expected_compiler_effect=(
            "change argument materialization and type-conversion spelling"
        ),
        generated_probe_form=(
            "elide a call-argument or assignment pointer cast when local types match"
        ),
        keywords=("pointer", "cast", "elision", "argument", "assignment"),
    ),
    TransformFamily(
        family_id="unused_trailing_parameter",
        label="unused trailing parameter",
        mutator_keys=(
            "remove_unused_trailing_parameter",
            "add_unused_trailing_parameter",
        ),
        semantic_risk="high",
        source_region_selector=(
            "unused trailing function parameters and corresponding call contract"
        ),
        expected_compiler_effect=(
            "change call contract and stack/register argument shape despite no body use"
        ),
        generated_probe_form=(
            "update a self-contained static signature plus all local direct call sites"
        ),
        keywords=("unused", "trailing", "parameter", "signature", "call-contract"),
    ),
    TransformFamily(
        family_id="outgoing_parameter_area_shape",
        label="outgoing parameter-area call shape",
        mutator_keys=("materialize_outgoing_parameter_area_call_args",),
        semantic_risk="medium",
        source_region_selector=(
            "high-arity call sites whose argument materialization can change "
            "the outgoing parameter area"
        ),
        expected_compiler_effect=(
            "change outgoing parameter area word-count by materializing "
            "selected call arguments as block-local temps"
        ),
        generated_probe_form=(
            "insert exact local temporaries immediately before one call site "
            "or remove immediate one-use argument locals back into calls"
        ),
        keywords=("outgoing", "parameter", "area", "call", "argument", "temp"),
    ),
    TransformFamily(
        family_id="vector_alias_type_shape",
        label="vector alias type shape",
        mutator_keys=("rewrite_vector_alias_type",),
        semantic_risk="medium",
        source_region_selector=(
            "equivalent vector/point alias types in parameters and local declarations"
        ),
        expected_compiler_effect=(
            "preserve field access codegen while matching API/prototype type shape"
        ),
        generated_probe_form=(
            "rewrite a local declaration type token between layout-identical aliases"
        ),
        keywords=("Vec3", "Point3d", "alias", "type", "prototype"),
    ),
    TransformFamily(
        family_id="minmax_macro_ternary_shape",
        label="min/max macro vs ternary shape",
        mutator_keys=("rewrite_minmax_macro_to_ternary",),
        semantic_risk="medium",
        source_region_selector=(
            "MIN/MAX-style macro calls and equivalent conditional expressions"
        ),
        expected_compiler_effect=(
            "change conditional expression materialization and duplicated operand lifetimes"
        ),
        generated_probe_form=(
            "rewrite simple MIN/MAX macro operands to an explicit ternary"
        ),
        keywords=("min", "max", "ternary", "macro", "conditional"),
    ),
    TransformFamily(
        family_id="assert_macro_expansion_shape",
        label="assert macro expansion shape",
        mutator_keys=("collapse_hsd_assert",),
        semantic_risk="medium",
        source_region_selector=(
            "HSD_ASSERT / HSD_ASSERTMSG / HSD_ASSERTREPORT calls and their "
            "hand-expanded __assert / OSReport equivalents"
        ),
        expected_compiler_effect=(
            "toggle between assert-macro and expanded report/assert spelling, "
            "changing string-pool and call materialization at the assert site"
        ),
        generated_probe_form=(
            "collapse explicit __assert NULL checks to HSD_ASSERTMSG when file "
            "basename and message are locally proven equivalent"
        ),
        keywords=("assert", "HSD_ASSERT", "__assert", "OSReport", "macro", "expansion"),
    ),
    TransformFamily(
        family_id="assignment_expression_temp_seed",
        label="assignment expression temp seed",
        mutator_keys=("fold_assignment_expression_seed",),
        semantic_risk="medium",
        source_region_selector=(
            "standalone seed assignments adjacent to a use, and chained "
            "assignments that reuse or seed a temp"
        ),
        expected_compiler_effect=(
            "embed an assignment as a sub-expression to seed or reuse a temp, "
            "shifting value/use boundaries and register allocation"
        ),
        generated_probe_form=(
            "fold a simple adjacent temp seed assignment into an if/while "
            "assignment expression"
        ),
        keywords=("assignment", "expression", "temp", "seed", "chained", "embedded"),
    ),
    TransformFamily(
        family_id="string_literal_data_blob_field_shape",
        label="string literal vs data blob field shape",
        mutator_keys=("replace_string_literal_with_data_field",),
        semantic_risk="high",
        source_region_selector=(
            "inline string literals and the equivalent named data-blob fields, "
            "symbols, or base+offset references that hold the same bytes"
        ),
        expected_compiler_effect=(
            "change string/data-pool materialization and relocation shape "
            "(string analog of global_float_literal_shape)"
        ),
        generated_probe_form=(
            "replace a string literal with a unique source-local initialized "
            "data field holding identical bytes"
        ),
        keywords=("string", "literal", "data", "blob", "OSReport", "symbol", "offset"),
    ),
    TransformFamily(
        family_id="raw_pointer_offset_struct_field_shape",
        label="raw pointer offset to struct field shape",
        mutator_keys=("rewrite_raw_pointer_offset_field",),
        semantic_risk="high",
        source_region_selector=(
            "raw byte-offset pointer-cast loads/stores and typed pointer-cast "
            "overlays with a recovered struct/bitfield field map"
        ),
        expected_compiler_effect=(
            "replace byte-offset cast addressing with typed struct field / "
            "bitfield member access"
        ),
        generated_probe_form=(
            "rewrite a byte-offset pointer cast to a struct field when local "
            "layout proves the offset and type exactly"
        ),
        keywords=("raw", "offset", "cast", "struct", "field", "bitfield", "overlay"),
    ),
    TransformFamily(
        family_id="comma_operator_noop_expression_shape",
        label="comma operator no-op expression shape",
        mutator_keys=("wrap_comma_noop_assignment_rhs",),
        semantic_risk="low",
        source_region_selector=(
            "expressions that can carry a no-op comma operand, e.g. (0, expr)"
        ),
        expected_compiler_effect=(
            "introduce a no-op comma operand to perturb evaluation order and "
            "register allocation"
        ),
        generated_probe_form=(
            "wrap a simple assignment RHS in a no-op comma expression"
        ),
        keywords=("comma", "operator", "noop", "no-op", "expression", "sequence"),
    ),
    TransformFamily(
        family_id="numeric_cast_shape",
        label="numeric cast insert/elide shape",
        mutator_keys=("elide_numeric_cast",),
        semantic_risk="medium",
        source_region_selector=(
            "non-pointer numeric casts at operands, call arguments, and "
            "assignments (int/float width and signedness)"
        ),
        expected_compiler_effect=(
            "insert or elide a numeric cast to steer int/float conversion and "
            "sign-extension codegen"
        ),
        generated_probe_form=(
            "elide a redundant call-argument numeric cast when a source-local "
            "prototype proves the same formal type"
        ),
        keywords=("numeric", "cast", "float", "int", "unsigned", "conversion"),
    ),
    TransformFamily(
        family_id="void_to_value_return_shape",
        label="void to value return shape",
        mutator_keys=("return_tail_call_value",),
        semantic_risk="high",
        source_region_selector=(
            "void functions whose return type can widen to forward a tail call "
            "result or return an existing live value"
        ),
        expected_compiler_effect=(
            "change the return-type contract and epilogue/result-register codegen "
            "without altering side effects"
        ),
        generated_probe_form=(
            "widen a static void tail-call wrapper to return a locally proven "
            "scalar helper result"
        ),
        keywords=("return", "void", "value", "tail-call", "forward", "contract"),
    ),
    TransformFamily(
        family_id="global_pointer_alias_shape",
        label="global pointer alias shape",
        mutator_keys=("introduce_global_pointer_alias",),
        semantic_risk="medium",
        source_region_selector=(
            "direct global or global-subobject member accesses that can be "
            "routed through a typed local pointer alias to the base"
        ),
        expected_compiler_effect=(
            "cache a global base address in a register and change member "
            "addressing codegen"
        ),
        generated_probe_form=(
            "insert a typed local pointer alias for a visible global object and "
            "route repeated member accesses through it"
        ),
        keywords=("global", "pointer", "alias", "base", "member", "indirection"),
    ),
    TransformFamily(
        family_id="empty_do_while_barrier",
        label="empty do/while no-op barrier",
        mutator_keys=("insert_empty_do_while_barrier",),
        semantic_risk="low",
        source_region_selector=(
            "statement boundaries that can carry an empty do { } while (0) or "
            "equivalent no-op statement barrier"
        ),
        expected_compiler_effect=(
            "insert or remove a no-op statement barrier to perturb scheduling "
            "and register allocation"
        ),
        generated_probe_form=(
            "insert an empty do/while no-op barrier between simple statements"
        ),
        keywords=("empty", "do-while", "barrier", "noop", "no-op", "self-assignment"),
    ),
    TransformFamily(
        family_id="scheduler_order_source_realizer",
        label="scheduler-order source realizer",
        mutator_keys=(
            "scheduler_anchor_iv_init_before_bias",
            "scheduler_split_float_cast_temp",
            "scheduler_empty_barrier_before_float_cast",
        ),
        semantic_risk="low",
        source_region_selector="explicit scheduler-order target source_region.contains window",
        expected_compiler_effect=(
            "perturb source statement boundaries near a two-instruction scheduler-order target"
        ),
        generated_probe_form="bounded exact-span scheduler-order source probes",
        keywords=("scheduler", "order", "source", "realizer", "mixed-opcode"),
    ),
    TransformFamily(
        family_id="switch_case_order_default_shape",
        label="switch case order / default shape",
        mutator_keys=("swap_simple_switch_cases",),
        semantic_risk="medium",
        source_region_selector=(
            "switch statements with reorderable independent case arms or an "
            "addable/removable explicit default arm"
        ),
        expected_compiler_effect=(
            "reshape switch dispatch (jump-table vs compare chain) by reordering "
            "arms or materializing a default"
        ),
        generated_probe_form=(
            "swap adjacent self-contained switch arms ending in break"
        ),
        keywords=("switch", "case", "default", "order", "dispatch", "jump-table"),
    ),
)


_FAMILY_BY_ID = {family.family_id: family for family in DEFAULT_TRANSFORM_FAMILIES}


_FAMILY_IDS_BY_MUTATOR: dict[str, tuple[str, ...]] = {}


for _family in DEFAULT_TRANSFORM_FAMILIES:
    for _mutator_key in _family.mutator_keys:
        _FAMILY_IDS_BY_MUTATOR.setdefault(_mutator_key, ())
        _FAMILY_IDS_BY_MUTATOR[_mutator_key] = (
            *_FAMILY_IDS_BY_MUTATOR[_mutator_key],
            _family.family_id,
        )


_MNDIAGRAM_COLORING_TARGETS = frozenset({
    "mnDiagram2_Create",
    "mnDiagram2_GetRankedFighter",
    "mnDiagram3_80245BA4",
    "mnDiagram_8024227C",
    "mnDiagram2_GetAggregatedFighterRank",
})


def _assignment_labels(force_phys: Mapping[int, int]) -> tuple[str, ...]:
    return tuple(f"ig{ig}->r{phys}" for ig, phys in sorted(force_phys.items()))


def _cluster_assignments(
    force_phys: Mapping[int, int],
    virtuals: Iterable[int],
) -> tuple[str, ...]:
    return tuple(
        f"ig{ig}->r{force_phys[ig]}"
        for ig in virtuals
        if ig in force_phys
    )


def _families_for_clusters(clusters: tuple[TransformCluster, ...]) -> tuple[TransformFamily, ...]:
    wanted = {family_id for cluster in clusters for family_id in cluster.family_ids}
    return tuple(family for family in DEFAULT_TRANSFORM_FAMILIES if family.family_id in wanted)


def _is_mndiagram_coloring_target(
    function: str,
    unit: str,
    force_phys: Mapping[int, int],
) -> bool:
    if not force_phys:
        return False
    if function in _MNDIAGRAM_COLORING_TARGETS:
        return True
    return function.startswith("mnDiagram") and "/mn/" in f"/{unit}/"


def plan_transform_experiments(
    *,
    function: str,
    unit: str,
    force_phys: Mapping[int, int],
) -> TransformExperimentPlan:
    """Map a directed diagnostic proof vector to transform-family clusters."""

    if function == "ftCo_8009E7B4" and ({58, 44, 42} & set(force_phys)):
        early = TransformCluster(
            cluster_id="early_flag_reload",
            label="early flag/reload temps",
            source_regions=(
                "early flag/reload block",
                "boolean flag temp and reload boundary",
                "early volatile call-adjacent temps",
            ),
            target_assignments=_cluster_assignments(force_phys, (58, 44, 42)),
            family_ids=(
                "condition_split_merge",
                "reload_branch_scope",
                "declaration_use_boundary",
                "lifetime_preserve_shorten",
            ),
            rationale=(
                "Move the early volatile-register proof holders as one source "
                "shape rather than as isolated virtual nudges."
            ),
        )
        late = TransformCluster(
            cluster_id="late_field_loop_tree",
            label="late x594_b4/x594_b3 loop IV/tree-pointer swaps",
            source_regions=(
                "x594_b4/x594_b3 field-bit tests",
                "loop IV/tree-pointer lifetime boundary",
                "late callee-save holder overlap",
            ),
            target_assignments=_cluster_assignments(force_phys, (35, 56, 34)),
            family_ids=(
                "condition_split_merge",
                "loop_index_pointer_walk_split",
                "reload_branch_scope",
                "lifetime_preserve_shorten",
                "counter_type_shape",
            ),
            rationale=(
                "Probe field-bit predicates together with loop-index and "
                "tree-pointer lifetime changes."
            ),
        )
        clusters = tuple(
            cluster for cluster in (early, late) if cluster.target_assignments
        )
    elif function == "mnDiagram2_GetRankedFighter":
        ranked_cluster = TransformCluster(
            cluster_id="ranked_cursor_iv_unification",
            label="ranked fighter cursor/value IV unification",
            source_regions=(
                "selection-sort maxIdx update loop",
                "rank pointer tail return",
            ),
            target_assignments=("cursor-value accumulator",),
            family_ids=("ranked_cursor_iv_unification",),
            rationale=(
                "Probe Class D source shapes that replace indexed reads "
                "with the existing cursor/value accumulator."
            ),
        )
        if force_phys:
            coloring_cluster = TransformCluster(
                cluster_id="mndiagram_coloring_register_steering",
                label="mndiagram register-coloring steering",
                source_regions=(
                    "adjacent local declaration order",
                    "local initializer and counter-width boundaries",
                    "loop-counter and same-type lifetime reuse windows",
                ),
                target_assignments=_assignment_labels(force_phys),
                family_ids=("coloring_register_steering",),
                rationale=(
                    "Probe source-level register-coloring levers for the "
                    "mndiagram force-phys residual class."
                ),
            )
            clusters = (ranked_cluster, coloring_cluster)
        else:
            clusters = (ranked_cluster,)
    elif _is_mndiagram_coloring_target(function, unit, force_phys):
        clusters = (
            TransformCluster(
                cluster_id="mndiagram_coloring_register_steering",
                label="mndiagram register-coloring steering",
                source_regions=(
                    "adjacent local declaration order",
                    "local initializer and counter-width boundaries",
                    "loop-counter and same-type lifetime reuse windows",
                ),
                target_assignments=_assignment_labels(force_phys),
                family_ids=("coloring_register_steering",),
                rationale=(
                    "Probe source-level register-coloring levers for the "
                    "mndiagram force-phys residual class."
                ),
            ),
        )
    else:
        clusters = (
            TransformCluster(
                cluster_id="generic_allocator_shape",
                label="generic allocator-shape source cluster",
                source_regions=(
                    "proof-vector source region unresolved",
                    "run diagnose/reanchor to refine source spans",
                ),
                target_assignments=_assignment_labels(force_phys),
                family_ids=(
                    "declaration_use_boundary",
                    "independent_statement_order",
                    "condition_split_merge",
                    "reload_branch_scope",
                    "lifetime_preserve_shorten",
                    "loop_index_pointer_walk_split",
                    "helper_shape",
                    "same_type_local_lifetime_reuse",
                    "function_codegen_pragma_shape",
                    "explicit_zero_return",
                    "named_zero_local_shape",
                    "redundant_pointer_cast_elision",
                    "callback_cast_elision",
                    "unused_trailing_parameter",
                    "vector_alias_type_shape",
                    "comma_operator_noop_expression_shape",
                    "empty_do_while_barrier",
                    "assignment_expression_temp_seed",
                    "numeric_cast_shape",
                    "bool_int_accumulator_shape",
                    "global_float_literal_shape",
                    "fp_subtraction_operand_reassociation",
                    "data_table_indirection_shape",
                    "raw_index_struct_field_shape",
                    "zero_compare_logical_not",
                    "abs_macro_expression_fold",
                    "minmax_macro_ternary_shape",
                    "switch_case_order_default_shape",
                    "assert_macro_expansion_shape",
                    "void_to_value_return_shape",
                    "string_literal_data_blob_field_shape",
                    "global_pointer_alias_shape",
                    "raw_pointer_offset_struct_field_shape",
                ),
                rationale="Bounded fallback when the diagnostic lacks a named source cluster.",
            ),
        )

    return TransformExperimentPlan(
        function=function,
        unit=unit,
        source_file=_source_file_for_unit(unit),
        clusters=clusters,
        families=_families_for_clusters(clusters),
    )
