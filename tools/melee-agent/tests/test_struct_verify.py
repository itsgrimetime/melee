# tests/test_struct_verify.py
"""Tests for struct verify Phase 3: functions_for_unit, aggregation, CLI command, renderer."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Task 3.1: functions_for_unit helper
# ---------------------------------------------------------------------------

def test_functions_for_unit_thpdec():
    from src.extractor import report as report_mod
    fns = report_mod.functions_for_unit(REPO / "build/GALE01/report.json", "thp/THPDec")
    assert "__THPRestartDefinition" in fns
    assert "THPVideoDecode" in fns
    assert all(isinstance(f, str) for f in fns)


def test_functions_for_unit_not_found():
    from src.extractor import report as report_mod
    import pytest
    with pytest.raises(ValueError, match="not found"):
        report_mod.functions_for_unit(REPO / "build/GALE01/report.json", "nonexistent/DoesNotExist")


# ---------------------------------------------------------------------------
# Task 3.2: aggregate + confidence
# ---------------------------------------------------------------------------

def test_aggregate_keeps_singletons_and_flags_ambiguous():
    from src.common import struct_verify as sv
    findings = [
        {"function": "f1", "field": "RST", "current": 0x740, "expected": 0x900},
        {"function": "f2", "field": "nMCU", "current": 0x742, "expected": 0x8fc},
        {"function": "f3", "field": "nMCU", "current": 0x742, "expected": 0x8fc},
        # ambiguous: same field, conflicting expected
        {"function": "f4", "field": "RST", "current": 0x740, "expected": 0x123},
    ]
    agg = sv.aggregate(findings)
    rst = next(a for a in agg if a["field"] == "RST")
    nmcu = next(a for a in agg if a["field"] == "nMCU")
    assert rst["conflict"] is True              # RST has two expecteds
    assert nmcu["n_functions"] == 2 and nmcu["conflict"] is False
    assert nmcu["confidence"] == "high"         # >=2 agreeing
    # agreeing functions collapse to a single expected value
    assert nmcu["expected"] == 0x8fc


def test_aggregate_singleton_confidence_low():
    from src.common import struct_verify as sv
    findings = [
        {"function": "f1", "field": "RST", "current": 0x740, "expected": 0x900},
    ]
    agg = sv.aggregate(findings)
    assert len(agg) == 1
    assert agg[0]["confidence"] == "low"
    assert agg[0]["n_functions"] == 1
    assert agg[0]["conflict"] is False
    assert agg[0]["expected"] == 0x900


def test_aggregate_sorted_by_current():
    from src.common import struct_verify as sv
    findings = [
        {"function": "f1", "field": "B", "current": 0x900, "expected": 0xa00},
        {"function": "f2", "field": "A", "current": 0x100, "expected": 0x200},
    ]
    agg = sv.aggregate(findings)
    assert agg[0]["field"] == "A"
    assert agg[1]["field"] == "B"


def test_aggregate_empty():
    from src.common import struct_verify as sv
    assert sv.aggregate([]) == []


def test_aggregate_flags_ambiguous_when_ref_field_differs():
    from src.common import struct_verify as sv
    findings = [
        # ambiguous: cur_disp maps to "predDC" but ref_disp maps to a DIFFERENT
        # known field "nextField" -> could be a deliberate different-field access
        {"function": "f1", "field": "predDC", "current": 0x100, "expected": 0x110,
         "ref_field": "nextField"},
        # normal: ref_field is None -> not ambiguous
        {"function": "f2", "field": "RST", "current": 0x740, "expected": 0x900,
         "ref_field": None},
        # normal: ref_field == field (plain offset shift of the SAME field) -> not ambiguous
        {"function": "f3", "field": "nMCU", "current": 0x742, "expected": 0x8fc,
         "ref_field": "nMCU"},
    ]
    agg = sv.aggregate(findings)
    by_field = {a["field"]: a for a in agg}
    assert by_field["predDC"]["ambiguous"] is True
    assert by_field["RST"]["ambiguous"] is False
    assert by_field["nMCU"]["ambiguous"] is False


def test_aggregate_ambiguous_defaults_false_when_key_absent():
    # Findings produced before the ref_field enrichment (or for a non-mapping
    # path) must still aggregate, defaulting ambiguous to False.
    from src.common import struct_verify as sv
    findings = [
        {"function": "f1", "field": "RST", "current": 0x740, "expected": 0x900},
    ]
    agg = sv.aggregate(findings)
    assert agg[0]["ambiguous"] is False


# ---------------------------------------------------------------------------
# Task 3.3: struct verify CLI help test
# ---------------------------------------------------------------------------

def test_struct_verify_help():
    from typer.testing import CliRunner
    from src.cli.struct import struct_app
    r = CliRunner().invoke(struct_app, ["verify", "--help"])
    assert r.exit_code == 0
    assert "--struct" in r.output and "--base" in r.output


# ---------------------------------------------------------------------------
# Task 3.4: _render_verify_table smoke test
# ---------------------------------------------------------------------------

def test_render_verify_table_smoke(capsys):
    from src.cli.struct import _render_verify_table
    _render_verify_table(
        [{"field": "RST", "current": 0x740, "expected": 0x900,
          "expecteds": [0x900], "n_functions": 1, "functions": ["f"],
          "conflict": False, "confidence": "low"}],
        [],
    )
    out = capsys.readouterr().out
    assert "RST" in out and "0x900" in out


def test_render_verify_table_conflict(capsys):
    from src.cli.struct import _render_verify_table
    _render_verify_table(
        [{"field": "RST", "current": 0x740, "expected": None,
          "expecteds": [0x900, 0x123], "n_functions": 2, "functions": ["f1", "f2"],
          "conflict": True, "confidence": "low"}],
        [("skippedFn", "no base")],
    )
    out = capsys.readouterr().out
    assert "CONFLICT" in out
    assert "skipped" in out


def test_render_verify_table_high_confidence(capsys):
    from src.cli.struct import _render_verify_table
    _render_verify_table(
        [{"field": "nMCU", "current": 0x742, "expected": 0x8fc,
          "expecteds": [0x8fc], "n_functions": 2, "functions": ["f1", "f2"],
          "conflict": False, "confidence": "high"}],
        [],
    )
    out = capsys.readouterr().out
    assert "nMCU" in out and "high" in out


def test_render_verify_table_ambiguous(capsys):
    from src.cli.struct import _render_verify_table
    _render_verify_table(
        [{"field": "predDC", "current": 0x100, "expected": 0x110,
          "expecteds": [0x110], "n_functions": 1, "functions": ["f1"],
          "conflict": False, "confidence": "low", "ambiguous": True}],
        [],
    )
    out = capsys.readouterr().out
    assert "predDC" in out and "AMBIGUOUS" in out
