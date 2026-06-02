"""Tests for order_metric.py — Phase 0 scorer for the 9ACC directed-search pilot.

Unit tests run without any live compiler (they use a minimal synthetic pcdump
or monkeypatch parse_hook_events).  The @pytest.mark.slow live tests are
excluded from the default suite and must be run explicitly:

    pytest tests/search/directed/test_order_metric.py -m slow -s

The live tests confirm the scorer reads the expected numbers from a real
baseline compile and from a known force-iter-first hit.
"""

from __future__ import annotations

import os
import textwrap
from typing import Optional
from unittest.mock import patch

import pytest

from src.search.directed.order_metric import (
    NINEACC_ORDER_TARGET,
    NINEACC_PHYS_TARGET,
    Score,
    colorgraph_ranks,
    order_distance,
    phys_match,
    score_9acc,
)
from src.mwcc_debug.colorgraph_parser import (
    ColorgraphDecision,
    ColorgraphSection,
    FunctionEvents,
)


# ---------------------------------------------------------------------------
# Minimal synthetic pcdump text builder
# ---------------------------------------------------------------------------

def _make_pcdump(function: str, decisions: list[tuple[int, int, int]], class_id: int = 0) -> str:
    """Build a minimal fake pcdump text with one COLORGRAPH DECISIONS section.

    decisions: list of (iter_idx, ig_idx, assigned_reg)

    The parser requires "Starting function" at column 0 and colorgraph rows
    with leading whitespace.  Build the string directly (no textwrap.dedent)
    so we don't accidentally indent the header lines.
    """
    rows = "\n".join(
        f"  {iter_idx}  {ig_idx}  r{assigned_reg}  0  0  0x0000"
        for iter_idx, ig_idx, assigned_reg in decisions
    )
    lines = [
        f"Starting function {function}",
        f"COLORGRAPH DECISIONS (class={class_id}, result=0, n_nodes={len(decisions)})",
        "iter ig_idx rN degree n_interferers flags",
        rows,
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# colorgraph_ranks — unit tests
# ---------------------------------------------------------------------------


class TestColorgraphRanks:
    def test_returns_1based_positions(self):
        # iter_idx 0 → rank 1, iter_idx 1 → rank 2, iter_idx 2 → rank 3
        pcdump = _make_pcdump("grIceMt_801F9ACC", [
            (0, 32, 3),
            (1, 95, 4),
            (2, 40, 5),  # ig40 at iter_idx=2 → rank 3
            (3, 34, 6),
            (4, 33, 7),  # ig33 at iter_idx=4 → rank 5
        ])
        ranks = colorgraph_ranks(pcdump, "grIceMt_801F9ACC")
        assert ranks[40] == 3
        assert ranks[33] == 5

    def test_returns_empty_for_unknown_function(self):
        pcdump = _make_pcdump("grIceMt_801F9ACC", [(0, 33, 27)])
        ranks = colorgraph_ranks(pcdump, "nonexistent_fn")
        assert ranks == {}

    def test_returns_empty_for_wrong_class(self):
        pcdump = _make_pcdump("grIceMt_801F9ACC", [(0, 33, 27)], class_id=0)
        ranks = colorgraph_ranks(pcdump, "grIceMt_801F9ACC", class_id=1)
        assert ranks == {}

    def test_uses_last_section_when_multiple(self):
        # Two COLORGRAPH DECISIONS sections — the scorer should use the last one.
        pcdump = "\n".join([
            "Starting function grIceMt_801F9ACC",
            "COLORGRAPH DECISIONS (class=0, result=0, n_nodes=1)",
            "iter ig_idx rN degree n_interferers flags",
            "  0  33  r28  0  0  0x0000",
            "COLORGRAPH DECISIONS (class=0, result=0, n_nodes=1)",
            "iter ig_idx rN degree n_interferers flags",
            "  0  33  r27  0  0  0x0000",
            "",
        ])
        ranks = colorgraph_ranks(pcdump, "grIceMt_801F9ACC")
        # Last section: iter_idx=0 → rank=1, assigned_reg=27 (rank is 1)
        assert ranks[33] == 1

    def test_all_ranks_present_in_synthetic_baseline(self):
        # Synthetic baseline: ig33@rank-3, ig40@rank-5 (matches known 9ACC baseline state)
        pcdump = _make_pcdump("grIceMt_801F9ACC", [
            (0, 32, 3),
            (1, 95, 4),
            (2, 33, 29),  # ig33 at iter_idx=2 → rank 3
            (3, 34, 6),
            (4, 40, 27),  # ig40 at iter_idx=4 → rank 5
        ])
        ranks = colorgraph_ranks(pcdump, "grIceMt_801F9ACC")
        assert ranks[33] == 3
        assert ranks[40] == 5


# ---------------------------------------------------------------------------
# order_distance — unit tests
# ---------------------------------------------------------------------------


class TestOrderDistance:
    def test_baseline_distance_is_4(self):
        # Baseline: ig33@rank-3, ig40@rank-5.  Target: ig40@3, ig33@5.
        # |3 - 5| + |5 - 3| = 2 + 2 = 4
        ranks = {33: 3, 40: 5, 32: 1, 95: 2, 34: 4}
        result = order_distance(ranks, NINEACC_ORDER_TARGET)
        assert result == 4

    def test_target_hit_is_zero(self):
        # Exactly at target: ig40@3, ig33@5.
        ranks = {33: 5, 40: 3, 32: 1, 95: 2, 34: 4}
        result = order_distance(ranks, NINEACC_ORDER_TARGET)
        assert result == 0

    def test_missing_ig_adds_penalty(self):
        # Only ig33 present, ig40 missing → penalty 99 for ig40
        ranks = {33: 5}
        result = order_distance(ranks, NINEACC_ORDER_TARGET)
        assert result == 99  # ig40 missing: +99; ig33 at target (5==5): +0

    def test_both_missing_adds_double_penalty(self):
        result = order_distance({}, NINEACC_ORDER_TARGET)
        assert result == 99 + 99

    def test_partial_distance(self):
        # ig40 at rank 4 (off by 1 from target 3), ig33 at rank 5 (on target)
        ranks = {40: 4, 33: 5}
        result = order_distance(ranks, NINEACC_ORDER_TARGET)
        assert result == 1  # |4-3| + |5-5| = 1

    def test_empty_target(self):
        ranks = {33: 3, 40: 5}
        result = order_distance(ranks, {})
        assert result == 0

    def test_direct_dicts_baseline_vs_target(self):
        # Explicit check from task spec:
        # order_distance({33:3, 40:5, ...}, {40:3, 33:5}) == 4 (baseline)
        # order_distance({40:3, 33:5}, {40:3, 33:5}) == 0 (target)
        assert order_distance({33: 3, 40: 5}, {40: 3, 33: 5}) == 4
        assert order_distance({40: 3, 33: 5}, {40: 3, 33: 5}) == 0


# ---------------------------------------------------------------------------
# phys_match — unit tests
# ---------------------------------------------------------------------------


class TestPhysMatch:
    def test_baseline_matches_zero(self):
        # Baseline: ig33→r29 (wrong, want r27), ig40→r27 (wrong, want r29)
        pcdump = _make_pcdump("grIceMt_801F9ACC", [
            (2, 33, 29),  # ig33 gets r29, but target is r27
            (4, 40, 27),  # ig40 gets r27, but target is r29
        ])
        matched, total = phys_match(pcdump, "grIceMt_801F9ACC", NINEACC_PHYS_TARGET)
        assert matched == 0
        assert total == 2

    def test_force_hit_matches_both(self):
        # Force-hit: ig33→r27 (correct), ig40→r29 (correct)
        pcdump = _make_pcdump("grIceMt_801F9ACC", [
            (2, 40, 29),  # ig40 gets r29 ✓
            (4, 33, 27),  # ig33 gets r27 ✓
        ])
        matched, total = phys_match(pcdump, "grIceMt_801F9ACC", NINEACC_PHYS_TARGET)
        assert matched == 2
        assert total == 2

    def test_one_of_two_matched(self):
        pcdump = _make_pcdump("grIceMt_801F9ACC", [
            (2, 33, 27),  # ig33→r27 ✓
            (4, 40, 27),  # ig40→r27 ✗ (want r29)
        ])
        matched, total = phys_match(pcdump, "grIceMt_801F9ACC", NINEACC_PHYS_TARGET)
        assert matched == 1
        assert total == 2

    def test_unknown_function_returns_zero(self):
        pcdump = _make_pcdump("grIceMt_801F9ACC", [(0, 33, 27)])
        matched, total = phys_match(pcdump, "other_fn", NINEACC_PHYS_TARGET)
        assert matched == 0
        assert total == 2

    def test_missing_ig_counts_as_miss(self):
        # Only ig33 in pcdump, ig40 absent
        pcdump = _make_pcdump("grIceMt_801F9ACC", [(0, 33, 27)])
        matched, total = phys_match(pcdump, "grIceMt_801F9ACC", NINEACC_PHYS_TARGET)
        assert matched == 1  # ig33 matched
        assert total == 2


# ---------------------------------------------------------------------------
# Score dataclass
# ---------------------------------------------------------------------------


class TestScoreDataclass:
    def test_baseline_score_shape(self):
        pcdump = _make_pcdump("grIceMt_801F9ACC", [
            (0, 32, 3),
            (1, 95, 4),
            (2, 33, 29),  # ig33 rank=3, assigned r29 (want r27)
            (3, 34, 6),
            (4, 40, 27),  # ig40 rank=5, assigned r27 (want r29)
        ])
        s = score_9acc(pcdump)
        assert s.order_distance == 4
        assert s.phys_matched == 0
        assert s.phys_total == 2
        assert s.rank33 == 3
        assert s.rank40 == 5
        assert s.missing_target_nodes == frozenset()

    def test_target_score_shape(self):
        pcdump = _make_pcdump("grIceMt_801F9ACC", [
            (0, 32, 3),
            (1, 95, 4),
            (2, 40, 29),  # ig40 rank=3, assigned r29 ✓
            (3, 34, 6),
            (4, 33, 27),  # ig33 rank=5, assigned r27 ✓
        ])
        s = score_9acc(pcdump)
        assert s.order_distance == 0
        assert s.phys_matched == 2
        assert s.phys_total == 2
        assert s.rank33 == 5
        assert s.rank40 == 3
        assert s.missing_target_nodes == frozenset()

    def test_missing_nodes_reported(self):
        pcdump = _make_pcdump("grIceMt_801F9ACC", [(0, 32, 3)])
        s = score_9acc(pcdump)
        assert {33, 40} <= s.missing_target_nodes
        assert s.rank33 is None
        assert s.rank40 is None


# ---------------------------------------------------------------------------
# Live verification tests (marked slow; excluded from default suite)
# ---------------------------------------------------------------------------

_LIVE_GUARD = pytest.mark.skipif(
    not os.environ.get("LIVE_9ACC_TESTS"),
    reason="Set LIVE_9ACC_TESTS=1 to run live compiler tests",
)


@pytest.mark.slow
@_LIVE_GUARD
def test_live_baseline_order_distance_is_4(tmp_path):
    """Compile the baseline gricemt.c and confirm scorer reads distance=4.

    Expected:
        order_distance == 4
        phys_match == (0, 2)
        rank33 == 3
        rank40 == 5
    """
    import subprocess

    dump_path = tmp_path / "9acc_base.txt"
    result = subprocess.run(
        [
            "melee-agent", "debug", "dump", "local",
            "src/melee/gr/gricemt.c",
            "--function", "grIceMt_801F9ACC",
            "--output", str(dump_path),
            "--no-cache-sync",
        ],
        cwd="/Users/mike/code/melee",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"baseline compile failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )

    pcdump_text = dump_path.read_text(encoding="utf-8")
    ranks = colorgraph_ranks(pcdump_text, "grIceMt_801F9ACC")
    od = order_distance(ranks, NINEACC_ORDER_TARGET)
    matched, total = phys_match(pcdump_text, "grIceMt_801F9ACC", NINEACC_PHYS_TARGET)

    print(f"\n[LIVE BASELINE] ranks={ranks}")
    print(f"  order_distance={od}  phys=({matched},{total})")
    print(f"  rank33={ranks.get(33)}  rank40={ranks.get(40)}")

    assert od == 4, f"Expected baseline order_distance=4, got {od}"
    assert (matched, total) == (0, 2), f"Expected phys=(0,2), got ({matched},{total})"
    assert ranks.get(33) == 3, f"Expected rank33=3, got {ranks.get(33)}"
    assert ranks.get(40) == 5, f"Expected rank40=5, got {ranks.get(40)}"


@pytest.mark.slow
@_LIVE_GUARD
def test_live_force_iter_first_distance_is_0(tmp_path):
    """Compile with force-iter-first and confirm scorer reads distance=0.

    Expected:
        order_distance == 0
        phys_match == (2, 2)
        rank40 == 3
        rank33 == 5
    """
    import subprocess

    dump_path = tmp_path / "9acc_force.txt"
    result = subprocess.run(
        [
            "melee-agent", "debug", "dump", "local",
            "src/melee/gr/gricemt.c",
            "--function", "grIceMt_801F9ACC",
            "--output", str(dump_path),
            "--no-cache-sync",
            "--force-iter-first", "32,95,40,34,33",
            "--force-iter-first-class", "0",
            "--force-iter-first-fn", "grIceMt_801F9ACC",
        ],
        cwd="/Users/mike/code/melee",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"force compile failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )

    pcdump_text = dump_path.read_text(encoding="utf-8")
    ranks = colorgraph_ranks(pcdump_text, "grIceMt_801F9ACC")
    od = order_distance(ranks, NINEACC_ORDER_TARGET)
    matched, total = phys_match(pcdump_text, "grIceMt_801F9ACC", NINEACC_PHYS_TARGET)

    print(f"\n[LIVE FORCE-HIT] ranks={ranks}")
    print(f"  order_distance={od}  phys=({matched},{total})")
    print(f"  rank40={ranks.get(40)}  rank33={ranks.get(33)}")

    assert od == 0, f"Expected force-hit order_distance=0, got {od}"
    assert (matched, total) == (2, 2), f"Expected phys=(2,2), got ({matched},{total})"
    assert ranks.get(40) == 3, f"Expected rank40=3, got {ranks.get(40)}"
    assert ranks.get(33) == 5, f"Expected rank33=5, got {ranks.get(33)}"
