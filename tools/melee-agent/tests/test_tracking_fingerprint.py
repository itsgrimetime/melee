"""Tests for fingerprint-related extensions to src/cli/tracking.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cli.tracking import record_attempt


def test_record_attempt_persists_fingerprint_fields(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))

    record_attempt(
        "fn_test",
        match_percent=87.2,
        outcome="neutral",
        fingerprint="abc123def456",
        fingerprint_norm="def456abc123",
        source_file="src/melee/mn/mnvibration.c",
    )

    data = json.loads(ledger.read_text())
    entry = data["functions"]["fn_test"]
    assert len(entry["attempts"]) == 1
    a = entry["attempts"][0]
    assert a["fingerprint"] == "abc123def456"
    assert a["fingerprint_norm"] == "def456abc123"
    assert a["source_file"] == "src/melee/mn/mnvibration.c"
    assert a["replay_count"] == 0
    assert a["last_replay_ts"] is None


def test_record_attempt_without_fingerprint_kwargs_still_works(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))

    record_attempt("fn_legacy", match_percent=50.0, outcome="neutral")
    data = json.loads(ledger.read_text())
    a = data["functions"]["fn_legacy"]["attempts"][0]
    # Fingerprint fields default to empty string, replay_count to 0
    assert a.get("fingerprint") in (None, "")
    assert a.get("replay_count", 0) == 0


from src.cli.tracking import find_attempt_by_fp


def _record(fn, **kw):
    """Test helper: defaults outcome/match for brevity."""
    record_attempt(fn, match_percent=kw.pop("match", 50.0),
                   outcome=kw.pop("outcome", "neutral"), **kw)


def test_find_attempt_by_fp_returns_raw_match(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))

    _record("fn_x", fingerprint="aaa111", fingerprint_norm="zzz999")
    _record("fn_x", fingerprint="bbb222", fingerprint_norm="zzz999")

    result = find_attempt_by_fp("fn_x", "aaa111", "ignored")
    assert result is not None
    assert result["fingerprint"] == "aaa111"
    assert result["match_type"] == "raw"


def test_find_attempt_by_fp_returns_most_recent_raw_match(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))

    _record("fn_x", fingerprint="aaa111", match=50.0)
    _record("fn_x", fingerprint="aaa111", match=60.0)  # divergent retry
    result = find_attempt_by_fp("fn_x", "aaa111")
    assert result["match_percent"] == 60.0
    assert result["index"] == 2


def test_find_attempt_by_fp_falls_back_to_norm(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))

    _record("fn_x", fingerprint="aaa111", fingerprint_norm="zzz999")
    result = find_attempt_by_fp("fn_x", "different", "zzz999")
    assert result is not None
    assert result["fingerprint"] == "aaa111"
    assert result["match_type"] == "norm"


def test_find_attempt_by_fp_returns_none_on_miss(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))

    _record("fn_x", fingerprint="aaa111")
    assert find_attempt_by_fp("fn_x", "no_match") is None


def test_find_attempt_by_fp_returns_none_for_unknown_function(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    assert find_attempt_by_fp("fn_unknown", "anything") is None


def test_find_attempt_by_fp_ignores_entries_without_fingerprint(tmp_path, monkeypatch):
    """Legacy entries (no fingerprint field) must not produce false hits."""
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))

    record_attempt("fn_x", match_percent=50.0, outcome="neutral")
    assert find_attempt_by_fp("fn_x", "", "") is None


from src.cli.tracking import increment_replay


def test_increment_replay_bumps_count_and_timestamp(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))

    record_attempt("fn_x", match_percent=50.0, outcome="neutral",
                   fingerprint="aaa111")

    summary = increment_replay("fn_x", attempt_index=1)
    assert summary["attempt_count"] == 1
    data = json.loads(ledger.read_text())
    a = data["functions"]["fn_x"]["attempts"][0]
    assert a["replay_count"] == 1
    assert a["last_replay_ts"] is not None

    increment_replay("fn_x", attempt_index=1)
    data = json.loads(ledger.read_text())
    a = data["functions"]["fn_x"]["attempts"][0]
    assert a["replay_count"] == 2


def test_increment_replay_preserves_outcome_note_classification(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))

    record_attempt("fn_x", match_percent=50.0, outcome="reverted",
                   note="tried foo", classification="register-allocation",
                   blocker="r30/r31 swap", fingerprint="aaa111")
    increment_replay("fn_x", attempt_index=1)

    data = json.loads(ledger.read_text())
    a = data["functions"]["fn_x"]["attempts"][0]
    assert a["outcome"] == "reverted"
    assert a["note"] == "tried foo"
    assert a["classification"] == "register-allocation"
    assert a["blocker"] == "r30/r31 swap"


def test_increment_replay_does_not_touch_streak_counter(tmp_path, monkeypatch):
    """Replays must NOT bump no_progress_count. Set up a non-zero
    baseline (one improvement + two no-progress attempts) so the test
    actually validates the invariant — a trivial 0→0 assertion would
    pass even if the field were corrupted."""
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))

    # Build a non-zero streak
    record_attempt("fn_x", match_percent=50.0, outcome="improved",
                   fingerprint="aaa111")
    record_attempt("fn_x", match_percent=50.0, outcome="neutral",
                   fingerprint="bbb222")
    record_attempt("fn_x", match_percent=50.0, outcome="neutral",
                   fingerprint="ccc333")

    data = json.loads(ledger.read_text())
    assert data["functions"]["fn_x"]["no_progress_count"] == 2  # sanity check fixture

    streak_before = data["functions"]["fn_x"]["no_progress_count"]
    best_before = data["functions"]["fn_x"]["best_match_percent"]
    move_on_before = data["functions"]["fn_x"]["move_on_recommended"]
    reg_streak_before = data["functions"]["fn_x"]["register_only_no_progress_count"]

    increment_replay("fn_x", attempt_index=1)
    increment_replay("fn_x", attempt_index=1)
    increment_replay("fn_x", attempt_index=1)

    data = json.loads(ledger.read_text())
    assert data["functions"]["fn_x"]["no_progress_count"] == streak_before
    assert data["functions"]["fn_x"]["best_match_percent"] == best_before
    assert data["functions"]["fn_x"]["move_on_recommended"] == move_on_before
    assert data["functions"]["fn_x"]["register_only_no_progress_count"] == reg_streak_before


def test_increment_replay_raises_for_unknown_function(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    with pytest.raises(KeyError):
        increment_replay("fn_unknown", attempt_index=1)


def test_increment_replay_raises_for_unknown_index(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    record_attempt("fn_x", match_percent=50.0, outcome="neutral",
                   fingerprint="aaa111")
    with pytest.raises(KeyError):
        increment_replay("fn_x", attempt_index=999)
