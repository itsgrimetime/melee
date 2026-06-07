import json

from src.attempt_evidence import (
    TERMINAL_ATTEMPT_ACTIONABILITIES,
    apply_terminal_attempt_overlay,
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


def test_move_on_with_known_blocker_maps_to_tooling_blocked(tmp_path):
    ledger = tmp_path / "attempt_ledger.json"
    _write_ledger(
        ledger,
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

    evidence = load_terminal_attempt_evidence(ledger)

    assert TERMINAL_ATTEMPT_ACTIONABILITIES == {
        "source-ceiling",
        "tooling-blocked",
        "diagnostic-only",
        "manual-review",
    }
    assert evidence["demo_fn"]["terminal_attempt_actionability"] == "tooling-blocked"
    assert evidence["demo_fn"]["terminal_attempt_blocker"] == "no-safe-materialized-pointer"
    assert evidence["demo_fn"]["terminal_attempt_stale_check"] == "no-tooling-fingerprint"


def test_diagnostic_padstack_blocker_maps_to_diagnostic_only(tmp_path):
    ledger = tmp_path / "attempt_ledger.json"
    _write_ledger(
        ledger,
        {
            "demo_fn": {
                "function": "demo_fn",
                "move_on_recommended": True,
                "attempts": [
                    {
                        "index": 2,
                        "timestamp": 20.0,
                        "outcome": "blocked",
                        "blocker": "diagnostic-padstack-only",
                    }
                ],
            }
        },
    )

    evidence = load_terminal_attempt_evidence(ledger)

    assert evidence["demo_fn"]["terminal_attempt_actionability"] == "diagnostic-only"
    assert evidence["demo_fn"]["terminal_attempt_blocker"] == "diagnostic-padstack-only"


def test_terminal_attempt_before_later_retained_progress_is_not_active(tmp_path):
    ledger = tmp_path / "attempt_ledger.json"
    _write_ledger(
        ledger,
        {
            "demo_fn": {
                "function": "demo_fn",
                "move_on_recommended": True,
                "attempts": [
                    {
                        "index": 1,
                        "timestamp": 10.0,
                        "outcome": "blocked",
                        "blocker": "no-safe-materialized-pointer",
                        "retained": False,
                    },
                    {
                        "index": 2,
                        "timestamp": 20.0,
                        "outcome": "improved",
                        "retained": True,
                    },
                ],
            }
        },
    )

    assert load_terminal_attempt_evidence(ledger) == {}


def test_active_overlay_preserves_bucket_topology_and_rewrites_actionability(tmp_path):
    ledger = tmp_path / "attempt_ledger.json"
    _write_ledger(
        ledger,
        {
            "demo_fn": {
                "function": "demo_fn",
                "move_on_recommended": True,
                "move_on_reason": "repeated no-progress attempts",
                "attempts": [
                    {
                        "index": 4,
                        "timestamp_utc": "2026-06-07T00:00:40+00:00",
                        "outcome": "blocked",
                        "blocker": "no-safe-materialized-pointer",
                        "classification": "indexed-struct-pointer",
                    }
                ],
            }
        },
    )
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

    assert row["work_bucket"] == "indexed-struct-pointer"
    assert row["primary"] == "source-shape"
    assert row["subcategory"] == "array-index"
    assert row["source_actionability"] == "tooling-blocked"
    assert row["headline_tool"] == "attempt-ledger"
    assert row["next_command"] == (
        "melee-agent attempts show demo_fn --no-measure-current"
    )
    assert row["terminal_attempt_status"] == "active"
    assert row["terminal_attempt_blocker"] == "no-safe-materialized-pointer"
    assert row["terminal_attempt_original_source_actionability"] == (
        "current-tools-indexed-pointer"
    )
    assert row["terminal_attempt_original_headline_tool"] == "source-shape"
    assert "attempt ledger terminal evidence" in row["actionability_reason"]
    assert "current-tools-indexed-pointer" in row["actionability_reason"]


def test_mismatched_same_key_tool_fingerprint_marks_stale_without_rewrite(tmp_path):
    ledger = tmp_path / "attempt_ledger.json"
    _write_ledger(
        ledger,
        {
            "demo_fn": {
                "function": "demo_fn",
                "move_on_recommended": True,
                "attempts": [
                    {
                        "index": 5,
                        "timestamp_utc": "2026-06-07T00:00:50+00:00",
                        "outcome": "blocked",
                        "blocker": "no-safe-materialized-pointer",
                        "tool_sha256": "old-tool",
                    }
                ],
            }
        },
    )
    evidence = load_terminal_attempt_evidence(ledger)

    row = apply_terminal_attempt_overlay(
        {
            "function": "demo_fn",
            "work_bucket": "indexed-struct-pointer",
            "source_actionability": "current-tools-indexed-pointer",
            "headline_tool": "source-shape",
            "next_command": "original command",
        },
        evidence,
        current_tool_fingerprints={"tool_sha256": "new-tool"},
    )

    assert row["source_actionability"] == "current-tools-indexed-pointer"
    assert row["headline_tool"] == "source-shape"
    assert row["next_command"] == "original command"
    assert row["terminal_attempt_status"] == "stale"
    assert row["terminal_attempt_stale_check"] == "stale-tool_sha256"
    assert row["terminal_attempt_tool_sha256"] == "old-tool"


def test_fingerprint_comparison_does_not_cross_keys(tmp_path):
    ledger = tmp_path / "attempt_ledger.json"
    _write_ledger(
        ledger,
        {
            "demo_fn": {
                "function": "demo_fn",
                "move_on_recommended": True,
                "attempts": [
                    {
                        "index": 6,
                        "timestamp_utc": "2026-06-07T00:01:00+00:00",
                        "outcome": "blocked",
                        "blocker": "no-safe-materialized-pointer",
                        "tool_sha256": "same-tool",
                    }
                ],
            }
        },
    )
    evidence = load_terminal_attempt_evidence(ledger)

    row = apply_terminal_attempt_overlay(
        {
            "function": "demo_fn",
            "source_actionability": "current-tools-indexed-pointer",
            "headline_tool": "source-shape",
            "next_command": "original command",
        },
        evidence,
        current_tool_fingerprints={
            "tool_sha256": "same-tool",
            "row_tool_sha256": "different-row-tool",
        },
    )

    assert row["terminal_attempt_status"] == "active"
    assert row["terminal_attempt_stale_check"] == "fresh-tool_sha256"
    assert row["source_actionability"] == "tooling-blocked"


def test_all_comparable_fingerprint_keys_are_checked(tmp_path):
    ledger = tmp_path / "attempt_ledger.json"
    _write_ledger(
        ledger,
        {
            "demo_fn": {
                "function": "demo_fn",
                "move_on_recommended": True,
                "attempts": [
                    {
                        "index": 7,
                        "timestamp_utc": "2026-06-07T00:01:10+00:00",
                        "outcome": "blocked",
                        "blocker": "no-safe-materialized-pointer",
                        "tool_sha256": "same-tool",
                        "row_tool_sha256": "old-row-tool",
                    }
                ],
            }
        },
    )
    evidence = load_terminal_attempt_evidence(ledger)

    row = apply_terminal_attempt_overlay(
        {
            "function": "demo_fn",
            "source_actionability": "current-tools-indexed-pointer",
            "headline_tool": "source-shape",
            "next_command": "original command",
        },
        evidence,
        current_tool_fingerprints={
            "tool_sha256": "same-tool",
            "row_tool_sha256": "new-row-tool",
        },
    )

    assert row["terminal_attempt_status"] == "stale"
    assert row["terminal_attempt_stale_check"] == "stale-row_tool_sha256"
    assert row["source_actionability"] == "current-tools-indexed-pointer"


def test_tooling_sha256_is_a_comparable_fingerprint_key(tmp_path):
    ledger = tmp_path / "attempt_ledger.json"
    _write_ledger(
        ledger,
        {
            "demo_fn": {
                "function": "demo_fn",
                "move_on_recommended": True,
                "attempts": [
                    {
                        "index": 8,
                        "timestamp_utc": "2026-06-07T00:01:20+00:00",
                        "outcome": "blocked",
                        "blocker": "no-safe-materialized-pointer",
                        "tooling_sha256": "old-tooling",
                    }
                ],
            }
        },
    )
    evidence = load_terminal_attempt_evidence(ledger)

    row = apply_terminal_attempt_overlay(
        {
            "function": "demo_fn",
            "source_actionability": "current-tools-indexed-pointer",
            "headline_tool": "source-shape",
            "next_command": "original command",
        },
        evidence,
        current_tool_fingerprints={"tooling_sha256": "new-tooling"},
    )

    assert row["terminal_attempt_status"] == "stale"
    assert row["terminal_attempt_stale_check"] == "stale-tooling_sha256"
    assert row["terminal_attempt_tooling_sha256"] == "old-tooling"
    assert row["source_actionability"] == "current-tools-indexed-pointer"
