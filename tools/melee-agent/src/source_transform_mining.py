"""SQLite-backed source-transform mining ledger.

The mining ledger tracks source transitions at function granularity so history
backfills can avoid repeatedly analyzing the same commit/file/function body
change.  It deliberately stops at task staging; analysis and promotion into a
real transform corpus remain review steps.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.mwcc_debug.source_patch import find_function_definitions


DEFAULT_DB_PATH = Path.home() / ".config" / "decomp-me" / "source_transform_mining.db"
ANALYZER_VERSION = "source-transform-mining-v1"
LEDGER_MISSING_HASH = "missing"


SCHEMA = """
CREATE TABLE IF NOT EXISTS transform_mining_jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    config JSON,
    total_tasks INTEGER DEFAULT 0,
    processed_tasks INTEGER DEFAULT 0,
    skipped_ledger_hits INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS transform_mining_tasks (
    id TEXT PRIMARY KEY,
    job_id TEXT REFERENCES transform_mining_jobs(id) ON DELETE CASCADE,
    ledger_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',

    commit_sha TEXT NOT NULL,
    commit_message TEXT,
    commit_date TEXT,
    file_path TEXT NOT NULL,
    function_name TEXT NOT NULL,
    analyzer_version TEXT NOT NULL,
    before_hash TEXT NOT NULL,
    after_hash TEXT NOT NULL,
    before_source TEXT,
    after_source TEXT NOT NULL,

    agent_id TEXT,
    analysis_notes TEXT,
    result_kind TEXT,
    family_id TEXT,
    error_message TEXT,

    assigned_at TEXT,
    completed_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transform_tasks_job
    ON transform_mining_tasks(job_id);
CREATE INDEX IF NOT EXISTS idx_transform_tasks_status
    ON transform_mining_tasks(status);
CREATE INDEX IF NOT EXISTS idx_transform_tasks_function
    ON transform_mining_tasks(function_name);

CREATE TABLE IF NOT EXISTS transform_mining_ledger (
    ledger_key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    commit_message TEXT,
    commit_date TEXT,
    file_path TEXT NOT NULL,
    function_name TEXT NOT NULL,
    analyzer_version TEXT NOT NULL,
    before_hash TEXT NOT NULL,
    after_hash TEXT NOT NULL,
    task_id TEXT,
    result_kind TEXT,
    family_id TEXT,
    notes TEXT,
    seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transform_ledger_status
    ON transform_mining_ledger(status);
CREATE INDEX IF NOT EXISTS idx_transform_ledger_source
    ON transform_mining_ledger(commit_sha, file_path, function_name);
"""


@dataclass(frozen=True)
class JobCreationResult:
    job_id: str
    tasks_created: int
    skipped_ledger_hits: int


@dataclass(frozen=True)
class MiningJobStatus:
    id: str
    status: str
    config: dict
    total_tasks: int
    processed_tasks: int
    skipped_ledger_hits: int
    error_message: str | None = None


@dataclass(frozen=True)
class MiningTask:
    id: str
    job_id: str
    ledger_key: str
    status: str
    commit_sha: str
    commit_message: str | None
    commit_date: str | None
    file_path: str
    function_name: str
    analyzer_version: str
    before_hash: str
    after_hash: str
    before_source: str | None = None
    after_source: str | None = None
    agent_id: str | None = None
    analysis_notes: str | None = None
    result_kind: str | None = None
    family_id: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class MiningDiffCluster:
    signature: str
    task_count: int
    samples: tuple[MiningTask, ...]


@dataclass(frozen=True)
class _CommitInfo:
    sha: str
    message: str
    date: str


@dataclass(frozen=True)
class _SourceTransition:
    commit: _CommitInfo
    file_path: str
    function_name: str
    analyzer_version: str
    before_source: str | None
    after_source: str
    before_hash: str
    after_hash: str
    ledger_key: str


class TransformMiningStore:
    """Create and manage source-transform mining jobs."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def create_job(
        self,
        *,
        repo: Path,
        commit_range: str,
        filter_pattern: str = r"[Mm]atch|100%",
        analyzer_version: str = ANALYZER_VERSION,
        include_additions: bool = False,
    ) -> JobCreationResult:
        """Scan git history and queue unseen function-level transitions."""

        job_id = str(uuid.uuid4())[:8]
        config = {
            "repo": str(repo),
            "commit_range": commit_range,
            "filter_pattern": filter_pattern,
            "analyzer_version": analyzer_version,
            "include_additions": include_additions,
        }
        self.conn.execute(
            """
            INSERT INTO transform_mining_jobs (id, status, config, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (job_id, "running", json.dumps(config), _now()),
        )

        tasks_created = 0
        skipped_ledger_hits = 0
        for transition in self._scan_transitions(
            repo=repo,
            commit_range=commit_range,
            filter_pattern=filter_pattern,
            analyzer_version=analyzer_version,
            include_additions=include_additions,
        ):
            if self._ledger_contains(transition.ledger_key):
                skipped_ledger_hits += 1
                continue
            task_id = str(uuid.uuid4())[:8]
            self._insert_task(job_id, task_id, transition)
            self._insert_ledger("pending", task_id, transition)
            tasks_created += 1

        status = "running" if tasks_created else "completed"
        self.conn.execute(
            """
            UPDATE transform_mining_jobs
            SET status = ?, total_tasks = ?, skipped_ledger_hits = ?,
                completed_at = CASE WHEN ? = 'completed' THEN ? ELSE completed_at END
            WHERE id = ?
            """,
            (status, tasks_created, skipped_ledger_hits, status, _now(), job_id),
        )
        self.conn.commit()
        return JobCreationResult(
            job_id=job_id,
            tasks_created=tasks_created,
            skipped_ledger_hits=skipped_ledger_hits,
        )

    def list_tasks(self, job_id: str, status: str | None = None) -> list[MiningTask]:
        if status is None:
            rows = self.conn.execute(
                """
                SELECT * FROM transform_mining_tasks
                WHERE job_id = ?
                ORDER BY rowid
                """,
                (job_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM transform_mining_tasks
                WHERE job_id = ? AND status = ?
                ORDER BY rowid
                """,
                (job_id, status),
            ).fetchall()
        return [_task_from_row(row) for row in rows]

    def get_task(self, task_id: str) -> MiningTask | None:
        row = self.conn.execute(
            "SELECT * FROM transform_mining_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        return _task_from_row(row) if row else None

    def claim_task(
        self,
        job_id: str,
        *,
        agent_id: str,
        existing_only: bool = False,
    ) -> MiningTask | None:
        while True:
            self.conn.execute("BEGIN IMMEDIATE")
            where = "job_id = ? AND status = 'pending'"
            params: list[object] = [job_id]
            if existing_only:
                where += " AND before_source IS NOT NULL"
            row = self.conn.execute(
                f"""
                SELECT id, ledger_key FROM transform_mining_tasks
                WHERE {where}
                ORDER BY rowid
                LIMIT 1
                """,
                params,
            ).fetchone()
            if row is None:
                self.conn.commit()
                return None

            now = _now()
            updated = self.conn.execute(
                """
                UPDATE transform_mining_tasks
                SET status = 'assigned', agent_id = ?, assigned_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (agent_id, now, row["id"]),
            )
            if updated.rowcount == 0:
                self.conn.rollback()
                continue
            self._update_ledger_status(row["ledger_key"], "assigned", task_id=row["id"])
            self.conn.commit()
            return self.get_task(row["id"])

    def complete_task(
        self,
        task_id: str,
        *,
        analysis_notes: str,
        result_kind: str,
        family_id: str | None = None,
    ) -> None:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"task not found: {task_id}")

        now = _now()
        self.conn.execute(
            """
            UPDATE transform_mining_tasks
            SET status = 'completed', analysis_notes = ?, result_kind = ?,
                family_id = ?, completed_at = ?
            WHERE id = ?
            """,
            (analysis_notes, result_kind, family_id, now, task_id),
        )
        self._update_ledger_status(
            task.ledger_key,
            "completed",
            task_id=task_id,
            result_kind=result_kind,
            family_id=family_id,
            notes=analysis_notes,
        )
        self._refresh_job_progress(task.job_id)
        self.conn.commit()

    def fail_task(self, task_id: str, error_message: str) -> None:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"task not found: {task_id}")

        now = _now()
        self.conn.execute(
            """
            UPDATE transform_mining_tasks
            SET status = 'failed', error_message = ?, completed_at = ?
            WHERE id = ?
            """,
            (error_message, now, task_id),
        )
        self._update_ledger_status(
            task.ledger_key,
            "failed",
            task_id=task_id,
            notes=error_message,
        )
        self._refresh_job_progress(task.job_id)
        self.conn.commit()

    def job_status(self, job_id: str) -> MiningJobStatus:
        row = self.conn.execute(
            "SELECT * FROM transform_mining_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"job not found: {job_id}")
        return MiningJobStatus(
            id=row["id"],
            status=row["status"],
            config=json.loads(row["config"] or "{}"),
            total_tasks=int(row["total_tasks"] or 0),
            processed_tasks=int(row["processed_tasks"] or 0),
            skipped_ledger_hits=int(row["skipped_ledger_hits"] or 0),
            error_message=row["error_message"],
        )

    def ledger_stats(self) -> dict[str, int]:
        rows = self.conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM transform_mining_ledger
            GROUP BY status
            ORDER BY status
            """
        ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def list_results(self, *, result_kind: str | None = None) -> list[MiningTask]:
        """List completed tasks that have review classifications."""
        if result_kind is None:
            rows = self.conn.execute(
                """
                SELECT * FROM transform_mining_tasks
                WHERE status = 'completed' AND result_kind IS NOT NULL
                ORDER BY completed_at, rowid
                """
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM transform_mining_tasks
                WHERE status = 'completed' AND result_kind = ?
                ORDER BY completed_at, rowid
                """,
                (result_kind,),
            ).fetchall()
        return [_task_from_row(row) for row in rows]

    def complete_pending_additions(
        self,
        job_id: str,
        *,
        analysis_notes: str = (
            "Function addition only; no before/after source rewrite to mine."
        ),
        result_kind: str = "not-useful",
        family_id: str | None = None,
    ) -> int:
        """Bulk-complete pending function additions as out of scope."""

        rows = self.conn.execute(
            """
            SELECT id FROM transform_mining_tasks
            WHERE job_id = ? AND status = 'pending' AND before_source IS NULL
            ORDER BY rowid
            """,
            (job_id,),
        ).fetchall()
        return self.complete_tasks(
            [row["id"] for row in rows],
            analysis_notes=analysis_notes,
            result_kind=result_kind,
            family_id=family_id,
        )

    def complete_tasks(
        self,
        task_ids: list[str] | tuple[str, ...],
        *,
        analysis_notes: str,
        result_kind: str,
        family_id: str | None = None,
    ) -> int:
        """Bulk-complete pending tasks with one reviewed classification."""

        if not task_ids:
            return 0
        unique_ids = list(dict.fromkeys(task_ids))
        placeholders = ",".join("?" for _ in unique_ids)
        self.conn.execute("BEGIN IMMEDIATE")
        rows = self.conn.execute(
            f"""
            SELECT id, job_id, ledger_key
            FROM transform_mining_tasks
            WHERE status = 'pending' AND id IN ({placeholders})
            """,
            unique_ids,
        ).fetchall()
        if not rows:
            self.conn.commit()
            return 0

        now = _now()
        row_ids = [row["id"] for row in rows]
        row_placeholders = ",".join("?" for _ in row_ids)
        self.conn.execute(
            f"""
            UPDATE transform_mining_tasks
            SET status = 'completed', analysis_notes = ?, result_kind = ?,
                family_id = ?, completed_at = ?
            WHERE status = 'pending' AND id IN ({row_placeholders})
            """,
            [analysis_notes, result_kind, family_id, now, *row_ids],
        )
        for row in rows:
            self._update_ledger_status(
                row["ledger_key"],
                "completed",
                task_id=row["id"],
                result_kind=result_kind,
                family_id=family_id,
                notes=analysis_notes,
            )
        for job_id in sorted({row["job_id"] for row in rows}):
            self._refresh_job_progress(job_id)
        self.conn.commit()
        return len(rows)

    def diff_clusters(
        self,
        job_id: str,
        *,
        status: str = "pending",
        sample_size: int = 5,
    ) -> list[MiningDiffCluster]:
        """Group existing-function tasks by a normalized before/after diff."""

        rows = self.conn.execute(
            """
            SELECT * FROM transform_mining_tasks
            WHERE job_id = ? AND status = ? AND before_source IS NOT NULL
            ORDER BY rowid
            """,
            (job_id, status),
        ).fetchall()
        grouped: dict[str, list[MiningTask]] = {}
        for row in rows:
            task = _task_from_row(row)
            signature = diff_signature(task.before_source or "", task.after_source or "")
            grouped.setdefault(signature, []).append(task)
        clusters = [
            MiningDiffCluster(
                signature=signature,
                task_count=len(tasks),
                samples=tuple(tasks[:sample_size]),
            )
            for signature, tasks in grouped.items()
        ]
        return sorted(clusters, key=lambda cluster: (-cluster.task_count, cluster.signature))

    def complete_cluster(
        self,
        job_id: str,
        signature: str,
        *,
        analysis_notes: str,
        result_kind: str,
        family_id: str | None = None,
        max_tasks: int | None = None,
    ) -> int:
        """Complete all pending existing-function tasks in a diff cluster."""

        rows = self.conn.execute(
            """
            SELECT id, before_source, after_source
            FROM transform_mining_tasks
            WHERE job_id = ? AND status = 'pending' AND before_source IS NOT NULL
            ORDER BY rowid
            """,
            (job_id,),
        ).fetchall()
        task_ids: list[str] = []
        for row in rows:
            if diff_signature(row["before_source"] or "", row["after_source"] or "") != signature:
                continue
            task_ids.append(row["id"])
            if max_tasks is not None and len(task_ids) >= max_tasks:
                break
        return self.complete_tasks(
            task_ids,
            analysis_notes=analysis_notes,
            result_kind=result_kind,
            family_id=family_id,
        )

    def _scan_transitions(
        self,
        *,
        repo: Path,
        commit_range: str,
        filter_pattern: str,
        analyzer_version: str,
        include_additions: bool,
    ) -> list[_SourceTransition]:
        transitions: list[_SourceTransition] = []
        for commit in _iter_commits(repo, commit_range, filter_pattern):
            for file_path in _changed_c_files(repo, commit.sha):
                after_text = _git_show_text(repo, f"{commit.sha}:{file_path}")
                if after_text is None:
                    continue
                before_text = _git_show_text(repo, f"{commit.sha}^:{file_path}")
                transitions.extend(
                    _transitions_for_file(
                        commit=commit,
                        file_path=file_path,
                        before_text=before_text,
                        after_text=after_text,
                        analyzer_version=analyzer_version,
                        include_additions=include_additions,
                    )
                )
        return transitions

    def _ledger_contains(self, ledger_key: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM transform_mining_ledger WHERE ledger_key = ?",
            (ledger_key,),
        ).fetchone()
        return row is not None

    def _insert_task(
        self,
        job_id: str,
        task_id: str,
        transition: _SourceTransition,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO transform_mining_tasks
                (id, job_id, ledger_key, status, commit_sha, commit_message,
                 commit_date, file_path, function_name, analyzer_version,
                 before_hash, after_hash, before_source, after_source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                job_id,
                transition.ledger_key,
                "pending",
                transition.commit.sha,
                transition.commit.message,
                transition.commit.date,
                transition.file_path,
                transition.function_name,
                transition.analyzer_version,
                transition.before_hash,
                transition.after_hash,
                transition.before_source,
                transition.after_source,
                _now(),
            ),
        )

    def _insert_ledger(
        self,
        status: str,
        task_id: str,
        transition: _SourceTransition,
    ) -> None:
        now = _now()
        self.conn.execute(
            """
            INSERT INTO transform_mining_ledger
                (ledger_key, status, commit_sha, commit_message, commit_date,
                 file_path, function_name, analyzer_version, before_hash,
                 after_hash, task_id, seen_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transition.ledger_key,
                status,
                transition.commit.sha,
                transition.commit.message,
                transition.commit.date,
                transition.file_path,
                transition.function_name,
                transition.analyzer_version,
                transition.before_hash,
                transition.after_hash,
                task_id,
                now,
                now,
            ),
        )

    def _update_ledger_status(
        self,
        ledger_key: str,
        status: str,
        *,
        task_id: str,
        result_kind: str | None = None,
        family_id: str | None = None,
        notes: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE transform_mining_ledger
            SET status = ?, task_id = ?, result_kind = COALESCE(?, result_kind),
                family_id = COALESCE(?, family_id), notes = COALESCE(?, notes),
                updated_at = ?
            WHERE ledger_key = ?
            """,
            (status, task_id, result_kind, family_id, notes, _now(), ledger_key),
        )

    def _refresh_job_progress(self, job_id: str) -> None:
        row = self.conn.execute(
            """
            SELECT
                SUM(CASE WHEN status IN ('completed', 'failed') THEN 1 ELSE 0 END)
                    AS processed,
                COUNT(*) AS total
            FROM transform_mining_tasks
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        processed = int(row["processed"] or 0)
        total = int(row["total"] or 0)
        status = "completed" if total and processed == total else "running"
        self.conn.execute(
            """
            UPDATE transform_mining_jobs
            SET processed_tasks = ?, status = ?,
                completed_at = CASE WHEN ? = 'completed' THEN ? ELSE completed_at END
            WHERE id = ?
            """,
            (processed, status, status, _now(), job_id),
        )


def _iter_commits(repo: Path, commit_range: str, filter_pattern: str) -> list[_CommitInfo]:
    cmd = [
        "git",
        "log",
        "--reverse",
        "--format=%H%x1f%s%x1f%ai",
        f"--grep={filter_pattern}",
        "--extended-regexp",
        commit_range,
        "--",
        "src/melee/**/*.c",
    ]
    result = _run_git(repo, cmd)
    commits: list[_CommitInfo] = []
    for line in result.splitlines():
        if not line:
            continue
        parts = line.split("\x1f")
        if len(parts) < 3:
            continue
        commits.append(_CommitInfo(parts[0], parts[1], parts[2][:10]))
    return commits


def _changed_c_files(repo: Path, commit_sha: str) -> list[str]:
    result = _run_git(
        repo,
        [
            "git",
            "show",
            "--name-only",
            "--format=",
            commit_sha,
            "--",
            "src/melee/**/*.c",
        ],
    )
    return [line for line in result.splitlines() if line.endswith(".c")]


def _git_show_text(repo: Path, spec: str) -> str | None:
    proc = subprocess.run(
        ["git", "show", spec],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _run_git(repo: Path, cmd: list[str]) -> str:
    proc = subprocess.run(
        cmd,
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def _transitions_for_file(
    *,
    commit: _CommitInfo,
    file_path: str,
    before_text: str | None,
    after_text: str,
    analyzer_version: str,
    include_additions: bool,
) -> list[_SourceTransition]:
    before_by_name: dict[str, str] = {}
    if before_text is not None:
        before_by_name = {
            span.name: before_text[span.sig_start : span.full_end]
            for span in find_function_definitions(before_text)
        }

    transitions: list[_SourceTransition] = []
    for span in find_function_definitions(after_text):
        after_source = after_text[span.sig_start : span.full_end]
        before_source = before_by_name.get(span.name)
        if before_source is None and not include_additions:
            continue
        if before_source == after_source:
            continue
        before_hash = _source_hash(before_source)
        after_hash = _source_hash(after_source)
        ledger_key = make_ledger_key(
            commit_sha=commit.sha,
            file_path=file_path,
            function_name=span.name,
            before_hash=before_hash,
            after_hash=after_hash,
            analyzer_version=analyzer_version,
        )
        transitions.append(
            _SourceTransition(
                commit=commit,
                file_path=file_path,
                function_name=span.name,
                analyzer_version=analyzer_version,
                before_source=before_source,
                after_source=after_source,
                before_hash=before_hash,
                after_hash=after_hash,
                ledger_key=ledger_key,
            )
        )
    return transitions


def make_ledger_key(
    *,
    commit_sha: str,
    file_path: str,
    function_name: str,
    before_hash: str,
    after_hash: str,
    analyzer_version: str,
) -> str:
    payload = "\x00".join(
        (
            commit_sha,
            file_path,
            function_name,
            before_hash,
            after_hash,
            analyzer_version,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z_0-9]*\b")
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z_0-9])(?:0x[0-9A-Fa-f]+|\d+(?:\.\d+)?(?:[FfUuLl]*)?)"
)
_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')
_CHAR_RE = re.compile(r"'(?:\\.|[^'\\])'")
_C_KEYWORDS = {
    "auto",
    "break",
    "case",
    "char",
    "const",
    "continue",
    "default",
    "do",
    "double",
    "else",
    "enum",
    "extern",
    "float",
    "for",
    "goto",
    "if",
    "inline",
    "int",
    "long",
    "register",
    "return",
    "short",
    "signed",
    "sizeof",
    "static",
    "struct",
    "switch",
    "typedef",
    "union",
    "unsigned",
    "void",
    "volatile",
    "while",
    "bool",
    "BOOL",
    "s8",
    "s16",
    "s32",
    "s64",
    "u8",
    "u16",
    "u32",
    "u64",
    "NULL",
    "true",
    "false",
}


def diff_signature(before_source: str, after_source: str) -> str:
    """Return a stable normalized diff signature for clustering reviews."""

    before_lines = [_normalize_diff_line(line) for line in before_source.splitlines()]
    after_lines = [_normalize_diff_line(line) for line in after_source.splitlines()]
    matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed = before_lines[i1:i2]
        added = after_lines[j1:j2]
        parts.append(f"{tag}:{len(removed)}:{len(added)}")
        parts.extend(f"-{line}" for line in removed)
        parts.extend(f"+{line}" for line in added)
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _normalize_diff_line(line: str) -> str:
    stripped = line.strip()
    stripped = _STRING_RE.sub('""', stripped)
    stripped = _CHAR_RE.sub("''", stripped)

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        return token if token in _C_KEYWORDS else "ID"

    stripped = _IDENT_RE.sub(repl, stripped)
    return _NUMBER_RE.sub(_normalize_number, stripped)


def _normalize_number(match: re.Match[str]) -> str:
    token = match.group(0)
    lowered = token.lower()
    if lowered.startswith("0x"):
        return "NUM_HEX"
    if "." in token or "f" in lowered:
        return "NUM_FLOAT"
    return "NUM_INT"


def generate_analysis_prompt(task: MiningTask) -> str:
    """Render a review prompt for a mined source transition."""
    before = task.before_source or "Function was not present before this commit."
    return f"""# Source Transform Mining Task

## Task
- Task ID: {task.id}
- Commit: {task.commit_sha}
- Message: {task.commit_message or ""}
- Function: {task.function_name}
- File: {task.file_path}
- Ledger key: {task.ledger_key}

## Goal

Compare the before/after source and decide whether this transition is:

- a duplicate of an already known transform family
- a useful example for an existing transform family
- a candidate for a new bounded source-transform family
- not useful for corpus expansion

## Before

```c
{before}
```

## After

```c
{task.after_source or ""}
```

## Result JSON

```json
{{
  "analysis_notes": "why this transition is or is not useful",
  "result_kind": "example-for-existing-family",
  "family_id": "declaration_use_boundary"
}}
```
"""


def _source_hash(source: str | None) -> str:
    if source is None:
        return LEDGER_MISSING_HASH
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _task_from_row(row: sqlite3.Row) -> MiningTask:
    return MiningTask(
        id=row["id"],
        job_id=row["job_id"],
        ledger_key=row["ledger_key"],
        status=row["status"],
        commit_sha=row["commit_sha"],
        commit_message=row["commit_message"],
        commit_date=row["commit_date"],
        file_path=row["file_path"],
        function_name=row["function_name"],
        analyzer_version=row["analyzer_version"],
        before_hash=row["before_hash"],
        after_hash=row["after_hash"],
        before_source=row["before_source"],
        after_source=row["after_source"],
        agent_id=row["agent_id"],
        analysis_notes=row["analysis_notes"],
        result_kind=row["result_kind"],
        family_id=row["family_id"],
        error_message=row["error_message"],
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
