"""Data corrections for persisted mismatch-db rows."""

from __future__ import annotations

import json
import sqlite3


_REGISTER_KEYWORD_PATTERN_ID = "register-keyword-respected-by-mwcc"
_REGISTER_KEYWORD_NAME = (
    "`register` keyword is not a reliable MWCC allocation hint in this repo"
)
_REGISTER_KEYWORD_DESCRIPTION = (
    "For the MWCC 1.2.5n compiler configuration used by this Melee repo, "
    "the C `register` keyword does not respect allocation-hint intent in "
    "ordinary source. Probes that only add `register` should be treated as "
    "expected no-ops for allocator mismatches."
)
_REGISTER_KEYWORD_ROOT_CAUSE = (
    "The old entry generalized from other MWCC folklore, but this compiler "
    "configuration does not use `register` as a useful allocator hint for "
    "normal C variables. Register allocation changes need source-shape, "
    "lifetime, type, or control-flow changes instead."
)
_REGISTER_KEYWORD_FIXES = [
    {
        "description": (
            "Do not spend time adding `register` as an allocator probe in "
            "this repo. If a value needs a different physical register, use "
            "lifetime-layout, declaration/source-shape probes, or a targeted "
            "allocator diagnostic instead."
        ),
        "success_rate": 0.0,
    }
]
_REGISTER_KEYWORD_EXAMPLES = [
    {
        "function": "ftCo_8009E7B4",
        "context": (
            "Manual `register` probes scored neutral and did not alter the "
            "relevant allocator result."
        ),
    }
]
_REGISTER_KEYWORD_NOTES = (
    "Corrected after ftCo_8009E7B4 probe batch: register_flag_reload and "
    "register_i_tree_success were unchanged at 99.44976."
)


def apply_pattern_corrections(conn: sqlite3.Connection) -> None:
    """Apply small data fixes to existing user mismatch pattern databases."""
    examples_json = json.dumps(_REGISTER_KEYWORD_EXAMPLES)
    fixes_json = json.dumps(_REGISTER_KEYWORD_FIXES)
    cursor = conn.execute(
        """
        UPDATE patterns
        SET name = ?,
            description = ?,
            root_cause = ?,
            notes = ?,
            examples = ?,
            fixes = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
          AND (
            COALESCE(name, '') != ?
            OR COALESCE(description, '') != ?
            OR COALESCE(root_cause, '') != ?
            OR COALESCE(notes, '') != ?
            OR COALESCE(examples, '') != ?
            OR COALESCE(fixes, '') != ?
          )
        """,
        (
            _REGISTER_KEYWORD_NAME,
            _REGISTER_KEYWORD_DESCRIPTION,
            _REGISTER_KEYWORD_ROOT_CAUSE,
            _REGISTER_KEYWORD_NOTES,
            examples_json,
            fixes_json,
            _REGISTER_KEYWORD_PATTERN_ID,
            _REGISTER_KEYWORD_NAME,
            _REGISTER_KEYWORD_DESCRIPTION,
            _REGISTER_KEYWORD_ROOT_CAUSE,
            _REGISTER_KEYWORD_NOTES,
            examples_json,
            fixes_json,
        ),
    )
    if cursor.rowcount:
        conn.execute(
            "DELETE FROM pattern_signals WHERE pattern_id = ?",
            (_REGISTER_KEYWORD_PATTERN_ID,),
        )
        conn.commit()
