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

_MIGRATED_PATTERN_ROWS = [
    {
        "id": "sparse-scratch-array-no-zero-init",
        "name": "Sparse Scratch Array Without Zero Initialization",
        "description": (
            "A fixed-size scratch array passed to a type-dispatched consumer "
            "should be declared bare, not initialized with `= {0}`, when the "
            "target only stores selected fields."
        ),
        "root_cause": (
            "m2c often reconstructs command buffers as zero-initialized "
            "records, but MWCC emits a separate zeroing block and then "
            "overwrites fields. The original source writes only the fields "
            "required by the command type, leaving omitted fields dirty."
        ),
        "notes": (
            "Use this only when checkdiff says current is larger. If expected "
            "is larger or an inline boundary dominates, removing instructions "
            "can falsely raise fuzzy match while collapsing opcode similarity."
        ),
        "signals": [
            {
                "type": "instruction_sequence",
                "description": "Sparse stores into a stack array before a consumer call",
                "sequence": ["stw", "stw", "bl"],
            },
            {
                "type": "code_smell",
                "description": "Zero-initialized fixed-size local command buffer",
                "pattern": "s32 cmd[N] = {0}",
            },
        ],
        "examples": [
            {"function": "fn_803B0E9C", "context": "hsd_3AA7.c command buffer builder"},
            {"function": "fn_803ADF90", "context": "Same sparse scratch array class"},
            {"function": "fn_803AD16C", "context": "Opcode similarity improved after removing zero initialization"},
        ],
        "fixes": [
            {
                "description": (
                    "Drop `= {0}`, declare the fixed-size array bare, and "
                    "write exactly the fields the target stores, including "
                    "explicit zero stores that are present in the target."
                ),
                "before": "s32 cmd[9] = { 0 };",
                "after": "s32 cmd[9];",
                "success_rate": 0.75,
            }
        ],
        "provenance": {
            "discovered_from": [
                {"function": "fn_803B0E9C", "date": "2026-06-04"},
                {"function": "fn_803ADF90", "date": "2026-06-04"},
                {"function": "fn_803AD16C", "date": "2026-06-04"},
            ],
            "helped_match": [],
        },
        "related_patterns": [],
        "opcodes": ["stw", "bl"],
        "categories": ["stack", "array", "source-transform"],
    },
    {
        "id": "loop-field-reload-comma-assignment",
        "name": "Loop Field Reload Via For-Condition Comma Assignment",
        "description": (
            "A struct field reloaded every loop iteration and reused in the "
            "loop body can be modeled with a for-condition comma assignment "
            "so one reload feeds both condition and body, coalescing the uses "
            "into one callee-save."
        ),
        "root_cause": (
            "Plain C that reads a struct field in both the condition and body "
            "can make MWCC emit two reloads. Assigning a local in the for "
            "condition creates the target's single per-iteration reload and "
            "callee-save reuse."
        ),
        "notes": (
            "Useful when the target reloads the field once per iteration and "
            "coalesces the reload into one callee-save. Remaining differences "
            "may still be register numbering."
        ),
        "signals": [
            {
                "type": "instruction_sequence",
                "description": "One field reload reused for loop bound, offset math, and callee argument",
                "sequence": ["lwz", "divw", "mullw", "bl"],
            }
        ],
        "examples": [
            {"function": "fn_803ACD58", "context": "CardState loop reloads state->x8 each iteration"},
        ],
        "fixes": [
            {
                "description": (
                    "Introduce a loop-local size variable assigned in the "
                    "for-condition comma expression, then reuse that local in "
                    "the condition and body."
                ),
                "success_rate": 0.6,
            }
        ],
        "provenance": {
            "discovered_from": [
                {"function": "fn_803ACD58", "date": "2026-06-04"},
            ],
            "helped_match": [],
        },
        "related_patterns": [],
        "opcodes": ["lwz", "mullw", "divw"],
        "categories": ["loop", "register", "source-transform"],
    },
    {
        "id": "inverse-cse-rematerialized-global-read",
        "name": "Inverse CSE Rematerialized Global Read",
        "description": (
            "The target rematerializes or must rematerialize a non-volatile "
            "global read, while source forms that reuse the obvious local "
            "make MWCC CSE the reads and collapse distinct register roles."
        ),
        "root_cause": (
            "Some targets reload a non-volatile global for a later array index "
            "while keeping a prior value live across a call. Natural C "
            "expressions that index by the saved local can make MWCC "
            "common-subexpression-eliminate the second read."
        ),
        "notes": (
            "A ceiling characterization as much as a lever. It is the inverse "
            "of the usual source-rematerializes/target-CSEs mismatch."
        ),
        "signals": [
            {
                "type": "instruction_sequence",
                "description": "A global is read, a call occurs, then the same global is read again for indexing",
                "sequence": ["lwz", "bl", "lwz"],
            }
        ],
        "examples": [
            {"function": "fn_803AC168", "context": "CardState read index and hsd_804D1148 indexing"},
        ],
        "fixes": [
            {
                "description": (
                    "Confirm the target really rematerializes instead of "
                    "CSEing. If ordinary locals CSE the reads, try source "
                    "forms that force a distinct reload; if no C lever exists, "
                    "bank the ceiling rather than chasing register cascades."
                ),
                "success_rate": 0.2,
            }
        ],
        "provenance": {
            "discovered_from": [
                {"function": "fn_803AC168", "date": "2026-06-04"},
            ],
            "helped_match": [],
        },
        "related_patterns": [],
        "opcodes": ["lwz", "bl"],
        "categories": ["global", "register", "ceiling"],
    },
]


def _signal_payload(signal: dict) -> dict:
    return {
        key: value
        for key, value in signal.items()
        if key not in {"type", "description"}
    }


def _insert_missing_pattern_row(conn: sqlite3.Connection, row: dict) -> None:
    cursor = conn.execute(
        """
        INSERT INTO patterns (
            id, name, description, root_cause, notes, signals, examples,
            fixes, provenance, related_patterns, opcodes, categories
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (
            row["id"],
            row["name"],
            row["description"],
            row["root_cause"],
            row["notes"],
            json.dumps(row["signals"]),
            json.dumps(row["examples"]),
            json.dumps(row["fixes"]),
            json.dumps(row["provenance"]),
            json.dumps(row["related_patterns"]),
            json.dumps(row["opcodes"]),
            json.dumps(row["categories"]),
        ),
    )
    if cursor.rowcount == 0:
        return
    conn.execute("DELETE FROM pattern_signals WHERE pattern_id = ?", (row["id"],))
    for signal in row["signals"]:
        signal_type = signal["type"]
        payload = _signal_payload(signal)
        conn.execute(
            """
            INSERT OR IGNORE INTO pattern_signals
                (pattern_id, signal_type, signal_data, opcode_expected, opcode_actual, m2c_artifact)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                signal_type,
                json.dumps(payload),
                payload.get("expected") if signal_type == "opcode_mismatch" else None,
                payload.get("actual") if signal_type == "opcode_mismatch" else None,
                payload.get("artifact") if signal_type == "m2c_artifact" else None,
            ),
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
    for row in _MIGRATED_PATTERN_ROWS:
        _insert_missing_pattern_row(conn, row)
    conn.commit()
