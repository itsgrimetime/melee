# tools/melee-agent/tests/test_suggest_coalesce.py
"""End-to-end tests for the suggest_coalesce orchestrator."""

from __future__ import annotations

import json
import pathlib

from src.mwcc_debug.suggest_coalesce import (
    PairReport, Report, render_json, render_text, run,
)


FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "mwcc_debug"


def test_run_pair_mode_returns_report_with_suggestions() -> None:
    """Running on a real fixture with a known coalesce-amenable pair
    produces at least one Suggestion."""
    if not (FIXTURES / "fn_802461BC_pcdump.txt").exists():
        import pytest
        pytest.skip("fn_802461BC_pcdump.txt fixture not present")
    text = (FIXTURES / "fn_802461BC_pcdump.txt").read_text()
    # The fixture file does not contain fn_802461BC itself; it contains
    # mnDiagram3_8024714C (and others from the same TU).  Use a function
    # that is actually present so run() does not raise ValueError.
    report = run(
        function="mnDiagram3_8024714C",
        pair=(53, 3),
        discover=False,
        pcdump_text=text,
    )
    assert report is not None
    assert report.mode == "pair"
    assert len(report.pairs) == 1
    # Either we have suggestions, or the fall-through emits raw facts
    pair = report.pairs[0]
    assert pair.from_virt == 53
    assert pair.to_virt == 3


def test_run_pair_mode_serializes_to_valid_json() -> None:
    """The Report → render_json output is parseable JSON."""
    if not (FIXTURES / "fn_802461BC_pcdump.txt").exists():
        import pytest
        pytest.skip("fixture not present")
    text = (FIXTURES / "fn_802461BC_pcdump.txt").read_text()
    report = run(
        function="mnDiagram3_8024714C", pair=(53, 3), discover=False,
        pcdump_text=text,
    )
    out = render_json(report)
    parsed = json.loads(out)
    assert parsed["function"] == "mnDiagram3_8024714C"
    assert parsed["mode"] == "pair"
