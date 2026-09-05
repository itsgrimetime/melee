"""CliRunner tests for the 5 new backtest hook subcommands (Task 4.5)."""
from __future__ import annotations

import json
import sys

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.backtest.store import BacktestStore
from src.backtest.types import Case, CaseResult

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_case(function: str = "fn_test", provenance: str = "held_out") -> Case:
    return Case(
        function=function,
        c_sha="aaa" + "0" * 37,
        cprev_sha="bbb" + "0" * 37,
        unit="mn",
        file="src/melee/mn/test.c",
        ground_truth_diff="- old\n+ new\n",
        lever_locus="local",
        author="test",
        provenance=provenance,
        lever_class="other",
        baseline_pct=95.0,
        baseline_ndl=4,
        target_pct=100.0,
        target_ndl=0,
    )


def _seed_case_and_result(store: BacktestStore, case: Case, rollup: str) -> str:
    store.ensure_schema()
    store.insert_case(case)
    result = CaseResult(
        case_id=case.case_id,
        advisory="silent-or-wrong",
        generative="no-progress",
        agent=None,
        rollup=rollup,
        evidence={},
    )
    store.upsert_result(result)
    return case.case_id


# ---------------------------------------------------------------------------
# escalation
# ---------------------------------------------------------------------------

def test_escalation_returns_gap_case(tmp_path):
    db = tmp_path / "bt.db"
    store = BacktestStore(db)

    gap_case = _make_case("fn_gap", provenance="held_out")
    held_solved = _make_case("fn_solved", provenance="held_out")
    gap_id = _seed_case_and_result(store, gap_case, "GAP")
    _seed_case_and_result(store, held_solved, "SOLVED-BY-TOOLING")

    result = runner.invoke(app, ["backtest", "escalation", "--json", "--db", str(db)])
    assert result.exit_code == 0, result.output
    ids = json.loads(result.output)
    assert gap_id in ids


def test_escalation_plain_text(tmp_path):
    db = tmp_path / "bt.db"
    store = BacktestStore(db)
    gap_case = _make_case("fn_gap2", provenance="held_out")
    gap_id = _seed_case_and_result(store, gap_case, "GAP")

    result = runner.invoke(app, ["backtest", "escalation", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert gap_id in result.output


# ---------------------------------------------------------------------------
# set-advisory
# ---------------------------------------------------------------------------

def test_set_advisory_names_lever(tmp_path):
    db = tmp_path / "bt.db"
    store = BacktestStore(db)
    case = _make_case("fn_adv")
    cid = _seed_case_and_result(store, case, "GAP")

    result = runner.invoke(app, ["backtest", "set-advisory", cid, "names-lever", "--db", str(db)])
    assert result.exit_code == 0, result.output

    # Verify the store was updated
    row = BacktestStore(db).get_result(cid)
    assert row is not None
    assert row["advisory"] == "names-lever"
    # rollup should upgrade from GAP → PARTIAL (names-lever → PARTIAL)
    assert row["rollup"] in ("PARTIAL", "SOLVED-BY-TOOLING")


def test_set_advisory_bad_verdict(tmp_path):
    db = tmp_path / "bt.db"
    store = BacktestStore(db)
    case = _make_case("fn_adv_bad")
    cid = _seed_case_and_result(store, case, "GAP")

    result = runner.invoke(app, ["backtest", "set-advisory", cid, "not-a-real-verdict", "--db", str(db)])
    assert result.exit_code != 0


def test_set_advisory_no_prior_result(tmp_path):
    """set-advisory works even when no result row exists yet (case-only scenario)."""
    db = tmp_path / "bt.db"
    store = BacktestStore(db)
    store.ensure_schema()
    case = _make_case("fn_adv_new")
    store.insert_case(case)
    cid = case.case_id

    result = runner.invoke(app, ["backtest", "set-advisory", cid, "hints-adjacent", "--db", str(db)])
    assert result.exit_code == 0, result.output
    row = BacktestStore(db).get_result(cid)
    assert row["advisory"] == "hints-adjacent"


# ---------------------------------------------------------------------------
# set-agent
# ---------------------------------------------------------------------------

def test_set_agent_matched(tmp_path):
    db = tmp_path / "bt.db"
    store = BacktestStore(db)
    case = _make_case("fn_agent")
    cid = _seed_case_and_result(store, case, "GAP")

    result = runner.invoke(app, ["backtest", "set-agent", cid, "matched", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "SOLVED-BY-TOOLING" in result.output

    row = BacktestStore(db).get_result(cid)
    assert row["agent"] == "matched"
    assert row["rollup"] == "SOLVED-BY-TOOLING"


def test_set_agent_bad_verdict(tmp_path):
    db = tmp_path / "bt.db"
    store = BacktestStore(db)
    case = _make_case("fn_agent_bad")
    cid = _seed_case_and_result(store, case, "GAP")

    result = runner.invoke(app, ["backtest", "set-agent", cid, "flew-away", "--db", str(db)])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# open-sandbox / close-sandbox (monkeypatched — no real build)
# ---------------------------------------------------------------------------

def test_open_sandbox_returns_json(tmp_path, monkeypatch):
    db = tmp_path / "bt.db"
    store = BacktestStore(db)
    store.ensure_schema()
    case = _make_case("fn_sandbox")
    store.insert_case(case)
    cid = case.case_id

    import src.backtest.sandbox as _sandbox_mod
    import src.backtest.run as _run_mod

    monkeypatch.setattr(_sandbox_mod, "build_sandbox", lambda **kw: kw["dest"])
    monkeypatch.setattr(_sandbox_mod, "teardown_sandbox", lambda dest: None)

    import subprocess as _sp
    monkeypatch.setattr(_sp, "run", lambda *a, **kw: type("R", (), {"returncode": 0})())

    result = runner.invoke(app, ["backtest", "open-sandbox", cid, "--db", str(db)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["function"] == "fn_sandbox"
    assert "sandbox" in payload


def test_close_sandbox_exits_0(tmp_path, monkeypatch):
    db = tmp_path / "bt.db"
    store = BacktestStore(db)
    store.ensure_schema()
    case = _make_case("fn_close")
    store.insert_case(case)
    cid = case.case_id

    import src.backtest.sandbox as _sandbox_mod
    monkeypatch.setattr(_sandbox_mod, "teardown_sandbox", lambda dest: None)

    result = runner.invoke(app, ["backtest", "close-sandbox", cid, "--db", str(db)])
    assert result.exit_code == 0, result.output


def test_open_sandbox_missing_case(tmp_path, monkeypatch):
    db = tmp_path / "bt.db"
    store = BacktestStore(db)
    store.ensure_schema()

    import src.backtest.sandbox as _sandbox_mod
    monkeypatch.setattr(_sandbox_mod, "build_sandbox", lambda **kw: kw["dest"])

    import subprocess as _sp
    monkeypatch.setattr(_sp, "run", lambda *a, **kw: type("R", (), {"returncode": 0})())

    result = runner.invoke(app, ["backtest", "open-sandbox", "nonexistent-id", "--db", str(db)])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# judge-input  (F1)
# ---------------------------------------------------------------------------

def _seed_case_with_advisory(store: BacktestStore, case: Case, advisory_outputs: dict) -> str:
    store.ensure_schema()
    store.insert_case(case)
    result = CaseResult(
        case_id=case.case_id,
        advisory=None,
        generative="no-progress",
        agent=None,
        rollup="GAP",
        evidence={"advisory": advisory_outputs, "generative": {"best_ndl": 4}},
    )
    store.upsert_result(result)
    return case.case_id


def test_judge_input_is_label_blinded(tmp_path):
    db = tmp_path / "bt.db"
    store = BacktestStore(db)
    case = _make_case("fn_judge")
    advisory = {"inspect_explain_diff": {"rc": 0, "stdout": "some tool output"}}
    cid = _seed_case_with_advisory(store, case, advisory)

    result = runner.invoke(app, ["backtest", "judge-input", cid, "--json", "--db", str(db)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    # Label-blinded: no provenance / author / lever_locus leak to the judge.
    assert "provenance" not in payload
    assert "author" not in payload
    # But the judge DOES see the function, diff, lever_class and tool outputs.
    assert payload["function"] == "fn_judge"
    assert payload["lever_class"] == "other"
    assert payload["tool_outputs"] == advisory
    assert "ground_truth_diff" in payload


def test_judge_input_missing_result_errors(tmp_path):
    db = tmp_path / "bt.db"
    store = BacktestStore(db)
    store.ensure_schema()
    case = _make_case("fn_no_result")
    store.insert_case(case)

    result = runner.invoke(app, ["backtest", "judge-input", case.case_id, "--db", str(db)])
    assert result.exit_code != 0


def test_judge_input_missing_case_errors(tmp_path):
    db = tmp_path / "bt.db"
    store = BacktestStore(db)
    store.ensure_schema()
    result = runner.invoke(app, ["backtest", "judge-input", "nonexistent", "--db", str(db)])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# pending-judge  (F1)
# ---------------------------------------------------------------------------

def test_pending_judge_lists_run_cases(tmp_path):
    db = tmp_path / "bt.db"
    store = BacktestStore(db)
    # Two cases with result rows, one case with no result row.
    cid_a = _seed_case_and_result(store, _make_case("fn_a"), "GAP")
    cid_b = _seed_case_and_result(store, _make_case("fn_b"), "PARTIAL")
    store.insert_case(_make_case("fn_no_run"))

    result = runner.invoke(app, ["backtest", "pending-judge", "--json", "--db", str(db)])
    assert result.exit_code == 0, result.output
    ids = json.loads(result.output)
    assert set(ids) == {cid_a, cid_b}


def test_pending_judge_empty(tmp_path):
    db = tmp_path / "bt.db"
    BacktestStore(db).ensure_schema()
    result = runner.invoke(app, ["backtest", "pending-judge", "--json", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []


# ---------------------------------------------------------------------------
# calibrate  (F3)
# ---------------------------------------------------------------------------

def test_calibrate_passes_on_shipped_fixtures():
    """The Phase-0 gate must exit 0 and report passed:true on the shipped fixtures."""
    result = runner.invoke(app, ["backtest", "calibrate", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True
    assert payload["positives_ok"] >= 1
    assert payload["negatives_ok"] >= 1


def test_calibrate_fails_when_negative_scorer_leaks():
    """Directly exercise the underlying calibrate() with a leaking generative
    scorer: negatives must then fail the gate (non-empty failures, passed:false)."""
    from src.backtest.calibrate import calibrate
    from src.backtest.fixtures import load_calibration_fixtures

    fx = load_calibration_fixtures()
    # Leak: mark EVERYTHING byte-match-reproduced -> negatives wrongly SOLVED.
    out = calibrate(
        fx,
        score_advisory=lambda f: "names-lever",
        score_generative=lambda f: "byte-match-reproduced",
    )
    assert out["passed"] is False
    assert any(fl["kind"] == "negative" for fl in out["failures"])
