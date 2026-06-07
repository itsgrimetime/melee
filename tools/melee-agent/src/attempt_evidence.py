"""Attempt-ledger terminal evidence helpers for taxonomy and harvest rows."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

TERMINAL_ATTEMPT_ACTIONABILITIES = {
    "source-ceiling",
    "tooling-blocked",
    "diagnostic-only",
    "manual-review",
}

TERMINAL_ATTEMPT_FIELDS = (
    "terminal_attempt_status",
    "terminal_attempt_actionability",
    "terminal_attempt_blocker",
    "terminal_attempt_attempt_index",
    "terminal_attempt_timestamp",
    "terminal_attempt_move_on_recommended",
    "terminal_attempt_move_on_reason",
    "terminal_attempt_stale_check",
    "terminal_attempt_original_source_actionability",
    "terminal_attempt_original_headline_tool",
    "terminal_attempt_original_next_command",
    "terminal_attempt_tool_sha256",
    "terminal_attempt_tooling_sha256",
    "terminal_attempt_row_tool_sha256",
    "terminal_attempt_taxonomy_tool_sha256",
    "terminal_attempt_tool_commit",
)

_TOOLING_BLOCKERS = {
    "allocator-target-conflict",
    "allocator-force-vector-no-match",
    "no-safe-materialized-pointer",
    "malformed-source-candidate",
    "malformed-candidate",
    "unsupported-harness",
    "unsupported-tool",
}
_SOURCE_CEILING_BLOCKERS = {
    "source-ceiling",
    "negative-role-shape",
    "negative-role-shape-probes",
    "no-improvement",
    "no-improvement-search",
    "no-source-retained",
}
_DIAGNOSTIC_BLOCKERS = {
    "pad-stack-only",
    "padstack-only",
    "diagnostic-padstack-only",
    "diagnostic-only",
}
_PROGRESS_OUTCOMES = {"improved", "matched"}
_FINGERPRINT_KEYS = (
    "tool_sha256",
    "tooling_sha256",
    "row_tool_sha256",
    "taxonomy_tool_sha256",
)
_TOOL_COMMIT_KEYS = ("tool_commit", "tooling_commit", "taxonomy_tool_commit")
_LEDGER_CACHE: dict[tuple[str, int, int], dict[str, dict[str, str]]] = {}


def _default_ledger_path() -> Path:
    env_path = os.environ.get("DECOMP_ATTEMPT_LEDGER_FILE")
    if env_path:
        return Path(env_path)
    return Path.home() / ".config" / "decomp-me" / "attempt_ledger.json"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "functions": {}}
    if not isinstance(data, dict):
        return {"version": 1, "functions": {}}
    if not isinstance(data.get("functions"), dict):
        data["functions"] = {}
    return data


def _attempt_sort_key(attempt: Mapping[str, Any]) -> tuple[float, int]:
    index = _stringify(attempt.get("index"))
    try:
        parsed_index = int(index)
    except ValueError:
        parsed_index = 0
    try:
        timestamp = float(attempt.get("timestamp") or 0.0)
    except (TypeError, ValueError):
        timestamp = 0.0
    return (timestamp, parsed_index)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _is_progress_attempt(attempt: Mapping[str, Any]) -> bool:
    return bool(attempt.get("retained")) or _stringify(
        attempt.get("outcome")
    ).lower() in _PROGRESS_OUTCOMES


def _blocker_actionability(blocker: str, note: str, move_on: bool) -> str:
    normalized = blocker.strip().lower()
    note_normalized = note.strip().lower()
    if normalized in _TOOLING_BLOCKERS:
        return "tooling-blocked"
    if normalized in _SOURCE_CEILING_BLOCKERS:
        return "source-ceiling"
    if normalized in _DIAGNOSTIC_BLOCKERS or "pad_stack" in note_normalized:
        return "diagnostic-only"
    if "source-ceiling" in note_normalized or "no-improvement" in note_normalized:
        return "source-ceiling"
    if move_on:
        return "manual-review"
    return ""


def _latest_active_terminal_attempt(
    entry: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    attempts = [
        attempt for attempt in entry.get("attempts", [])
        if isinstance(attempt, Mapping)
    ]
    attempts.sort(key=_attempt_sort_key)

    latest_progress = -1
    for position, attempt in enumerate(attempts):
        if _is_progress_attempt(attempt):
            latest_progress = position

    move_on = bool(entry.get("move_on_recommended"))
    latest_terminal: Mapping[str, Any] | None = None
    for position, attempt in enumerate(attempts):
        if position <= latest_progress:
            continue
        blocker = _stringify(attempt.get("blocker")) or _stringify(
            entry.get("suspected_blocker")
        )
        actionability = _blocker_actionability(
            blocker,
            _stringify(attempt.get("note")),
            move_on,
        )
        if actionability:
            latest_terminal = attempt

    if latest_terminal is None and move_on and latest_progress < len(attempts) - 1:
        return attempts[-1] if attempts else {}
    if latest_terminal is None and move_on and not attempts:
        return {}
    return latest_terminal


def _evidence_for_entry(
    function_name: str,
    entry: Mapping[str, Any],
) -> dict[str, str] | None:
    attempt = _latest_active_terminal_attempt(entry)
    if attempt is None:
        return None
    blocker = _stringify(attempt.get("blocker")) or _stringify(
        entry.get("suspected_blocker")
    )
    actionability = _blocker_actionability(
        blocker,
        _stringify(attempt.get("note")),
        bool(entry.get("move_on_recommended")),
    )
    if not actionability:
        actionability = "manual-review"

    evidence = {
        "function": function_name,
        "terminal_attempt_status": "active",
        "terminal_attempt_actionability": actionability,
        "terminal_attempt_blocker": blocker,
        "terminal_attempt_attempt_index": _stringify(attempt.get("index")),
        "terminal_attempt_timestamp": _stringify(
            attempt.get("timestamp_utc") or attempt.get("timestamp")
        ),
        "terminal_attempt_move_on_recommended": str(
            bool(entry.get("move_on_recommended"))
        ).lower(),
        "terminal_attempt_move_on_reason": _stringify(
            entry.get("move_on_reason")
        ),
        "terminal_attempt_stale_check": "no-tooling-fingerprint",
    }
    for key in _FINGERPRINT_KEYS:
        value = _stringify(attempt.get(key))
        if value:
            evidence[f"terminal_attempt_{key}"] = value
    for key in _TOOL_COMMIT_KEYS:
        value = _stringify(attempt.get(key))
        if value:
            evidence["terminal_attempt_tool_commit"] = value
            break
    return evidence


def load_terminal_attempt_evidence(
    path: Path | None = None,
    *,
    current_tool_fingerprints: Mapping[str, str] | None = None,
    current_tool_commit: str | None = None,
) -> dict[str, dict[str, str]]:
    """Load active terminal evidence from an attempt ledger.

    Freshness parameters are accepted for API symmetry; staleness is evaluated
    by ``apply_terminal_attempt_overlay`` because harvest has row-specific
    tooling fingerprints.
    """
    del current_tool_fingerprints, current_tool_commit
    ledger_path = path or _default_ledger_path()
    try:
        stat = ledger_path.stat()
    except OSError:
        return {}

    cache_key = (str(ledger_path), stat.st_mtime_ns, stat.st_size)
    cached = _LEDGER_CACHE.get(cache_key)
    if cached is not None:
        return {function: dict(fields) for function, fields in cached.items()}

    data = _load_json(ledger_path)
    evidence: dict[str, dict[str, str]] = {}
    for function_name, entry in data.get("functions", {}).items():
        if not isinstance(entry, Mapping):
            continue
        function = _stringify(entry.get("function")) or _stringify(function_name)
        entry_evidence = _evidence_for_entry(function, entry)
        if entry_evidence is not None:
            evidence[function] = entry_evidence

    _LEDGER_CACHE.clear()
    _LEDGER_CACHE[cache_key] = {function: dict(fields) for function, fields in evidence.items()}
    return evidence


def _stale_status(
    evidence: Mapping[str, Any],
    current_tool_fingerprints: Mapping[str, str] | None,
    current_tool_commit: str | None,
) -> tuple[str, str]:
    current = current_tool_fingerprints or {}
    fresh_key = ""
    for key in _FINGERPRINT_KEYS:
        evidence_value = _stringify(evidence.get(f"terminal_attempt_{key}"))
        if not evidence_value:
            continue
        current_value = _stringify(current.get(key))
        if not current_value:
            continue
        if evidence_value != current_value:
            return "stale", f"stale-{key}"
        if not fresh_key:
            fresh_key = key

    evidence_commit = _stringify(evidence.get("terminal_attempt_tool_commit"))
    if evidence_commit and current_tool_commit:
        if evidence_commit != current_tool_commit:
            return "stale", "stale-tool_commit"
        return "active", "fresh-tool_commit"
    if fresh_key:
        return "active", f"fresh-{fresh_key}"

    return "active", "no-tooling-fingerprint"


def apply_terminal_attempt_overlay(
    raw: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Any]],
    *,
    current_tool_fingerprints: Mapping[str, str] | None = None,
    current_tool_commit: str | None = None,
) -> dict[str, str]:
    """Apply terminal attempt metadata to a taxonomy or harvest row."""
    row = {str(key): _stringify(value) for key, value in raw.items()}
    function = row.get("function", "")
    terminal = evidence.get(function)
    if terminal is None:
        return row

    status, stale_check = _stale_status(
        terminal,
        current_tool_fingerprints,
        current_tool_commit,
    )
    original_source_actionability = row.get("source_actionability", "")
    original_headline_tool = row.get("headline_tool", "")
    original_next_command = row.get("next_command", "")

    for key, value in terminal.items():
        if key == "terminal_attempt_status":
            continue
        row[str(key)] = _stringify(value)
    row["terminal_attempt_status"] = status
    row["terminal_attempt_stale_check"] = stale_check
    row["terminal_attempt_original_source_actionability"] = (
        original_source_actionability
    )
    row["terminal_attempt_original_headline_tool"] = original_headline_tool
    row["terminal_attempt_original_next_command"] = original_next_command

    if status == "stale":
        return row

    actionability = _stringify(terminal.get("terminal_attempt_actionability"))
    blocker = _stringify(terminal.get("terminal_attempt_blocker")) or "unknown"
    row["source_actionability"] = actionability
    row["headline_tool"] = "attempt-ledger"
    row["next_command"] = (
        f"melee-agent attempts show {function} --no-measure-current"
    )
    row["actionability_reason"] = (
        "attempt ledger terminal evidence: "
        f"blocker={blocker}; original_source_actionability="
        f"{original_source_actionability or 'unclassified'}"
    )
    return row


def is_active_terminal_attempt_row(raw: Mapping[str, Any]) -> bool:
    return str(raw.get("terminal_attempt_status") or "") == "active"
