"""CLI for source-transform corpus mining."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich import print as rprint

from src.source_transform_mining import (
    DEFAULT_DB_PATH,
    TransformMiningStore,
    generate_analysis_prompt,
)


transform_corpus_app = typer.Typer(help="Source-transform corpus tooling.")
mine_app = typer.Typer(help="Mine source-transform corpus candidates from history.")
transform_corpus_app.add_typer(mine_app, name="mine")


def _store(db: Path | None) -> TransformMiningStore:
    return TransformMiningStore(db or DEFAULT_DB_PATH)


@mine_app.command("create-job")
def create_job(
    repo: Annotated[Path | None, typer.Option("--repo", help="Melee repo to scan")] = None,
    db: Annotated[Path | None, typer.Option("--db", help="Mining ledger database path")] = None,
    commit_range: Annotated[str, typer.Option("--range", help="Git commit range to scan")] = "HEAD~50..HEAD",
    filter_pattern: Annotated[
        str,
        typer.Option("--filter", help="Commit subject filter regex"),
    ] = r"[Mm]atch|100%",
    include_additions: Annotated[
        bool,
        typer.Option(
            "--include-additions",
            help="Include newly added functions instead of only before/after rewrites",
        ),
    ] = False,
):
    """Create a mining job from unseen commit/function source transitions."""

    repo = repo or Path.cwd()
    if not repo.exists():
        rprint(f"[red]Repo not found: {repo}[/red]")
        raise typer.Exit(2)
    result = _store(db).create_job(
        repo=repo,
        commit_range=commit_range,
        filter_pattern=filter_pattern,
        include_additions=include_additions,
    )
    rprint(f"Created job: {result.job_id}")
    rprint(f"Queued tasks: {result.tasks_created}")
    rprint(f"Skipped ledger hits: {result.skipped_ledger_hits}")
    if result.tasks_created:
        rprint(
            "\nNext: "
            f"melee-agent transform-corpus mine claim-task {result.job_id}"
        )


@mine_app.command("job-status")
def job_status(
    job_id: str,
    db: Annotated[Path | None, typer.Option("--db", help="Mining ledger database path")] = None,
):
    """Show status for a mining job."""

    try:
        status = _store(db).job_status(job_id)
    except ValueError as exc:
        rprint(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    rprint(f"\nTransform mining job: {status.id}")
    rprint("=" * 40)
    rprint(f"Status: {status.status}")
    rprint(f"Progress: {status.processed_tasks}/{status.total_tasks} tasks")
    rprint(f"Skipped ledger hits: {status.skipped_ledger_hits}")
    rprint(f"Config: {json.dumps(status.config, indent=2)}")


@mine_app.command("list-tasks")
def list_tasks(
    job_id: str,
    db: Annotated[Path | None, typer.Option("--db", help="Mining ledger database path")] = None,
    status: Annotated[str | None, typer.Option("--status", help="Filter by task status")] = None,
):
    """List tasks for a mining job."""

    tasks = _store(db).list_tasks(job_id, status=status)
    if not tasks:
        rprint("No tasks found.")
        return
    for task in tasks:
        rprint(
            f"{task.id:<10} [{task.status:<9}] "
            f"{task.function_name:<30} {task.file_path}"
        )


@mine_app.command("claim-task")
def claim_task(
    job_id: str,
    db: Annotated[Path | None, typer.Option("--db", help="Mining ledger database path")] = None,
    agent: Annotated[str, typer.Option("--agent", help="Agent ID claiming the task")] = "cli",
    prompt: Annotated[bool, typer.Option("--prompt", help="Print review prompt")] = True,
    existing_only: Annotated[
        bool,
        typer.Option("--existing-only", help="Only claim tasks with before/after source"),
    ] = False,
):
    """Claim the next pending mining task."""

    task = _store(db).claim_task(job_id, agent_id=agent, existing_only=existing_only)
    if task is None:
        rprint("No pending tasks available.")
        return
    rprint(f"Claimed task: {task.id}")
    rprint(f"  Commit: {task.commit_sha}")
    rprint(f"  Function: {task.function_name}")
    rprint(f"  File: {task.file_path}")
    if prompt:
        rprint("\n--- Analysis Prompt ---")
        rprint(generate_analysis_prompt(task))


@mine_app.command("get-task")
def get_task(
    task_id: str,
    db: Annotated[Path | None, typer.Option("--db", help="Mining ledger database path")] = None,
    prompt: Annotated[bool, typer.Option("--prompt", help="Print review prompt")] = False,
):
    """Show one mining task."""

    task = _store(db).get_task(task_id)
    if task is None:
        rprint(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)
    rprint(f"\nTask: {task.id}")
    rprint(f"Status: {task.status}")
    rprint(f"Commit: {task.commit_sha}")
    rprint(f"Function: {task.function_name}")
    rprint(f"File: {task.file_path}")
    rprint(f"Result kind: {task.result_kind or '-'}")
    rprint(f"Family: {task.family_id or '-'}")
    if task.analysis_notes:
        rprint(f"\nAnalysis notes:\n{task.analysis_notes}")
    if prompt:
        rprint("\n--- Analysis Prompt ---")
        rprint(generate_analysis_prompt(task))


@mine_app.command("complete-task")
def complete_task(
    task_id: str,
    result_file: Annotated[Path, typer.Argument(help="JSON file with analysis result")],
    db: Annotated[Path | None, typer.Option("--db", help="Mining ledger database path")] = None,
):
    """Complete a mining task from a result JSON file."""

    if not result_file.exists():
        rprint(f"[red]Result file not found: {result_file}[/red]")
        raise typer.Exit(2)
    result = json.loads(result_file.read_text())
    _store(db).complete_task(
        task_id,
        analysis_notes=str(result.get("analysis_notes") or ""),
        result_kind=str(result.get("result_kind") or "not-useful"),
        family_id=result.get("family_id"),
    )
    rprint(f"Completed task: {task_id}")


@mine_app.command("fail-task")
def fail_task(
    task_id: str,
    error_message: str,
    db: Annotated[Path | None, typer.Option("--db", help="Mining ledger database path")] = None,
):
    """Mark a mining task as failed."""

    _store(db).fail_task(task_id, error_message)
    rprint(f"Failed task: {task_id}")


@mine_app.command("ledger-stats")
def ledger_stats(
    db: Annotated[Path | None, typer.Option("--db", help="Mining ledger database path")] = None,
):
    """Show ledger counts by status."""

    stats = _store(db).ledger_stats()
    if not stats:
        rprint("Ledger is empty.")
        return
    for status, count in stats.items():
        rprint(f"{status}: {count}")


@mine_app.command("complete-additions")
def complete_additions(
    job_id: str,
    db: Annotated[Path | None, typer.Option("--db", help="Mining ledger database path")] = None,
    notes: Annotated[
        str,
        typer.Option("--notes", help="Analysis note recorded on completed tasks"),
    ] = "Function addition only; no before/after source rewrite to mine.",
):
    """Complete pending function additions as out of scope."""

    completed = _store(db).complete_pending_additions(
        job_id,
        analysis_notes=notes,
    )
    rprint(f"Completed addition-only tasks: {completed}")


@mine_app.command("clusters")
def clusters(
    job_id: str,
    db: Annotated[Path | None, typer.Option("--db", help="Mining ledger database path")] = None,
    status: Annotated[str, typer.Option("--status", help="Task status to cluster")] = "pending",
    max_clusters: Annotated[int, typer.Option("--max-clusters", help="Maximum clusters to print")] = 25,
    sample_size: Annotated[int, typer.Option("--sample-size", help="Samples per cluster")] = 3,
):
    """List normalized before/after diff clusters for existing-function tasks."""

    found = _store(db).diff_clusters(job_id, status=status, sample_size=sample_size)
    if not found:
        rprint("No diff clusters found.")
        return
    for cluster in found[:max_clusters]:
        samples = ", ".join(
            f"{task.function_name} ({task.file_path})" for task in cluster.samples
        )
        rprint(f"{cluster.signature:<18} {cluster.task_count:<5} {samples}")


@mine_app.command("complete-cluster")
def complete_cluster(
    job_id: str,
    signature: str,
    db: Annotated[Path | None, typer.Option("--db", help="Mining ledger database path")] = None,
    result_kind: Annotated[
        str,
        typer.Option("--result-kind", help="Classification to record"),
    ] = "not-useful",
    family_id: Annotated[
        str | None,
        typer.Option("--family-id", help="Transform family for useful clusters"),
    ] = None,
    notes: Annotated[
        str,
        typer.Option("--notes", help="Analysis note recorded on completed tasks"),
    ] = "Cluster reviewed and classified in bulk.",
    max_tasks: Annotated[
        int | None,
        typer.Option("--max-tasks", help="Optional cap for one bulk completion"),
    ] = None,
):
    """Complete all pending tasks in a normalized diff cluster."""

    completed = _store(db).complete_cluster(
        job_id,
        signature,
        analysis_notes=notes,
        result_kind=result_kind,
        family_id=family_id,
        max_tasks=max_tasks,
    )
    rprint(f"Completed cluster tasks: {completed}")


@mine_app.command("results")
def results(
    db: Annotated[Path | None, typer.Option("--db", help="Mining ledger database path")] = None,
    result_kind: Annotated[
        str | None,
        typer.Option("--result-kind", help="Filter by completed task classification"),
    ] = None,
):
    """List completed mining task classifications."""

    tasks = _store(db).list_results(result_kind=result_kind)
    if not tasks:
        rprint("No completed results found.")
        return
    for task in tasks:
        rprint(
            f"{task.id:<10} {task.result_kind or '-':<28} "
            f"{task.family_id or '-':<32} {task.function_name:<30} {task.file_path}"
        )
