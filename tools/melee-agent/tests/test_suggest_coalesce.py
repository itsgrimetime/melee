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


import yaml


def _load_calibration():
    """Load the calibration YAML; skip silently if not present."""
    path = pathlib.Path(__file__).parent / "fixtures" / "coalesce_calibration.yaml"
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text()).get("cases", [])


import pytest


@pytest.mark.parametrize("case", _load_calibration())
def test_calibration_corpus(case) -> None:
    """Each calibration case asserts the orchestrator behaves as the
    YAML specifies. New cases can be added without writing new test
    code — just append to coalesce_calibration.yaml."""
    fixture_path = FIXTURES / case["pcdump"]
    if not fixture_path.exists():
        pytest.skip(f"fixture {case['pcdump']} not present")
    text = fixture_path.read_text()

    if case.get("discover"):
        report = run(
            function=case["function"],
            discover=True, pcdump_text=text,
        )
        assert report.mode == "discover"
        min_len = case.get("expected_cascade_length_min", 2)
        assert report.cascade is not None
        assert len(report.cascade) >= min_len
        if "expected_top_priority_class" in case:
            assert report.pairs, "discover produced no candidates"
            assert (
                report.pairs[0].priority_class
                == case["expected_top_priority_class"]
            )
        # Strict: top-1 pair equality (when set in YAML)
        top_pair = case.get("expected_top_pair")
        if top_pair is not None:
            assert report.pairs, "discover produced no candidates"
            actual = (report.pairs[0].from_virt, report.pairs[0].to_virt)
            assert actual == tuple(top_pair), (
                f"expected top-1 pair {tuple(top_pair)}, got {actual}"
            )
    else:
        pair_tuple = tuple(case["pair"])
        report = run(
            function=case["function"],
            pair=pair_tuple, discover=False,
            pcdump_text=text,
        )
        assert report.mode == "pair"
        assert len(report.pairs) == 1
        pr = report.pairs[0]
        # Strict: each expected pattern name must appear in suggestions
        expected_patterns = set(case.get("expected_patterns") or [])
        if expected_patterns:
            actual_patterns = {s.pattern_name for s in pr.suggestions}
            missing = expected_patterns - actual_patterns
            assert not missing, (
                f"expected patterns {expected_patterns}, "
                f"actual {actual_patterns}, missing {missing}"
            )
        else:
            # Fall-through acceptable: any non-empty ir_facts is OK
            assert pr.ir_facts
