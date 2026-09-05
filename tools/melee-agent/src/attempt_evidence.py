"""Attempt-ledger terminal evidence helpers (disabled).

The attempt ledger used to mark functions as terminal "dead ends"
(source-ceiling / tooling-blocked / diagnostic-only / manual-review) and have
the taxonomy and harvest function pickers demote or skip those rows. That
behavior has been removed: the attempt ledger no longer signals that any
function is a dead end, and never tells agents to stop working on a function.
Source provably exists for every function, so none is flagged as unworkable.

These helpers are retained as inert no-ops so existing call sites in
``harvest.py`` and ``function_taxonomy_inventory.py`` keep working without
demoting any row:

* ``load_terminal_attempt_evidence`` always returns ``{}`` (no function has
  terminal evidence), which makes both consumers early-return unchanged.
* ``apply_terminal_attempt_overlay`` returns the row unchanged.
* ``is_active_terminal_attempt_row`` is always ``False``.

``TERMINAL_ATTEMPT_FIELDS`` is kept so the taxonomy/queue CSV schema stays
stable; those columns are always emitted empty now.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

# Column names emitted by the taxonomy/harvest queues. Retained for CSV schema
# stability; always written empty now that terminal evidence is disabled.
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


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def load_terminal_attempt_evidence(
    path: Path | None = None,
    *,
    current_tool_fingerprints: Mapping[str, str] | None = None,
    current_tool_commit: str | None = None,
) -> dict[str, dict[str, str]]:
    """Disabled: the attempt ledger never marks a function as a dead end."""
    del path, current_tool_fingerprints, current_tool_commit
    return {}


def apply_terminal_attempt_overlay(
    raw: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Any]],
    *,
    current_tool_fingerprints: Mapping[str, str] | None = None,
    current_tool_commit: str | None = None,
) -> dict[str, str]:
    """Disabled: return the row unchanged (no terminal demotion applied)."""
    del evidence, current_tool_fingerprints, current_tool_commit
    return {str(key): _stringify(value) for key, value in raw.items()}


def is_active_terminal_attempt_row(raw: Mapping[str, Any]) -> bool:
    """Disabled: no row is ever an active terminal/dead-end attempt."""
    del raw
    return False
