from __future__ import annotations

import textwrap

import pytest

from src.search.directed.window_order_source import (
    generate_window_order_source_probes,
    plan_target_aware_live_range_repair_probes,
    plan_window_order_source_probes,
)


def test_window_order_probe_hoists_unique_source_local() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int idx;
            int guard;
            int dst_iter;
            idx = seed;
            guard = seed;
            dst_iter = idx;
        }
    """)

    probes = generate_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{
            "target_ig": 34,
            "order_move": ["before", 43],
            "move_distance": 5,
            "perturbed_reg": 25,
        }],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 8},
        },
        max_probes=4,
    )
    if not probes:
        pytest.skip("tree-sitter unavailable")

    probe = probes[0]
    assert probe.operator == "window-order-source-steering"
    assert probe.provenance["kind"] == "window-order-fallback-source-move"
    assert probe.provenance["lead"]["target_ig"] == 34
    assert probe.provenance["moved_local"] == "dst_iter"
    assert probe.source_text.index("dst_iter = idx;") < probe.source_text.index(
        "guard = seed;"
    )


def test_window_order_probe_sinks_unique_source_local() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int idx;
            int guard;
            int dst_iter;
            idx = seed;
            dst_iter = idx;
            guard = seed;
        }
    """)

    probes = generate_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{
            "target_ig": 34,
            "order_move": ["after", 43],
            "move_distance": 3,
            "perturbed_reg": 25,
        }],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 7},
        },
        max_probes=4,
    )
    if not probes:
        pytest.skip("tree-sitter unavailable")

    assert probes[0].source_text.index("guard = seed;") < probes[0].source_text.index(
        "dst_iter = idx;"
    )


def test_window_order_probe_requires_source_attribution() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int dst_iter;
            dst_iter = seed;
        }
    """)

    probes = generate_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={},
    )

    assert probes == []


def test_window_order_probe_skips_ambiguous_source_local() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int dst_iter;
            dst_iter = seed;
            if (seed != 0) {
                dst_iter = seed;
            }
        }
    """)

    probes = generate_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 4},
        },
    )
    if probes:
        pytest.fail("ambiguous source attribution produced a source probe")


def test_window_order_plan_marks_materialized_lead_actionable() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int idx;
            int guard;
            int dst_iter;
            idx = seed;
            guard = seed;
            dst_iter = idx;
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 8},
        },
        max_probes=4,
    )
    if not plan.probes:
        pytest.skip("tree-sitter unavailable")

    assert len(plan.probes) == 1
    assert plan.lead_diagnostics[0]["status"] == "materialized"
    assert plan.lead_diagnostics[0]["materialized_probe_labels"] == [
        plan.probes[0].label
    ]
    assert "source_diff" in plan.lead_diagnostics[0]


def test_window_order_plan_materializes_call_return_source_probe() -> None:
    source = textwrap.dedent("""\
        typedef struct HSD_GObj HSD_GObj;
        HSD_GObj* GObj_Create(int kind, int p_link, int gx_link);
        void sink(HSD_GObj* gobj);

        void fn(void)
        {
            HSD_GObj* cursor;
            if (1) {
                cursor = GObj_Create(1, 2, 3);
                sink(cursor);
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 40, "order_move": ["before", 67]}],
        source_attributions={
            40: {
                "kind": "call-return",
                "name": "cursor",
                "type": "HSD_GObj*",
                "expression": "GObj_Create(1, 2, 3)",
                "call_symbol": "GObj_Create",
                "source_line": 9,
                "copy_chain": [40],
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert len(plan.probes) == 1
    probe = plan.probes[0]
    diag = plan.lead_diagnostics[0]
    assert probe.operator == "window-order-source-steering"
    assert probe.label.startswith("window-order-call-return-ig40-before-")
    assert probe.provenance["kind"] == "window-order-call-return-source-order"
    assert diag["status"] == "materialized"
    assert diag["materialized_probe_labels"] == [probe.label]
    assert diag["source_hunks"]
    assert diag["source_diff"]
    call_return = probe.provenance["call_return_source_probe"]
    assert call_return["handler"] == "call-return-owner-split"
    assert call_return["assigned_local"] == "cursor"
    assert call_return["call_symbol"] == "GObj_Create"
    assert call_return["source_hunks"]
    assert "HSD_GObj* window_order_synthetic_cursor;" in probe.source_text
    assert "window_order_synthetic_cursor = GObj_Create(1, 2, 3);" in (
        probe.source_text
    )
    assert "cursor = window_order_synthetic_cursor;" in probe.source_text


def test_window_order_plan_reports_call_return_owner_copy_not_found() -> None:
    source = textwrap.dedent("""\
        typedef struct HSD_GObj HSD_GObj;
        HSD_GObj* GObj_Create(int kind, int p_link, int gx_link);
        void sink(HSD_GObj* gobj);

        void fn(void)
        {
            sink(GObj_Create(1, 2, 3));
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 40, "order_move": ["before", 67]}],
        source_attributions={
            40: {
                "kind": "call-return",
                "name": "cursor",
                "type": "HSD_GObj*",
                "expression": "GObj_Create(1, 2, 3)",
                "call_symbol": "GObj_Create",
                "source_line": 7,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"] == "call-return-owner-copy-not-found"
    assert diag["source_attribution"]["kind"] == "call-return"
    assert diag["call_return_source_probe"]["handler"] == "call-return-owner-split"


def test_window_order_plan_materializes_param_alias_declaration_order_probe() -> None:
    source = textwrap.dedent("""\
        typedef int s32;
        void sink(s32 lhs, s32 rhs);

        void fn(s32 arg1, s32 arg2)
        {
            s32 arg1_r = arg1;
            s32 arg2_r = arg2;
            sink(arg1_r, arg2_r);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 56, "order_move": ["before", 40]}],
        source_attributions={
            56: {"kind": "param", "name": "arg2", "type": "s32"},
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    probe = next(
        (
            probe for probe in plan.probes
            if probe.provenance.get("param_alias_source_candidate", {}).get(
                "materialization_kind"
            )
            == "declaration-order"
        ),
        None,
    )
    assert probe is not None
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag.get("terminal_blocker") != "unsupported-source-attribution-kind"
    assert probe.label.startswith("window-order-param-alias-ig56-before-")
    assert probe.operator == "window-order-source-steering"
    assert probe.provenance["kind"] == "window-order-param-alias-source-order"
    assert probe.provenance["source_attribution"]["kind"] == "param"
    assert probe.provenance["source_attribution"]["name"] == "arg2"
    assert probe.provenance["source_hunks"]
    assert diag["source_hunks"]

    assert diag["param_alias_source_candidates"]
    assert diag["materialized_param_alias_source_candidates"]
    summary = diag["param_alias_materialization_summary"]
    assert summary["param_name"] == "arg2"
    assert summary["param_alias_candidates"] >= 1
    assert summary["materialized_param_alias_candidates"] >= 1

    materialized = diag["materialized_param_alias_source_candidates"][0]
    assert materialized["param_name"] == "arg2"
    assert materialized["alias_name"] == "arg2_r"
    assert materialized["materialization_kind"] == "declaration-order"
    assert probe.provenance["param_alias_source_candidate"] == materialized
    assert probe.source_text.index("s32 arg2_r = arg2;") < probe.source_text.index(
        "s32 arg1_r = arg1;"
    )


def test_window_order_plan_materializes_param_alias_delayed_init_probe() -> None:
    source = textwrap.dedent("""\
        typedef int s32;
        void sink(s32 value);

        void fn(s32 arg1, s32 arg2)
        {
            s32 arg2_r = arg2;
            s32 total;
            total = arg2_r + arg1;
            sink(total);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 56, "order_move": ["after", 40]}],
        source_attributions={
            56: {"kind": "param", "name": "arg2", "type": "s32"},
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    probe = next(
        (
            probe for probe in plan.probes
            if probe.provenance.get("param_alias_source_candidate", {}).get(
                "materialization_kind"
            )
            == "delayed-init"
        ),
        None,
    )
    assert probe is not None
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag.get("terminal_blocker") != "unsupported-source-attribution-kind"
    assert probe.label.startswith("window-order-param-alias-ig56-after-")
    assert probe.provenance["kind"] == "window-order-param-alias-source-order"
    assert probe.provenance["source_hunks"]
    assert diag["source_hunks"]
    assert diag["param_alias_source_candidates"]
    assert diag["materialized_param_alias_source_candidates"]

    candidate = probe.provenance["param_alias_source_candidate"]
    assert candidate["param_name"] == "arg2"
    assert candidate["alias_name"] == "arg2_r"
    assert candidate["materialization_kind"] == "delayed-init"
    assert "s32 arg2_r = arg2;" not in probe.source_text
    declaration_index = probe.source_text.index("s32 arg2_r;")
    init_index = probe.source_text.index("arg2_r = arg2;")
    use_index = probe.source_text.index("total = arg2_r + arg1;")
    assert declaration_index < init_index < use_index


def test_window_order_plan_param_alias_terminal_proof_when_no_alias_source() -> None:
    source = textwrap.dedent("""\
        typedef int s32;
        void sink(s32 value);

        void fn(s32 arg2)
        {
            sink(arg2);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 56, "order_move": ["before", 40]}],
        source_attributions={
            56: {"kind": "param", "name": "arg2", "type": "s32"},
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "blocked"
    assert diag["terminal_blocker"] != "unsupported-source-attribution-kind"
    assert diag["terminal_blocker"].startswith("param-alias-")
    assert diag["param_name"] == "arg2"
    summary = diag["param_alias_materialization_summary"]
    assert summary["param_name"] == "arg2"
    assert summary["param_alias_candidates"] == 0
    assert summary["materialized_param_alias_candidates"] == 0
    assert "unsupported-source-attribution-kind" not in summary["reasons"]


def test_window_order_plan_rejects_compound_call_return_rhs() -> None:
    source = textwrap.dedent("""\
        typedef struct HSD_GObj HSD_GObj;
        HSD_GObj* GObj_Create(int kind, int p_link, int gx_link);
        HSD_GObj* wrap(HSD_GObj* gobj);
        void sink(HSD_GObj* gobj);

        void fn(void)
        {
            HSD_GObj* cursor;
            cursor = wrap(GObj_Create(1, 2, 3));
            sink(cursor);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 40, "order_move": ["before", 67]}],
        source_attributions={
            40: {
                "kind": "call-return",
                "name": "cursor",
                "type": "HSD_GObj*",
                "expression": "GObj_Create(1, 2, 3)",
                "call_symbol": "GObj_Create",
                "source_line": 9,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"] == "call-return-owner-copy-not-found"
    assert diag["call_return_source_probe"]["candidate_assignment_count"] == 0


def test_window_order_plan_recovers_pcode_field_load_user_data_from_base_virtual(
) -> None:
    source = textwrap.dedent("""\
        typedef struct HSD_GObj HSD_GObj;
        void sink(void* data);

        void fn(HSD_GObj* gobj)
        {
            void* data;
            data = gobj->user_data;
            sink(data);
        }
    """)

    first_def = {
        "block": "B0",
        "index": 12,
        "opcode": "lwz",
        "operands": "r67,44(r32)",
        "text": "lwz r67,44(r32)",
    }
    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 67, "order_move": ["before", 40]}],
        source_attributions={
            32: {"kind": "local", "name": "gobj", "type": "HSD_GObj*"},
            67: {
                "kind": "first-def",
                "confidence": "pcode-first-def",
                "expression": "lwz r67,44(r32)",
                "base_virtual": 32,
                "field_offset": 44,
                "first_def": first_def,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert len(plan.probes) == 1
    probe = plan.probes[0]
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag.get("terminal_blocker") != "unsupported-source-attribution-kind"
    assert diag["base_virtual"] == 32
    assert diag["field_offset"] == 44
    assert diag["pcode_first_def"] == first_def
    assert diag["field_load_source_candidate"]["base_var"] == "gobj"
    assert diag["field_load_source_candidate"]["field_name"] == "user_data"
    assert diag["source_hunks"]
    assert probe.provenance["kind"] == "pcode-first-def-field-load-source-order"
    assert probe.provenance["source_attribution"]["kind"] == "first-def"
    assert probe.provenance["pcode_first_def"] == first_def
    assert (
        probe.provenance["field_load_source_candidate"]["pcode_first_def"]
        == first_def
    )
    assert "void* window_order_gobj_user_data_probe;" in probe.source_text
    assert "window_order_gobj_user_data_probe = gobj->user_data;" in (
        probe.source_text
    )


def test_window_order_plan_materializes_chained_pcode_gobj_hsd_obj_field_load(
) -> None:
    source = textwrap.dedent("""\
        typedef struct HSD_JObj HSD_JObj;
        typedef struct HSD_GObj HSD_GObj;
        typedef struct Diagram3 Diagram3;
        struct HSD_GObj {
            char pad0[0x28];
            /* 0x28 */ HSD_JObj* hsd_obj;
        };
        struct Diagram3 {
            char pad1[0x74];
            /* 0x74 */ HSD_GObj* popup_gobj;
        };
        void sink(HSD_JObj* jobj);

        void fn(HSD_GObj* gobj)
        {
            Diagram3* data;
            HSD_JObj* popup;
            data = gobj->user_data;
            popup = data->popup_gobj->hsd_obj;
            sink(popup);
        }
    """)

    first_def = {
        "block": "B3",
        "index": 33,
        "opcode": "lwz",
        "operands": "r42,40(r263)",
        "text": "lwz r42,40(r263)",
    }
    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 42, "order_move": ["before", 33]}],
        source_attributions={
            263: {
                "kind": "field-load",
                "expression": "data->popup_gobj",
                "base_var": "data",
                "base_type": "Diagram3*",
                "field_offset": 0x74,
            },
            42: {
                "kind": "load/store-address",
                "confidence": "pcode-first-def",
                "expression": "lwz r42,40(r263)",
                "base_virtual": 263,
                "field_offset": 40,
                "first_def": first_def,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert len(plan.probes) == 1
    probe = plan.probes[0]
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["base_virtual"] == 263
    assert diag["base_expression"] == "data->popup_gobj"
    assert diag["field_name"] == "hsd_obj"
    assert diag["base_source_attribution"]["kind"] == "field-load"
    assert diag["field_load_source_candidate"]["base_expression"] == (
        "data->popup_gobj"
    )
    assert diag["field_load_source_candidate"]["field_name"] == "hsd_obj"
    assert diag["source_hunks"]
    assert probe.provenance["kind"] == "pcode-first-def-field-load-source-order"
    assert probe.provenance["base_expression"] == "data->popup_gobj"
    assert probe.provenance["field_load_source_candidate"]["field_load_chain"]
    assert (
        "HSD_JObj* window_order_data_popup_gobj_hsd_obj_probe;"
        in probe.source_text
    )
    assert (
        "window_order_data_popup_gobj_hsd_obj_probe = "
        "data->popup_gobj->hsd_obj;"
    ) in probe.source_text
    assert "popup = window_order_data_popup_gobj_hsd_obj_probe;" in (
        probe.source_text
    )


def test_window_order_chained_pcode_field_load_probe_limit_is_bounded() -> None:
    source = textwrap.dedent("""\
        typedef struct HSD_JObj HSD_JObj;
        typedef struct HSD_GObj HSD_GObj;
        typedef struct Diagram3 Diagram3;
        struct HSD_GObj {
            char pad0[0x28];
            /* 0x28 */ HSD_JObj* hsd_obj;
        };
        struct Diagram3 {
            char pad1[0x74];
            /* 0x74 */ HSD_GObj* popup_gobj;
        };
        void sink(HSD_JObj* jobj);

        void fn(HSD_GObj* gobj)
        {
            Diagram3* data;
            HSD_JObj* popup;
            HSD_JObj* popup2;
            data = gobj->user_data;
            popup = data->popup_gobj->hsd_obj;
            popup2 = data->popup_gobj->hsd_obj;
            sink(popup);
            sink(popup2);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 42, "order_move": ["before", 33]}],
        source_attributions={
            263: {
                "kind": "field-load",
                "expression": "data->popup_gobj",
                "base_var": "data",
                "base_type": "Diagram3*",
                "field_offset": 0x74,
            },
            42: {
                "kind": "load/store-address",
                "confidence": "pcode-first-def",
                "expression": "lwz r42,40(r263)",
                "base_virtual": 263,
                "field_offset": 40,
            },
        },
        max_probes=1,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert len(plan.probes) == 1
    diag = plan.lead_diagnostics[0]
    summary = diag["field_load_materialization_summary"]
    assert summary["field_load_source_candidates"] == 2
    assert summary["materialized_field_load_source_candidates"] == 1
    assert summary["reasons"]["field-load-candidate-limit-exhausted"] == 1


def test_window_order_plan_recovers_chained_pcode_base_from_synthetic_field_at(
) -> None:
    source = textwrap.dedent("""\
        typedef struct HSD_JObj HSD_JObj;
        typedef struct HSD_GObj HSD_GObj;
        typedef struct Diagram3 Diagram3;
        struct HSD_GObj {
            char pad0[0x28];
            /* 0x28 */ HSD_JObj* hsd_obj;
        };
        struct Diagram3 {
            char pad1[0x74];
            /* 0x74 */ HSD_GObj* popup_gobj;
        };
        void sink(HSD_JObj* jobj);

        void fn(HSD_GObj* gobj)
        {
            Diagram3* data;
            Diagram3* text_data;
            HSD_JObj* popup;
            data = gobj->user_data;
            text_data = data;
            popup = data->popup_gobj->hsd_obj;
            sink(popup);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 42, "order_move": ["before", 33]}],
        source_attributions={
            263: {
                "kind": "field-load",
                "expression": "text_data->field_at_0x74",
                "base_var": "text_data",
                "base_type": "Diagram3*",
                "field_offset": 0x74,
            },
            42: {
                "kind": "load/store-address",
                "confidence": "pcode-first-def",
                "expression": "lwz r42,40(r263)",
                "base_virtual": 263,
                "field_offset": 40,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert len(plan.probes) == 1
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["field_load_source_probe"]["synthetic_base_expression"] == (
        "text_data->field_at_0x74"
    )
    assert diag["base_expression"] == "text_data->popup_gobj"
    candidate = diag["field_load_source_candidate"]
    assert candidate["kind"] == "same-offset-chained-source-field"
    assert candidate["base_expression"] == "data->popup_gobj"
    assert candidate["expression"] == "data->popup_gobj->hsd_obj"
    assert candidate["field_load_chain"][-1]["requested_base_expression"] == (
        "text_data->popup_gobj"
    )


def test_window_order_plan_terminal_proof_for_unresolved_pcode_field_load_base(
) -> None:
    source = textwrap.dedent("""\
        typedef struct HSD_GObj HSD_GObj;
        void sink(void* data);

        void fn(HSD_GObj* gobj)
        {
            void* data;
            data = gobj->user_data;
            sink(data);
        }
    """)

    first_def = {
        "block": "B0",
        "index": 12,
        "opcode": "lwz",
        "operands": "r67,44(r32)",
        "text": "lwz r67,44(r32)",
    }
    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 67, "order_move": ["before", 40]}],
        source_attributions={
            67: {
                "kind": "load/store-address",
                "confidence": "pcode-first-def",
                "expression": "lwz r67,44(r32)",
                "base_virtual": 32,
                "field_offset": 44,
                "first_def": first_def,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"] == "field-load-base-source-unresolved"
    assert diag["terminal_blocker"] != "unsupported-source-attribution-kind"
    assert diag["base_virtual"] == 32
    assert diag["field_offset"] == 44
    assert diag["pcode_first_def"] == first_def
    assert diag["base_source_attribution"] is None


def test_window_order_plan_rejects_pcode_field_store_address() -> None:
    source = textwrap.dedent("""\
        typedef struct HSD_GObj HSD_GObj;
        void sink(void* data);

        void fn(HSD_GObj* gobj)
        {
            void* data;
            data = gobj->user_data;
            sink(data);
        }
    """)

    first_def = {
        "block": "B0",
        "index": 12,
        "opcode": "stw",
        "operands": "r67,44(r32)",
        "text": "stw r67,44(r32)",
    }
    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 67, "order_move": ["before", 40]}],
        source_attributions={
            32: {"kind": "local", "name": "gobj", "type": "HSD_GObj*"},
            67: {
                "kind": "load/store-address",
                "confidence": "pcode-first-def",
                "expression": "stw r67,44(r32)",
                "base_virtual": 32,
                "field_offset": 44,
                "first_def": first_def,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"] == (
        "pcode-field-store-source-owner-unsupported-shape"
    )
    assert "field_load_source_probe" not in diag


def test_window_order_plan_materializes_implicit_add_owner_split() -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        void sink(int value);

        void fn(int seed)
        {
            int idx;
            u8* dst_iter;
            idx = seed;
            dst_iter = idx;
            sink(dst_iter);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 44, "order_move": ["before", 43]}],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 8},
            44: {
                "kind": "implicit-temp",
                "expression": "add r44,r49,r34",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    assert plan.lead_diagnostics[0]["status"] == "materialized"
    assert "source_diff" in plan.lead_diagnostics[0]
    assert (
        plan.lead_diagnostics[0]["synthetic_source_probe"]["handler"]
        == "implicit-add-owner-split"
    )
    synthetic_probe = plan.probes[0].provenance["synthetic_source_probe"]
    assert synthetic_probe["handler"] == "implicit-add-owner-split"
    assert "synthetic" in plan.probes[0].provenance["kind"]
    assert "u8*" in plan.probes[0].source_text
    assert "window_order_synthetic_dst_iter = idx;" in plan.probes[0].source_text
    assert "dst_iter = window_order_synthetic_dst_iter;" in plan.probes[0].source_text


def test_window_order_plan_materializes_li_constant_threshold_owner() -> None:
    source = textwrap.dedent("""\
        void sink(int value);

        void fn(int is_name, int scroll)
        {
            int threshold;
            int offset;
            if (is_name != 0) {
                threshold = 0x18;
            } else {
                threshold = 0x15;
            }
            if (scroll >= threshold) {
                offset = scroll - threshold;
            } else {
                offset = scroll;
            }
            sink(offset);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{
            "target_ig": 36,
            "order_move": ["before", 41],
            "perturbed_reg": 27,
        }],
        source_attributions={
            36: {
                "kind": "first-def",
                "expression": "li r36,24",
                "first_def": {"opcode": "li", "operands": "r36,24"},
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag.get("terminal_blocker") != "unsupported-source-attribution-kind"
    assert diag["source_hunks"]
    synthetic = diag["synthetic_source_probe"]
    assert synthetic["handler"] == "li-constant-threshold-owner"
    assert synthetic["immediate_value"] == 24
    candidate = synthetic["ranked_li_constant_source_candidates"][0]
    assert candidate["literal_text"] == "0x18"
    assert candidate["owner_local"] == "threshold"
    assert candidate["paired_literal"]["literal_text"] == "0x15"
    assert candidate["paired_literal"]["literal_value"] == 21
    assert synthetic["materialized_ranked_li_constant_source_candidates"]

    probe = plan.probes[0]
    assert probe.provenance["kind"] == "window-order-li-constant-source-probe"
    assert probe.provenance["source_hunks"]
    assert (
        probe.provenance["ranked_li_constant_source_candidate"]["owner_local"]
        == "threshold"
    )
    assert "int window_order_threshold_24_probe;" in probe.source_text
    assert "window_order_threshold_24_probe = 0x18;" in probe.source_text
    assert "threshold = window_order_threshold_24_probe;" in probe.source_text


def test_window_order_plan_li_constant_terminal_blocker_is_specific() -> None:
    source = textwrap.dedent("""\
        void fn(int scroll)
        {
            int threshold;
            threshold = 12;
            if (scroll >= threshold) {
                threshold = scroll;
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 36, "order_move": ["before", 41]}],
        source_attributions={
            36: {
                "kind": "first-def",
                "expression": "li r36,24",
                "first_def": {"opcode": "li", "operands": "r36,24"},
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert not plan.probes
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"] == "li-constant-source-owner-not-found"
    assert diag["terminal_blocker"] != "unsupported-source-attribution-kind"
    assert diag["synthetic_source_probe"]["handler"] == "li-constant-threshold-owner"
    assert diag["synthetic_source_probe"]["ranked_li_constant_source_candidates"] == []


def test_window_order_plan_materializes_pointer_walk_add_callarg_temp() -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        typedef struct HSD_JObj HSD_JObj;
        void lb_80011E24(HSD_JObj* root, HSD_JObj** out, int i, int sentinel);

        void fn(HSD_JObj* jobj, void* user_data)
        {
            int i;
            for (i = 0; i < 15; i++) {
                lb_80011E24(jobj, (HSD_JObj**) ((u8*) user_data + (i << 2) + 8), i,
                            -1);
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{
            "target_ig": 51,
            "order_move": ["before", "force-phys"],
            "perturbed_reg": 27,
        }],
        source_attributions={
            51: {
                "kind": "implicit-temp",
                "expression": "add r51,r45,r63",
                "first_def": {"opcode": "add", "operands": "r51,r45,r63"},
            },
            45: {
                "kind": "call-return",
                "expression": "HSD_MemAlloc(0xC8)",
                "source_line": 1037,
            },
            63: {
                "kind": "implicit-temp",
                "expression": "rlwinm r63,r37,2,0,29",
            },
            37: {"kind": "local", "name": "i", "type": "int"},
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag.get("terminal_blocker") != "synthetic-temp-operands-unattributed"
    assert diag["source_hunks"]
    synthetic = diag["synthetic_source_probe"]
    assert synthetic["ranked_pointer_walk_add_source_candidates"]
    assert synthetic["materialized_ranked_pointer_walk_add_source_candidates"]
    candidate = synthetic["ranked_pointer_walk_add_source_candidates"][0]
    assert candidate["base_expression"] == "user_data"
    assert candidate["index_expr"] == "i"
    assert candidate["shift"] == 2
    assert candidate["scale_bytes"] == 4
    assert candidate["offset_value"] == 8
    assert candidate["callee"] == "lb_80011E24"
    assert candidate["argument_index"] == 1
    assert "((u8*) user_data + (i << 2) + 8)" in candidate["argument_text"]

    probe = plan.probes[0]
    assert (
        probe.provenance["kind"]
        == "window-order-pointer-walk-add-source-probe"
    )
    assert probe.provenance["source_hunks"]
    assert (
        probe.provenance["ranked_pointer_walk_add_source_candidate"][
            "base_expression"
        ]
        == "user_data"
    )
    assert "HSD_JObj** window_order_user_data_jobj_probe;" in probe.source_text
    assert "window_order_user_data_jobj_probe =" in probe.source_text
    assert "lb_80011E24(jobj, window_order_user_data_jobj_probe, i," in (
        probe.source_text
    )


def test_window_order_plan_pointer_walk_add_terminal_blocker_is_specific() -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        typedef struct HSD_JObj HSD_JObj;
        void sink(HSD_JObj** out);
        void fn(void* user_data, int i)
        {
            sink((HSD_JObj**) ((u8*) user_data + (i++ << 2) + 8));
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 51, "order_move": ["before", "force-phys"]}],
        source_attributions={
            51: {"kind": "implicit-temp", "expression": "add r51,r45,r63"},
            45: {"kind": "call-return", "expression": "HSD_MemAlloc(0xC8)"},
            63: {"kind": "implicit-temp", "expression": "rlwinm r63,r37,2,0,29"},
            37: {"kind": "local", "name": "i", "type": "int"},
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert not plan.probes
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"] in {
        "pointer-walk-add-owner-not-materializable",
        "unsafe-pointer-walk-add-expression",
    }
    assert diag["terminal_blocker"] != "synthetic-temp-operands-unattributed"


def test_window_order_plan_materializes_generic_literal_and_pointer_walk_names(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        typedef struct Widget Widget;
        void attach_widget(Widget** out);
        void sink(int value);

        void generic(Widget* owner, void* arena, int mode, int slot)
        {
            int limit;
            int derived;
            if (mode) {
                limit = 12;
            } else {
                limit = 7;
            }
            attach_widget((Widget**) ((u8*) arena + (slot << 2) + 4));
            derived = limit + slot;
            sink(derived);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="generic",
        fallback_leads=[
            {"target_ig": 36, "order_move": ["before", 41]},
            {"target_ig": 51, "order_move": ["before", "force-phys"]},
        ],
        source_attributions={
            36: {
                "kind": "first-def",
                "expression": "li r36,12",
                "first_def": {"opcode": "li", "operands": "r36,12"},
            },
            51: {
                "kind": "implicit-temp",
                "expression": "add r51,r45,r63",
            },
            45: {"kind": "call-return", "expression": "AllocThing(0x40)"},
            63: {"kind": "implicit-temp", "expression": "rlwinm r63,r37,2,0,29"},
            37: {"kind": "local", "name": "slot", "type": "int"},
        },
        max_probes=6,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    kinds = {probe.provenance["kind"] for probe in plan.probes}
    assert "window-order-li-constant-source-probe" in kinds
    assert "window-order-pointer-walk-add-source-probe" in kinds

    constant_probe = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "window-order-li-constant-source-probe"
    )
    literal_candidate = constant_probe.provenance[
        "ranked_li_constant_source_candidate"
    ]
    assert literal_candidate["owner_local"] == "limit"
    assert literal_candidate["literal_text"] == "12"
    assert "window_order_limit_12_probe" in constant_probe.source_text

    pointer_probe = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "window-order-pointer-walk-add-source-probe"
    )
    pointer_candidate = pointer_probe.provenance[
        "ranked_pointer_walk_add_source_candidate"
    ]
    assert pointer_candidate["base_expression"] == "arena"
    assert pointer_candidate["index_expr"] == "slot"
    assert pointer_candidate["offset_value"] == 4
    assert pointer_candidate["callee"] == "attach_widget"
    assert "window_order_arena_widget_probe" in pointer_probe.source_text


def test_window_order_plan_materializes_pcode_addi_end_pointer_owner() -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        void fn(u8* dst, u8* common_source_r39_probe)
        {
            int i;
            {
                u8* ll_probe_iter_0 = common_source_r39_probe;
                u8* ll_probe_end_0 = dst + 0x78;
                for (i = 0; ll_probe_iter_0 < ll_probe_end_0; i++, ll_probe_iter_0++) {
                    *ll_probe_iter_0 = dst[i];
                }
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{
            "target_ig": 34,
            "order_move": ["before", "force-phys"],
            "perturbed_reg": 27,
        }],
        source_attributions={
            34: {
                "kind": "implicit-temp",
                "expression": "addi r34,r40,120",
            },
            40: {
                "kind": "implicit-temp",
                "expression": "addi r40,r51,28",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    probe = plan.probes[0]
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert probe.provenance["kind"] == (
        "window-order-ranked-end-pointer-source-probe"
    )
    synthetic = diag["synthetic_source_probe"]
    assert synthetic["ranked_end_pointer_source_candidates"]
    candidate = synthetic["ranked_end_pointer_source_candidates"][0]
    assert candidate["end_local"] == "ll_probe_end_0"
    assert candidate["iter_local"] == "ll_probe_iter_0"
    assert candidate["owner_assignment_text"] == "u8* ll_probe_end_0 = dst + 0x78;"
    assert "ranked_end_pointer_candidate_diagnostics" in diag
    assert "u8* ll_probe_end_0;\n" in probe.source_text
    assert "ll_probe_end_0 = dst + 0x78;" in probe.source_text
    assert "ll_probe_iter_0" in probe.source_text
    assert "common_source_r39_probe" in probe.source_text


def test_window_order_plan_end_pointer_candidate_terminal_blocker_is_specific(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        u8* get_end(void);
        void fn(u8* dst, u8* common_source_r39_probe)
        {
            int i;
            {
                u8* ll_probe_iter_0 = common_source_r39_probe;
                u8* ll_probe_end_0;
                ll_probe_end_0 = get_end();
                for (i = 0; ll_probe_iter_0 < ll_probe_end_0; i++, ll_probe_iter_0++) {
                    *ll_probe_iter_0 = i;
                }
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{
            "target_ig": 34,
            "order_move": ["before", "force-phys"],
            "perturbed_reg": 27,
        }],
        source_attributions={
            34: {
                "kind": "implicit-temp",
                "expression": "addi r34,r40,120",
            },
            40: {
                "kind": "implicit-temp",
                "expression": "addi r40,r51,28",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"] == "ranked-owner-candidates-not-materializable"
    reasons = {
        item.get("reason")
        for item in diag["ranked_end_pointer_candidate_diagnostics"]
    }
    assert "unsafe-end-pointer-expression" in reasons
    assert diag["terminal_blocker"] != "synthetic-temp-operands-unattributed"


def test_window_order_plan_materializes_gobj_user_data_field_load_source_probe(
) -> None:
    source = textwrap.dedent("""\
        typedef struct HSD_GObj HSD_GObj;
        typedef struct MnVibrationData MnVibrationData;
        struct MnVibrationData { void* jobjs[24]; };
        void sink(void*);

        void fn(HSD_GObj* gobj)
        {
            MnVibrationData* data;
            void* jobj;
            data = gobj->user_data;
            jobj = ((MnVibrationData*) gobj->user_data)->jobjs[23];
            sink(jobj);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 32, "order_move": ["before", 72]}],
        source_attributions={
            32: {
                "kind": "field-load",
                "expression": "gobj->field_at_0x2C",
                "base_var": "gobj",
                "field_offset": 44,
                "source_line": 10,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    probe = plan.probes[0]
    diag = plan.lead_diagnostics[0]
    assert probe.label.startswith("window-order-field-load-")
    assert probe.operator == "window-order-source-steering"
    assert probe.provenance["kind"] == "field-load-source-order"
    assert probe.provenance["source_attribution"]["kind"] == "field-load"
    assert probe.provenance["field_load_source_candidate"]["field_name"] == (
        "user_data"
    )
    assert probe.provenance["source_hunks"]
    assert "window_order_gobj_user_data_probe" in probe.source_text
    assert "window_order_gobj_user_data_probe = gobj->user_data;" in (
        probe.source_text
    )
    assert diag["status"] == "materialized"
    assert diag["field_load_source_candidate"]["field_name"] == "user_data"
    assert diag["source_hunks"]
    assert "unsupported-source-attribution-kind" not in {
        row.get("terminal_blocker") for row in plan.lead_diagnostics
    }


def test_window_order_plan_materializes_copy_coalesce_source_field_probe(
) -> None:
    source = textwrap.dedent("""\
        typedef struct HSD_GObj HSD_GObj;
        typedef struct Diagram3 Diagram3;
        struct Diagram3 { void* jobjs[24]; void* popup_gobj; };
        void sink(void*);

        void fn(HSD_GObj* gobj)
        {
            Diagram3* data;
            void* row0;
            data = gobj->user_data;
            row0 = data->jobjs[8];
            sink(row0);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{
            "target_ig": 66,
            "order_move": ["before", 41],
            "perturbed_reg": 30,
        }],
        source_attributions={
            66: {
                "kind": "copy/coalesce-source",
                "expression": "gobj->user_data",
                "base_virtual": 41,
                "base_var": "gobj",
                "field_offset": 44,
                "field_name": "user_data",
                "type": "Diagram3*",
                "source_line": 10,
                "copy_chain": [66, 41],
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    probe = plan.probes[0]
    diag = plan.lead_diagnostics[0]
    assert probe.label.startswith("window-order-field-load-ig66-before-inline-temp-")
    assert probe.operator == "window-order-source-steering"
    assert probe.provenance["kind"] == (
        "copy-coalesce-source-field-load-source-order"
    )
    assert probe.provenance["source_attribution"]["kind"] == "copy/coalesce-source"
    assert probe.provenance["source_attribution"]["copy_chain"] == [66, 41]
    assert probe.provenance["field_load_source_candidate"]["field_name"] == (
        "user_data"
    )
    assert probe.provenance["source_hunks"]
    assert "window_order_gobj_user_data_probe = gobj->user_data;" in (
        probe.source_text
    )
    assert diag["status"] == "materialized"
    assert diag["source_attribution_kind"] == "copy/coalesce-source"
    assert diag["copy_coalesce_source_probe"]["copy_chain"] == [66, 41]
    assert "unsupported-source-attribution-kind" not in {
        row.get("terminal_blocker") for row in plan.lead_diagnostics
    }


def test_window_order_copy_coalesce_source_unresolved_base_reports_field_blocker(
) -> None:
    source = textwrap.dedent("""\
        void sink(void*);

        void fn(void* gobj)
        {
            sink(gobj);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{
            "target_ig": 66,
            "order_move": ["before", 41],
            "perturbed_reg": 30,
        }],
        source_attributions={
            66: {
                "kind": "copy/coalesce-source",
                "expression": "gobj->field_at_0x2C",
                "base_var": "gobj",
                "field_offset": 44,
                "copy_chain": [66, 41],
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"].startswith("field-load-")
    assert diag["terminal_blocker"] == "field-load-base-type-unresolved"
    assert diag["terminal_blocker"] != "unsupported-source-attribution-kind"


def test_window_order_field_load_unknown_base_reports_specific_terminal_blocker(
) -> None:
    source = textwrap.dedent("""\
        void sink(void*);

        void fn(void* gobj)
        {
            sink(gobj);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 32, "order_move": ["before", 72]}],
        source_attributions={
            32: {
                "kind": "field-load",
                "expression": "gobj->field_at_0x2C",
                "base_var": "gobj",
                "field_offset": 44,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"].startswith("field-load-")
    assert diag["terminal_blocker"] == "field-load-base-type-unresolved"
    assert diag["terminal_blocker"] != "unsupported-source-attribution-kind"


def test_window_order_field_load_probe_limit_is_bounded() -> None:
    source = textwrap.dedent("""\
        typedef struct HSD_GObj HSD_GObj;
        typedef struct MnVibrationData MnVibrationData;
        struct MnVibrationData { void* jobjs[24]; };
        void sink(void*);

        void fn(HSD_GObj* gobj)
        {
            MnVibrationData* data;
            void* jobj;
            data = gobj->user_data;
            jobj = ((MnVibrationData*) gobj->user_data)->jobjs[23];
            sink(gobj->user_data);
            sink(jobj);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 32, "order_move": ["before", 72]}],
        source_attributions={
            32: {
                "kind": "field-load",
                "expression": "gobj->field_at_0x2C",
                "base_var": "gobj",
                "field_offset": 44,
            },
        },
        max_probes=1,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert len(plan.probes) == 1
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    summary = diag["field_load_materialization_summary"]
    assert summary["field_load_source_candidates"] >= 2
    assert summary["materialized_field_load_source_candidates"] == 1
    assert summary["reasons"]["field-load-candidate-limit-exhausted"] >= 1


def test_window_order_field_load_rejects_continuation_expression_line() -> None:
    source = textwrap.dedent("""\
        typedef struct HSD_GObj HSD_GObj;
        typedef struct MnVibrationData MnVibrationData;
        struct MnVibrationData { void* jobjs[24]; };

        void fn(HSD_GObj* gobj)
        {
            void* temp_jobj2;
            temp_jobj2 =
                ((MnVibrationData*) gobj->user_data)->jobjs[23];
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 32, "order_move": ["before", 72]}],
        source_attributions={
            32: {
                "kind": "field-load",
                "expression": "gobj->field_at_0x2C",
                "base_var": "gobj",
                "field_offset": 44,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"] == "field-load-no-safe-insertion-point"
    assert diag["field_load_materialization_summary"]["reasons"] == {
        "field-load-no-safe-insertion-point": 1
    }


def test_window_order_field_load_recovers_same_offset_when_base_is_wrong(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        typedef unsigned int u32;
        typedef struct DiagramData {
            /* 0x48 */ u8 is_name_mode;
        } DiagramData;
        void sink(int value);

        void fn(DiagramData* user_data, int threshold)
        {
            DiagramData* new_var;
            u32 is_name;
            new_var = user_data;
            if ((is_name = user_data->is_name_mode) != 0) {
                sink(is_name);
            }
            if (threshold != 0) {
                sink(threshold);
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 40, "order_move": ["before", 36]}],
        source_attributions={
            40: {
                "kind": "field-load",
                "expression": "threshold->field_at_0x48",
                "base_var": "threshold",
                "field_offset": 72,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag.get("terminal_blocker") != "field-load-field-name-unresolved"
    candidate = diag["field_load_source_candidate"]
    assert candidate["kind"] == "same-offset-source-field"
    assert candidate["base_var"] == "user_data"
    assert candidate["field_name"] == "is_name_mode"
    assert candidate["field_offset"] == 72
    assert candidate["owner_local"] == "is_name"
    assert candidate["owner_type"] == "u32"
    assert diag["field_load_source_probe"]["resolution_fallback"] == (
        "same-offset-source-field"
    )

    probe = plan.probes[0]
    assert "u32 window_order_user_data_is_name_mode_probe;" in probe.source_text
    assert (
        "window_order_user_data_is_name_mode_probe = user_data->is_name_mode;"
        in probe.source_text
    )
    assert (
        "if ((is_name = window_order_user_data_is_name_mode_probe) != 0) {"
        in probe.source_text
    )


def test_window_order_plan_materializes_gpr_copy_product_implicit_add_owner(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        void sink(int value);

        void fn(int seed)
        {
            int idx;
            u8* dst_iter;
            idx = seed;
            dst_iter = idx;
            sink(dst_iter);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={
            34: {
                "kind": "copy/coalesce-product",
                "expression": "mr r34,r44",
                "base_virtual": 44,
            },
            37: {"kind": "local", "name": "dst_iter", "source_line": 8},
            44: {
                "kind": "implicit-temp",
                "expression": "add r44,r49,r37",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert "source_diff" in diag
    assert diag["source_attribution"]["kind"] == "copy/coalesce-product"
    assert diag["copy_product_source"]["copy_product_source_ig"] == 44
    assert (
        diag["synthetic_source_probe"]["handler"]
        == "implicit-add-owner-split"
    )
    assert [
        entry["virtual"]
        for entry in diag["synthetic_source_probe"]["copy_chain"][:2]
    ] == [34, 44]
    assert (
        diag["synthetic_source_probe"]["copy_product_source_attribution"]["kind"]
        == "implicit-temp"
    )
    synthetic_probe = plan.probes[0].provenance["synthetic_source_probe"]
    assert synthetic_probe["handler"] == "implicit-add-owner-split"
    assert synthetic_probe["copy_product_expression"] == "mr r34,r44"
    assert "window_order_synthetic_dst_iter = idx;" in plan.probes[0].source_text
    assert "dst_iter = window_order_synthetic_dst_iter;" in plan.probes[0].source_text


def test_window_order_plan_blocks_unmapped_gpr_copy_product_source() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int dst_iter;
            dst_iter = seed;
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={
            34: {
                "kind": "copy/coalesce-product",
                "expression": "mr r34,r44",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "blocked"
    assert diag["terminal_blocker"] == "copy-product-source-unmapped"
    assert diag["copy_product_source"]["copy_product_source_ig"] == 44
    assert diag["synthetic_source_probe"]["copy_product_source_missing"] is True


def test_window_order_plan_materializes_fpr_sub_owner_split() -> None:
    source = textwrap.dedent("""\
        void sink(float value);

        void fn(float y_offset, int row)
        {
            float row_offset;
            float row_offset_adj;
            row_offset = y_offset * row;
            row_offset_adj = row_offset - 0.4f;
            sink(row_offset_adj);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 46, "order_move": ["before", 50]}],
        source_attributions={
            46: {
                "kind": "fpr-temp",
                "expression": "fsubs f46,f45,f44",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    assert plan.lead_diagnostics[0]["status"] == "materialized"
    assert "source_diff" in plan.lead_diagnostics[0]
    assert (
        plan.lead_diagnostics[0]["synthetic_source_probe"]["handler"]
        == "fpr-arith-owner-split"
    )
    synthetic_probe = plan.probes[0].provenance["synthetic_source_probe"]
    assert synthetic_probe["handler"] == "fpr-arith-owner-split"
    assert "synthetic" in plan.probes[0].provenance["kind"]
    assert (
        "window_order_synthetic_row_offset_adj = row_offset - 0.4f;"
        in plan.probes[0].source_text
    )
    assert (
        "row_offset_adj = window_order_synthetic_row_offset_adj;"
        in plan.probes[0].source_text
    )
    assert "    row_offset_adj = row_offset - 0.4f;" not in plan.probes[0].source_text


def test_window_order_plan_materializes_row_fsubs_call_owner_repairs() -> None:
    source = textwrap.dedent("""\
        typedef float f32;
        extern f32 HSD_JObjGetTranslationY(void* jobj);
        void sink(f32 value);

        void fn(void* jobj2, f32 base)
        {
            f32 row_offset;
            row_offset = HSD_JObjGetTranslationY(jobj2) - base;
            sink(row_offset);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 37, "order_move": ["before", 50]}],
        source_attributions={
            37: {
                "kind": "local",
                "name": "row_offset",
                "type": "f32",
                "source_line": 8,
                "expected_phys": 26,
                "expression": "HSD_JObjGetTranslationY(jobj2) - base",
                "first_def": {
                    "opcode": "fsubs",
                    "operands": "f37,f43,f38",
                },
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert len(plan.probes) == 2
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["synthetic_source_probe"]["handler"] == (
        "local-fpr-row-fsubs-owner-repair"
    )
    assert diag["synthetic_source_probe"]["candidate_id"] == (
        "row-fsubs-call-result-owner"
    )
    assert len(diag["synthetic_source_candidates"]) == 2
    by_id = {
        probe.provenance["synthetic_source_probe"]["candidate_id"]: probe
        for probe in plan.probes
    }
    call_owner = by_id["row-fsubs-call-result-owner"]
    assert "f32 window_order_synthetic_row_offset;" in call_owner.source_text
    assert (
        "window_order_synthetic_row_offset = HSD_JObjGetTranslationY(jobj2);"
        in call_owner.source_text
    )
    assert "row_offset = window_order_synthetic_row_offset - base;" in (
        call_owner.source_text
    )
    owner_temp = by_id["row-fsubs-owner-temp"]
    assert (
        "window_order_synthetic_row_offset = "
        "HSD_JObjGetTranslationY(jobj2) - base;"
    ) in owner_temp.source_text
    assert "row_offset = window_order_synthetic_row_offset;" in (
        owner_temp.source_text
    )
    for meta in diag["synthetic_source_candidates"]:
        assert meta["handler"] == "local-fpr-row-fsubs-owner-repair"
        assert meta["owner_local"] == "row_offset"
        assert meta["original_rhs"] == "HSD_JObjGetTranslationY(jobj2) - base"
        assert meta["call_expr"] == "HSD_JObjGetTranslationY(jobj2)"
        assert meta["base_local"] == "base"
        assert meta["target_ig"] == 37
        assert meta["expected_phys"] == 26
        assert meta["requires_expression_score_validation"] is True


def test_window_order_plan_prefers_fpr_conversion_consumer_cast_owner() -> None:
    source = textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn(f32 y_spacing, int col, f32 row_offset)
        {
            f32 col_offset;
            f32 row_offset_adj;
            col_offset = y_spacing * (f32) col;
            row_offset_adj = row_offset - 0.4f;
            sink(col_offset + row_offset_adj);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 46, "order_move": ["before", 50]}],
        source_attributions={
            32: {
                "kind": "local",
                "name": "col_offset",
                "type": "f32",
                "source_line": 8,
                "expression": "y_spacing * (f32) col",
                "first_def": {
                    "opcode": "fmuls",
                    "operands": "f32,f34,f46",
                },
            },
            46: {
                "kind": "fpr-temp",
                "expression": "fsubs f46,f45,f44",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["source_local"] == "col_offset"
    assert diag["synthetic_source_probe"]["handler"] == "fpr-conversion-owner-split"
    assert diag["synthetic_source_probe"]["consumer_ig"] == 32
    assert diag["synthetic_source_probe"]["operand_ig"] == 46
    assert diag["synthetic_source_probe"]["split_expression"] == "(f32) col"
    assert "window_order_synthetic_col_offset = (f32) col;" in plan.probes[0].source_text
    assert "col_offset = y_spacing * window_order_synthetic_col_offset;" in plan.probes[0].source_text
    assert "row_offset_adj = row_offset - 0.4f;" in plan.probes[0].source_text


def test_window_order_plan_materializes_fpr_lfs_owner_split() -> None:
    source = textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn(int row)
        {
            f32 rowf;
            rowf = (f32) row;
            sink(rowf);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 38, "order_move": ["before", 50]}],
        source_attributions={
            38: {
                "kind": "fpr-temp",
                "expression": "lfs f38,60(r47)",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["synthetic_source_probe"]["handler"] == "fpr-load-owner-split"
    assert "source_diff" in diag
    assert "window_order_synthetic_rowf = (f32) row;" in plan.probes[0].source_text
    assert "rowf = window_order_synthetic_rowf;" in plan.probes[0].source_text


def test_window_order_plan_keeps_duplicate_fpr_source_for_distinct_targets() -> None:
    source = textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn(int row)
        {
            f32 rowf;
            rowf = (f32) row;
            sink(rowf);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[
            {"target_ig": 38, "order_move": ["before", 50]},
            {"target_ig": 39, "order_move": ["before", 50]},
        ],
        source_attributions={
            38: {
                "kind": "fpr-temp",
                "expression": "lfs f38,60(r47)",
            },
            39: {
                "kind": "fpr-temp",
                "expression": "lfs f39,60(r47)",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert [diag["status"] for diag in plan.lead_diagnostics] == [
        "materialized",
        "materialized",
    ]
    assert [
        probe.provenance["lead"]["target_ig"]
        for probe in plan.probes
    ] == [38, 39]
    assert plan.probes[0].source_text == plan.probes[1].source_text


def test_window_order_plan_materializes_fpr_lfs_cast_fragment_split() -> None:
    source = textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn(f32 y_offset, int row)
        {
            f32 row_offset;
            row_offset = y_offset * (f32) row;
            sink(row_offset);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 38, "order_move": ["before", 50]}],
        source_attributions={
            38: {
                "kind": "fpr-temp",
                "expression": "lfs f38,60(r47)",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["synthetic_source_probe"]["split_expression"] == "(f32) row"
    assert (
        "window_order_synthetic_row_offset = (f32) row;"
        in plan.probes[0].source_text
    )
    assert (
        "row_offset = y_offset * window_order_synthetic_row_offset;"
        in plan.probes[0].source_text
    )


def test_window_order_plan_rejects_type_mismatched_fpr_lfs_cast_fragment() -> None:
    source = textwrap.dedent("""\
        void sink(float value);

        void fn(float scale, int row)
        {
            float row_offset;
            row_offset = scale * (double) row;
            sink(row_offset);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 38, "order_move": ["before", 50]}],
        source_attributions={
            38: {
                "kind": "fpr-temp",
                "expression": "lfs f38,60(r47)",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    assert (
        plan.lead_diagnostics[0]["terminal_blocker"]
        == "fpr-first-def-source-owner-missing"
    )


def test_window_order_plan_materializes_ambiguous_fpr_lfs_candidates() -> None:
    source = textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn(int col, int row)
        {
            f32 colf;
            f32 rowf;
            colf = (f32) col;
            rowf = (f32) row;
            sink(colf + rowf);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 38, "order_move": ["before", 50]}],
        source_attributions={
            38: {
                "kind": "fpr-temp",
                "expression": "lfs f38,60(r47)",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert len(plan.probes) == 2
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["synthetic_source_probe"]["candidate_count"] == 2
    assert len(diag["synthetic_source_candidates"]) == 2


def test_window_order_plan_reports_unattributed_implicit_add_operand() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int dst_iter;
            dst_iter = seed;
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 44, "order_move": ["before", 43]}],
        source_attributions={
            44: {
                "kind": "implicit-temp",
                "expression": "add r44,r49,r34",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    assert (
        plan.lead_diagnostics[0]["terminal_blocker"]
        == "synthetic-temp-operands-unattributed"
    )


def test_window_order_plan_reports_ranked_gpr_local_owner_candidates_for_loop_index(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        void fn(u8 temp)
        {
            int i;
            int max_idx;
            u8* ll_probe_iter_0;
            u8 dst[0x78];
            ll_probe_iter_0 = dst;
            for (i = 0; i < 0x78; i++, ll_probe_iter_0++) {
                max_idx = i;
                *ll_probe_iter_0 = temp;
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={
            34: {
                "kind": "local",
                "name": "i",
                "type": "int",
                "source_line": 4,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert plan.probes
    assert any(
        probe.provenance["kind"] == "window-order-ranked-local-owner-source-probe"
        for probe in plan.probes
    )
    assert "int window_order_i_probe;" in plan.probes[0].source_text
    assert "max_idx = window_order_i_probe;" in plan.probes[0].source_text
    candidates = diag["ranked_source_owner_candidates"]
    kinds = {candidate["kind"] for candidate in candidates}
    assert "loop-index-declaration" in kinds
    assert "loop-index-header" in kinds
    assert "loop-body-read" in kinds
    assert "loop-indexed-byte-expression" in kinds
    declaration = next(
        candidate for candidate in candidates
        if candidate["kind"] == "loop-index-declaration"
    )
    assert declaration["local"] == "i"
    assert declaration["span_text"].strip() == "int i;"
    assert declaration["line_start"] == 4
    body_read = next(
        candidate for candidate in candidates
        if candidate["kind"] == "loop-body-read"
    )
    assert body_read["span_text"].strip() == "max_idx = i;"
    assert body_read["source_span"][0] < body_read["source_span"][1]
    assert body_read["byte_span"][0] < body_read["byte_span"][1]
    diagnostics = diag["ranked_source_owner_candidate_diagnostics"]
    reasons = {item.get("reason") for item in diagnostics}
    assert "non-executable-declaration-span" in reasons
    assert "unsupported-loop-header-owner" in reasons
    assert diag["materialized_ranked_source_owner_candidates"]


def test_window_order_plan_attributes_unattributed_implicit_add_to_indexed_byte_candidates(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        void fn(u8* dst, u8 temp)
        {
            int i;
            u8* ll_probe_iter_0;
            ll_probe_iter_0 = dst;
            for (i = 0; i < 0x78; i++, ll_probe_iter_0++) {
                temp = dst[i];
                *ll_probe_iter_0 = temp;
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 44, "order_move": ["after", 34]}],
        source_attributions={
            44: {
                "kind": "implicit-temp",
                "expression": "addi r44,r50,28",
            },
            50: {
                "kind": "copy/coalesce-product",
                "expression": "mr r50,r52",
                "base_virtual": 52,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert plan.probes
    assert any(
        probe.provenance["kind"] == "window-order-ranked-indexed-byte-source-probe"
        for probe in plan.probes
    )
    synthetic_probe = diag["synthetic_source_probe"]
    assert [entry["virtual"] for entry in synthetic_probe["copy_chain"][:2]] == [
        44,
        50,
    ]
    assert synthetic_probe["copy_chain"][1]["kind"] == "copy/coalesce-product"
    candidates = synthetic_probe["ranked_indexed_byte_source_candidates"]
    assert candidates
    assert any(
        candidate["array_base"] == "dst" and candidate["index_expr"] == "i"
        for candidate in candidates
    )
    pointer_candidate = next(
        candidate for candidate in candidates
        if candidate["span_text"].strip() == "*ll_probe_iter_0 = temp;"
    )
    assert pointer_candidate["array_base"] == "ll_probe_iter_0"
    assert pointer_candidate["index_expr"] == "i"
    assert "steer_indexed_byte_implicit_init_loop_indexed_store" in (
        pointer_candidate["mutator_keys"]
    )
    assert synthetic_probe["materialized_ranked_indexed_byte_source_candidates"]


def test_window_order_plan_rejects_array_declarator_indexed_byte_candidate(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        typedef unsigned int u32;
        void fn(u8* dst, int i)
        {
            u32 totals[0x78];
            u8 temp;
            temp = dst[i];
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 44, "order_move": ["after", 34]}],
        source_attributions={
            44: {
                "kind": "implicit-temp",
                "expression": "addi r44,r50,28",
            },
            50: {
                "kind": "copy/coalesce-product",
                "expression": "mr r50,r52",
                "base_virtual": 52,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    diag = plan.lead_diagnostics[0]
    synthetic_probe = diag["synthetic_source_probe"]
    candidates = synthetic_probe["ranked_indexed_byte_source_candidates"]
    assert any(
        candidate["span_text"].strip() == "u32 totals[0x78];"
        and candidate["is_array_declarator"] is True
        for candidate in candidates
    )
    for probe in plan.probes:
        ranked = probe.provenance.get("ranked_indexed_byte_source_candidate")
        assert not (
            isinstance(ranked, dict)
            and ranked.get("span_text", "").strip() == "u32 totals[0x78];"
        )
    diagnostics = synthetic_probe["ranked_indexed_byte_candidate_diagnostics"]
    assert any(
        item.get("reason") == "array-declarator-not-indexed-expression"
        for item in diagnostics
    )
    assert any(
        item.get("status") == "materialized"
        and item.get("array_base") == "dst"
        for item in diagnostics
    )


def test_window_order_plan_materializes_ranked_indexed_byte_candidates_for_unattributed_add(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        typedef unsigned int u32;
        void* GetNameText(u8 value);
        void fn(u8* sorted_names, u32* totals, int max_idx, int j)
        {
            if ((GetNameText(sorted_names[j]) != 0) &&
                (totals[sorted_names[max_idx]] < totals[sorted_names[j]])) {
                max_idx = j;
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 44, "order_move": ["after", 34]}],
        source_attributions={
            44: {
                "kind": "implicit-temp",
                "expression": "addi r44,r50,28",
            },
            50: {
                "kind": "copy/coalesce-product",
                "expression": "mr r50,r52",
                "base_virtual": 52,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    probe = plan.probes[0]
    assert probe.operator == "window-order-source-steering"
    assert probe.provenance["kind"] == (
        "window-order-ranked-indexed-byte-source-probe"
    )
    assert "int window_order_" in probe.source_text
    assert "_probe = " in probe.source_text
    assert "[window_order_" in probe.source_text
    diag = plan.lead_diagnostics[0]
    assert "terminal_blocker" not in diag
    synthetic_probe = diag["synthetic_source_probe"]
    assert [entry["virtual"] for entry in synthetic_probe["copy_chain"][:2]] == [
        44,
        50,
    ]
    assert synthetic_probe["materialized_ranked_indexed_byte_source_candidates"]
    diagnostics = synthetic_probe["ranked_indexed_byte_candidate_diagnostics"]
    assert any(
        item.get("reason") == "continuation-line-indexed-expression"
        for item in diagnostics
    )
    for probe in plan.probes:
        lines = probe.source_text.splitlines()
        for prev, line in zip(lines, lines[1:]):
            assert not (
                prev.rstrip().endswith("&&")
                and line.strip().startswith("window_order_")
            )


def test_window_order_plan_keeps_default_one_ranked_indexed_byte_candidate(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        void fn(u8* sorted_names, int max_idx, int j)
        {
            u8 current;
            u8 alternate;
            current = sorted_names[max_idx];
            alternate = sorted_names[j];
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["after", 32]}],
        source_attributions={
            34: {
                "kind": "copy/coalesce-product",
                "expression": "mr r34,r44",
                "base_virtual": 44,
            },
            44: {"kind": "implicit-temp", "expression": "addi r44,r50,28"},
            50: {
                "kind": "copy/coalesce-product",
                "expression": "mr r50,r52",
                "base_virtual": 52,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    ranked = [
        probe for probe in plan.probes
        if probe.provenance["kind"] == "window-order-ranked-indexed-byte-source-probe"
    ]
    assert len(ranked) == 1
    diag = plan.lead_diagnostics[0]
    summary = diag["ranked_indexed_byte_materialization_summary"]
    assert summary["ranked_indexed_byte_candidates"] >= 2
    assert summary["materialized_indexed_byte_candidates"] == 1
    assert summary["per_target_materialization_limit"] == 1


def test_window_order_plan_can_materialize_later_ranked_indexed_byte_candidates(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        void fn(u8* sorted_names, int max_idx, int j)
        {
            u8 current;
            u8 alternate;
            current = sorted_names[max_idx];
            alternate = sorted_names[j];
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["after", 32]}],
        source_attributions={
            34: {
                "kind": "copy/coalesce-product",
                "expression": "mr r34,r44",
                "base_virtual": 44,
            },
            44: {"kind": "implicit-temp", "expression": "addi r44,r50,28"},
            50: {
                "kind": "copy/coalesce-product",
                "expression": "mr r50,r52",
                "base_virtual": 52,
            },
        },
        max_probes=4,
        ranked_indexed_byte_candidates_per_target=3,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    ranked = [
        probe for probe in plan.probes
        if probe.provenance["kind"] == "window-order-ranked-indexed-byte-source-probe"
    ]
    assert len(ranked) >= 2
    ranks = [
        probe.provenance["ranked_indexed_byte_source_candidate"]["rank"]
        for probe in ranked
    ]
    assert ranks[:2] == [1, 2]
    assert any("alternate = sorted_names[window_order_" in probe.source_text for probe in ranked)
    diag = plan.lead_diagnostics[0]
    summary = diag["ranked_indexed_byte_materialization_summary"]
    assert summary["materialized_indexed_byte_candidates"] >= 2
    assert summary["per_target_materialization_limit"] == 3


def test_window_order_plan_rejects_expression_continuation_indexed_byte_candidate(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        typedef unsigned int u32;
        void fn(u8* sorted_names, u32* totals, int max_idx, int j)
        {
            u8 current;
            u8 alternate;
            current = sorted_names[max_idx];
            alternate = sorted_names[j];
            if ((totals[current] <
                 totals[alternate]) ||
                (totals[sorted_names[j]] != 0)) {
                max_idx = j;
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["after", 32]}],
        source_attributions={
            34: {
                "kind": "copy/coalesce-product",
                "expression": "mr r34,r44",
                "base_virtual": 44,
            },
            44: {"kind": "implicit-temp", "expression": "addi r44,r50,28"},
            50: {
                "kind": "copy/coalesce-product",
                "expression": "mr r50,r52",
                "base_virtual": 52,
            },
        },
        max_probes=8,
        ranked_indexed_byte_candidates_per_target=8,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    diagnostics = plan.lead_diagnostics[0][
        "ranked_indexed_byte_candidate_diagnostics"
    ]
    assert any(
        item.get("reason") == "expression-context-indexed-expression"
        and str(item.get("span_text", "")).startswith("totals[alternate]")
        for item in diagnostics
    )
    for probe in plan.probes:
        assert "window_order_totals_index_probe = alternate;" not in probe.source_text
        assert "totals[window_order_totals_index_probe]) ||" not in probe.source_text


def test_target_aware_live_range_repair_materializes_bounded_probe_classes(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        typedef unsigned int u32;
        void* GetNameText(u8 value);
        void fn(u8* sorted_names, u32* totals, int max_idx, int j)
        {
            if ((GetNameText(sorted_names[j]) != 0) &&
                (totals[sorted_names[max_idx]] < totals[sorted_names[j]])) {
                max_idx = j;
            }
        }
    """)

    plan = plan_target_aware_live_range_repair_probes(
        source,
        function="fn",
        repair_goals=[{
            "kind": "target-aware-live-range-interference",
            "target_ig": 44,
            "target_phys": 25,
            "protected_targets": {"34": 27},
            "interferer_ig": 39,
            "interferer_phys": 25,
            "source_expression": "sorted_names[j]",
            "required_delta": 6,
        }],
        max_probes=8,
    )

    assert plan.probes
    kinds = {probe.provenance["kind"] for probe in plan.probes}
    assert {
        "target-aware-live-range-anchor",
        "target-aware-interference-shape",
        "target-aware-address-side-temp",
        "target-aware-value-side-temp",
        "target-aware-coupled-address-value",
    } <= kinds
    for probe in plan.probes:
        provenance = probe.provenance
        assert provenance["target_ig"] == 44
        assert provenance["target_phys"] == 25
        assert provenance["interferer_ig"] == 39
        assert provenance["interferer_phys"] == 25
        assert provenance["protected_targets"] == {"34": 27}
        assert provenance["required_delta"] == 6
        assert provenance["repair_goal"]["source_expression"] == "sorted_names[j]"
        assert probe.source_text != source

    address_probe = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "target-aware-address-side-temp"
    )
    assert "&sorted_names[max_idx]" in address_probe.source_text
    assert "target_repair_address_ig44_max_idx_probe" in address_probe.source_text
    assert address_probe.source_text.index(
        "target_repair_address_ig44_max_idx_probe = &sorted_names[max_idx];"
    ) < address_probe.source_text.index("if ((GetNameText")

    value_probe = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "target-aware-value-side-temp"
    )
    assert (
        "target_repair_value_ig39_j_probe = sorted_names[j];"
        in value_probe.source_text
    )
    assert (
        "target_repair_value_ig41_j_probe = target_repair_value_ig39_j_probe;"
        in value_probe.source_text
    )
    assert "GetNameText(target_repair_value_ig41_j_probe)" in value_probe.source_text

    coupled_probe = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "target-aware-coupled-address-value"
    )
    assert "&sorted_names[max_idx]" in coupled_probe.source_text
    assert "target_repair_value_ig39_j_probe" in coupled_probe.source_text
    assert coupled_probe.source_text.index(
        "target_repair_address_ig44_max_idx_probe = &sorted_names[max_idx];"
    ) < coupled_probe.source_text.index("if ((GetNameText")


def test_target_aware_live_range_repair_materializes_fpr_scalar_shape_probes(
) -> None:
    source = textwrap.dedent("""\
        typedef float f32;
        typedef struct HSD_JObj HSD_JObj;
        void HSD_JObjSetTranslateX(HSD_JObj*, f32);
        void HSD_JObjSetTranslateY(HSD_JObj*, f32);
        void fn(HSD_JObj* jobj, int col, f32 row_offset)
        {
            f32 col_offset_product_fpr;
            f32 col_offset;
            f32 row_offset_adj;
            col_offset_product_fpr = (f32) col * 10.0f;
            col_offset = col_offset_product_fpr;
            row_offset_adj = row_offset - 0.4f;
            HSD_JObjSetTranslateX(jobj, col_offset);
            HSD_JObjSetTranslateY(jobj, row_offset_adj);
        }
    """)

    plan = plan_target_aware_live_range_repair_probes(
        source,
        function="fn",
        repair_goals=[{
            "kind": "target-aware-fpr-live-range-interference",
            "target_ig": 37,
            "target_phys": 26,
            "protected_targets": {"32": 26},
            "interferer_ig": 37,
            "interferer_phys": 26,
            "source_expression": "row_offset_adj",
            "paired_source_expression": "col_offset",
            "paired_interferer_ig": 32,
            "source_type": "f32",
            "required_delta": 1,
        }],
        max_probes=6,
    )

    kinds = {probe.provenance["kind"] for probe in plan.probes}
    assert {
        "target-aware-scalar-interference-shape",
        "target-aware-scalar-pair-overlap",
    } <= kinds
    duplicate_probe = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "target-aware-scalar-interference-shape"
    )
    assert (
        "target_repair_scalar_ig37_probe = row_offset_adj;"
        in duplicate_probe.source_text
    )
    assert (
        "target_repair_scalar_duplicate_ig37_probe = "
        "target_repair_scalar_ig37_probe;"
    ) in duplicate_probe.source_text
    assert (
        "HSD_JObjSetTranslateY(jobj, "
        "target_repair_scalar_duplicate_ig37_probe);"
    ) in duplicate_probe.source_text

    pair_probe = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "target-aware-scalar-pair-overlap"
    )
    assert "target_repair_scalar_pair_ig32_probe = col_offset;" in (
        pair_probe.source_text
    )
    assert "target_repair_scalar_pair_ig37_probe = row_offset_adj;" in (
        pair_probe.source_text
    )
    assert (
        "HSD_JObjSetTranslateX(jobj, target_repair_scalar_pair_ig32_probe);"
        in pair_probe.source_text
    )
    assert (
        "HSD_JObjSetTranslateY(jobj, target_repair_scalar_pair_ig37_probe);"
        in pair_probe.source_text
    )


def test_target_aware_live_range_repair_handles_parenthesized_address_index(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        typedef unsigned int u32;
        void* GetNameText(u8 value);
        void fn(u8* sorted_names, u32* totals, int max_idx, int j)
        {
            if ((GetNameText(sorted_names[j]) != 0) &&
                (totals[sorted_names[(max_idx)]] < totals[sorted_names[j]])) {
                max_idx = j;
            }
        }
    """)

    plan = plan_target_aware_live_range_repair_probes(
        source,
        function="fn",
        repair_goals=[{
            "kind": "target-aware-live-range-interference",
            "target_ig": 44,
            "target_phys": 25,
            "protected_targets": {"34": 27},
            "interferer_ig": 39,
            "interferer_phys": 25,
            "source_expression": "sorted_names[j]",
            "address_source_expression": "sorted_names[max_idx]",
            "required_delta": 6,
        }],
        max_probes=12,
    )

    kinds = {probe.provenance["kind"] for probe in plan.probes}
    assert {
        "target-aware-address-side-temp",
        "target-aware-coupled-address-value",
        "target-aware-implicit-index-normalize",
        "target-aware-implicit-index-alias",
        "target-aware-implicit-base-alias",
    } <= kinds
    normalize_probe = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "target-aware-implicit-index-normalize"
    )
    assert "sorted_names[max_idx]" in normalize_probe.source_text
    assert "sorted_names[(max_idx)]" not in normalize_probe.source_text
    index_alias = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "target-aware-implicit-index-alias"
    )
    assert "target_repair_index_ig44_max_idx_probe = max_idx;" in index_alias.source_text
    assert "sorted_names[target_repair_index_ig44_max_idx_probe]" in index_alias.source_text
    base_alias = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "target-aware-implicit-base-alias"
    )
    assert "target_repair_base_ig44_probe = sorted_names;" in base_alias.source_text
    assert "target_repair_base_ig44_probe[(max_idx)]" in base_alias.source_text


def test_target_aware_live_range_repair_default_address_finds_parenthesized_index(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        typedef unsigned int u32;
        void* GetNameText(u8 value);
        void fn(u8* sorted_names, u32* totals, int max_idx, int j)
        {
            if ((GetNameText(sorted_names[j]) != 0) &&
                (totals[sorted_names[(max_idx)]] < totals[sorted_names[j]])) {
                max_idx = j;
            }
        }
    """)

    plan = plan_target_aware_live_range_repair_probes(
        source,
        function="fn",
        repair_goals=[{
            "kind": "target-aware-live-range-interference",
            "target_ig": 44,
            "target_phys": 25,
            "protected_targets": {"34": 27},
            "interferer_ig": 39,
            "interferer_phys": 25,
            "source_expression": "sorted_names[j]",
            "required_delta": 6,
        }],
        max_probes=12,
    )

    kinds = {probe.provenance["kind"] for probe in plan.probes}
    assert {
        "target-aware-address-side-temp",
        "target-aware-coupled-address-value",
        "target-aware-implicit-index-normalize",
    } <= kinds
    address_probe = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "target-aware-address-side-temp"
    )
    assert "&sorted_names[(max_idx)]" in address_probe.source_text
    coupled_probe = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "target-aware-coupled-address-value"
    )
    assert "&sorted_names[(max_idx)]" in coupled_probe.source_text


def test_target_aware_live_range_repair_keeps_statement_alias_inside_loop(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        typedef unsigned int u32;
        void fn(u8* sorted_names, u32* totals)
        {
            u8 left;
            u8 right;
            int i;
            int j;
            int max_idx;
            for (i = 0; i < 4; i++) {
                max_idx = i;
                for (j = i + 1; j < 4; j++) {
                    left = sorted_names[(max_idx)];
                    right = sorted_names[j];
                    if (totals[left] < totals[right]) {
                        max_idx = j;
                    }
                }
            }
        }
    """)

    plan = plan_target_aware_live_range_repair_probes(
        source,
        function="fn",
        repair_goals=[{
            "kind": "target-aware-live-range-interference",
            "target_ig": 44,
            "target_phys": 25,
            "protected_targets": {"34": 27},
            "interferer_ig": 39,
            "interferer_phys": 25,
            "source_expression": "sorted_names[j]",
            "required_delta": 6,
        }],
        max_probes=12,
    )

    index_alias = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "target-aware-implicit-index-alias"
    )
    assert (
        "for (j = i + 1; j < 4; j++) {\n"
        "            target_repair_index_ig44_max_idx_probe = max_idx;\n"
        "            left = sorted_names[target_repair_index_ig44_max_idx_probe];"
    ) in index_alias.source_text
    assert (
        "max_idx = i;\n"
        "            target_repair_index_ig44_max_idx_probe = max_idx;\n"
        "            for (j = i + 1; j < 4; j++) {"
    ) not in index_alias.source_text


def test_target_aware_live_range_repair_does_not_normalize_comma_index(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        typedef unsigned int u32;
        void* GetNameText(u8 value);
        void fn(u8* sorted_names, u32* totals, int max_idx, int j)
        {
            if ((GetNameText(sorted_names[j]) != 0) &&
                (totals[sorted_names[(0, max_idx)]] < totals[sorted_names[j]])) {
                max_idx = j;
            }
        }
    """)

    plan = plan_target_aware_live_range_repair_probes(
        source,
        function="fn",
        repair_goals=[{
            "kind": "target-aware-live-range-interference",
            "target_ig": 44,
            "target_phys": 25,
            "protected_targets": {"34": 27},
            "interferer_ig": 39,
            "interferer_phys": 25,
            "source_expression": "sorted_names[j]",
            "address_source_expression": "sorted_names[(0, max_idx)]",
            "required_delta": 6,
        }],
        max_probes=12,
    )

    kinds = {probe.provenance["kind"] for probe in plan.probes}
    assert "target-aware-implicit-index-normalize" not in kinds
    assert "target-aware-implicit-index-alias" not in kinds
    reasons = {
        diagnostic.get("reason")
        for diagnostic in plan.lead_diagnostics[0]["repair_candidate_diagnostics"]
    }
    assert "unsafe-address-expression" in reasons


def test_target_aware_live_range_repair_reports_missing_source_binding(
) -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        void fn(u8* sorted_names, int j)
        {
            (void) sorted_names[j];
        }
    """)

    plan = plan_target_aware_live_range_repair_probes(
        source,
        function="fn",
        repair_goals=[{
            "kind": "target-aware-live-range-interference",
            "target_ig": 44,
            "target_phys": 25,
            "protected_targets": {"34": 27},
            "interferer_ig": 39,
            "interferer_phys": 25,
            "required_delta": 6,
        }],
        max_probes=4,
    )

    assert plan.probes == []
    assert plan.lead_diagnostics
    assert plan.lead_diagnostics[0]["terminal_blocker"] == (
        "missing-interferer-source-binding"
    )


def test_window_order_plan_explains_ranked_candidates_when_none_materialize(
) -> None:
    source = textwrap.dedent("""\
        void fn(void)
        {
            int i;
            for (i = 0; i < 10; i++) {
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={
            34: {
                "kind": "local",
                "name": "i",
                "type": "int",
                "source_line": 3,
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"] == "ranked-owner-candidates-not-materializable"
    summary = diag["ranked_source_owner_materialization_summary"]
    assert summary["ranked_local_candidates"] >= 2
    assert summary["materialized_local_candidates"] == 0
    assert summary["reasons"]["non-executable-declaration-span"] == 1
    assert summary["reasons"]["unsupported-loop-header-owner"] == 1


def test_window_order_plan_reports_ambiguous_movable_local_write() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int dst_iter;
            dst_iter = seed;
            if (seed != 0) {
                dst_iter = seed;
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 4},
        },
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    assert plan.lead_diagnostics[0]["status"] == "blocked"
    assert (
        plan.lead_diagnostics[0]["terminal_blocker"]
        == "ambiguous-movable-local-write"
    )
    assert plan.lead_diagnostics[0]["movable_write_count"] == 2


def test_window_order_plan_reports_implicit_temp_no_safe_source_move() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int idx;
            int dst_iter;
            idx = seed;
            dst_iter = idx;
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={
            34: {
                "kind": "implicit-temp",
                "expression": "r35 + r36",
                "source_line": 6,
            },
        },
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    assert plan.lead_diagnostics[0]["status"] == "blocked"
    assert (
        plan.lead_diagnostics[0]["terminal_blocker"]
        == "synthetic-temp-unsupported-shape"
    )


def test_window_order_plan_reports_no_legal_destination() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int dst_iter;
            dst_iter = seed;
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["after", 43]}],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 4},
        },
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes == []
    assert plan.lead_diagnostics[0]["status"] == "blocked"
    assert plan.lead_diagnostics[0]["terminal_blocker"] == "no-legal-destination"
    assert plan.lead_diagnostics[0]["candidate_destinations"] == []


def test_window_order_plan_generates_pointer_walk_lever_for_no_legal_destination() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int n;
            int* dst_iter;
            int* tp;
            int dst[4];
            int totals[4];
            dst_iter = dst;
            tp = totals;
            for (n = 0; n < 4; n++, dst_iter++, tp++) {
                *dst_iter = n;
                *tp = seed + n;
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 8},
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    pointer_probe = next(
        probe for probe in plan.probes
        if probe.provenance["kind"] == "window-order-local-pointer-walk-source-move"
    )
    assert pointer_probe.operator == "window-order-source-steering"
    assert "for (n = 0; n < 4; n++, tp++) {" in pointer_probe.source_text
    assert "        dst_iter++;\n    }" in pointer_probe.source_text
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["local_lifetime_probe"]["handler"] == "pointer-walk-increment-sink"


def test_window_order_pointer_walk_lever_generates_indexed_variants() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int n;
            int* dst_iter;
            int* tp;
            int dst[4];
            int totals[4];
            dst_iter = dst;
            tp = totals;
            for (n = 0; n < 4; n++, dst_iter++, tp++) {
                *dst_iter = n;
                *tp = seed + n;
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 8},
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    handlers = [
        probe.provenance["local_lifetime_probe"]["handler"]
        for probe in plan.probes
        if probe.provenance["kind"].startswith("window-order-local-pointer-walk")
    ]
    assert "pointer-walk-increment-sink" in handlers
    assert "pointer-walk-indexed-write" in handlers
    assert "pointer-walk-indexed-rebind" in handlers
    indexed_write = next(
        probe for probe in plan.probes
        if probe.provenance["local_lifetime_probe"]["handler"]
        == "pointer-walk-indexed-write"
    )
    assert "dst[n] = n;" in indexed_write.source_text
    indexed_rebind = next(
        probe for probe in plan.probes
        if probe.provenance["local_lifetime_probe"]["handler"]
        == "pointer-walk-indexed-rebind"
    )
    assert "        dst_iter = &dst[n];\n" in indexed_rebind.source_text


def test_window_order_pointer_walk_lever_stays_in_target_function() -> None:
    source = textwrap.dedent("""\
        void other(int seed)
        {
            int i;
            int* dst_iter;
            int dst[4];
            dst_iter = dst;
            for (i = 0; i < 4; i++, dst_iter++) {
                *dst_iter = seed + i;
            }
        }

        void fn(int seed)
        {
            int n;
            int* dst_iter;
            int* tp;
            int dst[4];
            int totals[4];
            dst_iter = dst;
            tp = totals;
            for (n = 0; n < 4; n++, dst_iter++, tp++) {
                *dst_iter = n;
                *tp = seed + n;
            }
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 20},
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    probe = plan.probes[0]
    other_body = probe.source_text[
        probe.source_text.index("void other"):
        probe.source_text.index("void fn")
    ]
    fn_body = probe.source_text[probe.source_text.index("void fn"):]
    assert "for (i = 0; i < 4; i++, dst_iter++) {" in other_body
    assert "for (n = 0; n < 4; n++, tp++) {" in fn_body
    assert "        dst_iter++;\n    }" in fn_body
