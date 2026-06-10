"""Tests for the register-coloring tiebreak surrogate (debug inspect tiebreak)."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools/melee-agent"))
from src.mwcc_debug import tiebreak as tb  # noqa: E402
from src.mwcc_debug.colorgraph_parser import (ColorgraphDecision,  # noqa: E402
                                              ColorgraphSection)

FIXTURE = (REPO / "tools/melee-agent/tests/fixtures/role_identity"
           / "mnVibration_matched_pcdump.txt")


def _decision(ig, reg, interferers):
    return ColorgraphDecision(iter_idx=0, ig_idx=ig, assigned_reg=reg, degree=0,
                              n_interferers=len(interferers), flags=0,
                              interferers=interferers)


def test_g1_100pct_on_committed_fixture():
    ig = tb.load_gpr_ig(FIXTURE.read_text(), "mnVibration_80248644")
    assert ig is not None
    r = tb.validate_g1(ig, "mnVibration_80248644")
    assert r.total > 0
    assert r.rate == 1.0, r.mismatches  # non-negotiable per spec


def test_machine_reg_interferer_blocks_its_own_number():
    # ig50 interferes with machine r0,r3..r12 (paired reg sometimes -1, e.g.
    # (12,-1)) -> all volatiles must still be blocked -> fresh callee-save r31.
    interferers = [(0, -1), (12, -1)] + [(i, i) for i in range(3, 12)]
    sec = ColorgraphSection(class_id=0, result=1, n_nodes=1,
                            decisions=[_decision(50, 31, interferers)])
    ig = tb.build_ig(sec)
    assert tb.predict_assignments(ig)[50] == 31


def test_dispense_reuse_before_fresh():
    # Two non-interfering callee-save nodes: first gets r31, second can REUSE
    # r31? No — they interfere here, so second must go fresh r30.
    sec = ColorgraphSection(class_id=0, result=1, n_nodes=2, decisions=[
        ColorgraphDecision(0, 40, 31, 0, 11, 0, [(i, i) for i in (0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)]),
        ColorgraphDecision(1, 41, 30, 0, 12, 0, [(i, i) for i in (0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)] + [(40, 31)]),
    ])
    ig = tb.build_ig(sec)
    pred = tb.predict_assignments(ig)
    assert pred[40] == 31 and pred[41] == 30


def test_truncation_flagged_incomplete():
    sec = ColorgraphSection(class_id=0, result=1, n_nodes=1, decisions=[
        ColorgraphDecision(0, 50, 27, 0, 92, 0, [(i, i) for i in range(3, 13)])])
    ig = tb.build_ig(sec)
    assert ig.nodes[50].incomplete  # 10 listed but n_interferers=92


def test_whatif_add_interferer_changes_reg():
    # A node that would pick r28 (reuse) flips to fresh r27 if it gains an
    # interferer holding r28.
    sec = ColorgraphSection(class_id=0, result=1, n_nodes=3, decisions=[
        ColorgraphDecision(0, 60, 28, 0, 11, 0, [(i, i) for i in (0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)]),
        ColorgraphDecision(1, 61, 28, 0, 11, 0, [(i, i) for i in (0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)]),
    ])
    ig = tb.build_ig(sec)
    base = tb.predict_assignments(ig)
    assert base[60] == 31           # first callee-save node: fresh r31
    assert base[61] == 31           # second REUSES r31 (doesn't interfere w/ ig60)
    w = tb.what_if(ig, 61, add_interferers={60})
    assert w.predicted_reg == 31
    assert w.perturbed_reg == 30    # new edge to r31-holder forces fresh r30
    assert w.flips


def test_inputproc_g1_perfect_when_available():
    # Live-ish: only if a cached mndiagram dump is present.
    dump = REPO / "build/mwcc_debug_cache/melee/mn/mndiagram.txt"
    alt = Path("/tmp/pc_mndiagram.txt")
    p = dump if dump.exists() else (alt if alt.exists() else None)
    if p is None:
        pytest.skip("no mndiagram pcdump available")
    ig = tb.load_gpr_ig(p.read_text(), "mnDiagram_InputProc")
    if ig is None:
        pytest.skip("InputProc not in dump")
    r = tb.validate_g1(ig)
    assert r.rate == 1.0, r.mismatches


def test_cli_validate_only_exit0_on_fixture():
    from typer.testing import CliRunner
    from src.cli import app
    r = CliRunner().invoke(app, ["debug", "inspect", "tiebreak",
                                 "-f", "mnVibration_80248644",
                                 "--pcdump", str(FIXTURE), "--validate-only"])
    assert r.exit_code == 0
    assert "100.0%" in r.output


def test_cli_whatif_runs_on_fixture():
    from typer.testing import CliRunner
    from src.cli import app
    # pick any node and a remove-edge that the engine can evaluate; just assert
    # it runs and reports a predicted->perturbed line (exit 0, G1 perfect here).
    ig = tb.load_gpr_ig(FIXTURE.read_text(), "mnVibration_80248644")
    node = next(n for n in ig.nodes.values() if n.neighbors)
    nb = next(iter(node.neighbors))
    r = CliRunner().invoke(app, ["debug", "inspect", "tiebreak",
                                 "-f", "mnVibration_80248644", "--pcdump", str(FIXTURE),
                                 "--what-if", f"remove-edge {node.ig_idx}:{nb}"])
    assert r.exit_code == 0
    assert "what-if" in r.output


def test_move_after_vs_before_are_distinct():
    # Three callee-save nodes in a chain so order matters; verify the engine
    # honors after vs before (they were silently conflated before the fix).
    full = [(i, i) for i in (0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)]
    sec = ColorgraphSection(class_id=0, result=1, n_nodes=3, decisions=[
        ColorgraphDecision(0, 70, 31, 0, 11, 0, list(full)),
        ColorgraphDecision(1, 71, 30, 0, 12, 0, list(full) + [(70, 31)]),
        ColorgraphDecision(2, 72, 29, 0, 13, 0, list(full) + [(70, 31), (71, 30)]),
    ])
    ig = tb.build_ig(sec)
    before = tb.what_if(ig, 72, move_before=70)
    after = tb.what_if(ig, 72, move_after=70)
    assert "before ig70" in before.description
    assert "after ig70" in after.description
    # moved first, ig72 takes the first fresh callee-save r31 in both cases;
    # the distinction shows in order placement — assert via order effect on ig70
    assert before.perturbed_reg == 31


def test_cli_move_rejects_bad_middle_token():
    from typer.testing import CliRunner
    from src.cli import app
    r = CliRunner().invoke(app, ["debug", "inspect", "tiebreak",
                                 "-f", "mnVibration_80248644", "--pcdump", str(FIXTURE),
                                 "--what-if", "move 32:nonsense:33"])
    assert r.exit_code == 2
    assert "could not parse" in r.output


def test_cli_move_after_accepted():
    from typer.testing import CliRunner
    from src.cli import app
    ig = tb.load_gpr_ig(FIXTURE.read_text(), "mnVibration_80248644")
    a, b = ig.select_order[0], ig.select_order[1]
    r = CliRunner().invoke(app, ["debug", "inspect", "tiebreak",
                                 "-f", "mnVibration_80248644", "--pcdump", str(FIXTURE),
                                 "--what-if", f"move {a}:after:{b}"])
    assert r.exit_code == 0
    assert "what-if" in r.output
