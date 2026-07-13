"""Tests for select-order-directed source-shape search ranking."""

from __future__ import annotations

import json
import pathlib
import signal
import subprocess
import tempfile
import time
import textwrap

import pytest
from typer.testing import CliRunner

import src.cli.debug as debug_cli
from src.cli import app
from src.mwcc_debug.cache import cache_path
from src.mwcc_debug.node_set_split import requests_from_node_set_delta
from src.mwcc_debug.pressure_explorer import LifetimeLayoutProbe, PressureDelta
from src.mwcc_debug.select_order_search import (
    rank_select_order_candidates,
    render_select_order_variant,
    score_select_order_candidate,
)
from src.mwcc_debug.virtual_attribution import InstructionSite

runner = CliRunner()


BASELINE = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
        mr r33,r4
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 33 1 1 0x00
        1 32 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 33 r30 1 1 0x00
          interferers: 32=r29
        1 32 r29 1 1 0x00
          interferers: 33=r30
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r29,24(r1)
        blr
""")


TARGET_ORDER = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
        mr r33,r4
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 32 1 1 0x00
        1 33 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 32 r30 1 1 0x00
          interferers: 33=r29
        1 33 r29 1 1 0x00
          interferers: 32=r30
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r29,24(r1)
        blr
""")

TARGET_ORDER_WRONG_PHYS = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
        mr r33,r4
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 32 1 1 0x00
        1 33 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 32 r30 1 1 0x00
          interferers: 33=r29
        1 33 r29 1 1 0x00
          interferers: 32=r30
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r29,24(r1)
        blr
""")

TARGET_ORDER_RIGHT_PHYS = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
        mr r33,r4
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 32 1 1 0x00
        1 33 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 32 r29 1 1 0x00
          interferers: 33=r30
        1 33 r30 1 1 0x00
          interferers: 32=r29
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r29,24(r1)
        blr
""")

TARGET_ORDER_FAR_WRONG_PHYS = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
        mr r33,r4
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 32 1 1 0x00
        1 33 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 32 r3 1 1 0x00
          interferers: 33=r4
        1 33 r4 1 1 0x00
          interferers: 32=r3
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r29,24(r1)
        blr
""")

WRONG_ORDER_NEAR_PHYS = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
        mr r33,r4
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 33 1 1 0x00
        1 32 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 33 r31 1 1 0x00
          interferers: 32=r28
        1 32 r28 1 1 0x00
          interferers: 33=r31
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r29,24(r1)
        blr
""")

ONE_FORCE_PHYS_HIT = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
        mr r33,r4
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 33 1 1 0x00
        1 32 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 33 r30 1 1 0x00
          interferers: 32=r3
        1 32 r3 1 1 0x00
          interferers: 33=r30
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r29,24(r1)
        blr
""")

COMPLEMENT_FORCE_PHYS_HIT = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
        mr r33,r4
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 32 1 1 0x00
        1 33 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 32 r29 1 1 0x00
          interferers: 33=r3
        1 33 r3 1 1 0x00
          interferers: 32=r29
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r29,24(r1)
        blr
""")

FPR_BASELINE = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        fmuls f39,f32,f51
        fmuls f33,f36,f48
    SIMPLIFY GRAPH (class=1, n_colors=18, n_class_regs=32)
      iter ig_idx degree arraySize flags notes
        0 39 1 1 0x00
        1 33 1 1 0x00
    COLORGRAPH DECISIONS (class=1, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 39 f28 1 1 0x00
          interferers: 33=f26
        1 33 f26 1 1 0x00
          interferers: 39=f28
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        blr
""")

TRANSFORM_ASSIGNMENT_SOURCE = textwrap.dedent("""\
    void fn_80000000(void)
    {
        int x;
        x = 1;
        sink(x);
    }
""")


def _assert_comma_transform_probe(probe: dict) -> None:
    assert probe["operator"] == "transform-corpus:comma_operator_noop_expression_shape"
    assert probe["provenance"]["kind"] == "transform-corpus"
    assert probe["family_id"] == "comma_operator_noop_expression_shape"
    assert probe["mutator_key"] == "wrap_comma_noop_assignment_rhs"
    assert probe["probe_id"] == "comma_operator_noop_expression_shape@0"


def _write_stale_auto_cache(tmp_path: pathlib.Path) -> pathlib.Path:
    melee_root = tmp_path / "melee"
    source = melee_root / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    cached = cache_path(melee_root, "melee/mn/sample")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(BASELINE, encoding="utf-8")
    cached.with_suffix(".hash").write_text("0" * 64 + "\n", encoding="ascii")
    return melee_root


MISSING_SECOND = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 32 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)
      iter ig_idx phys degree nIntfr flags
        0 32 r30 1 1 0x00
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r29,24(r1)
        blr
""")


R32_ONE_STEP_CLOSER = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
        mr r33,r4
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 33 1 1 0x00
        1 32 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 33 r30 1 1 0x00
          interferers: 32=r28
        1 32 r28 1 1 0x00
          interferers: 33=r30
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r28,20(r1)
        blr
""")


STICKY_POOL_BASELINE = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
        mr r50,r4
        add r56,r32,r50
        add r36,r56,r32
        add r72,r36,r50
        add r63,r72,r36
        add r71,r63,r56
    AFTER REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r29,r3
        mr r28,r4
        add r30,r29,r28
        add r29,r30,r29
        add r31,r29,r28
        add r27,r31,r29
        add r26,r27,r30
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 56 5 5 0x00
        1 36 6 6 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=6)
      iter ig_idx phys degree nIntfr flags
        0 56 r30 5 5 0x00
          interferers: 32=r29 36=r29 50=r28 63=r27 71=r26
        1 36 r29 6 6 0x00
          interferers: 32=r29 50=r28 56=r30 63=r27 71=r26 72=r31
        2 72 r31 1 1 0x00
          interferers: 36=r29
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r26,24(r1)
        blr
""")


STICKY_POOL_REDUCED_FIRST_DEGREE = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
        mr r50,r4
        add r56,r32,r50
        add r36,r56,r32
        add r72,r36,r50
        add r63,r72,r36
        add r71,r63,r56
    AFTER REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r29,r3
        mr r28,r4
        add r30,r29,r28
        add r29,r30,r29
        add r31,r29,r28
        add r27,r31,r29
        add r26,r27,r30
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 56 5 5 0x00
        1 36 5 5 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=6)
      iter ig_idx phys degree nIntfr flags
        0 56 r30 5 5 0x00
          interferers: 32=r29 36=r29 50=r28 63=r27 71=r26
        1 36 r29 5 5 0x00
          interferers: 32=r29 50=r28 56=r30 63=r27 71=r26
        2 72 r31 0 0 0x00
          interferers:
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r26,24(r1)
        blr
""")


def test_select_order_score_prioritizes_requested_order() -> None:
    wrong = score_select_order_candidate(
        BASELINE,
        BASELINE,
        function="fn_80000000",
        target_orders=[(32, 33)],
        match_percent=99.0,
    )
    right = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER,
        function="fn_80000000",
        target_orders=[(32, 33)],
        match_percent=12.0,
    )

    ranked = rank_select_order_candidates([
        {"label": "high-match-wrong-order", "status": "ok", "objective": wrong.to_dict()},
        {"label": "select-order-flipped", "status": "ok", "objective": right.to_dict()},
    ])

    assert ranked[0]["label"] == "select-order-flipped"
    assert ranked[0]["objective"]["target_order_satisfied"] is True
    assert ranked[0]["objective"]["target_order_improved"] is True
    assert ranked[0]["objective"]["target_orders"][0]["candidate_satisfied"] is True


def test_select_order_score_marks_missing_target_side_actionable() -> None:
    objective = score_select_order_candidate(
        BASELINE,
        MISSING_SECOND,
        function="fn_80000000",
        target_orders=[(32, 33)],
        match_percent=10.0,
    )

    pair = objective.to_dict()["target_orders"][0]
    assert pair["candidate_missing_virtuals"] == [33]
    assert pair["candidate_present_count"] == 1
    assert pair["distance_to_flip"] == 2
    assert pair["actionable_movement"] is True
    assert objective.to_dict()["actionable_movement_count"] == 1


def test_select_order_score_tracks_force_phys_satisfaction() -> None:
    wrong_phys = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER_WRONG_PHYS,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=99.0,
    )
    right_phys = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER_RIGHT_PHYS,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=12.0,
    )

    wrong_payload = wrong_phys.to_dict()
    assert wrong_payload["target_order_satisfied"] is True
    assert wrong_payload["force_phys_satisfied"] is False
    assert wrong_payload["force_phys_satisfied_count"] == 0
    assert wrong_payload["force_phys_mismatches"] == {
        "32": {"expected": 29, "actual": 30},
        "33": {"expected": 30, "actual": 29},
    }

    ranked = rank_select_order_candidates([
        {
            "label": "high-match-order-only",
            "status": "ok",
            "objective": wrong_phys.to_dict(),
        },
        {
            "label": "force-phys-satisfied",
            "status": "ok",
            "objective": right_phys.to_dict(),
        },
    ])

    assert ranked[0]["label"] == "force-phys-satisfied"
    assert ranked[0]["objective"]["force_phys_satisfied"] is True


def test_select_order_force_phys_assignments_are_baseline_relative() -> None:
    objective = score_select_order_candidate(
        BASELINE,
        MISSING_SECOND,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 28, 33: 31},
        match_percent=10.0,
    )

    payload = objective.to_dict()
    assignment = payload["force_phys_assignments"]["33"]

    assert payload["force_phys_progress_kind"] == "target-missing"
    assert assignment["status"] == "missing_or_coalesced"
    assert assignment["baseline_actual"] == 30
    assert assignment["actual"] is None
    assert assignment["changed"] is True


def test_select_order_ranking_demotes_force_phys_win_with_structural_drift() -> None:
    shape_drift_win = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER_RIGHT_PHYS,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=99.0,
    )
    shape_preserving_loss = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER_WRONG_PHYS,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=12.0,
    )

    ranked = rank_select_order_candidates([
        {
            "label": "force-phys-but-shape-drift",
            "status": "ok",
            "objective": shape_drift_win.to_dict(),
            "structural_guard": {
                "accepted": False,
                "shape_preserved": False,
                "rejection_reason": (
                    "checkdiff structural drift: "
                    "inline-boundary-toolchain-artifact"
                ),
            },
        },
        {
            "label": "shape-preserving-register-loss",
            "status": "ok",
            "objective": shape_preserving_loss.to_dict(),
            "structural_guard": {
                "accepted": True,
                "shape_preserved": True,
                "classification_primary": "normalized-structural-match",
            },
        },
    ])

    assert ranked[0]["label"] == "shape-preserving-register-loss"


def test_select_order_guard_repair_summary_groups_rejected_allocator_hits() -> None:
    inline_hit = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER_RIGHT_PHYS,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=91.0,
    )
    stack_hit = score_select_order_candidate(
        BASELINE,
        ONE_FORCE_PHYS_HIT,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=99.0,
    )
    accepted = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER_RIGHT_PHYS,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=100.0,
    )
    ranked = rank_select_order_candidates([
        {
            "label": "accepted-hit",
            "status": "ok",
            "path": "/tmp/accepted.c",
            "source_retained": "/tmp/accepted.c",
            "objective": accepted.to_dict(),
            "structural_guard": {"accepted": True},
        },
        {
            "label": "inline-hit",
            "status": "ok",
            "path": "/tmp/inline.c",
            "source_retained": "/tmp/inline.c",
            "chain": ["inline-shape"],
            "objective": inline_hit.to_dict(),
            "structural_guard": {
                "accepted": False,
                "classification_primary": "inline-boundary-toolchain-artifact",
                "normalized_diff_lines": 7,
                "frame_delta": 0,
                "rejection_reason": (
                    "checkdiff structural drift: inline-boundary-toolchain-artifact"
                ),
            },
        },
        {
            "label": "stack-hit",
            "status": "ok",
            "path": "/tmp/stack.c",
            "source_retained": "/tmp/stack.c",
            "chain": ["stack-shape"],
            "objective": stack_hit.to_dict(),
            "structural_guard": {
                "accepted": False,
                "classification_primary": "operand-register-or-offset",
                "normalized_diff_lines": 2,
                "frame_delta": 16,
                "rejection_reason": "checkdiff structural drift: stack slot layout",
            },
        },
    ])

    summary = debug_cli._select_order_guard_repair_summary(
        ranked,
        force_phys={32: 29, 33: 30},
    )

    assert summary["status"] == "needs-repair"
    assert summary["seed_count"] == 2
    lane_kinds = [lane["kind"] for lane in summary["lanes"]]
    assert lane_kinds == ["inline-boundary-toolchain-artifact", "stack-layout"]

    inline_lane = summary["lanes"][0]
    assert inline_lane["repair_action"]["kind"] == "restore-inline-boundary-shape"
    assert "debug select-order-search --candidate" in (
        inline_lane["repair_action"]["next_command_hint"]
    )
    assert inline_lane["candidates"][0]["label"] == "inline-hit"
    assert inline_lane["candidates"][0]["force_phys_satisfied_count"] == 2
    assert inline_lane["candidates"][0]["achieved_registers"] == {"32": 29, "33": 30}
    assert inline_lane["candidates"][0]["guard"]["accepted"] is False
    assert inline_lane["candidates"][0]["normalized_diff_lines"] == 7
    assert inline_lane["candidates"][0]["frame_delta"] == 0

    stack_lane = summary["lanes"][1]
    assert stack_lane["repair_action"]["kind"] == "repair-stack-layout"
    assert stack_lane["candidates"][0]["label"] == "stack-hit"
    assert stack_lane["candidates"][0]["missing_registers"] == {}
    assert stack_lane["candidates"][0]["mismatched_registers"] == {
        "32": {"expected": 29, "actual": 3}
    }


def test_select_order_guard_repair_summary_localizes_inline_boundary_drift(
    tmp_path: pathlib.Path,
) -> None:
    source = tmp_path / "inline.c"
    source.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    helper();\n"
        "    helper();\n"
        "}\n"
    )
    objective = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER_RIGHT_PHYS,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=93.0,
    )
    ranked = rank_select_order_candidates([{
        "label": "inline-hit",
        "status": "ok",
        "path": str(source),
        "source_retained": str(source),
        "objective": objective.to_dict(),
        "structural_guard": {
            "accepted": False,
            "classification_primary": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 21,
            "opcode_similarity": 0.8355,
            "line_delta": 4,
            "frame_delta": 0,
            "rejection_reason": (
                "checkdiff structural drift: inline-boundary-toolchain-artifact"
            ),
        },
    }])

    summary = debug_cli._select_order_guard_repair_summary(
        ranked,
        force_phys={32: 29, 33: 30},
        function="fn_80000000",
    )

    inline_lane = summary["lanes"][0]
    drift = inline_lane["inline_boundary_drift"]
    assert drift["status"] == "localized"
    assert drift["classification_primary"] == "inline-boundary-toolchain-artifact"
    assert "void fn_80000000" in drift["source_hunk"]
    assert drift["source_call_lines"]
    assert all("helper" in line for line in drift["source_call_lines"])
    assert not any("void fn_80000000" in line for line in drift["source_call_lines"])
    assert drift["opcode_drift"]["normalized_diff_lines"] == 21
    assert drift["repair_routes"][0]["kind"] == "run-inline-boundary-structure-search"
    assert drift["next_probe"]["axis"] == "inline-boundary"
    assert "--axis inline-boundary" in drift["next_probe"]["command"]
    assert str(source) in drift["next_probe"]["command"]


def test_select_order_inline_boundary_drift_uses_executable_source_lines(
    tmp_path: pathlib.Path,
) -> None:
    source = tmp_path / "inline.c"
    source.write_text(
        "/** helper(comment_only) should not become a drift anchor. */\n"
        "void helper(int arg);\n"
        "unsigned int flags; // helper(declaration_comment)\n"
        "u32 counter; /* helper(block_comment) */\n"
        "void fn_80000000(void)\n"
        "{\n"
        "    int value = 1;\n"
        "    helper(value);\n"
        "}\n"
    )
    objective = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER_RIGHT_PHYS,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=93.0,
    )
    ranked = rank_select_order_candidates([{
        "label": "inline-hit",
        "status": "ok",
        "path": str(source),
        "source_retained": str(source),
        "objective": objective.to_dict(),
        "structural_guard": {
            "accepted": False,
            "classification_primary": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 21,
            "opcode_similarity": 0.8355,
            "line_delta": 4,
            "frame_delta": 0,
            "rejection_reason": "inline-boundary-toolchain-artifact",
        },
    }])

    summary = debug_cli._select_order_guard_repair_summary(
        ranked,
        force_phys={32: 29, 33: 30},
        function="fn_80000000",
    )

    drift = summary["lanes"][0]["inline_boundary_drift"]
    assert drift["executable_source_lines"]
    assert any("helper(value)" in line for line in drift["executable_source_lines"])
    assert not any("comment_only" in line for line in drift["executable_source_lines"])
    assert not any(
        "declaration_comment" in line
        for line in drift["executable_source_lines"]
    )
    assert not any("block_comment" in line for line in drift["executable_source_lines"])
    assert not any("void helper" in line for line in drift["executable_source_lines"])
    assert not any("unsigned int flags" in line for line in drift["executable_source_lines"])
    assert not any("u32 counter" in line for line in drift["executable_source_lines"])
    assert drift["source_call_lines"] == [
        line for line in drift["executable_source_lines"] if "helper(value)" in line
    ]


def test_select_order_inline_boundary_drift_reports_unmapped_source_spans(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    source = tmp_path / "inline.c"
    source.write_text(
        "void helper(int arg);\n"
        "void fn_80000000(void)\n"
        "{\n"
        "    unsigned int flags;\n"
        "    unsigned int count;\n"
        "    /* helper(comment_start)\n"
        "       helper(comment_body);\n"
        "    */\n"
        "    helper(3);\n"
        "    if (flags) {\n"
        "        helper(count);\n"
        "    }\n"
        "}\n"
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_variant_source_hunk",
        lambda *_args, **_kwargs: (
            "2: void fn_80000000(void)\n"
            "3: {\n"
            "4:     unsigned int flags;\n"
            "5:     unsigned int count;\n"
        ),
    )

    drift = debug_cli._select_order_inline_boundary_drift_summary(
        {
            "label": "inline-hit",
            "path": str(source),
            "source_retained": str(source),
            "frame_delta": 0,
            "guard": {
                "accepted": False,
                "classification_primary": "inline-boundary-toolchain-artifact",
                "normalized_diff_lines": 21,
                "opcode_similarity": 0.8355,
                "line_delta": 4,
                "rejection_reason": "inline-boundary-toolchain-artifact",
            },
        },
        function="fn_80000000",
    )

    assert drift is not None
    assert drift["status"] == "unmapped"
    assert drift["source_attribution_status"] == "unmapped"
    assert drift["terminal_blocker"] == "source-hunk-no-executable-lines"
    assert drift["executable_source_lines"] == []
    assert drift["source_call_lines"] == []
    assert drift["nearest_executable_source_spans"]
    span_text = "\n".join(
        line["text"]
        for span in drift["nearest_executable_source_spans"]
        for line in span["lines"]
    )
    assert "helper(3)" in span_text
    assert "helper(count)" in span_text
    assert "comment_body" not in span_text
    assert drift["opcode_drift"]["hunk_status"] == "metrics-only"
    assert drift["next_probe"]["kind"] == "score-retained-inline-boundary-source"
    assert "--score" in drift["next_probe"]["command"]


def test_select_order_inline_boundary_drift_includes_checkdiff_opcode_hunk(
    tmp_path: pathlib.Path,
) -> None:
    source = tmp_path / "inline.c"
    source.write_text(
        "void helper(int arg);\n"
        "void fn_80000000(void)\n"
        "{\n"
        "    int value = 1;\n"
        "    helper(value);\n"
        "}\n"
    )
    objective = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER_RIGHT_PHYS,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=93.0,
    )
    ranked = rank_select_order_candidates([{
        "label": "inline-hit",
        "status": "ok",
        "path": str(source),
        "source_retained": str(source),
        "objective": objective.to_dict(),
        "structural_guard": {
            "accepted": False,
            "classification_primary": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 21,
            "opcode_similarity": 0.8355,
            "line_delta": 4,
            "frame_delta": 0,
            "rejection_reason": "inline-boundary-toolchain-artifact",
        },
        "_checkdiff_payload": {
            "classification": {
                "primary": "inline-boundary-toolchain-artifact",
                "inline_boundary_artifact": {
                    "missing_ref_calls": ["<fn_80000000+0x24>"],
                },
            },
            "diff": (
                "@@ -1,4 +1,5 @@\n"
                " bl target_helper\n"
                "+fmr f1, f31\n"
                "-bl old_helper\n"
                "+bl current_helper\n"
            ),
            "target_asm": [
                "+000: 48 00 00 01 \tbl target_helper",
                "+004: EC 21 00 2A \tfadds f1, f1, f0",
                "+008: 48 00 00 02 \tbl expected_tail",
            ],
            "current_asm": [
                "+000: 48 00 00 01 \tbl target_helper",
                "+004: FC 20 F8 90 \tfmr f1, f31",
                "+008: EC 21 00 2A \tfadds f1, f1, f0",
                "+00c: 48 00 00 03 \tbl current_tail",
            ],
        },
    }])

    summary = debug_cli._select_order_guard_repair_summary(
        ranked,
        force_phys={32: 29, 33: 30},
        target_orders=[(32, 33)],
        function="fn_80000000",
    )

    drift = summary["lanes"][0]["inline_boundary_drift"]
    checkdiff_drift = drift["checkdiff_drift"]
    assert checkdiff_drift["inline_boundary_artifact"] == {
        "missing_ref_calls": ["<fn_80000000+0x24>"],
    }
    assert any("current_helper" in line for line in checkdiff_drift["diff_hunk"])
    opcode_hunk = checkdiff_drift["opcode_hunk"]
    assert opcode_hunk["status"] == "localized"
    target_signatures = [row["signature"] for row in opcode_hunk["target"]]
    current_signatures = [row["signature"] for row in opcode_hunk["current"]]
    assert "bl expected_tail" in target_signatures
    assert "bl current_tail" in current_signatures
    route_kinds = [route["kind"] for route in drift["repair_routes"]]
    assert "run-select-order-transform-corpus-repair" in route_kinds
    repair_command = next(
        route["command"]
        for route in drift["repair_routes"]
        if route["kind"] == "run-select-order-transform-corpus-repair"
    )
    assert "--include-transform-corpus" in repair_command
    assert "--transform-force-phys 32:29,33:30" in repair_command
    assert "--target 'r32<r33'" in repair_command


def test_select_order_guard_repair_summary_reports_downhill_complement_ceiling() -> None:
    force_phys = {32: 28, 33: 26, 38: 29, 39: 29, 40: 29, 46: 26}
    seed_objective = {
        "match_percent": 93.49416,
        "force_phys_targets": {str(k): v for k, v in force_phys.items()},
        "force_phys_satisfied": False,
        "force_phys_satisfied_count": 4,
        "force_phys_missing": [],
        "force_phys_mismatches": {
            "38": {"expected": 29, "actual": 28},
            "46": {"expected": 26, "actual": 0},
        },
        "force_phys_distance": 27,
        "frame_delta": 0,
    }
    seed_guard = {
        "accepted": False,
        "shape_preserved": False,
        "classification_primary": "inline-boundary-toolchain-artifact",
        "normalized_diff_lines": 21,
        "frame_delta": 0,
        "rejection_reason": "checkdiff structural drift: inline-boundary-toolchain-artifact",
    }
    losing_objective = {
        "match_percent": 92.0,
        "force_phys_targets": {str(k): v for k, v in force_phys.items()},
        "force_phys_satisfied": False,
        "force_phys_satisfied_count": 0,
        "force_phys_missing": [],
        "force_phys_mismatches": {
            str(k): {"expected": v, "actual": 0}
            for k, v in force_phys.items()
        },
        "force_phys_distance": 121,
        "frame_delta": 0,
    }
    seed = {
        "label": "d2-0010-coloring",
        "status": "ok",
        "path": "seed.c",
        "source_retained": "seed.c",
        "objective": seed_objective,
        "structural_guard": seed_guard,
    }
    preserving_rejected = {
        "label": "gr1-preserves-fprs",
        "status": "ok",
        "path": "preserve.c",
        "source_retained": "preserve.c",
        "repair_seed_label": "d2-0010-coloring",
        "parent_label": "d2-0010-coloring",
        "objective": seed_objective,
        "structural_guard": seed_guard,
    }
    structural_loses_fprs = {
        "label": "gr1-repairs-shape",
        "status": "ok",
        "path": "shape.c",
        "source_retained": "shape.c",
        "repair_seed_label": "d2-0010-coloring",
        "parent_label": "d2-0010-coloring",
        "objective": losing_objective,
        "structural_guard": {
            "accepted": True,
            "shape_preserved": True,
            "classification_primary": "normalized-structural-match",
            "normalized_diff_lines": 0,
            "frame_delta": 0,
        },
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [seed, preserving_rejected, structural_loses_fprs],
        force_phys=force_phys,
        function="fn_80000000",
    )

    complement = summary["downhill_complement"]
    assert complement["status"] == "terminal-complement-ceiling"
    assert complement["reason"] == (
        "guard repair found structural candidates, but none preserved the "
        "protected downhill force-phys hits"
    )
    assert complement["protected_registers"] == {
        "32": 28,
        "33": 26,
        "39": 29,
        "40": 29,
    }
    assert complement["best_preserving_candidate"]["label"] == "gr1-preserves-fprs"
    assert complement["best_preserving_candidate"]["preserved_protected_count"] == 4
    assert complement["best_preserving_candidate"]["guard_accepted"] is False
    assert complement["best_structural_candidate"]["label"] == "gr1-repairs-shape"
    assert complement["best_structural_candidate"]["preserved_protected_count"] == 0
    assert complement["best_structural_candidate"]["guard_accepted"] is True
    assert not complement["repair_preserves_protected_hits"]
    assert complement["repair_trades_off_protected_hits"]


def test_select_order_guard_repair_summary_reports_terminal_ceiling_without_guard_repair() -> None:
    force_phys = {32: 28, 33: 26, 39: 29, 40: 29}
    seed_objective = {
        "match_percent": 93.49416,
        "force_phys_targets": {str(k): v for k, v in force_phys.items()},
        "force_phys_satisfied": True,
        "force_phys_satisfied_count": 4,
        "force_phys_missing": [],
        "force_phys_mismatches": {},
        "force_phys_distance": 0,
        "frame_delta": 0,
    }
    rejected_guard = {
        "accepted": False,
        "shape_preserved": False,
        "classification_primary": "inline-boundary-toolchain-artifact",
        "normalized_diff_lines": 21,
        "frame_delta": 0,
        "rejection_reason": "checkdiff structural drift: inline-boundary-toolchain-artifact",
    }
    seed = {
        "label": "d2-0010-coloring",
        "status": "ok",
        "path": "seed.c",
        "source_retained": "seed.c",
        "objective": seed_objective,
        "structural_guard": rejected_guard,
    }
    preserving_rejected = {
        "label": "gr1-preserves-fprs",
        "status": "ok",
        "path": "preserve.c",
        "source_retained": "preserve.c",
        "repair_seed_label": "d2-0010-coloring",
        "parent_label": "d2-0010-coloring",
        "objective": seed_objective,
        "structural_guard": rejected_guard,
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [seed, preserving_rejected],
        force_phys=force_phys,
        function="fn_80000000",
    )

    complement = summary["downhill_complement"]
    assert complement["status"] == "terminal-complement-ceiling"
    assert complement["reason"] == (
        "guard repair candidates were scored, but none repaired the structural "
        "guard while preserving protected downhill force-phys hits"
    )
    assert complement["protected_registers"] == {
        "32": 28,
        "33": 26,
        "39": 29,
        "40": 29,
    }
    assert complement["best_preserving_candidate"]["label"] == "gr1-preserves-fprs"
    assert complement["best_preserving_candidate"]["preserved_protected_count"] == 4
    assert complement["best_preserving_candidate"]["guard_accepted"] is False
    assert complement["best_structural_candidate"]["label"] == "gr1-preserves-fprs"
    assert complement["best_structural_candidate"]["guard_accepted"] is False
    assert not complement["repair_preserves_protected_hits"]
    assert not complement["repair_trades_off_protected_hits"]


def test_select_order_guard_repair_summary_reports_one_register_protected_complement() -> None:
    force_phys = {34: 27, 44: 25}
    seed = {
        "label": "ig34-near44",
        "status": "ok",
        "path": "seed.c",
        "source_retained": "seed.c",
        "objective": {
            "match_percent": 78.92593,
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_missing": [],
            "force_phys_mismatches": {
                "44": {"expected": 25, "actual": 24},
            },
            "force_phys_distance": 1,
            "frame_delta": 24,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "stack-layout",
            "normalized_diff_lines": 21,
            "frame_delta": 24,
        },
    }
    preserving_still_r24 = {
        "label": "gr1-preserve-ig34",
        "status": "ok",
        "path": "preserve.c",
        "source_retained": "preserve.c",
        "repair_seed_label": "ig34-near44",
        "parent_label": "ig34-near44",
        "probe": {
            "label": "source-hunk-revert-1",
            "operator": "source-hunk-subtractive-repair",
            "provenance": {
                "repair_action": "revert-hunk",
                "candidate_hunk": "dst = sorted_names_probe;\n",
            },
        },
        "objective": {
            "match_percent": 79.0,
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_missing": [],
            "force_phys_mismatches": {
                "44": {"expected": 25, "actual": 24},
            },
            "force_phys_distance": 1,
            "frame_delta": 24,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "stack-layout",
            "normalized_diff_lines": 21,
            "frame_delta": 24,
        },
    }
    hits_ig44_loses_ig34 = {
        "label": "gr1-hit-ig44",
        "status": "ok",
        "path": "hit.c",
        "source_retained": "hit.c",
        "repair_seed_label": "ig34-near44",
        "parent_label": "ig34-near44",
        "objective": {
            "match_percent": 78.0,
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_missing": [],
            "force_phys_mismatches": {
                "34": {"expected": 27, "actual": 26},
            },
            "force_phys_distance": 1,
            "frame_delta": 0,
        },
        "structural_guard": {
            "accepted": True,
            "classification_primary": "normalized-structural-match",
            "normalized_diff_lines": 0,
            "frame_delta": 0,
        },
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [seed, preserving_still_r24, hits_ig44_loses_ig34],
        force_phys=force_phys,
        function="mnDiagram_SortNamesByKOs",
    )

    lane = summary["protected_complement_repair"]
    assert lane["status"] == "terminal-protected-complement-ceiling"
    assert lane["register_class"] == "gpr"
    assert lane["protected_registers"] == {"34": 27}
    assert lane["complement_targets"] == {
        "44": {"expected": 25, "actual": 24, "status": "mismatched"}
    }
    assert lane["best_preserving_candidate"]["label"] == "gr1-preserve-ig34"
    assert lane["best_preserving_candidate"]["preserved_protected_count"] == 1
    assert lane["best_preserving_candidate"]["complement_hit_count"] == 0
    assert lane["best_complement_candidate"]["label"] == "gr1-hit-ig44"
    assert lane["best_complement_candidate"]["lost_protected_registers"] == {
        "34": 27
    }
    assert "complement-target-not-hit-while-protected" in lane[
        "terminal_blockers"
    ]
    assert lane["groups"][0]["candidates"][0]["source_provenance"][
        "repair_action"
    ] == "revert-hunk"


def test_select_order_guard_repair_summary_exposes_one_hit_structural_blockers() -> None:
    force_phys = {34: 27, 44: 25}
    seed_objective = {
        "match_percent": 70.0,
        "force_phys_targets": {"34": 27, "44": 25},
        "force_phys_satisfied": False,
        "force_phys_satisfied_count": 1,
        "force_phys_missing": [],
        "force_phys_mismatches": {
            "44": {"expected": 25, "actual": 24},
        },
        "force_phys_distance": 1,
        "frame_delta": 0,
    }
    rejected_guard = {
        "accepted": False,
        "shape_preserved": False,
        "classification_primary": "inline-boundary-toolchain-artifact",
        "normalized_diff_lines": 21,
        "opcode_similarity": 0.913242,
        "frame_delta": 0,
        "rejection_reason": (
            "checkdiff structural drift: inline-boundary-toolchain-artifact"
        ),
    }
    source_hunk = (
        "302:     u8 sorted_names_probe = sorted_names[j];\n"
        "303:     bool sorted_names_exists_probe = sorted_names_probe != 0;\n"
        "304:     mnDiagram_804A076C.sorted_names[store_idx] = sorted_names_probe;\n"
    )
    seed = {
        "label": "gr1-0031",
        "status": "ok",
        "path": "gr1-0031.c",
        "source_retained": "gr1-0031.c",
        "objective": seed_objective,
        "structural_guard": rejected_guard,
        "delta": {
            "spill_unexpected": [45, 49],
            "saved_added": ["r31"],
            "saved_removed": ["r30"],
        },
    }
    preserves_ig34 = {
        "label": "gr1-0032",
        "status": "ok",
        "path": "gr1-0032.c",
        "source_retained": "gr1-0032.c",
        "repair_seed_label": "gr1-0031",
        "parent_label": "gr1-0031",
        "probe": {
            "label": "sorted-names-store-index",
            "operator": "window-order-source-steering",
            "provenance": {
                "repair_action": "move-store-index-temp",
                "candidate_hunk": source_hunk,
            },
        },
        "source_hunk": source_hunk,
        "objective": seed_objective,
        "structural_guard": rejected_guard,
        "delta": {
            "spill_unexpected": [45, 49],
            "saved_added": ["r31"],
            "saved_removed": ["r30"],
        },
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [seed, preserves_ig34],
        force_phys=force_phys,
        function="mnDiagram_SortNamesByKOs",
    )

    lane = summary["protected_complement_repair"]
    assert lane["status"] == "terminal-protected-complement-ceiling"
    assert lane["terminal_blocker"] == "complement-target-not-hit-while-protected"
    assert lane["best_preserving_candidate"]["label"] == "gr1-0032"
    assert lane["best_preserving_candidate"]["complement_targets"] == {
        "44": {"expected": 25, "actual": 24, "status": "mismatched"}
    }
    assert lane["best_preserving_candidate"]["opcode_similarity"] == pytest.approx(
        0.913242
    )
    assert lane["best_preserving_candidate"]["source_hunk"] == source_hunk
    assert lane["best_preserving_candidate"]["spill_delta"] == {
        "spill_unexpected": [45, 49],
        "spill_missing": [],
        "spill_added": [],
        "spill_removed": [],
    }
    assert lane["best_preserving_candidate"]["saved_register_delta"][
        "saved_added"
    ] == ["r31"]
    assert lane["complement_source_diagnostics"]["44"]["target"] == {
        "expected": 25,
        "actual": 24,
        "status": "mismatched",
    }


def test_select_order_guard_repair_summary_reports_fpr_protected_complement() -> None:
    force_phys = {32: 28, 33: 26, 38: 29, 39: 29, 40: 29, 46: 26}
    seed = {
        "label": "draw-four-fpr-hits",
        "status": "ok",
        "path": "seed.c",
        "source_retained": "seed.c",
        "objective": {
            "match_percent": 93.49416,
            "force_phys_targets": {str(k): v for k, v in force_phys.items()},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 4,
            "force_phys_missing": ["46"],
            "force_phys_mismatches": {
                "38": {"expected": 29, "actual": 28},
            },
            "force_phys_distance": 27,
            "frame_delta": 0,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 21,
            "frame_delta": 0,
        },
        "delta": {
            "saved_added": [],
            "saved_removed": [],
        },
    }
    preserves_four = {
        "label": "gr1-preserve-four",
        "status": "ok",
        "path": "preserve.c",
        "source_retained": "preserve.c",
        "repair_seed_label": "draw-four-fpr-hits",
        "parent_label": "draw-four-fpr-hits",
        "objective": seed["objective"],
        "structural_guard": seed["structural_guard"],
        "delta": {
            "saved_added": ["f31"],
            "saved_removed": ["f29"],
        },
    }
    hits_ig38_loses_ig32 = {
        "label": "gr1-hit-ig38",
        "status": "ok",
        "path": "hit38.c",
        "source_retained": "hit38.c",
        "repair_seed_label": "draw-four-fpr-hits",
        "parent_label": "draw-four-fpr-hits",
        "objective": {
            "match_percent": 93.0,
            "force_phys_targets": {str(k): v for k, v in force_phys.items()},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 4,
            "force_phys_missing": ["46"],
            "force_phys_mismatches": {
                "32": {"expected": 28, "actual": 27},
            },
            "force_phys_distance": 3,
            "frame_delta": 8,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "stack-layout",
            "normalized_diff_lines": 0,
            "frame_delta": 8,
        },
        "delta": {
            "saved_added": ["f30"],
            "saved_removed": [],
        },
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [seed, preserves_four, hits_ig38_loses_ig32],
        force_phys=force_phys,
        function="mnDiagram_DrawCellNumber",
        class_id=1,
    )

    lane = summary["protected_complement_repair"]
    assert lane["status"] == "terminal-protected-complement-ceiling"
    assert lane["register_class"] == "fpr"
    assert lane["protected_registers"] == {
        "32": 28,
        "33": 26,
        "39": 29,
        "40": 29,
    }
    assert lane["complement_targets"] == {
        "38": {"expected": 29, "actual": 28, "status": "mismatched"},
        "46": {"expected": 26, "actual": None, "status": "missing"},
    }
    assert lane["best_preserving_candidate"]["label"] == "gr1-preserve-four"
    assert lane["best_preserving_candidate"]["saved_register_delta"][
        "saved_fpr_removed"
    ] == ["f29"]
    assert lane["best_complement_candidate"]["label"] == "gr1-hit-ig38"
    assert lane["best_complement_candidate"]["frame_delta"] == 8
    assert "protected-hit-lost-by-best-complement" in lane["terminal_blockers"]


def test_select_order_guard_repair_summary_reports_fpr_complement_source_diagnostics() -> None:
    force_phys = {32: 28, 33: 26, 38: 29, 39: 29, 40: 29, 46: 26}
    seed = {
        "label": "draw-four-fpr-hits",
        "status": "ok",
        "path": "seed.c",
        "source_retained": "seed.c",
        "objective": {
            "match_percent": 93.49416,
            "force_phys_targets": {str(k): v for k, v in force_phys.items()},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 4,
            "force_phys_missing": ["46"],
            "force_phys_mismatches": {
                "38": {"expected": 29, "actual": 28},
            },
            "force_phys_distance": 27,
            "frame_delta": 0,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 21,
            "frame_delta": 0,
        },
    }
    preserves_four = {
        "label": "gr1-preserve-four",
        "status": "ok",
        "path": "preserve.c",
        "source_retained": "preserve.c",
        "repair_seed_label": "draw-four-fpr-hits",
        "parent_label": "draw-four-fpr-hits",
        "objective": seed["objective"],
        "structural_guard": seed["structural_guard"],
    }
    fpr_temp_attribution = {
        "kind": "fpr-temp",
        "name": None,
        "source_file": "guard-repair/depth-01/gr1-0017.c",
        "source_line": None,
        "expression": "lfs f38,60(r47)",
        "confidence": "pcode-first-def",
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [seed, preserves_four],
        force_phys=force_phys,
        function="mnDiagram_DrawCellNumber",
        class_id=1,
        window_order_source_attributions={38: fpr_temp_attribution},
        window_order_probe_diagnostics={
            "lead_diagnostics": [{
                "target_ig": 38,
                "status": "blocked",
                "source_attribution": fpr_temp_attribution,
                "terminal_blocker": "unsupported-source-attribution-kind",
            }],
        },
    )

    lane = summary["protected_complement_repair"]
    diagnostics = lane["complement_source_diagnostics"]
    assert diagnostics["38"]["target"] == {
        "expected": 29,
        "actual": 28,
        "status": "mismatched",
    }
    assert diagnostics["38"]["source_attribution"]["kind"] == "fpr-temp"
    assert diagnostics["38"]["source_attribution"]["expression"] == (
        "lfs f38,60(r47)"
    )
    assert diagnostics["38"]["terminal_blocker"] == (
        "unsupported-source-attribution-kind"
    )
    assert diagnostics["38"]["source_actionable"] is False
    assert diagnostics["46"]["target"] == {
        "expected": 26,
        "actual": None,
        "status": "missing",
    }
    assert diagnostics["46"]["terminal_blocker"] == "source-attribution-missing"
    assert diagnostics["46"]["source_actionable"] is False
    assert "unsupported-source-attribution-kind" in lane["terminal_blockers"]
    assert "source-attribution-missing" in lane["terminal_blockers"]


def test_select_order_guard_repair_summary_reports_dual_target_composition_plan() -> None:
    force_phys = {34: 27, 44: 25}
    seed = {
        "label": "ig34-near44",
        "status": "ok",
        "path": "seed.c",
        "source_retained": "seed.c",
        "objective": {
            "match_percent": 78.92593,
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_missing": [],
            "force_phys_mismatches": {
                "44": {"expected": 25, "actual": 24},
            },
            "force_phys_distance": 1,
            "frame_delta": 24,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "stack-layout",
            "normalized_diff_lines": 21,
            "opcode_similarity": 0.941,
            "frame_delta": 24,
        },
    }
    preserves_ig34 = {
        "label": "gr1-preserve-ig34",
        "status": "ok",
        "path": "preserve.c",
        "source_retained": "preserve.c",
        "repair_seed_label": "ig34-near44",
        "parent_label": "ig34-near44",
        "objective": seed["objective"],
        "structural_guard": seed["structural_guard"],
        "probe": {
            "label": "dst-iter-owner",
            "operator": "window-order-source-steering",
            "provenance": {
                "repair_action": "move-dst-iter-source-span",
                "candidate_hunk": "dst_iter = dst;\n",
            },
        },
    }
    hits_ig44_loses_ig34 = {
        "label": "gr1-hit-ig44",
        "status": "ok",
        "path": "hit44.c",
        "source_retained": "hit44.c",
        "repair_seed_label": "ig34-near44",
        "parent_label": "ig34-near44",
        "objective": {
            "match_percent": 78.0,
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_missing": [],
            "force_phys_mismatches": {
                "34": {"expected": 27, "actual": 26},
            },
            "force_phys_distance": 1,
            "frame_delta": 0,
        },
        "structural_guard": {
            "accepted": True,
            "classification_primary": "normalized-structural-match",
            "normalized_diff_lines": 0,
            "opcode_similarity": 0.997,
            "frame_delta": 0,
        },
        "delta": {
            "spill_added": [49],
            "spill_removed": [43],
        },
        "probe": {
            "label": "ig34-ig44-causal-crossover",
            "operator": "source-hunk-crossover",
            "provenance": {
                "kind": "source-hunk-crossover",
                "repair_action": "cross-neighborhood-atomized-crossover",
                "component_depth": 2,
                "source_components": [
                    {
                        "source_label": "ig34-near44",
                        "component_kind": "line",
                        "candidate_hunk": "dst_iter = dst;\n",
                        "expression_provenance": {
                            "name": "dst_iter",
                            "source_line": 302,
                        },
                    },
                    {
                        "source_label": "ig44-complement",
                        "component_kind": "line",
                        "candidate_hunk": "store_idx_next = store_idx + 1;\n",
                        "expression_provenance": {
                            "name": "implicit_add_temp",
                            "source_line": 318,
                        },
                    },
                ],
                "protected_force_phys_hits": {"34": 27, "44": 25},
            },
        },
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [seed, preserves_ig34, hits_ig44_loses_ig34],
        force_phys=force_phys,
        function="mnDiagram_SortNamesByKOs",
    )

    lane = summary["protected_complement_repair"]
    composition = lane["protected_hit_composition"]
    assert composition["status"] == "blocked"
    assert composition["terminal_reason"] == (
        "complement-target-not-hit-while-protected"
    )
    assert composition["composition_coverage"]["scored_candidates"] == 2
    assert composition["composition_coverage"]["coverage_status"] == (
        "summary-candidates-only"
    )
    assert composition["protected_registers"] == {"34": 27}
    assert composition["complement_targets"]["44"]["status"] == "mismatched"
    ranked = composition["ranked_source_hunks"]
    assert ranked[0]["candidate_label"] == "gr1-hit-ig44"
    assert ranked[0]["target_assignments"]["complement"]["44"]["status"] == "hit"
    assert ranked[0]["target_assignments"]["lost_protected"] == {"34": 27}
    assert ranked[0]["normalized_diff_lines"] == 0
    assert ranked[0]["opcode_similarity"] == pytest.approx(0.997)
    assert ranked[0]["frame_delta"] == 0
    assert ranked[0]["spill_delta"]["spill_added"] == [49]
    assert [
        component["expression_provenance"]["name"]
        for component in ranked[0]["source_composition"]["source_components"]
    ] == ["dst_iter", "implicit_add_temp"]


def test_select_order_guard_repair_summary_reports_fpr_causal_composition_lane() -> None:
    force_phys = {33: 26, 38: 29, 39: 29, 40: 29, 46: 26}
    seed = {
        "label": "draw-three-fpr-hits",
        "status": "ok",
        "path": "seed.c",
        "source_retained": "seed.c",
        "objective": {
            "match_percent": 93.49416,
            "force_phys_targets": {str(k): v for k, v in force_phys.items()},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 3,
            "force_phys_missing": ["46"],
            "force_phys_mismatches": {
                "38": {"expected": 29, "actual": 28},
            },
            "force_phys_distance": 27,
            "frame_delta": 0,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 21,
            "opcode_similarity": 0.901,
            "frame_delta": -8,
        },
    }
    preserves_three = {
        "label": "gr1-preserve-three",
        "status": "ok",
        "path": "preserve.c",
        "source_retained": "preserve.c",
        "repair_seed_label": "draw-three-fpr-hits",
        "parent_label": "draw-three-fpr-hits",
        "objective": seed["objective"],
        "structural_guard": seed["structural_guard"],
        "delta": {
            "saved_added": ["f31"],
            "saved_removed": ["f29"],
        },
        "probe": {
            "label": "col-cast-owner-family",
            "operator": "window-order-source-steering",
            "provenance": {
                "repair_action": "compose-fpr-owner-family",
                "candidate_hunk": "row_cast_owner_fpr = (f32) row;\n",
            },
        },
    }
    attrs = {
        38: {
            "kind": "fpr-temp",
            "expression": "lfs f38,60(r47)",
            "confidence": "pcode-first-def",
        },
        46: {
            "kind": "fpr-temp",
            "expression": "fsubs f46,f45,f44",
            "confidence": "pcode-first-def",
        },
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [seed, preserves_three],
        force_phys=force_phys,
        function="mnDiagram_DrawCellNumber",
        class_id=1,
        window_order_source_attributions=attrs,
        window_order_probe_diagnostics={
            "lead_diagnostics": [
                {
                    "target_ig": 38,
                    "status": "materialized",
                    "materialized_probe_labels": ["fpr-load-owner-split-rowf"],
                    "synthetic_source_probe": {
                        "handler": "fpr-load-owner-split",
                    },
                },
                {
                    "target_ig": 46,
                    "status": "materialized",
                    "materialized_probe_labels": ["fpr-arith-owner-split-row"],
                    "synthetic_source_probe": {
                        "handler": "fpr-arith-owner-split",
                    },
                },
            ],
        },
    )

    composition = summary["protected_complement_repair"][
        "protected_hit_composition"
    ]
    assert composition["register_class"] == "fpr"
    assert composition["composition_coverage"]["scored_candidates"] == 1
    assert composition["protected_registers"] == {
        "33": 26,
        "39": 29,
        "40": 29,
    }
    assert composition["causal_targets"]["38"]["causal_source"][
        "pcode_first_def"
    ]["expression"] == "lfs f38,60(r47)"
    assert composition["causal_targets"]["46"]["causal_source"][
        "synthetic_source_probe"
    ]["handler"] == "fpr-arith-owner-split"
    ranked = composition["ranked_source_hunks"]
    assert ranked[0]["saved_register_delta"]["saved_fpr_removed"] == ["f29"]
    assert ranked[0]["source_hunks"][0]["candidate_hunk"] == (
        "row_cast_owner_fpr = (f32) row;\n"
    )


def test_select_order_composition_reports_targeted_interference_source_plan() -> None:
    force_phys = {34: 27, 44: 25}
    seed = {
        "label": "sort-ig34-hit",
        "status": "ok",
        "path": "seed.c",
        "source_retained": "seed.c",
        "objective": {
            "match_percent": 81.0,
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_missing": ["44"],
            "force_phys_mismatches": {},
            "force_phys_distance": 2,
            "frame_delta": 0,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "structural-drift",
            "normalized_diff_lines": 7,
            "opcode_similarity": 0.92,
            "frame_delta": 0,
        },
    }
    hits_ig44_loses_ig34 = {
        "label": "gr1-hit-ig44",
        "status": "ok",
        "path": "ig44.c",
        "source_retained": "ig44.c",
        "repair_seed_label": "sort-ig34-hit",
        "parent_label": "sort-ig34-hit",
        "objective": {
            "match_percent": 87.14815,
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_missing": [],
            "force_phys_mismatches": {
                "34": {"expected": 27, "actual": 23},
            },
            "force_phys_distance": 4,
            "frame_delta": 16,
            "target_orders": [
                {
                    "first_virtual": 34,
                    "second_virtual": 44,
                    "probe_intents": [
                        {
                            "kind": "remove-interference",
                            "virtual": 34,
                            "interferer": 43,
                            "description": "remove IG34/r43 interference",
                        },
                        {
                            "kind": "add-interference",
                            "virtual": 44,
                            "interferer": 63,
                            "description": "add harmless IG44/r63 interference",
                        },
                    ],
                }
            ],
        },
        "structural_guard": {
            "accepted": True,
            "classification_primary": "normalized-structural-match",
            "normalized_diff_lines": 0,
            "opcode_similarity": 0.997,
            "frame_delta": 16,
        },
        "delta": {
            "spill_removed": [43, 45],
            "spill_added": [46, 48],
            "saved_removed": ["r31"],
        },
        "probe": {
            "label": "indexed-byte-address-temp-steering-13",
            "operator": "transform-corpus:indexed_byte_address_temp_steering",
            "provenance": {
                "kind": "transform-corpus",
                "family_id": "indexed_byte_address_temp_steering",
                "candidate_hunk": "store_idx_next = store_idx + 1;\n",
            },
        },
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [seed, hits_ig44_loses_ig34],
        force_phys=force_phys,
        function="mnDiagram_SortNamesByKOs",
    )

    composition = summary["protected_complement_repair"][
        "protected_hit_composition"
    ]
    targeted = composition["targeted_interference_source_transforms"]
    assert targeted["status"] == "planned"
    assert targeted["candidate_label"] == "gr1-hit-ig44"
    assert targeted["target_assignments"]["lost_protected"] == {"34": 27}
    assert targeted["target_assignments"]["complement"]["44"]["status"] == "hit"
    assert targeted["node_set_delta"]["function"] == "mnDiagram_SortNamesByKOs"
    assert targeted["node_set_delta"]["class_id"] == 0
    entries = targeted["node_set_delta"]["missing_virtuals"]
    assert [entry["target_ig"] for entry in entries] == [34, 44]
    assert entries[0]["desired_registers"] == ["r27"]
    assert entries[0]["interference_action"] == "remove-interference"
    assert entries[0]["interferer"] == 43
    assert entries[1]["desired_registers"] == ["r25"]
    assert entries[1]["interference_action"] == "add-interference"
    assert entries[1]["interferer"] == 63
    assert targeted["terminal_blockers"] == [
        "source-attribution-missing-for-r34",
        "source-attribution-missing-for-r44",
    ]
    assert (
        debug_cli._select_order_materializable_targeted_interference_delta(targeted)
        is None
    )


def test_select_order_targeted_interference_uses_window_attrs_for_lost_protected_target() -> None:
    force_phys = {34: 27, 44: 25}
    seed = {
        "label": "sort-ig34-hit",
        "status": "ok",
        "path": "seed.c",
        "source_retained": "seed.c",
        "objective": {
            "match_percent": 81.0,
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_missing": ["44"],
            "force_phys_mismatches": {},
            "force_phys_distance": 2,
            "frame_delta": 0,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "structural-drift",
            "normalized_diff_lines": 7,
            "opcode_similarity": 0.92,
            "frame_delta": 0,
        },
    }
    hits_ig44_loses_ig34 = {
        "label": "gr1-hit-ig44",
        "status": "ok",
        "path": "ig44.c",
        "source_retained": "ig44.c",
        "repair_seed_label": "sort-ig34-hit",
        "parent_label": "sort-ig34-hit",
        "objective": {
            "match_percent": 87.14815,
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_missing": [],
            "force_phys_mismatches": {
                "34": {"expected": 27, "actual": 23},
            },
            "force_phys_distance": 4,
            "frame_delta": 16,
            "target_orders": [
                {
                    "first_virtual": 34,
                    "second_virtual": 44,
                    "probe_intents": [
                        {
                            "kind": "remove-interference",
                            "virtual": 34,
                            "interferer": 43,
                            "description": "remove IG34/r43 interference",
                        },
                        {
                            "kind": "add-interference",
                            "virtual": 44,
                            "interferer": 63,
                            "description": "add harmless IG44/r63 interference",
                        },
                    ],
                }
            ],
        },
        "structural_guard": {
            "accepted": True,
            "classification_primary": "normalized-structural-match",
            "normalized_diff_lines": 0,
            "opcode_similarity": 0.997,
            "frame_delta": 16,
        },
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [seed, hits_ig44_loses_ig34],
        force_phys=force_phys,
        function="mnDiagram_SortNamesByKOs",
        window_order_source_attributions={
            "34": {
                "kind": "local",
                "name": "dst_iter",
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 911,
                "expression": "dst_iter",
            },
            "44": {
                "kind": "implicit-temp",
                "expression": "add r44,r49,r34",
            },
        },
        window_order_probe_diagnostics={
            "lead_diagnostics": [
                {
                    "target_ig": 44,
                    "status": "materialized",
                    "materialized_probe_labels": [
                        "window-order-synthetic-ig44-before-dst_iter-3",
                    ],
                    "synthetic_source_probe": {
                        "handler": "implicit-add-owner-split",
                        "owner_local": "dst_iter",
                        "split_expression": "dst",
                        "rewritten_rhs": "window_order_synthetic_dst_iter",
                        "type": "u8*",
                    },
                },
            ],
        },
    )

    targeted = summary["protected_complement_repair"][
        "protected_hit_composition"
    ]["targeted_interference_source_transforms"]
    delta = targeted["node_set_delta"]
    by_target = {entry["target_ig"]: entry for entry in delta["missing_virtuals"]}
    assert by_target[34]["source"]["name"] == "dst_iter"
    assert by_target[34]["source"]["source_line"] == 911
    assert by_target[44]["source"]["expression"] == "add r44,r49,r34"
    assert "source-attribution-missing-for-r34" not in targeted[
        "terminal_blockers"
    ]
    mixed_plan = targeted["mixed_source_repair_plan"]
    assert mixed_plan["status"] == "ready"
    materialized = targeted["materialized_node_set_delta"]
    reqs = requests_from_node_set_delta(
        materialized,
        include_introducible=True,
        max_requests=0,
    )
    assert [req.target_ig for req in reqs] == [34, 44]
    materialized_by_target = {
        entry["target_ig"]: entry
        for entry in materialized["missing_virtuals"]
    }
    assert materialized_by_target[44]["source"] == {
        "kind": "synthetic-owner-split",
        "expression": "dst",
        "type": "u8*",
        "introduce_binding": True,
    }
    assert materialized_by_target[44]["raw_source"]["expression"] == (
        "add r44,r49,r34"
    )


def test_select_order_protected_complement_reports_secondary_actionable_orientation() -> None:
    force_phys = {10: 1, 20: 2, 30: 3, 40: 4}

    def objective(
        *,
        hit_count: int,
        missing: list[str],
        mismatches: dict[str, dict[str, int]],
        target_orders: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "match_percent": 81.0,
            "force_phys_targets": {str(key): value for key, value in force_phys.items()},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": hit_count,
            "force_phys_missing": missing,
            "force_phys_mismatches": mismatches,
            "force_phys_distance": len(missing) + len(mismatches),
            "frame_delta": 0,
        }
        if target_orders is not None:
            payload["target_orders"] = target_orders
        return payload

    rejected_guard = {
        "accepted": False,
        "classification_primary": "stack-layout",
        "normalized_diff_lines": 12,
        "frame_delta": 0,
    }
    accepted_guard = {
        "accepted": True,
        "classification_primary": "normalized-structural-match",
        "normalized_diff_lines": 0,
        "frame_delta": 0,
    }
    primary_seed = {
        "label": "primary-three-hits",
        "status": "ok",
        "path": "primary.c",
        "source_retained": "primary.c",
        "objective": objective(hit_count=3, missing=["30"], mismatches={}),
        "structural_guard": rejected_guard,
    }
    primary_preserving = {
        "label": "gr1-primary-preserve",
        "status": "ok",
        "path": "primary-preserve.c",
        "source_retained": "primary-preserve.c",
        "repair_seed_label": "primary-three-hits",
        "parent_label": "primary-three-hits",
        "objective": objective(hit_count=3, missing=["30"], mismatches={}),
        "structural_guard": rejected_guard,
    }
    secondary_seed = {
        "label": "secondary-two-hits",
        "status": "ok",
        "path": "secondary.c",
        "source_retained": "secondary.c",
        "objective": objective(
            hit_count=2,
            missing=["40"],
            mismatches={"20": {"expected": 2, "actual": 9}},
        ),
        "structural_guard": rejected_guard,
    }
    secondary_preserving = {
        "label": "gr1-secondary-preserve",
        "status": "ok",
        "path": "secondary-preserve.c",
        "source_retained": "secondary-preserve.c",
        "repair_seed_label": "secondary-two-hits",
        "parent_label": "secondary-two-hits",
        "objective": objective(
            hit_count=2,
            missing=["40"],
            mismatches={"20": {"expected": 2, "actual": 9}},
        ),
        "structural_guard": rejected_guard,
    }
    secondary_hits_complement_loses_protected = {
        "label": "gr1-secondary-hit40",
        "status": "ok",
        "path": "secondary-hit40.c",
        "source_retained": "secondary-hit40.c",
        "repair_seed_label": "secondary-two-hits",
        "parent_label": "secondary-two-hits",
        "objective": objective(
            hit_count=2,
            missing=[],
            mismatches={
                "20": {"expected": 2, "actual": 9},
                "30": {"expected": 3, "actual": 6},
            },
            target_orders=[
                {
                    "probe_intents": [
                        {
                            "kind": "remove-interference",
                            "virtual": 30,
                            "interferer": 41,
                            "description": "preserve secondary protected owner",
                        },
                        {
                            "kind": "add-interference",
                            "virtual": 40,
                            "interferer": 63,
                            "description": "materialize secondary complement owner",
                        },
                    ]
                }
            ],
        ),
        "structural_guard": accepted_guard,
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [
            primary_seed,
            primary_preserving,
            secondary_seed,
            secondary_preserving,
            secondary_hits_complement_loses_protected,
        ],
        force_phys=force_phys,
        function="fn_80000000",
        window_order_source_attributions={
            "30": {
                "kind": "local",
                "name": "secondary_owner",
                "expression": "secondary_owner",
                "type": "u8*",
            },
            "40": {
                "kind": "implicit-temp",
                "expression": "add r40,r41,r30",
                "confidence": "pcode-first-def",
            },
        },
        window_order_probe_diagnostics={
            "lead_diagnostics": [
                {
                    "target_ig": 40,
                    "status": "materialized",
                    "materialized_probe_labels": [
                        "window-order-synthetic-ig40-before-secondary-owner"
                    ],
                    "synthetic_source_probe": {
                        "handler": "implicit-add-owner-split",
                        "owner_local": "secondary_owner",
                        "split_expression": "secondary_owner",
                        "type": "u8*",
                    },
                }
            ],
        },
    )

    lane = summary["protected_complement_repair"]
    assert lane["status"] == "terminal-protected-complement-ceiling"
    assert lane["protected_registers"] == {"10": 1, "20": 2, "40": 4}
    assert lane["protected_count"] == 3
    assert lane["complement_targets"] == {
        "30": {"expected": 3, "actual": None, "status": "missing"}
    }
    assert lane["best_preserving_candidate"]["label"] == "gr1-primary-preserve"
    assert lane["best_complement_candidate"]["label"] == "gr1-primary-preserve"
    assert lane["groups"][1]["seed_label"] == "secondary-two-hits"

    lanes = lane["orientation_reconciliation_lanes"]
    assert [entry["seed_label"] for entry in lanes] == [
        "primary-three-hits",
        "secondary-two-hits",
    ]
    assert lanes[0]["source_actionable"] is False
    assert lanes[0]["protected_registers"] == {"10": 1, "20": 2, "40": 4}

    secondary_lane = lanes[1]
    assert secondary_lane["source_actionable"] is True
    assert secondary_lane["group_index"] == 1
    assert secondary_lane["protected_registers"] == {"10": 1, "30": 3}
    assert secondary_lane["complement_targets"]["40"] == {
        "expected": 4,
        "actual": None,
        "status": "missing",
    }
    assert secondary_lane["causal_lane"]["status"] == "actionable"
    assert secondary_lane["causal_lane"]["actionable_target_ids"] == [40]
    assert secondary_lane["causal_lane"]["materialized_candidate_count"] == 1
    assert secondary_lane["causal_lane"]["materialized_candidate_labels"] == [
        "materialized-causal-composition-ig40"
    ]
    assert secondary_lane["mixed_source_repair"]["status"] == "ready"
    assert secondary_lane["mixed_source_repair"]["node_set_target_ids"] == [30, 40]
    assert secondary_lane["materialized_request_targets"] == [30, 40]
    assert secondary_lane["materialized_delta_paths"] == [
        (
            "/groups/1/protected_hit_composition/"
            "causal_complement_composition_lane/scored_causal_candidates/0/"
            "node_set_delta"
        ),
        (
            "/groups/1/protected_hit_composition/"
            "targeted_interference_source_transforms/mixed_source_repair_plan/"
            "materialized_node_set_delta"
        ),
    ]
    assert lane["source_actionable_orientations"] == [secondary_lane]


def test_select_order_reconciliation_frontier_uses_window_attrs_for_lost_protected_target() -> None:
    variant = {
        "label": "gr1-hit-ig44",
        "status": "ok",
        "path": "ig44.c",
        "source_retained": "ig44.c",
        "repair_seed_label": "sort-ig34-hit",
        "parent_label": "sort-ig34-hit",
        "objective": {
            "match_percent": 87.14815,
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_missing": [],
            "force_phys_mismatches": {
                "34": {"expected": 27, "actual": 23},
            },
            "force_phys_distance": 4,
            "frame_delta": 16,
            "target_orders": [
                {
                    "first_virtual": 34,
                    "second_virtual": 44,
                    "probe_intents": [
                        {
                            "kind": "remove-interference",
                            "virtual": 34,
                            "interferer": 43,
                            "description": "remove IG34/r43 interference",
                        },
                        {
                            "kind": "add-interference",
                            "virtual": 44,
                            "interferer": 63,
                            "description": "add harmless IG44/r63 interference",
                        },
                    ],
                }
            ],
        },
        "structural_guard": {
            "accepted": True,
            "classification_primary": "normalized-structural-match",
            "normalized_diff_lines": 0,
            "opcode_similarity": 0.997,
            "frame_delta": 16,
        },
    }

    recovery = debug_cli._select_order_guard_repair_reconciliation_frontier_entry(
        variant,
        function="mnDiagram_SortNamesByKOs",
        class_id=0,
        candidate_source="void f(void) {}\n",
        force_phys={34: 27, 44: 25},
        protected_hits={"34": 27},
        complement_targets={
            "44": {"expected": 25, "actual": None, "status": "unhit"},
        },
        repair_seed_label="sort-ig34-hit",
        depth=1,
        window_order_source_attributions={
            "34": {
                "kind": "local",
                "name": "dst_iter",
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 911,
                "expression": "dst_iter",
            },
            "44": {
                "kind": "implicit-temp",
                "expression": "add r44,r49,r34",
            },
        },
        window_order_probe_diagnostics={},
    )

    assert recovery is not None
    targeted = recovery["ledger"]["targeted_interference_source_transforms"]
    by_target = {
        entry["target_ig"]: entry
        for entry in targeted["node_set_delta"]["missing_virtuals"]
    }
    assert by_target[34]["source"]["name"] == "dst_iter"
    assert by_target[44]["source"]["expression"] == "add r44,r49,r34"
    assert "source-attribution-missing-for-r34" not in targeted[
        "terminal_blockers"
    ]


def test_select_order_targeted_interference_plan_keeps_source_bindings() -> None:
    plan = debug_cli._select_order_targeted_interference_transform_plan(
        function="mnDiagram_SortNamesByKOs",
        class_id=0,
        candidate={
            "label": "gr1-hit-ig44",
            "source_retained": "ig44.c",
            "achieved_registers": {"34": 23, "44": 25},
            "lost_protected_registers": {"34": 27},
            "objective": {
                "target_orders": [
                    {
                        "probe_intents": [
                            {
                                "kind": "remove-interference",
                                "virtual": 34,
                                "interferer": 43,
                                "description": "split dst_iter",
                            },
                            {
                                "kind": "add-interference",
                                "virtual": 44,
                                "interferer": 63,
                                "description": "split store_idx_next",
                            },
                        ]
                    }
                ]
            },
            "source_provenance": {
                "source_components": [
                    {
                        "expression_provenance": {
                            "target_ig": 34,
                            "name": "dst_iter",
                            "expression": "dst_iter",
                            "source_line": 302,
                        },
                    },
                    {
                        "expression_provenance": {
                            "target_ig": 44,
                            "name": "store_idx_next",
                            "expression": "store_idx_next",
                            "source_line": 318,
                        },
                    },
                ],
            },
        },
        protected_registers={"34": 27},
        complement_targets={"44": {"expected": 25, "actual": 25, "status": "hit"}},
        complement_source_diagnostics={},
    )

    assert plan is not None
    assert plan["terminal_blockers"] == []
    delta = debug_cli._select_order_materializable_targeted_interference_delta(plan)
    assert delta is not None
    assert [entry["source"]["name"] for entry in delta["missing_virtuals"]] == [
        "dst_iter",
        "store_idx_next",
    ]


def test_select_order_mixed_source_plan_materializes_owner_split_delta() -> None:
    targeted = {
        "status": "planned",
        "candidate_label": "gr1-hit-ig44",
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": "mnDiagram_SortNamesByKOs",
            "class_id": 0,
            "register_prefix": "r",
            "missing_virtuals": [
                {
                    "target_ig": 34,
                    "current_register": "r23",
                    "desired_registers": ["r27"],
                    "source": {
                        "kind": "local",
                        "name": "dst_iter",
                        "expression": "dst_iter",
                        "type": "u8*",
                    },
                },
                {
                    "target_ig": 44,
                    "current_register": "r24",
                    "desired_registers": ["r25"],
                    "source": {
                        "kind": "implicit-temp",
                        "expression": "add r44,r49,r34",
                        "confidence": "pcode-first-def",
                    },
                },
            ],
        },
    }
    causal_targets = {
        "44": {
            "target_ig": 44,
            "source_actionable": True,
            "materialized_probe_labels": [
                "window-order-synthetic-ig44-before-dst-0",
            ],
            "synthetic_source_probe": {
                "handler": "implicit-add-owner-split",
                "expression": "add r44,r49,r34",
                "owner_local": "dst",
                "split_expression": "dst",
                "type": "u8*",
            },
        }
    }

    mixed = debug_cli._select_order_mixed_source_repair_plan(
        targeted,
        causal_targets=causal_targets,
    )

    assert mixed["status"] == "ready"
    delta = mixed["materialized_node_set_delta"]
    assert delta["function"] == "mnDiagram_SortNamesByKOs"
    by_target = {
        entry["target_ig"]: entry for entry in delta["missing_virtuals"]
    }
    assert by_target[44]["source"] == {
        "kind": "synthetic-owner-split",
        "expression": "dst",
        "type": "u8*",
        "introduce_binding": True,
    }
    assert by_target[44]["raw_source"]["expression"] == "add r44,r49,r34"
    assert "add r44,r49,r34" not in json.dumps(by_target[44]["source"])
    plan_entries = {
        entry["target_ig"]: entry for entry in mixed["entries"]
    }
    assert plan_entries[44]["safe_source_expression"] == "dst"
    assert plan_entries[44]["provenance"]["raw_source"]["expression"] == (
        "add r44,r49,r34"
    )

    reqs = requests_from_node_set_delta(
        delta,
        include_introducible=True,
        max_requests=0,
    )

    assert [req.target_ig for req in reqs] == [34, 44]
    assert reqs[0].var_name == "dst_iter"
    assert reqs[1].var_name is None
    assert reqs[1].source_expression == "dst"


def test_select_order_mixed_source_plan_blocks_raw_implicit_temp() -> None:
    targeted = {
        "status": "planned",
        "candidate_label": "gr1-hit-ig44",
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": "mnDiagram_SortNamesByKOs",
            "class_id": 0,
            "register_prefix": "r",
            "missing_virtuals": [
                {
                    "target_ig": 44,
                    "current_register": "r24",
                    "desired_registers": ["r25"],
                    "source": {
                        "kind": "implicit-temp",
                        "expression": "add r44,r49,r34",
                        "confidence": "pcode-first-def",
                    },
                },
            ],
        },
    }

    mixed = debug_cli._select_order_mixed_source_repair_plan(
        targeted,
        causal_targets={},
    )

    assert mixed["status"] == "blocked"
    assert mixed["blocked_reasons"] == ["implicit-temp-not-materializable"]
    assert mixed["entries"][0]["status"] == "blocked"
    assert mixed["entries"][0]["blocker"] == "implicit-temp-not-materializable"
    assert mixed["entries"][0]["provenance"]["raw_source"]["expression"] == (
        "add r44,r49,r34"
    )
    assert "materialized_node_set_delta" not in mixed


def test_select_order_targeted_interference_plan_uses_probe_source_attribution() -> None:
    plan = debug_cli._select_order_targeted_interference_transform_plan(
        function="mnDiagram_SortNamesByKOs",
        class_id=0,
        candidate={
            "label": "window-order-ig34",
            "achieved_registers": {"34": 23},
            "lost_protected_registers": {"34": 27},
            "objective": {
                "target_orders": [
                    {
                        "probe_intents": [
                            {
                                "kind": "remove-interference",
                                "virtual": 34,
                                "interferer": 43,
                                "description": "split dst_iter",
                            }
                        ]
                    }
                ]
            },
            "source_provenance": {
                "kind": "window-order-source-steering",
                "source_attribution": {
                    "target_ig": 34,
                    "name": "dst_iter",
                    "expression": "dst_iter",
                    "source_line": 302,
                },
            },
        },
        protected_registers={"34": 27},
        complement_targets={},
        complement_source_diagnostics={},
    )

    assert plan is not None
    delta = debug_cli._select_order_materializable_targeted_interference_delta(plan)
    assert delta is not None
    assert delta["missing_virtuals"][0]["source"]["name"] == "dst_iter"


def test_select_order_pcode_first_def_payload_structures_instruction_site() -> None:
    site = InstructionSite(
        pass_name="BEFORE REGISTER COLORING",
        block_idx=3,
        instr_idx=12,
        opcode="fsubs",
        operands="f46,f45,f44",
    )

    payload = debug_cli._select_order_pcode_first_def_payload(
        target_ig=46,
        source={
            "first_def": site,
            "expression": "fsubs f46,f45,f44",
            "confidence": "pcode-first-def",
        },
        probe_diag=None,
    )

    assert payload == {
        "target_ig": 46,
        "pass_name": "BEFORE REGISTER COLORING",
        "block_idx": 3,
        "instr_idx": 12,
        "opcode": "fsubs",
        "operands": "f46,f45,f44",
        "expression": "fsubs f46,f45,f44",
        "confidence": "pcode-first-def",
    }


def test_select_order_timeout_ledger_serializes_instruction_sites(
    tmp_path: pathlib.Path,
) -> None:
    site = InstructionSite(
        pass_name="BEFORE REGISTER COLORING",
        block_idx=3,
        instr_idx=12,
        opcode="fsubs",
        operands="f46,f45,f44",
    )
    ledger_path = tmp_path / "ledger.json"

    debug_cli._write_select_order_timeout_ledger(
        ledger_path,
        {
            "function": "fn_80000000",
            "window_order_probe_diagnostics": {
                "lead_diagnostics": [
                    {
                        "target_ig": 46,
                        "source": {"first_def": site},
                    }
                ],
            },
        },
        timed_out=False,
        timeout_error=None,
    )

    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    first_def = payload["window_order_probe_diagnostics"]["lead_diagnostics"][0][
        "source"
    ]["first_def"]
    assert first_def == {
        "pass_name": "BEFORE REGISTER COLORING",
        "block_idx": 3,
        "instr_idx": 12,
        "opcode": "fsubs",
        "operands": "f46,f45,f44",
    }


def test_select_order_composition_coverage_reports_bounded_exhaustion() -> None:
    composition = debug_cli._select_order_protected_hit_composition_summary(
        lane_status="repair-missing",
        register_class="gpr",
        protected_registers={"34": 27},
        complement_targets={"44": {"expected": 25, "actual": 24, "status": "mismatched"}},
        candidates=[],
        best_preserving={},
        best_complement={},
        complement_source_diagnostics={},
        terminal_blockers=[],
        guard_repair_ledger={
            "entries": [{"label": "gr1-probe"}],
            "deduped": [],
            "stop_condition": "depth-exhausted",
            "effective_depth": 1,
            "width": 1,
            "max_probes": 1,
        },
    )

    coverage = composition["composition_coverage"]
    assert coverage["coverage_status"] == "bounded-depth-exhausted"
    assert coverage["truncated_by_max_probes"] is True
    assert coverage["bounded_by"] == {
        "effective_depth": 1,
        "width": 1,
        "max_probes": 1,
    }
    assert composition["status"] == "blocked"
    assert composition["terminal_reason"] == "bounded-depth-exhausted"


def test_select_order_composition_coverage_separates_depth_from_probe_cap() -> None:
    composition = debug_cli._select_order_protected_hit_composition_summary(
        lane_status="repair-missing",
        register_class="gpr",
        protected_registers={"34": 27},
        complement_targets={"44": {"expected": 25, "actual": 24, "status": "mismatched"}},
        candidates=[],
        best_preserving={},
        best_complement={},
        complement_source_diagnostics={},
        terminal_blockers=[],
        guard_repair_ledger={
            "entries": [{"label": f"gr1-probe-{index}"} for index in range(17)],
            "deduped": [],
            "stop_condition": "depth-exhausted",
            "effective_depth": 1,
            "width": 1,
            "max_probes": 64,
        },
    )

    coverage = composition["composition_coverage"]
    assert coverage["coverage_status"] == "bounded-depth-exhausted"
    assert coverage["generated_candidates"] == 17
    assert coverage["truncated_by_max_probes"] is False


def test_select_order_complement_source_diagnostics_prefers_actionable_lead() -> None:
    diagnostics = debug_cli._select_order_complement_source_diagnostics(
        complement_targets={
            "38": {"expected": 29, "actual": 28, "status": "mismatched"}
        },
        window_order_source_attributions={
            38: {
                "kind": "local",
                "name": "row_offset",
                "source_file": "sample.c",
                "source_line": 4,
            },
        },
        window_order_probe_diagnostics={
            "lead_diagnostics": [
                {
                    "target_ig": 38,
                    "status": "blocked",
                    "terminal_blocker": "no-movable-local-write",
                },
                {
                    "target_ig": 38,
                    "status": "materialized",
                    "materialized_probe_labels": ["window-order-ig38-before-row"],
                },
            ],
        },
    )

    entry = diagnostics["38"]
    assert entry["source_actionable"] is True
    assert entry["materialized_probe_labels"] == ["window-order-ig38-before-row"]
    assert "terminal_blocker" not in entry
    assert entry["blocked_lead_terminal_blockers"] == ["no-movable-local-write"]
    assert entry["source_probe_diagnostic"]["status"] == "materialized"


def test_select_order_guard_repair_summary_omits_source_blocker_for_hit_complement() -> None:
    force_phys = {32: 29, 33: 30}
    seed = {
        "label": "ig33-near32",
        "status": "ok",
        "path": "seed.c",
        "source_retained": "seed.c",
        "objective": {
            "match_percent": 90.0,
            "force_phys_targets": {"32": 29, "33": 30},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_missing": [],
            "force_phys_mismatches": {
                "32": {"expected": 29, "actual": 3},
            },
            "force_phys_distance": 26,
            "frame_delta": 0,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 12,
            "frame_delta": 0,
        },
    }
    preserving_hits_complement = {
        "label": "gr1-preserve-and-hit32",
        "status": "ok",
        "path": "hit32.c",
        "source_retained": "hit32.c",
        "repair_seed_label": "ig33-near32",
        "parent_label": "ig33-near32",
        "objective": {
            "match_percent": 94.0,
            "force_phys_targets": {"32": 29, "33": 30},
            "force_phys_satisfied": True,
            "force_phys_satisfied_count": 2,
            "force_phys_missing": [],
            "force_phys_mismatches": {},
            "force_phys_distance": 0,
            "frame_delta": 0,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 8,
            "frame_delta": 0,
        },
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [seed, preserving_hits_complement],
        force_phys=force_phys,
        window_order_source_attributions={
            32: {"kind": "fpr-temp", "expression": "lfs f32,60(r47)"}
        },
        window_order_probe_diagnostics={
            "lead_diagnostics": [{
                "target_ig": 32,
                "status": "blocked",
                "terminal_blocker": "unsupported-source-attribution-kind",
            }],
        },
    )

    lane = summary["protected_complement_repair"]
    hit_diagnostic = lane["complement_source_diagnostics"]["32"]
    assert hit_diagnostic["target"]["status"] == "hit"
    assert "terminal_blocker" not in hit_diagnostic
    assert "structural-guard-not-accepted" in lane["terminal_blockers"]
    assert "unsupported-source-attribution-kind" not in lane["terminal_blockers"]


def test_select_order_guard_repair_summary_reports_fpr_partial_hit_composition_without_seed_pair() -> None:
    force_phys = {32: 28, 33: 26, 38: 29, 39: 29, 40: 29, 46: 26}
    direct_partial_hit = {
        "label": "draw-three-fpr-direct",
        "status": "ok",
        "path": "draw-direct.c",
        "source_retained": "draw-direct.c",
        "objective": {
            "match_percent": 93.49416,
            "force_phys_targets": {str(k): v for k, v in force_phys.items()},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 3,
            "force_phys_missing": [],
            "force_phys_mismatches": {
                "32": {"expected": 28, "actual": 27},
                "38": {"expected": 29, "actual": 28},
                "46": {"expected": 26, "actual": 25},
            },
            "force_phys_distance": 4,
            "frame_delta": -8,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 21,
            "opcode_similarity": 0.901,
            "frame_delta": -8,
        },
        "delta": {
            "spill_unexpected": [47],
            "spill_added": [51],
            "saved_added": ["f31"],
            "saved_removed": ["f29"],
        },
    }
    unmatched_repair_candidate = {
        **direct_partial_hit,
        "label": "gr1-draw-three-fpr-direct",
        "repair_seed_label": "missing-seed",
        "parent_label": "missing-seed",
        "path": "draw-repair.c",
        "source_retained": "draw-repair.c",
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [direct_partial_hit, unmatched_repair_candidate],
        force_phys=force_phys,
        function="mnDiagram_DrawCellNumber",
        class_id=1,
        guard_repair_ledger={
            "entries": [{"label": "gr1-draw-three-fpr-direct"}],
            "deduped": [],
            "stop_condition": "frontier-empty",
            "effective_depth": 1,
            "width": 1,
            "max_probes": 1,
        },
    )

    lane = summary["protected_complement_repair"]
    assert lane["status"] != "repair-found"
    assert lane["register_class"] == "fpr"
    composition = lane["protected_hit_composition"]
    assert composition["status"] == "blocked"
    assert composition["terminal_reason"] == (
        "partial-protected-complement-no-seed-pair"
    )
    assert "partial-protected-complement-no-seed-pair" in composition[
        "terminal_blockers"
    ]
    assert composition["protected_registers"] == {
        "33": 26,
        "39": 29,
        "40": 29,
    }
    assert composition["complement_targets"] == {
        "32": {"expected": 28, "actual": 27, "status": "mismatched"},
        "38": {"expected": 29, "actual": 28, "status": "mismatched"},
        "46": {"expected": 26, "actual": 25, "status": "mismatched"},
    }
    ranked = composition["ranked_source_hunks"]
    assert ranked[0]["candidate_label"] == "draw-three-fpr-direct"
    assert ranked[0]["frame_delta"] == -8
    assert ranked[0]["spill_delta"]["spill_added"] == [51]
    assert ranked[0]["saved_register_delta"]["saved_fpr_added"] == ["f31"]
    assert ranked[0]["saved_register_delta"]["saved_fpr_removed"] == ["f29"]


def test_select_order_partial_summary_reports_causal_complement_lane() -> None:
    force_phys = {32: 28, 33: 26, 38: 29, 39: 29, 40: 29, 46: 26}
    direct_partial_hit = {
        "label": "draw-three-fpr-direct",
        "status": "ok",
        "path": "draw-direct.c",
        "source_retained": "draw-direct.c",
        "objective": {
            "match_percent": 93.49416,
            "force_phys_targets": {str(k): v for k, v in force_phys.items()},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 3,
            "force_phys_missing": [],
            "force_phys_mismatches": {
                "32": {"expected": 28, "actual": 27},
                "38": {"expected": 29, "actual": 28},
                "46": {"expected": 26, "actual": 25},
            },
            "force_phys_distance": 4,
            "frame_delta": -8,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 21,
            "opcode_similarity": 0.901,
            "frame_delta": -8,
        },
    }
    causal_repair_candidate = {
        **direct_partial_hit,
        "label": "gr1-draw-causal",
        "repair_seed_label": "missing-seed",
        "parent_label": "missing-seed",
        "path": "draw-causal.c",
        "source_retained": "draw-causal.c",
        "chain": ["window-order-synthetic-ig38-before-row-0"],
        "objective": {
            **direct_partial_hit["objective"],
            "match_percent": 94.0,
            "force_phys_distance": 3,
        },
        "probe": {
            "label": "draw-causal-owner-composition",
            "operator": "source-hunk-crossover",
            "provenance": {
                "kind": "source-hunk-crossover",
                "repair_action": "compose-fpr-owner-family",
                "component_labels": [
                    "window-order-synthetic-ig38-before-row-0",
                    "window-order-synthetic-ig46-before-row-0",
                ],
                "source_components": [
                    {
                        "source_label": "window-order-synthetic-ig46-before-row-0",
                        "component_kind": "line",
                        "candidate_hunk": "row_owner = (f32) row;\n",
                    },
                ],
            },
        },
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [direct_partial_hit, causal_repair_candidate],
        force_phys=force_phys,
        function="mnDiagram_DrawCellNumber",
        class_id=1,
        window_order_source_attributions={
            32: {
                "kind": "fpr-temp",
                "expression": "fsubs f32,f31,f30",
                "confidence": "pcode-first-def",
            },
            38: {
                "kind": "fpr-temp",
                "expression": "lfs f38,60(r47)",
                "confidence": "pcode-first-def",
            },
            46: {
                "kind": "fpr-temp",
                "expression": "fsubs f46,f45,f44",
                "confidence": "pcode-first-def",
            },
        },
        window_order_probe_diagnostics={
            "lead_diagnostics": [
                {
                    "target_ig": 32,
                    "status": "blocked",
                    "terminal_blocker": "no-movable-local-write",
                },
                {
                    "target_ig": 38,
                    "status": "materialized",
                    "materialized_probe_labels": [
                        "window-order-synthetic-ig38-before-row-0",
                        "window-order-synthetic-ig38-before-row-1",
                    ],
                    "synthetic_source_probe": {
                        "handler": "fpr-load-owner-split",
                        "owner_local": "row",
                        "split_expression": "(f32) row",
                        "type": "f32",
                    },
                },
                {
                    "target_ig": 46,
                    "status": "materialized",
                    "materialized_probe_labels": [
                        "window-order-synthetic-ig46-before-row-0",
                    ],
                    "synthetic_source_probe": {
                        "handler": "fpr-arith-owner-split",
                        "owner_local": "row_offset_adj",
                        "split_expression": "row_offset - 0.4f",
                        "type": "f32",
                    },
                },
            ],
        },
        guard_repair_ledger={
            "entries": [{"label": "gr1-draw-causal"}],
            "deduped": [],
            "stop_condition": "timeout",
            "timed_out": True,
            "effective_depth": 1,
            "width": 1,
            "max_probes": 1,
        },
    )

    composition = summary["protected_complement_repair"][
        "protected_hit_composition"
    ]
    causal = composition["causal_complement_composition_lane"]
    assert causal["protected_requirements"] == {
        "33": 26,
        "39": 29,
        "40": 29,
    }
    assert causal["coverage"]["complete"] is False
    assert causal["coverage"]["incomplete_reason"] == "timed-out"
    assert causal["blocked_targets"]["32"]["terminal_blocker"] == (
        "no-movable-local-write"
    )
    assert causal["actionable_targets"]["38"]["materialized_probe_labels"] == [
        "window-order-synthetic-ig38-before-row-0",
        "window-order-synthetic-ig38-before-row-1",
    ]
    assert causal["actionable_targets"]["46"]["materialized_probe_labels"] == [
        "window-order-synthetic-ig46-before-row-0",
    ]
    assert causal["all_materialized_probe_labels"] == [
        "window-order-synthetic-ig38-before-row-0",
        "window-order-synthetic-ig38-before-row-1",
        "window-order-synthetic-ig46-before-row-0",
    ]
    scored = causal["scored_causal_candidates"]
    assert scored[0]["candidate_label"] == "gr1-draw-causal"
    assert scored[0]["target_igs"] == [38, 46]
    assert scored[0]["referenced_materialized_labels"] == [
        "window-order-synthetic-ig38-before-row-0",
        "window-order-synthetic-ig46-before-row-0",
    ]
    assert scored[0]["match_percent"] == 94.0
    assert scored[0]["frame_delta"] == -8
    assert scored[0]["source_hunks"][0]["candidate_hunk"] == (
        "row_owner = (f32) row;\n"
    )
    assert causal["bounded_pair_hints"] == [
        {
            "target_igs": [38, 46],
            "materialized_probe_labels": [
                "window-order-synthetic-ig38-before-row-0",
                "window-order-synthetic-ig38-before-row-1",
                "window-order-synthetic-ig46-before-row-0",
            ],
            "status": "bounded-search-incomplete",
        }
    ]


def test_select_order_causal_lane_dedupes_ranked_compiled_candidates() -> None:
    candidate = {
        "candidate_label": "compiled-causal",
        "rank": 1,
        "chain": ["window-order-synthetic-ig38-before-row-0"],
        "status": "ok",
        "match_percent": 94.0,
    }

    lane = debug_cli._select_order_causal_complement_composition_lane(
        function="fn_80000000",
        class_id=1,
        causal_targets={
            "38": {
                "expected_phys": 29,
                "actual_phys": 28,
                "status": "mismatched",
                "source_actionable": True,
                "materialized_probe_labels": [
                    "window-order-synthetic-ig38-before-row-0",
                ],
            },
        },
        ranked_candidates=[candidate, dict(candidate)],
        protected_registers={},
        coverage={"complete": True},
    )

    assert [entry["candidate_label"] for entry in lane["scored_causal_candidates"]] == [
        "compiled-causal",
    ]


def test_select_order_causal_lane_materializes_mixed_node_set_candidate_when_unscored() -> None:
    complement_candidate = {
        "label": "gr1-hit-ig44",
        "status": "ok",
        "source_retained": "ig44.c",
        "repair_seed_label": "sort-ig34-hit",
        "objective": {
            "match_percent": 87.14815,
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_missing": [],
            "force_phys_mismatches": {"34": {"expected": 27, "actual": 23}},
            "force_phys_distance": 4,
            "frame_delta": 16,
            "target_orders": [
                {
                    "probe_intents": [
                        {
                            "kind": "remove-interference",
                            "virtual": 34,
                            "interferer": 43,
                            "description": "split dst_iter",
                        },
                        {
                            "kind": "add-interference",
                            "virtual": 44,
                            "interferer": 63,
                            "description": "split implicit add owner",
                        },
                    ]
                }
            ],
        },
        "guard_accepted": True,
        "normalized_diff_lines": 0,
        "opcode_similarity": 0.997,
        "frame_delta": 16,
        "achieved_registers": {"44": 25, "34": 23},
        "mismatched_registers": {"34": {"expected": 27, "actual": 23}},
        "lost_protected_registers": {"34": 27},
        "complement_targets": {
            "44": {"expected": 25, "actual": 25, "status": "hit"}
        },
    }

    composition = debug_cli._select_order_protected_hit_composition_summary(
        lane_status="terminal-protected-complement-ceiling",
        register_class="gpr",
        function="mnDiagram_SortNamesByKOs",
        class_id=0,
        protected_registers={"34": 27},
        complement_targets={
            "44": {"expected": 25, "actual": 24, "status": "mismatched"}
        },
        candidates=[complement_candidate],
        best_preserving=complement_candidate,
        best_complement=complement_candidate,
        complement_source_diagnostics={
            "44": {
                "target_ig": 44,
                "target": {"expected": 25, "actual": 24, "status": "mismatched"},
                "source_actionable": True,
                "source_attribution": {
                    "kind": "implicit-temp",
                    "expression": "add r44,r49,r34",
                    "confidence": "pcode-first-def",
                },
                "materialized_probe_labels": [
                    "window-order-synthetic-ig44-before-dst-0",
                ],
                "source_probe_diagnostic": {
                    "status": "materialized",
                    "target_ig": 44,
                    "materialized_probe_labels": [
                        "window-order-synthetic-ig44-before-dst-0",
                    ],
                    "synthetic_source_probe": {
                        "handler": "implicit-add-owner-split",
                        "owner_local": "dst",
                        "split_expression": "dst",
                        "type": "u8*",
                    },
                },
            }
        },
        targeted_interference_source_diagnostics={
            "34": {
                "target_ig": 34,
                "target": {"expected": 27, "actual": 23, "status": "lost-protected"},
                "source_actionable": True,
                "source_attribution": {
                    "kind": "local",
                    "name": "dst_iter",
                    "expression": "dst_iter",
                    "type": "u8*",
                },
            },
            "44": {
                "target_ig": 44,
                "target": {"expected": 25, "actual": 25, "status": "hit"},
                "source_actionable": True,
                "source_attribution": {
                    "kind": "implicit-temp",
                    "expression": "add r44,r49,r34",
                    "confidence": "pcode-first-def",
                },
                "materialized_probe_labels": [
                    "window-order-synthetic-ig44-before-dst-0",
                ],
                "source_probe_diagnostic": {
                    "status": "materialized",
                    "target_ig": 44,
                    "materialized_probe_labels": [
                        "window-order-synthetic-ig44-before-dst-0",
                    ],
                    "synthetic_source_probe": {
                        "handler": "implicit-add-owner-split",
                        "owner_local": "dst",
                        "split_expression": "dst",
                        "type": "u8*",
                    },
                },
            },
        },
        terminal_blockers=["protected-hit-lost-by-best-complement"],
        guard_repair_ledger={
            "entries": [],
            "stop_condition": "timeout",
            "timed_out": True,
            "effective_depth": 1,
            "width": 1,
            "max_probes": 1,
        },
    )

    causal = composition["causal_complement_composition_lane"]
    scored = causal["scored_causal_candidates"]
    assert scored[0]["candidate_label"] == (
        "materialized-causal-composition-ig44"
    )
    assert scored[0]["score_status"] == "materialized-not-compiled"
    assert scored[0]["target_igs"] == [44]
    assert scored[0]["protected_requirements"] == {"34": 27}
    assert scored[0]["referenced_materialized_labels"] == [
        "window-order-synthetic-ig44-before-dst-0"
    ]
    delta = scored[0]["node_set_delta"]
    assert [entry["target_ig"] for entry in delta["missing_virtuals"]] == [34, 44]
    by_target = {entry["target_ig"]: entry for entry in delta["missing_virtuals"]}
    assert by_target[34]["current_virtual"] == "r34"
    assert by_target[34]["desired_registers"] == ["r27"]
    assert by_target[44]["current_virtual"] == "r44"
    assert by_target[44]["desired_registers"] == ["r25"]
    assert by_target[44]["source"] == {
        "kind": "synthetic-owner-split",
        "expression": "dst",
        "type": "u8*",
        "introduce_binding": True,
    }
    assert causal["bounded_pair_hints"][0]["protected_igs"] == [34]


def test_select_order_causal_lane_materializes_fpr_pair_and_subset_candidates_when_unscored() -> None:
    composition = debug_cli._select_order_protected_hit_composition_summary(
        lane_status="terminal-protected-complement-ceiling",
        register_class="fpr",
        function="mnDiagram_DrawCellNumber",
        class_id=1,
        protected_registers={"33": 26, "39": 29, "40": 29},
        complement_targets={
            "32": {"expected": 28, "actual": 27, "status": "mismatched"},
            "38": {"expected": 29, "actual": 28, "status": "mismatched"},
            "46": {"expected": 26, "actual": 1, "status": "mismatched"},
        },
        candidates=[],
        best_preserving={},
        best_complement={},
        complement_source_diagnostics={
            "32": {
                "target_ig": 32,
                "target": {"expected": 28, "actual": 27, "status": "mismatched"},
                "source_actionable": False,
                "terminal_blocker": "no-movable-local-write",
            },
            "38": {
                "target_ig": 38,
                "target": {"expected": 29, "actual": 28, "status": "mismatched"},
                "source_actionable": True,
                "source_attribution": {
                    "kind": "fpr-temp",
                    "expression": "lfs f38,60(r47)",
                    "confidence": "pcode-first-def",
                },
                "pcode_first_def": {
                    "target_ig": 38,
                    "opcode": "lfs",
                    "operands": "f38,60(r47)",
                    "expression": "lfs f38,60(r47)",
                    "confidence": "pcode-first-def",
                },
                "materialized_probe_labels": [
                    "window-order-synthetic-ig38-before-row-0",
                    "window-order-synthetic-ig38-before-row-1",
                ],
                "source_probe_diagnostic": {
                    "status": "materialized",
                    "target_ig": 38,
                    "materialized_probe_labels": [
                        "window-order-synthetic-ig38-before-row-0",
                        "window-order-synthetic-ig38-before-row-1",
                    ],
                    "synthetic_source_probe": {
                        "handler": "fpr-load-owner-split",
                        "owner_local": "row",
                        "split_expression": "(f32) row",
                        "type": "f32",
                    },
                },
            },
            "46": {
                "target_ig": 46,
                "target": {"expected": 26, "actual": 1, "status": "mismatched"},
                "source_actionable": True,
                "source_attribution": {
                    "kind": "fpr-temp",
                    "expression": "fsubs f46,f45,f44",
                    "confidence": "pcode-first-def",
                },
                "materialized_probe_labels": [
                    "window-order-synthetic-ig46-before-row-0",
                ],
                "source_probe_diagnostic": {
                    "status": "materialized",
                    "target_ig": 46,
                    "materialized_probe_labels": [
                        "window-order-synthetic-ig46-before-row-0",
                    ],
                    "synthetic_source_probe": {
                        "handler": "fpr-arith-owner-split",
                        "owner_local": "row_offset_adj",
                        "split_expression": "row_offset - 0.4f",
                        "type": "f32",
                    },
                },
            },
        },
        terminal_blockers=["protected-hit-lost-by-best-complement"],
        guard_repair_ledger={
            "entries": [],
            "stop_condition": "timeout",
            "timed_out": True,
            "effective_depth": 1,
            "width": 1,
            "max_probes": 1,
        },
    )

    causal = composition["causal_complement_composition_lane"]
    assert causal["blocked_targets"]["32"]["terminal_blocker"] == (
        "no-movable-local-write"
    )
    scored = causal["scored_causal_candidates"]
    assert [entry["target_igs"] for entry in scored] == [[38, 46], [38], [46]]
    assert all(entry["score_status"] == "materialized-not-compiled" for entry in scored)
    pair = scored[0]
    assert pair["protected_requirements"] == {"33": 26, "39": 29, "40": 29}
    assert pair["referenced_materialized_labels"] == [
        "window-order-synthetic-ig38-before-row-0",
        "window-order-synthetic-ig38-before-row-1",
        "window-order-synthetic-ig46-before-row-0",
    ]
    assert [entry["target_ig"] for entry in pair["node_set_delta"]["missing_virtuals"]] == [
        38,
        46,
    ]
    by_target = {
        entry["target_ig"]: entry
        for entry in pair["node_set_delta"]["missing_virtuals"]
    }
    assert by_target[38]["desired_registers"] == ["f29"]
    assert by_target[38]["source"]["expression"] == "row"
    assert by_target[46]["desired_registers"] == ["f26"]
    assert by_target[46]["source"]["expression"] == "row_offset - 0.4f"
    reqs = requests_from_node_set_delta(
        pair["node_set_delta"],
        include_introducible=True,
        max_requests=0,
    )
    assert [req.target_ig for req in reqs] == [38, 46]


def test_select_order_materialized_causal_candidates_filter_targeted_delta_to_combo() -> None:
    targeted_delta = {
        "kind": "node-set-delta",
        "function": "mnDiagram_DrawCellNumber",
        "class_id": 1,
        "missing_virtuals": [
            {
                "target_ig": 33,
                "current_virtual": "f33",
                "desired_registers": ["f26"],
                "source": {
                    "kind": "local",
                    "name": "protected_y",
                    "expression": "protected_y",
                    "type": "f32",
                },
            },
            {
                "target_ig": 38,
                "current_virtual": "f38",
                "desired_registers": ["f29"],
                "source": {
                    "kind": "synthetic-owner-split",
                    "expression": "row",
                    "type": "f32",
                    "introduce_binding": True,
                },
            },
            {
                "target_ig": 46,
                "current_virtual": "f46",
                "desired_registers": ["f26"],
                "source": {
                    "kind": "synthetic-owner-split",
                    "expression": "row_offset - 0.4f",
                    "type": "f32",
                    "introduce_binding": True,
                },
            },
        ],
    }

    candidates = debug_cli._select_order_materialized_causal_candidates(
        function="mnDiagram_DrawCellNumber",
        class_id=1,
        causal_targets={
            "38": {
                "expected_phys": 29,
                "actual_phys": 28,
                "status": "mismatched",
                "source_actionable": True,
                "materialized_probe_labels": ["ig38-owner"],
            },
            "46": {
                "expected_phys": 26,
                "actual_phys": 1,
                "status": "mismatched",
                "source_actionable": True,
                "materialized_probe_labels": ["ig46-owner"],
            },
        },
        actionable_igs=[38, 46],
        label_to_targets={"ig38-owner": {38}, "ig46-owner": {46}},
        all_labels=["ig38-owner", "ig46-owner"],
        protected_registers={"33": 26},
        targeted_interference={"materialized_node_set_delta": targeted_delta},
    )

    assert [candidate["target_igs"] for candidate in candidates] == [
        [38, 46],
        [38],
        [46],
    ]
    assert [
        [entry["target_ig"] for entry in candidate["node_set_delta"]["missing_virtuals"]]
        for candidate in candidates
    ] == [[33, 38, 46], [33, 38], [33, 46]]


def test_select_order_subtractive_source_hunk_repair_generates_reverts_and_type_variants() -> None:
    base_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            use(GetNameText(sorted_names[j]));
            use(GetNameText(sorted_names[max_idx]));
        }
    """)
    downhill_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            u8 sorted_names_probe = sorted_names[j];
            use(GetNameText(sorted_names_probe));
            u8 max_probe = sorted_names[max_idx];
            use(GetNameText(max_probe));
        }
    """)

    probes = debug_cli._select_order_subtractive_source_hunk_repair_probes(
        base_source=base_source,
        downhill_source=downhill_source,
        function="fn_80000000",
        protected_hits={32: 29, 33: 30},
        max_probes=8,
    )

    revert = next(
        probe for probe in probes
        if probe.operator == "source-hunk-subtractive-repair"
    )
    assert "use(GetNameText(sorted_names[j]));" in revert.source_text
    assert "sorted_names_probe = sorted_names[j]" not in revert.source_text
    assert "u8 max_probe = sorted_names[max_idx];" in revert.source_text
    assert revert.provenance["repair_action"] == "revert-hunk"
    assert revert.provenance["protected_force_phys_hits"] == {"32": 29, "33": 30}

    type_variant = next(
        probe for probe in probes
        if probe.operator == "source-hunk-type-variant"
    )
    assert "int sorted_names_probe = sorted_names[j];" in type_variant.source_text
    assert type_variant.provenance["repair_action"] == "type-variant"
    assert type_variant.provenance["from_type"] == "u8"
    assert type_variant.provenance["to_type"] == "int"


def test_select_order_source_hunk_crossover_generates_donor_recipient_probe() -> None:
    base_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            use(GetNameText(sorted_names[j]));
            use(GetNameText(sorted_names[max_idx]));
        }
    """)
    left_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            u8 sorted_names_probe = sorted_names[j];
            use(GetNameText(sorted_names_probe));
            use(GetNameText(sorted_names[max_idx]));
        }
    """)
    right_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            use(GetNameText(sorted_names[j]));
            u8 max_probe = sorted_names[max_idx];
            use(GetNameText(max_probe));
        }
    """)

    probes = debug_cli._select_order_source_hunk_crossover_probes(
        base_source=base_source,
        seed_sources=[
            {
                "label": "left-lane",
                "source_text": left_source,
                "protected_hits": {"34": 27},
            },
            {
                "label": "right-lane",
                "source_text": right_source,
                "protected_hits": {"44": 25},
            },
        ],
        function="fn_80000000",
        max_probes=4,
    )

    crossover = next(
        probe for probe in probes
        if probe.operator == "source-hunk-crossover"
    )
    assert "u8 sorted_names_probe = sorted_names[j];" in crossover.source_text
    assert "u8 max_probe = sorted_names[max_idx];" in crossover.source_text
    assert "use(GetNameText(sorted_names_probe));" in crossover.source_text
    assert "use(GetNameText(max_probe));" in crossover.source_text
    assert crossover.provenance["repair_action"] == "cross-neighborhood-crossover"
    assert crossover.provenance["protected_force_phys_hits"] == {
        "34": 27,
        "44": 25,
    }
    assert crossover.provenance["donor_label"] in {"left-lane", "right-lane"}
    assert crossover.provenance["recipient_label"] in {"left-lane", "right-lane"}
    assert crossover.provenance["donor_label"] != crossover.provenance[
        "recipient_label"
    ]


def test_select_order_source_hunk_crossover_dedupes_same_scope_declarations() -> None:
    base_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            if (left) {
                use(GetNameText(sorted_names[j]));
            }
            if (right) {
                use(GetNameText(sorted_names[max_idx]));
            }
        }
    """)
    left_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            char* ll_probe_helper_result_0;
            if (left) {
                ll_probe_helper_result_0 = GetNameText(sorted_names[j]);
                use(ll_probe_helper_result_0);
            }
            if (right) {
                use(GetNameText(sorted_names[max_idx]));
            }
        }
    """)
    right_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            if (left) {
                use(GetNameText(sorted_names[j]));
            }
            char* ll_probe_helper_result_0;
            if (right) {
                ll_probe_helper_result_0 = GetNameText(sorted_names[max_idx]);
                use(ll_probe_helper_result_0);
            }
        }
    """)

    probes = debug_cli._select_order_source_hunk_crossover_probes(
        base_source=base_source,
        seed_sources=[
            {
                "label": "left-lane",
                "source_text": left_source,
                "protected_hits": {"34": 27},
            },
            {
                "label": "right-lane",
                "source_text": right_source,
                "protected_hits": {"44": 25},
            },
        ],
        function="fn_80000000",
        max_probes=4,
    )

    crossover_sources = [
        probe.source_text
        for probe in probes
        if probe.operator == "source-hunk-crossover"
    ]
    assert crossover_sources
    assert all(
        source.count("char* ll_probe_helper_result_0;") == 1
        for source in crossover_sources
        if "ll_probe_helper_result_0" in source
    )
    crossover = next(
        probe for probe in probes
        if probe.operator == "source-hunk-crossover"
        and "ll_probe_helper_result_0 = GetNameText(sorted_names[max_idx]);"
        in probe.source_text
    )
    assert "ll_probe_helper_result_0 = GetNameText(sorted_names[j]);" in (
        crossover.source_text
    )
    assert "ll_probe_helper_result_0 = GetNameText(sorted_names[max_idx]);" in (
        crossover.source_text
    )


def test_select_order_source_hunk_crossover_recombines_atomized_components() -> None:
    base_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            int a = A();
            int b = B();
            int c = C();
        }
    """)
    left_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            int a = A_left();
            int b = B_left();
            int c = C();
        }
    """)
    right_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            int a = A_right();
            int b = B();
            int c = C_right();
        }
    """)

    probes = debug_cli._select_order_source_hunk_crossover_probes(
        base_source=base_source,
        seed_sources=[
            {
                "label": "ig34-hit",
                "source_text": left_source,
                "protected_hits": {"34": 27},
            },
            {
                "label": "ig44-hit",
                "source_text": right_source,
                "protected_hits": {"44": 25},
            },
        ],
        function="fn_80000000",
        max_probes=32,
    )

    crossover = next(
        probe for probe in probes
        if probe.operator == "source-hunk-crossover"
        and "int a = A_right();" in probe.source_text
        and "int b = B_left();" in probe.source_text
        and "int c = C_right();" in probe.source_text
    )
    assert crossover.provenance["repair_action"] == (
        "cross-neighborhood-atomized-crossover"
    )
    assert crossover.provenance["component_depth"] == 3
    assert crossover.provenance["protected_force_phys_hits"] == {
        "34": 27,
        "44": 25,
    }
    assert [
        component["component_kind"]
        for component in crossover.provenance["source_components"]
    ] == ["line", "line", "line"]
    assert any(
        "B_left()" in component["expression_provenance"]["candidate_calls"]
        for component in crossover.provenance["source_components"]
    )


def test_select_order_guard_repair_summary_includes_saved_register_deltas_for_fpr_frontier() -> None:
    variant = {
        "label": "gr1-fpr-frontier",
        "status": "ok",
        "repair_seed_label": "seed-fpr",
        "parent_label": "seed-fpr",
        "path": "probe.c",
        "source_retained": "probe.c",
        "objective": {
            "match_percent": 91.0,
            "force_phys_satisfied_count": 1,
            "force_phys_distance": 0,
            "force_phys_targets": {33: 26},
            "force_phys_missing": [],
            "force_phys_mismatches": {},
            "frame_delta": 8,
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "normalized-structural-match",
            "normalized_diff_lines": 2,
            "frame_delta": 8,
        },
        "delta": {
            "saved_added": ["f31", "r29"],
            "saved_removed": ["f29"],
        },
    }

    candidate_summary = debug_cli._select_order_guard_repair_candidate_summary(
        variant,
    )
    result_summary = debug_cli._select_order_guard_repair_result_summary(variant)

    assert candidate_summary is not None
    assert candidate_summary["saved_register_delta"] == {
        "saved_added": ["f31", "r29"],
        "saved_removed": ["f29"],
        "saved_fpr_added": ["f31"],
        "saved_fpr_removed": ["f29"],
    }
    assert result_summary is not None
    assert result_summary["saved_register_delta"]["saved_fpr_added"] == ["f31"]
    complement = debug_cli._select_order_complement_candidate_summary(
        result_summary,
        protected_registers={"33": 26},
    )
    assert complement["saved_register_delta"]["saved_fpr_removed"] == ["f29"]


def test_select_order_guard_repair_scores_subtractive_source_hunk_probe(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)
    base = tmp_path / "base.c"
    downhill = tmp_path / "downhill.c"
    base.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    use(GetNameText(sorted_names[j]));\n"
        "}\n"
    )
    downhill.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    u8 sorted_names_probe = sorted_names[j];\n"
        "    use(GetNameText(sorted_names_probe));\n"
        "}\n"
    )
    campaign = tmp_path / "campaign"

    def fake_compile(*args, **kwargs) -> str:
        path = pathlib.Path(kwargs["diff_input"].path)
        if path.name.startswith("gr"):
            return TARGET_ORDER_RIGHT_PHYS
        if path == downhill:
            return ONE_FORCE_PHYS_HIT
        return TARGET_ORDER_RIGHT_PHYS

    def fake_source_score(*args, **kwargs):
        text = pathlib.Path(kwargs["path"]).read_text()
        if "sorted_names_probe" in text:
            return debug_cli._SourceCandidateRealScore(
                87.0,
                None,
                structural_guard={
                    "accepted": False,
                    "shape_preserved": False,
                    "classification_primary": "inline-boundary-toolchain-artifact",
                    "normalized_diff_lines": 11,
                    "frame_delta": 0,
                },
            )
        return debug_cli._SourceCandidateRealScore(
            94.0,
            None,
            structural_guard={
                "accepted": True,
                "shape_preserved": True,
                "classification_primary": "normalized-structural-match",
                "normalized_diff_lines": 0,
                "frame_delta": 0,
            },
        )

    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda probes, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_score",
        fake_source_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(base),
            "--candidate",
            f"downhill:indexed-byte={downhill}",
            "--transform-force-phys",
            "32:29,33:30",
            "--guard-repair-depth",
            "1",
            "--guard-repair-width",
            "1",
            "--no-compile-probes",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    ledger = json.loads(pathlib.Path(payload["guard_repair_ledger"]).read_text())
    assert ledger["seeds"][0]["protected_force_phys_hits"] == {"33": 30}
    assert ledger["seeds"][0]["protected_complement_targets"] == {
        "32": {"expected": 29, "actual": 3, "status": "mismatched"}
    }
    repair_entries = [
        row for row in ledger["entries"]
        if "source-hunk" in row["chain"][-1]
    ]
    assert repair_entries
    assert repair_entries[0]["status"] == "ok"
    protected_complement = repair_entries[0]["protected_complement"]
    assert protected_complement["protected_registers"] == {"33": 30}
    assert protected_complement["complement_targets"] == {
        "32": {"expected": 29, "actual": 3, "status": "mismatched"}
    }
    assert protected_complement["candidate"]["preserved_protected_count"] == 1
    assert protected_complement["candidate"]["complement_hit_count"] == 1
    assert protected_complement["candidate"]["complement_targets"]["32"] == {
        "expected": 29,
        "actual": 29,
        "status": "hit",
    }
    repair_variant = next(
        variant for variant in payload["variants"]
        if variant.get("repair_seed_label") == "downhill"
        and variant["operator"] == "source-hunk-subtractive-repair"
    )
    assert repair_variant["structural_guard"]["accepted"] is True
    assert repair_variant["objective"]["force_phys_satisfied_count"] == 2


def test_select_order_guard_repair_expands_complement_hit_recovery_frontier(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)
    base = tmp_path / "base.c"
    downhill = tmp_path / "downhill.c"
    base.write_text("void fn_80000000(void) { /* seed_protected */ }\n")
    downhill.write_text("void fn_80000000(void) { /* seed_protected */ }\n")
    campaign = tmp_path / "campaign"

    def fake_transform_probes(probes, *, source_text: str | None, **kwargs):
        if source_text is None:
            return None
        if "seed_protected" in source_text:
            probes.append(
                LifetimeLayoutProbe(
                    label="preserve-protected",
                    operator="transform-corpus:test",
                    description="Keeps only the protected assignment.",
                    source_text=source_text.replace(
                        "seed_protected",
                        "preserve_protected",
                    ),
                    provenance={"kind": "test", "mode": "preserve"},
                )
            )
            probes.append(
                LifetimeLayoutProbe(
                    label="hit-complement",
                    operator="transform-corpus:test",
                    description="Hits complement but loses protected.",
                    source_text=source_text.replace(
                        "seed_protected",
                        "hit_complement",
                    ),
                    provenance={"kind": "test", "mode": "complement"},
                )
            )
        elif "hit_complement" in source_text:
            probes.append(
                LifetimeLayoutProbe(
                    label="recover-both",
                    operator="transform-corpus:test",
                    description="Recovers protected while keeping complement.",
                    source_text=source_text.replace(
                        "hit_complement",
                        "recover_both",
                    ),
                    provenance={"kind": "test", "mode": "recover"},
                )
            )
        return None

    def fake_compile(*args, **kwargs) -> str:
        text = pathlib.Path(kwargs["diff_input"].path).read_text()
        if "recover_both" in text:
            return TARGET_ORDER_RIGHT_PHYS
        if "hit_complement" in text:
            return COMPLEMENT_FORCE_PHYS_HIT
        return ONE_FORCE_PHYS_HIT

    def fake_source_score(*args, **kwargs):
        text = pathlib.Path(kwargs["path"]).read_text()
        accepted = "recover_both" in text
        return debug_cli._SourceCandidateRealScore(
            98.0 if accepted else 90.0,
            None,
            structural_guard={
                "accepted": accepted,
                "shape_preserved": accepted,
                "classification_primary": (
                    "normalized-structural-match"
                    if accepted else "inline-boundary-toolchain-artifact"
                ),
                "normalized_diff_lines": 0 if accepted else 21,
                "frame_delta": 0,
            },
        )

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: {"ran": True, "leads": []},
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        fake_transform_probes,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_score",
        fake_source_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(base),
            "--candidate",
            f"downhill:indexed-byte={downhill}",
            "--transform-force-phys",
            "32:29,33:30",
            "--guard-repair-depth",
            "2",
            "--guard-repair-width",
            "1",
            "--no-compile-probes",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    ledger = json.loads(pathlib.Path(payload["guard_repair_ledger"]).read_text())
    assert ledger["reconciliation_frontier"]
    recovery_seed = ledger["reconciliation_frontier"][0]
    assert recovery_seed["source_label"].endswith("hit-complement")
    assert recovery_seed["repair_seed_label"] == "downhill"
    assert recovery_seed["depth_promoted_from"] == 1
    assert recovery_seed["depth_promoted_to"] == 2
    assert "complement-hit candidate lost protected" in (
        recovery_seed["selection_reason"]
    )
    assert recovery_seed["chain"] == ["hit-complement"]
    assert recovery_seed["original_protected_force_phys_hits"] == {"33": 30}
    assert recovery_seed["preserved_original_protected_hits"] == {}
    assert recovery_seed["lost_protected_registers"] == {"33": 30}
    assert recovery_seed["hit_complement_targets"] == {
        "32": {"expected": 29, "actual": 29, "status": "hit"}
    }
    assert recovery_seed["achieved_force_phys_hits"] == {"32": 29}
    assert recovery_seed["protected_force_phys_hits"] == {"32": 29}
    assert recovery_seed["protected_complement_targets"] == {
        "33": {"expected": 30, "actual": 3, "status": "mismatched"}
    }
    recovery_entries = [
        row for row in ledger["entries"]
        if row["depth"] == 2 and row["chain"][-1] == "recover-both"
    ]
    assert recovery_entries
    assert recovery_entries[0]["reconciliation_seed"]["source_label"] == (
        recovery_seed["source_label"]
    )
    assert recovery_entries[0]["protected_force_phys_hits"] == {"32": 29}
    assert recovery_entries[0]["protected_complement"]["candidate"][
        "complement_hit_count"
    ] == 1
    recovery_variant = next(
        variant for variant in payload["variants"]
        if variant.get("depth") == 2 and variant["chain"][-1] == "recover-both"
    )
    assert recovery_variant["objective"]["force_phys_satisfied"] is True
    assert recovery_variant["structural_guard"]["accepted"] is True


def test_select_order_guard_repair_rewrites_selected_complement_hit_frontier(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)
    base = tmp_path / "base.c"
    downhill = tmp_path / "downhill.c"
    base.write_text("void fn_80000000(void) { /* seed_protected */ }\n")
    downhill.write_text("void fn_80000000(void) { /* seed_protected */ }\n")
    campaign = tmp_path / "campaign"

    def fake_transform_probes(probes, *, source_text: str | None, **kwargs):
        if source_text is None:
            return None
        if "seed_protected" in source_text:
            probes.append(
                LifetimeLayoutProbe(
                    label="hit-complement",
                    operator="transform-corpus:test",
                    description="Hits complement but loses protected.",
                    source_text=source_text.replace(
                        "seed_protected",
                        "hit_complement",
                    ),
                    provenance={"kind": "test", "mode": "complement"},
                )
            )
        elif "hit_complement" in source_text:
            probes.append(
                LifetimeLayoutProbe(
                    label="recover-both",
                    operator="transform-corpus:test",
                    description="Recovers protected while keeping complement.",
                    source_text=source_text.replace(
                        "hit_complement",
                        "recover_both",
                    ),
                    provenance={"kind": "test", "mode": "recover"},
                )
            )
        return None

    def fake_compile(*args, **kwargs) -> str:
        text = pathlib.Path(kwargs["diff_input"].path).read_text()
        if "recover_both" in text:
            return TARGET_ORDER_RIGHT_PHYS
        if "hit_complement" in text:
            return COMPLEMENT_FORCE_PHYS_HIT
        return ONE_FORCE_PHYS_HIT

    def fake_source_score(*args, **kwargs):
        text = pathlib.Path(kwargs["path"]).read_text()
        accepted = "hit_complement" in text or "recover_both" in text
        return debug_cli._SourceCandidateRealScore(
            98.0 if accepted else 90.0,
            None,
            structural_guard={
                "accepted": accepted,
                "shape_preserved": accepted,
                "classification_primary": (
                    "normalized-structural-match"
                    if accepted else "inline-boundary-toolchain-artifact"
                ),
                "normalized_diff_lines": 0 if accepted else 21,
                "frame_delta": 0,
            },
        )

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: {"ran": True, "leads": []},
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        fake_transform_probes,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_score",
        fake_source_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(base),
            "--candidate",
            f"downhill:indexed-byte={downhill}",
            "--transform-force-phys",
            "32:29,33:30",
            "--guard-repair-depth",
            "2",
            "--guard-repair-width",
            "1",
            "--no-compile-probes",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    ledger = json.loads(pathlib.Path(payload["guard_repair_ledger"]).read_text())
    recovery_seed = ledger["reconciliation_frontier"][0]
    assert recovery_seed["source_label"].endswith("hit-complement")
    recovery_entries = [
        row for row in ledger["entries"]
        if row["depth"] == 2 and row["chain"][-1] == "recover-both"
    ]
    assert recovery_entries
    assert recovery_entries[0]["reconciliation_seed"]["source_label"] == (
        recovery_seed["source_label"]
    )
    assert recovery_entries[0]["protected_force_phys_hits"] == {"32": 29}
    assert recovery_entries[0]["protected_complement_targets"] == {
        "33": {"expected": 30, "actual": 3, "status": "mismatched"}
    }
    recovery_variant = next(
        variant for variant in payload["variants"]
        if variant.get("depth") == 2 and variant["chain"][-1] == "recover-both"
    )
    assert recovery_variant["objective"]["force_phys_satisfied"] is True


def test_select_order_search_threads_complement_source_diagnostics_into_json(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)
    base = tmp_path / "base.c"
    downhill = tmp_path / "downhill.c"
    base.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    use(GetNameText(sorted_names[j]));\n"
        "}\n"
    )
    downhill.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    u8 sorted_names_probe = sorted_names[j];\n"
        "    use(GetNameText(sorted_names_probe));\n"
        "}\n"
    )
    campaign = tmp_path / "campaign"
    source_attr = {
        "kind": "fpr-temp",
        "source_file": str(downhill),
        "source_line": None,
        "expression": "lfs f32,60(r47)",
        "confidence": "pcode-first-def",
    }

    def fake_compile(*args, **kwargs) -> str:
        path = pathlib.Path(kwargs["diff_input"].path)
        if path.name.startswith("gr"):
            return TARGET_ORDER_RIGHT_PHYS
        if path == downhill:
            return ONE_FORCE_PHYS_HIT
        return TARGET_ORDER_RIGHT_PHYS

    def fake_source_score(*args, **kwargs):
        text = pathlib.Path(kwargs["path"]).read_text()
        accepted = "sorted_names_probe" not in text
        return debug_cli._SourceCandidateRealScore(
            94.0 if accepted else 87.0,
            None,
            structural_guard={
                "accepted": accepted,
                "shape_preserved": accepted,
                "classification_primary": (
                    "normalized-structural-match"
                    if accepted else "inline-boundary-toolchain-artifact"
                ),
                "normalized_diff_lines": 0 if accepted else 11,
                "frame_delta": 0,
            },
        )

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: {"ran": True, "leads": []},
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {32: source_attr},
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda probes, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_score",
        fake_source_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(base),
            "--candidate",
            f"downhill:indexed-byte={downhill}",
            "--transform-force-phys",
            "32:29,33:30",
            "--guard-repair-depth",
            "1",
            "--guard-repair-width",
            "1",
            "--no-compile-probes",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    diagnostics = payload["guard_repair_summary"]["protected_complement_repair"][
        "complement_source_diagnostics"
    ]
    assert diagnostics["32"]["source_attribution"] == source_attr
    assert diagnostics["32"]["source_actionable"] is False
    assert diagnostics["32"]["target"]["status"] == "hit"
    assert "terminal_blocker" not in diagnostics["32"]


def test_select_order_guard_repair_failed_source_hunk_retains_source_provenance(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)
    base = tmp_path / "base.c"
    downhill = tmp_path / "downhill.c"
    base.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    use(GetNameText(sorted_names[j]));\n"
        "}\n"
    )
    downhill.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    u8 sorted_names_probe = sorted_names[j];\n"
        "    use(GetNameText(sorted_names_probe));\n"
        "}\n"
    )
    campaign = tmp_path / "campaign"

    def fake_compile(*args, **kwargs) -> str:
        path = pathlib.Path(kwargs["diff_input"].path)
        if path.name.startswith("gr"):
            raise RuntimeError("synthetic repair compile failure")
        return TARGET_ORDER_RIGHT_PHYS

    def fake_source_score(*args, **kwargs):
        return debug_cli._SourceCandidateRealScore(
            87.0,
            None,
            structural_guard={
                "accepted": False,
                "shape_preserved": False,
                "classification_primary": "inline-boundary-toolchain-artifact",
                "normalized_diff_lines": 11,
                "frame_delta": 0,
            },
        )

    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda probes, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_score",
        fake_source_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(base),
            "--candidate",
            f"downhill:indexed-byte={downhill}",
            "--transform-force-phys",
            "32:29,33:30",
            "--guard-repair-depth",
            "1",
            "--guard-repair-width",
            "1",
            "--no-compile-probes",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    ledger = json.loads(pathlib.Path(payload["guard_repair_ledger"]).read_text())
    repair_entry = next(
        row for row in ledger["entries"]
        if "source-hunk" in row["chain"][-1]
    )
    assert repair_entry["status"] == "failed"
    assert repair_entry["error"] == "synthetic repair compile failure"
    assert "candidate_text" not in repair_entry["error"]
    assert "source_hunk" in repair_entry
    assert "fn_80000000" in repair_entry["source_hunk"]

    repair_variant = next(
        variant for variant in payload["variants"]
        if variant.get("repair_seed_label") == "downhill"
        and variant["operator"] == "source-hunk-subtractive-repair"
    )
    assert repair_variant["source_hunk"] == repair_entry["source_hunk"]


def test_select_order_guard_repair_failed_crossover_retains_probe_provenance(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)
    base = tmp_path / "base.c"
    left = tmp_path / "left.c"
    right = tmp_path / "right.c"
    base.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    use(GetNameText(sorted_names[j]));\n"
        "    use(GetNameText(sorted_names[max_idx]));\n"
        "}\n"
    )
    left.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    u8 sorted_names_probe = sorted_names[j];\n"
        "    use(GetNameText(sorted_names_probe));\n"
        "    use(GetNameText(sorted_names[max_idx]));\n"
        "}\n"
    )
    right.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    use(GetNameText(sorted_names[j]));\n"
        "    u8 max_probe = sorted_names[max_idx];\n"
        "    use(GetNameText(max_probe));\n"
        "}\n"
    )
    campaign = tmp_path / "campaign"

    def fake_compile(*args, **kwargs) -> str:
        path = pathlib.Path(kwargs["diff_input"].path)
        if path.name.startswith("gr"):
            raise RuntimeError("synthetic crossover compile failure")
        return TARGET_ORDER_RIGHT_PHYS

    def fake_source_score(*args, **kwargs):
        return debug_cli._SourceCandidateRealScore(
            89.0,
            None,
            structural_guard={
                "accepted": False,
                "shape_preserved": False,
                "classification_primary": "inline-boundary-toolchain-artifact",
                "normalized_diff_lines": 9,
                "frame_delta": 8,
            },
        )

    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda probes, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_score",
        fake_source_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(base),
            "--candidate",
            f"left:source-lane={left}",
            "--candidate",
            f"right:source-lane={right}",
            "--transform-force-phys",
            "32:29,33:30",
            "--guard-repair-depth",
            "1",
            "--guard-repair-width",
            "2",
            "--no-compile-probes",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    ledger = json.loads(pathlib.Path(payload["guard_repair_ledger"]).read_text())
    crossover_entry = next(
        row for row in ledger["entries"]
        if "source-hunk-crossover" in row["chain"][-1]
    )
    assert crossover_entry["status"] == "failed"
    assert crossover_entry["error"] == "synthetic crossover compile failure"
    assert crossover_entry["protected_complement"] is None
    assert "source_hunk" in crossover_entry
    assert "fn_80000000" in crossover_entry["source_hunk"]
    probe = crossover_entry["probe"]
    assert probe["operator"] == "source-hunk-crossover"
    assert probe["provenance"]["repair_action"] == (
        "cross-neighborhood-crossover"
    )
    assert probe["provenance"]["donor_label"] in {"left", "right"}
    assert probe["provenance"]["recipient_label"] in {"left", "right"}
    assert probe["provenance"]["donor_label"] != probe["provenance"][
        "recipient_label"
    ]

    repair_variant = next(
        variant for variant in payload["variants"]
        if variant.get("repair_seed_label") == "cross-neighborhood"
        and variant["operator"] == "source-hunk-crossover"
    )
    assert repair_variant["probe"] == crossover_entry["probe"]


def test_select_order_guard_repair_scores_crossover_source_hunk_probe(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)
    base = tmp_path / "base.c"
    left = tmp_path / "left.c"
    right = tmp_path / "right.c"
    base.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    use(GetNameText(sorted_names[j]));\n"
        "    use(GetNameText(sorted_names[max_idx]));\n"
        "}\n"
    )
    left.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    u8 sorted_names_probe = sorted_names[j];\n"
        "    use(GetNameText(sorted_names_probe));\n"
        "    use(GetNameText(sorted_names[max_idx]));\n"
        "}\n"
    )
    right.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    use(GetNameText(sorted_names[j]));\n"
        "    u8 max_probe = sorted_names[max_idx];\n"
        "    use(GetNameText(max_probe));\n"
        "}\n"
    )
    campaign = tmp_path / "campaign"

    def fake_compile(*args, **kwargs) -> str:
        return TARGET_ORDER_RIGHT_PHYS

    def fake_source_score(*args, **kwargs):
        text = pathlib.Path(kwargs["path"]).read_text()
        if "sorted_names_probe" in text and "max_probe" in text:
            return debug_cli._SourceCandidateRealScore(
                95.0,
                None,
                structural_guard={
                    "accepted": True,
                    "shape_preserved": True,
                    "classification_primary": "normalized-structural-match",
                    "normalized_diff_lines": 0,
                    "frame_delta": 0,
                },
            )
        return debug_cli._SourceCandidateRealScore(
            89.0,
            None,
            structural_guard={
                "accepted": False,
                "shape_preserved": False,
                "classification_primary": "inline-boundary-toolchain-artifact",
                "normalized_diff_lines": 9,
                "frame_delta": 8,
            },
        )

    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda probes, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_score",
        fake_source_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(base),
            "--candidate",
            f"left:source-lane={left}",
            "--candidate",
            f"right:source-lane={right}",
            "--transform-force-phys",
            "32:29,33:30",
            "--guard-repair-depth",
            "1",
            "--guard-repair-width",
            "2",
            "--no-compile-probes",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    ledger = json.loads(pathlib.Path(payload["guard_repair_ledger"]).read_text())
    crossover_entries = [
        row for row in ledger["entries"]
        if "source-hunk-crossover" in row["chain"][-1]
    ]
    assert crossover_entries
    assert crossover_entries[0]["status"] == "ok"
    repair_variant = next(
        variant for variant in payload["variants"]
        if variant.get("repair_seed_label") == "cross-neighborhood"
        and variant["operator"] == "source-hunk-crossover"
    )
    assert repair_variant["structural_guard"]["accepted"] is True
    assert repair_variant["objective"]["force_phys_satisfied_count"] == 2


def test_select_order_source_bridge_summary_explains_order_leads_and_blockers() -> None:
    fallback = {
        "ran": True,
        "leads": [
            {
                "target_ig": 34,
                "order_move": ["before", 43],
                "move_distance": 10,
                "perturbed_reg": 27,
            },
            {
                "target_ig": 44,
                "order_move": ["after", 34],
                "move_distance": 4,
                "perturbed_reg": 25,
            },
        ],
    }
    attrs = {
        34: {
            "kind": "local",
            "name": "j",
            "source_file": "src/melee/mn/mndiagram.c",
            "source_line": 1234,
            "confidence": "high",
        },
    }
    diagnostics = {
        "fallback_leads": 2,
        "source_attributed_leads": 1,
        "listed_source_probes": 0,
    }
    variants = [
        {
            "label": "indexed-byte",
            "status": "ok",
            "operator": "transform-corpus:indexed_byte_address_temp_steering",
            "objective": {
                "force_phys_targets": {"34": 27, "44": 25},
                "force_phys_satisfied_count": 0,
                "force_phys_mismatches": {
                    "34": {"expected": 27, "actual": 25},
                    "44": {"expected": 25, "actual": 28},
                },
                "force_phys_missing": [],
                "force_phys_distance": 5,
                "frame_delta": 0,
                "match_percent": 99.3,
            },
            "structural_guard": {"accepted": True},
        },
        {
            "label": "pad-stack",
            "status": "ok",
            "operator": "lifetime-layout",
            "objective": {
                "force_phys_targets": {"34": 27, "44": 25},
                "force_phys_satisfied_count": 1,
                "force_phys_mismatches": {
                    "34": {"expected": 27, "actual": 24}
                },
                "force_phys_missing": [],
                "force_phys_distance": 3,
                "frame_delta": 8,
                "match_percent": 99.1,
            },
            "structural_guard": {
                "accepted": False,
                "rejection_reason": "stack-layout frame_delta=8",
            },
        },
    ]

    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=variants,
        force_phys={34: 27, 44: 25},
        window_order_fallback=fallback,
        window_order_source_attributions=attrs,
        window_order_probe_diagnostics=diagnostics,
        diagnostic_buckets={},
    )

    assert summary["status"] == "blocked"
    assert summary["dominant_blocker"] == "window-order-leads-not-materialized"
    assert summary["leads"][0]["source"]["name"] == "j"
    assert summary["leads"][1]["source"] is None
    assert "indexed-byte-address-temp-shape" in summary["blocker_classes"]
    assert "stack-layout" in summary["blocker_classes"]
    action_kinds = [action["kind"] for action in summary["ranked_actions"]]
    assert "try-window-order-source-move" not in action_kinds
    assert "inspect-window-order-source-mobility" in action_kinds
    assert "inspect-indexed-byte-address-temp-shape" in action_kinds


def test_select_order_source_bridge_attaches_per_lead_terminal_blockers() -> None:
    fallback = {
        "ran": True,
        "leads": [
            {
                "target_ig": 34,
                "order_move": ["before", 43],
                "move_distance": 10,
                "perturbed_reg": 27,
            },
            {
                "target_ig": 34,
                "order_move": ["after", 75],
                "move_distance": 3,
                "perturbed_reg": 28,
            },
        ],
    }
    attrs = {
        34: {
            "kind": "local",
            "name": "dst_iter",
            "source_file": "src/melee/mn/mndiagram.c",
            "source_line": 911,
            "confidence": "low",
        },
    }
    diagnostics = {
        "fallback_leads": 1,
        "source_attributed_leads": 1,
        "listed_source_probes": 0,
        "lead_diagnostics": [{
            "lead": fallback["leads"][0],
            "target_ig": 34,
            "direction": "before",
            "status": "blocked",
            "terminal_blocker": "ambiguous-movable-local-write",
            "source_attribution": attrs[34],
            "source_local": "dst_iter",
            "movable_write_count": 2,
            "candidate_destinations": [],
        }, {
            "lead": fallback["leads"][1],
            "target_ig": 34,
            "direction": "after",
            "status": "blocked",
            "terminal_blocker": "no-legal-destination",
            "source_attribution": attrs[34],
            "source_local": "dst_iter",
            "movable_write_count": 1,
            "candidate_destinations": [],
        }],
    }

    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[],
        force_phys={34: 27},
        window_order_fallback=fallback,
        window_order_source_attributions=attrs,
        window_order_probe_diagnostics=diagnostics,
        diagnostic_buckets={},
    )

    lead = summary["leads"][0]
    assert lead["source_actionable"] is False
    assert lead["terminal_blocker"] == "ambiguous-movable-local-write"
    assert lead["source_probe_diagnostic"]["movable_write_count"] == 2
    assert summary["leads"][1]["terminal_blocker"] == "no-legal-destination"
    inspect_action = next(
        action for action in summary["ranked_actions"]
        if action["kind"] == "inspect-window-order-source-mobility"
    )
    assert inspect_action["terminal_blocker"] == "ambiguous-movable-local-write"
    assert inspect_action["source_probe_diagnostic"]["source_local"] == "dst_iter"


def test_select_order_source_bridge_marks_materialized_lead_actionable() -> None:
    fallback = {
        "ran": True,
        "leads": [{
            "target_ig": 34,
            "order_move": ["before", 43],
            "move_distance": 10,
        }],
    }
    attrs = {34: {"kind": "local", "name": "dst_iter"}}
    diagnostics = {
        "fallback_leads": 1,
        "source_attributed_leads": 1,
        "listed_source_probes": 1,
        "lead_diagnostics": [{
            "lead": fallback["leads"][0],
            "target_ig": 34,
            "direction": "before",
            "status": "materialized",
            "materialized_probe_labels": ["window-order-source-ig34-before-43-dst_iter"],
            "source_attribution": attrs[34],
            "source_local": "dst_iter",
            "source_diff": "--- source\n+++ window-order-source-probe\n",
        }],
    }

    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[],
        force_phys={34: 27},
        window_order_fallback=fallback,
        window_order_source_attributions=attrs,
        window_order_probe_diagnostics=diagnostics,
        diagnostic_buckets={},
    )

    lead = summary["leads"][0]
    assert lead["source_actionable"] is True
    assert lead["materialized_probe_labels"] == [
        "window-order-source-ig34-before-43-dst_iter"
    ]
    try_action = next(
        action for action in summary["ranked_actions"]
        if action["kind"] == "try-window-order-source-move"
    )
    assert try_action["probe_labels"] == [
        "window-order-source-ig34-before-43-dst_iter"
    ]


def test_select_order_source_bridge_demotes_already_satisfied_support_orders(
) -> None:
    variants = [{
        "label": "support-before-product",
        "status": "ok",
        "operator": "window-order-source-steering",
        "objective": {
            "force_phys_targets": {"32": 28, "37": 26},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 0,
            "force_phys_mismatches": {
                "32": {"expected": 28, "actual": 26},
                "37": {"expected": 26, "actual": 28},
            },
            "force_phys_missing": [],
            "force_phys_distance": 4,
            "target_order_improved": False,
            "target_orders": [
                {
                    "first_virtual": 34,
                    "second_virtual": 32,
                    "baseline_satisfied": True,
                    "candidate_satisfied": True,
                    "improved": False,
                },
                {
                    "first_virtual": 46,
                    "second_virtual": 32,
                    "baseline_satisfied": True,
                    "candidate_satisfied": True,
                    "improved": False,
                },
            ],
        },
        "structural_guard": {"accepted": True},
    }]

    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=variants,
        force_phys={32: 28, 37: 26},
        window_order_fallback={"ran": True, "leads": []},
        window_order_source_attributions={},
        window_order_probe_diagnostics={
            "fallback_leads": 0,
            "source_attributed_leads": 0,
            "listed_source_probes": 0,
        },
        diagnostic_buckets={},
    )

    assert summary["status"] == "blocked"
    assert summary["dominant_blocker"] == "support-order-targets-already-satisfied"
    assert "support-order-targets-already-satisfied" in summary["blocker_classes"]
    assert summary["target_order_actionability"] == {
        "already_satisfied_target_orders": [[34, 32], [46, 32]],
        "non_satisfied_target_orders": [],
        "all_baseline_satisfied": True,
        "any_target_order_improved": False,
        "force_phys_hits": [],
        "suggested_target_orders": [[32, 37], [32, 34], [32, 46]],
    }
    action = summary["ranked_actions"][0]
    assert action["kind"] == "derive-non-satisfied-sticky-pool-targets"
    assert action["avoid_target_orders"] == [[34, 32], [46, 32]]
    assert action["suggested_target_orders"] == [[32, 37], [32, 34], [32, 46]]


def test_select_order_source_bridge_does_not_apply_orderless_diag_to_ordered_leads() -> None:
    fallback = {
        "ran": True,
        "leads": [
            {"target_ig": 34, "order_move": ["before", 43]},
            {"target_ig": 34, "order_move": ["after", 75]},
        ],
    }
    attrs = {34: {"kind": "local", "name": "dst_iter"}}
    diagnostics = {
        "fallback_leads": 2,
        "source_attributed_leads": 1,
        "listed_source_probes": 1,
        "lead_diagnostics": [{
            "target_ig": 34,
            "status": "materialized",
            "materialized_probe_labels": ["orderless-probe"],
            "source_attribution": attrs[34],
            "source_local": "dst_iter",
        }],
    }

    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[],
        force_phys={34: 27},
        window_order_fallback=fallback,
        window_order_source_attributions=attrs,
        window_order_probe_diagnostics=diagnostics,
        diagnostic_buckets={},
    )

    assert [lead["source_actionable"] for lead in summary["leads"]] == [False, False]
    assert "try-window-order-source-move" not in [
        action["kind"] for action in summary["ranked_actions"]
    ]


def test_select_order_source_bridge_does_not_resolve_guard_rejected_exact_hit() -> None:
    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[{
            "label": "exact-drift",
            "status": "ok",
            "operator": "transform-corpus:coloring_register_steering",
            "objective": {
                "force_phys_targets": {"32": 29},
                "force_phys_satisfied": True,
                "force_phys_satisfied_count": 1,
                "force_phys_mismatches": {},
                "force_phys_missing": [],
                "force_phys_distance": 0,
                "frame_delta": 0,
            },
            "structural_guard": {
                "accepted": False,
                "rejection_reason": "inline-boundary-toolchain-artifact",
            },
        }],
        force_phys={32: 29},
        window_order_fallback={"ran": True, "leads": []},
        window_order_source_attributions={},
        window_order_probe_diagnostics={
            "fallback_leads": 0,
            "source_attributed_leads": 0,
            "listed_source_probes": 0,
        },
        diagnostic_buckets={},
    )

    assert summary["status"] == "blocked"
    assert summary["dominant_blocker"] == "guard-rejected-structural-drift"


def test_select_order_source_bridge_prefers_concrete_no_lead_blocker() -> None:
    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[{
            "label": "stack-layout",
            "status": "ok",
            "operator": "lifetime-layout",
            "objective": {
                "force_phys_targets": {"34": 27},
                "force_phys_satisfied": False,
                "force_phys_satisfied_count": 0,
                "force_phys_mismatches": {
                    "34": {"expected": 27, "actual": 24}
                },
                "force_phys_missing": [],
                "force_phys_distance": 3,
                "frame_delta": 8,
            },
            "structural_guard": {
                "accepted": False,
                "rejection_reason": "stack-layout frame_delta=8",
            },
        }],
        force_phys={34: 27},
        window_order_fallback={"ran": True, "leads": []},
        window_order_source_attributions={},
        window_order_probe_diagnostics={
            "fallback_leads": 0,
            "source_attributed_leads": 0,
            "listed_source_probes": 0,
        },
        diagnostic_buckets={},
    )

    assert summary["status"] == "blocked"
    assert summary["dominant_blocker"] == "stack-layout"
    assert "terminal-allocator-ceiling" not in [
        action.get("blocker") for action in summary["ranked_actions"]
    ]


def test_select_order_source_bridge_reports_terminal_recombine_lane() -> None:
    source_a = "/tmp/indexed-byte.c"
    source_b = "/tmp/stack-repair.c"
    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[
            {
                "label": "indexed-byte",
                "rank": 1,
                "status": "ok",
                "operator": "transform-corpus:indexed_byte_address_temp_steering",
                "path": source_a,
                "source_retained": source_a,
                "objective": {
                    "force_phys_targets": {"34": 27, "44": 25},
                    "force_phys_satisfied": False,
                    "force_phys_satisfied_count": 0,
                    "force_phys_mismatches": {
                        "34": {"expected": 27, "actual": 24},
                        "44": {"expected": 25, "actual": 27},
                    },
                    "force_phys_missing": [],
                    "force_phys_distance": 5,
                    "frame_delta": 8,
                    "match_percent": 99.30556,
                },
                "structural_guard": {"accepted": True},
            },
            {
                "label": "pad-stack",
                "rank": 2,
                "status": "ok",
                "operator": "lifetime-layout",
                "path": source_b,
                "source_retained": source_b,
                "objective": {
                    "force_phys_targets": {"34": 27, "44": 25},
                    "force_phys_satisfied": False,
                    "force_phys_satisfied_count": 0,
                    "force_phys_mismatches": {
                        "34": {"expected": 27, "actual": 24},
                        "44": {"expected": 25, "actual": 27},
                    },
                    "force_phys_missing": [],
                    "force_phys_distance": 5,
                    "frame_delta": 4,
                    "match_percent": 99.33,
                },
                "structural_guard": {
                    "accepted": False,
                    "rejection_reason": "stack-layout frame_delta=4",
                },
            },
        ],
        force_phys={34: 27, 44: 25},
        window_order_fallback={
            "ran": True,
            "leads": [{"target_ig": 34, "order_move": ["before", 43]}],
        },
        window_order_source_attributions={
            34: {"kind": "local", "name": "dst_iter"},
        },
        window_order_probe_diagnostics={
            "fallback_leads": 1,
            "source_attributed_leads": 1,
            "listed_source_probes": 0,
            "lead_diagnostics": [{
                "target_ig": 34,
                "order_move": ["before", 43],
                "status": "blocked",
                "terminal_blocker": "no-legal-destination",
                "source_local": "dst_iter",
            }],
        },
        diagnostic_buckets={},
        base_source_path="/tmp/real-tu.c",
    )

    lane = summary["terminal_next_lane"]
    assert lane["status"] == "available"
    assert lane["reason"] == "terminal-bridge-structural-near-candidates"
    assert [item["label"] for item in lane["candidates"]] == [
        "indexed-byte",
        "pad-stack",
    ]
    assert lane["candidates"][0]["source_retained"] == source_a
    assert lane["candidates"][0]["registers"]["mismatched"]["34"] == {
        "expected": 27,
        "actual": 24,
    }
    action_kinds = [action["kind"] for action in lane["actions"]]
    assert "try-retained-variant-recombine" in action_kinds
    assert "try-natural-stack-frame-repair" in action_kinds
    combine = next(
        action for action in lane["actions"]
        if action["kind"] == "try-retained-variant-recombine"
    )
    assert "--base /tmp/real-tu.c" in combine["command_hint"]
    assert "frame_repair_lane" in lane


def test_select_order_source_bridge_terminal_lane_ranks_local_and_synthetic_source_probes(
) -> None:
    fallback = {
        "ran": True,
        "leads": [
            {"target_ig": 34, "order_move": ["before", 43]},
            {"target_ig": 44, "order_move": ["after", 34]},
        ],
    }
    attrs = {
        34: {"kind": "local", "name": "i", "type": "int", "source_line": 911},
        44: {"kind": "implicit-temp", "expression": "addi r44,r50,28"},
    }
    owner_candidate = {
        "kind": "loop-index-declaration",
        "local": "i",
        "line_start": 911,
        "line_end": 911,
        "span_text": "int i;",
        "action_families": ["local-declaration-lifetime", "loop-index-owner"],
    }
    indexed_candidate = {
        "kind": "indexed-byte-address-temp",
        "array_base": "dst",
        "index_expr": "i",
        "target_local": "ll_probe_iter_0",
        "span_text": "*ll_probe_iter_0 = temp;",
        "mutator_keys": [
            "steer_indexed_byte_direct_global_dst",
            "steer_indexed_byte_implicit_init_loop_indexed_store",
        ],
    }
    diagnostics = {
        "fallback_leads": 2,
        "source_attributed_leads": 2,
        "listed_source_probes": 0,
        "lead_diagnostics": [
            {
                "lead": fallback["leads"][0],
                "target_ig": 34,
                "direction": "before",
                "status": "blocked",
                "terminal_blocker": "local-source-owner-no-unique-assignment",
                "source_attribution": attrs[34],
                "source_local": "i",
                "ranked_source_owner_candidates": [owner_candidate],
            },
            {
                "lead": fallback["leads"][1],
                "target_ig": 44,
                "direction": "after",
                "status": "blocked",
                "terminal_blocker": "synthetic-temp-operands-unattributed",
                "source_attribution": attrs[44],
                "synthetic_source_probe": {
                    "expression": "addi r44,r50,28",
                    "copy_chain": [
                        {"virtual": 44, "kind": "implicit-temp"},
                        {
                            "virtual": 50,
                            "kind": "copy/coalesce-product",
                            "base_virtual": 52,
                        },
                    ],
                    "ranked_indexed_byte_source_candidates": [
                        indexed_candidate
                    ],
                },
            },
        ],
    }
    variants = [
        {
            "label": "d1-0002",
            "rank": 1,
            "status": "ok",
            "operator": "transform-corpus:indexed_byte_address_temp_steering",
            "path": "/tmp/d1-0002.c",
            "source_retained": "/tmp/d1-0002.c",
            "pcdump_path": "/tmp/d1-0002.pcdump.txt",
            "probe": {
                "provenance": {
                    "mutator_key": "steer_indexed_byte_implicit_init_loop_indexed_store",
                    "payload": indexed_candidate,
                },
            },
            "objective": {
                "force_phys_targets": {"34": 27, "44": 25},
                "force_phys_satisfied": False,
                "force_phys_satisfied_count": 0,
                "force_phys_mismatches": {
                    "34": {"expected": 27, "actual": 26},
                    "44": {"expected": 25, "actual": 27},
                },
                "force_phys_missing": [],
                "force_phys_distance": 3,
                "frame_delta": 8,
                "match_percent": 99.4,
            },
            "structural_guard": {
                "accepted": False,
                "rejection_reason": "stack-layout frame_delta=8",
            },
        },
        {
            "label": "d1-0004",
            "rank": 2,
            "status": "ok",
            "operator": "transform-corpus:indexed_byte_address_temp_steering",
            "path": "/tmp/d1-0004.c",
            "source_retained": "/tmp/d1-0004.c",
            "pcdump_path": "/tmp/d1-0004.pcdump.txt",
            "probe": {
                "provenance": {
                    "mutator_key": "steer_indexed_byte_direct_global_dst",
                    "payload": indexed_candidate,
                },
            },
            "objective": {
                "force_phys_targets": {"34": 27, "44": 25},
                "force_phys_satisfied": False,
                "force_phys_satisfied_count": 0,
                "force_phys_mismatches": {
                    "34": {"expected": 27, "actual": 26},
                    "44": {"expected": 25, "actual": 28},
                },
                "force_phys_missing": [],
                "force_phys_distance": 4,
                "frame_delta": 0,
                "match_percent": 99.3,
            },
            "structural_guard": {"accepted": True},
        },
    ]

    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=variants,
        force_phys={34: 27, 44: 25},
        window_order_fallback=fallback,
        window_order_source_attributions=attrs,
        window_order_probe_diagnostics=diagnostics,
        diagnostic_buckets={},
        function="mnDiagram_SortNamesByKOs",
    )

    lane = summary["terminal_next_lane"]["source_bridge_lane"]
    assert lane["status"] == "available"
    assert lane["reason"] == "terminal-blockers-source-actionable"
    probes = lane["ranked_probes"]
    assert [probe["label"] for probe in probes[:2]] == ["d1-0004", "d1-0002"]
    top = probes[0]
    assert top["source_retained"] == "/tmp/d1-0004.c"
    assert top["pcdump_path"] == "/tmp/d1-0004.pcdump.txt"
    assert top["target_score"]["virtuals"]["34"] == {
        "expected": 27,
        "actual": 26,
        "hit": False,
        "matched": False,
    }
    assert top["registers"] == {"34": 26, "44": 28}
    assert top["source_owner"]["span_text"] == "*ll_probe_iter_0 = temp;"
    assert top["source_provenance"]["mutator_key"] == (
        "steer_indexed_byte_direct_global_dst"
    )
    assert top["linked_terminal_blockers"] == [
        "local-source-owner-no-unique-assignment",
        "synthetic-temp-operands-unattributed",
    ]
    assert lane["actions"][0]["kind"] == "score-ranked-retained-source"


def test_select_order_refresh_counts_only_successful_retained_window_source_probes(
) -> None:
    diagnostics = {
        "listed_source_probes": 1,
        "lead_diagnostics": [{
            "materialized_probe_labels": ["ranked-owner-probe"],
        }],
    }
    failed = debug_cli._select_order_refresh_window_order_probe_diagnostics(
        diagnostics,
        [{
            "label": "ranked-owner-probe",
            "status": "compile-failed",
            "source_retained": "/tmp/ranked-owner-probe.c",
            "pcdump_path": "/tmp/ranked-owner-probe.pcdump.txt",
            "probe": {
                "operator": "window-order-source-steering",
                "label": "ranked-owner-probe",
            },
            "objective": {
                "force_phys_targets": {"34": 27},
                "force_phys_assignments": {
                    "34": {"actual": 27, "status": "hit"},
                },
            },
        }],
    )

    assert failed["attempted_window_order_source_probes"] == 1
    assert failed["scored_window_order_source_probes"] == 0
    assert failed["scored_window_order_source_probe_labels"] == []
    assert "scored_probe_labels" not in failed["lead_diagnostics"][0]

    scored = debug_cli._select_order_refresh_window_order_probe_diagnostics(
        diagnostics,
        [{
            "label": "ranked-owner-probe",
            "status": "ok",
            "source_retained": "/tmp/ranked-owner-probe.c",
            "pcdump_path": "/tmp/ranked-owner-probe.pcdump.txt",
            "probe": {
                "operator": "window-order-source-steering",
                "label": "ranked-owner-probe",
            },
            "objective": {
                "force_phys_targets": {"34": 27},
                "force_phys_assignments": {
                    "34": {"actual": 27, "status": "hit"},
                },
            },
        }],
    )

    assert scored["attempted_window_order_source_probes"] == 1
    assert scored["scored_window_order_source_probes"] == 1
    assert scored["scored_window_order_source_probe_labels"] == [
        "ranked-owner-probe"
    ]
    assert scored["lead_diagnostics"][0]["scored_probe_labels"] == [
        "ranked-owner-probe"
    ]


def test_select_order_source_bridge_explains_unmaterializable_ranked_owner_candidates(
) -> None:
    fallback = {
        "ran": True,
        "leads": [{"target_ig": 34, "order_move": ["before", 43]}],
    }
    attrs = {34: {"kind": "local", "name": "i", "type": "int"}}
    diagnostics = {
        "fallback_leads": 1,
        "source_attributed_leads": 1,
        "listed_source_probes": 0,
        "lead_diagnostics": [{
            "lead": fallback["leads"][0],
            "target_ig": 34,
            "direction": "before",
            "status": "blocked",
            "terminal_blocker": "ranked-owner-candidates-not-materializable",
            "source_attribution": attrs[34],
            "source_local": "i",
            "ranked_source_owner_candidates": [
                {
                    "kind": "loop-index-declaration",
                    "span_text": "int i;",
                },
                {
                    "kind": "loop-index-header",
                    "span_text": "for (i = 0; i < 10; i++) {",
                },
            ],
            "ranked_source_owner_materialization_summary": {
                "ranked_local_candidates": 2,
                "materialized_local_candidates": 0,
                "reasons": {
                    "non-executable-declaration-span": 1,
                    "unsupported-loop-header-owner": 1,
                },
            },
        }],
    }

    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[],
        force_phys={34: 27},
        window_order_fallback=fallback,
        window_order_source_attributions=attrs,
        window_order_probe_diagnostics=diagnostics,
        diagnostic_buckets={},
    )

    assert summary["status"] == "blocked"
    assert summary["dominant_blocker"] == (
        "ranked-owner-candidates-not-materializable"
    )
    owner_summary = summary["terminal_owner_probe_summary"]
    assert owner_summary["status"] == "blocked"
    assert owner_summary["ranked_local_candidates"] == 2
    assert owner_summary["materialized_local_candidates"] == 0
    assert owner_summary["terminal_blocker"] == (
        "ranked-owner-candidates-not-materializable"
    )
    assert owner_summary["reasons"] == {
        "non-executable-declaration-span": 1,
        "unsupported-loop-header-owner": 1,
    }
    assert not any(
        action["kind"] == "try-window-order-source-move"
        for action in summary["ranked_actions"]
    )


def test_select_order_source_bridge_reports_materialized_field_load_action(
) -> None:
    fallback = {
        "ran": True,
        "leads": [{"target_ig": 32, "order_move": ["before", 72]}],
    }
    attrs = {
        32: {
            "kind": "field-load",
            "expression": "gobj->field_at_0x2C",
            "base_var": "gobj",
            "field_offset": 44,
        }
    }
    field_candidate = {
        "kind": "inline-temp",
        "base_var": "gobj",
        "field_offset": 44,
        "field_name": "user_data",
        "expression": "gobj->user_data",
    }
    source_hunks = [{
        "hunk_id": "field-load001",
        "base_range": {"start": 8, "end": 8},
        "candidate_range": {"start": 9, "end": 10},
    }]
    diagnostics = {
        "fallback_leads": 1,
        "source_attributed_leads": 1,
        "listed_source_probes": 1,
        "lead_diagnostics": [{
            "lead": fallback["leads"][0],
            "target_ig": 32,
            "direction": "before",
            "status": "materialized",
            "materialized_probe_labels": [
                "window-order-field-load-ig32-before-inline-temp-0"
            ],
            "source_attribution": attrs[32],
            "source_diff": "@@ field-load diff @@\n",
            "source_hunks": source_hunks,
            "field_load_source_candidate": field_candidate,
            "materialized_field_load_source_candidates": [field_candidate],
            "field_load_materialization_summary": {
                "field_load_source_candidates": 1,
                "materialized_field_load_source_candidates": 1,
                "reasons": {},
            },
        }],
    }

    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[],
        force_phys={32: 30},
        window_order_fallback=fallback,
        window_order_source_attributions=attrs,
        window_order_probe_diagnostics=diagnostics,
        diagnostic_buckets={},
    )

    action = next(
        action for action in summary["ranked_actions"]
        if action["kind"] == "try-window-order-source-move"
    )
    assert action["probe_labels"] == [
        "window-order-field-load-ig32-before-inline-temp-0"
    ]
    assert action["field_load_source_candidate"] == field_candidate
    assert action["materialized_field_load_source_candidates"] == [field_candidate]
    assert action["source_hunks"] == source_hunks
    owner_summary = summary["terminal_owner_probe_summary"]
    assert owner_summary["field_load_source_candidates"] == 1
    assert owner_summary["materialized_field_load_source_candidates"] == 1


def test_select_order_source_bridge_reports_field_load_terminal_blocker(
) -> None:
    fallback = {
        "ran": True,
        "leads": [{"target_ig": 32, "order_move": ["before", 72]}],
    }
    attrs = {
        32: {
            "kind": "field-load",
            "expression": "gobj->field_at_0x2C",
            "base_var": "gobj",
            "field_offset": 44,
        }
    }
    diagnostics = {
        "fallback_leads": 1,
        "source_attributed_leads": 1,
        "listed_source_probes": 0,
        "lead_diagnostics": [{
            "lead": fallback["leads"][0],
            "target_ig": 32,
            "direction": "before",
            "status": "blocked",
            "terminal_blocker": "field-load-base-type-unresolved",
            "source_attribution": attrs[32],
            "field_load_source_candidates": [{
                "kind": "inline-temp",
                "base_var": "gobj",
                "field_offset": 44,
                "field_name": None,
                "expression": "gobj->field_at_0x2C",
            }],
            "field_load_materialization_summary": {
                "field_load_source_candidates": 1,
                "materialized_field_load_source_candidates": 0,
                "reasons": {"field-load-base-type-unresolved": 1},
            },
        }],
    }

    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[],
        force_phys={32: 30},
        window_order_fallback=fallback,
        window_order_source_attributions=attrs,
        window_order_probe_diagnostics=diagnostics,
        diagnostic_buckets={},
    )

    assert summary["status"] == "blocked"
    assert summary["dominant_blocker"] == "field-load-base-type-unresolved"
    owner_summary = summary["terminal_owner_probe_summary"]
    assert owner_summary["field_load_source_candidates"] == 1
    assert owner_summary["materialized_field_load_source_candidates"] == 0
    assert owner_summary["terminal_blocker"] == "field-load-base-type-unresolved"
    assert owner_summary["field_load_terminal_blockers"] == [
        "field-load-base-type-unresolved"
    ]
    assert summary["leads"][0]["terminal_blocker"] == (
        "field-load-base-type-unresolved"
    )


def test_select_order_source_bridge_reports_materialized_param_alias_action(
) -> None:
    fallback = {
        "ran": True,
        "leads": [{"target_ig": 34, "order_move": ["before", 74]}],
    }
    attrs = {34: {"kind": "param", "name": "arg2", "type": "s32"}}
    param_candidate = {
        "kind": "adjacent-param-alias-decl-swap",
        "materialization_kind": "declaration-order",
        "param_name": "arg2",
        "alias_name": "arg2_r",
        "peer_param_name": "arg1",
        "peer_alias_name": "arg1_r",
    }
    source_hunks = [{
        "hunk_id": "param-alias001",
        "base_range": {"start": 2408, "end": 2409},
        "candidate_range": {"start": 2408, "end": 2409},
    }]
    diagnostics = {
        "fallback_leads": 1,
        "source_attributed_leads": 1,
        "listed_source_probes": 1,
        "lead_diagnostics": [{
            "lead": fallback["leads"][0],
            "target_ig": 34,
            "direction": "before",
            "status": "materialized",
            "materialized_probe_labels": [
                "window-order-param-alias-ig34-before-decl-swap-0"
            ],
            "source_attribution": attrs[34],
            "source_diff": "@@ param-alias diff @@\n",
            "source_hunks": source_hunks,
            "param_alias_source_candidate": param_candidate,
            "materialized_param_alias_source_candidates": [param_candidate],
            "param_alias_materialization_summary": {
                "param_name": "arg2",
                "param_alias_source_candidates": 1,
                "materialized_param_alias_source_candidates": 1,
                "param_alias_candidates": 1,
                "materialized_param_alias_candidates": 1,
                "reasons": {},
            },
        }],
    }

    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[],
        force_phys={34: 29},
        window_order_fallback=fallback,
        window_order_source_attributions=attrs,
        window_order_probe_diagnostics=diagnostics,
        diagnostic_buckets={},
    )

    action = next(
        action for action in summary["ranked_actions"]
        if action["kind"] == "try-window-order-source-move"
    )
    assert action["probe_labels"] == [
        "window-order-param-alias-ig34-before-decl-swap-0"
    ]
    assert action["param_alias_source_candidate"] == param_candidate
    assert action["materialized_param_alias_source_candidates"] == [
        param_candidate
    ]
    assert action["source_hunks"] == source_hunks
    owner_summary = summary["terminal_owner_probe_summary"]
    assert owner_summary["param_alias_source_candidates"] == 1
    assert owner_summary["materialized_param_alias_source_candidates"] == 1
    assert owner_summary["materialized_candidates"] == 1


def test_select_order_source_bridge_reports_param_alias_terminal_blocker(
) -> None:
    fallback = {
        "ran": True,
        "leads": [{"target_ig": 34, "order_move": ["before", 74]}],
    }
    attrs = {34: {"kind": "param", "name": "arg2", "type": "s32"}}
    diagnostics = {
        "fallback_leads": 1,
        "source_attributed_leads": 1,
        "listed_source_probes": 0,
        "lead_diagnostics": [{
            "lead": fallback["leads"][0],
            "target_ig": 34,
            "direction": "before",
            "status": "blocked",
            "terminal_blocker": "param-alias-no-legal-source-movement",
            "source_attribution": attrs[34],
            "param_name": "arg2",
            "param_alias_source_candidates": [{
                "kind": "delayed-param-alias-init",
                "param_name": "arg2",
                "alias_name": "arg2_r",
            }],
            "param_alias_materialization_summary": {
                "param_name": "arg2",
                "param_alias_source_candidates": 1,
                "materialized_param_alias_source_candidates": 0,
                "param_alias_candidates": 1,
                "materialized_param_alias_candidates": 0,
                "reasons": {"param-alias-use-before-delayed-init": 1},
            },
        }],
    }

    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[],
        force_phys={34: 29},
        window_order_fallback=fallback,
        window_order_source_attributions=attrs,
        window_order_probe_diagnostics=diagnostics,
        diagnostic_buckets={},
    )

    assert summary["status"] == "blocked"
    assert summary["dominant_blocker"] == "param-alias-no-legal-source-movement"
    owner_summary = summary["terminal_owner_probe_summary"]
    assert owner_summary["param_alias_source_candidates"] == 1
    assert owner_summary["materialized_param_alias_source_candidates"] == 0
    assert owner_summary["terminal_blocker"] == (
        "param-alias-no-legal-source-movement"
    )
    assert owner_summary["param_alias_terminal_blockers"] == [
        "param-alias-no-legal-source-movement"
    ]
    assert not any(
        action["kind"] == "try-window-order-source-move"
        for action in summary["ranked_actions"]
    )


def test_select_order_source_bridge_does_not_double_count_indexed_terminal_reasons(
) -> None:
    fallback = {
        "ran": True,
        "leads": [{"target_ig": 44, "order_move": ["after", 34]}],
    }
    attrs = {44: {"kind": "implicit-temp", "expression": "addi r44,r50,28"}}
    indexed_summary = {
        "ranked_indexed_byte_candidates": 1,
        "materialized_indexed_byte_candidates": 0,
        "reasons": {"unsafe-index-expression": 1},
    }
    diagnostics = {
        "fallback_leads": 1,
        "source_attributed_leads": 1,
        "listed_source_probes": 0,
        "lead_diagnostics": [{
            "lead": fallback["leads"][0],
            "target_ig": 44,
            "direction": "after",
            "status": "blocked",
            "terminal_blocker": "ranked-owner-candidates-not-materializable",
            "source_attribution": attrs[44],
            "synthetic_source_probe": {
                "ranked_indexed_byte_source_candidates": [{
                    "kind": "indexed-byte-address-temp",
                    "span_text": "dst[i + f()]",
                }],
                "ranked_indexed_byte_materialization_summary": indexed_summary,
            },
            "ranked_indexed_byte_materialization_summary": indexed_summary,
        }],
    }

    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[],
        force_phys={44: 25},
        window_order_fallback=fallback,
        window_order_source_attributions=attrs,
        window_order_probe_diagnostics=diagnostics,
        diagnostic_buckets={},
    )

    owner_summary = summary["terminal_owner_probe_summary"]
    assert owner_summary["ranked_indexed_byte_candidates"] == 1
    assert owner_summary["materialized_indexed_byte_candidates"] == 0
    assert owner_summary["reasons"] == {"unsafe-index-expression": 1}


def test_select_order_source_bridge_keeps_pcdump_path_for_retained_variants(
) -> None:
    public = debug_cli._select_order_public_variants([
        {
            "label": "d1-0004",
            "status": "ok",
            "source_retained": "/tmp/d1-0004.c",
            "pcdump_path": "/tmp/d1-0004.pcdump.txt",
            "_pcdump_key": 7,
        }
    ])

    assert public == [
        {
            "label": "d1-0004",
            "status": "ok",
            "source_retained": "/tmp/d1-0004.c",
            "pcdump_path": "/tmp/d1-0004.pcdump.txt",
        }
    ]


def test_select_order_source_bridge_support_order_satisfied_still_reports_source_lane(
) -> None:
    fallback = {
        "ran": True,
        "leads": [{"target_ig": 34, "order_move": ["before", 42]}],
    }
    attrs = {34: {"kind": "local", "name": "i", "type": "int"}}
    diagnostics = {
        "fallback_leads": 1,
        "source_attributed_leads": 1,
        "listed_source_probes": 0,
        "lead_diagnostics": [{
            "lead": fallback["leads"][0],
            "target_ig": 34,
            "direction": "before",
            "status": "blocked",
            "terminal_blocker": "local-source-owner-no-unique-assignment",
            "source_attribution": attrs[34],
            "source_local": "i",
            "ranked_source_owner_candidates": [{
                "kind": "loop-index-declaration",
                "local": "i",
                "line_start": 911,
                "line_end": 911,
                "span_text": "int i;",
            }],
        }],
    }
    variants = [{
        "label": "support-before-product",
        "rank": 1,
        "status": "ok",
        "operator": "transform-corpus:indexed_byte_address_temp_steering",
        "path": "/tmp/support.c",
        "source_retained": "/tmp/support.c",
        "pcdump_path": "/tmp/support.pcdump.txt",
        "objective": {
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 0,
            "force_phys_mismatches": {
                "34": {"expected": 27, "actual": 26},
                "44": {"expected": 25, "actual": 28},
            },
            "force_phys_missing": [],
            "force_phys_distance": 4,
            "target_orders": [{
                "first_virtual": 42,
                "second_virtual": 34,
                "baseline_satisfied": True,
                "candidate_satisfied": True,
                "improved": False,
            }],
            "frame_delta": 0,
            "match_percent": 99.3,
        },
        "structural_guard": {"accepted": True},
    }]

    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=variants,
        force_phys={34: 27, 44: 25},
        window_order_fallback=fallback,
        window_order_source_attributions=attrs,
        window_order_probe_diagnostics=diagnostics,
        diagnostic_buckets={},
    )

    assert summary["dominant_blocker"] == "support-order-targets-already-satisfied"
    assert summary["target_order_actionability"]["suggested_target_orders"]
    lane = summary["terminal_next_lane"]["source_bridge_lane"]
    assert lane["status"] == "available"
    assert lane["ranked_probes"][0]["source_retained"] == "/tmp/support.c"


def test_select_order_terminal_exhaustion_reports_case_c_no_hit() -> None:
    target_score = {
        "matched": 4,
        "targeted": 6,
        "virtuals": {
            "33": {"expected": 26, "actual": 26, "matched": True},
            "46": {"expected": 26, "actual": 1, "matched": False},
        },
    }
    ranked_variants = [
        {
            "label": "protected",
            "rank": 1,
            "status": "ok",
            "operator": "window-order-source-steering",
            "path": "/tmp/protected.c",
            "source_retained": "/tmp/protected.c",
            "objective": {
                "target_score": target_score,
                "force_phys_targets": {"33": 26, "46": 26},
                "force_phys_satisfied": False,
                "force_phys_satisfied_count": 1,
                "force_phys_mismatches": {
                    "46": {"expected": 26, "actual": 1},
                },
                "force_phys_missing": [],
                "force_phys_distance": 25,
                "frame_delta": 0,
            },
        },
        {
            "label": "blocker",
            "rank": 2,
            "status": "ok",
            "operator": "transform-corpus:indexed_byte_address_temp_steering",
            "path": "/tmp/blocker.c",
            "source_retained": "/tmp/blocker.c",
            "objective": {
                "validator_payload": {"target_score": target_score},
                "force_phys_targets": {"33": 26, "46": 26},
                "force_phys_satisfied": False,
                "force_phys_satisfied_count": 0,
                "force_phys_mismatches": {
                    "33": {"expected": 26, "actual": 1},
                    "46": {"expected": 26, "actual": 1},
                },
                "force_phys_missing": [],
                "force_phys_distance": 50,
                "frame_delta": 0,
            },
        },
    ]
    source_bridge_summary = {
        "status": "blocked",
        "dominant_blocker": "source-probes-exhausted",
        "blocker_classes": ["wrong-register"],
        "terminal_next_lane": {
            "status": "available",
            "actions": [{"kind": "try-retained-variant-recombine"}],
        },
    }

    summary = debug_cli._select_order_terminal_exhaustion_summary(
        ranked_variants=ranked_variants,
        force_phys={33: 26, 46: 26},
        blocker_targets={46},
        diagnostic_buckets={
            "force-phys-hit-33": [{"label": "protected"}],
            "force-phys-hit-46": [],
            "global-top": [{"label": "protected"}],
        },
        source_bridge_summary=source_bridge_summary,
        timed_out=False,
        class_id=1,
    )

    assert summary["status"] == "blocked"
    assert summary["kind"] == "degree-zero-fpr-case-c-source-exhaustion"
    assert summary["dominant_blocker"] == "source-probes-exhausted"
    assert summary["force_phys_targets"]["46"] == 26
    assert summary["blocker_targets"] == [46]
    assert summary["recombine_status"] == "unverified"
    assert "manual-subhunk-recombine" in summary["next_source_lever_classes"]
    assert summary["best_retained_variants"][0]["target_score"]["virtuals"]["46"][
        "actual"
    ] == 1


def test_select_order_terminal_exhaustion_reports_param_alias_family() -> None:
    source_hunks = [{
        "hunk_id": "param-alias001",
        "base_range": {"start": 2412, "end": 2413},
        "candidate_range": {"start": 2412, "end": 2413},
    }]
    param_candidate = {
        "probe_label": "window-order-param-alias-ig34-before-0",
        "materialization_kind": "declaration-order",
        "param_name": "arg2",
        "alias_name": "arg2_r",
    }
    ranked_variants = [{
        "label": "window-order-param-alias-ig34-before-0",
        "rank": 1,
        "status": "ok",
        "operator": "window-order-source-steering",
        "path": "/tmp/param-alias.c",
        "source_retained": "/tmp/param-alias.c",
        "pcdump_path": "/tmp/param-alias.pcdump.txt",
        "probe": {
            "provenance": {
                "kind": "window-order-param-alias-source-order",
                "source_hunks": source_hunks,
            },
        },
        "objective": {
            "force_phys_targets": {"34": 29},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 0,
            "force_phys_mismatches": {"34": {"expected": 29, "actual": 30}},
            "force_phys_missing": [],
            "force_phys_distance": 1,
            "frame_delta": 0,
        },
        "target_score": {
            "matched": 0,
            "total": 1,
            "targeted": 1,
            "virtuals": {
                "34": {
                    "expected": 29,
                    "actual": 30,
                    "hit": False,
                    "matched": False,
                },
            },
        },
    }]
    source_bridge_summary = {
        "status": "blocked",
        "dominant_blocker": "source-probes-exhausted",
        "blocker_classes": ["wrong-register"],
        "terminal_owner_probe_summary": {
            "param_alias_source_candidates": 1,
            "materialized_param_alias_source_candidates": 1,
        },
        "ranked_actions": [{
            "kind": "try-window-order-source-move",
            "probe_labels": ["window-order-param-alias-ig34-before-0"],
            "materialized_param_alias_source_candidates": [param_candidate],
        }],
    }

    summary = debug_cli._select_order_terminal_exhaustion_summary(
        ranked_variants=ranked_variants,
        force_phys={34: 29},
        blocker_targets={34},
        diagnostic_buckets={
            "force-phys-hit-34": [],
            "global-top": ranked_variants,
        },
        source_bridge_summary=source_bridge_summary,
        timed_out=False,
        class_id=0,
    )

    assert summary["terminal_blocker"] == "param-alias-source-family-exhausted"
    proof = summary["source_candidate_family_exhaustion"]
    assert proof["status"] == "exhausted"
    assert proof["family"] == "param-alias-source-bridge"
    assert proof["generated_candidates"] == 1
    assert proof["materialized_candidates"] == 1
    assert proof["scored_candidates"] == 1
    result = proof["source_probe_results"][0]
    assert result["source_retained"] == "/tmp/param-alias.c"
    assert result["pcdump_path"] == "/tmp/param-alias.pcdump.txt"
    assert result["source_hunks"] == source_hunks
    assert result["target_score"]["virtuals"]["34"] == {
        "expected": 29,
        "actual": 30,
        "hit": False,
        "matched": False,
    }
    assert "arg2/arg2_r" in proof["source_level_handoff"]


def test_select_order_source_bridge_reports_terminal_frame_repair_lane() -> None:
    source = "/tmp/stack-repair.c"
    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[
            {
                "label": "pad-stack",
                "rank": 2,
                "status": "ok",
                "operator": "lifetime-layout",
                "path": source,
                "source_retained": source,
                "objective": {
                    "force_phys_targets": {"34": 27},
                    "force_phys_satisfied": False,
                    "force_phys_satisfied_count": 0,
                    "force_phys_mismatches": {
                        "34": {"expected": 27, "actual": 24},
                    },
                    "force_phys_missing": [],
                    "force_phys_distance": 5,
                    "frame_delta": 4,
                    "match_percent": 99.33,
                },
                "structural_guard": {
                    "accepted": False,
                    "rejection_reason": "stack-layout frame_delta=4",
                },
            },
        ],
        force_phys={34: 27},
        window_order_fallback={
            "ran": True,
            "leads": [{"target_ig": 34, "order_move": ["before", 43]}],
        },
        window_order_source_attributions={
            34: {"kind": "local", "name": "dst_iter"},
        },
        window_order_probe_diagnostics={
            "fallback_leads": 1,
            "source_attributed_leads": 1,
            "listed_source_probes": 0,
            "lead_diagnostics": [{
                "target_ig": 34,
                "order_move": ["before", 43],
                "status": "blocked",
                "terminal_blocker": "no-legal-destination",
                "source_local": "dst_iter",
            }],
        },
        diagnostic_buckets={},
        function="fn_80000000",
        campaign_dir=pathlib.Path("/tmp/campaign"),
    )

    frame_lane = summary["terminal_next_lane"]["frame_repair_lane"]
    assert frame_lane["status"] == "blocked"
    assert frame_lane["terminal_blocker"] == "frame-transform-not-materialized"
    assert frame_lane["candidates"][0]["label"] == "pad-stack"
    assert frame_lane["candidates"][0]["candidate_frame_delta"] == 4
    assert frame_lane["candidates"][0]["remaining_frame_delta"] == 4
    assert frame_lane["candidates"][0]["frame_reservation_bytes_hint"] == 4
    action = frame_lane["actions"][0]
    assert action["kind"] == "run-frame-transform-search"
    assert "melee-agent debug mutate frame-transform-search" in action["command_hint"]
    assert "-f fn_80000000" in action["command_hint"]
    assert "--source-file /tmp/stack-repair.c" in action["command_hint"]
    assert "--frame-reservation-bytes 4" in action["command_hint"]
    assert "--output-dir /tmp/campaign/frame-repair/pad-stack" in (
        action["command_hint"]
    )
    assert "--json" in action["command_hint"]


def test_select_order_source_bridge_frame_lane_does_not_pad_negative_delta() -> None:
    source = "/tmp/stack-shrink.c"
    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[
            {
                "label": "stack-shrink",
                "rank": 1,
                "status": "ok",
                "operator": "lifetime-layout",
                "path": source,
                "source_retained": source,
                "objective": {
                    "force_phys_targets": {"34": 27},
                    "force_phys_satisfied": False,
                    "force_phys_satisfied_count": 0,
                    "force_phys_mismatches": {
                        "34": {"expected": 27, "actual": 24},
                    },
                    "force_phys_missing": [],
                    "force_phys_distance": 5,
                    "frame_delta": -4,
                    "match_percent": 99.33,
                },
                "structural_guard": {
                    "accepted": False,
                    "rejection_reason": "stack-layout frame_delta=-4",
                },
            },
        ],
        force_phys={34: 27},
        window_order_fallback={
            "ran": True,
            "leads": [{"target_ig": 34, "order_move": ["before", 43]}],
        },
        window_order_source_attributions={
            34: {"kind": "local", "name": "dst_iter"},
        },
        window_order_probe_diagnostics={
            "fallback_leads": 1,
            "source_attributed_leads": 1,
            "listed_source_probes": 0,
            "lead_diagnostics": [{
                "target_ig": 34,
                "order_move": ["before", 43],
                "status": "blocked",
                "terminal_blocker": "no-legal-destination",
                "source_local": "dst_iter",
            }],
        },
        diagnostic_buckets={},
        function="fn_80000000",
    )

    frame_lane = summary["terminal_next_lane"]["frame_repair_lane"]
    assert frame_lane["candidates"][0]["candidate_frame_delta"] == -4
    assert frame_lane["candidates"][0]["frame_reservation_bytes_hint"] is None
    assert "--frame-reservation-bytes" not in (
        frame_lane["actions"][0]["command_hint"]
    )


def test_select_order_source_bridge_single_terminal_candidate_has_action() -> None:
    source = "/tmp/indexed-byte.c"
    summary = debug_cli._select_order_source_bridge_summary(
        ranked_variants=[
            {
                "label": "indexed-byte",
                "rank": 1,
                "status": "ok",
                "operator": "transform-corpus:indexed_byte_address_temp_steering",
                "path": source,
                "source_retained": source,
                "objective": {
                    "force_phys_targets": {"34": 27},
                    "force_phys_satisfied": False,
                    "force_phys_satisfied_count": 0,
                    "force_phys_mismatches": {
                        "34": {"expected": 27, "actual": 24},
                    },
                    "force_phys_missing": [],
                    "force_phys_distance": 3,
                    "frame_delta": 0,
                    "match_percent": 99.3,
                },
                "structural_guard": {"accepted": True},
            },
        ],
        force_phys={34: 27},
        window_order_fallback={
            "ran": True,
            "leads": [{"target_ig": 34, "order_move": ["before", 43]}],
        },
        window_order_source_attributions={
            34: {"kind": "local", "name": "dst_iter"},
        },
        window_order_probe_diagnostics={
            "fallback_leads": 1,
            "source_attributed_leads": 1,
            "listed_source_probes": 0,
            "lead_diagnostics": [{
                "target_ig": 34,
                "order_move": ["before", 43],
                "status": "blocked",
                "terminal_blocker": "no-legal-destination",
                "source_local": "dst_iter",
            }],
        },
        diagnostic_buckets={},
        function="fn_80000000",
    )

    lane = summary["terminal_next_lane"]
    assert lane["status"] == "available"
    assert lane["actions"] == [{
        "kind": "inspect-single-retained-candidate",
        "command_hint": (
            "melee-agent debug search structure -f fn_80000000 "
            "--source-file /tmp/indexed-byte.c --json"
        ),
    }]


def test_select_order_ranking_prefers_near_force_phys_over_order_only() -> None:
    order_only_far = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER_FAR_WRONG_PHYS,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=99.0,
    )
    phys_nearer = score_select_order_candidate(
        BASELINE,
        WRONG_ORDER_NEAR_PHYS,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=12.0,
    )

    assert order_only_far.to_dict()["target_order_satisfied"] is True
    assert phys_nearer.to_dict()["target_order_satisfied"] is False
    assert order_only_far.to_dict()["force_phys_distance"] > (
        phys_nearer.to_dict()["force_phys_distance"]
    )

    ranked = rank_select_order_candidates([
        {
            "label": "order-only-far",
            "status": "ok",
            "objective": order_only_far.to_dict(),
        },
        {
            "label": "phys-nearer",
            "status": "ok",
            "objective": phys_nearer.to_dict(),
        },
    ])

    assert ranked[0]["label"] == "phys-nearer"


def test_select_order_ranking_prefers_force_phys_progress_over_spill_only() -> None:
    spill_only = score_select_order_candidate(
        BASELINE,
        BASELINE,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 27},
        delta=PressureDelta(
            frame_before=48,
            frame_after=48,
            frame_delta=0,
            saved_added=(),
            saved_removed=(),
            spill_added=(),
            spill_removed=(45,),
            interference_added=(),
            interference_removed=(),
            coalesce_added=(),
            coalesce_removed=(),
            target_pairs=(),
        ),
        match_percent=99.0,
    )
    target_progress = score_select_order_candidate(
        BASELINE,
        R32_ONE_STEP_CLOSER,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 27},
        match_percent=12.0,
    )

    ranked = rank_select_order_candidates([
        {"label": "spill-only", "status": "ok", "objective": spill_only.to_dict()},
        {
            "label": "target-progress",
            "status": "ok",
            "objective": target_progress.to_dict(),
        },
    ])

    assert spill_only.to_dict()["force_phys_progress_kind"] == "spill-only"
    assert target_progress.to_dict()["force_phys_progress_kind"] == "target-progress"
    assert ranked[0]["label"] == "target-progress"


def test_select_order_ranking_prefers_force_phys_hit_count_before_distance() -> None:
    one_hit = score_select_order_candidate(
        BASELINE,
        ONE_FORCE_PHYS_HIT,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=12.0,
    )
    zero_hit_near = score_select_order_candidate(
        BASELINE,
        WRONG_ORDER_NEAR_PHYS,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 29, 33: 30},
        match_percent=99.0,
    )

    assert one_hit.to_dict()["force_phys_satisfied_count"] == 1
    assert zero_hit_near.to_dict()["force_phys_satisfied_count"] == 0
    assert one_hit.to_dict()["force_phys_distance"] > (
        zero_hit_near.to_dict()["force_phys_distance"]
    )

    ranked = rank_select_order_candidates([
        {"label": "zero-hit-near", "status": "ok", "objective": zero_hit_near.to_dict()},
        {"label": "one-hit-far", "status": "ok", "objective": one_hit.to_dict()},
    ])

    assert ranked[0]["label"] == "one-hit-far"


def test_render_select_order_variant_shows_force_phys_progress_assignments() -> None:
    objective = score_select_order_candidate(
        BASELINE,
        R32_ONE_STEP_CLOSER,
        function="fn_80000000",
        target_orders=[(32, 33)],
        proof_force_phys={32: 27},
        match_percent=12.0,
    )

    text = render_select_order_variant({
        "rank": 1,
        "label": "target-progress",
        "operator": "phys-probe",
        "status": "ok",
        "objective": objective.to_dict(),
    })

    assert "progress=target-progress" in text
    assert "r32:r29->r28!=r27" in text


def test_select_order_ranking_prefers_actionable_missing_side_over_unchanged() -> None:
    wrong = score_select_order_candidate(
        BASELINE,
        BASELINE,
        function="fn_80000000",
        target_orders=[(32, 33)],
        match_percent=99.0,
    )
    missing = score_select_order_candidate(
        BASELINE,
        MISSING_SECOND,
        function="fn_80000000",
        target_orders=[(32, 33)],
        match_percent=12.0,
    )
    right = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER,
        function="fn_80000000",
        target_orders=[(32, 33)],
        match_percent=1.0,
    )

    ranked = rank_select_order_candidates([
        {
            "label": "high-match-wrong-order",
            "status": "ok",
            "objective": wrong.to_dict(),
        },
        {
            "label": "missing-target-side",
            "status": "ok",
            "objective": missing.to_dict(),
        },
        {
            "label": "select-order-flipped",
            "status": "ok",
            "objective": right.to_dict(),
        },
    ])

    assert [row["label"] for row in ranked] == [
        "select-order-flipped",
        "missing-target-side",
        "high-match-wrong-order",
    ]


def test_select_order_score_reports_targeted_interference_facts() -> None:
    objective = score_select_order_candidate(
        STICKY_POOL_BASELINE,
        STICKY_POOL_BASELINE,
        function="fn_80000000",
        target_orders=[(36, 56)],
        match_percent=99.26,
    )

    payload = objective.to_dict()
    pair = payload["target_orders"][0]

    assert payload["opcode_shape_preserved"] is True
    assert payload["targeted_interference_movement_count"] == 0
    assert pair["candidate_first_fact"]["virtual"] == 36
    assert pair["candidate_first_fact"]["live_range"] == [3, 5]
    assert pair["candidate_first_fact"]["degree"] == 6
    assert pair["candidate_first_fact"]["interferers"] == [32, 50, 56, 63, 71, 72]
    assert pair["candidate_second_fact"]["virtual"] == 56
    assert pair["candidate_second_fact"]["live_range"] == [2, 6]
    assert pair["candidate_second_fact"]["degree"] == 5
    assert pair["candidate_first_only_interferers"] == [72]
    assert pair["candidate_shared_interferers"] == [32, 50, 63, 71]
    assert {
        (intent["kind"], intent["virtual"], intent.get("interferer"))
        for intent in pair["probe_intents"]
    } >= {
        ("reduce-degree", 36, None),
        ("remove-interference", 36, 72),
        ("increase-degree", 56, None),
        ("add-interference", 56, 72),
    }


def test_select_order_ranking_prefers_targeted_degree_movement() -> None:
    unchanged = score_select_order_candidate(
        STICKY_POOL_BASELINE,
        STICKY_POOL_BASELINE,
        function="fn_80000000",
        target_orders=[(36, 56)],
        match_percent=99.26,
    )
    reduced_first_degree = score_select_order_candidate(
        STICKY_POOL_BASELINE,
        STICKY_POOL_REDUCED_FIRST_DEGREE,
        function="fn_80000000",
        target_orders=[(36, 56)],
        match_percent=98.0,
    )

    ranked = rank_select_order_candidates([
        {
            "label": "unchanged-sticky-pool",
            "status": "ok",
            "objective": unchanged.to_dict(),
        },
        {
            "label": "reduced-r36-degree",
            "status": "ok",
            "objective": reduced_first_degree.to_dict(),
        },
    ])

    assert ranked[0]["label"] == "reduced-r36-degree"
    assert ranked[0]["objective"]["targeted_interference_movement_count"] == 1
    assert (
        ranked[0]["objective"]["target_orders"][0]["desired_first_degree_reduced"]
        is True
    )


def test_select_order_render_includes_targeted_probe_intents() -> None:
    objective = score_select_order_candidate(
        STICKY_POOL_BASELINE,
        STICKY_POOL_BASELINE,
        function="fn_80000000",
        target_orders=[(36, 56)],
        match_percent=99.26,
    )
    text = render_select_order_variant({
        "rank": 1,
        "label": "unchanged-sticky-pool",
        "operator": "noop",
        "status": "ok",
        "objective": objective.to_dict(),
    })

    assert "opcode_shape_preserved=yes" in text
    assert "r36 fact: live=3..5 degree=6 nIntfr=6 interferers=r32,r50,r56,r63,r71,r72" in text
    assert "r56 fact: live=2..6 degree=5 nIntfr=5 interferers=r32,r36,r50,r63,r71" in text
    assert "probe-intent: remove r36/r72 interference" in text
    assert "probe-intent: add r56/r72 interference" in text


def test_select_order_search_cli_ranks_candidate_pcdumps_json(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    unchanged = tmp_path / "unchanged.txt"
    target_order = tmp_path / "target-order.txt"
    baseline.write_text(BASELINE)
    unchanged.write_text(BASELINE)
    target_order.write_text(TARGET_ORDER)

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"high-match-wrong-order:noop={unchanged}",
            "--candidate",
            f"select-order-flipped:block-scope={target_order}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["target_orders"] == [[32, 33]]
    assert payload["ranking"] == "target select-order objective, final match percent tiebreaker"
    assert payload["variants"][0]["label"] == "select-order-flipped"
    assert payload["variants"][0]["objective"]["target_order_satisfied"] is True
    assert payload["variants"][1]["label"] == "high-match-wrong-order"


def test_select_order_search_rejects_stale_auto_cache_by_default(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = _write_stale_auto_cache(tmp_path)
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 4
    assert "cached pcdump is stale" in result.stdout + result.stderr
    assert "--allow-stale-pcdump" in result.stdout + result.stderr


def test_select_order_search_allow_stale_auto_cache_reports_timestamps(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = _write_stale_auto_cache(tmp_path)
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--allow-stale-pcdump",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    baseline_cache = payload["baseline_cache"]
    assert baseline_cache["fresh"] is False
    assert baseline_cache["path"].endswith("build/mwcc_debug_cache/melee/mn/sample.txt")
    assert baseline_cache["source_path"].endswith("src/melee/mn/sample.c")
    assert isinstance(baseline_cache["source_mtime"], float)
    assert isinstance(baseline_cache["cache_mtime"], float)


def test_select_order_search_includes_probe_provenance_and_match_score(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {}\n")

    def fake_compile(*args, **kwargs) -> str:
        return TARGET_ORDER

    def fake_match_percent(*args, **kwargs) -> tuple[float | None, str | None]:
        return 87.25, None

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        "src.cli.debug._select_order_source_match_percent",
        fake_match_percent,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"call-chain:call-return-compare-switch={source}",
            "--probe-provenance",
            json.dumps({
                "kind": "call-return-compare-chain",
                "call_symbol": "helper_call",
                "call_expression": "helper_call(entity)",
                "result_var": "b34_result",
                "compare_var": "b34",
                "compare_values": [1, 0],
                "source_line": 6,
                "source_col": 18,
            }),
            "--score-match-percent",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["probe"]["provenance"]["call_symbol"] == "helper_call"
    assert variant["probe"]["provenance"]["compare_values"] == [1, 0]
    assert variant["objective"]["match_percent"] == 87.25


def test_select_order_search_scores_generated_probe_match_percent_by_default(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {}\n")
    calls: list[pathlib.Path] = []

    def fake_probes(*args, **kwargs) -> list[LifetimeLayoutProbe]:
        return [
            LifetimeLayoutProbe(
                label="generated-probe-0",
                operator="call-return-compare-chain",
                description="Synthetic generated probe.",
                source_text="void fn_80000000(void) {}\n",
            )
        ]

    def fake_compile(*args, **kwargs) -> str:
        return TARGET_ORDER

    def fake_match_percent(
        path: pathlib.Path,
        **kwargs,
    ) -> tuple[float | None, str | None]:
        calls.append(path)
        return 91.5, None

    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        "src.cli.debug._select_order_source_match_percent",
        fake_match_percent,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["label"] == "generated-probe-0"
    assert variant["objective"]["match_percent"] == 91.5
    assert len(calls) == 1
    assert calls[0].name == "generated-probe-0.c"


def test_select_order_search_opt_in_lists_transform_corpus_probe_json(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "demo.c"
    baseline.write_text(BASELINE)
    source.write_text(TRANSFORM_ASSIGNMENT_SOURCE)

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--no-compile-probes",
            "--include-transform-corpus",
            "--transform-family",
            "comma_operator_noop_expression_shape",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    probe = next(
        probe for probe in payload["probes"]
        if probe["operator"] == "transform-corpus:comma_operator_noop_expression_shape"
    )
    _assert_comma_transform_probe(probe)


def test_select_order_search_force_phys_lists_window_order_probe_json(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) { int dst_iter; dst_iter = 1; }\n")

    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": [{
            "target_ig": 32,
            "order_move": ["before", 33],
            "move_distance": 4,
            "perturbed_reg": 29,
        }],
    }

    def fake_window_probes(*args, **kwargs) -> list[LifetimeLayoutProbe]:
        return [
            LifetimeLayoutProbe(
                label="window-order-ig32-before-dst_iter-0",
                operator="window-order-source-steering",
                description="Synthetic window-order source move.",
                source_text=source.read_text().replace(
                    "dst_iter = 1;",
                    "dst_iter = 2;",
                ),
                provenance={
                    "kind": "window-order-fallback-source-move",
                    "lead": fallback["leads"][0],
                    "moved_local": "dst_iter",
                },
            )
        ]

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        fake_window_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "32:29",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["window_order_fallback"] == fallback
    assert payload["window_order_probe_diagnostics"]["fallback_leads"] == 1
    assert payload["window_order_probe_diagnostics"]["listed_source_probes"] == 1
    assert any(
        probe["operator"] == "window-order-source-steering"
        for probe in payload["probes"]
    )


def test_select_order_search_json_exposes_implicit_temp_source_probe(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(BASELINE)
    source.write_text(textwrap.dedent("""\
        typedef unsigned char u8;
        void sink(u8* value);

        void fn_80000000(int seed)
        {
            int idx;
            u8* dst_iter;
            idx = seed;
            dst_iter = idx;
            sink(dst_iter);
        }
    """))

    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": [{
            "target_ig": 44,
            "order_move": ["before", 43],
            "move_distance": 4,
            "perturbed_reg": 25,
        }],
    }
    attrs = {
        34: {
            "kind": "local",
            "name": "dst_iter",
            "source_file": str(source),
            "source_line": 7,
            "confidence": "low",
        },
        44: {
            "kind": "implicit-temp",
            "expression": "add r44,r49,r34",
            "confidence": "pcode-first-def",
        },
    }

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: attrs,
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda probes, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "32:29",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    diagnostics = payload["window_order_probe_diagnostics"]
    assert diagnostics["fallback_leads"] == 1
    assert diagnostics["source_attributed_leads"] == 1
    assert diagnostics["listed_source_probes"] == 1
    lead = diagnostics["lead_diagnostics"][0]
    assert lead["status"] == "materialized"
    assert lead["synthetic_source_probe"]["handler"] == "implicit-add-owner-split"
    assert lead["synthetic_source_probe"]["operand_ig"] == 34
    probe = next(
        probe for probe in payload["probes"]
        if probe["operator"] == "window-order-source-steering"
    )
    assert (
        probe["provenance"]["synthetic_source_probe"]["handler"]
        == "implicit-add-owner-split"
    )
    try_action = next(
        action for action in payload["source_bridge_summary"]["ranked_actions"]
        if action["kind"] == "try-window-order-source-move"
    )
    assert try_action["target_ig"] == 44
    assert try_action["probe_labels"] == lead["materialized_probe_labels"]
    assert (
        try_action["synthetic_source_probe"]["handler"]
        == "implicit-add-owner-split"
    )
    assert try_action["synthetic_source_probe"]["operand_ig"] == 34


def test_select_order_source_attributions_for_leads_uses_virtual_report(
    monkeypatch,
) -> None:
    class Source:
        kind = "local"
        name = "dst_iter"

    report = object()
    captured: dict[str, object] = {}

    def fake_explain_virtuals(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return report

    def fake_source_attr_of(actual_report, ig_idx: int):
        assert actual_report is report
        return Source() if ig_idx == 32 else None

    monkeypatch.setattr(
        "src.mwcc_debug.virtual_attribution.explain_virtuals",
        fake_explain_virtuals,
    )
    monkeypatch.setattr(
        "src.search.solver.probe.source_attr_of",
        fake_source_attr_of,
    )

    attrs = debug_cli._select_order_source_attributions_for_leads(
        pcdump_text="pcdump",
        function="fn_80000000",
        class_id=0,
        source_text="void fn_80000000(void) {}\n",
        source_file="sample.c",
        fallback={
            "leads": [
                {"target_ig": "32"},
                {"target_ig": 44},
                {"not_target": True},
            ]
        },
        extra_virtuals=[38, 32],
    )

    assert attrs[32].name == "dst_iter"
    assert 44 not in attrs
    assert captured["kwargs"]["virtuals"] == (32, 44, 38)
    assert captured["kwargs"]["reg_class"] == "gpr"


def test_select_order_source_attributions_ignore_low_confidence_binding_for_copy() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000009
        BEFORE REGISTER COLORING
        fn_80000009
        B0: Succ={} Pred={} Labels={}
            mr r32,r3
            mr r33,r4
            mr r34,r39
            addi r35,r3,0
            addi r36,r3,4
            addi r37,r3,8
            addi r38,r3,12
            addi r39,r3,16
        COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)
          iter ig_idx phys degree nIntfr flags
            0 34 r30 0 0 0x00
    """)
    source = textwrap.dedent("""\
        void fn_80000009(void) {
            int probe_a;
            int probe_b;
            int totals;
            int dst_iter;
            sink(dst_iter);
        }
    """)

    attrs = debug_cli._select_order_source_attributions_for_leads(
        pcdump_text=pcdump,
        function="fn_80000009",
        class_id=0,
        source_text=source,
        source_file="sample.c",
        fallback={"leads": [{"target_ig": 34}]},
    )

    assert attrs[34].kind == "copy/coalesce-product"
    assert attrs[34].confidence == "pcode-first-def"
    assert attrs[34].expression == "mr r34,r39"
    assert attrs[34].base_virtual == 39


def test_select_order_source_attributions_for_leads_loads_synthetic_operands(
    monkeypatch,
) -> None:
    class ImplicitTemp:
        kind = "implicit-temp"
        expression = "add r44,r49,r34"

    class LocalSource:
        kind = "local"
        name = "dst_iter"

    calls: list[tuple[int, ...]] = []

    def fake_explain_virtuals(*args, **kwargs):
        virtuals = tuple(kwargs["virtuals"])
        calls.append(virtuals)
        return virtuals

    def fake_source_attr_of(report, ig_idx: int):
        if ig_idx == 44:
            return ImplicitTemp()
        if ig_idx == 34 and 34 in report:
            return LocalSource()
        return None

    monkeypatch.setattr(
        "src.mwcc_debug.virtual_attribution.explain_virtuals",
        fake_explain_virtuals,
    )
    monkeypatch.setattr(
        "src.search.solver.probe.source_attr_of",
        fake_source_attr_of,
    )

    attrs = debug_cli._select_order_source_attributions_for_leads(
        pcdump_text="pcdump",
        function="fn_80000000",
        class_id=0,
        source_text="void fn_80000000(void) {}\n",
        source_file="sample.c",
        fallback={"leads": [{"target_ig": 44}]},
    )

    assert calls == [(44,), (44, 49, 34)]
    assert attrs[44].kind == "implicit-temp"
    assert attrs[34].name == "dst_iter"


def test_select_order_source_attributions_for_leads_loads_pcode_base_virtual(
    monkeypatch,
) -> None:
    class PcodeFieldLoad:
        kind = "load/store-address"
        confidence = "pcode-first-def"
        expression = "lwz r42,40(r263)"
        base_virtual = 263
        field_offset = 40

    class BaseFieldLoad:
        kind = "field-load"
        expression = "data->popup_gobj"
        base_var = "data"
        field_offset = 0x74
        type = "HSD_GObj*"

    calls: list[tuple[int, ...]] = []

    def fake_explain_virtuals(*args, **kwargs):
        virtuals = tuple(kwargs["virtuals"])
        calls.append(virtuals)
        return virtuals

    def fake_source_attr_of(report, ig_idx: int):
        if ig_idx == 42:
            return PcodeFieldLoad()
        if ig_idx == 263 and 263 in report:
            return BaseFieldLoad()
        return None

    monkeypatch.setattr(
        "src.mwcc_debug.virtual_attribution.explain_virtuals",
        fake_explain_virtuals,
    )
    monkeypatch.setattr(
        "src.search.solver.probe.source_attr_of",
        fake_source_attr_of,
    )

    attrs = debug_cli._select_order_source_attributions_for_leads(
        pcdump_text="pcdump",
        function="fn_80000000",
        class_id=0,
        source_text="void fn_80000000(void) {}\n",
        source_file="sample.c",
        fallback={"leads": [{"target_ig": 42}]},
    )

    assert calls == [(42,), (42, 263)]
    assert attrs[42].base_virtual == 263
    assert attrs[263].expression == "data->popup_gobj"


def test_select_order_source_attributions_load_copy_product_source_operand(
    monkeypatch,
) -> None:
    class CopyProduct:
        kind = "copy/coalesce-product"
        expression = "mr r34,r37"
        base_virtual = 37

    class ImplicitTemp:
        kind = "implicit-temp"
        expression = "addi r37,r52,28"

    calls: list[tuple[int, ...]] = []

    def fake_explain_virtuals(*args, **kwargs):
        virtuals = tuple(kwargs["virtuals"])
        calls.append(virtuals)
        return virtuals

    def fake_source_attr_of(report, ig_idx: int):
        if ig_idx == 34:
            return CopyProduct()
        if ig_idx == 37 and 37 in report:
            return ImplicitTemp()
        return None

    monkeypatch.setattr(
        "src.mwcc_debug.virtual_attribution.explain_virtuals",
        fake_explain_virtuals,
    )
    monkeypatch.setattr(
        "src.search.solver.probe.source_attr_of",
        fake_source_attr_of,
    )

    attrs = debug_cli._select_order_source_attributions_for_leads(
        pcdump_text="pcdump",
        function="fn_80000000",
        class_id=0,
        source_text="void fn_80000000(void) {}\n",
        source_file="sample.c",
        fallback={"leads": [{"target_ig": 34}]},
    )

    assert calls == [(34,), (34, 37)]
    assert attrs[34].kind == "copy/coalesce-product"
    assert attrs[37].kind == "implicit-temp"
    assert attrs[37].expression == "addi r37,r52,28"


def test_expression_score_rejects_fpr_order_source_with_mismatched_first_def(
    monkeypatch,
) -> None:
    signature = {
        "kind": "source-expression",
        "source_kind": "local",
        "name": "row_offset",
        "expression": "y_offset * rowf",
    }
    key = debug_cli._expression_signature_key(signature)

    def fake_candidate_expression_entries(**kwargs):
        return {
            key: [
                {
                    "virtual": 33,
                    "actual": 26,
                    "signature": dict(signature),
                    "source": {
                        "kind": "local",
                        "confidence": "fpr-expression-order",
                        "name": "row_offset",
                        "expression": "y_offset * rowf",
                        "first_def": {
                            "opcode": "fmuls",
                            "operands": "f33,f36,f52",
                        },
                    },
                }
            ]
        }

    monkeypatch.setattr(
        debug_cli,
        "_candidate_expression_entries",
        fake_candidate_expression_entries,
    )

    score = debug_cli._score_expression_anchors(
        target_spec={
            "virtuals": {"33": 26},
            "expression_register_class": "fpr",
            "expression_anchors": {
                "33": {
                    "expected": 26,
                    "signature": signature,
                    "baseline_source": {
                        "kind": "local",
                        "confidence": "fpr-expression-order",
                        "name": "row_offset",
                        "expression": "y_offset * rowf",
                        "first_def": {
                            "opcode": "fmuls",
                            "operands": "f39,f32,f48",
                        },
                    },
                }
            },
        },
        target_details={
            "virtuals": {
                "33": {
                    "actual": 26,
                    "matched": True,
                }
            }
        },
        pcdump_text="candidate pcdump",
        function="fn_80000000",
        fn=object(),
        candidate_source_text="void fn_80000000(void) {}\n",
        candidate_source_file="sample.c",
        baseline_pcdump_text=None,
        baseline_source_text=None,
        baseline_source_file=None,
        reg_class="fpr",
    )

    assert score is not None
    assert score["matched"] == 0
    assert score["false_positive_virtual_id_hit_count"] == 1
    detail = score["virtuals"]["33"]
    assert detail["status"] == "first-def-mismatch"
    assert detail["matched"] is False
    assert detail["virtual_id_false_positive"] is True


def test_select_order_source_attributions_keep_first_pass_when_operand_retry_fails(
    monkeypatch,
) -> None:
    class ImplicitTemp:
        kind = "implicit-temp"
        expression = "add r44,r49,r34"

    calls: list[tuple[int, ...]] = []

    def fake_explain_virtuals(*args, **kwargs):
        virtuals = tuple(kwargs["virtuals"])
        calls.append(virtuals)
        if len(calls) > 1:
            raise RuntimeError("operand retry failed")
        return virtuals

    def fake_source_attr_of(report, ig_idx: int):
        return ImplicitTemp() if ig_idx == 44 else None

    monkeypatch.setattr(
        "src.mwcc_debug.virtual_attribution.explain_virtuals",
        fake_explain_virtuals,
    )
    monkeypatch.setattr(
        "src.search.solver.probe.source_attr_of",
        fake_source_attr_of,
    )

    attrs = debug_cli._select_order_source_attributions_for_leads(
        pcdump_text="pcdump",
        function="fn_80000000",
        class_id=0,
        source_text="void fn_80000000(void) {}\n",
        source_file="sample.c",
        fallback={"leads": [{"target_ig": 44}]},
    )

    assert calls == [(44,), (44, 49, 34)]
    assert attrs[44].kind == "implicit-temp"


def test_select_order_search_force_phys_reports_unmaterialized_window_leads(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) { int dst_iter; dst_iter = 1; }\n")
    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": [{"target_ig": 32, "order_move": ["before", 33]}],
    }

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "32:29",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    diagnostics = json.loads(result.stdout)["window_order_probe_diagnostics"]
    assert diagnostics["fallback_leads"] == 1
    assert diagnostics["source_attributed_leads"] == 0
    assert diagnostics["listed_source_probes"] == 0


def test_select_order_search_force_phys_transform_probes_keep_priority_over_window_budget(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) { int dst_iter; dst_iter = 1; }\n")

    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": [{"target_ig": 32, "order_move": ["before", 33]}],
    }

    def fake_append_transform(probes, *, source_text: str | None, **kwargs):
        if source_text is not None:
            probes.append(
                LifetimeLayoutProbe(
                    label="indexed-byte",
                    operator="transform-corpus:indexed_byte_address_temp_steering",
                    description="Synthetic indexed-byte transform.",
                    source_text=source_text.replace("dst_iter = 1;", "dst_iter = 2;"),
                    provenance={
                        "kind": "transform-corpus",
                        "family_id": "indexed_byte_address_temp_steering",
                    },
                )
            )
        return probes

    def fake_window_probes(source_text: str, *args, **kwargs) -> list[LifetimeLayoutProbe]:
        return [
            LifetimeLayoutProbe(
                label=f"window-{idx}",
                operator="window-order-source-steering",
                description="Synthetic window-order source move.",
                source_text=source_text.replace(
                    "dst_iter = 1;",
                    f"dst_iter = {idx + 10};",
                ),
                provenance={"kind": "window-order-fallback-source-move"},
            )
            for idx in range(4)
        ]

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        fake_append_transform,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        fake_window_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "32:29",
            "--max-probes",
            "2",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    operators = [probe["operator"] for probe in json.loads(result.stdout)["probes"]]
    assert operators == [
        "transform-corpus:indexed_byte_address_temp_steering",
        "window-order-source-steering",
    ]


def test_select_order_search_reserves_window_probe_when_transforms_fill_budget(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) { int dst_iter; dst_iter = 1; }\n")

    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": [{"target_ig": 32, "order_move": ["before", 33]}],
    }

    def fake_append_transform(
        probes,
        *,
        source_text: str | None,
        max_probes: int,
        **kwargs,
    ):
        if source_text is None:
            return probes
        for idx in range(max_probes):
            probes.append(
                LifetimeLayoutProbe(
                    label=f"indexed-byte-{idx}",
                    operator="transform-corpus:indexed_byte_address_temp_steering",
                    description="Synthetic indexed-byte transform.",
                    source_text=source_text.replace(
                        "dst_iter = 1;",
                        f"dst_iter = {idx + 2};",
                    ),
                    provenance={
                        "kind": "transform-corpus",
                        "family_id": "indexed_byte_address_temp_steering",
                    },
                )
            )
        return probes

    def fake_window_probes(source_text: str, *args, **kwargs) -> list[LifetimeLayoutProbe]:
        return [
            LifetimeLayoutProbe(
                label="window-force",
                operator="window-order-source-steering",
                description="Synthetic window-order source move.",
                source_text=source_text.replace("dst_iter = 1;", "dst_iter = 10;"),
                provenance={"kind": "window-order-fallback-source-move"},
            )
        ]

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        fake_append_transform,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        fake_window_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "32:29",
            "--max-probes",
            "2",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    operators = [probe["operator"] for probe in payload["probes"]]
    assert operators.count("window-order-source-steering") == 1
    assert operators.count("transform-corpus:indexed_byte_address_temp_steering") == 1
    assert payload["window_order_probe_diagnostics"]["listed_source_probes"] == 1


def test_select_order_search_promotes_attributed_force_phys_fpr_temp_to_lead(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "fpr-baseline.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(FPR_BASELINE)
    source.write_text(textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn_80000000(f32 row_offset)
        {
            f32 row_offset_adj;
            row_offset_adj = row_offset - 0.4f;
            sink(row_offset_adj);
        }
    """))

    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": [{
            "target_ig": 38,
            "order_move": ["before", 50],
            "move_distance": 12,
            "perturbed_reg": 29,
        }],
    }
    attrs = {
        38: {
            "kind": "fpr-temp",
            "expression": "lfs f38,60(r47)",
            "confidence": "pcode-first-def",
        },
        46: {
            "kind": "fpr-temp",
            "expression": "fsubs f46,f45,f44",
            "confidence": "pcode-first-def",
        },
    }

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: attrs,
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda probes, **kwargs: probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "f46<f32",
            "--class",
            "1",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "46:26",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    diagnostics = payload["window_order_probe_diagnostics"]
    assert diagnostics["fallback_leads"] == 2
    ig46 = next(
        lead for lead in diagnostics["lead_diagnostics"]
        if lead["target_ig"] == 46
    )
    assert ig46["status"] == "materialized"
    assert ig46["lead"]["source"] == "force-phys-attributed-temp"
    assert ig46["synthetic_source_probe"]["handler"] == "fpr-arith-owner-split"
    probe = next(
        probe for probe in payload["probes"]
        if (
            probe["operator"] == "window-order-source-steering"
            and probe["provenance"]["lead"]["target_ig"] == 46
        )
    )
    assert (
        probe["provenance"]["synthetic_source_probe"]["handler"]
        == "fpr-arith-owner-split"
    )


def test_select_order_search_materializes_fpr_local_product_owner_split(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "fpr-baseline.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(FPR_BASELINE)
    source.write_text(textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn_80000000(f32 y_spacing, int col)
        {
            f32 y_spacing_alias_32_0;
            f32 col_offset;

            y_spacing_alias_32_0 = y_spacing;
            col_offset = y_spacing_alias_32_0 * (f32) col;
            sink(col_offset);
        }
    """))

    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": [{
            "target_ig": 32,
            "order_move": ["before", 37],
            "move_distance": 5,
            "perturbed_reg": 28,
        }],
    }
    attrs = {
        32: {
            "kind": "local",
            "name": "col_offset",
            "type": "f32",
            "source_file": str(source),
            "source_line": 10,
            "expression": "col_offset = y_spacing_alias_32_0 * (f32) col",
            "confidence": "pcode-first-def",
        },
    }

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: attrs,
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda probes, **kwargs: probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "f32<f37",
            "--class",
            "1",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--force-phys",
            "32:28",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    diagnostics = payload["window_order_probe_diagnostics"]
    lead = next(
        item for item in diagnostics["lead_diagnostics"]
        if item["target_ig"] == 32
    )
    assert lead["status"] == "materialized"
    assert lead["synthetic_source_probe"]["handler"] == "local-fpr-owner-split"
    assert lead["source_local"] == "col_offset"
    assert "terminal_blocker" not in lead
    assert "source_diff" in lead
    assert diagnostics["listed_source_probes"] == 1
    probe = next(
        probe for probe in payload["probes"]
        if probe["operator"] == "window-order-source-steering"
    )
    assert probe["provenance"]["synthetic_source_probe"]["handler"] == (
        "local-fpr-owner-split"
    )
    assert "window_order_synthetic_col_offset" in lead["source_diff"]
    assert "col_offset = window_order_synthetic_col_offset" in lead["source_diff"]
    try_action = next(
        action for action in payload["source_bridge_summary"]["ranked_actions"]
        if action["kind"] == "try-window-order-source-move"
    )
    assert try_action["synthetic_source_probe"]["handler"] == "local-fpr-owner-split"
    assert "window_order_synthetic_col_offset" in try_action["source_diff"]


def test_window_order_source_probe_reports_specific_blocker_for_unsplittable_fpr_local(
) -> None:
    from src.search.directed.window_order_source import plan_window_order_source_probes

    source = textwrap.dedent("""\
        typedef float f32;
        f32 make_value(void);
        void sink(f32 value);

        void fn_80000000(void)
        {
            f32 col_offset;

            col_offset = make_value();
            sink(col_offset);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn_80000000",
        fallback_leads=[{"target_ig": 32, "order_move": ["before", 37]}],
        source_attributions={
            32: {"kind": "local", "name": "col_offset", "source_line": 9},
        },
        max_probes=4,
    )

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"] == "local-source-owner-unsupported-rhs"
    assert diag["source_local"] == "col_offset"


@pytest.mark.parametrize(
    "rhs",
    [
        "f",
        "y_spacing * F",
    ],
)
def test_window_order_source_probe_rejects_unknown_bare_float_suffix_identifier(
    rhs: str,
) -> None:
    from src.search.directed.window_order_source import plan_window_order_source_probes

    source = textwrap.dedent(f"""\
        typedef float f32;
        void sink(f32 value);

        void fn_80000000(f32 y_spacing)
        {{
            f32 col_offset;

            col_offset = {rhs};
            sink(col_offset);
        }}
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn_80000000",
        fallback_leads=[{"target_ig": 32, "order_move": ["before", 37]}],
        source_attributions={
            32: {"kind": "local", "name": "col_offset", "source_line": 8},
        },
        max_probes=4,
    )

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"] == "local-source-owner-unsupported-rhs"
    assert diag["source_local"] == "col_offset"


def test_window_order_source_probe_reports_nonfloat_blocker_for_static_fpr_local(
) -> None:
    from src.search.directed.window_order_source import plan_window_order_source_probes

    source = textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn_80000000(f32 y_spacing)
        {
            static f32 col_offset;

            col_offset = y_spacing * y_spacing;
            sink(col_offset);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn_80000000",
        fallback_leads=[{"target_ig": 32, "order_move": ["before", 37]}],
        source_attributions={
            32: {"kind": "local", "name": "col_offset", "source_line": 8},
        },
        max_probes=4,
    )

    assert plan.probes == []
    assert plan.lead_diagnostics[0]["terminal_blocker"] == (
        "local-source-owner-nonfloat"
    )


def test_window_order_source_probe_source_line_disambiguates_local_owner() -> None:
    from src.search.directed.window_order_source import plan_window_order_source_probes

    source = textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn_80000000(f32 y_spacing, int col)
        {
            f32 col_offset;

            col_offset = y_spacing;
            col_offset = y_spacing * (f32) col;
            sink(col_offset);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn_80000000",
        fallback_leads=[{"target_ig": 32, "order_move": ["before", 37]}],
        source_attributions={
            32: {"kind": "local", "name": "col_offset", "source_line": 9},
        },
        max_probes=4,
    )

    assert len(plan.probes) == 1
    assert plan.lead_diagnostics[0]["status"] == "materialized"

    stale = plan_window_order_source_probes(
        source,
        function="fn_80000000",
        fallback_leads=[{"target_ig": 32, "order_move": ["before", 37]}],
        source_attributions={
            32: {"kind": "local", "name": "col_offset", "source_line": 99},
        },
        max_probes=4,
    )

    assert stale.probes == []
    assert stale.lead_diagnostics[0]["terminal_blocker"] == (
        "local-source-owner-no-unique-assignment"
    )


def test_window_order_source_probe_fpr_temp_owner_accepts_casted_multiply() -> None:
    from src.search.directed.window_order_source import plan_window_order_source_probes

    source = textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn_80000000(f32 y_spacing, int col)
        {
            f32 col_offset;

            col_offset = y_spacing * (f32) col;
            sink(col_offset);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn_80000000",
        fallback_leads=[{
            "target_ig": 46,
            "order_move": ["before", 32],
            "source": "force-phys-attributed-temp",
        }],
        source_attributions={
            46: {"kind": "fpr-temp", "expression": "fmuls f46,f45,f44"},
        },
        max_probes=4,
    )

    assert len(plan.probes) == 1
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["synthetic_source_probe"]["handler"] == "fpr-arith-owner-split"
    assert diag["synthetic_source_probe"]["split_expression"] == (
        "y_spacing * (f32) col"
    )


def test_select_order_search_prioritizes_explicit_force_phys_temp_target(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "fpr-baseline.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(FPR_BASELINE)
    source.write_text(textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn_80000000(f32 row_offset)
        {
            f32 row_offset_adj;
            row_offset_adj = row_offset - 0.4f;
            sink(row_offset_adj);
        }
    """))

    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": [{
            "target_ig": 38,
            "order_move": ["before", 50],
            "move_distance": 12,
            "perturbed_reg": 29,
        }],
    }
    attrs = {
        38: {
            "kind": "fpr-temp",
            "expression": "lfs f38,60(r47)",
            "confidence": "pcode-first-def",
        },
        46: {
            "kind": "fpr-temp",
            "expression": "fsubs f46,f45,f44",
            "confidence": "pcode-first-def",
        },
    }

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: attrs,
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda probes, **kwargs: probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "f46<f32",
            "--class",
            "1",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "38:29,46:26",
            "--max-probes",
            "1",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    probe = payload["probes"][0]
    assert probe["operator"] == "window-order-source-steering"
    assert probe["provenance"]["lead"]["target_ig"] == 46
    assert (
        probe["provenance"]["synthetic_source_probe"]["handler"]
        == "fpr-arith-owner-split"
    )


def test_select_order_search_threads_explicit_pcdump_into_window_fallback(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "retained-baseline.pcdump.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) { int j; j = 1; }\n")

    captured: dict[str, object] = {}

    def fake_fallback(**kwargs):
        captured.update(kwargs)
        return {
            "ran": True,
            "reason": "no window-order fallback lead found",
            "pcdump": str(kwargs.get("pcdump_path")),
            "pcdump_path": str(kwargs.get("pcdump_path")),
            "pcdump_source": kwargs.get("pcdump_source"),
            "target_source": "explicit-force-phys",
            "leads": [],
        }

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        fake_fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda probes, **kwargs: probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "32:29",
            "--max-probes",
            "1",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert captured["pcdump_path"] == baseline
    assert captured["pcdump_text"] == BASELINE
    assert captured["allow_auto_pcdump"] is False
    assert captured["pcdump_source"] == "explicit"
    assert captured["force_phys"] == {32: 29}
    payload = json.loads(result.stdout)
    assert payload["baseline_pcdump_path"] == str(baseline)
    assert payload["baseline_pcdump_source"] == "explicit"
    assert payload["window_order_fallback"]["pcdump"] == str(baseline)
    assert payload["window_order_fallback"]["pcdump_path"] == str(baseline)
    assert payload["window_order_fallback"]["pcdump_source"] == "explicit"
    assert payload["window_order_fallback"]["target_source"] == "explicit-force-phys"
    bridge = payload["source_bridge_summary"]
    assert bridge["window_order_fallback_pcdump_path"] == str(baseline)
    assert bridge["window_order_fallback_pcdump_source"] == "explicit"
    assert bridge["window_order_fallback_target_source"] == "explicit-force-phys"


def test_window_order_fallback_uses_provided_pcdump_text(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    from src.mwcc_debug import tiebreak as tb

    explicit_path = tmp_path / "retained.pcdump.txt"
    explicit_text = "explicit retained pcdump"
    seen: dict[str, object] = {}

    class FakeIG:
        nodes = {}

    class FakeFunction:
        name = "fn_80000000"

        def last_precolor_pass(self):
            return object()

    def fail_resolve(*args, **kwargs):
        raise AssertionError("fallback should not auto-resolve a cache pcdump")

    def fake_load_ig(text, function, *, class_id, fallback_first):
        seen["pcdump_text"] = text
        seen["function"] = function
        seen["class_id"] = class_id
        seen["fallback_first"] = fallback_first
        return FakeIG()

    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", fail_resolve)
    monkeypatch.setattr(tb, "load_ig", fake_load_ig)
    monkeypatch.setattr(
        tb,
        "validate_g1",
        lambda ig, function: type("G1", (), {"rate": 1.0})(),
    )
    monkeypatch.setattr(debug_cli, "parse_pcdump", lambda text: [FakeFunction()])
    monkeypatch.setattr(debug_cli, "parse_hook_events", lambda text: [])
    monkeypatch.setattr(debug_cli, "find_function", lambda events, function: None)
    monkeypatch.setattr(
        debug_cli,
        "_read_force_phys_checkdiff_payload",
        lambda **kwargs: ({}, "fake-checkdiff"),
    )
    monkeypatch.setattr(debug_cli, "_checkdiff_asm_lines", lambda *args: [])
    monkeypatch.setattr(
        debug_cli,
        "_derive_force_phys_from_register_diff_lines",
        lambda *args, **kwargs: {"targets": []},
    )
    monkeypatch.setattr(
        debug_cli,
        "_register_window_rotation_desired_regs",
        lambda *args, **kwargs: {29},
    )
    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_order_flip_leads",
        lambda *args, **kwargs: [{"target_ig": 32}],
    )

    fallback = debug_cli._register_tiebreak_window_order_fallback(
        function="fn_80000000",
        class_id=0,
        pcdump_path=explicit_path,
        pcdump_text=explicit_text,
    )

    assert fallback["ran"] is True
    assert fallback["pcdump"] == str(explicit_path)
    assert fallback["leads"] == [{"target_ig": 32}]
    assert seen == {
        "pcdump_text": explicit_text,
        "function": "fn_80000000",
        "class_id": 0,
        "fallback_first": False,
    }


def test_window_order_fallback_refuses_hidden_auto_pcdump(
    monkeypatch,
) -> None:
    def fail_resolve(*args, **kwargs):
        raise AssertionError("fallback should refuse before resolving cache")

    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", fail_resolve)

    fallback = debug_cli._register_tiebreak_window_order_fallback(
        function="fn_80000000",
        class_id=0,
        allow_auto_pcdump=False,
    )

    assert fallback["ran"] is False
    assert fallback["leads"] == []
    assert fallback["pcdump_path"] is None
    assert fallback["pcdump_source"] == "unavailable"
    assert "auto cache resolution is disabled" in fallback["reason"]


def test_window_order_fallback_uses_explicit_force_phys_targets(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    from src.mwcc_debug import tiebreak as tb

    explicit_path = tmp_path / "retained.pcdump.txt"
    explicit_text = "explicit retained pcdump"
    seen: dict[str, object] = {}

    class FakeNode:
        observed_reg = 29
        incomplete = False
        array_size = 1

    class FakeIG:
        nodes = {32: FakeNode()}

    class FakeFunction:
        name = "fn_80000000"

        def last_precolor_pass(self):
            return object()

    def fake_order_leads(tb_mod, ig, *, vector_targets, desired_regs, max_leads):
        seen["vector_targets"] = vector_targets
        seen["desired_regs"] = desired_regs
        return [{"target_ig": 32, "perturbed_reg": 30}]

    monkeypatch.setattr(tb, "load_ig", lambda *args, **kwargs: FakeIG())
    monkeypatch.setattr(
        tb,
        "validate_g1",
        lambda ig, function: type("G1", (), {"rate": 1.0})(),
    )
    monkeypatch.setattr(debug_cli, "parse_pcdump", lambda text: [FakeFunction()])
    monkeypatch.setattr(debug_cli, "parse_hook_events", lambda text: [])
    monkeypatch.setattr(debug_cli, "find_function", lambda events, function: None)
    monkeypatch.setattr(
        debug_cli,
        "_read_force_phys_checkdiff_payload",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("explicit force-phys must not use live checkdiff")
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_order_flip_leads",
        fake_order_leads,
    )

    fallback = debug_cli._register_tiebreak_window_order_fallback(
        function="fn_80000000",
        class_id=0,
        pcdump_path=explicit_path,
        pcdump_text=explicit_text,
        pcdump_source="explicit",
        force_phys={32: 30},
    )

    assert fallback["ran"] is True
    assert fallback["target_source"] == "explicit-force-phys"
    assert fallback["checkdiff_source"] is None
    assert fallback["pcdump_path"] == str(explicit_path)
    assert fallback["pcdump_source"] == "explicit"
    assert seen["vector_targets"] == [{
        "ig_idx": 32,
        "target_reg": 30,
        "target_reg_name": "r30",
        "already_target": False,
    }]
    assert seen["desired_regs"] == set(range(23, 32))


def test_augmented_window_order_leads_prioritize_explicit_targets() -> None:
    leads = debug_cli._select_order_augmented_window_order_leads(
        [{
            "target_ig": 38,
            "order_move": ["before", "force-phys"],
            "perturbed_reg": 29,
        }],
        force_phys={38: 29, 46: 26},
        class_id=1,
        source_attributions={
            38: {
                "kind": "fpr-temp",
                "expression": "lfs f38,60(r47)",
            },
            46: {
                "kind": "fpr-temp",
                "expression": "fsubs f46,f45,f44",
            },
        },
        priority_targets=(46,),
    )

    assert [lead["target_ig"] for lead in leads[:2]] == [46, 38]
    assert leads[0]["source"] == "force-phys-attributed-temp"


def test_augmented_window_order_leads_include_global_field_address_target() -> None:
    leads = debug_cli._select_order_augmented_window_order_leads(
        [],
        force_phys={79: 29},
        class_id=0,
        source_attributions={
            79: {
                "kind": "global-field-address",
                "confidence": "global-field-address-source-span-unresolved",
                "expression": "assets->FaceB",
                "field_offset": 0xB4,
                "field_name": "FaceB",
                "owner_status": "source-owner-unresolved",
            },
        },
    )

    assert [lead["target_ig"] for lead in leads] == [79]
    assert leads[0]["source"] == "force-phys-global-field-address"
    assert leads[0]["order_move"] == ["before", "force-phys"]


def test_select_order_search_reserves_multiple_promoted_temp_lead_slots(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) { int seed; seed = 0; }\n")

    promoted_leads = [
        {
            "target_ig": target,
            "order_move": ["before", "force-phys"],
            "perturbed_reg": 29,
            "source": "force-phys-attributed-temp",
        }
        for target in (46, 38, 39, 40)
    ]
    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": promoted_leads,
        "force_phys_attributed_temp_leads": promoted_leads,
    }

    def fake_append_transform(
        probes,
        *,
        source_text: str | None,
        max_probes: int,
        **kwargs,
    ):
        if source_text is None:
            return probes
        for idx in range(max_probes):
            probes.append(
                LifetimeLayoutProbe(
                    label=f"indexed-byte-{idx}",
                    operator="transform-corpus:indexed_byte_address_temp_steering",
                    description="Synthetic indexed-byte transform.",
                    source_text=source_text.replace("seed = 0;", f"seed = {idx};"),
                    provenance={
                        "kind": "transform-corpus",
                        "family_id": "indexed_byte_address_temp_steering",
                    },
                )
            )
        return probes

    def fake_window_probes(
        source_text: str,
        *args,
        max_probes: int,
        fallback_leads,
        **kwargs,
    ) -> list[LifetimeLayoutProbe]:
        return [
            LifetimeLayoutProbe(
                label=f"window-ig{lead['target_ig']}",
                operator="window-order-source-steering",
                description="Synthetic window-order source move.",
                source_text=source_text.replace(
                    "seed = 0;",
                    f"seed = {lead['target_ig']};",
                ),
                provenance={
                    "kind": "window-order-fallback-synthetic-source-move",
                    "lead": lead,
                },
            )
            for lead in list(fallback_leads)[:max_probes]
        ]

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        fake_append_transform,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        fake_window_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "32:29,33:30",
            "--max-probes",
            "12",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    window_targets = [
        probe["provenance"]["lead"]["target_ig"]
        for probe in payload["probes"]
        if probe["operator"] == "window-order-source-steering"
    ]
    assert window_targets == [46, 38, 39, 40]
    assert payload["window_order_probe_diagnostics"]["listed_source_probes"] == 4


def test_select_order_search_force_phys_reserves_multi_candidate_promoted_leads(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) { int seed; seed = 0; }\n")

    promoted_leads = [
        {
            "target_ig": target,
            "order_move": ["before", "force-phys"],
            "perturbed_reg": 29,
            "source": "force-phys-attributed-temp",
        }
        for target in (46, 38, 39, 40)
    ]
    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": promoted_leads,
        "force_phys_attributed_temp_leads": promoted_leads,
    }

    def fake_append_transform(
        probes,
        *,
        source_text: str | None,
        max_probes: int,
        **kwargs,
    ):
        if source_text is None:
            return probes
        for idx in range(max_probes):
            probes.append(
                LifetimeLayoutProbe(
                    label=f"indexed-byte-{idx}",
                    operator="transform-corpus:indexed_byte_address_temp_steering",
                    description="Synthetic indexed-byte transform.",
                    source_text=source_text.replace("seed = 0;", f"seed = {idx};"),
                    provenance={
                        "kind": "transform-corpus",
                        "family_id": "indexed_byte_address_temp_steering",
                    },
                )
            )
        return probes

    def fake_window_probes(
        source_text: str,
        *args,
        max_probes: int,
        fallback_leads,
        **kwargs,
    ) -> list[LifetimeLayoutProbe]:
        out: list[LifetimeLayoutProbe] = []
        for lead in fallback_leads:
            candidate_count = 1 if lead["target_ig"] == 46 else 3
            for index in range(candidate_count):
                if len(out) >= max_probes:
                    return out
                out.append(
                    LifetimeLayoutProbe(
                        label=f"window-ig{lead['target_ig']}-{index}",
                        operator="window-order-source-steering",
                        description="Synthetic multi-candidate source move.",
                        source_text=source_text.replace(
                            "seed = 0;",
                            f"seed = {lead['target_ig'] + index};",
                        ),
                        provenance={
                            "kind": "window-order-fallback-synthetic-source-move",
                            "lead": lead,
                            "candidate_index": index,
                        },
                    )
                )
        return out

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        fake_append_transform,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        fake_window_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "f46<f32",
            "--class",
            "1",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--force-phys",
            "32:28,33:26,38:29,39:29,40:29,46:26",
            "--max-probes",
            "16",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    window_targets = [
        probe["provenance"]["lead"]["target_ig"]
        for probe in payload["probes"]
        if probe["operator"] == "window-order-source-steering"
    ]
    assert {46, 38, 39, 40}.issubset(window_targets)
    assert payload["window_order_probe_diagnostics"]["listed_source_probes"] >= 10


def test_debug_cli_transform_corpus_probes_resolve_function_aliases(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_aliases(function: str, melee_root: pathlib.Path) -> tuple[str, ...]:
        captured["alias_function"] = function
        captured["alias_root"] = melee_root
        return ("fn_80000000",)

    def fake_generate(source_text: str, **kwargs) -> tuple[object, ...]:
        captured["source_text"] = source_text
        captured["function_aliases"] = kwargs["function_aliases"]
        captured["force_phys"] = kwargs["force_phys"]
        captured["node_set_delta"] = kwargs["node_set_delta"]
        return ()

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.function_pcdump_aliases",
        fake_aliases,
    )
    monkeypatch.setattr(
        "src.search.directed.transform_corpus.generate_transform_probes",
        fake_generate,
    )

    probes: list[LifetimeLayoutProbe] = []
    result = debug_cli._append_transform_corpus_probes(
        probes,
        source_text="void fn_80000000(void) {}\n",
        function="mnDiagram_DrawCellNumber",
        unit="melee/mn/mndiagram",
        include=True,
        families=["coloring_register_steering"],
        force_phys="33:28",
        node_set_delta={
            "function": "mnDiagram_DrawCellNumber",
            "class_id": 0,
            "missing_virtuals": [{"target_ig": 33, "desired_register": "r28"}],
        },
        max_probes=4,
    )

    assert result is probes
    assert captured["alias_function"] == "mnDiagram_DrawCellNumber"
    assert captured["function_aliases"] == ("fn_80000000",)
    assert captured["force_phys"] == {33: 28}
    assert captured["node_set_delta"]["missing_virtuals"][0]["target_ig"] == 33
    assert isinstance(captured["alias_root"], pathlib.Path)


def test_select_order_search_default_excludes_transform_corpus_probe_json(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "demo.c"
    baseline.write_text(BASELINE)
    source.write_text(TRANSFORM_ASSIGNMENT_SOURCE)

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert not any(
        probe["operator"].startswith("transform-corpus:")
        for probe in payload["probes"]
    )


def test_select_order_search_auto_includes_fpr_expression_transform_probes(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "fpr-baseline.txt"
    source = tmp_path / "demo.c"
    baseline.write_text(FPR_BASELINE)
    source.write_text(
        textwrap.dedent(
            """\
            typedef unsigned char u8;
            typedef float f32;
            void fn_80000000(u8 row) {
                f32 y_offset;
                f32 rowf;
                f32 row_offset;
                f32 row_offset_adj;
                rowf = (f32) row;
                row_offset = y_offset * rowf;
                row_offset_adj = row_offset - 0.4f;
                use(row_offset, row_offset_adj);
            }
            """
        )
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "f33<f39",
            "--class",
            "1",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "39:26,33:28",
            "--no-compile-probes",
            "--max-probes",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["auto_transform_families"] == [
        "pcode_only_fpr_callarg_temp_repair",
        "coupled_fpr_coalesce_product_repair",
        "coloring_register_steering",
    ]
    assert payload["probes"][0]["operator"] == (
        "transform-corpus:coloring_register_steering"
    )
    assert payload["probes"][0]["mutator_key"] == (
        "steer_fpr_dependent_product_recompute"
    )


def test_select_order_search_auto_includes_indexed_byte_transform_probes(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "gpr-baseline.txt"
    source = tmp_path / "demo.c"
    baseline.write_text(BASELINE)
    source.write_text(
        textwrap.dedent(
            """\
            typedef unsigned char u8;
            struct MnDiagramData { u8 sorted_names[25]; };
            extern struct MnDiagramData mnDiagram_804A076C;
            void fn_80000000(int j) {
                u8 candidate;
                candidate = mnDiagram_804A076C.sorted_names[j + 1];
                use(candidate);
            }
            """
        )
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--class",
            "0",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "34:27,44:25",
            "--no-compile-probes",
            "--max-probes",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["auto_transform_families"] == [
        "indexed_byte_address_temp_steering"
    ]
    assert payload["probes"][0]["operator"] == (
        "transform-corpus:indexed_byte_address_temp_steering"
    )
    assert payload["probes"][0]["mutator_key"] == (
        "steer_indexed_byte_same_line_expr"
    )


def test_select_order_search_auto_materializes_indexed_byte_helper_result(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "gpr-baseline.txt"
    source = tmp_path / "helper.c"
    baseline.write_text(BASELINE)
    source.write_text(
        textwrap.dedent(
            """\
            typedef unsigned char u8;
            static inline u8 visible_name(u8* sorted, int i) { return sorted[i]; }
            void fn_80000000(u8* sorted, int i) {
                int name_id;
                name_id = visible_name(sorted, i) &
                          0xFFFFFFFFFFFFFFFFu;
                use(name_id);
            }
            """
        )
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--class",
            "0",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "79:25",
            "--no-compile-probes",
            "--max-probes",
            "4",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["auto_transform_families"] == [
        "indexed_byte_address_temp_steering"
    ]
    assert any(
        probe["operator"] == "transform-corpus:indexed_byte_address_temp_steering"
        and probe["mutator_key"] == "steer_indexed_byte_helper_result_temp"
        for probe in payload["probes"]
    )


def test_select_order_signal_restore_handler_restores_active_source(
    tmp_path: pathlib.Path,
) -> None:
    source = tmp_path / "sample.c"
    source.write_text("void fn_80000000(void) { /* original */ }\n")

    debug_cli._ACTIVE_SOURCE_RESTORES.clear()
    debug_cli._register_active_source_restore(source, source.read_text())
    source.write_text("void fn_80000000(void) { /* mutated */ }\n")

    with pytest.raises(SystemExit) as excinfo:
        debug_cli._restore_active_sources_for_signal(signal.SIGTERM, None)

    assert excinfo.value.code == 128 + signal.SIGTERM
    assert source.read_text() == "void fn_80000000(void) { /* original */ }\n"
    assert source not in debug_cli._ACTIVE_SOURCE_RESTORES


def test_select_order_command_restore_registers_active_source_for_signal(
    tmp_path: pathlib.Path,
) -> None:
    source = tmp_path / "sample.c"
    original = "void fn_80000000(void) { /* original */ }\n"
    source.write_text(original)

    debug_cli._ACTIVE_SOURCE_RESTORES.clear()
    restore = debug_cli._SelectOrderCommandSourceRestore(source, melee_root=tmp_path)
    source.write_text("void fn_80000000(void) { /* interrupted residue */ }\n")

    with pytest.raises(SystemExit) as excinfo:
        debug_cli._restore_active_sources_for_signal(signal.SIGTERM, None)

    assert excinfo.value.code == 128 + signal.SIGTERM
    assert source.read_text() == original
    assert source not in debug_cli._ACTIVE_SOURCE_RESTORES
    restore.close()


def test_select_order_command_restore_survives_nested_source_restore_unregister(
    tmp_path: pathlib.Path,
) -> None:
    source = tmp_path / "sample.c"
    original = "void fn_80000000(void) { /* original */ }\n"
    nested_original = "void fn_80000000(void) { /* nested */ }\n"
    source.write_text(original)

    debug_cli._ACTIVE_SOURCE_RESTORES.clear()
    restore = debug_cli._SelectOrderCommandSourceRestore(source, melee_root=tmp_path)
    debug_cli._register_active_source_restore(source, nested_original)
    debug_cli._unregister_active_source_restore(source)
    source.write_text("void fn_80000000(void) { /* interrupted residue */ }\n")

    with pytest.raises(SystemExit):
        debug_cli._restore_active_sources_for_signal(signal.SIGTERM, None)

    assert source.read_text() == original
    assert source not in debug_cli._ACTIVE_SOURCE_RESTORES
    restore.close()


def test_select_order_source_match_percent_restores_after_compile_timeout(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    target = melee_root / "src" / "melee" / "mn" / "sample.c"
    target.parent.mkdir(parents=True)
    original = "void fn_80000000(void) { /* original */ }\n"
    target.write_text(original)
    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_80000000(void) { /* candidate */ }\n")

    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_ninja_with_no_diag_retry",
        lambda *args, **kwargs: (
            subprocess.CompletedProcess(
                ["ninja", "build/GALE01/src/melee/mn/sample.o"],
                124,
                "",
                "timed out after 1s",
            ),
            False,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_command_with_optional_timeout",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, "", ""),
    )

    pct, error = debug_cli._select_order_source_match_percent(
        candidate,
        function="fn_80000000",
        melee_root=melee_root,
        timeout=1,
    )

    assert pct is None
    assert error is not None
    assert "timed out after 1s" in error
    assert target.read_text() == original


def test_select_order_source_match_percent_holds_repo_lock_through_restore(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    target = melee_root / "src" / "melee" / "mn" / "sample.c"
    target.parent.mkdir(parents=True)
    original = "void fn_80000000(void) { /* original */ }\n"
    candidate_text = "void fn_80000000(void) { /* candidate */ }\n"
    target.write_text(original)
    candidate = tmp_path / "candidate.c"
    candidate.write_text(candidate_text)
    events: list[str] = []
    lock_held = False

    class FakeLock:
        def __enter__(self):
            nonlocal lock_held
            events.append("lock-enter")
            lock_held = True

        def __exit__(self, exc_type, exc, tb):
            nonlocal lock_held
            assert target.read_text() == original
            events.append("lock-exit")
            lock_held = False

    def fake_lock(
        root: pathlib.Path,
        *,
        label: str = "",
        timeout: float | None = None,
    ):
        assert root == melee_root
        assert label == "source-scoring"
        assert timeout == 1
        return FakeLock()

    def fake_ninja(*args, **kwargs):
        assert lock_held is True
        assert target.read_text() == candidate_text
        events.append("ninja")
        return (
            subprocess.CompletedProcess(args[0], 0, "", ""),
            False,
        )

    def fake_refresh(*args, **kwargs):
        assert lock_held is True
        assert target.read_text() == candidate_text
        events.append("report")
        return 97.5, None

    def fake_cleanup(cmd, **kwargs):
        assert lock_held is True
        assert target.read_text() == original
        events.append("cleanup")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_acquire_checkdiff_repo_lock", fake_lock)
    monkeypatch.setattr(debug_cli, "_run_ninja_with_no_diag_retry", fake_ninja)
    monkeypatch.setattr(debug_cli, "_refresh_match_pct_after_successful_build", fake_refresh)
    monkeypatch.setattr(debug_cli, "_run_command_with_optional_timeout", fake_cleanup)

    pct, error = debug_cli._select_order_source_match_percent(
        candidate,
        function="fn_80000000",
        melee_root=melee_root,
        timeout=1,
    )

    assert pct == 97.5
    assert error is None
    assert events == ["lock-enter", "ninja", "report", "cleanup", "lock-exit"]
    assert target.read_text() == original


def test_refresh_match_percent_reports_objdiff_timeout(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    objdiff = tmp_path / "build" / "tools" / "objdiff-cli"
    objdiff.parent.mkdir(parents=True)
    objdiff.write_text("#!/bin/sh\n")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))

    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    pct, error = debug_cli._refresh_match_pct_after_successful_build(
        "melee/mn/sample",
        "fn_80000000",
        tmp_path,
        timeout=3,
    )

    assert pct is None
    assert error is not None
    assert "timed out after 3s running" in error
    assert "objdiff-cli report generate" in error


def test_select_order_search_beam_composes_and_ranks_by_real_score(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    campaign = tmp_path / "campaign"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) { /* seed */ }\n")

    def fake_probes(source_text: str, *args, **kwargs) -> list[LifetimeLayoutProbe]:
        if "neutral" in source_text:
            return [
                LifetimeLayoutProbe(
                    label="compose-win",
                    operator="block-scope",
                    description="Compose with the neutral probe.",
                    source_text=(
                        "void fn_80000000(void) { /* seed neutral win */ }\n"
                    ),
                )
            ]
        return [
            LifetimeLayoutProbe(
                label="neutral",
                operator="call-return-compare-chain",
                description="Neutral first step.",
                source_text="void fn_80000000(void) { /* seed neutral */ }\n",
            ),
            LifetimeLayoutProbe(
                label="regression",
                operator="call-return-compare-chain",
                description="Regressing first step.",
                source_text="void fn_80000000(void) { /* seed regression */ }\n",
            ),
            LifetimeLayoutProbe(
                label="duplicate-neutral",
                operator="call-return-compare-chain",
                description="Duplicate body.",
                source_text="void fn_80000000(void) { /* seed neutral */ }\n",
            ),
        ]

    def fake_compile(*args, **kwargs) -> str:
        return TARGET_ORDER

    def fake_match_percent(
        path: pathlib.Path,
        **kwargs,
    ) -> tuple[float | None, str | None]:
        text = path.read_text()
        if "win" in text:
            return 98.0, None
        if "neutral" in text:
            return 97.37545, None
        return 70.0, None

    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        "src.cli.debug._select_order_source_match_percent",
        fake_match_percent,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--beam-depth",
            "2",
            "--beam-width",
            "1",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ranking"] == (
        "final match percent first, then target select-order objective"
    )
    assert payload["beam_campaign_dir"] == str(campaign)
    ledger = json.loads((campaign / "ledger.json").read_text())
    assert ledger["beam_depth"] == 2
    assert ledger["beam_width"] == 1
    assert len(ledger["deduped"]) == 1
    labels = [entry["label"] for entry in ledger["entries"]]
    assert any("neutral" in label for label in labels)
    assert any("compose-win" in label for label in labels)

    variants = payload["variants"]
    assert variants[0]["chain"] == ["neutral", "compose-win"]
    assert variants[0]["objective"]["match_percent"] == 98.0
    assert variants[1]["chain"] == ["neutral"]
    assert variants[1]["objective"]["match_percent"] == 97.37545


def test_select_order_search_single_probe_uses_campaign_dir_for_retained_sources(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    campaign = tmp_path / "campaign"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) { /* seed */ }\n")

    def fake_probes(source_text: str, *args, **kwargs) -> list[LifetimeLayoutProbe]:
        return [
            LifetimeLayoutProbe(
                label="single",
                operator="call-return-compare-chain",
                description="Single generated probe.",
                source_text="void fn_80000000(void) { /* single */ }\n",
            )
        ]

    def fake_compile(*args, **kwargs) -> str:
        return TARGET_ORDER

    def fake_match_percent(
        path: pathlib.Path,
        **kwargs,
    ) -> tuple[float | None, str | None]:
        return 99.0, None

    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        "src.cli.debug._select_order_source_match_percent",
        fake_match_percent,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    retained_dir = campaign / "probes"
    assert payload["generated_source_dir"] == str(retained_dir)
    retained = pathlib.Path(payload["variants"][0]["source_retained"])
    assert retained.read_text() == "void fn_80000000(void) { /* single */ }\n"
    assert retained.relative_to(retained_dir)


def test_select_order_search_force_phys_beam_composes_transform_and_window_order(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    campaign = tmp_path / "campaign"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) { /* seed */ }\n")

    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": [{
            "target_ig": 32,
            "order_move": ["before", 33],
            "move_distance": 4,
            "perturbed_reg": 29,
        }],
    }

    def fake_append_transform(probes, *, source_text: str | None, **kwargs):
        if source_text is None or "indexed" in source_text:
            return probes
        probes.append(
            LifetimeLayoutProbe(
                label="indexed-byte",
                operator="transform-corpus:indexed_byte_address_temp_steering",
                description="Synthetic indexed-byte transform.",
                source_text=source_text.replace("seed", "seed indexed"),
                provenance={
                    "kind": "transform-corpus",
                    "family_id": "indexed_byte_address_temp_steering",
                    "probe_id": "indexed_byte_address_temp_steering@0",
                    "mutator_key": "indexed-byte-test",
                },
            )
        )
        return probes

    def fake_window_probes(source_text: str, *args, **kwargs) -> list[LifetimeLayoutProbe]:
        if "indexed" not in source_text or "force-win" in source_text:
            return []
        return [
            LifetimeLayoutProbe(
                label="window-force",
                operator="window-order-source-steering",
                description="Synthetic force-phys window move.",
                source_text=source_text.replace("indexed", "indexed force-win"),
                provenance={
                    "kind": "window-order-fallback-source-move",
                    "lead": fallback["leads"][0],
                    "moved_local": "dst_iter",
                },
            )
        ]

    def fake_compile(diff_input, **kwargs) -> str:
        text = diff_input.path.read_text()
        if "force-win" in text:
            return TARGET_ORDER_RIGHT_PHYS
        return TARGET_ORDER_WRONG_PHYS

    def fake_match_percent(
        path: pathlib.Path,
        **kwargs,
    ) -> tuple[float | None, str | None]:
        text = path.read_text()
        if "force-win" in text:
            return 95.0, None
        if "indexed" in text:
            return 99.0, None
        return 70.0, None

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        fake_append_transform,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        fake_window_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        "src.cli.debug._select_order_source_match_percent",
        fake_match_percent,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "32:29",
            "--beam-depth",
            "2",
            "--beam-width",
            "1",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ranking"] == (
        "target select-order objective, final match percent tiebreaker"
    )
    assert payload["window_order_fallback"] == fallback
    assert payload["source_bridge_summary"]["listed_source_probes"] == 1
    ledger = json.loads((campaign / "ledger.json").read_text())
    chains = [entry["chain"] for entry in ledger["entries"]]
    assert ["indexed-byte", "window-force"] in chains

    variants = payload["variants"]
    assert variants[0]["chain"] == ["indexed-byte", "window-force"]
    assert variants[0]["objective"]["force_phys_satisfied_count"] == 1
    assert variants[0]["objective"]["match_percent"] == 95.0
    assert variants[1]["chain"] == ["indexed-byte"]
    assert variants[1]["objective"]["force_phys_satisfied_count"] == 0
    assert variants[1]["objective"]["match_percent"] == 99.0
    bucket_entry = next(
        entry for entry in payload["diagnostic_buckets"]["force-phys-hit-32"]
        if entry["label"] == variants[0]["label"]
    )
    assert bucket_entry["chain"] == ["indexed-byte", "window-force"]
    assert bucket_entry["probe"]["chain"] == ["indexed-byte", "window-force"]
    assert bucket_entry["probe"]["provenance"]["kind"] == (
        "window-order-fallback-source-move"
    )
    assert "void fn_80000000" in bucket_entry["source_hunk"]


def test_select_order_search_force_phys_beam_composes_distinct_window_leads(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    campaign = tmp_path / "campaign"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) { int seed; seed = 0; }\n")

    promoted_leads = [
        {
            "target_ig": target,
            "order_move": ["before", "force-phys"],
            "perturbed_reg": 29,
            "source": "force-phys-attributed-temp",
        }
        for target in (46, 38)
    ]
    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": promoted_leads,
        "force_phys_attributed_temp_leads": promoted_leads,
    }

    def fake_append_transform(
        probes,
        *,
        source_text: str | None,
        max_probes: int,
        **kwargs,
    ):
        if source_text is None:
            return probes
        for idx in range(max_probes):
            probes.append(
                LifetimeLayoutProbe(
                    label=f"indexed-byte-{idx}",
                    operator="transform-corpus:indexed_byte_address_temp_steering",
                    description="Synthetic indexed-byte transform.",
                    source_text=source_text.replace(
                        "seed = 0;",
                        f"seed = {idx + 10};",
                    ),
                    provenance={
                        "kind": "transform-corpus",
                        "family_id": "indexed_byte_address_temp_steering",
                    },
                )
            )
        return probes

    def fake_window_probes(
        source_text: str,
        *args,
        max_probes: int,
        fallback_leads,
        **kwargs,
    ) -> list[LifetimeLayoutProbe]:
        return [
            LifetimeLayoutProbe(
                label=f"window-ig{lead['target_ig']}",
                operator="window-order-source-steering",
                description="Synthetic window-order source move.",
                source_text=source_text.replace(
                    "seed = 0;",
                    f"seed = 0; /* ig{lead['target_ig']} */",
                ),
                provenance={
                    "kind": "window-order-fallback-synthetic-source-move",
                    "lead": lead,
                },
            )
            for lead in list(fallback_leads)[:max_probes]
        ]

    def fake_compile(diff_input, **kwargs) -> str:
        text = diff_input.path.read_text()
        if "ig38" in text and "ig46" in text:
            return TARGET_ORDER_RIGHT_PHYS
        return TARGET_ORDER_WRONG_PHYS

    def fake_match_percent(
        path: pathlib.Path,
        **kwargs,
    ) -> tuple[float | None, str | None]:
        text = path.read_text()
        if "ig38" in text and "ig46" in text:
            return 99.0, None
        if "ig38" in text or "ig46" in text:
            return 95.0, None
        return 70.0, None

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        fake_append_transform,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        fake_window_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        "src.cli.debug._select_order_source_match_percent",
        fake_match_percent,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "32:29,33:30",
            "--max-probes",
            "4",
            "--beam-depth",
            "2",
            "--beam-width",
            "2",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    ledger = json.loads((campaign / "ledger.json").read_text())
    assert ["window-ig46", "window-ig38"] in [
        entry["chain"] for entry in ledger["entries"]
    ]
    composed = next(
        variant for variant in payload["variants"]
        if variant.get("chain") == ["window-ig46", "window-ig38"]
    )
    first_step = next(
        variant for variant in payload["variants"]
        if variant.get("chain") == ["window-ig46"]
    )
    assert composed["probe"]["provenance"]["lead"]["target_ig"] == 38
    assert first_step["probe"]["provenance"]["lead"]["target_ig"] == 46


def test_select_order_search_guard_repair_beam_expands_rejected_allocator_hit(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    campaign = tmp_path / "campaign"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) { /* seed */ }\n")

    def fake_lifetime_probes(
        source_text: str,
        *args,
        **kwargs,
    ) -> list[LifetimeLayoutProbe]:
        if "guarded-hit" in source_text:
            return [
                LifetimeLayoutProbe(
                    label="repair-inline-boundary",
                    operator="block-scope",
                    description="Repair the rejected inline boundary shape.",
                    source_text=source_text.replace("guarded-hit", "repair-accepted"),
                )
            ]
        return [
            LifetimeLayoutProbe(
                label="guarded-hit",
                operator="call-return-compare-chain",
                description="Allocator hit rejected by the structural guard.",
                source_text=source_text.replace("seed", "guarded-hit"),
            )
        ]

    def fake_compile(diff_input, **kwargs) -> str:
        text = diff_input.path.read_text()
        if "guarded-hit" in text or "repair-accepted" in text:
            return TARGET_ORDER_RIGHT_PHYS
        return TARGET_ORDER_WRONG_PHYS

    def fake_source_score(path: pathlib.Path, **kwargs):
        text = path.read_text()
        if "guarded-hit" in text:
            return debug_cli._SourceCandidateRealScore(
                97.0,
                None,
                structural_guard={
                    "accepted": False,
                    "shape_preserved": False,
                    "classification_primary": "inline-boundary-toolchain-artifact",
                    "normalized_diff_lines": 6,
                    "frame_delta": 0,
                    "rejection_reason": (
                        "checkdiff structural drift: "
                        "inline-boundary-toolchain-artifact"
                    ),
                },
            )
        if "repair-accepted" in text:
            return debug_cli._SourceCandidateRealScore(
                96.5,
                None,
                structural_guard={
                    "accepted": True,
                    "shape_preserved": True,
                    "classification_primary": "normalized-structural-match",
                    "normalized_diff_lines": 0,
                    "frame_delta": 0,
                },
            )
        return debug_cli._SourceCandidateRealScore(70.0, None)

    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda probes, **kwargs: probes,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_lifetime_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_score",
        fake_source_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--transform-force-phys",
            "32:29,33:30",
            "--beam-depth",
            "1",
            "--beam-width",
            "1",
            "--guard-repair-width",
            "1",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    repair_dir = campaign / "guard-repair"
    assert payload["guard_repair_campaign_dir"] == str(repair_dir)
    assert payload["guard_repair_summary"]["status"] == "repair-found"
    assert payload["guard_repair_summary"]["repair_entry_count"] == 1

    ledger_path = pathlib.Path(payload["guard_repair_ledger"])
    ledger = json.loads(ledger_path.read_text())
    assert ledger_path == repair_dir / "ledger.json"
    assert ledger["effective_depth"] == 1
    assert ledger["width"] == 1
    assert ledger["seeds"][0]["label"].endswith("guarded-hit")
    assert ledger["seeds"][0]["protected_force_phys_hits"] == {"32": 29, "33": 30}
    assert ledger["entries"][0]["repair_seed_label"] == ledger["seeds"][0]["label"]
    assert ledger["entries"][0]["status"] == "ok"

    variants = payload["variants"]
    labels = [variant["label"] for variant in variants]
    seed_label = ledger["seeds"][0]["label"]
    repair_variant = next(
        variant for variant in variants
        if variant.get("repair_seed_label") == seed_label
    )
    assert seed_label in labels
    assert "repair-inline-boundary" in repair_variant["label"]
    assert repair_variant["parent_label"] == seed_label
    assert repair_variant["structural_guard"]["accepted"] is True
    assert repair_variant["objective"]["force_phys_satisfied_count"] == 2
    summary_repair = payload["guard_repair_summary"]["repair_candidates"][0]
    assert summary_repair["label"] == repair_variant["label"]
    assert summary_repair["guard_accepted"] is True


def test_select_order_guard_repair_summary_ignores_lost_protected_repair() -> None:
    seed = {
        "label": "exact",
        "status": "ok",
        "path": "/tmp/exact.c",
        "source_retained": "/tmp/exact.c",
        "structural_guard": {
            "accepted": False,
            "classification_primary": "control-flow-source-shape",
            "normalized_diff_lines": 55,
            "frame_delta": 0,
        },
        "objective": {
            "match_percent": 98.0,
            "force_phys_targets": {"32": 29, "33": 30},
            "force_phys_assignments": {
                "32": {"actual": 29, "status": "hit"},
                "33": {"actual": 30, "status": "hit"},
            },
            "force_phys_satisfied_count": 2,
            "force_phys_distance": 0,
            "force_phys_missing": [],
            "force_phys_mismatches": {},
        },
    }
    repair = {
        "label": "repair-lost-one",
        "status": "ok",
        "repair_seed_label": "exact",
        "source_retained": "/tmp/repair-lost-one.c",
        "structural_guard": {
            "accepted": True,
            "classification_primary": "normalized-structural-match",
            "normalized_diff_lines": 0,
            "frame_delta": 0,
        },
        "protected_preservation": {
            "protected_register_count": 2,
            "protected_preserved_count": 1,
            "preserved_protected_registers": {"32": 29},
            "lost_protected_registers": {"33": {"expected": 30, "actual": None}},
        },
        "objective": {
            "match_percent": 97.0,
            "force_phys_targets": {"32": 29, "33": 30},
            "force_phys_assignments": {
                "32": {"actual": 29, "status": "hit"},
                "33": {"actual": 3, "status": "mismatch"},
            },
            "force_phys_satisfied_count": 1,
            "force_phys_distance": 27,
            "force_phys_missing": [],
            "force_phys_mismatches": {
                "33": {"expected": 30, "actual": 3},
            },
        },
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [repair, seed],
        force_phys={32: 29, 33: 30},
    )

    assert summary["status"] == "needs-repair"
    assert summary["repair_entry_count"] == 1
    candidate = summary["repair_candidates"][0]
    assert candidate["protected_preserved_count"] == 1
    assert candidate["lost_protected_registers"] == {
        "33": {"expected": 30, "actual": None}
    }


def _protected_plateau_variant(
    *,
    label: str,
    normalized_diff_lines: int,
    actuals: dict[str, int | None],
    repair_seed_label: str | None = None,
    source_hunk: str | None = None,
    chain: list[str] | None = None,
    protected_preserved_count: int | None = None,
) -> dict:
    expected = {"34": 27, "44": 25}
    assignments = {}
    hit_count = 0
    mismatches = {}
    missing = []
    for ig_idx, expected_phys in expected.items():
        actual = actuals.get(ig_idx)
        if actual == expected_phys:
            status = "hit"
            hit_count += 1
        elif actual is None:
            status = "missing"
            missing.append(int(ig_idx))
        else:
            status = "mismatch"
            mismatches[ig_idx] = {"expected": expected_phys, "actual": actual}
        assignments[ig_idx] = {"actual": actual, "status": status}
    variant = {
        "label": label,
        "status": "ok",
        "path": f"/tmp/{label}.c",
        "source_retained": f"/tmp/{label}.c",
        "chain": list(chain or []),
        "source_hunk": source_hunk,
        "structural_guard": {
            "accepted": False,
            "classification_primary": "control-flow-source-shape",
            "normalized_diff_lines": normalized_diff_lines,
            "opcode_similarity": 0.7 + (100 - normalized_diff_lines) / 10000,
            "frame_delta": 0,
        },
        "objective": {
            "match_percent": 98.0 - normalized_diff_lines / 1000,
            "force_phys_targets": expected,
            "force_phys_assignments": assignments,
            "force_phys_satisfied_count": hit_count,
            "force_phys_distance": len(expected) - hit_count,
            "force_phys_missing": missing,
            "force_phys_mismatches": mismatches,
        },
    }
    if repair_seed_label is not None:
        variant["repair_seed_label"] = repair_seed_label
        preserved = {
            ig_idx: expected_phys
            for ig_idx, expected_phys in expected.items()
            if actuals.get(ig_idx) == expected_phys
        }
        lost = {
            ig_idx: {"expected": expected_phys, "actual": actuals.get(ig_idx)}
            for ig_idx, expected_phys in expected.items()
            if actuals.get(ig_idx) != expected_phys
        }
        variant["protected_preservation"] = {
            "protected_register_count": len(expected),
            "protected_preserved_count": (
                protected_preserved_count
                if protected_preserved_count is not None
                else len(preserved)
            ),
            "preserved_protected_registers": preserved,
            "lost_protected_registers": lost,
        }
    return variant


def test_select_order_guard_repair_summary_reports_protected_structural_plateau() -> None:
    hunk = (
        "s32 i;\n"
        "s32 max_idx;\n"
        "if (condition_temp) {\n"
        "    *ll_probe_iter_0++ = mnDiagram_804A076C.sorted_names[i];\n"
        "}\n"
    )
    seed = _protected_plateau_variant(
        label="ndiff53",
        normalized_diff_lines=53,
        actuals={"34": 27, "44": 25},
        source_hunk=hunk,
    )
    preserving_same = _protected_plateau_variant(
        label="preserving-same",
        repair_seed_label="ndiff53",
        normalized_diff_lines=53,
        actuals={"34": 27, "44": 25},
        source_hunk=hunk,
        chain=["transform-corpus-indexed_byte_address_temp_steering-1"],
    )
    lost_but_lower = _protected_plateau_variant(
        label="lost-both-lower",
        repair_seed_label="ndiff53",
        normalized_diff_lines=52,
        actuals={"34": None, "44": None},
        source_hunk=hunk,
        chain=["transform-corpus-indexed_byte_address_temp_steering-4"],
    )

    summary = debug_cli._select_order_guard_repair_summary(
        [lost_but_lower, preserving_same, seed],
        force_phys={34: 27, 44: 25},
        guard_repair_ledger={
            "entries": [{"label": "preserving-same"}, {"label": "lost-both-lower"}],
            "deduped": [],
            "stop_condition": "depth-exhausted",
            "effective_depth": 1,
            "width": 1,
            "max_probes": 16,
        },
    )

    plateau = summary["protected_structural_plateau"]
    assert plateau["status"] == "terminal-plateau"
    assert plateau["terminal_blocker"] == "protected-structural-plateau"
    assert plateau["seed_label"] == "ndiff53"
    assert plateau["required_normalized_diff_lines_below"] == 53
    assert plateau["best_preserving_candidate"]["label"] == "preserving-same"
    assert plateau["best_preserving_candidate"]["normalized_diff_lines"] == 53
    assert plateau["discarded_non_preserving_improvements"][0]["label"] == (
        "lost-both-lower"
    )
    assert plateau["coverage"]["coverage_status"] == "bounded-depth-exhausted"
    assert plateau["coverage"]["bounded_by"] == {
        "effective_depth": 1,
        "width": 1,
        "max_probes": 16,
    }
    component_kinds = {
        component["component"] for component in plateau["source_components"]
    }
    assert {
        "pointer-walk-store",
        "condition-temp-owner-split",
        "indexed-byte-address-temp-steering",
        "loop-index-declaration",
        "max-index-declaration-placement",
        "direct-global-dst",
    }.issubset(component_kinds)


def test_select_order_guard_repair_summary_omits_plateau_when_preserving_improves() -> None:
    seed = _protected_plateau_variant(
        label="ndiff53",
        normalized_diff_lines=53,
        actuals={"34": 27, "44": 25},
    )
    preserving_lower = _protected_plateau_variant(
        label="preserving-lower",
        repair_seed_label="ndiff53",
        normalized_diff_lines=52,
        actuals={"34": 27, "44": 25},
        chain=["transform-corpus-indexed_byte_address_temp_steering-2"],
    )

    summary = debug_cli._select_order_guard_repair_summary(
        [preserving_lower, seed],
        force_phys={34: 27, 44: 25},
        guard_repair_ledger={
            "entries": [{"label": "preserving-lower"}],
            "stop_condition": "depth-exhausted",
        },
    )

    assert "protected_structural_plateau" not in summary


def test_select_order_guard_repair_summary_requires_terminal_ledger_for_plateau() -> None:
    seed = _protected_plateau_variant(
        label="ndiff53",
        normalized_diff_lines=53,
        actuals={"34": 27, "44": 25},
    )
    preserving_same = _protected_plateau_variant(
        label="preserving-same",
        repair_seed_label="ndiff53",
        normalized_diff_lines=53,
        actuals={"34": 27, "44": 25},
    )

    summary = debug_cli._select_order_guard_repair_summary(
        [preserving_same, seed],
        force_phys={34: 27, 44: 25},
    )
    assert "protected_structural_plateau" not in summary

    timeout_summary = debug_cli._select_order_guard_repair_summary(
        [preserving_same, seed],
        force_phys={34: 27, 44: 25},
        guard_repair_ledger={
            "entries": [{"label": "preserving-same"}],
            "stop_condition": "timeout",
            "timed_out": True,
        },
    )
    assert "protected_structural_plateau" not in timeout_summary


def test_select_order_guard_repair_summary_requires_explicit_full_preservation() -> None:
    seed = _protected_plateau_variant(
        label="ndiff53",
        normalized_diff_lines=53,
        actuals={"34": 27, "44": 25},
    )
    repair_without_metadata = _protected_plateau_variant(
        label="missing-preservation-metadata",
        repair_seed_label="ndiff53",
        normalized_diff_lines=53,
        actuals={"34": 27, "44": 25},
    )
    repair_without_metadata.pop("protected_preservation")

    summary = debug_cli._select_order_guard_repair_summary(
        [repair_without_metadata, seed],
        force_phys={34: 27, 44: 25},
        guard_repair_ledger={
            "entries": [{"label": "missing-preservation-metadata"}],
            "stop_condition": "depth-exhausted",
        },
    )

    assert "protected_structural_plateau" not in summary


def test_select_order_guard_repair_summary_loads_plateau_ledger_path(
    tmp_path: pathlib.Path,
) -> None:
    seed = _protected_plateau_variant(
        label="ndiff53",
        normalized_diff_lines=53,
        actuals={"34": 27, "44": 25},
    )
    preserving_same = _protected_plateau_variant(
        label="preserving-same",
        repair_seed_label="ndiff53",
        normalized_diff_lines=53,
        actuals={"34": 27, "44": 25},
    )
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps({
        "entries": [{"label": "preserving-same"}],
        "deduped": [{"label": "deduped"}],
        "stop_condition": "frontier-empty",
        "effective_depth": 2,
        "width": 1,
        "max_probes": 8,
    }))

    summary = debug_cli._select_order_guard_repair_summary(
        [preserving_same, seed],
        force_phys={34: 27, 44: 25},
        guard_repair_ledger=str(ledger_path),
    )

    plateau = summary["protected_structural_plateau"]
    assert plateau["coverage"]["coverage_status"] == "frontier-empty"
    assert plateau["coverage"]["deduped_candidates"] == 1
    assert plateau["coverage"]["bounded_by"] == {
        "effective_depth": 2,
        "width": 1,
        "max_probes": 8,
    }


def test_select_order_search_guard_repair_seed_expands_without_beam(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    seed = tmp_path / "exact.c"
    campaign = tmp_path / "campaign"
    baseline.write_text(BASELINE)
    seed.write_text("void fn_80000000(void) { /* exact-hit */ }\n")

    def fake_lifetime_probes(
        source_text: str,
        *args,
        **kwargs,
    ) -> list[LifetimeLayoutProbe]:
        if "exact-hit" not in source_text:
            return []
        return [
            LifetimeLayoutProbe(
                label="repair-structural-shape",
                operator="block-scope",
                description="Repair exact-register structural shape.",
                source_text=source_text.replace("exact-hit", "repair-accepted"),
            )
        ]

    def fake_compile(diff_input, **kwargs) -> str:
        text = diff_input.path.read_text()
        if "exact-hit" in text or "repair-accepted" in text:
            return TARGET_ORDER_RIGHT_PHYS
        return TARGET_ORDER_WRONG_PHYS

    def fake_source_score(path: pathlib.Path, **kwargs):
        text = path.read_text()
        if "exact-hit" in text:
            return debug_cli._SourceCandidateRealScore(
                98.0,
                None,
                structural_guard={
                    "accepted": False,
                    "shape_preserved": False,
                    "classification_primary": "control-flow-source-shape",
                    "normalized_diff_lines": 55,
                    "opcode_similarity": 0.705314,
                    "line_delta": 9,
                    "frame_delta": 0,
                },
            )
        if "repair-accepted" in text:
            return debug_cli._SourceCandidateRealScore(
                97.5,
                None,
                structural_guard={
                    "accepted": True,
                    "shape_preserved": True,
                    "classification_primary": "normalized-structural-match",
                    "normalized_diff_lines": 0,
                    "opcode_similarity": 1.0,
                    "line_delta": 0,
                    "frame_delta": 0,
                },
            )
        return debug_cli._SourceCandidateRealScore(70.0, None)

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: {"leads": []},
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda probes, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_lifetime_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(debug_cli, "_select_order_source_score", fake_source_score)

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--force-phys",
            "32:29,33:30",
            "--guard-repair-seed",
            f"exact:manual-exact={seed}",
            "--guard-repair-width",
            "1",
            "--max-probes",
            "1",
            "--no-compile-probes",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["guard_repair_seed_specs"] == [
        {
            "label": "exact",
            "operator": "manual-exact",
            "path": str(seed),
        }
    ]
    assert payload["guard_repair_campaign_dir"] == str(campaign / "guard-repair")
    assert payload["guard_repair_summary"]["status"] == "repair-found"

    ledger = json.loads(pathlib.Path(payload["guard_repair_ledger"]).read_text())
    assert ledger["effective_depth"] == 1
    assert ledger["explicit_seed_specs"] == payload["guard_repair_seed_specs"]
    assert ledger["seeds"][0]["label"] == "exact"
    assert ledger["seeds"][0]["seed_source"] == "explicit"
    assert ledger["seeds"][0]["protected_force_phys_hits"] == {
        "32": 29,
        "33": 30,
    }
    assert ledger["entries"][0]["repair_seed_label"] == "exact"
    assert ledger["entries"][0]["status"] == "ok"
    assert ledger["entries"][0]["protected_register_count"] == 2
    assert ledger["entries"][0]["protected_preserved_count"] == 2
    assert ledger["entries"][0]["lost_protected_registers"] == {}
    assert ledger["entries"][0]["preserved_protected_registers"] == {
        "32": 29,
        "33": 30,
    }

    variants = payload["variants"]
    seed_variant = next(variant for variant in variants if variant["label"] == "exact")
    assert seed_variant["guard_repair_explicit_seed"] is True
    assert seed_variant["source_retained"] == str(seed)
    repair_variant = next(
        variant for variant in variants
        if variant.get("repair_seed_label") == "exact"
    )
    assert "repair-structural-shape" in repair_variant["label"]
    assert repair_variant["parent_label"] == "exact"
    assert repair_variant["structural_guard"]["accepted"] is True
    assert repair_variant["objective"]["force_phys_satisfied_count"] == 2
    summary_repair = payload["guard_repair_summary"]["repair_candidates"][0]
    assert summary_repair["protected_register_count"] == 2
    assert summary_repair["protected_preserved_count"] == 2
    assert summary_repair["lost_protected_registers"] == {}


def test_select_order_search_guard_repair_seed_has_selection_priority(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    candidate = tmp_path / "candidate.c"
    seed = tmp_path / "exact.c"
    campaign = tmp_path / "campaign"
    baseline.write_text(BASELINE)
    candidate.write_text("void fn_80000000(void) { /* better-ranked */ }\n")
    seed.write_text("void fn_80000000(void) { /* explicit-hit */ }\n")

    def fake_lifetime_probes(
        source_text: str,
        *args,
        **kwargs,
    ) -> list[LifetimeLayoutProbe]:
        if "explicit-hit" not in source_text:
            return []
        return [
            LifetimeLayoutProbe(
                label="repair-explicit",
                operator="block-scope",
                description="Repair explicit seed.",
                source_text=source_text.replace("explicit-hit", "repair-accepted"),
            )
        ]

    def fake_compile(diff_input, **kwargs) -> str:
        return TARGET_ORDER_RIGHT_PHYS

    def fake_source_score(path: pathlib.Path, **kwargs):
        text = path.read_text()
        if "better-ranked" in text:
            return debug_cli._SourceCandidateRealScore(
                99.0,
                None,
                structural_guard={
                    "accepted": False,
                    "shape_preserved": False,
                    "classification_primary": "control-flow-source-shape",
                    "normalized_diff_lines": 40,
                    "frame_delta": 0,
                },
            )
        if "explicit-hit" in text:
            return debug_cli._SourceCandidateRealScore(
                90.0,
                None,
                structural_guard={
                    "accepted": False,
                    "shape_preserved": False,
                    "classification_primary": "control-flow-source-shape",
                    "normalized_diff_lines": 55,
                    "frame_delta": 0,
                },
            )
        return debug_cli._SourceCandidateRealScore(
            89.0,
            None,
            structural_guard={
                "accepted": True,
                "shape_preserved": True,
                "classification_primary": "normalized-structural-match",
                "normalized_diff_lines": 0,
                "frame_delta": 0,
            },
        )

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: {"leads": []},
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_lifetime_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(debug_cli, "_select_order_source_score", fake_source_score)

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"better:manual-candidate={candidate}",
            "--transform-force-phys",
            "32:29,33:30",
            "--guard-repair-seed",
            f"exact:manual-exact={seed}",
            "--guard-repair-width",
            "1",
            "--max-probes",
            "1",
            "--no-compile-probes",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    ledger = json.loads(pathlib.Path(payload["guard_repair_ledger"]).read_text())
    assert [seed_entry["label"] for seed_entry in ledger["seeds"]] == ["exact"]
    assert ledger["seeds"][0]["seed_source"] == "explicit"
    assert ledger["entries"][0]["repair_seed_label"] == "exact"
    better_variant = next(
        variant for variant in payload["variants"]
        if variant["label"] == "better"
    )
    assert better_variant["objective"]["match_percent"] == 99.0
    assert better_variant.get("guard_repair_explicit_seed") is not True


def test_select_order_search_guard_repair_seed_respects_depth_zero(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    seed = tmp_path / "exact.c"
    baseline.write_text(BASELINE)
    seed.write_text("void fn_80000000(void) { /* exact-hit */ }\n")

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: {"leads": []},
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        lambda *args, **kwargs: TARGET_ORDER_RIGHT_PHYS,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_score",
        lambda *args, **kwargs: debug_cli._SourceCandidateRealScore(
            98.0,
            None,
            structural_guard={
                "accepted": False,
                "shape_preserved": False,
                "classification_primary": "control-flow-source-shape",
                "normalized_diff_lines": 55,
                "frame_delta": 0,
            },
        ),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--force-phys",
            "32:29,33:30",
            "--guard-repair-seed",
            f"exact:manual-exact={seed}",
            "--guard-repair-depth",
            "0",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["guard_repair_ledger"] is None
    assert payload["guard_repair_summary"]["status"] == "needs-repair"
    seed_variant = next(
        variant for variant in payload["variants"]
        if variant["label"] == "exact"
    )
    assert seed_variant["guard_repair_explicit_seed"] is True


def test_select_order_search_guard_repair_seed_requires_force_phys(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    seed = tmp_path / "exact.c"
    baseline.write_text(BASELINE)
    seed.write_text("void fn_80000000(void) { /* exact-hit */ }\n")

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--guard-repair-seed",
            f"exact:manual-exact={seed}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert "--guard-repair-seed requires --force-phys" in result.stderr


def test_select_order_search_guard_repair_seed_requires_source_path(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    seed = tmp_path / "exact.txt"
    baseline.write_text(BASELINE)
    seed.write_text(TARGET_ORDER_RIGHT_PHYS)

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--force-phys",
            "32:29,33:30",
            "--guard-repair-seed",
            f"exact:manual-exact={seed}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert "guard repair seed path must be a .c source" in result.stderr


def test_select_order_search_json_includes_source_bridge_summary(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    candidate = tmp_path / "candidate.c"
    baseline.write_text(BASELINE)
    candidate.write_text("void fn_80000000(void) { int j; j = 1; }\n")

    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": [{
            "target_ig": 32,
            "order_move": ["before", 33],
            "move_distance": 4,
            "perturbed_reg": 29,
        }],
    }
    attrs = {
        32: {
            "kind": "local",
            "name": "j",
            "source_file": str(candidate),
            "source_line": 1,
            "confidence": "high",
        },
    }

    def fake_compile(*args, **kwargs) -> str:
        return WRONG_ORDER_NEAR_PHYS

    def fake_source_score(path: pathlib.Path, **kwargs):
        return debug_cli._SourceCandidateRealScore(
            99.0,
            None,
            structural_guard={"accepted": True},
        )

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: attrs,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_score",
        fake_source_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"wrong:indexed-byte={candidate}",
            "--transform-force-phys",
            "32:29",
            "--guard-repair-depth",
            "0",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["guard_repair_ledger"] is None
    summary = payload["source_bridge_summary"]
    assert summary["status"] == "blocked"
    assert summary["dominant_blocker"] == "window-order-leads-not-materialized"
    assert summary["leads"][0]["source"]["name"] == "j"
    action_kinds = [action["kind"] for action in summary["ranked_actions"]]
    assert "try-window-order-source-move" not in action_kinds
    assert "inspect-window-order-source-mobility" in action_kinds


def test_select_order_search_json_reports_late_failure_after_source_restore(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    live_source = melee_root / "src" / "melee" / "mn" / "sample.c"
    live_source.parent.mkdir(parents=True)
    original = "void fn_80000000(void) { /* original */ }\n"
    residue = "void fn_80000000(void) { /* generated residue */ }\n"
    live_source.write_text(original)
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)
    campaign = tmp_path / "campaign"
    probe_calls = 0

    def fake_transform_probes(*args, **kwargs) -> None:
        return None

    def fake_probes(*args, **kwargs) -> list[LifetimeLayoutProbe]:
        nonlocal probe_calls
        probe_calls += 1
        if probe_calls == 1:
            assert live_source.read_text() == original
            live_source.write_text(residue)
        return [
            LifetimeLayoutProbe(
                label=f"late-failure-probe-{probe_calls}",
                operator="block-scope",
                description="Synthetic generated probe.",
                source_text=(
                    f"void fn_80000000(void) {{ /* candidate {probe_calls} */ }}\n"
                ),
            )
        ]

    def fake_compile(*args, **kwargs) -> str:
        return TARGET_ORDER_RIGHT_PHYS

    def fake_source_score(*args, **kwargs):
        return debug_cli._SourceCandidateRealScore(
            99.0,
            None,
            structural_guard={"accepted": True},
        )

    def fake_source_bridge_summary(*args, **kwargs):
        assert live_source.read_text() == original
        assert (campaign / "ledger.json").is_file()
        raise RuntimeError("source bridge summary exploded")

    debug_cli._ACTIVE_SOURCE_RESTORES.clear()
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: {"ran": True, "leads": []},
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        fake_transform_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_score",
        fake_source_score,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_bridge_summary",
        fake_source_bridge_summary,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(live_source),
            "--transform-force-phys",
            "32:29",
            "--beam-depth",
            "1",
            "--beam-width",
            "1",
            "--guard-repair-depth",
            "0",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["error"]["type"] == "RuntimeError"
    assert payload["error"]["message"] == "source bridge summary exploded"
    assert payload["source_restored"] is True
    assert payload["source"] == str(live_source)
    assert payload["beam_campaign_dir"] == str(campaign)
    assert payload["beam_ledger"] == str(campaign / "ledger.json")
    assert pathlib.Path(payload["beam_ledger"]).is_file()
    assert payload["variants"]
    assert live_source.read_text() == original
    assert debug_cli._ACTIVE_SOURCE_RESTORES == {}


def test_select_order_source_score_repo_lock_respects_timeout(
    tmp_path: pathlib.Path,
) -> None:
    fcntl = pytest.importorskip("fcntl")
    melee_root = tmp_path / "melee"
    melee_root.mkdir()
    lock_dir = pathlib.Path(tempfile.gettempdir()) / "melee-checkdiff-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    digest = debug_cli.hashlib.sha1(
        str(melee_root.resolve()).encode(),
    ).hexdigest()[:12]
    lock_path = lock_dir / f"repo.{digest}.lock"
    held_lock = lock_path.open("w")
    try:
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_EX)
        start = time.monotonic()
        with pytest.raises(TimeoutError, match="source-scoring lock"):
            with debug_cli._acquire_source_score_repo_lock(
                melee_root,
                timeout=0.01,
            ):
                pass
        assert time.monotonic() - start < 1.0
    finally:
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_UN)
        held_lock.close()


def test_select_order_search_json_returns_when_source_score_lock_is_held(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    fcntl = pytest.importorskip("fcntl")
    melee_root = tmp_path / "melee"
    live_source = melee_root / "src" / "melee" / "mn" / "sample.c"
    live_source.parent.mkdir(parents=True)
    live_source.write_text("void fn_80000000(void) { /* original */ }\n")
    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_80000000(void) { /* candidate */ }\n")
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)

    lock_dir = pathlib.Path(tempfile.gettempdir()) / "melee-checkdiff-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    digest = debug_cli.hashlib.sha1(
        str(melee_root.resolve()).encode(),
    ).hexdigest()[:12]
    lock_path = lock_dir / f"repo.{digest}.lock"
    held_lock = lock_path.open("w")

    def fake_compile(*args, **kwargs) -> str:
        return TARGET_ORDER_RIGHT_PHYS

    debug_cli._ACTIVE_SOURCE_RESTORES.clear()
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: {"ran": True, "leads": []},
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    try:
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_EX)
        start = time.monotonic()
        result = runner.invoke(
            app,
            [
                "debug",
                "select-order-search",
                "-f",
                "fn_80000000",
                "--target",
                "r32<r33",
                "--pcdump",
                str(baseline),
                "--candidate",
                f"held-lock:block-scope={candidate}",
                "--transform-force-phys",
                "32:29",
                "--guard-repair-depth",
                "0",
                "--no-compile-probes",
                "--timeout",
                "1",
                "--json",
            ],
        )
    finally:
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_UN)
        held_lock.close()

    assert result.exit_code == 0, result.stdout + result.stderr
    assert time.monotonic() - start < 2.5
    payload = json.loads(result.stdout)
    assert payload["status"] == "timeout"
    assert payload["timed_out"] is True
    assert "finishing select-order candidate held-lock" in payload["timeout_error"]
    assert payload["variants"]


def test_select_order_search_marks_source_pcdump_omission_as_malformed_source(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "bad-probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {}\n")

    def fake_compile(*args, **kwargs) -> str:
        return BASELINE.replace("fn_80000000", "other_fn")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"bad-source:declaration-use-distance={source}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["status"] == "malformed-source"
    assert "fn_80000000 not found in pcdump" in variant["error"]
    assert variant["source_retained"] == str(source)
    assert "source_hunk" in variant
    assert "objective" not in variant


def test_select_order_search_no_score_restores_live_source_after_probe_compile_mutates_it(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    live_source = melee_root / "src" / "melee" / "mn" / "sample.c"
    live_source.parent.mkdir(parents=True)
    original = "void fn_80000000(void) { /* original */ }\n"
    live_source.write_text(original)
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)

    def fake_probes(*args, **kwargs) -> list[LifetimeLayoutProbe]:
        return [
            LifetimeLayoutProbe(
                label="generated-probe-mutates-live-source",
                operator="block-scope",
                description="Synthetic generated probe.",
                source_text="void fn_80000000(void) { /* candidate */ }\n",
            )
        ]

    def fake_compile(*args, **kwargs) -> str:
        assert live_source.read_text() == original
        live_source.write_text("void fn_80000000(void) { /* mutated */ }\n")
        return TARGET_ORDER

    debug_cli._ACTIVE_SOURCE_RESTORES.clear()
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(live_source),
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert live_source.read_text() == original


def test_select_order_search_restores_unit_source_for_retained_source_file_timeout(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    live_source = melee_root / "src" / "melee" / "mn" / "sample.c"
    retained_source = melee_root / "build" / "diagnostics" / "candidate.c"
    live_source.parent.mkdir(parents=True)
    retained_source.parent.mkdir(parents=True)
    original = "void fn_80000000(void) { /* original */ }\n"
    live_source.write_text(original)
    retained_source.write_text("void fn_80000000(void) { /* retained */ }\n")
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)
    campaign = tmp_path / "campaign"
    seen_timeouts: list[int] = []

    def fake_find_unit(function: str, root: pathlib.Path) -> str:
        assert function == "fn_80000000"
        assert root == melee_root
        return "melee/mn/sample"

    def fake_probes(*args, **kwargs) -> list[LifetimeLayoutProbe]:
        return [
            LifetimeLayoutProbe(
                label="timeout-probe",
                operator="block-scope",
                description="Synthetic timeout probe.",
                source_text="void fn_80000000(void) { /* timeout */ }\n",
            )
        ]

    def fake_compile(*args, **kwargs) -> str:
        seen_timeouts.append(kwargs["timeout"])
        live_source.write_text("void fn_80000000(void) { /* interrupted */ }\n")
        raise subprocess.TimeoutExpired(["fake-compile"], 1)

    debug_cli._ACTIVE_SOURCE_RESTORES.clear()
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", fake_find_unit)
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(retained_source),
            "--beam-depth",
            "1",
            "--beam-width",
            "1",
            "--campaign-dir",
            str(campaign),
            "--timeout",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert live_source.read_text() == original
    assert seen_timeouts == pytest.approx([1.0], abs=0.1)
    payload = json.loads(result.stdout)
    assert payload["source_restored"] is True
    assert payload["source_restore_error"] is None
    assert payload["variants"][0]["status"] == "failed"
    assert debug_cli._ACTIVE_SOURCE_RESTORES == {}


def test_select_order_search_shares_timeout_budget_with_real_tree_score(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    live_source = melee_root / "src" / "melee" / "mn" / "sample.c"
    candidate = tmp_path / "candidate.c"
    live_source.parent.mkdir(parents=True)
    live_source.write_text("void fn_80000000(void) { /* original */ }\n")
    candidate.write_text("void fn_80000000(void) { /* candidate */ }\n")
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)
    clock = {"now": 100.0}
    seen: dict[str, float | None] = {}

    def fake_find_unit(function: str, root: pathlib.Path) -> str:
        assert function == "fn_80000000"
        assert root == melee_root
        return "melee/mn/sample"

    def fake_compile(*args, **kwargs) -> str:
        assert kwargs["timeout"] == pytest.approx(1.0)
        clock["now"] += 0.8
        return TARGET_ORDER_RIGHT_PHYS

    def fake_score(*args, **kwargs) -> debug_cli._SourceCandidateRealScore:
        seen["timeout"] = kwargs["timeout"]
        seen["deadline"] = kwargs["deadline"]
        return debug_cli._SourceCandidateRealScore(99.0, None)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", fake_find_unit)
    monkeypatch.setattr(debug_cli.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(debug_cli, "_select_order_source_score", fake_score)

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"manual:block-scope={candidate}",
            "--timeout",
            "1",
            "--max-probes",
            "0",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert seen["timeout"] == 1
    assert seen["deadline"] == pytest.approx(101.0)
    payload = json.loads(result.stdout)
    assert payload["variants"][0]["status"] == "ok"
    assert payload["variants"][0]["objective"]["match_percent"] == 99.0


def test_select_order_search_emits_partial_guard_repair_json_on_top_level_timeout(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    base = tmp_path / "base.c"
    seed = tmp_path / "seed.c"
    campaign = tmp_path / "campaign"
    baseline.write_text(BASELINE)
    base.write_text("void fn_80000000(void) { /* base */ }\n")
    seed.write_text("void fn_80000000(void) { /* downhill */ }\n")
    clock = {"now": 100.0}
    compile_labels: list[str] = []

    def fake_transform_probes(probes, *, source_text: str | None, **kwargs):
        if source_text is None or "downhill" not in source_text:
            return None
        for label in ("keep-ig34", "move-ig44"):
            probes.append(
                LifetimeLayoutProbe(
                    label=label,
                    operator="transform-corpus:test",
                    description="Synthetic guard repair probe.",
                    source_text=source_text.replace("downhill", label),
                    provenance={"kind": "test", "mode": label},
                )
            )
        return None

    def fake_compile(diff_input, **kwargs) -> str:
        compile_labels.append(diff_input.label)
        if diff_input.label.startswith("gr"):
            clock["now"] += 1.2
        return ONE_FORCE_PHYS_HIT

    def fake_source_score(path: pathlib.Path, **kwargs):
        return debug_cli._SourceCandidateRealScore(
            70.0,
            None,
            structural_guard={
                "accepted": False,
                "shape_preserved": False,
                "classification_primary": "inline-boundary-toolchain-artifact",
                "normalized_diff_lines": 21,
                "opcode_similarity": 0.913242,
                "frame_delta": 0,
                "rejection_reason": (
                    "checkdiff structural drift: inline-boundary-toolchain-artifact"
                ),
            },
        )

    monkeypatch.setattr(debug_cli.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: {"ran": True, "leads": []},
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        fake_transform_probes,
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(debug_cli, "_select_order_source_score", fake_source_score)

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(base),
            "--candidate",
            f"downhill:indexed-byte={seed}",
            "--force-phys",
            "32:29,33:30",
            "--guard-repair-depth",
            "1",
            "--guard-repair-width",
            "1",
            "--max-probes",
            "2",
            "--no-compile-probes",
            "--campaign-dir",
            str(campaign),
            "--timeout",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "timeout"
    assert payload["partial"] is True
    assert payload["timed_out"] is True
    assert "guard repair" in payload["timeout_error"]
    assert sum(label.startswith("gr") for label in compile_labels) == 1
    ledger = json.loads(pathlib.Path(payload["guard_repair_ledger"]).read_text())
    assert ledger["stop_condition"] == "timeout"
    assert ledger["timed_out"] is True
    assert ledger["partial"] is True
    assert "guard repair" in ledger["timeout_error"]
    assert len(ledger["entries"]) == 1
    assert payload["variants"]


def test_select_order_search_skips_optional_summaries_after_budget_exhausted(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    base = tmp_path / "base.c"
    campaign = tmp_path / "campaign"
    baseline.write_text(BASELINE)
    base.write_text("void fn_80000000(void) { /* base */ }\n")
    clock = {"now": 100.0}
    source_bridge_calls: list[bool] = []
    terminal_calls: list[bool] = []

    def fake_probes(*args, **kwargs) -> list[LifetimeLayoutProbe]:
        return [
            LifetimeLayoutProbe(
                label="slow-probe",
                operator="block-scope",
                description="Synthetic slow probe.",
                source_text="void fn_80000000(void) { /* slow */ }\n",
            )
        ]

    def fake_compile(*args, **kwargs) -> str:
        clock["now"] += 1.2
        return ONE_FORCE_PHYS_HIT

    def fake_source_score(path: pathlib.Path, **kwargs):
        return debug_cli._SourceCandidateRealScore(70.0, None)

    def fake_source_bridge_summary(*args, **kwargs):
        source_bridge_calls.append(True)
        return {"status": "called"}

    def fake_terminal_summary(*args, **kwargs):
        terminal_calls.append(True)
        return {"status": "called"}

    monkeypatch.setattr(debug_cli.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: {"ran": True, "leads": []},
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        "src.search.directed.window_order_source.generate_window_order_source_probes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(debug_cli, "_select_order_source_score", fake_source_score)
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_bridge_summary",
        fake_source_bridge_summary,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_terminal_exhaustion_summary",
        fake_terminal_summary,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(base),
            "--force-phys",
            "32:29,33:30",
            "--beam-depth",
            "1",
            "--beam-width",
            "1",
            "--max-probes",
            "1",
            "--campaign-dir",
            str(campaign),
            "--timeout",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "timeout"
    assert payload["partial"] is True
    assert "finishing select-order beam candidate" in payload["timeout_error"]
    assert payload["source_bridge_summary"]["status"] == "skipped-timeout"
    assert payload["terminal_exhaustion_summary"]["status"] == "skipped-timeout"
    assert source_bridge_calls == []
    assert terminal_calls == []
    ledger = json.loads(pathlib.Path(payload["beam_ledger"]).read_text())
    assert ledger["stop_condition"] == "timeout"
    assert ledger["timed_out"] is True


def test_select_order_search_marks_source_score_deadline_error_as_timeout(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    candidate = tmp_path / "candidate.c"
    baseline.write_text(BASELINE)
    candidate.write_text("void fn_80000000(void) { /* candidate */ }\n")

    def fake_compile(*args, **kwargs) -> str:
        return ONE_FORCE_PHYS_HIT

    def fake_source_score(*args, **kwargs):
        return debug_cli._SourceCandidateRealScore(
            70.0,
            None,
            structural_guard_error=(
                "budget exhausted before running checkdiff structural guard"
            ),
        )

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(debug_cli, "_select_order_source_score", fake_source_score)

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"deadline:block-scope={candidate}",
            "--force-phys",
            "32:29,33:30",
            "--guard-repair-depth",
            "0",
            "--max-probes",
            "0",
            "--timeout",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "timeout"
    assert payload["partial"] is True
    assert payload["timed_out"] is True
    assert payload["timeout_error"] == (
        "budget exhausted before running checkdiff structural guard"
    )
    assert payload["source_restored"] is True
    assert payload["source_restore_error"] is None
    assert payload["variants"][0]["structural_guard_error"] == payload[
        "timeout_error"
    ]
    retained_pcdump = pathlib.Path(payload["variants"][0]["pcdump_path"])
    assert retained_pcdump == candidate.with_suffix(".pcdump.txt")
    assert retained_pcdump.read_text(encoding="utf-8") == ONE_FORCE_PHYS_HIT
    assert payload["variants"][0]["objective"]["pcdump_path"] == str(retained_pcdump)
    summary = payload["source_bridge_summary"]
    assert summary["status"] != "skipped-timeout"
    assert summary["partial"] is True
    assert summary["timed_out"] is True
    assert summary["timeout_error"] == payload["timeout_error"]
    assert summary["variants"][0]["pcdump_path"] == str(retained_pcdump)


def test_select_order_search_restores_live_source_after_probe_generation_mutates_it(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    live_source = melee_root / "src" / "melee" / "mn" / "sample.c"
    live_source.parent.mkdir(parents=True)
    original = "void fn_80000000(void) { /* original */ }\n"
    residue = "void fn_80000000(void) { /* generated residue */ }\n"
    live_source.write_text(original)
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)

    def fake_find_unit(function: str, root: pathlib.Path) -> str:
        assert function == "fn_80000000"
        assert root == melee_root
        return "melee/mn/sample"

    def fake_probes(*args, **kwargs) -> list[LifetimeLayoutProbe]:
        assert live_source.read_text() == original
        live_source.write_text(residue)
        return [
            LifetimeLayoutProbe(
                label="generated-probe-mutates-before-scoring",
                operator="block-scope",
                description="Synthetic generated probe.",
                source_text="void fn_80000000(void) { /* candidate */ }\n",
            )
        ]

    def fake_compile(*args, **kwargs) -> str:
        return TARGET_ORDER

    def fake_match_percent(*args, **kwargs) -> tuple[float | None, str | None]:
        return 91.5, None

    debug_cli._ACTIVE_SOURCE_RESTORES.clear()
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", fake_find_unit)
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        "src.cli.debug._select_order_source_match_percent",
        fake_match_percent,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert live_source.read_text() == original


def test_select_order_search_restores_live_source_when_probe_generation_then_exits(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    live_source = melee_root / "src" / "melee" / "mn" / "sample.c"
    live_source.parent.mkdir(parents=True)
    original = "void fn_80000000(void) { /* original */ }\n"
    residue = "void fn_80000000(void) { /* generated residue */ }\n"
    live_source.write_text(original)
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)

    def fake_find_unit(function: str, root: pathlib.Path) -> str:
        assert function == "fn_80000000"
        assert root == melee_root
        return "melee/mn/sample"

    def fake_probes(*args, **kwargs) -> list[LifetimeLayoutProbe]:
        assert live_source.read_text() == original
        live_source.write_text(residue)
        return []

    debug_cli._ACTIVE_SOURCE_RESTORES.clear()
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", fake_find_unit)
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_probes,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert live_source.read_text() == original


def test_select_order_search_force_phys_residuals_annotate_top_retained_sources(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    live_source = melee_root / "src" / "melee" / "mn" / "sample.c"
    live_source.parent.mkdir(parents=True)
    live_source.write_text("void fn_80000000(void) { /* seed */ }\n")
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)
    residual_calls: list[dict] = []

    def fake_probes(*args, **kwargs) -> list[LifetimeLayoutProbe]:
        return [
            LifetimeLayoutProbe(
                label="force-phys-hit",
                operator="block-scope",
                description="Synthetic force-phys hit.",
                source_text="void fn_80000000(void) { /* force-phys-hit */ }\n",
            ),
            LifetimeLayoutProbe(
                label="force-phys-miss",
                operator="block-scope",
                description="Synthetic force-phys miss.",
                source_text="void fn_80000000(void) { /* force-phys-miss */ }\n",
            ),
        ]

    def fake_compile(diff_input, **kwargs) -> str:
        source = diff_input.path.read_text()
        if "force-phys-hit" in source:
            return TARGET_ORDER_RIGHT_PHYS
        return TARGET_ORDER_WRONG_PHYS

    def fake_residual_helper(*args, **kwargs) -> dict:
        variant = kwargs.get("variant")
        if variant is None:
            variant = next(
                (arg for arg in args if isinstance(arg, dict) and "label" in arg),
                {},
            )
        label = kwargs.get("label") or variant.get("label")
        source_retained = (
            kwargs.get("source_retained")
            or kwargs.get("retained_source_path")
            or variant.get("source_retained")
        )
        rank = kwargs.get("rank") or variant.get("rank")
        summary = {
            "first_divergence": {
                "kind": "register-choice",
                "candidate_label": label,
                "rank": rank,
                "ig_idx": 32,
            },
            "source_retained": str(source_retained),
        }
        residual_calls.append(summary)
        return summary

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    for helper_name in (
        "_select_order_candidate_residual_first_divergence",
        "_select_order_residual_first_divergence",
        "_select_order_residual_analysis_for_candidate",
    ):
        monkeypatch.setattr(
            debug_cli,
            helper_name,
            fake_residual_helper,
            raising=False,
        )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(live_source),
            "--force-phys",
            "32:29,33:30",
            "--residual-first-divergence-top",
            "2",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    variants = payload["variants"]
    assert [variant["label"] for variant in variants[:2]] == [
        "force-phys-hit",
        "force-phys-miss",
    ]
    for variant in variants[:2]:
        assert variant["status"] == "ok"
        assert variant["source_retained"].endswith(f"{variant['label']}.c")
        residual = variant["residual_analysis"]
        assert residual["first_divergence"]["candidate_label"] == variant["label"]
        assert residual["first_divergence"]["rank"] == variant["rank"]
        assert residual["source_retained"] == variant["source_retained"]
    assert [call["first_divergence"]["candidate_label"] for call in residual_calls] == [
        "force-phys-hit",
        "force-phys-miss",
    ]


def test_select_order_search_force_phys_residuals_include_diagnostic_buckets(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    exact = tmp_path / "exact.txt"
    one_hit = tmp_path / "one-hit.txt"
    miss = tmp_path / "miss.txt"
    baseline.write_text(BASELINE)
    exact.write_text(TARGET_ORDER_RIGHT_PHYS)
    one_hit.write_text(ONE_FORCE_PHYS_HIT)
    miss.write_text(TARGET_ORDER_WRONG_PHYS)
    residual_calls: list[str] = []

    def fake_residual_helper(*args, **kwargs) -> dict:
        variant = kwargs.get("variant")
        if variant is None:
            variant = next(
                (arg for arg in args if isinstance(arg, dict) and "label" in arg),
                {},
            )
        label = variant.get("label")
        residual_calls.append(label)
        return {
            "status": "ok",
            "candidate_label": label,
            "rank": variant.get("rank"),
            "first_divergence": {
                "candidate_label": label,
                "rank": variant.get("rank"),
                "case": "register-choice",
            },
        }

    monkeypatch.setattr(
        debug_cli,
        "_select_order_candidate_residual_first_divergence",
        fake_residual_helper,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"exact:block-scope={exact}",
            "--candidate",
            f"one-hit:block-scope={one_hit}",
            "--candidate",
            f"miss:block-scope={miss}",
            "--force-phys",
            "32:29,33:30",
            "--residual-first-divergence-top",
            "1",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    variants = {variant["label"]: variant for variant in payload["variants"]}
    assert variants["exact"]["residual_analysis"]["candidate_label"] == "exact"
    assert variants["one-hit"]["residual_analysis"]["candidate_label"] == "one-hit"
    buckets = payload["diagnostic_buckets"]
    assert set(buckets) >= {
        "global-top",
        "best-exact-distance",
        "best-one-target-hits",
        "best-opcode-frame-preserving",
        "best-frame-preserving-only",
        "force-phys-hit-32",
        "force-phys-hit-33",
    }
    one_hit_entry = next(
        item for item in buckets["force-phys-hit-33"]
        if item["label"] == "one-hit"
    )
    assert one_hit_entry["probe"] is None
    assert one_hit_entry["source_hunk"] is None
    assert "one-hit" in residual_calls


def test_select_order_diagnostic_buckets_preserve_target_score() -> None:
    target_score = {
        "matched": 4,
        "targeted": 6,
        "virtuals": {
            "33": {"expected": 26, "actual": 26, "matched": True},
            "46": {"expected": 26, "actual": 1, "matched": False},
        },
    }
    variant = {
        "label": "candidate",
        "rank": 1,
        "status": "ok",
        "objective": {
            "target_score": target_score,
            "force_phys_targets": {"33": 26, "46": 26},
            "force_phys_satisfied_count": 1,
            "force_phys_distance": 25,
            "force_phys_mismatches": {
                "46": {"expected": 26, "actual": 1},
            },
            "force_phys_missing": [],
            "frame_delta": 0,
        },
    }

    buckets = debug_cli._select_order_diagnostic_buckets(
        [variant],
        force_phys={33: 26, 46: 26},
        global_top=[variant],
    )

    entry = buckets["global-top"][0]
    assert entry["target_score"]["virtuals"]["46"]["actual"] == 1


def test_select_order_search_force_phys_aliases_compare_normalized_maps(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    candidate = tmp_path / "candidate.txt"
    baseline.write_text(BASELINE)
    candidate.write_text(TARGET_ORDER_RIGHT_PHYS)

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"same-map-different-order:block-scope={candidate}",
            "--force-phys",
            "32:29,33:30",
            "--transform-force-phys",
            "33:30,32:29",
            "--residual-first-divergence-top",
            "0",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["objective"]["force_phys_satisfied"] is True


def test_select_order_search_help_smoke() -> None:
    result = runner.invoke(
        app,
        ["debug", "select-order-search", "--help"],
        env={"COLUMNS": "160"},
    )

    assert result.exit_code == 0
    assert "--target" in result.stdout
    assert "--include-transform-corpus" in result.stdout
    assert "--transform-family" in result.stdout
    assert "--transform-force-phys" in result.stdout
    assert "--directed-force-phys" in result.stdout
    assert "--force-phys" in result.stdout
