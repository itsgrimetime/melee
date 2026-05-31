"""Tests for source-level decomp attempt tracking."""

import json
import re

from typer.testing import CliRunner

from src.cli import app


runner = CliRunner()


def strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text for reliable string matching."""
    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_escape.sub("", text)


def test_attempt_record_persists_best_score_and_regression(tmp_path, monkeypatch):
    """Recording attempts preserves the best score while retaining regressions."""
    ledger_path = tmp_path / "attempts.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger_path))

    first = runner.invoke(
        app,
        [
            "attempts",
            "record",
            "Func_80000000",
            "--match",
            "87.5",
            "--outcome",
            "improved",
            "--note",
            "first coherent structure",
        ],
    )
    assert first.exit_code == 0, first.stdout

    second = runner.invoke(
        app,
        [
            "attempts",
            "record",
            "Func_80000000",
            "--match",
            "84.0",
            "--outcome",
            "regressed",
            "--classification",
            "stack-layout",
            "--note",
            "PAD_STACK experiment lost structure",
        ],
    )
    assert second.exit_code == 0, second.stdout

    data = json.loads(ledger_path.read_text())
    entry = data["functions"]["Func_80000000"]
    assert entry["best_match_percent"] == 87.5
    assert entry["no_progress_count"] == 1
    assert [attempt["outcome"] for attempt in entry["attempts"]] == ["improved", "regressed"]
    assert entry["attempts"][1]["classification"] == "stack-layout"


def test_attempt_record_recommends_moving_on_after_stalled_attempts(tmp_path, monkeypatch):
    """Repeated no-progress attempts eventually produce a move-on recommendation."""
    ledger_path = tmp_path / "attempts.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger_path))

    runner.invoke(
        app,
        ["attempts", "record", "Func_80000004", "--match", "80.0", "--outcome", "improved", "--threshold", "3"],
    )
    runner.invoke(
        app,
        ["attempts", "record", "Func_80000004", "--match", "80.0", "--outcome", "neutral", "--threshold", "3"],
    )
    runner.invoke(
        app,
        ["attempts", "record", "Func_80000004", "--match", "79.0", "--outcome", "regressed", "--threshold", "3"],
    )
    final = runner.invoke(
        app,
        [
            "attempts",
            "record",
            "Func_80000004",
            "--match",
            "80.0",
            "--outcome",
            "blocked",
            "--blocker",
            "signature/type uncertainty",
            "--threshold",
            "3",
        ],
    )
    assert final.exit_code == 0, final.stdout
    assert "Move-on recommended" in strip_ansi(final.stdout)

    data = json.loads(ledger_path.read_text())
    entry = data["functions"]["Func_80000004"]
    assert entry["no_progress_count"] == 3
    assert entry["move_on_recommended"] is True
    assert entry["suspected_blocker"] == "signature/type uncertainty"


def test_attempt_show_json_summarizes_current_state(tmp_path, monkeypatch):
    """The show command emits machine-readable state for automation."""
    ledger_path = tmp_path / "attempts.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger_path))

    runner.invoke(
        app,
        [
            "attempts",
            "record",
            "Func_80000008",
            "--match",
            "91.0",
            "--outcome",
            "improved",
            "--retained",
        ],
    )

    result = runner.invoke(app, ["attempts", "show", "Func_80000008", "--json"])
    assert result.exit_code == 0, result.stdout

    summary = json.loads(result.stdout)
    assert summary["function"] == "Func_80000008"
    assert summary["best_match_percent"] == 91.0
    assert summary["attempt_count"] == 1
    assert summary["retained_improvements"] == 1


def test_attempt_record_snapshots_high_water_source_and_diff(tmp_path, monkeypatch):
    """Only new high-water attempts keep heavy source/diff recovery payloads."""
    ledger_path = tmp_path / "attempts.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger_path))

    from src.cli.tracking import record_attempt

    record_attempt(
        "Func_80000010",
        match_percent=91.0,
        outcome="improved",
        source_code="void Func_80000010(void) { int x = 1; }\n",
        diff="classification=register-allocation\n",
        verdict="near-match",
    )
    record_attempt(
        "Func_80000010",
        match_percent=89.0,
        outcome="regressed",
        source_code="void Func_80000010(void) { int x = 2; }\n",
        diff="classification=instruction-sequence\n",
        verdict="regressed",
    )

    data = json.loads(ledger_path.read_text())
    attempts = data["functions"]["Func_80000010"]["attempts"]
    assert attempts[0]["source_code"].startswith("void Func_80000010")
    assert attempts[0]["diff"] == "classification=register-allocation\n"
    assert attempts[0]["verdict"] == "near-match"
    assert "source_code" not in attempts[1]
    assert "diff" not in attempts[1]
    assert "verdict" not in attempts[1]


def test_scratch_recover_best_emits_best_source_and_diff(tmp_path, monkeypatch):
    """recover-best returns the best retained source snapshot for a function."""
    ledger_path = tmp_path / "attempts.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger_path))

    from src.cli.tracking import record_attempt

    record_attempt(
        "Func_80000014",
        match_percent=90.0,
        outcome="improved",
        source_code="void Func_80000014(void) { int early = 1; }\n",
        diff="classification=stack-layout\n",
        verdict="first high-water",
    )
    record_attempt(
        "Func_80000014",
        match_percent=93.5,
        outcome="improved",
        source_code="void Func_80000014(void) { int best = 1; }\n",
        diff="classification=register-allocation\n",
        verdict="new high-water",
    )

    result = runner.invoke(app, ["scratch", "recover-best", "Func_80000014", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["function"] == "Func_80000014"
    assert payload["match_percent"] == 93.5
    assert "int best" in payload["source_code"]
    assert payload["diff"] == "classification=register-allocation\n"
    assert payload["verdict"] == "new high-water"


def test_register_only_stall_records_specific_move_on_reason(tmp_path, monkeypatch):
    """Register-allocation churn gets a specific move-on reason."""
    ledger_path = tmp_path / "attempts.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger_path))

    runner.invoke(
        app,
        ["attempts", "record", "Func_8000000C", "--match", "82.0", "--outcome", "improved", "--threshold", "2"],
    )
    runner.invoke(
        app,
        [
            "attempts",
            "record",
            "Func_8000000C",
            "--match",
            "82.0",
            "--outcome",
            "neutral",
            "--classification",
            "register-allocation",
            "--threshold",
            "2",
        ],
    )
    runner.invoke(
        app,
        [
            "attempts",
            "record",
            "Func_8000000C",
            "--match",
            "82.0",
            "--outcome",
            "neutral",
            "--classification",
            "register-allocation",
            "--threshold",
            "2",
        ],
    )

    result = runner.invoke(app, ["attempts", "show", "Func_8000000C", "--threshold", "2", "--json"])
    assert result.exit_code == 0, result.stdout

    summary = json.loads(result.stdout)
    assert summary["move_on_reason"] == "repeated register-allocation mismatch attempts"
    assert "fresh function or TU" in summary["recommendation"]
