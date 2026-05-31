"""Tool issue commands for agent-reported bugs, papercuts, and requests."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from src.client.api import _get_agent_id
from src.db import get_db

from ._common import console
from .complete import _get_current_branch

issue_app = typer.Typer(help="Report and track tooling issues")


def _detect_session_id() -> str | None:
    """Return the best available Claude/Codex session identifier."""
    for env_name in (
        "CODEX_THREAD_ID",
        "CLAUDE_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CONVERSATION_ID",
    ):
        value = os.environ.get(env_name)
        if value:
            return value
    return None


def _detect_worktree_path() -> str:
    """Return the current git worktree root, falling back to cwd."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return str(Path.cwd())


def _normalize_functions(functions: list[str]) -> list[str]:
    """Normalize repeated --function values."""
    return [function.strip() for function in functions if function.strip()]


def _echo_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, default=str))


@issue_app.command("report")
def report_command(
    summary: Annotated[str, typer.Argument(help="Short summary of the tooling issue")],
    kind: Annotated[
        str,
        typer.Option("--kind", "-k", help="Issue kind: bug, feature, papercut, blocker, note"),
    ] = "bug",
    tool: Annotated[str | None, typer.Option("--tool", "-t", help="Tool or subsystem involved")] = None,
    body: Annotated[str | None, typer.Option("--body", "-b", help="Detailed context or failure output")] = None,
    functions: Annotated[
        list[str] | None,
        typer.Option("--function", "-f", help="Function this issue blocked or affected; repeatable"),
    ] = None,
    agent_id: Annotated[
        str | None,
        typer.Option("--agent-id", help="Reporting agent ID; auto-detected when omitted"),
    ] = None,
    session_id: Annotated[
        str | None,
        typer.Option("--session-id", help="Claude/Codex session or thread ID; auto-detected when omitted"),
    ] = None,
    worktree: Annotated[
        str | None,
        typer.Option("--worktree", help="Worktree path; auto-detected when omitted"),
    ] = None,
    branch: Annotated[str | None, typer.Option("--branch", help="Git branch; auto-detected when omitted")] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Report a tooling issue, feature request, papercut, or blocker."""
    worktree_path = worktree or _detect_worktree_path()
    branch_name = branch or _get_current_branch(Path(worktree_path))

    db = get_db()
    try:
        issue = db.report_tool_issue(
            summary=summary,
            kind=kind,
            tool=tool,
            body=body,
            functions=_normalize_functions(functions or []),
            agent_id=agent_id or _get_agent_id(),
            session_id=session_id or _detect_session_id(),
            worktree_path=worktree_path,
            branch=branch_name,
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)

    if output_json:
        _echo_json(issue)
        return

    console.print(f"[green]Reported issue #{issue['id']}[/green]: {issue['summary']}")
    console.print(f"[dim]View: melee-agent issue show {issue['id']}[/dim]")


@issue_app.command("list")
def list_command(
    status: Annotated[str, typer.Option("--status", "-s", help="Filter by status: open, resolved, all")] = "open",
    tool: Annotated[str | None, typer.Option("--tool", "-t", help="Filter by tool")] = None,
    kind: Annotated[str | None, typer.Option("--kind", "-k", help="Filter by kind")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum issues to show")] = 50,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """List reported tooling issues."""
    db = get_db()
    try:
        issues = db.list_tool_issues(status=status, tool=tool, kind=kind, limit=limit)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)

    if output_json:
        _echo_json(issues)
        return

    if not issues:
        console.print("[dim]No tool issues found[/dim]")
        return

    table = Table(title="Tool Issues")
    table.add_column("ID", justify="right")
    table.add_column("Status")
    table.add_column("Kind")
    table.add_column("Tool")
    table.add_column("Summary", max_width=60)
    table.add_column("Functions", max_width=28)

    for issue in issues:
        table.add_row(
            str(issue["id"]),
            issue["status"],
            issue["kind"],
            issue.get("tool") or "-",
            issue["summary"],
            ", ".join(issue.get("functions") or []) or "-",
        )

    console.print(table)


@issue_app.command("show")
def show_command(
    issue_id: Annotated[int, typer.Argument(help="Issue ID")],
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Show one reported tooling issue."""
    issue = get_db().get_tool_issue(issue_id)
    if issue is None:
        console.print(f"[red]Issue not found: {issue_id}[/red]")
        raise typer.Exit(1)

    if output_json:
        _echo_json(issue)
        return

    console.print(f"[bold cyan]Issue #{issue['id']}[/bold cyan] {issue['summary']}")
    console.print(f"[bold]Status:[/bold] {issue['status']}")
    console.print(f"[bold]Kind:[/bold] {issue['kind']}")
    console.print(f"[bold]Tool:[/bold] {issue.get('tool') or '-'}")
    if issue.get("functions"):
        console.print(f"[bold]Functions:[/bold] {', '.join(issue['functions'])}")
    if issue.get("agent_id"):
        console.print(f"[bold]Agent:[/bold] {issue['agent_id']}")
    if issue.get("session_id"):
        console.print(f"[bold]Session:[/bold] {issue['session_id']}")
    if issue.get("worktree_path"):
        console.print(f"[bold]Worktree:[/bold] {issue['worktree_path']}")
    if issue.get("branch"):
        console.print(f"[bold]Branch:[/bold] {issue['branch']}")
    if issue.get("body"):
        console.print(f"\n{issue['body']}")
    if issue.get("status") == "resolved":
        console.print(f"\n[bold]Resolved by:[/bold] {issue.get('resolved_by_agent') or '-'}")
        if issue.get("resolution_note"):
            console.print(f"[bold]Resolution:[/bold] {issue['resolution_note']}")


@issue_app.command("resolve")
def resolve_command(
    issue_id: Annotated[int, typer.Argument(help="Issue ID")],
    note: Annotated[str | None, typer.Option("--note", "-n", help="Resolution note")] = None,
    agent_id: Annotated[
        str | None,
        typer.Option("--agent-id", help="Resolving agent ID; auto-detected when omitted"),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Mark a reported tooling issue as resolved."""
    issue = get_db().resolve_tool_issue(
        issue_id,
        agent_id=agent_id or _get_agent_id(),
        resolution_note=note,
    )
    if issue is None:
        console.print(f"[red]Issue not found: {issue_id}[/red]")
        raise typer.Exit(1)

    if output_json:
        _echo_json(issue)
        return

    console.print(f"[green]Resolved issue #{issue['id']}[/green]: {issue['summary']}")
