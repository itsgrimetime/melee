from __future__ import annotations

from src.mwcc_debug.pressure_explorer import LifetimeLayoutProbe
from src.search.directed.transform_corpus.orchestrator import (
    RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID,
    RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID,
    RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID,
    _lifetime_layout_probe_to_transform_probe,
    generate_transform_probe_report,
)
from src.search.directed.transform_corpus.registry import plan_transform_experiments


def test_retained_case_c_window_order_continuation_converts_lifetime_probe() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int i) {\n"
        "    u8 temp;\n"
        "    temp = dst[i];\n"
        "}\n"
    )
    candidate = source.replace(
        "    temp = dst[i];\n",
        "    int window_order_dst_i_probe;\n"
        "    window_order_dst_i_probe = i;\n"
        "    temp = dst[window_order_dst_i_probe];\n",
    )
    ranked_candidate = {
        "kind": "indexed-byte-address-temp",
        "array_base": "dst",
        "index_expr": "i",
        "span_text": "temp = dst[i];",
    }
    lifetime_probe = LifetimeLayoutProbe(
        label="window-order-ranked-indexed-byte-ig44-before-0",
        operator="window-order-source-steering",
        description="Materialize ranked indexed-byte owner span.",
        source_text=candidate,
        provenance={
            "kind": "window-order-ranked-indexed-byte-source-probe",
            "lead": {
                "target_ig": 44,
                "order_move": ["before", "force-phys"],
                "perturbed_reg": 25,
            },
            "source_attribution": {
                "kind": "implicit-temp",
                "expression": "add r44,r52,r64",
            },
            "synthetic_source_probe": {
                "ranked_indexed_byte_source_candidates": [ranked_candidate],
            },
            "ranked_indexed_byte_source_candidate": ranked_candidate,
        },
    )
    plan = plan_transform_experiments(
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
    )

    probe = _lifetime_layout_probe_to_transform_probe(
        lifetime_probe,
        family_id=RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID,
        index=0,
        source_text=source,
        plan=plan,
        force_phys={34: 27, 44: 25},
    )

    assert probe.family_id == RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID
    assert probe.probe_id == "retained_gpr_case_c_window_order_continuation@0"
    assert probe.candidate_text != source
    assert probe.payload["window_order_label"] == lifetime_probe.label
    assert probe.payload["lead_target_ig"] == 44
    assert probe.payload["protected_targets"] == {"34": 27}
    assert probe.payload["attempted_targets"] == {"44": 25}
    assert probe.payload["source_attribution"]["kind"] == "implicit-temp"
    assert probe.payload["synthetic_source_probe"][
        "ranked_indexed_byte_source_candidates"
    ] == [ranked_candidate]
    assert probe.payload["ranked_indexed_byte_source_candidate"] == ranked_candidate
    assert "window_order_dst_i_probe" in probe.payload["source_diff"]


def test_retained_case_c_window_order_continuation_converts_end_pointer_probe(
) -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, u8* common_source_r39_probe) {\n"
        "    int i;\n"
        "    u8* ll_probe_iter_0 = common_source_r39_probe;\n"
        "    u8* ll_probe_end_0 = dst + 0x78;\n"
        "    for (i = 0; ll_probe_iter_0 < ll_probe_end_0; i++, ll_probe_iter_0++) {\n"
        "        *ll_probe_iter_0 = dst[i];\n"
        "    }\n"
        "}\n"
    )
    candidate = source.replace(
        "    u8* ll_probe_end_0 = dst + 0x78;\n",
        "    u8* ll_probe_end_0;\n"
        "    ll_probe_end_0 = dst + 0x78;\n",
    )
    ranked_candidate = {
        "kind": "pointer-loop-end-pointer",
        "end_local": "ll_probe_end_0",
        "iter_local": "ll_probe_iter_0",
        "owner_assignment_text": "u8* ll_probe_end_0 = dst + 0x78;",
        "loop_header_text": (
            "for (i = 0; ll_probe_iter_0 < ll_probe_end_0; "
            "i++, ll_probe_iter_0++) {"
        ),
    }
    lifetime_probe = LifetimeLayoutProbe(
        label="window-order-ranked-end-pointer-ig34-before-0",
        operator="window-order-source-steering",
        description="Materialize ranked end-pointer owner span.",
        source_text=candidate,
        provenance={
            "kind": "window-order-ranked-end-pointer-source-probe",
            "lead": {
                "target_ig": 34,
                "order_move": ["before", "force-phys"],
                "perturbed_reg": 27,
            },
            "source_attribution": {
                "kind": "implicit-temp",
                "expression": "addi r34,r40,120",
            },
            "protected_targets": {"44": 25},
            "synthetic_source_probe": {
                "ranked_end_pointer_source_candidates": [ranked_candidate],
            },
            "ranked_end_pointer_source_candidate": ranked_candidate,
            "source_diff": "@@ end pointer diff @@\n",
        },
    )
    plan = plan_transform_experiments(
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
    )

    probe = _lifetime_layout_probe_to_transform_probe(
        lifetime_probe,
        family_id=RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID,
        index=0,
        source_text=source,
        plan=plan,
        force_phys={34: 27, 44: 25},
    )

    assert probe.family_id == RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID
    assert probe.payload["lead_target_ig"] == 34
    assert probe.payload["attempted_targets"] == {"34": 27}
    assert probe.payload["protected_targets"] == {"44": 25}
    assert probe.payload["synthetic_source_probe"][
        "ranked_end_pointer_source_candidates"
    ] == [ranked_candidate]
    assert probe.payload["ranked_end_pointer_source_candidate"] == ranked_candidate
    assert probe.payload["source_diff"] == "@@ end pointer diff @@\n"


def test_retained_case_c_window_order_continuation_converts_li_constant_probe(
) -> None:
    source = (
        "void fn(int mode) {\n"
        "    int limit;\n"
        "    if (mode) {\n"
        "        limit = 12;\n"
        "    }\n"
        "}\n"
    )
    candidate = source.replace(
        "    int limit;\n",
        "    int limit;\n"
        "    int window_order_limit_12_probe;\n",
    ).replace(
        "        limit = 12;\n",
        "        window_order_limit_12_probe = 12;\n"
        "        limit = window_order_limit_12_probe;\n",
    )
    ranked_candidate = {
        "kind": "li-constant-threshold-owner",
        "owner_local": "limit",
        "literal_text": "12",
        "immediate_value": 12,
    }
    source_hunks = [{"hunk_id": "li-constant001", "base_start": 2}]
    lifetime_probe = LifetimeLayoutProbe(
        label="window-order-li-constant-ig36-before-0",
        operator="window-order-source-steering",
        description="Materialize li constant source owner.",
        source_text=candidate,
        provenance={
            "kind": "window-order-li-constant-source-probe",
            "lead": {
                "target_ig": 36,
                "order_move": ["before", 41],
                "perturbed_reg": 27,
            },
            "source_attribution": {
                "kind": "first-def",
                "expression": "li r36,12",
            },
            "synthetic_source_probe": {
                "ranked_li_constant_source_candidates": [ranked_candidate],
            },
            "ranked_li_constant_source_candidate": ranked_candidate,
            "source_hunks": source_hunks,
            "source_diff": "@@ li diff @@\n",
        },
    )
    plan = plan_transform_experiments(
        function="fn",
        unit="melee/mn/mndiagram2",
        force_phys={36: 27, 51: 27},
    )

    probe = _lifetime_layout_probe_to_transform_probe(
        lifetime_probe,
        family_id=RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID,
        index=0,
        source_text=source,
        plan=plan,
        force_phys={36: 27, 51: 27},
    )

    assert probe.payload["source_probe_provenance_kind"] == (
        "window-order-li-constant-source-probe"
    )
    assert probe.payload["source_hunks"] == source_hunks
    assert probe.payload["source_diff"] == "@@ li diff @@\n"
    assert probe.payload["ranked_li_constant_source_candidate"] == ranked_candidate
    assert probe.payload["synthetic_source_probe"][
        "ranked_li_constant_source_candidates"
    ] == [ranked_candidate]
    assert probe.payload["attempted_targets"] == {"36": 27}
    assert probe.payload["protected_targets"] == {"51": 27}


def test_retained_case_c_window_order_continuation_converts_pointer_walk_add_probe(
) -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef struct Widget Widget;\n"
        "void attach_widget(Widget** out);\n"
        "void fn(void* arena, int slot) {\n"
        "    attach_widget((Widget**) ((u8*) arena + (slot << 2) + 4));\n"
        "}\n"
    )
    candidate = source.replace(
        "void fn(void* arena, int slot) {\n",
        "void fn(void* arena, int slot) {\n"
        "    Widget** window_order_arena_widget_probe;\n",
    ).replace(
        "    attach_widget((Widget**) ((u8*) arena + (slot << 2) + 4));\n",
        "    window_order_arena_widget_probe = "
        "(Widget**) ((u8*) arena + (slot << 2) + 4);\n"
        "    attach_widget(window_order_arena_widget_probe);\n",
    )
    ranked_candidate = {
        "kind": "pointer-walk-add-callarg",
        "base_expression": "arena",
        "index_expr": "slot",
        "offset_value": 4,
        "callee": "attach_widget",
    }
    source_hunks = [{"hunk_id": "pointer-walk-add001", "base_start": 4}]
    lifetime_probe = LifetimeLayoutProbe(
        label="window-order-pointer-walk-add-ig51-before-0",
        operator="window-order-source-steering",
        description="Materialize pointer-walk add source owner.",
        source_text=candidate,
        provenance={
            "kind": "window-order-pointer-walk-add-source-probe",
            "lead": {
                "target_ig": 51,
                "order_move": ["before", "force-phys"],
                "perturbed_reg": 27,
            },
            "source_attribution": {
                "kind": "implicit-temp",
                "expression": "add r51,r45,r63",
            },
            "synthetic_source_probe": {
                "ranked_pointer_walk_add_source_candidates": [ranked_candidate],
            },
            "ranked_pointer_walk_add_source_candidate": ranked_candidate,
            "source_hunks": source_hunks,
            "source_diff": "@@ pointer diff @@\n",
        },
    )
    plan = plan_transform_experiments(
        function="fn",
        unit="melee/mn/mndiagram2",
        force_phys={36: 27, 51: 27},
    )

    probe = _lifetime_layout_probe_to_transform_probe(
        lifetime_probe,
        family_id=RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID,
        index=0,
        source_text=source,
        plan=plan,
        force_phys={36: 27, 51: 27},
    )

    assert probe.payload["source_probe_provenance_kind"] == (
        "window-order-pointer-walk-add-source-probe"
    )
    assert probe.payload["source_hunks"] == source_hunks
    assert probe.payload["source_diff"] == "@@ pointer diff @@\n"
    assert (
        probe.payload["ranked_pointer_walk_add_source_candidate"]
        == ranked_candidate
    )
    assert probe.payload["synthetic_source_probe"][
        "ranked_pointer_walk_add_source_candidates"
    ] == [ranked_candidate]
    assert probe.payload["attempted_targets"] == {"51": 27}
    assert probe.payload["protected_targets"] == {"36": 27}


def test_retained_case_c_window_order_continuation_preserves_field_load_payload(
) -> None:
    source = (
        "typedef struct HSD_GObj HSD_GObj;\n"
        "void fn(HSD_GObj* gobj) {\n"
        "    void* data;\n"
        "    data = gobj->user_data;\n"
        "}\n"
    )
    candidate = source.replace(
        "    void* data;\n",
        "    void* data;\n"
        "    void* window_order_gobj_user_data_probe;\n",
    ).replace(
        "    data = gobj->user_data;\n",
        "    window_order_gobj_user_data_probe = gobj->user_data;\n"
        "    data = window_order_gobj_user_data_probe;\n",
    )
    field_candidate = {
        "kind": "inline-temp",
        "base_var": "gobj",
        "field_offset": 44,
        "field_name": "user_data",
        "expression": "gobj->user_data",
        "pcode_first_def": {"opcode": "lwz", "operands": "r32,44(r30)"},
        "base_virtual": 30,
    }
    source_hunks = [{"hunk_id": "field-load001", "base_start": 2}]
    lifetime_probe = LifetimeLayoutProbe(
        label="window-order-field-load-ig32-before-inline-temp-0",
        operator="window-order-source-steering",
        description="Materialize a field-load source-order probe.",
        source_text=candidate,
        provenance={
            "kind": "field-load-source-order",
            "lead": {
                "target_ig": 32,
                "order_move": ["before", "force-phys"],
                "perturbed_reg": 30,
            },
            "source_attribution": {
                "kind": "field-load",
                "expression": "gobj->field_at_0x2C",
                "base_var": "gobj",
                "field_offset": 44,
            },
            "field_load_source_candidate": field_candidate,
            "pcode_first_def": {"opcode": "lwz", "operands": "r32,44(r30)"},
            "source_hunks": source_hunks,
            "attempted_force_phys_targets": {"32": 30},
            "protected_force_phys_targets": {"44": 25},
            "selected_force_phys_targets": {"32": 30},
        },
    )
    plan = plan_transform_experiments(
        function="fn",
        unit="melee/mn/mnvibration",
        force_phys={32: 30, 44: 25},
    )

    probe = _lifetime_layout_probe_to_transform_probe(
        lifetime_probe,
        family_id=RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID,
        index=0,
        source_text=source,
        plan=plan,
        force_phys={32: 30, 44: 25},
    )

    assert probe.payload["source_probe_provenance_kind"] == (
        "field-load-source-order"
    )
    assert probe.payload["source_attribution"]["kind"] == "field-load"
    assert probe.payload["field_load_source_candidate"] == field_candidate
    assert probe.payload["pcode_first_def"] == {
        "opcode": "lwz",
        "operands": "r32,44(r30)",
    }
    assert probe.payload["source_hunks"] == source_hunks
    assert probe.payload["attempted_force_phys_targets"] == {"32": 30}
    assert probe.payload["protected_force_phys_targets"] == {"44": 25}
    assert probe.payload["selected_force_phys_targets"] == {"32": 30}


def test_retained_case_c_window_order_continuation_preserves_call_return_payload(
) -> None:
    source = (
        "typedef struct HSD_GObj HSD_GObj;\n"
        "HSD_GObj* GObj_Create(int kind);\n"
        "void fn(void) {\n"
        "    HSD_GObj* gobj;\n"
        "    gobj = GObj_Create(1);\n"
        "}\n"
    )
    candidate = source.replace(
        "    HSD_GObj* gobj;\n",
        "    HSD_GObj* gobj;\n"
        "    HSD_GObj* window_order_synthetic_gobj;\n",
    ).replace(
        "    gobj = GObj_Create(1);\n",
        "    window_order_synthetic_gobj = GObj_Create(1);\n"
        "    gobj = window_order_synthetic_gobj;\n",
    )
    call_return_probe = {
        "handler": "call-return-owner-split",
        "assigned_local": "gobj",
        "call_symbol": "GObj_Create",
        "variant": "synthetic-call-return-owner-copy",
    }
    source_hunks = [{"hunk_id": "call-return001", "base_start": 4}]
    lifetime_probe = LifetimeLayoutProbe(
        label="window-order-call-return-ig40-before-0",
        operator="window-order-source-steering",
        description="Split a named call-return owner.",
        source_text=candidate,
        provenance={
            "kind": "window-order-call-return-source-order",
            "lead": {
                "target_ig": 40,
                "order_move": ["before", 67],
                "perturbed_reg": 29,
            },
            "source_attribution": {
                "kind": "call-return",
                "name": "gobj",
                "call_symbol": "GObj_Create",
            },
            "call_return_source_probe": call_return_probe,
            "source_hunks": source_hunks,
            "attempted_force_phys_targets": {"40": 29},
            "protected_force_phys_targets": {"67": 31},
            "selected_force_phys_targets": {"40": 29},
        },
    )
    plan = plan_transform_experiments(
        function="fn",
        unit="melee/mn/mnvibration",
        force_phys={40: 29, 67: 31},
    )

    probe = _lifetime_layout_probe_to_transform_probe(
        lifetime_probe,
        family_id=RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID,
        index=0,
        source_text=source,
        plan=plan,
        force_phys={40: 29, 67: 31},
    )

    assert probe.payload["source_probe_provenance_kind"] == (
        "window-order-call-return-source-order"
    )
    assert probe.payload["source_attribution"]["kind"] == "call-return"
    assert probe.payload["call_return_source_probe"] == call_return_probe
    assert probe.payload["source_hunks"] == source_hunks
    assert probe.payload["attempted_force_phys_targets"] == {"40": 29}
    assert probe.payload["protected_force_phys_targets"] == {"67": 31}
    assert probe.payload["selected_force_phys_targets"] == {"40": 29}


def test_retained_case_c_target_live_range_repair_converts_lifetime_probe(
) -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* sorted_names, int j) {\n"
        "    use(sorted_names[j]);\n"
        "}\n"
    )
    candidate = source.replace(
        "    use(sorted_names[j]);\n",
        "    u8 target_live_range_sorted_names_j_probe;\n"
        "    target_live_range_sorted_names_j_probe = sorted_names[j];\n"
        "    use(target_live_range_sorted_names_j_probe);\n",
    )
    repair_goal = {
        "kind": "target-aware-live-range-interference",
        "target_ig": 44,
        "target_phys": 25,
        "protected_targets": {"34": 27},
        "interferer_ig": 39,
        "interferer_phys": 25,
        "source_expression": "sorted_names[j]",
        "required_delta": 6,
    }
    lifetime_probe = LifetimeLayoutProbe(
        label="target-live-range-ig44-r39-0",
        operator="target-aware-live-range-repair",
        description="Split r39 source expression around IG44.",
        source_text=candidate,
        provenance={
            "kind": "target-aware-live-range-anchor",
            "repair_goal": repair_goal,
            "target_ig": 44,
            "target_phys": 25,
            "interferer_ig": 39,
            "interferer_phys": 25,
            "protected_targets": {"34": 27},
            "required_delta": 6,
            "ranked_repair_candidate": {
                "strategy": "interferer-expression-temp",
                "source_expression": "sorted_names[j]",
            },
        },
    )
    plan = plan_transform_experiments(
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
    )

    probe = _lifetime_layout_probe_to_transform_probe(
        lifetime_probe,
        family_id=RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID,
        index=0,
        source_text=source,
        plan=plan,
        force_phys={34: 27, 44: 25},
    )

    assert probe.family_id == RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID
    assert probe.probe_id == "retained_gpr_case_c_target_live_range_repair@0"
    assert probe.mutator_key == "steer_retained_gpr_case_c_target_live_range_repair"
    assert probe.payload["source_probe_provenance_kind"] == (
        "target-aware-live-range-anchor"
    )
    assert probe.payload["target_ig"] == 44
    assert probe.payload["interferer_ig"] == 39
    assert probe.payload["required_delta"] == 6
    assert probe.payload["repair_goal"] == repair_goal
    assert probe.payload["protected_targets"] == {"34": 27}
    assert probe.payload["attempted_targets"] == {"44": 25}
    assert "target_live_range_sorted_names_j_probe" in probe.payload["source_diff"]


def test_retained_case_c_window_order_continuation_reports_blocked_diagnostics() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int i) {\n"
        "    u8 temp;\n"
        "    temp = dst[i];\n"
        "}\n"
    )

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        force_class_id=0,
        families=[RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID],
        window_order_continuation={
            "fallback_leads": [{"target_ig": 44, "order_move": ["before", 34]}],
            "source_attributions": {},
            "probe_diagnostics": {},
        },
    )

    assert report.probes == ()
    diagnostic = next(
        item for item in report.family_diagnostics
        if item.family_id == RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID
    )
    assert diagnostic.family_id == RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID
    assert diagnostic.no_probe_reason == "missing-source-attribution"
    assert diagnostic.matcher_diagnostics["terminal_blocker"] == (
        "missing-source-attribution"
    )


def test_retained_case_c_window_order_continuation_is_opt_in_without_json() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int i) {\n"
        "    u8 temp;\n"
        "    temp = dst[i];\n"
        "}\n"
    )

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        force_class_id=0,
    )

    diagnostic = next(
        item for item in report.family_diagnostics
        if item.family_id == RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID
    )
    assert diagnostic.attempted is False
    assert diagnostic.no_probe_reason == "family-filtered-by-unit"


def _retained_case_c_simplify_order_source() -> str:
    return (
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "void* GetNameText(u8 value);\n"
        "struct Names { u8 sorted_names[0x78]; };\n"
        "extern struct Names mnDiagram_804A076C;\n"
        "void mnDiagram_SortNamesByKOs(u32* totals, int i) {\n"
        "    int j;\n"
        "    int max_idx;\n"
        "    max_idx = i;\n"
        "    for (j = i + 1; j < 0x78; j++) {\n"
        "        if ((GetNameText(mnDiagram_804A076C.sorted_names[j]) != 0) &&\n"
        "            ((totals[mnDiagram_804A076C.sorted_names[max_idx]] <\n"
        "              totals[mnDiagram_804A076C.sorted_names[j]]) ||\n"
        "             ((GetNameText((0, mnDiagram_804A076C.sorted_names[max_idx])) == 0) &&\n"
        "              (GetNameText(mnDiagram_804A076C.sorted_names[j]) != 0)))) {\n"
        "            max_idx = j;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def _retained_case_c_lower_drift_residual_source() -> str:
    return (
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "void* GetNameText(u8 value);\n"
        "struct Names { u8 sorted_names[0x78]; };\n"
        "extern struct Names mnDiagram_804A076C;\n"
        "void mnDiagram_SortNamesByKOs(u32* totals) {\n"
        "    int case_c_max_idx_probe;\n"
        "    u32 sorted_names_base_probe_probe;\n"
        "    int sorted_names_totals_idx_probe;\n"
        "    u8* sorted_names_base_probe;\n"
        "    int sorted_names_totals_idx_probe_2;\n"
        "    int window_order_mnDiagram_804A076C_sorted_names_index_probe;\n"
        "    int i;\n"
        "    int j;\n"
        "    int max_idx;\n"
        "    u8* dst_iter;\n"
        "    for (i = 0; i < 0x78; i++, dst_iter++) {\n"
        "        max_idx = i;\n"
        "        for (j = i + 1; j < 0x78; j++) {\n"
        "            case_c_max_idx_probe = max_idx;\n"
        "            sorted_names_totals_idx_probe = mnDiagram_804A076C.sorted_names[case_c_max_idx_probe];\n"
        "            sorted_names_totals_idx_probe_2 = mnDiagram_804A076C.sorted_names[j];\n"
        "            window_order_mnDiagram_804A076C_sorted_names_index_probe = j;\n"
        "            sorted_names_base_probe = mnDiagram_804A076C.sorted_names;\n"
        "            sorted_names_base_probe_probe = sorted_names_base_probe[window_order_mnDiagram_804A076C_sorted_names_index_probe];\n"
        "            if ((GetNameText(sorted_names_base_probe_probe) != 0) &&\n"
        "                ((totals[sorted_names_totals_idx_probe] < totals[sorted_names_totals_idx_probe_2]) ||\n"
        "                 ((GetNameText((0, mnDiagram_804A076C.sorted_names[case_c_max_idx_probe])) == 0) &&\n"
        "                  (GetNameText(mnDiagram_804A076C.sorted_names[(0, j)]) != 0)))) {\n"
        "                max_idx = j;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def _lower_drift_residual_goal() -> dict:
    return {
        "kind": "retained-case-c-lower-drift-residual",
        "target_ig": 34,
        "target_phys": 27,
        "protected_targets": {"44": 26},
        "final_force_phys": {"34": 27, "44": 25},
        "baseline_pcdump_path": "build/diag/max_index_alias.pcdump.txt",
        "baseline_first_divergence": {
            "class_id": 0,
            "iter": 3,
            "ig_idx": 34,
            "case": "C",
        },
        "baseline_score": {
            "34": {"expected": 27, "actual": 28},
            "44": {"expected": 25, "actual": 26},
        },
    }


def test_retained_case_c_simplify_order_continuation_materializes_probes() -> None:
    source = _retained_case_c_simplify_order_source()

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        force_class_id=0,
        families=[RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID],
        max_per_family=6,
        window_order_continuation={
            "retained_case_c_simplify_order_goals": [{
                "kind": "retained-case-c-simplify-order",
                "target_ig": 44,
                "target_phys": 25,
                "protected_targets": {"34": 27},
                "baseline_first_divergence": {
                    "class_id": 0,
                    "iter": 40,
                    "ig_idx": 44,
                    "case": "C",
                },
            }],
        },
    )

    assert len(report.probes) >= 4
    assert {
        probe.payload["strategy"] for probe in report.probes
    } >= {
        "case-c-max-index-alias",
        "case-c-max-name-reload",
        "case-c-j-name-reload",
        "case-c-compare-block-scope",
    }
    probe = report.probes[0]
    assert probe.family_id == RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID
    assert probe.mutator_key == (
        "steer_retained_gpr_case_c_simplify_order_continuation"
    )
    assert probe.payload["protected_targets"] == {"34": 27}
    assert probe.payload["attempted_targets"] == {"44": 25}
    assert probe.payload["baseline_first_divergence"]["ig_idx"] == 44
    assert probe.payload["source_hunk"]
    assert "source" in probe.payload["source_diff"]
    assert probe.candidate_text != source

    diagnostics = {
        item.family_id: item for item in report.family_diagnostics
    }
    family = diagnostics[RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID]
    assert family.materialized_count >= 4
    assert family.matcher_diagnostics["emitted_simplify_order_probe_count"] >= 4


def test_retained_case_c_lower_drift_residual_materializes_probe_strategies() -> None:
    source = _retained_case_c_lower_drift_residual_source()

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        force_class_id=0,
        families=[RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID],
        max_per_family=6,
        window_order_continuation={
            "retained_case_c_lower_drift_residual": _lower_drift_residual_goal(),
        },
    )

    assert len(report.probes) >= 4
    strategies = {probe.payload["strategy"] for probe in report.probes}
    assert strategies >= {
        "case-c-max-index-probe-block-scope",
        "case-c-max-index-probe-reload-near-first-use",
        "case-c-preserve-ig44-alias-window",
        "case-c-dst-iter-lifetime-anchor",
    }
    assert "case-c-max-index-alias" not in strategies
    reload_probe = next(
        probe for probe in report.probes
        if probe.payload["strategy"] == "case-c-max-index-probe-reload-near-null-check"
    )
    assert (
        "            case_c_max_idx_probe = max_idx;\n"
        "            if ((GetNameText"
    ) in reload_probe.candidate_text
    assert "||\n            case_c_max_idx_probe = max_idx;" not in (
        reload_probe.candidate_text
    )
    probe = report.probes[0]
    assert probe.payload["attempted_targets"] == {"34": 27}
    assert probe.payload["protected_targets"] == {"44": 26}
    assert probe.payload["final_force_phys"] == {"34": 27, "44": 25}
    assert probe.payload["baseline_pcdump_path"].endswith("max_index_alias.pcdump.txt")
    assert probe.payload["baseline_first_divergence"]["ig_idx"] == 34
    assert probe.payload["source_probe_provenance_kind"] == (
        "retained-case-c-lower-drift-residual"
    )
    assert probe.payload["source_span"]["kind"] in {
        "case-c-max-index-probe",
        "case-c-dst-iter-lifetime",
    }

    family = next(
        item for item in report.family_diagnostics
        if item.family_id == RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID
    )
    assert family.materialized_count >= 4
    assert family.matcher_diagnostics["attempted_targets"] == {"34": 27}
    assert family.matcher_diagnostics["protected_targets"] == {"44": 26}


def test_retained_case_c_lower_drift_residual_requires_retained_alias_shape() -> None:
    report = generate_transform_probe_report(
        _retained_case_c_simplify_order_source(),
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        force_class_id=0,
        families=[RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID],
        max_per_family=6,
        window_order_continuation={
            "retained_case_c_lower_drift_residual": _lower_drift_residual_goal(),
        },
    )

    assert report.probes == ()
    family = next(
        item for item in report.family_diagnostics
        if item.family_id == RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID
    )
    assert family.no_probe_reason == "blocked-missing-case-c-max-idx-probe"
    assert family.matcher_diagnostics["blocked_source_spans"] == [
        {
            "kind": "case-c-max-index-probe",
            "unsupported_reason": "blocked-missing-case-c-max-idx-probe",
        },
        {
            "kind": "case-c-dst-iter-lifetime",
            "unsupported_reason": "blocked-ambiguous-dst-iter-owner",
        },
    ]


def test_retained_case_c_lower_drift_decl_move_stays_in_target_function() -> None:
    source = _retained_case_c_lower_drift_residual_source().replace(
        "void mnDiagram_SortNamesByKOs",
        "void unrelated_prior(void) {\n"
        "    u8* dst_iter;\n"
        "}\n"
        "void mnDiagram_SortNamesByKOs",
        1,
    )

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        force_class_id=0,
        families=[RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID],
        max_per_family=6,
        window_order_continuation={
            "retained_case_c_lower_drift_residual": _lower_drift_residual_goal(),
        },
    )

    moved_decl_probe = next(
        probe for probe in report.probes
        if probe.payload["strategy"] == "case-c-max-index-probe-decl-before-dst-iter"
    )
    before_target = moved_decl_probe.candidate_text.split(
        "void mnDiagram_SortNamesByKOs",
        1,
    )[0]
    assert "case_c_max_idx_probe" not in before_target
    target_function = moved_decl_probe.candidate_text.split(
        "void mnDiagram_SortNamesByKOs",
        1,
    )[1]
    assert (
        "    int case_c_max_idx_probe;\n"
        "    u32 sorted_names_base_probe_probe;"
    ) not in target_function
    assert (
        "    int max_idx;\n"
        "    int case_c_max_idx_probe;\n"
        "    u8* dst_iter;"
    ) in target_function


def test_retained_case_c_simplify_order_continuation_reports_blocked_without_goals(
) -> None:
    report = generate_transform_probe_report(
        _retained_case_c_simplify_order_source(),
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        force_class_id=0,
        families=[RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID],
    )

    diagnostic = next(
        item for item in report.family_diagnostics
        if item.family_id == RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID
    )
    assert diagnostic.materialized_count == 0
    assert diagnostic.no_probe_reason == "missing-simplify-order-goals"
    assert diagnostic.matcher_diagnostics["terminal_blocker"] == (
        "missing-simplify-order-goals"
    )


def test_retained_case_c_simplify_order_alias_keeps_setup_lhs() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "void* GetNameText(u8 value);\n"
        "void mnDiagram_SortNamesByKOs(u8* sorted_names, u32* totals, int i, int j) {\n"
        "    int max_idx;\n"
        "    max_idx = i;\n"
        "    if ((GetNameText(sorted_names[j]) != 0) &&\n"
        "        (totals[sorted_names[max_idx]] < totals[sorted_names[j]])) {\n"
        "        max_idx = j;\n"
        "    }\n"
        "}\n"
    )

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        force_class_id=0,
        families=[RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID],
        max_per_family=1,
        window_order_continuation={
            "retained_case_c_simplify_order_goals": [{
                "kind": "retained-case-c-simplify-order",
                "target_ig": 44,
                "target_phys": 25,
                "protected_targets": {"34": 27},
            }],
        },
    )

    probe = report.probes[0]
    assert probe.payload["strategy"] == "case-c-max-index-alias"
    assert "    max_idx = i;\n" in probe.candidate_text
    assert "case_c_max_idx_probe = i;" not in probe.candidate_text
    assert "sorted_names[case_c_max_idx_probe]" in probe.candidate_text
