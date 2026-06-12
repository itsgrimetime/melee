"""
SQLite storage for the opcode synthesis database.

Stores compiled samples and provides lookup by opcode sequences.
"""

import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional

from .opcodes import OpcodeSequence, parse_mnemonic_sequence


@dataclass
class SampleRecord:
    """A stored sample."""

    id: int
    source: str
    template_name: str
    context_name: str
    mnemonics: str  # Comma-separated
    normalized: str  # Comma-separated
    mnemonic_hash: str
    normalized_hash: str
    asm: str


@dataclass
class MatchResult:
    """A search result."""

    sample: SampleRecord
    score: float
    match_type: str  # "exact", "hash", "ngram", "fuzzy"
    match_details: dict


class OpcodeDB:
    """SQLite database for opcode samples."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                template_name TEXT,
                context_name TEXT,
                mnemonics TEXT NOT NULL,
                normalized TEXT NOT NULL,
                mnemonic_hash TEXT NOT NULL,
                normalized_hash TEXT NOT NULL,
                asm TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_mnemonic_hash ON samples(mnemonic_hash);
            CREATE INDEX IF NOT EXISTS idx_normalized_hash ON samples(normalized_hash);
            CREATE INDEX IF NOT EXISTS idx_template ON samples(template_name);

            -- N-gram index for subsequence matching
            CREATE TABLE IF NOT EXISTS ngrams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ngram TEXT NOT NULL,
                sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                is_normalized INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_ngram ON ngrams(ngram);
            CREATE INDEX IF NOT EXISTS idx_ngram_sample ON ngrams(sample_id);

            -- Metadata table
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        self.conn.commit()

    def insert_sample(
        self,
        source: str,
        opcodes: OpcodeSequence,
        template_name: str = "",
        context_name: str = "",
        asm: str = "",
        ngram_size: int = 3,
    ) -> int:
        """
        Insert a compiled sample into the database.

        Returns the sample ID.
        """
        cursor = self.conn.execute(
            """INSERT INTO samples
               (source, template_name, context_name, mnemonics, normalized,
                mnemonic_hash, normalized_hash, asm)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source,
                template_name,
                context_name,
                ",".join(opcodes.mnemonics),
                ",".join(opcodes.normalized),
                opcodes.mnemonic_hash,
                opcodes.normalized_hash,
                asm,
            ),
        )
        sample_id = cursor.lastrowid

        # Index n-grams for fuzzy matching
        for i, ngram in enumerate(opcodes.get_ngrams(ngram_size)):
            self.conn.execute(
                "INSERT INTO ngrams (ngram, sample_id, position, is_normalized) VALUES (?, ?, ?, 0)",
                (ngram, sample_id, i),
            )

        for i, ngram in enumerate(opcodes.get_normalized_ngrams(ngram_size)):
            self.conn.execute(
                "INSERT INTO ngrams (ngram, sample_id, position, is_normalized) VALUES (?, ?, ?, 1)",
                (ngram, sample_id, i),
            )

        self.conn.commit()
        return sample_id

    def _row_to_sample(self, row: sqlite3.Row) -> SampleRecord:
        """Convert database row to SampleRecord."""
        return SampleRecord(
            id=row["id"],
            source=row["source"],
            template_name=row["template_name"],
            context_name=row["context_name"],
            mnemonics=row["mnemonics"],
            normalized=row["normalized"],
            mnemonic_hash=row["mnemonic_hash"],
            normalized_hash=row["normalized_hash"],
            asm=row["asm"],
        )

    def find_by_hash(self, opcodes: OpcodeSequence) -> list[MatchResult]:
        """Find samples by exact hash match."""
        results = []

        # Try mnemonic hash
        rows = self.conn.execute("SELECT * FROM samples WHERE mnemonic_hash = ?", (opcodes.mnemonic_hash,)).fetchall()

        for row in rows:
            sample = self._row_to_sample(row)
            results.append(
                MatchResult(
                    sample=sample,
                    score=1.0,
                    match_type="hash",
                    match_details={"hash_type": "mnemonic"},
                )
            )

        # If no mnemonic hash match, try normalized hash
        if not results:
            rows = self.conn.execute(
                "SELECT * FROM samples WHERE normalized_hash = ?", (opcodes.normalized_hash,)
            ).fetchall()

            for row in rows:
                sample = self._row_to_sample(row)
                results.append(
                    MatchResult(
                        sample=sample,
                        score=0.95,
                        match_type="hash",
                        match_details={"hash_type": "normalized"},
                    )
                )

        return results

    def find_by_ngrams(
        self,
        opcodes: OpcodeSequence,
        ngram_size: int = 3,
        limit: int = 20,
    ) -> list[MatchResult]:
        """Find samples by n-gram overlap."""
        query_ngrams = set(opcodes.get_ngrams(ngram_size))

        if not query_ngrams:
            return []

        # Find samples that share ngrams
        placeholders = ",".join("?" * len(query_ngrams))
        rows = self.conn.execute(
            f"""
            SELECT s.*, COUNT(DISTINCT n.ngram) as ngram_matches
            FROM samples s
            JOIN ngrams n ON s.id = n.sample_id
            WHERE n.ngram IN ({placeholders}) AND n.is_normalized = 0
            GROUP BY s.id
            ORDER BY ngram_matches DESC
            LIMIT ?
        """,
            (*query_ngrams, limit),
        ).fetchall()

        results = []
        for row in rows:
            sample = self._row_to_sample(row)
            sample_ngrams = set(sample.mnemonics.split(","))

            # Calculate Jaccard-like score
            matching = row["ngram_matches"]
            total = len(query_ngrams)
            score = matching / total if total > 0 else 0

            results.append(
                MatchResult(
                    sample=sample,
                    score=score,
                    match_type="ngram",
                    match_details={
                        "matching_ngrams": matching,
                        "total_query_ngrams": total,
                    },
                )
            )

        return results

    def find_by_fuzzy(
        self,
        opcodes: OpcodeSequence,
        min_score: float = 0.5,
        limit: int = 20,
    ) -> list[MatchResult]:
        """Find samples by fuzzy sequence matching."""
        query_mnemonics = opcodes.mnemonics

        # Get candidate samples (limit to reasonable set)
        rows = self.conn.execute("SELECT * FROM samples ORDER BY RANDOM() LIMIT 1000").fetchall()

        results = []
        for row in rows:
            sample = self._row_to_sample(row)
            sample_mnemonics = sample.mnemonics.split(",")

            # Calculate sequence similarity
            mnemonic_sim = SequenceMatcher(None, query_mnemonics, sample_mnemonics).ratio()

            if mnemonic_sim >= min_score:
                # Also check normalized similarity
                normalized_sim = SequenceMatcher(None, opcodes.normalized, sample.normalized.split(",")).ratio()

                # Combined score
                score = mnemonic_sim * 0.6 + normalized_sim * 0.4

                results.append(
                    MatchResult(
                        sample=sample,
                        score=score,
                        match_type="fuzzy",
                        match_details={
                            "mnemonic_similarity": mnemonic_sim,
                            "normalized_similarity": normalized_sim,
                        },
                    )
                )

        # Sort by score and limit
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def search(
        self,
        opcodes: OpcodeSequence,
        limit: int = 10,
    ) -> list[MatchResult]:
        """
        Search for samples matching an opcode sequence.

        Tries multiple strategies in order:
        1. Exact hash match
        2. N-gram overlap
        3. Fuzzy sequence matching

        Returns results sorted by score.
        """
        # Try exact hash first
        results = self.find_by_hash(opcodes)
        if results:
            return results[:limit]

        # Try n-gram matching
        results = self.find_by_ngrams(opcodes, limit=limit * 2)
        if results:
            return results[:limit]

        # Fall back to fuzzy matching
        return self.find_by_fuzzy(opcodes, limit=limit)

    def search_by_mnemonic_string(
        self,
        mnemonic_seq: str,
        limit: int = 10,
    ) -> list[MatchResult]:
        """
        Search by a comma-separated mnemonic sequence string.

        Example: "beq,mr,lwz,addi"
        """
        mnemonics = parse_mnemonic_sequence(mnemonic_seq)
        opcodes = OpcodeSequence(
            raw=mnemonics,
            mnemonics=mnemonics,
            normalized=mnemonics,  # No normalization available
        )
        return self.search(opcodes, limit=limit)

    def find_containing_opcodes(
        self,
        target_opcodes: list[str],
        require_all: bool = False,
        limit: int = 20,
    ) -> list[MatchResult]:
        """
        Find samples containing specific opcodes.

        Args:
            target_opcodes: List of opcodes to search for
            require_all: If True, require all opcodes; if False, any match
            limit: Maximum results to return

        Returns:
            List of matching samples sorted by number of matches
        """
        if not target_opcodes:
            return []

        # Build query with LIKE clauses
        if require_all:
            conditions = " AND ".join(f"mnemonics LIKE '%{op}%'" for op in target_opcodes)
        else:
            conditions = " OR ".join(f"mnemonics LIKE '%{op}%'" for op in target_opcodes)

        rows = self.conn.execute(
            f"""
            SELECT * FROM samples
            WHERE {conditions}
            LIMIT ?
        """,
            (limit,),
        ).fetchall()

        results = []
        for row in rows:
            sample = self._row_to_sample(row)
            sample_ops = sample.mnemonics.split(",")

            # Count matches
            matches = sum(1 for op in target_opcodes if op in sample_ops)
            score = matches / len(target_opcodes)

            results.append(
                MatchResult(
                    sample=sample,
                    score=score,
                    match_type="contains",
                    match_details={"matching_opcodes": matches, "total_target": len(target_opcodes)},
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def find_subsequence(
        self,
        subseq: list[str],
        limit: int = 20,
    ) -> list[MatchResult]:
        """
        Find samples containing a subsequence of opcodes (in order but not necessarily adjacent).

        Args:
            subseq: List of opcodes that should appear in order
            limit: Maximum results

        Returns:
            List of matching samples
        """
        if not subseq:
            return []

        # First, filter by samples containing all the opcodes
        candidates = self.find_containing_opcodes(subseq, require_all=True, limit=limit * 5)

        results = []
        for candidate in candidates:
            sample_ops = candidate.sample.mnemonics.split(",")

            # Check if subsequence appears in order
            subseq_idx = 0
            for op in sample_ops:
                if subseq_idx < len(subseq) and op == subseq[subseq_idx]:
                    subseq_idx += 1

            if subseq_idx == len(subseq):
                # Found complete subsequence
                results.append(
                    MatchResult(
                        sample=candidate.sample,
                        score=1.0,
                        match_type="subsequence",
                        match_details={"subsequence_length": len(subseq)},
                    )
                )

        return results[:limit]

    def get_stats(self) -> dict:
        """Get database statistics."""
        total = self.conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        by_template = self.conn.execute("""
            SELECT template_name, COUNT(*) as count
            FROM samples
            GROUP BY template_name
            ORDER BY count DESC
        """).fetchall()
        by_context = self.conn.execute("""
            SELECT context_name, COUNT(*) as count
            FROM samples
            GROUP BY context_name
            ORDER BY count DESC
        """).fetchall()
        ngram_count = self.conn.execute("SELECT COUNT(*) FROM ngrams").fetchone()[0]

        return {
            "total_samples": total,
            "by_template": [(r[0], r[1]) for r in by_template],
            "by_context": [(r[0], r[1]) for r in by_context],
            "ngram_count": ngram_count,
        }

    def close(self):
        """Close the database connection."""
        self.conn.close()


def get_default_db_path() -> Path:
    """Get the default database path."""
    config_dir = Path.home() / ".config" / "decomp-me"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "opseq_synth.db"
