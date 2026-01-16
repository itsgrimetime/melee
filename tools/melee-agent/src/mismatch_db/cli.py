"""
CLI for the mismatch pattern database (Typer version).
"""

import json
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table
from typing_extensions import Annotated

from .backfill import (
    BackfillOrchestrator,
    CandidateReviewer,
    TaskStatus,
    generate_analysis_prompt,
)
from .migrate_markdown import migrate_markdown_file, parse_markdown, section_to_pattern
from .models import Pattern, PatternDB
from .sample_entries import SAMPLE_PATTERNS, load_samples
from .schema import DEFAULT_DB_PATH, init_db

console = Console()

# Main mismatch app
mismatch_app = typer.Typer(
    name="mismatch",
    help="Mismatch pattern database CLI.",
)

# Subgroups
backfill_app = typer.Typer(help="Backfill patterns from git history.")
review_app = typer.Typer(help="Review candidate patterns.")

mismatch_app.add_typer(backfill_app, name="backfill")
mismatch_app.add_typer(review_app, name="review")


def get_db_path(db: Path | None) -> Path:
    """Get database path, using default if not specified."""
    return db if db else DEFAULT_DB_PATH


@mismatch_app.command()
def init(
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
):
    """Initialize the database with schema and sample patterns."""
    db_path = get_db_path(db)

    if db_path.exists():
        if not typer.confirm(f"Database already exists at {db_path}. Reinitialize?"):
            raise typer.Abort()
        db_path.unlink()

    rprint(f"Initializing database at {db_path}")
    conn = init_db(db_path)
    pattern_db = PatternDB(conn)

    rprint("Loading sample patterns...")
    load_samples(pattern_db)

    rprint(f"Done! {len(pattern_db.list_all())} patterns loaded.")


@mismatch_app.command("list")
def list_patterns(
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
    category: Annotated[str | None, typer.Option("-c", "--category", help="Filter by category")] = None,
    opcode: Annotated[str | None, typer.Option("-o", "--opcode", help="Filter by opcode")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """List all patterns."""
    db_path = get_db_path(db)
    pattern_db = PatternDB(init_db(db_path))

    if category:
        patterns = pattern_db.search_by_category(category)
    elif opcode:
        # Search for opcode in either position
        patterns = []
        for p in pattern_db.list_all():
            if opcode.lower() in [o.lower() for o in p.opcodes]:
                patterns.append(p)
    else:
        patterns = pattern_db.list_all()

    if as_json:
        rprint(json.dumps([p.to_dict() for p in patterns], indent=2))
    else:
        if not patterns:
            rprint("No patterns found.")
            return

        for p in patterns:
            cats = ", ".join(p.categories[:3]) if p.categories else "none"
            rprint(f"  {p.id:<40} [{cats}]")
            rprint(f"    {p.name}")


@mismatch_app.command()
def get(
    pattern_id: str,
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Get details for a specific pattern."""
    db_path = get_db_path(db)
    pattern_db = PatternDB(init_db(db_path))
    pattern = pattern_db.get(pattern_id)

    if not pattern:
        rprint(f"[red]Pattern not found: {pattern_id}[/red]")
        raise typer.Exit(1)

    if as_json:
        rprint(json.dumps(pattern.to_dict(), indent=2))
    else:
        rprint(f"\n{pattern.name}")
        rprint("=" * len(pattern.name))
        rprint(f"\nID: {pattern.id}")
        rprint(f"Categories: {', '.join(pattern.categories)}")
        rprint(f"Opcodes: {', '.join(pattern.opcodes[:10])}")

        rprint(f"\nDescription:\n  {pattern.description}")
        rprint(f"\nRoot Cause:\n  {pattern.root_cause}")

        if pattern.signals:
            rprint(f"\nSignals ({len(pattern.signals)}):")
            for s in pattern.signals:
                rprint(f"  - [{s.type}] {s.data}")

        if pattern.fixes:
            rprint(f"\nFixes ({len(pattern.fixes)}):")
            for f in pattern.fixes:
                rprint(f"  - {f.description[:80]}...")

        if pattern.examples:
            rprint(f"\nExamples ({len(pattern.examples)}):")
            for e in pattern.examples:
                rprint(f"  - {e.function}: {e.context or 'no context'}")

        if pattern.provenance.helped_match:
            rprint(f"\nHelped match ({len(pattern.provenance.helped_match)}):")
            for p in pattern.provenance.helped_match[:5]:
                rprint(f"  - {p.function}")


@mismatch_app.command()
def search(
    query: str,
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
):
    """Full-text search across patterns."""
    db_path = get_db_path(db)
    pattern_db = PatternDB(init_db(db_path))
    patterns = pattern_db.search_fulltext(query)

    if not patterns:
        rprint(f"No patterns found for: {query}")
        return

    rprint(f"Found {len(patterns)} pattern(s):\n")
    for p in patterns:
        rprint(f"  {p.id}")
        rprint(f"    {p.name}")
        rprint(f"    {p.description[:100]}...")
        rprint()


@mismatch_app.command()
def opcode(
    expected: str,
    actual: str,
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
):
    """Find patterns by opcode mismatch (expected vs actual)."""
    db_path = get_db_path(db)
    pattern_db = PatternDB(init_db(db_path))
    patterns = pattern_db.search_by_opcode(expected.lower(), actual.lower())

    if not patterns:
        rprint(f"No patterns found for {expected} → {actual}")
        # Try reverse
        patterns = pattern_db.search_by_opcode(actual.lower(), expected.lower())
        if patterns:
            rprint(f"(Found {len(patterns)} for reverse: {actual} → {expected})")

    for p in patterns:
        rprint(f"\n{p.name}")
        rprint(f"  ID: {p.id}")
        rprint(f"  {p.description[:150]}...")
        if p.fixes:
            rprint(f"  Fix: {p.fixes[0].description[:100]}...")


@mismatch_app.command()
def m2c(
    artifact: str,
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
):
    """Find patterns related to an m2c artifact (e.g., M2C_STRUCT_COPY)."""
    db_path = get_db_path(db)
    pattern_db = PatternDB(init_db(db_path))
    patterns = pattern_db.search_by_m2c_artifact(artifact.upper())

    if not patterns:
        rprint(f"No patterns found for m2c artifact: {artifact}")
        return

    for p in patterns:
        rprint(f"\n{p.name}")
        rprint(f"  ID: {p.id}")
        rprint(f"  {p.description[:150]}...")


@mismatch_app.command()
def record_success(
    pattern_id: str,
    function: str,
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
    scratch: Annotated[str | None, typer.Option(help="decomp.me scratch slug")] = None,
):
    """Record that a pattern helped match a function."""
    db_path = get_db_path(db)
    pattern_db = PatternDB(init_db(db_path))

    pattern = pattern_db.get(pattern_id)
    if not pattern:
        rprint(f"[red]Pattern not found: {pattern_id}[/red]")
        raise typer.Exit(1)

    pattern_db.record_success(pattern_id, function, scratch)
    rprint(f"Recorded: {pattern_id} helped match {function}")


@mismatch_app.command()
def migrate(
    markdown_file: Annotated[Path, typer.Argument(help="Markdown file to migrate")],
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Parse only, do not insert")] = False,
):
    """Migrate patterns from a markdown file."""
    if not markdown_file.exists():
        rprint(f"[red]File not found: {markdown_file}[/red]")
        raise typer.Exit(1)

    db_path = get_db_path(db)
    pattern_db = PatternDB(init_db(db_path))

    rprint(f"Parsing: {markdown_file}")
    patterns = migrate_markdown_file(markdown_file, pattern_db, dry_run=dry_run)

    rprint(f"\nParsed {len(patterns)} patterns")

    if dry_run:
        rprint("\nDry run - patterns not inserted. Preview:")
        for p in patterns:
            rprint(f"  {p.id}: {p.name}")
            rprint(f"    Categories: {p.categories}")
            rprint(f"    Signals: {len(p.signals)}")


@mismatch_app.command()
def stats(
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
):
    """Show database statistics."""
    db_path = get_db_path(db)
    pattern_db = PatternDB(init_db(db_path))
    patterns = pattern_db.list_all()

    rprint("\nMismatch Pattern Database")
    rprint("=" * 30)
    rprint(f"Database: {db_path}")
    rprint(f"Total patterns: {len(patterns)}")

    # Category breakdown
    categories = {}
    for p in patterns:
        for c in p.categories:
            categories[c] = categories.get(c, 0) + 1

    rprint("\nBy category:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        rprint(f"  {cat}: {count}")

    # Patterns with provenance
    with_prov = sum(1 for p in patterns if p.provenance.helped_match)
    rprint(f"\nPatterns with success records: {with_prov}")


# =============================================================================
# BACKFILL COMMANDS
# =============================================================================


@backfill_app.command("create-job")
def backfill_create_job(
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
    commit_range: Annotated[str, typer.Option("--range", help="Git commit range")] = "HEAD~50..HEAD",
    filter_pattern: Annotated[str, typer.Option("--filter", help="Commit message filter regex")] = r"[Mm]atch|100%",
):
    """Create a new backfill job."""
    db_path = get_db_path(db)
    melee_repo = Path.home() / "code" / "melee"
    if not melee_repo.exists():
        rprint(f"[red]Melee repo not found at {melee_repo}[/red]")
        raise typer.Exit(1)

    orchestrator = BackfillOrchestrator(db_path)
    job_id = orchestrator.create_job(commit_range=commit_range, filter_pattern=filter_pattern)
    rprint(f"Created job: {job_id}")

    num_tasks = orchestrator.populate_tasks(job_id, melee_repo)
    rprint(f"Created {num_tasks} analysis tasks")
    rprint("\nNext steps:")
    rprint(f"  1. Run analysis agents: backfill claim-task {job_id}")
    rprint("  2. Review candidates: backfill review")


@backfill_app.command("list-jobs")
def backfill_list_jobs(
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
):
    """List all backfill jobs."""
    db_path = get_db_path(db)
    orchestrator = BackfillOrchestrator(db_path)
    jobs = orchestrator.list_jobs()

    if not jobs:
        rprint("No backfill jobs found.")
        return

    rprint(f"\n{'ID':<10} {'Status':<12} {'Progress':<15} {'Candidates':<12}")
    rprint("-" * 50)
    for job in jobs:
        progress = f"{job.processed_commits}/{job.total_commits}"
        rprint(f"{job.id:<10} {job.status.value:<12} {progress:<15} {job.candidates_found:<12}")


@backfill_app.command("job-status")
def backfill_job_status(
    job_id: str,
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
):
    """Show detailed status for a backfill job."""
    db_path = get_db_path(db)
    orchestrator = BackfillOrchestrator(db_path)
    job = orchestrator.get_job(job_id)

    if not job:
        rprint(f"[red]Job not found: {job_id}[/red]")
        raise typer.Exit(1)

    rprint(f"\nBackfill Job: {job.id}")
    rprint("=" * 40)
    rprint(f"Status: {job.status.value}")
    rprint(f"Config: {json.dumps(job.config, indent=2)}")
    rprint(f"Progress: {job.processed_commits}/{job.total_commits} commits")
    rprint(f"Candidates found: {job.candidates_found}")

    tasks = orchestrator.list_tasks(job_id)
    by_status = {}
    for t in tasks:
        by_status[t.status.value] = by_status.get(t.status.value, 0) + 1

    rprint("\nTasks by status:")
    for status, count in by_status.items():
        rprint(f"  {status}: {count}")


@backfill_app.command("list-tasks")
def backfill_list_tasks(
    job_id: str,
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
    status: Annotated[str | None, typer.Option(help="Filter by status (pending, assigned, completed, failed)")] = None,
):
    """List tasks for a backfill job."""
    db_path = get_db_path(db)
    orchestrator = BackfillOrchestrator(db_path)
    task_status = TaskStatus(status) if status else None
    tasks = orchestrator.list_tasks(job_id, task_status)

    if not tasks:
        rprint("No tasks found.")
        return

    for t in tasks:
        func = t.function_name or "unknown"
        rprint(f"  {t.id:<10} [{t.status.value:<10}] {func:<30} {t.commit_message[:40] if t.commit_message else ''}")


@backfill_app.command("claim-task")
def backfill_claim_task(
    job_id: str,
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
    agent: Annotated[str, typer.Option(help="Agent ID claiming the task")] = "cli",
):
    """Claim a pending task for analysis."""
    db_path = get_db_path(db)
    orchestrator = BackfillOrchestrator(db_path)
    task = orchestrator.claim_task(job_id, agent)

    if not task:
        rprint("No pending tasks available.")
        return

    rprint(f"Claimed task: {task.id}")
    rprint(f"  Commit: {task.commit_sha}")
    rprint(f"  Message: {task.commit_message}")
    rprint(f"  Function: {task.function_name}")
    rprint(f"  File: {task.file_path}")

    # Generate analysis prompt
    rprint("\n--- Analysis Prompt ---")
    prompt = generate_analysis_prompt(task)
    rprint(prompt[:2000] + "..." if len(prompt) > 2000 else prompt)


@backfill_app.command("get-task")
def backfill_get_task(
    task_id: str,
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
    prompt: Annotated[bool, typer.Option("--prompt", help="Show analysis prompt")] = False,
):
    """Get details for a specific task."""
    db_path = get_db_path(db)
    orchestrator = BackfillOrchestrator(db_path)
    task = orchestrator.get_task(task_id)

    if not task:
        rprint(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)

    rprint(f"\nTask: {task.id}")
    rprint(f"Status: {task.status.value}")
    rprint(f"Commit: {task.commit_sha}")
    rprint(f"Message: {task.commit_message}")
    rprint(f"Function: {task.function_name}")
    rprint(f"File: {task.file_path}")

    if task.analysis_notes:
        rprint(f"\nAnalysis Notes:\n{task.analysis_notes}")

    if prompt:
        rprint("\n--- Analysis Prompt ---")
        rprint(generate_analysis_prompt(task))


@backfill_app.command("complete-task")
def backfill_complete_task(
    task_id: str,
    result_file: Annotated[Path, typer.Argument(help="JSON file with analysis results")],
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
):
    """Complete a task with analysis results from a JSON file."""
    if not result_file.exists():
        rprint(f"[red]File not found: {result_file}[/red]")
        raise typer.Exit(1)

    db_path = get_db_path(db)
    orchestrator = BackfillOrchestrator(db_path)

    with open(result_file) as f:
        result = json.load(f)

    analysis_notes = result.get("analysis_notes", "")
    candidates = result.get("candidates", [])

    orchestrator.complete_task(task_id, analysis_notes, candidates)
    rprint(f"Completed task {task_id} with {len(candidates)} candidate(s)")


# =============================================================================
# REVIEW COMMANDS
# =============================================================================


@review_app.command("list")
def review_list(
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
    job_id: Annotated[str | None, typer.Option("--job", help="Filter by job ID")] = None,
):
    """List pending candidate patterns."""
    db_path = get_db_path(db)
    reviewer = CandidateReviewer(db_path)
    candidates = reviewer.list_pending(job_id)

    if not candidates:
        rprint("No pending candidates.")
        return

    rprint(f"\n{'ID':<6} {'Confidence':<12} {'Function':<25} {'Name':<40}")
    rprint("-" * 85)
    for c in candidates:
        func = (c.source_function or "?")[:24]
        name = c.name[:39]
        rprint(f"{c.id:<6} {c.confidence:<12.2f} {func:<25} {name:<40}")


@review_app.command("show")
def review_show(
    candidate_id: int,
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Show details for a candidate pattern."""
    db_path = get_db_path(db)
    reviewer = CandidateReviewer(db_path)
    candidate = reviewer.get_candidate(candidate_id)

    if not candidate:
        rprint(f"[red]Candidate not found: {candidate_id}[/red]")
        raise typer.Exit(1)

    if as_json:
        rprint(
            json.dumps(
                {
                    "id": candidate.id,
                    "name": candidate.name,
                    "description": candidate.description,
                    "root_cause": candidate.root_cause,
                    "signals": candidate.signals,
                    "examples": candidate.examples,
                    "fixes": candidate.fixes,
                    "opcodes": candidate.opcodes,
                    "categories": candidate.categories,
                    "confidence": candidate.confidence,
                    "source_function": candidate.source_function,
                    "source_commit": candidate.source_commit,
                },
                indent=2,
            )
        )
    else:
        rprint(f"\nCandidate #{candidate.id}: {candidate.name}")
        rprint("=" * 60)
        rprint(f"Suggested ID: {candidate.suggested_id}")
        rprint(f"Confidence: {candidate.confidence:.2f}")
        rprint(
            f"Source: {candidate.source_function} ({candidate.source_commit[:8] if candidate.source_commit else '?'})"
        )
        rprint(f"\nDescription:\n  {candidate.description}")
        rprint(f"\nRoot Cause:\n  {candidate.root_cause}")
        rprint(f"\nCategories: {candidate.categories}")
        rprint(f"Opcodes: {candidate.opcodes}")

        if candidate.signals:
            rprint("\nSignals:")
            for s in candidate.signals:
                rprint(f"  - {s}")

        if candidate.fixes:
            rprint("\nFixes:")
            for f in candidate.fixes:
                rprint(f"  - {f.get('description', '?')[:80]}")

        # Show similar patterns
        similar = reviewer.find_similar(candidate_id, threshold=0.3)
        if similar:
            rprint("\nSimilar existing patterns:")
            for pattern_id, score in similar[:3]:
                rprint(f"  - {pattern_id} (similarity: {score:.2f})")


@review_app.command("approve")
def review_approve(
    candidate_id: int,
    pattern_id: str,
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
    notes: Annotated[str | None, typer.Option(help="Review notes")] = None,
):
    """Approve a candidate as a new pattern."""
    db_path = get_db_path(db)
    reviewer = CandidateReviewer(db_path)
    reviewer.approve(candidate_id, pattern_id, reviewer="cli", notes=notes)
    rprint(f"Approved candidate #{candidate_id} as pattern: {pattern_id}")


@review_app.command("reject")
def review_reject(
    candidate_id: int,
    reason: str,
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
):
    """Reject a candidate pattern."""
    db_path = get_db_path(db)
    reviewer = CandidateReviewer(db_path)
    reviewer.reject(candidate_id, reason, reviewer="cli")
    rprint(f"Rejected candidate #{candidate_id}: {reason}")


@review_app.command("merge")
def review_merge(
    candidate_id: int,
    existing_pattern_id: str,
    db: Annotated[Path | None, typer.Option(help="Database path")] = None,
    notes: Annotated[str | None, typer.Option(help="Merge notes")] = None,
):
    """Merge a candidate into an existing pattern."""
    db_path = get_db_path(db)
    reviewer = CandidateReviewer(db_path)
    reviewer.merge(candidate_id, existing_pattern_id, reviewer="cli", notes=notes)
    rprint(f"Merged candidate #{candidate_id} into pattern: {existing_pattern_id}")


def main():
    mismatch_app()


if __name__ == "__main__":
    main()
