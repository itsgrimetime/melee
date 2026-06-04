"""Tests for lifetime/layout pressure-delta attribution."""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.cli import debug as debug_cli
from src.mwcc_debug.pressure_explorer import (
    PressureDelta,
    compare_pressure_signatures,
    generate_frame_directed_probes,
    generate_lifetime_layout_probes,
    pressure_signature_from_pcdump,
)

runner = CliRunner()


BASELINE = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r37,12(r32)
        add r40,r37,r33
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 37 1 1 0x08 SPILLED
        1 40 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 37 r25 1 1 0x00
          interferers: 40=r26
        1 40 r26 1 1 0x00
          interferers: 37=r25
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mflr r0
        stw r0,4(r1)
        stwu r1,-56(r1)
        stfd f31,48(r1)
        stmw r25,24(r1)
        blr
""")


CANDIDATE = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r37,12(r32)
        add r40,r37,r33
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 37 1 1 0x00
        1 40 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 37 r25 0 0 0x00
          interferers:
        1 40 r25 0 0 0x00
          interferers:
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mflr r0
        stw r0,4(r1)
        stwu r1,-48(r1)
        stmw r26,24(r1)
        blr
""")


SOURCE = textwrap.dedent("""\
    void fn_80000000(int flag, int x) {
        int i;
        int temp = x + 1;
        int result;
        int late;
        result = temp;
        sink(temp);
        late = temp + flag;
        sink(late);
        for (i = 0; i < 3; i++) {
            if (flag && result) {
                sink(result + i, x + flag);
            }
        }
    }
""")


def test_pressure_delta_reports_frame_saved_spill_and_interference() -> None:
    baseline = pressure_signature_from_pcdump(
        BASELINE,
        "fn_80000000",
        pairs=[(37, 40)],
    )
    candidate = pressure_signature_from_pcdump(
        CANDIDATE,
        "fn_80000000",
        pairs=[(37, 40)],
    )

    delta = compare_pressure_signatures(baseline, candidate)

    assert baseline.frame_size == 56
    assert candidate.frame_size == 48
    assert delta.frame_delta == -8
    assert delta.saved_removed == ("f31", "r25")
    assert delta.spill_removed == (37,)
    assert delta.interference_removed == ((37, 40),)
    assert delta.target_pairs[0].before.colorgraph_interference is True
    assert delta.target_pairs[0].after.colorgraph_interference is False


def test_pressure_signature_reports_spilled_markers_across_simplify_classes() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000000
        SIMPLIFY GRAPH (class=1, n_colors=29, n_class_regs=45)
          iter ig_idx degree arraySize flags notes
            0 37 1 1 0x08 SPILLED
            1 40 1 1 0x08 SPILLED
        COLORGRAPH DECISIONS (class=0, result=1, n_nodes=0)
          iter ig_idx phys degree nIntfr flags
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            blr
    """)

    signature = pressure_signature_from_pcdump(pcdump, "fn_80000000", class_id=0)

    assert signature.spill_set == (37, 40)


def test_pressure_signature_rejects_missing_function() -> None:
    missing = BASELINE.replace("Starting function fn_80000000", "Starting function other")

    try:
        pressure_signature_from_pcdump(missing, "fn_80000000")
    except ValueError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("missing function should be rejected")


def test_generate_lifetime_layout_probes_includes_core_operator_families() -> None:
    probes = generate_lifetime_layout_probes(SOURCE, "fn_80000000", max_probes=30)
    operators = {probe.operator for probe in probes}

    assert "temp-introduction" in operators
    assert "temp-removal" in operators
    assert "type-width" in operators
    assert "declaration-use-distance" in operators
    assert "early-guard-return" in operators
    assert "block-scope" in operators
    assert "loop-init" in operators
    assert "condition-nesting" in operators
    assert "call-argument-tempization" in operators
    assert all("fn_80000000" in probe.source_text for probe in probes)


def test_generate_frame_directed_probes_materializes_frame_levers() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(HSD_CObj* cobj, int arg1, int arg2)
        {
            f32 far_val;
            f32 bottom;

            far_val = 2.0f;
            bottom = (f32) arg2;
            setup();
            HSD_CObjSetFar(cobj, far_val);
            HSD_CObjSetOrtho(cobj, 0.0f, bottom, 0.0f, (f32) arg1);
        }
    """)

    probes = generate_frame_directed_probes(
        source,
        "fn_80000000",
        current_frame={"frame_size": 152},
        target_frame={"frame_size": 144, "unused_ranges": []},
        max_probes=10,
    )
    by_operator = {probe.operator: probe for probe in probes}

    direct = by_operator["frame-direct-literal-at-final-fp-call"]
    assert "HSD_CObjSetFar(cobj, 2.0f);" in direct.source_text
    assert "far_val = 2.0f;" not in direct.source_text

    split = by_operator["frame-split-fp-const-lifetime"]
    assert "setup();\n    far_val = 2.0f;\n    HSD_CObjSetFar" in split.source_text

    scratch = by_operator["frame-magic-scratch-relocation"]
    assert (
        "HSD_CObjSetFar(cobj, far_val);\n"
        "    bottom = (f32) arg2;\n"
        "    HSD_CObjSetOrtho"
    ) in scratch.source_text


def test_temp_introduction_skips_initialized_decl_before_later_decl() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Fighter* fp, u8 (*arg1)[2])
        {
            if (fp->x594_b4) {
                int idx = (*arg1)[1];
                FigaTree*** trees = fp->ft_data->x2C->x10;
                sink(idx, trees);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)

    assert "temp-introduction" not in {probe.operator for probe in probes}


def test_condition_nesting_skips_if_else_chain() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int kind, int flag)
        {
            bool reload;
            if (kind != 1 && kind != 2) {
                reload = false;
            } else if (!flag) {
                reload = true;
            }
            if (reload) {
                sink();
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)

    assert "condition-nesting" not in {probe.operator for probe in probes}


def test_block_scope_probe_keeps_local_uses_inside_block() -> None:
    source = textwrap.dedent("""\
        void grGreatBay_801F5460(Ground_GObj* gobj)
        {
            HSD_JObj* jobj = gobj->hsd_obj;
            Ground* gp = GET_GROUND(gobj);

            Ground_801C2ED0(jobj, gp->map_id);
            gp->xC_callback = NULL;
        }
    """)

    probes = generate_lifetime_layout_probes(
        source,
        "grGreatBay_801F5460",
        max_probes=20,
    )
    probe = next(probe for probe in probes if probe.operator == "block-scope")
    fn = probe.source_text

    assert "    }\n\n    Ground_801C2ED0" not in fn
    block_start = fn.index("    {\n")
    block_end = fn.rindex("    }\n}")
    assert block_start < fn.index("Ground_801C2ED0") < block_end
    assert block_start < fn.index("gp->xC_callback") < block_end


def test_block_scope_probe_does_not_duplicate_wrapped_lines() -> None:
    probes = generate_lifetime_layout_probes(SOURCE, "fn_80000000", max_probes=20)
    probe = next(probe for probe in probes if probe.operator == "block-scope")

    assert probe.source_text.count("int i;") == 1
    assert probe.source_text.count("int temp = x + 1;") == 1


def test_block_scope_probe_skips_region_that_crosses_shallower_else() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int kind, int flag)
        {
            if (kind == 0) {
                int anim_id = get_anim();
                if (anim_id == 1) {
                    sink(anim_id);
                }
            } else if (flag) {
                int anim_id = get_other_anim();
                sink(anim_id);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)

    assert "block-scope" not in {probe.operator for probe in probes}


def test_declaration_use_distance_probe_moves_plain_decl_to_first_use() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag, int x)
        {
            int late;
            int temp = x + 1;
            sink(temp);
            late = temp + flag;
            sink(late);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)
    probe = next(
        probe for probe in probes if probe.operator == "declaration-use-distance"
    )
    fn = probe.source_text

    assert "    int late;\n    int temp = x + 1;" not in fn
    assert "    {\n        int late;\n        late = temp + flag;" in fn
    assert fn.index("int late;") > fn.index("sink(temp);")


def test_declaration_use_distance_skips_use_that_crosses_shallower_else() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int cond, int b34)
        {
            int teammate_slot;
            if (cond) {
                if (b34 == 1) {
                    teammate_slot = get_slot();
                    sink(teammate_slot);
                } else if (1) {
                    sink(0);
                }
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)

    assert "declaration-use-distance" not in {probe.operator for probe in probes}


def test_declaration_use_distance_keeps_later_uses_inside_moved_block() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag)
        {
            int count;
            sink(flag);
            count = 0;
            if (flag) {
                count++;
            }

            if (count != 0) {
                sink(count);
            }
            done();
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)
    probe = next(
        probe for probe in probes if probe.operator == "declaration-use-distance"
    )
    fn = probe.source_text

    assert "    }\n\n    if (count != 0)" not in fn
    block_start = fn.index("    {\n        int count;")
    block_end = fn.index("    }\n    done();")
    assert block_start < fn.index("if (count != 0)") < block_end
    assert block_start < fn.index("sink(count);") < block_end


def test_early_guard_return_probe_unwraps_top_level_if_body() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag, int index)
        {
            int x;
            if (flag && (index != 1)) {
                sink(index);
                x = index + 1;
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)
    probe = next(probe for probe in probes if probe.operator == "early-guard-return")
    fn = probe.source_text

    assert "if (!(flag && (index != 1))) {" in fn
    assert "        return;\n    }\n    sink(index);" in fn
    assert "    if (flag && (index != 1)) {" not in fn


def test_call_arg_tempization_ignores_pointer_member_access() -> None:
    source = textwrap.dedent("""\
        void grGreatBay_801F5460(Ground_GObj* gobj)
        {
            HSD_JObj* jobj = gobj->hsd_obj;
            Ground* gp = GET_GROUND(gobj);

            Ground_801C2ED0(jobj, gp->map_id);
            gp->xC_callback = NULL;
        }
    """)

    probes = generate_lifetime_layout_probes(
        source,
        "grGreatBay_801F5460",
        max_probes=20,
    )

    assert "call-argument-tempization" not in {probe.operator for probe in probes}


def test_call_arg_tempization_wraps_single_argument_temp_in_block() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int x, int y)
        {
            if (x) {
                sink(x + y, y);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)
    probe = next(
        probe for probe in probes if probe.operator == "call-argument-tempization"
    )

    assert "int ll_probe_arg_0 = x + y;" in probe.source_text
    assert "sink(ll_probe_arg_0, y);" in probe.source_text
    assert "sink(ll_probe_arg_0);" not in probe.source_text
    assert "        {\n            int ll_probe_arg_0" in probe.source_text


def test_call_arg_tempization_preserves_float_argument_type() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(float x)
        {
            f32 y;
            y = 2.0f;
            sinkf(x + y);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(
        probe for probe in probes if probe.operator == "call-argument-tempization"
    )

    assert "f32 ll_probe_arg_0 = x + y;" in probe.source_text
    assert "sinkf(ll_probe_arg_0);" in probe.source_text
    assert "int ll_probe_arg_0 = x + y;" not in probe.source_text
    assert probe.provenance == {
        "kind": "call-argument-tempization",
        "call": "sinkf",
        "argument_index": 0,
        "temp_type": "f32",
    }


def test_call_arg_tempization_ignores_nested_call_in_outer_argument_list() -> None:
    source = textwrap.dedent("""\
        void AXDriver_8038BF6C(HSD_SM* v)
        {
            HSD_SynthSFXSetPitchRatio(v->vID, 0,
                                      powf(2.0F, v->x20 / 1200.0F));
        }
    """)

    probes = generate_lifetime_layout_probes(
        source,
        "AXDriver_8038BF6C",
        max_probes=20,
    )

    assert "call-argument-tempization" not in {probe.operator for probe in probes}


def test_frame_reservation_pad_stack_probe_inserts_requested_pad() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag)
        {
            int count;
            float y;

            sink(flag + count, y);
        }
    """)

    probes = generate_lifetime_layout_probes(
        source,
        "fn_80000000",
        frame_reservation_bytes=64,
        max_probes=30,
    )
    probe = next(
        probe for probe in probes if probe.operator == "frame-reservation-pad-stack"
    )

    assert probe.label == "frame-reservation-pad-stack-64"
    assert "    float y;\n    PAD_STACK(64);\n\n    sink" in probe.source_text
    assert probe.provenance == {
        "kind": "frame-reservation-pad-stack",
        "bytes": 64,
        "action": "insert",
    }


def test_frame_reservation_pad_stack_probe_replaces_existing_pad() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag)
        {
            int count;
            PAD_STACK(8);
            sink(flag + count);
        }
    """)

    probes = generate_lifetime_layout_probes(
        source,
        "fn_80000000",
        frame_reservation_bytes=64,
        max_probes=30,
    )
    probe = next(
        probe for probe in probes if probe.operator == "frame-reservation-pad-stack"
    )

    assert "PAD_STACK(8)" not in probe.source_text
    assert "    PAD_STACK(64);\n    sink" in probe.source_text
    assert probe.provenance == {
        "kind": "frame-reservation-pad-stack",
        "bytes": 64,
        "action": "replace",
        "previous_bytes": 8,
    }


def test_call_return_compare_chain_probes_include_targeted_variants() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(void* entity, float dist, int teammate_slot)
        {
            s32 b34_result = 0;
            int b34;

            b34_result = helper_call(entity);
            b34 = b34_result;
            if (b34 == 1) {
                sink_one();
                if (teammate_slot != 6) {
                    Table* teammate_table = lookup(teammate_slot);
                    if (dist > teammate_table->xD88) {
                        teammate_table->xD88 = dist;
                    }
                }
            } else {
                if (b34 == 0) {
                    sink_zero();
                }
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)
    by_label = {probe.label: probe for probe in probes}

    assert {
        "call-return-compare-switch-0",
        "call-return-compare-inverted-0",
        "call-return-compare-copy-in-else-0",
        "call-return-compare-split-direct-0",
        "call-return-compare-narrow-pointer-0",
    } <= set(by_label)
    provenance = by_label["call-return-compare-switch-0"].to_dict()["provenance"]
    assert provenance == {
        "kind": "call-return-compare-chain",
        "call_symbol": "helper_call",
        "call_expression": "helper_call(entity)",
        "result_var": "b34_result",
        "compare_var": "b34",
        "compare_values": [1, 0],
        "source_line": 6,
        "source_col": 18,
    }
    switch_source = by_label["call-return-compare-switch-0"].source_text
    assert "switch (b34)" in switch_source
    assert "case 1:" in switch_source
    assert "case 0:" in switch_source

    copy_else_source = by_label["call-return-compare-copy-in-else-0"].source_text
    assert "if (b34_result == 1)" in copy_else_source
    assert "    } else {\n        b34 = b34_result;\n        if (b34 == 0)" in copy_else_source

    narrowed_source = by_label["call-return-compare-narrow-pointer-0"].source_text
    assert "            {\n                Table* teammate_table" in narrowed_source
    assert "            }\n        }\n    } else" in narrowed_source


def test_loop_init_probe_uses_c89_compatible_enclosing_block() -> None:
    probes = generate_lifetime_layout_probes(SOURCE, "fn_80000000", max_probes=20)
    probe = next(probe for probe in probes if probe.operator == "loop-init")

    assert "for (int i =" not in probe.source_text
    assert "    {\n        int i;\n        for (i = 0;" in probe.source_text


def test_declaration_order_probes_include_adjacent_swap_and_loop_counter_hoist() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag)
        {
            int count;
            int total;

            if (flag) {
                s32 i;
                for (i = 0; i < count; i++) {
                    total += i;
                }
            }
            sink(total);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    by_label = {probe.label: probe for probe in probes}

    assert "adjacent-decl-swap-0" in by_label
    assert "    int total;\n    int count;" in by_label["adjacent-decl-swap-0"].source_text

    hoist = by_label["loop-counter-hoist-before-0"].source_text
    assert "    int i;\n    int count;" in hoist
    assert "        s32 i;\n" not in hoist
    assert "        for (i = 0; i < count; i++)" in hoist

    hoist_after = by_label["loop-counter-hoist-after-0"].source_text
    assert "    int count;\n    int i;\n    int total;" in hoist_after
    assert "        s32 i;\n" not in hoist_after


def test_loop_counter_hoist_reuses_existing_function_scope_counter() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag, int count)
        {
            int i;
            int total;

            if (flag) {
                s32 i;
                for (i = 0; i < count; i++) {
                    total += i;
                }
            }
            sink(total);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(probe for probe in probes if probe.label == "loop-counter-hoist-before-0")

    assert probe.source_text.count("int i;") == 1
    assert "        s32 i;\n" not in probe.source_text
    assert "        for (i = 0; i < count; i++)" in probe.source_text
    assert probe.to_dict()["provenance"]["placement"] == "reuse:function-scope"


def test_sibling_loop_counter_hoist_reuses_safe_call_loops_and_skips_indexed_loop() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Fighter* fp, FigaTree*** trees, u8* order, int anim_id)
        {
            int total;

            if (anim_id != -1) {
                s32 i;
                for (i = 0; i < fp->dynamics_num; i++) {
                    ftCo_8009CB40(fp, i, 0, 0);
                }
            }
            if (fp->x594_b4) {
                s32 i;
                for (i = 0; i < fp->dynamics_num; i++) {
                    FigaTree* tree = trees[order[i]][0];
                    ftCo_8009CB40(fp, i, 1, tree);
                }
            }
            if (anim_id == -1) {
                s32 i;
                for (i = 0; i < fp->dynamics_num; i++) {
                    ftCo_8009CB40(fp, i, 0, 0);
                }
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=60)
    by_label = {probe.label: probe for probe in probes}

    probe = by_label["sibling-loop-counter-hoist-function-0"]
    assert "    int i;\n    int total;" in probe.source_text
    assert probe.source_text.count("        s32 i;\n") == 1
    assert "if (fp->x594_b4) {\n        s32 i;" in probe.source_text
    assert probe.source_text.count("for (i = 0; i < fp->dynamics_num; i++)") == 3
    assert probe.to_dict()["provenance"] == {
        "kind": "sibling-loop-counter-hoist",
        "counter": "i",
        "call_symbol": "ftCo_8009CB40",
        "loop_count": 2,
        "placement": "function-scope",
        "skipped_indexed_loops": 1,
    }


def test_loop_counter_type_probe_targets_loop_counter_not_first_local() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            int count;
            s32 i;
            for (i = 0; i < count; i++) {
                sink(i);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(probe for probe in probes if probe.label == "loop-counter-type-0")

    assert "    int count;\n    int i;" in probe.source_text
    assert "    s32 i;" not in probe.source_text


def test_indexed_pointer_loop_probes_control_base_index_address_and_bound() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(FigaTree*** base, u8* order, int count)
        {
            FigaTree*** trees = base;
            int i;
            for (i = 0; i < count; i++) {
                FigaTree* tree = trees[order[i]][0];
                apply(i, tree);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=60)
    by_label = {probe.label: probe for probe in probes}

    assert "indexed-pointer-loop-bound-local-0" in by_label
    bound = by_label["indexed-pointer-loop-bound-local-0"]
    assert "    {\n        int ll_probe_loop_bound_0 = count;\n" in bound.source_text
    assert "for (i = 0; i < ll_probe_loop_bound_0; i++)" in bound.source_text

    assert "indexed-pointer-loop-index-temp-0" in by_label
    index = by_label["indexed-pointer-loop-index-temp-0"]
    assert "        int ll_probe_index_0 = order[i];\n" in index.source_text
    assert "trees[ll_probe_index_0][0]" in index.source_text

    assert "indexed-pointer-loop-base-alias-0" in by_label
    base_alias = by_label["indexed-pointer-loop-base-alias-0"]
    assert "        FigaTree*** ll_probe_base_0 = trees;\n" in base_alias.source_text
    assert "ll_probe_base_0[order[i]][0]" in base_alias.source_text

    assert "indexed-pointer-loop-address-temp-0" in by_label
    address = by_label["indexed-pointer-loop-address-temp-0"]
    assert "        FigaTree** ll_probe_addr_0 = trees[order[i]];\n" in address.source_text
    assert "FigaTree* tree = ll_probe_addr_0[0];" in address.source_text

    assert address.provenance == {
        "kind": "indexed-pointer-loop",
        "variant": "address-temp",
        "counter": "i",
        "base": "trees",
        "index_expr": "order[i]",
        "bound": "count",
    }

    struct_source = textwrap.dedent("""\
        void fn_80000001(struct FigaTree*** base, u8* order, int count)
        {
            struct FigaTree*** trees = base;
            int i;
            for (i = 0; i < count; i++) {
                struct FigaTree* tree = trees[order[i]][0];
                apply(i, tree);
            }
        }
    """)

    struct_probes = generate_lifetime_layout_probes(
        struct_source,
        "fn_80000001",
        max_probes=60,
    )
    struct_by_label = {probe.label: probe for probe in struct_probes}
    assert (
        "        struct FigaTree*** ll_probe_base_0 = trees;\n"
        in struct_by_label["indexed-pointer-loop-base-alias-0"].source_text
    )
    assert (
        "        struct FigaTree** ll_probe_addr_0 = trees[order[i]];\n"
        in struct_by_label["indexed-pointer-loop-address-temp-0"].source_text
    )


def test_pointer_walk_loop_probes_control_tree_index_address_and_end() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Fighter* fp, FigaTree** trees)
        {
            FigaTree** tree = trees;
            int i;
            for (i = 0; i < fp->dynamics_num; i++) {
                ftCo_8009CB40(fp, i, true, tree[i]);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=60)
    by_label = {probe.label: probe for probe in probes}

    index = by_label["pointer-walk-loop-index-temp-0"]
    assert "        int ll_probe_index_0 = i;\n" in index.source_text
    assert "tree[ll_probe_index_0]" in index.source_text

    base = by_label["pointer-walk-loop-base-alias-0"]
    assert "        FigaTree** ll_probe_base_0 = tree;\n" in base.source_text
    assert "ll_probe_base_0[i]" in base.source_text

    address = by_label["pointer-walk-loop-address-temp-0"]
    assert "        FigaTree** ll_probe_addr_0 = tree + i;\n" in address.source_text
    assert "ftCo_8009CB40(fp, i, true, *ll_probe_addr_0);" in address.source_text

    value = by_label["pointer-walk-loop-value-temp-0"]
    assert "        FigaTree* ll_probe_value_0 = tree[i];\n" in value.source_text
    assert "ftCo_8009CB40(fp, i, true, ll_probe_value_0);" in value.source_text

    induction = by_label["pointer-walk-loop-induction-0"]
    assert "        FigaTree** ll_probe_iter_0 = tree;\n" in induction.source_text
    assert (
        "for (i = 0; i < fp->dynamics_num; i++, ll_probe_iter_0++)"
        in induction.source_text
    )
    assert "ftCo_8009CB40(fp, i, true, *ll_probe_iter_0);" in induction.source_text

    end_pointer = by_label["pointer-walk-loop-end-pointer-0"]
    assert (
        "        FigaTree** ll_probe_end_0 = tree + fp->dynamics_num;\n"
        in end_pointer.source_text
    )
    assert (
        "for (i = 0; ll_probe_iter_0 < ll_probe_end_0; i++, ll_probe_iter_0++)"
        in end_pointer.source_text
    )

    assert address.provenance == {
        "kind": "pointer-walk-loop",
        "variant": "address-temp",
        "counter": "i",
        "base": "tree",
        "index_expr": "i",
        "bound": "fp->dynamics_num",
    }


def test_lifetime_layout_operator_filter_applies_before_max_limit() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Fighter* fp, FigaTree** trees)
        {
            FigaTree** tree = trees;
            int i;
            for (i = 0; i < fp->dynamics_num; i++) {
                ftCo_8009CB40(fp, i, true, tree[i]);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(
        source,
        "fn_80000000",
        max_probes=2,
        operator_filter={"pointer-walk-loop"},
    )

    assert [probe.operator for probe in probes] == [
        "pointer-walk-loop",
        "pointer-walk-loop",
    ]
    assert [probe.label for probe in probes] == [
        "pointer-walk-loop-index-temp-0",
        "pointer-walk-loop-base-alias-0",
    ]


def test_pointer_base_call_loop_probes_index_direct_tree_argument() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Fighter* fp, FigaTree** tree)
        {
            int i;
            for (i = 0; i < fp->dynamics_num; i++) {
                ftCo_8009CB40(fp, i, true, tree);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=60)
    by_label = {probe.label: probe for probe in probes}

    indexed = by_label["pointer-base-call-indexed-0"]
    assert "ftCo_8009CB40(fp, i, true, tree[i]);" in indexed.source_text

    value = by_label["pointer-base-call-value-temp-0"]
    assert "        FigaTree* ll_probe_value_0 = tree[i];\n" in value.source_text
    assert "ftCo_8009CB40(fp, i, true, ll_probe_value_0);" in value.source_text

    address = by_label["pointer-base-call-address-temp-0"]
    assert "        FigaTree** ll_probe_addr_0 = tree + i;\n" in address.source_text
    assert "ftCo_8009CB40(fp, i, true, *ll_probe_addr_0);" in address.source_text

    induction = by_label["pointer-base-call-induction-0"]
    assert "        FigaTree** ll_probe_iter_0 = tree;\n" in induction.source_text
    assert (
        "for (i = 0; i < fp->dynamics_num; i++, ll_probe_iter_0++)"
        in induction.source_text
    )
    assert "ftCo_8009CB40(fp, i, true, *ll_probe_iter_0);" in induction.source_text

    end_pointer = by_label["pointer-base-call-end-pointer-0"]
    assert "        FigaTree** ll_probe_end_0 = tree + fp->dynamics_num;\n" in (
        end_pointer.source_text
    )
    assert (
        "for (i = 0; ll_probe_iter_0 < ll_probe_end_0; i++, ll_probe_iter_0++)"
        in end_pointer.source_text
    )

    assert address.provenance == {
        "kind": "pointer-base-call-loop",
        "variant": "address-temp",
        "counter": "i",
        "base": "tree",
        "index_expr": "i",
        "bound": "fp->dynamics_num",
    }


def test_expression_shape_probe_removes_assignment_in_expression_temp() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Vec* prevPos, Vec* pos)
        {
            float avg_sum;
            float dist;

            dist = sqrtf(((prevPos->x - (avg_sum = pos->x)) * (prevPos->x - avg_sum)) +
                         ((prevPos->y - pos->y) * (prevPos->y - pos->y)));
            sink(dist);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(
        probe for probe in probes
        if probe.label == "assignment-expression-cse-removal-0"
    )

    assert "(avg_sum = pos->x)" not in probe.source_text
    assert "prevPos->x - pos->x" in probe.source_text
    assert "prevPos->x - avg_sum" not in probe.source_text


def test_expression_shape_probe_introduces_named_distance_component_temps() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Vec* prevPos, Vec* pos)
        {
            float dist;

            dist = sqrtf(((prevPos->x - pos->x) * (prevPos->x - pos->x)) +
                         ((prevPos->y - pos->y) * (prevPos->y - pos->y)));
            sink(dist);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(
        probe for probe in probes
        if probe.label == "distance-component-temps-0"
    )

    assert "float ll_probe_dx_0 = prevPos->x - pos->x;" in probe.source_text
    assert "float ll_probe_dy_0 = prevPos->y - pos->y;" in probe.source_text
    assert "sqrtf((ll_probe_dx_0 * ll_probe_dx_0) +" in probe.source_text
    assert "(ll_probe_dy_0 * ll_probe_dy_0)" in probe.source_text


def test_expression_shape_probe_splits_abs_branch_discriminator() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Vec* prevPos, Vec* pos)
        {
            float y_abs;

            y_abs = pos->y - prevPos->y;
            if (y_abs > 0.0f) {
                if (y_abs < 0.0f) {
                    y_abs = -y_abs;
                } else {
                    y_abs = y_abs;
                }
            }
            sink(y_abs);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(
        probe for probe in probes
        if probe.label == "abs-branch-discriminator-split-0"
    )

    assert "float ll_probe_abs_discriminator_0;" in probe.source_text
    assert "ll_probe_abs_discriminator_0 = pos->y - prevPos->y;" in probe.source_text
    assert "y_abs = ll_probe_abs_discriminator_0;" in probe.source_text
    assert "if (ll_probe_abs_discriminator_0 > 0.0f)" in probe.source_text
    assert "if (y_abs < 0.0f)" in probe.source_text
    assert probe.provenance == {
        "kind": "abs-branch-discriminator-split",
        "value_local": "y_abs",
        "discriminator_local": "ll_probe_abs_discriminator_0",
        "expression": "pos->y - prevPos->y",
    }


def test_guard_shape_probe_rewrites_boolean_call_return_as_case0_default_switch() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Entity* entity)
        {
            if (ftLib_8008732C(entity)) {
                return;
            }
            sink(entity);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(
        probe for probe in probes
        if probe.label == "boolean-guard-switch-0"
    )

    assert "switch (ftLib_8008732C(entity))" in probe.source_text
    assert "case 0:" in probe.source_text
    assert "break;" in probe.source_text
    assert "default:" in probe.source_text
    assert "return;" in probe.source_text
    assert "if (ftLib_8008732C(entity))" not in probe.source_text
    assert probe.provenance == {
        "kind": "boolean-guard-switch",
        "condition": "ftLib_8008732C(entity)",
    }


def test_probe_generation_skips_function_prototype_before_definition() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Entity* entity);

        void unrelated(void)
        {
            int x0;
            int x1;
            sink(x0, x1);
        }

        void fn_80000000(Entity* entity)
        {
            if (ftLib_8008732C(entity)) {
                return;
            }
            sink(entity);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    labels = {probe.label for probe in probes}

    assert "boolean-guard-switch-0" in labels
    assert "adjacent-decl-swap-0" not in labels


def test_lifetime_layout_cli_compares_candidate_pcdump_json(tmp_path: pathlib.Path) -> None:
    baseline = tmp_path / "baseline.txt"
    candidate = tmp_path / "candidate.txt"
    baseline.write_text(BASELINE)
    candidate.write_text(CANDIDATE)

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"unchanged={baseline}",
            "--candidate",
            f"temp-introduction={candidate}",
            "--pairs",
            "r37/r40",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["function"] == "fn_80000000"
    assert payload["ranking"] == (
        "lifetime-layout pressure objective, final match percent tiebreaker"
    )
    assert payload["baseline"]["frame_size"] == 56
    variant = payload["variants"][0]
    assert variant["rank"] == 1
    assert variant["label"] == "temp-introduction"
    assert variant["operator"] == "temp-introduction"
    assert variant["delta"]["frame_delta"] == -8
    assert variant["delta"]["spill_removed"] == [37]
    assert variant["delta"]["interference_removed"] == [[37, 40]]
    assert variant["objective"]["frame_delta"] == -8
    assert variant["objective"]["target_spill_removed"] == [37]
    assert variant["objective"]["actionability"] == "improved"
    assert variant["objective"]["actionability_reasons"] == [
        "frame_reduced",
        "target_spill_removed",
        "interference_removed",
    ]
    assert variant["objective"]["match_percent"] is None
    assert variant["objective"]["opcode_shape_preserved"] is None
    assert payload["variants"][1]["rank"] == 2
    assert payload["variants"][1]["label"] == "unchanged"
    assert payload["variants"][1]["objective"]["actionability"] == "neutral"


def test_lifetime_layout_objective_keeps_untargeted_interference_neutral() -> None:
    delta = PressureDelta(
        frame_before=56,
        frame_after=56,
        frame_delta=0,
        saved_added=(),
        saved_removed=(),
        spill_added=(),
        spill_removed=(),
        interference_added=((10, 11), (12, 13)),
        interference_removed=((20, 21), (22, 23), (24, 25)),
        coalesce_added=(),
        coalesce_removed=(),
        target_pairs=(),
    )

    objective = debug_cli._score_lifetime_layout_objective(
        delta,
        target_pairs=[],
        match_percent=99.37799,
    )

    assert objective["actionability"] == "regressed"
    assert "interference_removed" not in objective["actionability_reasons"]
    assert objective["sort_key"][3] == 0.0


def test_lifetime_layout_cli_source_failure_keeps_source_path(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {}\n")

    def fake_compile(*args, **kwargs) -> str:
        return BASELINE.replace("fn_80000000", "other")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"block-scope={source}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["status"] == "malformed-source"
    assert "compiled probe pcdump omitted the target function" in variant["error"]
    assert variant["source_retained"] == str(source)
    assert "source_hunk" in variant
    assert "fn_80000000" in variant["source_hunk"]


def test_lifetime_layout_cli_rejects_source_missing_target_before_compile(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000001(void) {\n    helper();\n}\n")

    def fail_if_compiled(*args, **kwargs) -> str:
        raise AssertionError("source missing target should be rejected before compile")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fail_if_compiled,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"block-scope={source}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["status"] == "malformed-source"
    assert "target function fn_80000000 not found in candidate source" in variant["error"]
    assert "before compile" in variant["error"]
    assert variant["source_retained"] == str(source)
    assert "fn_80000001" in variant["source_hunk"]


def test_lifetime_layout_cli_marks_dump_missing_target_as_malformed_source(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.mwcc_debug.diff_capture import CompileFailure

    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {\n}\n")

    def fake_compile(diff_input, *, function, melee_root, timeout) -> str:
        raise CompileFailure(
            side=diff_input.label,
            command=["debug", "dump", "local"],
            stdout="",
            stderr=(
                "function 'fn_80000000' not found in pcdump\n"
                "suggestions: fn_80000001"
            ),
            returncode=3,
        )

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"block-scope={source}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["status"] == "malformed-source"
    assert "compiled probe pcdump omitted the target function" in variant["error"]
    assert "fn_80000001" in variant["error"]
    assert variant["source_retained"] == str(source)
    assert "fn_80000000" in variant["source_hunk"]


def test_lifetime_layout_json_reports_candidate_progress_and_timeout_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.mwcc_debug.diff_capture import CompileFailure

    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {}\n")

    def fake_compile(diff_input, *, function, melee_root, timeout) -> str:
        raise CompileFailure(
            side=diff_input.label,
            command=["debug", "dump", "local"],
            stdout="",
            stderr="dump local timed out after 5s",
            returncode=124,
        )

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"manual:block-scope={source}",
            "--timeout",
            "5",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    variant = payload["variants"][0]
    assert variant["status"] == "failed"
    assert variant["label"] == "manual"
    assert variant["source_retained"] == str(source)
    assert "timed out" in variant["error"]
    progress = [
        json.loads(line)
        for line in result.stderr.splitlines()
        if line.startswith("{")
    ]
    assert progress[0] == {
        "event": "lifetime-layout-candidate-start",
        "index": 1,
        "total": 1,
        "label": "manual",
        "operator": "block-scope",
        "path": str(source),
    }
    assert progress[1]["event"] == "lifetime-layout-candidate-failed"
    assert progress[1]["label"] == "manual"
    assert "timed out" in progress[1]["error"]


def test_lifetime_layout_cli_scores_source_with_match_percent_and_stack_slots(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {}\n")

    stack_localizer = {
        "mismatch_count": 1,
        "deltas": [4],
        "mismatches": [
            {
                "opcode": "stfs",
                "expected_offset": 0x34,
                "current_offset": 0x30,
                "delta": 4,
            }
        ],
    }

    def fake_compile(*args, **kwargs) -> str:
        return CANDIDATE

    def fake_real_score(*args, **kwargs):
        return debug_cli._SourceCandidateRealScore(
            match_percent=99.94,
            match_percent_error=None,
            stack_slot_localizer=stack_localizer,
            stack_slot_error=None,
        )

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_score_source_candidate_real_tree",
        fake_real_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"temp-introduction={source}",
            "--pairs",
            "r37/r40",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["rank"] == 1
    assert variant["final_match_percent"] == 99.94
    assert variant["match_percent"] == 99.94
    assert variant["objective"]["match_percent"] == 99.94
    assert variant["source_retained"] == str(source)
    assert variant["stack_slot_localizer"] == stack_localizer
    assert variant["objective"]["stack_slot_mismatch_count"] == 1


def test_score_source_candidate_rejects_new_helper_definition_without_build(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    melee_root = tmp_path / "melee"
    target = melee_root / "src" / "melee" / "pl" / "plbonuslib.c"
    target.parent.mkdir(parents=True)
    original = textwrap.dedent("""\
        static float existing_helper(float value)
        {
            return value;
        }

        void fn_8003F654(void)
        {
            existing_helper(1.0f);
        }
    """)
    target.write_text(original)

    candidate = tmp_path / "candidate.c"
    candidate.write_text(textwrap.dedent("""\
        static float existing_helper(float value)
        {
            return value;
        }

        static inline float f654_slot_helper(float value)
        {
            return value;
        }

        void fn_8003F654(void)
        {
            f654_slot_helper(1.0f);
        }
    """))

    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/pl/plbonuslib",
    )

    def fail_if_builds(*args, **kwargs):
        raise AssertionError("candidate with external helper should be rejected before build")

    monkeypatch.setattr(debug_cli, "_run_ninja_with_no_diag_retry", fail_if_builds)

    score = debug_cli._score_source_candidate_real_tree(
        candidate,
        function="fn_8003F654",
        melee_root=melee_root,
    )

    assert score.match_percent is None
    assert score.match_percent_error is not None
    assert "helper function(s) outside fn_8003F654" in score.match_percent_error
    assert "f654_slot_helper" in score.match_percent_error
    assert "only transfers fn_8003F654" in score.match_percent_error
    assert target.read_text() == original


def test_lifetime_layout_json_compile_probes_emits_live_candidate_paths(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE)
    source.write_text(SOURCE)

    def fake_compile(*args, **kwargs) -> str:
        return CANDIDATE

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--compile-probes",
            "--no-score-match-percent",
            "--max-probes",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    variant = payload["variants"][0]
    assert variant["status"] == "ok"
    assert pathlib.Path(variant["path"]).exists()


def test_lifetime_layout_cli_exposes_frame_reservation_probe(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE)
    source.write_text(SOURCE)

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--frame-reservation-bytes",
            "64",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    probes = json.loads(result.stdout)["probes"]
    probe = next(
        probe for probe in probes
        if probe["operator"] == "frame-reservation-pad-stack"
    )
    assert probe["label"] == "frame-reservation-pad-stack-64"
    assert probe["provenance"] == {
        "kind": "frame-reservation-pad-stack",
        "bytes": 64,
        "action": "insert",
    }


def test_lifetime_layout_cli_focuses_b4_tree_loop_probe_families(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE)
    source.write_text(textwrap.dedent("""\
        void fn_80000000(Fighter* fp, FigaTree** trees)
        {
            FigaTree** tree = trees;
            int i;
            for (i = 0; i < fp->dynamics_num; i++) {
                ftCo_8009CB40(fp, i, true, tree[i]);
            }
        }
    """))

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--focus",
            "b4-tree-loop",
            "--max-probes",
            "3",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["focus"] == "b4-tree-loop"
    assert payload["operator_filter"] == [
        "declaration-order",
        "indexed-pointer-loop",
        "loop-counter-hoist",
        "loop-counter-type",
        "pointer-base-call-loop",
        "pointer-walk-loop",
    ]
    operators = {probe["operator"] for probe in payload["probes"]}
    assert operators == {"pointer-walk-loop"}
    assert len(payload["probes"]) == 3
