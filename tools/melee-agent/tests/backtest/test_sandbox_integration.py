# tools/melee-agent/tests/backtest/test_sandbox_integration.py
import os, json, subprocess, sys
import pytest
from pathlib import Path
from src.backtest.sandbox import build_sandbox, teardown_sandbox
from src.backtest.run import run_checkdiff_at, _structural_ndl

pytestmark = pytest.mark.skipif(os.environ.get("BACKTEST_SLOW") != "1",
                                reason="set BACKTEST_SLOW=1 to run the building integration test")

def test_sandbox_build_and_checkdiff_machinery(tmp_path):
    """Live proof the heavy machinery fires: provable-blind sandbox -> worktree-doctor
    -> real ninja build -> checkdiff structural scoring.

    Anchor: grIceMt_801F9ACC at C~1=13ccea114 (the match commit 3ce0722cd is provably
    absent from the sandbox). EMPIRICAL FINDING (verified 2026-06-26 real run): at C~1
    this function is match=False / fuzzy=99.979% but structurally MATCHED
    (structural_truth_gate.normalized_diff_lines == 0). I.e. its 100% "match" commit was
    a backend-coloring/reloc tie-break, NOT a source-lever structural flip. So grIceMt is
    NOT a valid corpus case under build_corpus's structural confound guard (which requires
    p_ndl > 0 at C~1) -- build_corpus would correctly DROP it. This test therefore asserts
    only what this anchor can prove: the machinery runs and checkdiff returns a well-formed
    payload with the structural gate computed. A genuine structural-flip anchor
    (p_ndl > 0 at C~1, c_ndl == 0 at C) is still needed for an end-to-end CORPUS smoke (TODO).
    """
    main = "/Users/mike/code/melee"
    c = subprocess.run(["git", "-C", main, "rev-parse", "3ce0722cd"], capture_output=True, text=True).stdout.strip()
    cprev = subprocess.run(["git", "-C", main, "rev-parse", "3ce0722cd~1"], capture_output=True, text=True).stdout.strip()
    sb = build_sandbox(main_repo=main, c_sha=c, cprev_sha=cprev, dest=tmp_path / "sb")  # asserts C absent
    try:
        subprocess.run([sys.executable, "tools/worktree-doctor.py", "--fix"], cwd=str(sb), check=True)
        payload = run_checkdiff_at(str(sb), "grIceMt_801F9ACC")
        # Machinery produced a real, well-formed checkdiff result from the blind sandbox build:
        assert payload["match"] is False                      # not byte-identical at C~1 (fuzzy ~99.98%)
        ndl = _structural_ndl(payload)
        assert isinstance(ndl, int)                           # structural gate was computed (here ndl==0)
    finally:
        teardown_sandbox(sb)
