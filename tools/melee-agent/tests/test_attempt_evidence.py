"""The attempt-ledger terminal evidence overlay is disabled.

The ledger no longer marks any function as a terminal "dead end" or demotes it
in the taxonomy/harvest pickers. These tests pin that the helpers are inert:
evidence is never produced, the overlay never rewrites a row, and no row is ever
treated as an active terminal attempt.
"""

import json

from src.attempt_evidence import (
    TERMINAL_ATTEMPT_FIELDS,
    apply_terminal_attempt_overlay,
    is_active_terminal_attempt_row,
    load_terminal_attempt_evidence,
)


def _write_ledger(path, functions):
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "functions": functions,
            }
        ),
        encoding="utf-8",
    )


def _blocked_ledger(path):
    """A ledger entry that previously produced terminal evidence."""
    _write_ledger(
        path,
        {
            "demo_fn": {
                "function": "demo_fn",
                "move_on_recommended": True,
                "move_on_reason": "repeated no-progress attempts",
                "suspected_blocker": "no-safe-materialized-pointer",
                "attempts": [
                    {
                        "index": 3,
                        "timestamp": 30.0,
                        "timestamp_utc": "2026-06-07T00:00:30+00:00",
                        "outcome": "blocked",
                        "classification": "indexed-struct-pointer",
                        "blocker": "no-safe-materialized-pointer",
                        "retained": False,
                        "note": "no source retained",
                    }
                ],
            }
        },
    )


def test_load_terminal_attempt_evidence_is_disabled(tmp_path):
    ledger = tmp_path / "attempt_ledger.json"
    _blocked_ledger(ledger)

    # Even an entry that recommends move-on with a known blocker yields no
    # terminal evidence — the ledger never flags a function as a dead end.
    assert load_terminal_attempt_evidence(ledger) == {}


def test_apply_terminal_attempt_overlay_returns_row_unchanged(tmp_path):
    ledger = tmp_path / "attempt_ledger.json"
    _blocked_ledger(ledger)
    evidence = load_terminal_attempt_evidence(ledger)

    row = apply_terminal_attempt_overlay(
        {
            "function": "demo_fn",
            "work_bucket": "indexed-struct-pointer",
            "primary": "source-shape",
            "subcategory": "array-index",
            "source_actionability": "current-tools-indexed-pointer",
            "headline_tool": "source-shape",
            "next_command": "melee-agent debug mutate indexed-struct-search -f demo_fn",
        },
        evidence,
    )

    # The row keeps its original actionability and routing — no demotion.
    assert row["source_actionability"] == "current-tools-indexed-pointer"
    assert row["headline_tool"] == "source-shape"
    assert row["next_command"] == (
        "melee-agent debug mutate indexed-struct-search -f demo_fn"
    )
    assert "terminal_attempt_status" not in row


def test_overlay_ignores_hand_supplied_evidence(tmp_path):
    # Even if a caller hands the overlay non-empty evidence, it does not rewrite
    # the row's actionability or routing.
    row = apply_terminal_attempt_overlay(
        {
            "function": "demo_fn",
            "source_actionability": "current-tools-indexed-pointer",
            "headline_tool": "source-shape",
            "next_command": "original command",
        },
        {"demo_fn": {"terminal_attempt_actionability": "tooling-blocked"}},
    )

    assert row["source_actionability"] == "current-tools-indexed-pointer"
    assert row["headline_tool"] == "source-shape"
    assert row["next_command"] == "original command"
    assert "terminal_attempt_status" not in row


def test_is_active_terminal_attempt_row_is_always_false():
    assert is_active_terminal_attempt_row({}) is False
    assert is_active_terminal_attempt_row({"terminal_attempt_status": "active"}) is False


def test_terminal_attempt_fields_schema_is_preserved():
    # Columns stay in the queue/CSV schema (emitted empty) for stability.
    assert "terminal_attempt_status" in TERMINAL_ATTEMPT_FIELDS
    assert "terminal_attempt_blocker" in TERMINAL_ATTEMPT_FIELDS
