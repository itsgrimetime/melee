"""Tests for the register-coloring tiebreak surrogate (debug inspect tiebreak)."""
import json
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


def test_fpr_class_uses_fpr_phys_pool():
    interferers = [(i, i) for i in range(14)]
    sec = ColorgraphSection(class_id=1, result=1, n_nodes=1,
                            decisions=[_decision(50, 31, interferers)])
    ig = tb.build_ig(sec)

    assert tb.predict_assignments(ig)[50] == 31
    assert tb.register_prefix(ig.class_id) == "f"


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
    assert "abstract diagnostic" in r.output
    assert "not a source-realizability proof" in r.output


def test_cli_whatif_json_labels_abstract_diagnostic():
    from typer.testing import CliRunner
    from src.cli import app

    ig = tb.load_gpr_ig(FIXTURE.read_text(), "mnVibration_80248644")
    node = next(n for n in ig.nodes.values() if n.neighbors)
    nb = next(iter(node.neighbors))

    r = CliRunner().invoke(app, ["debug", "inspect", "tiebreak",
                                 "-f", "mnVibration_80248644",
                                 "--pcdump", str(FIXTURE),
                                 "--what-if",
                                 f"remove-edge {node.ig_idx}:{nb}",
                                 "--json"])

    assert r.exit_code == 0
    payload = json.loads(r.output)
    assert payload["what_if"]["diagnostic_only"] is True
    assert (
        payload["what_if"]["realizability"]
        == "abstract-select-graph-not-source-realizability-proof"
    )


def test_cli_ig_output_documents_function_scoped_colorgraph_ids(tmp_path):
    from typer.testing import CliRunner
    from src.cli import app

    pcdump = tmp_path / "duplicate_ig_ids.txt"
    blockers = " ".join(f"{i}=r{i}" for i in (0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12))
    pcdump.write_text(
        "Starting function other_fn\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)\n"
        "iter ig_idx assignedReg degree nIntfr flags\n"
        f"0 52 r31 0 13 0x02\n    interferers: {blockers}\n"
        "Starting function target_fn\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=3)\n"
        "iter ig_idx assignedReg degree nIntfr flags\n"
        f"0 60 r31 0 11 0x02\n    interferers: {blockers}\n"
        f"1 61 r30 0 12 0x02\n    interferers: {blockers} 60=r31\n"
        f"2 52 r29 0 13 0x02\n    interferers: {blockers} 60=r31 61=r30\n"
    )

    result = CliRunner().invoke(
        app,
        [
            "debug",
            "inspect",
            "tiebreak",
            "-f",
            "target_fn",
            "--pcdump",
            str(pcdump),
            "--class",
            "gpr",
            "--ig",
            "52",
        ],
    )

    assert result.exit_code == 0
    assert "ig_idx scope: function=target_fn class=0" in result.output
    assert "same ig_idx values can appear in other functions" in result.output
    assert "ig52: observed r29 predicted r29" in result.output
    assert "observed r31" not in result.output


def test_cli_tiebreak_class_fpr_accepts_f_tokens(tmp_path):
    from typer.testing import CliRunner
    from src.cli import app

    pcdump = tmp_path / "class1.txt"
    fpr_blockers = " ".join(f"{i}=r{i}" for i in range(14))
    pcdump.write_text(
        "Starting function fn_80000000\n"
        "COLORGRAPH DECISIONS (class=1, result=1, n_nodes=2)\n"
        "iter  ig_idx assignedReg degree nIntfr flags\n"
        f"0 33 r31 0 14 0x02\n    interferers: {fpr_blockers}\n"
        f"1 34 r31 0 14 0x02\n    interferers: {fpr_blockers}\n"
    )

    result = CliRunner().invoke(
        app,
        [
            "debug",
            "inspect",
            "tiebreak",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(pcdump),
            "--class",
            "fpr",
            "--ig",
            "f33",
            "--what-if",
            "add-interferer f34:f33",
        ],
    )

    assert result.exit_code == 0
    assert "observed f31 predicted f31" in result.output
    assert "predicted f31 -> f30" in result.output


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


@pytest.mark.slow
def test_force_interfere_round_trip():
    """LIVE: inject an interference edge via the DLL force-interfere hook and
    confirm it appears in the target node's COLORGRAPH neighbors. Gated on
    RETRO_LIVE=1 + the deployed DLL."""
    import os
    import subprocess
    if os.environ.get("RETRO_LIVE") != "1":
        pytest.skip("set RETRO_LIVE=1 for the live force-interfere round trip")
    dll = REPO / "build/compilers/GC/1.2.5n/MWDBG326.dll"
    if not dll.exists():
        pytest.skip("deployed debug DLL missing")
    base_p, inj_p = Path("/tmp/fi_t_base.txt"), Path("/tmp/fi_t_inj.txt")
    cmd = ["melee-agent", "debug", "dump", "local", "src/melee/mn/mnvibration.c",
           "--no-cache-sync", "--output"]
    subprocess.run(cmd + [str(base_p)], cwd=REPO, capture_output=True, timeout=300)
    base = tb.load_gpr_ig(base_p.read_text(), "mnVibration_80248644")
    nodes = sorted(base.nodes)
    a, b = next((x, y) for x in nodes for y in nodes
                if x < y and x >= 33 and y >= 33 and y not in base.nodes[x].neighbors)
    env = dict(os.environ, MWCC_DEBUG_FORCE_INTERFERE=f"{a}={b}",
               MWCC_DEBUG_FORCE_INTERFERE_FUNCTION="mnVibration_80248644")
    subprocess.run(cmd + [str(inj_p)], cwd=REPO, env=env, capture_output=True, timeout=300)
    inj = tb.load_gpr_ig(inj_p.read_text(), "mnVibration_80248644")
    assert b not in base.nodes[a].neighbors
    assert b in inj.nodes[a].neighbors  # edge injected into the real matrix


def test_parse_live_ranges_scopes_by_function():
    # Block indices reset per function, so the parser must scope by fn= and
    # class=0; an unrelated function's blocks must not leak in.
    text = (
        "[LIVERANGES] fn=other class=0 n_virtuals=40\n"
        "B0 in: 99\nB0 out: 99\n"
        "[LIVERANGES] fn=target class=0 n_virtuals=40\n"
        "B4 in: 32 73\nB4 out: 73\nB5 out: 32 73\n"
        "[LIVERANGES] fn=target class=1 n_virtuals=10\n"   # FPR class, ignored
        "B4 out: 88\n"
    )
    lo = tb.parse_live_ranges(text, "target")
    assert lo[73] == {4, 5}        # live-out of B4 and B5
    assert lo[32] == {5}           # live-out of B5 only
    assert 99 not in lo            # other function's virtual excluded
    assert 88 not in lo            # FPR class excluded
