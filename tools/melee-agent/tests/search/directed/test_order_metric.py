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
    CandidateScore,
    Score,
    colorgraph_ranks,
    order_distance,
    phys_match,
    score_9acc,
    score_candidate_reanchored,
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
# score_candidate_reanchored — unit tests
# ---------------------------------------------------------------------------

def _make_role_descriptor(ig_idx, first_def_sig, is_param, var_name, assigned_reg,
                           use_site_multiset=None, spilled=False):
    """Helper to build minimal RoleDescriptor for reanchor tests."""
    from src.mwcc_debug.role_descriptor import RoleDescriptor
    return RoleDescriptor(
        ig_idx=ig_idx,
        first_def_sig=first_def_sig,
        use_site_multiset=use_site_multiset or (),
        is_param=is_param,
        var_name=var_name,
        var_confidence="high" if var_name else None,
        assigned_reg=assigned_reg,
        live_range=(0, 100),
        use_count=2,
        spilled=spilled,
    )


def _ref_descs_9acc_baseline():
    """Minimal ref_descs matching the 9ACC baseline identity (ig33=y param, ig40=gp local)."""
    return {
        33: _make_role_descriptor(33, "mr r#,r#", True, "y", assigned_reg=29),
        40: _make_role_descriptor(40, "li r#,0", False, "gp", assigned_reg=27),
    }


class TestScoreCandidateReanchored:
    """Tests for score_candidate_reanchored using synthetic pcdumps + descriptors."""

    def _pcdump_with(self, decisions):
        """Build synthetic pcdump: decisions = [(iter_idx, ig_idx, assigned_reg)]."""
        return _make_pcdump("grIceMt_801F9ACC", decisions)

    def test_baseline_identity_stable_order_distance_kendall_1(self):
        # Candidate has same ig numbering as ref: ig33@rank3, ig40@rank5 (baseline swap)
        pcdump = self._pcdump_with([
            (0, 32, 3),
            (1, 95, 4),
            (2, 33, 29),  # ig33 at rank=3, assigned r29
            (3, 34, 6),
            (4, 40, 27),  # ig40 at rank=5, assigned r27
        ])
        ref = _ref_descs_9acc_baseline()
        # Add identical candidate descs for 33 and 40 so reanchor works
        from src.mwcc_debug.role_descriptor import RoleDescriptor
        # We need to provide full cand_descs via patching build_descriptors
        # Use the same ref_descs as cand_descs (identity case)
        # Call directly with the helper's pcdump which has the right structure
        # but build_descriptors would fail on a synthetic pcdump
        # Instead, patch build_descriptors to return the ref_descs
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile") as mock_compile_cls:
            mock_compile = mock_compile_cls.from_text.return_value
            with patch("src.search.directed.order_metric.build_descriptors") as mock_bd:
                mock_bd.return_value = ref  # candidate has same descs → stable identity
                result = score_candidate_reanchored(pcdump, ref)

        assert result.valid is True
        assert result.invalid_reason is None
        assert result.rank33 == 3
        assert result.rank40 == 5
        # Kendall: the single (ig33, ig40) pair is inverted vs target -> 1.
        # (The OLD sum-of-deltas form scored this 4; that form still lives in
        # the standalone order_distance/score_9acc, tested separately.)
        assert result.order_distance == 1
        assert result.phys_matched == 0  # both are swapped

    def test_target_identity_stable_order_distance_0(self):
        # Candidate has the TARGET coloring: ig40@rank3 (r29), ig33@rank5 (r27)
        pcdump = self._pcdump_with([
            (0, 32, 3),
            (1, 95, 4),
            (2, 40, 29),  # ig40 at rank=3, assigned r29 ✓
            (3, 34, 6),
            (4, 33, 27),  # ig33 at rank=5, assigned r27 ✓
        ])
        ref = _ref_descs_9acc_baseline()
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile") as mock_compile_cls:
            mock_compile = mock_compile_cls.from_text.return_value
            with patch("src.search.directed.order_metric.build_descriptors") as mock_bd:
                mock_bd.return_value = ref
                result = score_candidate_reanchored(pcdump, ref)

        assert result.valid is True
        assert result.rank33 == 5
        assert result.rank40 == 3
        assert result.order_distance == 0
        assert result.phys_matched == 2

    def test_identity_lost_when_role_not_reanchored(self):
        # Cand descs omit ig33 entirely → reanchor cannot match it → invalid
        pcdump = self._pcdump_with([
            (0, 40, 27),  # ig40 present, ig33 absent
        ])
        ref = _ref_descs_9acc_baseline()
        # Candidate descs: only ig40, ig33 gone
        cand_descs_only40 = {
            40: _make_role_descriptor(40, "li r#,0", False, "gp", assigned_reg=27),
        }
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile") as mock_compile_cls:
            mock_compile = mock_compile_cls.from_text.return_value
            with patch("src.search.directed.order_metric.build_descriptors") as mock_bd:
                mock_bd.return_value = cand_descs_only40
                result = score_candidate_reanchored(pcdump, ref)

        assert result.valid is False
        assert result.invalid_reason is not None
        # §3.3 (T5): all lost-target-role cases collapse to the single unified
        # reason "target_role_lost" (the old "identity_lost: orig_ig 33" string
        # was replaced when the validity rule was generalized).
        assert result.invalid_reason == "target_role_lost"

    def test_compile_parse_failure_returns_invalid(self):
        # If Compile.from_text raises, result is invalid
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile") as mock_compile_cls:
            mock_compile_cls.from_text.side_effect = ValueError("not found")
            result = score_candidate_reanchored("bad pcdump text", _ref_descs_9acc_baseline())

        assert result.valid is False
        assert "compile_parse_failed" in (result.invalid_reason or "")

    def test_ig_renumbered_to_new_stable_slot(self):
        # Simulate mutation that renumbers ig33 -> ig50 and ig40 -> ig51.
        # ref_descs has ig33/ig40; cand_descs has ig50/ig51 with SAME descriptors.
        ref = _ref_descs_9acc_baseline()
        cand_descs_renumbered = {
            50: _make_role_descriptor(50, "mr r#,r#", True, "y", assigned_reg=27),  # was ig33
            51: _make_role_descriptor(51, "li r#,0", False, "gp", assigned_reg=29),  # was ig40
        }
        # Pcdump uses NEW ig numbers: ig50@rank5 (r27), ig51@rank3 (r29) → target
        pcdump = self._pcdump_with([
            (0, 32, 3),
            (1, 95, 4),
            (2, 51, 29),  # ig51 (=orig ig40=gp) at rank=3, r29 ✓
            (3, 34, 6),
            (4, 50, 27),  # ig50 (=orig ig33=y) at rank=5, r27 ✓
        ])
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile") as mock_compile_cls:
            mock_compile = mock_compile_cls.from_text.return_value
            with patch("src.search.directed.order_metric.build_descriptors") as mock_bd:
                mock_bd.return_value = cand_descs_renumbered
                result = score_candidate_reanchored(pcdump, ref)

        # Reanchor should find ig50→orig33 and ig51→orig40 via descriptor match.
        # If it does, rank33=5 (for ig50), rank40=3 (for ig51), od=0, phys=2
        assert result.valid is True, f"Expected valid but got: {result.invalid_reason}"
        assert result.order_distance == 0
        assert result.phys_matched == 2


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


# ---------------------------------------------------------------------------
# Generalized score_candidate_reanchored (order-distance directed search, T5)
# ---------------------------------------------------------------------------

class TestGeneralizedCandidateScore:
    def _pc(self, decisions):
        return _make_pcdump("mnDiagram_OnFrame", decisions)

    def _three_role_ref(self):
        return {
            28: _make_role_descriptor(28, "mr r#,r#", True, "a", assigned_reg=29),
            29: _make_role_descriptor(29, "li r#,0", False, "b", assigned_reg=28),
            31: _make_role_descriptor(31, "addi r#,r#,0", False, "c", assigned_reg=30),
        }

    def test_arbitrary_roles_kendall_zero_when_in_target_order(self):
        # Target order: ig28 earlier (rank 5) than ig29 (rank 7). Candidate matches.
        pc = self._pc([(4, 28, 29), (6, 29, 28)])  # rank5=iter4, rank7=iter6
        ref = {
            28: _make_role_descriptor(28, "mr r#,r#", True, "a", assigned_reg=29),
            29: _make_role_descriptor(29, "li r#,0", False, "b", assigned_reg=28),
        }
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile"):
            with patch("src.search.directed.order_metric.build_descriptors") as bd:
                bd.return_value = ref
                result = score_candidate_reanchored(
                    pc, ref, function="mnDiagram_OnFrame",
                    order_target={28: 5, 29: 7}, phys_target={28: 29, 29: 28},
                )
        assert result.valid is True
        assert result.ranks_by_role == {28: 5, 29: 7}
        assert result.order_distance == 0
        assert result.coverage == 1.0

    def test_kendall_one_when_pair_inverted(self):
        # Candidate has ig28 LATER than ig29 -> one inversion vs target.
        pc = self._pc([(6, 28, 29), (4, 29, 28)])
        ref = {
            28: _make_role_descriptor(28, "mr r#,r#", True, "a", assigned_reg=29),
            29: _make_role_descriptor(29, "li r#,0", False, "b", assigned_reg=28),
        }
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile"):
            with patch("src.search.directed.order_metric.build_descriptors") as bd:
                bd.return_value = ref
                result = score_candidate_reanchored(
                    pc, ref, function="mnDiagram_OnFrame",
                    order_target={28: 5, 29: 7}, phys_target={28: 29, 29: 28},
                )
        assert result.valid is True
        assert result.order_distance == 1

    def test_target_role_lost_is_invalid_not_zero(self):
        # §3.3 hole: a candidate that LOSES a target role must be invalid, never 0.
        ref = self._three_role_ref()
        cand_only_two = {
            28: _make_role_descriptor(28, "mr r#,r#", True, "a", assigned_reg=29),
            29: _make_role_descriptor(29, "li r#,0", False, "b", assigned_reg=28),
        }  # ig31 GONE
        pc = self._pc([(4, 28, 29), (6, 29, 28)])
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile"):
            with patch("src.search.directed.order_metric.build_descriptors") as bd:
                bd.return_value = cand_only_two
                result = score_candidate_reanchored(
                    pc, ref, function="mnDiagram_OnFrame",
                    order_target={28: 5, 29: 7, 31: 9}, phys_target={28: 29, 29: 28, 31: 30},
                )
        assert result.valid is False
        assert result.invalid_reason == "target_role_lost"
        assert result.order_distance is None

    def test_fewer_than_two_anchored_is_invalid(self):
        ref = {28: _make_role_descriptor(28, "mr r#,r#", True, "a", assigned_reg=29)}
        pc = self._pc([(4, 28, 29)])
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile"):
            with patch("src.search.directed.order_metric.build_descriptors") as bd:
                bd.return_value = ref
                result = score_candidate_reanchored(
                    pc, ref, function="mnDiagram_OnFrame",
                    order_target={28: 5}, phys_target={28: 29},
                )
        assert result.valid is False
        assert result.invalid_reason == "target_role_lost"

    def test_legacy_rank33_rank40_shim_still_populated(self):
        # The 9ACC two-role path keeps the back-compat rank33/rank40 fields.
        pc = _make_pcdump("grIceMt_801F9ACC", [(2, 40, 29), (4, 33, 27)])
        ref = _ref_descs_9acc_baseline()
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile"):
            with patch("src.search.directed.order_metric.build_descriptors") as bd:
                bd.return_value = ref
                result = score_candidate_reanchored(pc, ref)
        assert result.valid is True
        assert result.rank33 == 5
        assert result.rank40 == 3
        assert result.ranks_by_role == {33: 5, 40: 3}
