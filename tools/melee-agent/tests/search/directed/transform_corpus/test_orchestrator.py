"""Tests for the probe-generation orchestrator (transform_corpus.orchestrator)."""
from __future__ import annotations

import pytest

from src.search.directed.anchors import Anchor
from src.search.directed.mutators import apply_mutator
from src.search.directed.transform_corpus import (
    DEFAULT_TRANSFORM_FAMILIES,
    generate_transform_probe_report,
    generate_transform_probes,
    plan_transform_experiments,
)
from src.search.directed.transform_probe_adapter import transform_probe_key
from src.mwcc_debug.source_shape import CandidatePatch


def test_generate_transform_probes_materializes_source_edits() -> None:
    source = (
        "void ftCo_8009E7B4(void) {\n"
        "    if (flag) {\n"
        "        reload = 1;\n"
        "    } else {\n"
        "        if (kind != 0) {\n"
        "            reload = 0;\n"
        "        }\n"
        "    }\n"
        "    if (fp->x594_b4) {\n"
        "        s32 i;\n"
        "        for (i = 0; i < n; i++) {\n"
        "            sink(i);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="ftCo_8009E7B4",
        unit="melee/ft/ftcommon",
        force_phys={58: 4, 35: 29},
        max_per_family=2,
    )

    assert probes
    by_family = {probe.family_id: probe for probe in probes}
    assert "condition_split_merge" in by_family
    assert "} else if (kind != 0) {" in by_family["condition_split_merge"].candidate_text
    assert "lifetime_preserve_shorten" in by_family
    assert by_family["lifetime_preserve_shorten"].source_region
    assert all(probe.target_assignments for probe in probes)


def test_empty_do_while_barrier_skips_pointer_declaration_block() -> None:
    source = (
        "typedef struct Obj Obj;\n"
        "void target(Obj* gobj) {\n"
        "    Obj* data = gobj;\n"
        "    Obj* next = data;\n"
        "    int count = 0;\n"
        "    process(next);\n"
        "    update(count);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        max_per_family=1,
    )
    barrier = next(
        probe for probe in probes if probe.family_id == "empty_do_while_barrier"
    )

    assert "Obj* data = gobj;\n    do {" not in barrier.candidate_text
    assert "Obj* next = data;\n    do {" not in barrier.candidate_text
    assert "int count = 0;\n    do {" not in barrier.candidate_text
    assert "process(next);\n    do {" in barrier.candidate_text


def test_generate_transform_probes_node_set_delta_skips_recursive_combos(
    monkeypatch,
) -> None:
    import src.mwcc_debug.node_set_split as node_set_split

    source = (
        "typedef struct Entry { int stat_value; } Entry;\n"
        "void mnDiagram2_Create(Entry* entries, int i) {\n"
        "    int out;\n"
        "    out = entries[i].stat_value;\n"
        "    sink(out);\n"
        "}\n"
    )
    delta = {
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 42,
                "current_register": "r29",
                "desired_registers": ["r27"],
                "source": {
                    "kind": "field-load",
                    "expression": "entries[i].stat_value",
                },
            }
        ],
    }

    def fail_combo_generation(*_args, **_kwargs):
        raise AssertionError("plan-transform node-set probes must be bounded")

    monkeypatch.setattr(
        node_set_split,
        "_append_combo_patches",
        fail_combo_generation,
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={42: 27},
        node_set_delta=delta,
        max_per_family=2,
    )

    assert probes
    assert any(
        probe.mutator_key == "steer_node_set_delta_introduce_binding_split"
        for probe in probes
    )


def test_generate_transform_probes_node_set_delta_default_is_bounded(
    monkeypatch,
) -> None:
    import src.search.directed.transform_corpus.orchestrator as orchestrator

    source = (
        "typedef struct Entry { int stat_value; } Entry;\n"
        "void mnDiagram2_Create(Entry* entries, int i) {\n"
        "    int out;\n"
        "    out = entries[i].stat_value;\n"
        "    sink(out);\n"
        "}\n"
    )
    delta = {
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 42,
                "current_register": "r29",
                "desired_registers": ["r27"],
                "source": {
                    "kind": "field-load",
                    "expression": "entries[i].stat_value",
                },
            }
        ],
    }

    def fail_unrelated_anchor_scan(*_args, **_kwargs):
        raise AssertionError("node-set-delta default planning must not scan unrelated anchors")

    monkeypatch.setattr(
        orchestrator,
        "_iter_concrete_register_steering_body_anchors",
        fail_unrelated_anchor_scan,
    )
    monkeypatch.setattr(
        orchestrator,
        "_iter_register_steering_body_anchors",
        fail_unrelated_anchor_scan,
    )
    monkeypatch.setattr(
        orchestrator,
        "_iter_full_source_anchors",
        fail_unrelated_anchor_scan,
    )
    monkeypatch.setattr(
        orchestrator,
        "iter_source_shape_anchors",
        fail_unrelated_anchor_scan,
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={42: 27},
        node_set_delta=delta,
        max_per_family=2,
    )

    assert probes
    assert {probe.family_id for probe in probes} == {"coloring_register_steering"}
    assert all(
        probe.mutator_key.startswith("steer_node_set_delta")
        for probe in probes
    )


def test_generate_transform_probes_only_uses_target_function_body() -> None:
    source = (
        "void helper(void) {\n"
        "    if (a) {\n"
        "        x = 1;\n"
        "    } else if (b) {\n"
        "        x = 2;\n"
        "    }\n"
        "}\n"
        "void ftCo_8009E7B4(void) {\n"
        "    if (fp->x594_b4) {\n"
        "        s32 i;\n"
        "        for (i = 0; i < n; i++) {\n"
        "            sink(i);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="ftCo_8009E7B4",
        unit="melee/ft/ftcommon",
        force_phys={58: 4, 35: 29},
        max_per_family=1,
    )

    assert probes
    assert all(probe.span[0] > source.index("void ftCo_8009E7B4") for probe in probes)
    assert "condition_split_merge" not in {probe.family_id for probe in probes}


def test_generate_transform_probes_returns_empty_when_target_body_is_absent() -> None:
    source = (
        "void helper(void) {\n"
        "    if (a) {\n"
        "        x = 1;\n"
        "    } else if (b) {\n"
        "        x = 2;\n"
        "    }\n"
        "}\n"
        "/// #ftCo_8009E7B4\n"
    )

    probes = generate_transform_probes(
        source,
        function="ftCo_8009E7B4",
        unit="melee/ft/ftcommon",
        force_phys={58: 4, 35: 29},
    )

    assert probes == ()


def _fresh_callarg_local_diagnostic_source(
    *,
    duplicate_assignment: bool = False,
) -> str:
    duplicate = "        digitf = (f32) digit;\n" if duplicate_assignment else ""
    return (
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(HSD_JObj* jobj, f32 y_spacing, f32 y_offset, "
        "u8 value, u8 row) {\n"
        "    int i;\n"
        "    int digit;\n"
        "    int digit_count;\n"
        "    f32 rowf;\n"
        "    f32 digitf;\n"
        "    f32 col_offset;\n"
        "    f32 col_offset_product_fpr;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    f32 row_offset_adj_owner_fpr;\n"
        "    f32 col_cast_owner_fpr;\n"
        "    col_offset_product_fpr = y_spacing * col_cast_owner_fpr;\n"
        "    col_offset = col_offset_product_fpr;\n"
        "    digit_count = mn_GetDigitCount(value);\n"
        "    rowf = (f32) row;\n"
        "    row_offset *= rowf;\n"
        "    row_offset_adj_owner_fpr = row_offset - 0.4f;\n"
        "    row_offset_adj = row_offset_adj_owner_fpr;\n"
        "    for (i = 0; i < digit_count; i++) {\n"
        "        digit = mn_GetDigitAt(value, i);\n"
        f"{duplicate}"
        "        digitf = (f32) digit;\n"
        "        HSD_JObjReqAnimAll(jobj, digitf);\n"
        "        HSD_JObjAnimAll(jobj);\n"
        "    }\n"
        "    HSD_JObjSetTranslateY(jobj, row_offset_adj);\n"
        "}\n"
    )


def _callarg_local_structural_diag(source: str):
    report = generate_transform_probe_report(
        source,
        function="mnDiagram_DrawCellNumber",
        unit="melee/mn/mndiagram",
        force_phys={33: 26, 35: 26, 40: 28},
        families=("callarg_local_structural_repair",),
        max_per_family=8,
    )
    return next(
        diag for diag in report.family_diagnostics
        if diag.family_id == "callarg_local_structural_repair"
    )


def test_callarg_local_structural_diagnostics_report_fresh_existing_state() -> None:
    diag = _callarg_local_structural_diag(_fresh_callarg_local_diagnostic_source())

    assert diag.materialized_count > 0
    assert diag.no_probe_reason is None
    assert diag.matcher_diagnostics["has_existing_fresh_callarg_local"] is True
    assert diag.matcher_diagnostics["rowf_locals"] == ["rowf"]
    assert diag.matcher_diagnostics["call_arg_locals"] == ["digitf"]
    assert diag.matcher_diagnostics["call_arg_local_kinds"] == ["fresh-existing"]
    assert "source-pattern-not-found" not in (
        diag.matcher_diagnostics["rejection_reasons"]
    )


def test_callarg_local_structural_diagnostics_report_ambiguous_fresh_assignment() -> None:
    diag = _callarg_local_structural_diag(
        _fresh_callarg_local_diagnostic_source(duplicate_assignment=True)
    )

    assert diag.materialized_count == 0
    assert diag.no_probe_reason == "ambiguous-callarg-assignment"
    assert diag.matcher_diagnostics["has_existing_fresh_callarg_local"] is True
    assert "ambiguous-callarg-assignment" in (
        diag.matcher_diagnostics["rejection_reasons"]
    )
    assert "source-pattern-not-found" not in (
        diag.matcher_diagnostics["rejection_reasons"]
    )


def test_generate_transform_probes_materializes_explicit_zero_return_for_int_wrapper() -> None:
    source = (
        "int un_803004B4(int arg0) {\n"
        "    un_802FFD94(arg0, &un_803FA8E8, fn_802FFE6C);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="un_803004B4",
        unit="melee/if/soundtest",
        force_phys={1: 3},
    )

    explicit = next(
        probe for probe in probes if probe.family_id == "explicit_zero_return"
    )
    assert explicit.mutator_key == "add_explicit_zero_return"
    assert "    return 0;\n}" in explicit.candidate_text


def test_generate_transform_probes_skips_explicit_zero_return_for_void_wrapper() -> None:
    source = (
        "void un_803004B4(int arg0) {\n"
        "    un_802FFD94(arg0, &un_803FA8E8, fn_802FFE6C);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="un_803004B4",
        unit="melee/if/soundtest",
        force_phys={1: 3},
    )

    assert "explicit_zero_return" not in {probe.family_id for probe in probes}


def _mixed_pcode_fpr_lifetime_source() -> str:
    return (
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(HSD_JObj* jobj, f32 y_offset, u8 row, u8 digit) {\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    f32 rowf;\n"
        "    f32 row_offset_adj_owner_fpr;\n"
        "    row_offset = y_offset;\n"
        "    rowf = (f32) row;\n"
        "    row_offset *= rowf;\n"
        "    row_offset_adj_owner_fpr = row_offset - 0.4f;\n"
        "    row_offset_adj = row_offset_adj_owner_fpr;\n"
        "    for (digit = digit; digit < 10; digit++) {\n"
        "        rowf = (f32) digit;\n"
        "        HSD_JObjReqAnimAll(jobj, rowf);\n"
        "        if (row < 10) {\n"
        "            HSD_JObjSetTranslateY(jobj, row_offset);\n"
        "        } else {\n"
        "            HSD_JObjSetTranslateY(jobj, row_offset_adj);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def test_generate_transform_probes_materializes_mixed_pcode_fpr_without_force_phys() -> None:
    probes = generate_transform_probes(
        _mixed_pcode_fpr_lifetime_source(),
        function="mnDiagram_DrawCellNumber",
        unit="melee/mn/mndiagram",
        force_phys={},
        families=("mixed_pcode_fpr_lifetime_pressure_repair",),
        max_per_family=8,
    )

    mixed = [
        probe for probe in probes
        if probe.family_id == "mixed_pcode_fpr_lifetime_pressure_repair"
    ]

    assert mixed
    assert {probe.mutator_key for probe in mixed} == {
        "steer_mixed_pcode_fpr_lifetime_pressure"
    }


@pytest.mark.parametrize(
    "family",
    (
        "pcode_only_fpr_callarg_temp_repair",
        "pcode_only_fpr_fsubs_cast_owner_repair",
    ),
)
def test_generate_transform_probes_requested_pcode_fpr_families_no_force_phys_do_not_crash(
    family: str,
) -> None:
    probes = generate_transform_probes(
        _mixed_pcode_fpr_lifetime_source(),
        function="mnDiagram_DrawCellNumber",
        unit="melee/mn/mndiagram",
        force_phys={},
        families=(family,),
        max_per_family=8,
    )

    assert isinstance(probes, tuple)


def test_generate_transform_probes_edits_requested_function_when_bodies_repeat() -> None:
    source = (
        "int helper(int arg0) {\n"
        "    repeated(arg0);\n"
        "}\n"
        "int un_803004B4(int arg0) {\n"
        "    repeated(arg0);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="un_803004B4",
        unit="melee/if/soundtest",
        force_phys={1: 3},
    )

    explicit = next(
        probe for probe in probes if probe.family_id == "explicit_zero_return"
    )
    assert explicit.candidate_text == (
        "int helper(int arg0) {\n"
        "    repeated(arg0);\n"
        "}\n"
        "int un_803004B4(int arg0) {\n"
        "    repeated(arg0);\n"
        "    return 0;\n"
        "}\n"
    )


def test_coloring_register_steering_case_c_key_is_directly_emitted() -> None:
    source = (
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(unsigned char row) {\n"
        "    f32 base;\n"
        "    f32 y_offset;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    rowf = (f32) row;\n"
        "    y_offset = HSD_JObjGetTranslationY(jobj2) - base;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    HSD_JObjSetTranslateY(jobj, row_offset);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_DrawCellNumber",
        unit="melee/mn/mndiagram",
        force_phys={39: 26, 33: 28},
        families=("coloring_register_steering",),
        max_per_family=32,
    )

    case_c = [
        probe for probe in probes
        if probe.mutator_key == "steer_fpr_case_c_temp_order"
    ]
    assert case_c
    assert {
        probe.payload["strategy"] for probe in case_c
    } >= {
        "fpr-case-c-left-operand-temp",
        "fpr-case-c-rhs-owner-temp",
        "fpr-case-c-product-owner-temp",
    }


def test_generate_transform_probes_materializes_mined_family_mutators() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "typedef double f64;\n"
        "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
        "typedef struct Gp { u8 pad[0xE0]; Vec3 scroll; } Gp;\n"
        "typedef struct State { int field; int other; } State;\n"
        "typedef struct Item Item;\n"
        "void it_8026F790(HSD_GObj* gobj, f32 angle);\n"
        "State lbl_80472D28;\n"
        "s32 fn_8017F0A0(Item* it);\n"
        "static struct { char report_format[32]; } grIm_803E4800 = { \"loaded stage %d\\n\" };\n"
        "static void mined(Gp* gp, Item* it) {\n"
        "    item = HSD_GObj_Entities->items;\n"
        "    if (item != NULL) {\n"
        "        use(item);\n"
        "    }\n"
        "    jobj = (HSD_JObj*) HSD_GObjGetHSDObj(gobj);\n"
        "    process(cur);\n"
        "    update(cur);\n"
        "    it_8026F790(gobj, (f32) angle);\n"
        "    switch (kind) {\n"
        "    case 7:\n"
        "        b();\n"
        "        break;\n"
        "    case 9:\n"
        "        c();\n"
        "        break;\n"
        "    }\n"
        "    if (archive == NULL)\n"
        "        __assert(\"mined.c\", 0x617, \"0\");\n"
        "    OSReport(\"loaded stage %d\\n\", id);\n"
        "    lbl_80472D28.field = x;\n"
        "    use(lbl_80472D28.other);\n"
        "    *(Vec3*) ((u8*) gp + 0xE0) = scroll;\n"
        "    fn_8017F0A0(it);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mined",
        unit="melee/test/mined",
        force_phys={1: 3},
        max_per_family=1,
    )

    by_family = {probe.family_id: probe for probe in probes}
    expected_families = {
        "assert_macro_expansion_shape",
        "assignment_expression_temp_seed",
        "string_literal_data_blob_field_shape",
        "raw_pointer_offset_struct_field_shape",
        "comma_operator_noop_expression_shape",
        "numeric_cast_shape",
        "void_to_value_return_shape",
        "global_pointer_alias_shape",
        "empty_do_while_barrier",
        "switch_case_order_default_shape",
    }
    assert expected_families <= set(by_family)
    assert 'HSD_ASSERTMSG(0x617, archive, "0");' in by_family[
        "assert_macro_expansion_shape"
    ].candidate_text
    assert "if ((item = HSD_GObj_Entities->items) != NULL) {" in by_family[
        "assignment_expression_temp_seed"
    ].candidate_text
    assert "OSReport(grIm_803E4800.report_format, id);" in by_family[
        "string_literal_data_blob_field_shape"
    ].candidate_text
    assert "gp->scroll = scroll;" in by_family[
        "raw_pointer_offset_struct_field_shape"
    ].candidate_text
    assert " = (0, " in by_family[
        "comma_operator_noop_expression_shape"
    ].candidate_text
    assert "it_8026F790(gobj, angle);" in by_family[
        "numeric_cast_shape"
    ].candidate_text
    assert "static s32 mined(Gp* gp, Item* it)" in by_family[
        "void_to_value_return_shape"
    ].candidate_text
    assert "return fn_8017F0A0(it);" in by_family[
        "void_to_value_return_shape"
    ].candidate_text
    assert "State* lbl_80472D28_alias = &lbl_80472D28;" in by_family[
        "global_pointer_alias_shape"
    ].candidate_text
    assert "do {\n    } while (0);" in by_family[
        "empty_do_while_barrier"
    ].candidate_text
    assert by_family["switch_case_order_default_shape"].candidate_text.index(
        "    case 9:"
    ) < by_family["switch_case_order_default_shape"].candidate_text.index(
        "    case 7:"
    )


def test_generate_transform_probes_materializes_scalar_expression_mutators() -> None:
    source = (
        "typedef int s32;\n"
        "typedef int bool;\n"
        "void target(void) {\n"
        "    bool test;\n"
        "    test = first(gobj);\n"
        "    if (test != false) {\n"
        "        use(gobj);\n"
        "    }\n"
        "    test |= second(gobj);\n"
        "    if (call(gobj) == 0) {\n"
        "        return;\n"
        "    }\n"
        "    use((delta < 0.0F) ? -delta : delta);\n"
        "    clamped = MAX(value, limit);\n"
        "    return test;\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        max_per_family=1,
    )

    by_family = {probe.family_id: probe for probe in probes}
    assert "bool_int_accumulator_shape" in by_family
    assert by_family["bool_int_accumulator_shape"].mutator_key == "rewrite_bool_accumulator_as_int"
    assert "    s32 test;" in by_family["bool_int_accumulator_shape"].candidate_text
    assert "if (test != 0)" in by_family["bool_int_accumulator_shape"].candidate_text
    assert "zero_compare_logical_not" in by_family
    assert "if (!call(gobj))" in by_family["zero_compare_logical_not"].candidate_text
    assert "abs_macro_expression_fold" in by_family
    assert "use(ABS(delta));" in by_family["abs_macro_expression_fold"].candidate_text
    assert "minmax_macro_ternary_shape" in by_family
    assert "clamped = ((value) > (limit) ? (value) : (limit));" in by_family[
        "minmax_macro_ternary_shape"
    ].candidate_text


def test_scalar_expression_mutators_reject_duplicated_evaluation_risks() -> None:
    source = (
        "typedef int bool;\n"
        "void target(void) {\n"
        "    use((next() < 0) ? -next() : next());\n"
        "    use((values[i] < 0) ? -values[i] : values[i]);\n"
        "    clamped = MAX(next(), limit);\n"
        "    if ((value = next()) == 0) {\n"
        "        return;\n"
        "    }\n"
        "    if (ready && flag == 0) {\n"
        "        return;\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        max_per_family=1,
    )

    rejected = {
        "abs_macro_expression_fold",
        "minmax_macro_ternary_shape",
        "zero_compare_logical_not",
    }
    assert rejected.isdisjoint({probe.family_id for probe in probes})


def test_scalar_expression_mutators_do_not_rewrite_literals_or_comments() -> None:
    source = (
        "void target(void) {\n"
        "    OSReport(\"MAX(value, limit)\\n\");\n"
        "    // use((delta < 0.0F) ? -delta : delta);\n"
        "    /* clamped = MAX(value, limit); */\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        families=("abs_macro_expression_fold", "minmax_macro_ternary_shape"),
        max_per_family=1,
    )

    assert {
        "abs_macro_expression_fold",
        "minmax_macro_ternary_shape",
    }.isdisjoint({probe.family_id for probe in probes})


def test_zero_compare_accepts_member_chain_predicate() -> None:
    source = (
        "void target(void) {\n"
        "    if (fp->flag == 0) {\n"
        "        return;\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        families=("zero_compare_logical_not",),
        max_per_family=1,
    )

    zero_compare = next(
        probe for probe in probes if probe.family_id == "zero_compare_logical_not"
    )
    assert "if (!fp->flag)" in zero_compare.candidate_text


def test_bool_accumulator_rejects_unsafe_or_incomplete_shapes() -> None:
    source = (
        "typedef int bool;\n"
        "void target(void) {\n"
        "    bool address_taken;\n"
        "    address_taken = first(gobj);\n"
        "    use(&address_taken);\n"
        "    address_taken |= second(gobj);\n"
        "    return address_taken;\n"
        "}\n"
        "void missing_or(void) {\n"
        "    bool test;\n"
        "    test = first(gobj);\n"
        "    return test;\n"
        "}\n"
        "void missing_return(void) {\n"
        "    bool test;\n"
        "    test = first(gobj);\n"
        "    test |= second(gobj);\n"
        "}\n"
    )

    for function in ("target", "missing_or", "missing_return"):
        probes = generate_transform_probes(
            source,
            function=function,
            unit="melee/test/target",
            force_phys={1: 3},
            families=("bool_int_accumulator_shape",),
            max_per_family=1,
        )
        assert "bool_int_accumulator_shape" not in {probe.family_id for probe in probes}


def test_generate_transform_probes_rejects_unsafe_mined_shapes() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
        "typedef struct Gp { u8 pad[0xE4]; Vec3 scroll; } Gp;\n"
        "void cb(void (*callback)(HSD_GObj*));\n"
        "s32 helper(void);\n"
        "static void unsafe(Gp* gp) {\n"
        "    static struct { char report_format[8]; } first = { \"dupe\\n\" };\n"
        "    static struct { char report_format[8]; } second = { \"dupe\\n\" };\n"
        "    item = call_with_side_effect();\n"
        "    if (item != NULL) {\n"
        "        use(item);\n"
        "    }\n"
        "case_label:\n"
        "    process(cur);\n"
        "    update(cur);\n"
        "    cb((void (*)(HSD_GObj*)) callback);\n"
        "    switch (kind) {\n"
        "    case 7:\n"
        "        int local;\n"
        "        break;\n"
        "    case 9:\n"
        "        c();\n"
        "        break;\n"
        "    }\n"
        "    if (archive != NULL)\n"
        "        __assert(\"granime.c\", 0x617, \"0\");\n"
        "    OSReport(\"dupe\\n\", id);\n"
        "    puts(\"dupe\\n\");\n"
        "    *(Vec3*) ((u8*) gp + 0xE0) = scroll;\n"
        "    helper();\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="unsafe",
        unit="melee/test/unsafe",
        force_phys={1: 3},
        max_per_family=1,
    )

    rejected = {
        "assignment_expression_temp_seed",
        "numeric_cast_shape",
        "switch_case_order_default_shape",
        "assert_macro_expansion_shape",
        "string_literal_data_blob_field_shape",
        "raw_pointer_offset_struct_field_shape",
        "void_to_value_return_shape",
    }
    assert rejected.isdisjoint({probe.family_id for probe in probes})


def _scheduler_order_target() -> dict:
    return {
        "kind": "scheduler-order-target",
        "function": "mnDiagram3_8024714C",
        "target_first": {
            "opcode": "mr",
            "operands_contains": "r30,r31",
            "code_offset": "0x124",
        },
        "target_second": {
            "opcode": "lfd",
            "operands_contains": "mnDiagram3_804DC000",
            "code_offset": "0x120",
        },
        "source_region": {
            "contains": [
                "stat_idx = scroll;",
                "i = 0;",
                "do {",
                "f32 fi = (f32) i;",
            ],
        },
    }


def _scheduler_order_source(*, duplicate_region: bool = False) -> str:
    region = (
        "    stat_idx = scroll;\n"
        "    i = 0;\n"
        "    do {\n"
        "        f32 fi = (f32) i;\n"
        "        values[i] = fi + bias;\n"
        "        i++;\n"
        "    } while (i < limit);\n"
    )
    duplicate = region if duplicate_region else ""
    return (
        "typedef float f32;\n"
        "void mnDiagram3_8024714C(int scroll, int limit, f32 bias, f32* values) {\n"
        "    int stat_idx;\n"
        "    int i;\n"
        f"{duplicate}"
        f"{region}"
        "}\n"
    )


def test_scheduler_order_source_realizer_emits_three_probes_in_order() -> None:
    probes = [
        probe
        for probe in generate_transform_probes(
            _scheduler_order_source(),
            function="mnDiagram3_8024714C",
            unit="melee/mn/mndiagram3",
            force_phys={},
            families=("scheduler_order_source_realizer",),
            scheduler_order_target=_scheduler_order_target(),
        )
        if probe.family_id == "scheduler_order_source_realizer"
    ]

    assert [probe.family_id for probe in probes] == [
        "scheduler_order_source_realizer",
        "scheduler_order_source_realizer",
        "scheduler_order_source_realizer",
    ]
    assert [probe.mutator_key for probe in probes] == [
        "scheduler_anchor_iv_init_before_bias",
        "scheduler_split_float_cast_temp",
        "scheduler_empty_barrier_before_float_cast",
    ]
    assert [probe.payload["span_text"] for probe in probes] == [
        "    i = 0;\n",
        "        f32 fi = (f32) i;\n",
        "        f32 fi = (f32) i;\n",
    ]
    assert [probe.target_assignments for probe in probes] == [
        ("mr before lfd",),
        ("mr before lfd",),
        ("mr before lfd",),
    ]
    assert "do { } while (0);" in probes[2].candidate_text

    capped = [
        probe
        for probe in generate_transform_probes(
            _scheduler_order_source(),
            function="mnDiagram3_8024714C",
            unit="melee/mn/mndiagram3",
            force_phys={},
            families=("scheduler_order_source_realizer",),
            scheduler_order_target=_scheduler_order_target(),
            max_per_family=1,
        )
        if probe.family_id == "scheduler_order_source_realizer"
    ]
    assert [probe.mutator_key for probe in capped] == [
        "scheduler_anchor_iv_init_before_bias"
    ]


def test_scheduler_order_source_realizer_abstains_when_source_region_not_unique() -> None:
    probes = [
        probe
        for probe in generate_transform_probes(
            _scheduler_order_source(duplicate_region=True),
            function="mnDiagram3_8024714C",
            unit="melee/mn/mndiagram3",
            force_phys={},
            families=("scheduler_order_source_realizer",),
            scheduler_order_target=_scheduler_order_target(),
        )
        if probe.family_id == "scheduler_order_source_realizer"
    ]

    assert probes == []
