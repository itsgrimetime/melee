from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from .types import Case, CaseResult

DEFAULT_DB_PATH = Path.home() / ".config" / "decomp-me" / "backtest_results.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_cases (
    case_id TEXT PRIMARY KEY,
    function TEXT NOT NULL, c_sha TEXT NOT NULL, cprev_sha TEXT NOT NULL,
    unit TEXT, file TEXT, ground_truth_diff TEXT, lever_locus TEXT,
    author TEXT, provenance TEXT, lever_class TEXT,
    baseline_pct REAL, baseline_ndl INTEGER, target_pct REAL, target_ndl INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cases_provenance ON backtest_cases(provenance);
CREATE INDEX IF NOT EXISTS idx_cases_lever ON backtest_cases(lever_class);
CREATE TABLE IF NOT EXISTS backtest_results (
    case_id TEXT PRIMARY KEY REFERENCES backtest_cases(case_id) ON DELETE CASCADE,
    advisory TEXT, generative TEXT, agent TEXT, rollup TEXT,
    evidence JSON, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class BacktestStore:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def ensure_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def insert_case(self, case: Case) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO backtest_cases
               (case_id, function, c_sha, cprev_sha, unit, file, ground_truth_diff,
                lever_locus, author, provenance, lever_class, baseline_pct, baseline_ndl,
                target_pct, target_ndl)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (case.case_id, case.function, case.c_sha, case.cprev_sha, case.unit, case.file,
             case.ground_truth_diff, case.lever_locus, case.author, case.provenance,
             case.lever_class, case.baseline_pct, case.baseline_ndl, case.target_pct,
             case.target_ndl),
        )
        self.conn.commit()

    def get_case(self, case_id: str):
        row = self.conn.execute("SELECT * FROM backtest_cases WHERE case_id=?", (case_id,)).fetchone()
        return dict(row) if row else None

    def list_cases(self, provenance: Optional[str] = None) -> list:
        if provenance:
            rows = self.conn.execute("SELECT * FROM backtest_cases WHERE provenance=?", (provenance,)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM backtest_cases").fetchall()
        return [dict(r) for r in rows]

    def upsert_result(self, result: CaseResult) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO backtest_results
               (case_id, advisory, generative, agent, rollup, evidence)
               VALUES (?,?,?,?,?,?)""",
            (result.case_id, result.advisory, result.generative, result.agent,
             result.rollup, json.dumps(result.evidence)),
        )
        self.conn.commit()

    def results(self) -> list:
        return [dict(r) for r in self.conn.execute("SELECT * FROM backtest_results").fetchall()]

    def get_result(self, case_id: str) -> "dict | None":
        row = self.conn.execute(
            "SELECT * FROM backtest_results WHERE case_id=?", (case_id,)
        ).fetchone()
        return dict(row) if row else None
