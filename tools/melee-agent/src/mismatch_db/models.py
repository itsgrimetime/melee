"""
Mismatch Pattern Models and Operations
"""

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

from .schema import CATEGORIES, SIGNAL_TYPES, get_db


@dataclass
class Signal:
    """A signal that helps identify a pattern."""

    type: str
    data: dict
    description: str | None = None

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "description": self.description,
            **self.data,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Signal":
        type_ = d.pop("type")
        desc = d.pop("description", None)
        return cls(type=type_, data=d, description=desc)


@dataclass
class Example:
    """An example of the pattern in practice."""

    function: str
    context: str | None = None
    diff: str | None = None
    before: str | None = None  # Code before fix
    after: str | None = None  # Code after fix
    scratch: str | None = None  # decomp.me scratch slug

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict) -> "Example":
        return cls(**d)


@dataclass
class Fix:
    """A fix for the pattern."""

    description: str
    before: str | None = None
    after: str | None = None
    success_rate: float | None = None  # 0.0-1.0

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict) -> "Fix":
        return cls(**d)


@dataclass
class ProvenanceEntry:
    """A record of where a pattern was discovered or helped."""

    function: str
    date: str | None = None
    scratch: str | None = None
    pr: str | None = None  # PR URL or number

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict) -> "ProvenanceEntry":
        return cls(**d)


@dataclass
class Provenance:
    """Provenance tracking for a pattern."""

    discovered_from: list[ProvenanceEntry] = field(default_factory=list)
    helped_match: list[ProvenanceEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "discovered_from": [e.to_dict() for e in self.discovered_from],
            "helped_match": [e.to_dict() for e in self.helped_match],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Provenance":
        return cls(
            discovered_from=[ProvenanceEntry.from_dict(e) for e in d.get("discovered_from", [])],
            helped_match=[ProvenanceEntry.from_dict(e) for e in d.get("helped_match", [])],
        )


@dataclass
class Pattern:
    """A mismatch pattern."""

    id: str
    name: str
    description: str
    root_cause: str
    signals: list[Signal] = field(default_factory=list)
    examples: list[Example] = field(default_factory=list)
    fixes: list[Fix] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)
    related_patterns: list[str] = field(default_factory=list)
    opcodes: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    notes: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "root_cause": self.root_cause,
            "notes": self.notes,
            "signals": [s.to_dict() for s in self.signals],
            "examples": [e.to_dict() for e in self.examples],
            "fixes": [f.to_dict() for f in self.fixes],
            "provenance": self.provenance.to_dict(),
            "related_patterns": self.related_patterns,
            "opcodes": self.opcodes,
            "categories": self.categories,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Pattern":
        return cls(
            id=d["id"],
            name=d["name"],
            description=d.get("description", ""),
            root_cause=d.get("root_cause", ""),
            notes=d.get("notes"),
            signals=[Signal.from_dict(s) for s in d.get("signals", [])],
            examples=[Example.from_dict(e) for e in d.get("examples", [])],
            fixes=[Fix.from_dict(f) for f in d.get("fixes", [])],
            provenance=Provenance.from_dict(d.get("provenance", {})),
            related_patterns=d.get("related_patterns", []),
            opcodes=d.get("opcodes", []),
            categories=d.get("categories", []),
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Pattern":
        """Create a Pattern from a database row."""
        return cls(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            root_cause=row["root_cause"] or "",
            notes=row["notes"],
            signals=[Signal.from_dict(s) for s in json.loads(row["signals"] or "[]")],
            examples=[Example.from_dict(e) for e in json.loads(row["examples"] or "[]")],
            fixes=[Fix.from_dict(f) for f in json.loads(row["fixes"] or "[]")],
            provenance=Provenance.from_dict(json.loads(row["provenance"] or "{}")),
            related_patterns=json.loads(row["related_patterns"] or "[]"),
            opcodes=json.loads(row["opcodes"] or "[]"),
            categories=json.loads(row["categories"] or "[]"),
        )


class PatternDB:
    """Database operations for patterns."""

    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = conn or get_db()

    def insert(self, pattern: Pattern) -> None:
        """Insert a new pattern."""
        d = pattern.to_dict()
        self.conn.execute(
            """
            INSERT INTO patterns (id, name, description, root_cause, notes,
                                  signals, examples, fixes, provenance,
                                  related_patterns, opcodes, categories)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                d["id"],
                d["name"],
                d["description"],
                d["root_cause"],
                d["notes"],
                json.dumps(d["signals"]),
                json.dumps(d["examples"]),
                json.dumps(d["fixes"]),
                json.dumps(d["provenance"]),
                json.dumps(d["related_patterns"]),
                json.dumps(d["opcodes"]),
                json.dumps(d["categories"]),
            ),
        )

        # Index signals
        for signal in pattern.signals:
            self._index_signal(pattern.id, signal)

        self.conn.commit()

    def _index_signal(self, pattern_id: str, signal: Signal) -> None:
        """Index a signal for fast lookup."""
        opcode_expected = None
        opcode_actual = None
        m2c_artifact = None

        if signal.type == "opcode_mismatch":
            opcode_expected = signal.data.get("expected")
            opcode_actual = signal.data.get("actual")
        elif signal.type == "m2c_artifact":
            m2c_artifact = signal.data.get("artifact")

        self.conn.execute(
            """
            INSERT OR IGNORE INTO pattern_signals
                (pattern_id, signal_type, signal_data, opcode_expected, opcode_actual, m2c_artifact)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                pattern_id,
                signal.type,
                json.dumps(signal.data),
                opcode_expected,
                opcode_actual,
                m2c_artifact,
            ),
        )

    def get(self, pattern_id: str) -> Pattern | None:
        """Get a pattern by ID."""
        row = self.conn.execute("SELECT * FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if row is None:
            return None
        return Pattern.from_row(row)

    def list_all(self) -> list[Pattern]:
        """List all patterns."""
        rows = self.conn.execute("SELECT * FROM patterns ORDER BY name").fetchall()
        return [Pattern.from_row(row) for row in rows]

    def search_by_opcode(self, expected: str, actual: str) -> list[Pattern]:
        """Find patterns by opcode mismatch."""
        rows = self.conn.execute(
            """
            SELECT DISTINCT p.* FROM patterns p
            JOIN pattern_signals s ON p.id = s.pattern_id
            WHERE s.opcode_expected = ? AND s.opcode_actual = ?
            """,
            (expected, actual),
        ).fetchall()
        return [Pattern.from_row(row) for row in rows]

    def search_by_m2c_artifact(self, artifact: str) -> list[Pattern]:
        """Find patterns by m2c artifact."""
        rows = self.conn.execute(
            """
            SELECT DISTINCT p.* FROM patterns p
            JOIN pattern_signals s ON p.id = s.pattern_id
            WHERE s.m2c_artifact = ?
            """,
            (artifact,),
        ).fetchall()
        return [Pattern.from_row(row) for row in rows]

    def search_by_signal_type(self, signal_type: str) -> list[Pattern]:
        """Find patterns by signal type."""
        rows = self.conn.execute(
            """
            SELECT DISTINCT p.* FROM patterns p
            JOIN pattern_signals s ON p.id = s.pattern_id
            WHERE s.signal_type = ?
            """,
            (signal_type,),
        ).fetchall()
        return [Pattern.from_row(row) for row in rows]

    def search_by_category(self, category: str) -> list[Pattern]:
        """Find patterns by category."""
        rows = self.conn.execute(
            """
            SELECT * FROM patterns
            WHERE json_extract(categories, '$') LIKE ?
            ORDER BY name
            """,
            (f'%"{category}"%',),
        ).fetchall()
        return [Pattern.from_row(row) for row in rows]

    def search_fulltext(self, query: str) -> list[Pattern]:
        """Full-text search across pattern content."""
        rows = self.conn.execute(
            """
            SELECT p.* FROM patterns p
            JOIN patterns_fts fts ON p.rowid = fts.rowid
            WHERE patterns_fts MATCH ?
            ORDER BY rank
            """,
            (query,),
        ).fetchall()
        return [Pattern.from_row(row) for row in rows]

    def record_success(self, pattern_id: str, function: str, scratch: str | None = None) -> None:
        """Record that a pattern helped match a function."""
        pattern = self.get(pattern_id)
        if pattern is None:
            return

        entry = ProvenanceEntry(
            function=function,
            date=datetime.now().isoformat()[:10],
            scratch=scratch,
        )
        pattern.provenance.helped_match.append(entry)

        self.conn.execute(
            """
            UPDATE patterns
            SET provenance = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json.dumps(pattern.provenance.to_dict()), pattern_id),
        )
        self.conn.commit()

    def delete(self, pattern_id: str) -> bool:
        """Delete a pattern."""
        cursor = self.conn.execute("DELETE FROM patterns WHERE id = ?", (pattern_id,))
        self.conn.commit()
        return cursor.rowcount > 0
