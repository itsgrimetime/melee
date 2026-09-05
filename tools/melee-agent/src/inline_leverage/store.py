from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .types import LeverageRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS inline_leverage (
  id INTEGER PRIMARY KEY,
  run_id TEXT, function TEXT, unit TEXT, inline_name TEXT,
  def_location TEXT, def_file TEXT, is_static INTEGER, n_call_sites INTEGER,
  baseline_pct REAL, deinlined_pct REAL, delta_fuzzy REAL,
  baseline_ndl INTEGER, deinlined_ndl INTEGER, delta_struct INTEGER,
  verdict TEXT, expansion_form TEXT, shape_return TEXT, shape_body TEXT,
  shape_args TEXT, n_statements INTEGER, error TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS inline_leverage_seen (
  tu_hash TEXT, function TEXT, inline_name TEXT,
  PRIMARY KEY (tu_hash, function, inline_name)
);
"""


class InlineLeverageStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row

    def ensure_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def insert(self, rec: LeverageRecord) -> None:
        row = rec.to_row()
        row["created_at"] = datetime.now(timezone.utc).isoformat()
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        self._conn.execute(
            f"INSERT INTO inline_leverage ({cols}) VALUES ({placeholders})",
            list(row.values()),
        )
        self._conn.commit()

    def seen(self, tu_hash: str, function: str, inline_name: str) -> bool:
        cur = self._conn.execute(
            """
            SELECT 1 FROM inline_leverage_seen
            WHERE tu_hash=? AND function=? AND inline_name=?
            """,
            (tu_hash, function, inline_name),
        )
        return cur.fetchone() is not None

    def mark_seen(self, tu_hash: str, function: str, inline_name: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO inline_leverage_seen VALUES (?,?,?)",
            (tu_hash, function, inline_name),
        )
        self._conn.commit()

    def records(self, run_id: str) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM inline_leverage WHERE run_id=? ORDER BY id",
            (run_id,),
        )
        return [dict(row) for row in cur.fetchall()]
