"""
Mismatch Database Schema

Stores patterns discovered during decompilation matching, enabling
lookup by opcode, signal type, or full-text search.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path.home() / ".config" / "decomp-me" / "mismatch_patterns.db"

SCHEMA = """
-- Core pattern table
CREATE TABLE IF NOT EXISTS patterns (
    id TEXT PRIMARY KEY,              -- slug like "struct-field-copy"
    name TEXT NOT NULL,               -- "Copying Structs Field-by-Field"
    description TEXT,                 -- What the pattern looks like
    root_cause TEXT,                  -- Why it happens
    notes TEXT,                       -- Trade-offs, caveats

    -- Flexible nested data as JSON
    signals JSON,                     -- [{type, ...signal-specific fields}]
    examples JSON,                    -- [{diff, context, function, before, after}]
    fixes JSON,                       -- [{description, before, after, success_rate}]
    provenance JSON,                  -- {discovered_from: [], helped_match: []}
    related_patterns JSON,            -- ["slug1", "slug2"]

    -- Denormalized for fast filtering
    opcodes JSON,                     -- ["beq", "bne", "cmplwi"]
    categories JSON,                  -- ["branch", "control-flow", "stack"]

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Separate table for signal indexing (enables fast opcode lookups)
CREATE TABLE IF NOT EXISTS pattern_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id TEXT REFERENCES patterns(id) ON DELETE CASCADE,
    signal_type TEXT NOT NULL,        -- "opcode_mismatch", "offset_pattern", etc.
    signal_data JSON,                 -- type-specific payload

    -- Denormalized fields for common query patterns
    opcode_expected TEXT,             -- for opcode_mismatch type
    opcode_actual TEXT,
    m2c_artifact TEXT,                -- for m2c_artifact type (M2C_STRUCT_COPY, etc.)

    UNIQUE(pattern_id, signal_type, signal_data)
);

CREATE INDEX IF NOT EXISTS idx_signals_opcodes
    ON pattern_signals(opcode_expected, opcode_actual);
CREATE INDEX IF NOT EXISTS idx_signals_type
    ON pattern_signals(signal_type);
CREATE INDEX IF NOT EXISTS idx_signals_m2c
    ON pattern_signals(m2c_artifact);
CREATE INDEX IF NOT EXISTS idx_signals_pattern
    ON pattern_signals(pattern_id);

-- FTS5 for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS patterns_fts USING fts5(
    id, name, description, root_cause, notes,
    content='patterns',
    content_rowid='rowid'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS patterns_ai AFTER INSERT ON patterns BEGIN
    INSERT INTO patterns_fts(rowid, id, name, description, root_cause, notes)
    VALUES (NEW.rowid, NEW.id, NEW.name, NEW.description, NEW.root_cause, NEW.notes);
END;

CREATE TRIGGER IF NOT EXISTS patterns_ad AFTER DELETE ON patterns BEGIN
    INSERT INTO patterns_fts(patterns_fts, rowid, id, name, description, root_cause, notes)
    VALUES ('delete', OLD.rowid, OLD.id, OLD.name, OLD.description, OLD.root_cause, OLD.notes);
END;

CREATE TRIGGER IF NOT EXISTS patterns_au AFTER UPDATE ON patterns BEGIN
    INSERT INTO patterns_fts(patterns_fts, rowid, id, name, description, root_cause, notes)
    VALUES ('delete', OLD.rowid, OLD.id, OLD.name, OLD.description, OLD.root_cause, OLD.notes);
    INSERT INTO patterns_fts(rowid, id, name, description, root_cause, notes)
    VALUES (NEW.rowid, NEW.id, NEW.name, NEW.description, NEW.root_cause, NEW.notes);
END;

-- =============================================================================
-- BACKFILL STAGING TABLES
-- =============================================================================

-- Backfill jobs track orchestrator runs
CREATE TABLE IF NOT EXISTS backfill_jobs (
    id TEXT PRIMARY KEY,              -- UUID
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    config JSON,                      -- {commit_range, batch_size, ...}

    total_commits INTEGER DEFAULT 0,
    processed_commits INTEGER DEFAULT 0,
    candidates_found INTEGER DEFAULT 0,

    started_at TEXT,
    completed_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT
);

-- Analysis tasks are individual work items for subagents
CREATE TABLE IF NOT EXISTS analysis_tasks (
    id TEXT PRIMARY KEY,              -- UUID
    job_id TEXT REFERENCES backfill_jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, assigned, completed, failed

    -- What to analyze
    commit_sha TEXT NOT NULL,
    commit_message TEXT,
    commit_date TEXT,
    function_name TEXT,
    file_path TEXT,

    -- Analysis inputs (populated before agent runs)
    m2c_source TEXT,                  -- Decompiler output
    final_source TEXT,                -- Matched code from repo
    asm_diff TEXT,                    -- Assembly diff if available

    -- Analysis outputs (populated by agent)
    agent_id TEXT,                    -- Which agent worked on this
    analysis_notes TEXT,              -- Agent's reasoning

    assigned_at TEXT,
    completed_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tasks_job ON analysis_tasks(job_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON analysis_tasks(status);

-- Candidate patterns discovered by agents (staging before approval)
CREATE TABLE IF NOT EXISTS candidate_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    job_id TEXT REFERENCES backfill_jobs(id) ON DELETE CASCADE,

    status TEXT NOT NULL DEFAULT 'pending',  -- pending, approved, rejected, merged

    -- Pattern data (same structure as patterns table)
    suggested_id TEXT,                -- Agent's suggested slug
    name TEXT NOT NULL,
    description TEXT,
    root_cause TEXT,
    notes TEXT,
    signals JSON,
    examples JSON,
    fixes JSON,
    opcodes JSON,
    categories JSON,

    -- Source tracking
    source_function TEXT,             -- Function where discovered
    source_commit TEXT,               -- Commit SHA
    confidence REAL,                  -- Agent's confidence 0.0-1.0

    -- Review tracking
    reviewed_by TEXT,                 -- Human or agent reviewer
    reviewed_at TEXT,
    review_notes TEXT,
    merged_into TEXT,                 -- If merged into existing pattern
    approved_pattern_id TEXT,         -- ID if approved as new pattern

    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidate_patterns(status);
CREATE INDEX IF NOT EXISTS idx_candidates_job ON candidate_patterns(job_id);

-- Similar candidates grouping (for merge suggestions)
CREATE TABLE IF NOT EXISTS candidate_similarity (
    candidate_a INTEGER REFERENCES candidate_patterns(id) ON DELETE CASCADE,
    candidate_b INTEGER REFERENCES candidate_patterns(id) ON DELETE CASCADE,
    similarity_score REAL,            -- 0.0-1.0
    similarity_reason TEXT,           -- Why they're similar
    PRIMARY KEY (candidate_a, candidate_b)
);
"""

# Signal type definitions for validation and documentation
SIGNAL_TYPES = {
    "opcode_mismatch": {
        "description": "Single instruction differs",
        "fields": ["expected", "actual"],
        "example": {"expected": "beq", "actual": "bne"},
    },
    "opcode_pair_swap": {
        "description": "Two instructions in wrong order",
        "fields": ["opcodes", "description"],
        "example": {"opcodes": ["addi", "cmpwi"], "description": "increment before vs after compare"},
    },
    "offset_delta": {
        "description": "Stack/struct offsets shifted uniformly",
        "fields": ["register", "delta"],
        "example": {"register": "r1", "delta": 8},
    },
    "instruction_sequence": {
        "description": "Pattern of opcodes appears",
        "fields": ["sequence", "description"],
        "example": {"sequence": ["lwz", "mr", "stw"], "description": "load-move-store pattern"},
    },
    "register_class": {
        "description": "Wrong register category",
        "fields": ["expected_class", "actual_class"],
        "example": {"expected_class": "gpr", "actual_class": "fpr"},
    },
    "extra_instruction": {
        "description": "Unexpected instruction inserted",
        "fields": ["opcode", "context"],
        "example": {"opcode": "mr", "context": "after inline return"},
    },
    "m2c_artifact": {
        "description": "m2c decompiler produces specific construct",
        "fields": ["artifact", "description"],
        "example": {"artifact": "M2C_STRUCT_COPY", "description": "repeated struct copy calls"},
    },
    "stack_size": {
        "description": "Stack frame size mismatch",
        "fields": ["expected", "actual"],
        "example": {"expected": 0x28, "actual": 0x20},
    },
    "branch_polarity": {
        "description": "Branch condition inverted",
        "fields": ["expected", "actual", "context"],
        "example": {"expected": "bne", "actual": "beq", "context": "NULL check"},
    },
}

# Categories for organizing patterns
CATEGORIES = [
    "stack",  # Stack size, variable placement
    "branch",  # Branch polarity, conditions
    "control-flow",  # Loops, if-else, ternary
    "register",  # Register allocation, callee-saved
    "inline",  # Inline function issues
    "struct",  # Struct copy, field access
    "type",  # Type casting, signedness
    "float",  # Floating point operations
    "bitfield",  # Bitfield access
    "loop",  # Loop unrolling, increment order
    "calling-conv",  # Calling convention, varargs
    "data-layout",  # String addressing, data placement
]


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Initialize the database with schema."""
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Get a database connection."""
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    if not db_path.exists():
        return init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
