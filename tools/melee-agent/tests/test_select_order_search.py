"""Tests for select-order-directed source-shape search ranking."""

from __future__ import annotations

import json
import pathlib
import signal
import subprocess
import textwrap

import pytest
from typer.testing import CliRunner

import src.cli.debug as debug_cli
from src.cli import app
from src.mwcc_debug.cache import cache_path
from src.mwcc_debug.pressure_explorer import LifetimeLayoutProbe
from src.mwcc_debug.select_order_search import (
    rank_select_order_candidates,
    render_select_order_variant,
    score_select_order_candidate,
)

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
    )

    assert attrs[32].name == "dst_iter"
    assert 44 not in attrs
    assert captured["kwargs"]["virtuals"] == (32, 44)
    assert captured["kwargs"]["reg_class"] == "gpr"


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
        max_probes=4,
    )

    assert result is probes
    assert captured["alias_function"] == "mnDiagram_DrawCellNumber"
    assert captured["function_aliases"] == ("fn_80000000",)
    assert captured["force_phys"] == {33: 28}
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
    assert payload["auto_transform_families"] == ["coloring_register_steering"]
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
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", ""),
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

    def fake_lock(root: pathlib.Path, *, label: str = ""):
        assert root == melee_root
        assert label == "source-scoring"
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

    def fake_cleanup(*args, **kwargs):
        assert lock_held is True
        assert target.read_text() == original
        events.append("cleanup")
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_acquire_checkdiff_repo_lock", fake_lock)
    monkeypatch.setattr(debug_cli, "_run_ninja_with_no_diag_retry", fake_ninja)
    monkeypatch.setattr(debug_cli, "_refresh_match_pct_after_successful_build", fake_refresh)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_cleanup)

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
