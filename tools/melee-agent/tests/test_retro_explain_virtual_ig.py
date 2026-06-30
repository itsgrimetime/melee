"""Regression tests for `debug inspect explain-virtual` (ig_idx provenance).

Guards two things:
1. The lazy import resolves (it was broken: `..mwcc_debug` -> nonexistent
   `src.cli.mwcc_debug`; correct is `...mwcc_debug` = src.mwcc_debug). A broken
   import made the command crash and looked like the capability was missing.
2. `--ig N` queries by COLORGRAPH ig_idx (== virtual rN) and yields the node's
   physical reg + defining instruction + source attribution.
"""
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app

runner = CliRunner()

REPO = Path(__file__).resolve().parents[3]
FIXTURE = (REPO / "tools/melee-agent/tests/fixtures/role_identity"
           / "mnVibration_matched_pcdump.txt")
FN = "mnVibration_80248644"


def test_explain_virtual_import_not_broken():
    # Must not crash with ModuleNotFoundError (the original bug).
    r = runner.invoke(app, ["debug", "inspect", "explain-virtual",
                            "-f", FN, "--all", "--pcdump", str(FIXTURE)])
    assert r.exit_code == 0, r.output
    assert "ModuleNotFoundError" not in r.output
    assert "ig=" in r.output  # produced real attributions


def test_explain_virtual_ig_queries_by_ig_idx():
    # ig_idx 32 -> virtual r32 -> physical/defining-instruction attribution.
    r = runner.invoke(app, ["debug", "inspect", "explain-virtual",
                            "-f", FN, "--ig", "32", "--pcdump", str(FIXTURE)])
    assert r.exit_code == 0, r.output
    assert "r32:" in r.output
    assert "ig=32" in r.output


def test_explain_virtual_ig_rejects_garbage():
    r = runner.invoke(app, ["debug", "inspect", "explain-virtual",
                            "-f", FN, "--ig", "notanint", "--pcdump", str(FIXTURE)])
    assert r.exit_code != 0
