"""
Backfill mismatch patterns from git history.

Architecture:
1. Orchestrator creates a job and splits commits into analysis tasks
2. Subagents claim tasks, analyze m2c vs final code, submit candidate patterns
3. Human/orchestrator reviews candidates before committing to main patterns table

This module provides the data models and orchestration logic.
The actual LLM-based analysis is done by agents using the task definitions.
"""

import json
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from .schema import get_db


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    COMPLETED = "completed"
    FAILED = "failed"


class CandidateStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"


@dataclass
class BackfillJob:
    """A backfill job that orchestrates analysis of multiple commits."""

    id: str
    status: JobStatus
    config: dict
    total_commits: int = 0
    processed_commits: int = 0
    candidates_found: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str | None = None
    error_message: str | None = None


@dataclass
class AnalysisTask:
    """A single analysis task for a subagent."""

    id: str
    job_id: str
    status: TaskStatus

    # What to analyze
    commit_sha: str
    commit_message: str | None = None
    commit_date: str | None = None
    function_name: str | None = None
    file_path: str | None = None

    # Analysis inputs
    m2c_source: str | None = None
    final_source: str | None = None
    asm_diff: str | None = None

    # Analysis outputs
    agent_id: str | None = None
    analysis_notes: str | None = None

    assigned_at: str | None = None
    completed_at: str | None = None
    created_at: str | None = None


@dataclass
class CandidatePattern:
    """A candidate pattern discovered by an agent, pending review."""

    id: int | None
    task_id: str
    job_id: str
    status: CandidateStatus

    # Pattern data
    suggested_id: str
    name: str
    description: str
    root_cause: str
    notes: str | None = None
    signals: list = field(default_factory=list)
    examples: list = field(default_factory=list)
    fixes: list = field(default_factory=list)
    opcodes: list = field(default_factory=list)
    categories: list = field(default_factory=list)

    # Source tracking
    source_function: str | None = None
    source_commit: str | None = None
    confidence: float = 0.5

    # Review tracking
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_notes: str | None = None
    merged_into: str | None = None
    approved_pattern_id: str | None = None
    created_at: str | None = None


class BackfillOrchestrator:
    """
    Orchestrates backfill jobs.

    Usage:
        orchestrator = BackfillOrchestrator(db_path)
        job_id = orchestrator.create_job(commit_range="HEAD~50..HEAD")
        orchestrator.populate_tasks(job_id, melee_repo)
        # Agents claim and process tasks...
        orchestrator.check_job_status(job_id)
    """

    def __init__(self, db_path: Path | None = None):
        self.conn = get_db(db_path)

    def create_job(
        self,
        commit_range: str = "HEAD~50..HEAD",
        batch_size: int = 10,
        filter_pattern: str = r"[Mm]atch|100%",
    ) -> str:
        """Create a new backfill job."""
        job_id = str(uuid.uuid4())[:8]
        config = {
            "commit_range": commit_range,
            "batch_size": batch_size,
            "filter_pattern": filter_pattern,
        }

        self.conn.execute(
            """
            INSERT INTO backfill_jobs (id, status, config, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (job_id, JobStatus.PENDING, json.dumps(config), datetime.now().isoformat()),
        )
        self.conn.commit()
        return job_id

    def populate_tasks(self, job_id: str, melee_repo: Path) -> int:
        """
        Scan git history and create analysis tasks for a job.

        Returns the number of tasks created.
        """
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")

        config = job.config
        commit_range = config.get("commit_range", "HEAD~50..HEAD")
        filter_pattern = config.get("filter_pattern", r"[Mm]atch|100%")

        # Get commits in range
        cmd = ["git", "log", "--format=%H|%s|%ai", commit_range, "--", "src/melee/**/*.c"]
        result = subprocess.run(cmd, cwd=melee_repo, capture_output=True, text=True)

        tasks_created = 0
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            parts = line.split("|")
            if len(parts) < 3:
                continue

            sha, message, date = parts[0], parts[1], parts[2]

            # Filter to match-related commits
            if not re.search(filter_pattern, message):
                continue

            # Extract function name from commit message
            func_match = re.search(r"[Mm]atch\s+(\w+)|(\w+)\s*\(?\s*100%", message)
            func_name = None
            if func_match:
                func_name = func_match.group(1) or func_match.group(2)
                if func_name and func_name.lower() in ("the", "a", "to", "for", "with"):
                    func_name = None

            # Get file path from commit
            file_cmd = ["git", "show", "--name-only", "--format=", sha, "--", "src/melee/**/*.c"]
            file_result = subprocess.run(file_cmd, cwd=melee_repo, capture_output=True, text=True)
            file_path = None
            for f in file_result.stdout.strip().split("\n"):
                if f.endswith(".c"):
                    file_path = f
                    break

            task_id = str(uuid.uuid4())[:8]
            self.conn.execute(
                """
                INSERT INTO analysis_tasks
                    (id, job_id, status, commit_sha, commit_message, commit_date,
                     function_name, file_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    job_id,
                    TaskStatus.PENDING,
                    sha,
                    message,
                    date[:10],
                    func_name,
                    file_path,
                    datetime.now().isoformat(),
                ),
            )
            tasks_created += 1

        # Update job stats
        self.conn.execute(
            """
            UPDATE backfill_jobs
            SET total_commits = ?, status = ?
            WHERE id = ?
            """,
            (tasks_created, JobStatus.RUNNING, job_id),
        )
        self.conn.commit()
        return tasks_created

    def get_job(self, job_id: str) -> BackfillJob | None:
        """Get a job by ID."""
        row = self.conn.execute("SELECT * FROM backfill_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None

        return BackfillJob(
            id=row["id"],
            status=JobStatus(row["status"]),
            config=json.loads(row["config"] or "{}"),
            total_commits=row["total_commits"],
            processed_commits=row["processed_commits"],
            candidates_found=row["candidates_found"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            created_at=row["created_at"],
            error_message=row["error_message"],
        )

    def list_jobs(self) -> list[BackfillJob]:
        """List all jobs."""
        rows = self.conn.execute("SELECT * FROM backfill_jobs ORDER BY created_at DESC").fetchall()
        return [
            BackfillJob(
                id=row["id"],
                status=JobStatus(row["status"]),
                config=json.loads(row["config"] or "{}"),
                total_commits=row["total_commits"],
                processed_commits=row["processed_commits"],
                candidates_found=row["candidates_found"],
            )
            for row in rows
        ]

    def claim_task(self, job_id: str, agent_id: str) -> AnalysisTask | None:
        """
        Claim the next pending task for an agent to work on.

        Returns the task if one was claimed, None if no tasks available.
        """
        # Find and claim a pending task atomically
        row = self.conn.execute(
            """
            UPDATE analysis_tasks
            SET status = ?, agent_id = ?, assigned_at = ?
            WHERE id = (
                SELECT id FROM analysis_tasks
                WHERE job_id = ? AND status = ?
                LIMIT 1
            )
            RETURNING *
            """,
            (
                TaskStatus.ASSIGNED,
                agent_id,
                datetime.now().isoformat(),
                job_id,
                TaskStatus.PENDING,
            ),
        ).fetchone()
        self.conn.commit()

        if not row:
            return None

        return AnalysisTask(
            id=row["id"],
            job_id=row["job_id"],
            status=TaskStatus(row["status"]),
            commit_sha=row["commit_sha"],
            commit_message=row["commit_message"],
            commit_date=row["commit_date"],
            function_name=row["function_name"],
            file_path=row["file_path"],
            m2c_source=row["m2c_source"],
            final_source=row["final_source"],
            asm_diff=row["asm_diff"],
            agent_id=row["agent_id"],
        )

    def get_task(self, task_id: str) -> AnalysisTask | None:
        """Get a task by ID."""
        row = self.conn.execute("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None

        return AnalysisTask(
            id=row["id"],
            job_id=row["job_id"],
            status=TaskStatus(row["status"]),
            commit_sha=row["commit_sha"],
            commit_message=row["commit_message"],
            commit_date=row["commit_date"],
            function_name=row["function_name"],
            file_path=row["file_path"],
            m2c_source=row["m2c_source"],
            final_source=row["final_source"],
            asm_diff=row["asm_diff"],
            agent_id=row["agent_id"],
            analysis_notes=row["analysis_notes"],
        )

    def list_tasks(self, job_id: str, status: TaskStatus | None = None) -> list[AnalysisTask]:
        """List tasks for a job, optionally filtered by status."""
        if status:
            rows = self.conn.execute(
                "SELECT * FROM analysis_tasks WHERE job_id = ? AND status = ?",
                (job_id, status),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM analysis_tasks WHERE job_id = ?", (job_id,)).fetchall()

        return [
            AnalysisTask(
                id=row["id"],
                job_id=row["job_id"],
                status=TaskStatus(row["status"]),
                commit_sha=row["commit_sha"],
                commit_message=row["commit_message"],
                function_name=row["function_name"],
            )
            for row in rows
        ]

    def update_task_inputs(
        self,
        task_id: str,
        m2c_source: str | None = None,
        final_source: str | None = None,
        asm_diff: str | None = None,
    ) -> None:
        """Update the analysis inputs for a task."""
        updates = []
        params = []
        if m2c_source is not None:
            updates.append("m2c_source = ?")
            params.append(m2c_source)
        if final_source is not None:
            updates.append("final_source = ?")
            params.append(final_source)
        if asm_diff is not None:
            updates.append("asm_diff = ?")
            params.append(asm_diff)

        if updates:
            params.append(task_id)
            self.conn.execute(
                f"UPDATE analysis_tasks SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            self.conn.commit()

    def complete_task(
        self,
        task_id: str,
        analysis_notes: str,
        candidates: list[dict],
    ) -> None:
        """
        Mark a task as completed and submit candidate patterns.

        Args:
            task_id: The task ID
            analysis_notes: Agent's analysis reasoning
            candidates: List of candidate pattern dicts
        """
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        # Update task
        self.conn.execute(
            """
            UPDATE analysis_tasks
            SET status = ?, analysis_notes = ?, completed_at = ?
            WHERE id = ?
            """,
            (TaskStatus.COMPLETED, analysis_notes, datetime.now().isoformat(), task_id),
        )

        # Insert candidates
        for candidate in candidates:
            self.conn.execute(
                """
                INSERT INTO candidate_patterns
                    (task_id, job_id, status, suggested_id, name, description,
                     root_cause, notes, signals, examples, fixes, opcodes,
                     categories, source_function, source_commit, confidence, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    task.job_id,
                    CandidateStatus.PENDING,
                    candidate.get("suggested_id", ""),
                    candidate.get("name", "Unknown Pattern"),
                    candidate.get("description", ""),
                    candidate.get("root_cause", ""),
                    candidate.get("notes"),
                    json.dumps(candidate.get("signals", [])),
                    json.dumps(candidate.get("examples", [])),
                    json.dumps(candidate.get("fixes", [])),
                    json.dumps(candidate.get("opcodes", [])),
                    json.dumps(candidate.get("categories", [])),
                    task.function_name,
                    task.commit_sha,
                    candidate.get("confidence", 0.5),
                    datetime.now().isoformat(),
                ),
            )

        # Update job stats
        self.conn.execute(
            """
            UPDATE backfill_jobs
            SET processed_commits = processed_commits + 1,
                candidates_found = candidates_found + ?
            WHERE id = ?
            """,
            (len(candidates), task.job_id),
        )
        self.conn.commit()

    def fail_task(self, task_id: str, error_message: str) -> None:
        """Mark a task as failed."""
        self.conn.execute(
            """
            UPDATE analysis_tasks
            SET status = ?, analysis_notes = ?, completed_at = ?
            WHERE id = ?
            """,
            (TaskStatus.FAILED, f"ERROR: {error_message}", datetime.now().isoformat(), task_id),
        )
        self.conn.commit()


class CandidateReviewer:
    """
    Review interface for candidate patterns.

    Usage:
        reviewer = CandidateReviewer(db_path)
        candidates = reviewer.list_pending()
        reviewer.approve(candidate_id, "pattern-slug")
        reviewer.reject(candidate_id, "Duplicate of existing pattern")
        reviewer.merge(candidate_id, "existing-pattern-id")
    """

    def __init__(self, db_path: Path | None = None):
        self.conn = get_db(db_path)

    def list_pending(self, job_id: str | None = None) -> list[CandidatePattern]:
        """List pending candidate patterns."""
        if job_id:
            rows = self.conn.execute(
                """
                SELECT * FROM candidate_patterns
                WHERE status = ? AND job_id = ?
                ORDER BY confidence DESC, created_at
                """,
                (CandidateStatus.PENDING, job_id),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM candidate_patterns
                WHERE status = ?
                ORDER BY confidence DESC, created_at
                """,
                (CandidateStatus.PENDING,),
            ).fetchall()

        return [self._row_to_candidate(row) for row in rows]

    def get_candidate(self, candidate_id: int) -> CandidatePattern | None:
        """Get a candidate by ID."""
        row = self.conn.execute("SELECT * FROM candidate_patterns WHERE id = ?", (candidate_id,)).fetchone()
        if not row:
            return None
        return self._row_to_candidate(row)

    def _row_to_candidate(self, row) -> CandidatePattern:
        return CandidatePattern(
            id=row["id"],
            task_id=row["task_id"],
            job_id=row["job_id"],
            status=CandidateStatus(row["status"]),
            suggested_id=row["suggested_id"],
            name=row["name"],
            description=row["description"],
            root_cause=row["root_cause"],
            notes=row["notes"],
            signals=json.loads(row["signals"] or "[]"),
            examples=json.loads(row["examples"] or "[]"),
            fixes=json.loads(row["fixes"] or "[]"),
            opcodes=json.loads(row["opcodes"] or "[]"),
            categories=json.loads(row["categories"] or "[]"),
            source_function=row["source_function"],
            source_commit=row["source_commit"],
            confidence=row["confidence"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=row["reviewed_at"],
            review_notes=row["review_notes"],
            merged_into=row["merged_into"],
            approved_pattern_id=row["approved_pattern_id"],
            created_at=row["created_at"],
        )

    def approve(
        self,
        candidate_id: int,
        pattern_id: str,
        reviewer: str = "human",
        notes: str | None = None,
    ) -> None:
        """
        Approve a candidate and create it as an official pattern.

        Args:
            candidate_id: The candidate to approve
            pattern_id: The ID/slug for the new pattern
            reviewer: Who approved it
            notes: Optional review notes
        """
        from .models import Example, Fix, Pattern, PatternDB, Provenance, ProvenanceEntry, Signal

        candidate = self.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"Candidate not found: {candidate_id}")

        # Create the pattern
        pattern = Pattern(
            id=pattern_id,
            name=candidate.name,
            description=candidate.description,
            root_cause=candidate.root_cause,
            notes=candidate.notes,
            signals=[Signal.from_dict(s) for s in candidate.signals],
            examples=[Example.from_dict(e) for e in candidate.examples],
            fixes=[Fix.from_dict(f) for f in candidate.fixes],
            provenance=Provenance(
                discovered_from=[
                    ProvenanceEntry(
                        function=candidate.source_function or "unknown",
                        date=datetime.now().isoformat()[:10],
                    )
                ]
            ),
            related_patterns=[],
            opcodes=candidate.opcodes,
            categories=candidate.categories,
        )

        db = PatternDB(self.conn)
        db.insert(pattern)

        # Update candidate status
        self.conn.execute(
            """
            UPDATE candidate_patterns
            SET status = ?, reviewed_by = ?, reviewed_at = ?,
                review_notes = ?, approved_pattern_id = ?
            WHERE id = ?
            """,
            (
                CandidateStatus.APPROVED,
                reviewer,
                datetime.now().isoformat(),
                notes,
                pattern_id,
                candidate_id,
            ),
        )
        self.conn.commit()

    def reject(
        self,
        candidate_id: int,
        reason: str,
        reviewer: str = "human",
    ) -> None:
        """Reject a candidate pattern."""
        self.conn.execute(
            """
            UPDATE candidate_patterns
            SET status = ?, reviewed_by = ?, reviewed_at = ?, review_notes = ?
            WHERE id = ?
            """,
            (
                CandidateStatus.REJECTED,
                reviewer,
                datetime.now().isoformat(),
                reason,
                candidate_id,
            ),
        )
        self.conn.commit()

    def merge(
        self,
        candidate_id: int,
        existing_pattern_id: str,
        reviewer: str = "human",
        notes: str | None = None,
    ) -> None:
        """
        Merge a candidate into an existing pattern (add as example/provenance).

        Args:
            candidate_id: The candidate to merge
            existing_pattern_id: The pattern to merge into
            reviewer: Who performed the merge
            notes: Optional notes
        """
        from .models import PatternDB

        candidate = self.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"Candidate not found: {candidate_id}")

        db = PatternDB(self.conn)
        pattern = db.get(existing_pattern_id)
        if not pattern:
            raise ValueError(f"Pattern not found: {existing_pattern_id}")

        # Add candidate's examples to the pattern
        if candidate.examples:
            current_examples = json.loads(
                self.conn.execute("SELECT examples FROM patterns WHERE id = ?", (existing_pattern_id,)).fetchone()[
                    "examples"
                ]
                or "[]"
            )
            current_examples.extend(candidate.examples)
            self.conn.execute(
                "UPDATE patterns SET examples = ?, updated_at = ? WHERE id = ?",
                (json.dumps(current_examples), datetime.now().isoformat(), existing_pattern_id),
            )

        # Record in provenance
        db.record_success(existing_pattern_id, candidate.source_function or "unknown")

        # Update candidate status
        self.conn.execute(
            """
            UPDATE candidate_patterns
            SET status = ?, reviewed_by = ?, reviewed_at = ?,
                review_notes = ?, merged_into = ?
            WHERE id = ?
            """,
            (
                CandidateStatus.MERGED,
                reviewer,
                datetime.now().isoformat(),
                notes,
                existing_pattern_id,
                candidate_id,
            ),
        )
        self.conn.commit()

    def find_similar(self, candidate_id: int, threshold: float = 0.5) -> list[tuple[str, float]]:
        """
        Find existing patterns similar to a candidate.

        Returns list of (pattern_id, similarity_score) tuples.
        """
        from .models import PatternDB

        candidate = self.get_candidate(candidate_id)
        if not candidate:
            return []

        db = PatternDB(self.conn)
        all_patterns = db.list_all()

        similar = []
        for pattern in all_patterns:
            score = self._compute_similarity(candidate, pattern)
            if score >= threshold:
                similar.append((pattern.id, score))

        return sorted(similar, key=lambda x: -x[1])

    def _compute_similarity(self, candidate: CandidatePattern, pattern) -> float:
        """Compute similarity score between candidate and existing pattern."""
        score = 0.0
        weights = 0.0

        # Opcode overlap
        if candidate.opcodes and pattern.opcodes:
            overlap = len(set(candidate.opcodes) & set(pattern.opcodes))
            total = len(set(candidate.opcodes) | set(pattern.opcodes))
            if total > 0:
                score += 0.3 * (overlap / total)
            weights += 0.3

        # Category overlap
        if candidate.categories and pattern.categories:
            overlap = len(set(candidate.categories) & set(pattern.categories))
            total = len(set(candidate.categories) | set(pattern.categories))
            if total > 0:
                score += 0.2 * (overlap / total)
            weights += 0.2

        # Name similarity (simple word overlap)
        if candidate.name and pattern.name:
            c_words = set(candidate.name.lower().split())
            p_words = set(pattern.name.lower().split())
            overlap = len(c_words & p_words)
            total = len(c_words | p_words)
            if total > 0:
                score += 0.3 * (overlap / total)
            weights += 0.3

        # Signal type overlap
        c_signal_types = {s.get("type") for s in candidate.signals}
        p_signal_types = {s.type for s in pattern.signals}
        if c_signal_types and p_signal_types:
            overlap = len(c_signal_types & p_signal_types)
            total = len(c_signal_types | p_signal_types)
            if total > 0:
                score += 0.2 * (overlap / total)
            weights += 0.2

        return score / weights if weights > 0 else 0.0


# =============================================================================
# ANALYSIS TASK PROMPT GENERATION
# =============================================================================


def generate_analysis_prompt(task: AnalysisTask) -> str:
    """
    Generate a prompt for an analysis agent to work on a task.

    This prompt tells the agent what to analyze and how to report findings.
    """
    prompt = f"""# Pattern Discovery Analysis Task

You are analyzing a matched function to discover mismatch patterns that could help future decompilation work.

## Task Information
- **Task ID**: {task.id}
- **Commit**: {task.commit_sha}
- **Message**: {task.commit_message}
- **Function**: {task.function_name or "Unknown"}
- **File**: {task.file_path or "Unknown"}

## Your Goal

Compare the m2c decompiler output (starting point) with the final matched code.
Identify **patterns** - recurring transformations that could apply to other functions.

## Analysis Inputs

### M2C Decompiler Output (Starting Point)
```c
{task.m2c_source or "Not available - you may need to generate this"}
```

### Final Matched Code
```c
{task.final_source or "Not available - extract from the commit"}
```

### Assembly Diff (if available)
```
{task.asm_diff or "Not available"}
```

## What to Look For

1. **Structural changes**: loops rewritten, conditions restructured
2. **Type refinements**: void* → typed pointer, offset → field access
3. **Compiler quirks**: masks needed (& 0xFF), declaration order matters
4. **m2c artifacts replaced**: M2C_STRUCT_COPY, M2C_FIELD, etc.
5. **Macro usage**: GET_ITEM, ARRAY_SIZE, ABS/FABS, etc.

## Output Format

Report your findings as JSON with this structure:

```json
{{
  "analysis_notes": "Your reasoning about what patterns you found and why",
  "candidates": [
    {{
      "suggested_id": "pattern-slug",
      "name": "Human Readable Pattern Name",
      "description": "What the pattern looks like / when to suspect it",
      "root_cause": "Why this happens (compiler behavior, m2c limitation, etc.)",
      "signals": [
        {{"type": "opcode_mismatch", "expected": "lwz", "actual": "lfs"}},
        {{"type": "m2c_artifact", "artifact": "M2C_STRUCT_COPY"}}
      ],
      "examples": [
        {{
          "function": "{task.function_name}",
          "before": "code before fix",
          "after": "code after fix",
          "context": "brief description"
        }}
      ],
      "fixes": [
        {{
          "description": "How to fix this pattern",
          "before": "problematic code",
          "after": "fixed code"
        }}
      ],
      "opcodes": ["lwz", "lfs", "stw"],
      "categories": ["struct", "type"],
      "confidence": 0.8
    }}
  ]
}}
```

## Guidelines

- Only report **NEW patterns** - check if similar patterns already exist
- Confidence should reflect how generalizable the pattern is (0.0-1.0)
- Include concrete before/after code examples
- If you don't find any patterns, return empty candidates array with notes explaining why

"""
    return prompt


def generate_task_completion_schema() -> dict:
    """JSON schema for task completion output."""
    return {
        "type": "object",
        "required": ["analysis_notes", "candidates"],
        "properties": {
            "analysis_notes": {
                "type": "string",
                "description": "Your reasoning about patterns found",
            },
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "description"],
                    "properties": {
                        "suggested_id": {"type": "string"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "root_cause": {"type": "string"},
                        "notes": {"type": "string"},
                        "signals": {"type": "array"},
                        "examples": {"type": "array"},
                        "fixes": {"type": "array"},
                        "opcodes": {"type": "array", "items": {"type": "string"}},
                        "categories": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
            },
        },
    }
