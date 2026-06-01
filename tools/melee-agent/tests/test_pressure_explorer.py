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
    compare_pressure_signatures,
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
            f"temp-introduction={candidate}",
            "--pairs",
            "r37/r40",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["function"] == "fn_80000000"
    assert payload["baseline"]["frame_size"] == 56
    variant = payload["variants"][0]
    assert variant["operator"] == "temp-introduction"
    assert variant["delta"]["frame_delta"] == -8
    assert variant["delta"]["spill_removed"] == [37]
    assert variant["delta"]["interference_removed"] == [[37, 40]]


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
    assert variant["status"] == "failed"
    assert "compiled probe pcdump omitted the target function" in variant["error"]
    assert variant["source_retained"] == str(source)


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
    assert variant["final_match_percent"] == 99.94
    assert variant["stack_slot_localizer"] == stack_localizer


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
