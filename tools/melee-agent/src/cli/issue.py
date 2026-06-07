"""Tool issue commands for agent-reported bugs, papercuts, and requests."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.table import Table

from src.client.api import _get_agent_id
from src.db import get_db

from ._common import console
from .complete import _get_current_branch

issue_app = typer.Typer(help="Report and track tooling issues")

GOVERNANCE_FIELDS = {
    "reusable_class": "Reusable class",
    "applies_to": "Applies to",
    "source_actionable_output": "Source-actionable output",
    "stop_condition": "Stop condition",
    "existing_workflow_failed": "Existing workflow failed",
}
IMPACT_VALUES = {
    "matched",
    "retained-source-improvement",
    "negative-evidence",
    "infrastructure-only",
    "diagnostic-only",
}
FEATURE_LIKE_BLOCKER_RE = re.compile(
    r"\b(needs?|add|support|missing|lacks?|should|capability|no\s+[-\w ]*model)\b",
    re.IGNORECASE,
)


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


def _body_has_governance(body: str | None) -> bool:
    if not body:
        return False
    for label in GOVERNANCE_FIELDS.values():
        pattern = rf"^\s*(?:-\s*)?{re.escape(label)}\s*:"
        if re.search(pattern, body, re.IGNORECASE | re.MULTILINE) is None:
            return False
    return True


def _governance_flag_values(
    *,
    reusable_class: str | None,
    applies_to: list[str],
    source_actionable_output: str | None,
    stop_condition: str | None,
    existing_workflow_failed: str | None,
) -> dict[str, str]:
    return {
        "reusable_class": (reusable_class or "").strip(),
        "applies_to": ", ".join(_normalize_functions(applies_to)),
        "source_actionable_output": (source_actionable_output or "").strip(),
        "stop_condition": (stop_condition or "").strip(),
        "existing_workflow_failed": (existing_workflow_failed or "").strip(),
    }


def _missing_governance_fields(values: dict[str, str]) -> list[str]:
    return [label for key, label in GOVERNANCE_FIELDS.items() if not values.get(key)]


def _append_body_section(body: str | None, section: str) -> str:
    existing = (body or "").strip()
    if not existing:
        return section
    return f"{existing}\n\n{section}"


def _append_governance_section(body: str | None, values: dict[str, str]) -> str:
    lines = ["Governance:"]
    for key, label in GOVERNANCE_FIELDS.items():
        lines.append(f"{label}: {values[key]}")
    return _append_body_section(body, "\n".join(lines))


def _append_governance_waiver(body: str | None, waiver: str) -> str:
    return _append_body_section(body, f"Governance:\nGovernance waiver: {waiver.strip()}")


def _looks_like_feature_blocker(summary: str, body: str | None) -> bool:
    text = f"{summary}\n{body or ''}"
    return FEATURE_LIKE_BLOCKER_RE.search(text) is not None


def _append_impact_note(note: str | None, impact: str | None) -> str | None:
    if impact is None:
        return note
    normalized = impact.strip().lower()
    if normalized not in IMPACT_VALUES:
        valid = ", ".join(sorted(IMPACT_VALUES))
        raise ValueError(f"impact must be one of: {valid}")
    impact_line = f"impact={normalized}"
    clean_note = (note or "").strip()
    if not clean_note:
        return impact_line
    if re.search(r"^impact=", clean_note, re.MULTILINE):
        return clean_note
    return f"{clean_note}\n{impact_line}"


def _echo_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _issue_text(issue: dict[str, Any]) -> str:
    return "\n".join(
        str(issue.get(key) or "")
        for key in ("summary", "body", "resolution_note")
    )


def _extract_impact(note: str | None) -> str:
    if not note:
        return ""
    match = re.search(r"^impact=([-\w]+)\s*$", note, re.MULTILINE)
    return match.group(1).strip().lower() if match else ""


def _extract_governance_applies_to(body: str | None) -> list[str]:
    if not body:
        return []
    match = re.search(r"^\s*Applies to\s*:\s*(.+)$", body, re.IGNORECASE | re.MULTILINE)
    if match is None:
        return []
    raw = match.group(1)
    return [
        part.strip()
        for part in re.split(r"[,;]", raw)
        if part.strip()
    ]


def _attempt_roi_for_functions(functions: list[str]) -> dict[str, Any]:
    from .tracking import summarize_attempts

    by_function: dict[str, Any] = {}
    attempt_count = 0
    retained_source_wins = 0
    negative_evidence = 0
    recent_blockers: list[str] = []
    for function_name in sorted(set(functions)):
        summary = summarize_attempts(function_name)
        by_function[function_name] = {
            "exists": summary["exists"],
            "attempt_count": summary["attempt_count"],
            "retained_improvements": summary["retained_improvements"],
            "best_match_percent": summary["best_match_percent"],
            "ledger_best_match_percent": summary["ledger_best_match_percent"],
            "move_on_recommended": summary["move_on_recommended"],
            "move_on_reason": summary["move_on_reason"],
            "recent_blockers": summary["recent_blockers"],
        }
        attempt_count += int(summary["attempt_count"])
        retained_source_wins += int(summary["retained_improvements"])
        recent_blockers.extend(str(blocker) for blocker in summary["recent_blockers"])
        for attempt in summary["attempts"]:
            outcome = str(attempt.get("outcome") or "")
            if outcome in {"neutral", "regressed", "reverted", "blocked"}:
                negative_evidence += 1
    return {
        "attempt_count": attempt_count,
        "retained_source_wins": retained_source_wins,
        "negative_evidence": negative_evidence,
        "recent_blockers": recent_blockers,
        "by_function": by_function,
    }


def _campaign_recommendation(
    *,
    status: str,
    impact: str,
    retained_source_wins: int,
    negative_evidence: int,
    generality_count: int,
) -> str:
    if status == "open":
        return "keep-investing"
    if impact == "negative-evidence":
        return "stop-or-defer"
    if impact in {"matched", "retained-source-improvement"} or retained_source_wins > 0:
        return "mature"
    if generality_count >= 3:
        return "mature"
    if impact in {"infrastructure-only", "diagnostic-only"}:
        return "mature"
    if negative_evidence > 0 and retained_source_wins == 0:
        return "stop-or-defer"
    return "keep-investing"


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
    reusable_class: Annotated[
        str | None,
        typer.Option("--reusable-class", help="Reusable mismatch/tooling class this feature targets"),
    ] = None,
    applies_to: Annotated[
        list[str] | None,
        typer.Option("--applies-to", help="Known function or class member this feature applies to; repeatable"),
    ] = None,
    source_actionable_output: Annotated[
        str | None,
        typer.Option("--source-actionable-output", help="Source-level output this feature will produce"),
    ] = None,
    stop_condition: Annotated[
        str | None,
        typer.Option("--stop-condition", help="Bounded condition for stopping this tooling path"),
    ] = None,
    existing_workflow_failed: Annotated[
        str | None,
        typer.Option("--existing-workflow-failed", help="Existing workflow/tool path that failed first"),
    ] = None,
    governance_waiver: Annotated[
        str | None,
        typer.Option("--governance-waiver", help="Explicit reason to bypass feature governance metadata"),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Report a tooling issue, feature request, papercut, or blocker."""
    worktree_path = worktree or _detect_worktree_path()
    branch_name = branch or _get_current_branch(Path(worktree_path))
    cleaned_functions = _normalize_functions(functions or [])
    applies_to_values = _normalize_functions(applies_to or []) or cleaned_functions

    if kind == "feature":
        if governance_waiver and governance_waiver.strip():
            body = _append_governance_waiver(body, governance_waiver)
        elif not _body_has_governance(body):
            governance_values = _governance_flag_values(
                reusable_class=reusable_class,
                applies_to=applies_to_values,
                source_actionable_output=source_actionable_output,
                stop_condition=stop_condition,
                existing_workflow_failed=existing_workflow_failed,
            )
            missing = _missing_governance_fields(governance_values)
            if missing:
                console.print(
                    "[red]Feature issues require governance metadata.[/red] "
                    "Provide labeled lines in --body or pass the dedicated "
                    "governance flags."
                )
                console.print("[red]Missing:[/red] " + ", ".join(missing))
                raise typer.Exit(2)
            body = _append_governance_section(body, governance_values)
    elif (
        kind == "blocker"
        and not output_json
        and not governance_waiver
        and not _body_has_governance(body)
        and _looks_like_feature_blocker(summary, body)
    ):
        console.print(
            "[yellow]This blocker looks like a feature request. "
            "If it is asking for new tooling capability, prefer "
            "--kind feature with governance metadata or add "
            "--governance-waiver.[/yellow]"
        )

    db = get_db()
    try:
        issue = db.report_tool_issue(
            summary=summary,
            kind=kind,
            tool=tool,
            body=body,
            functions=cleaned_functions,
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


@issue_app.command("campaign-report")
def campaign_report_command(
    functions: Annotated[
        list[str] | None,
        typer.Option("--function", "-f", help="Campaign function to analyze; repeatable"),
    ] = None,
    tool: Annotated[str | None, typer.Option("--tool", "-t", help="Filter by tool")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum issues to scan")] = 200,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Report tooling-campaign ROI, generality, and remaining gaps."""
    focus_functions = set(_normalize_functions(functions or []))
    db = get_db()
    issues = db.list_tool_issues(status="all", tool=tool, limit=limit)

    rows: list[dict[str, Any]] = []
    for issue in issues:
        issue_functions = list(issue.get("functions") or [])
        applies_to = _extract_governance_applies_to(issue.get("body"))
        generality_functions = sorted(set(issue_functions) | set(applies_to))
        text = _issue_text(issue)
        if focus_functions and not (
            focus_functions & set(generality_functions)
            or any(fn in text for fn in focus_functions)
        ):
            continue

        roi = _attempt_roi_for_functions(generality_functions or list(focus_functions))
        impact = _extract_impact(issue.get("resolution_note"))
        retained_source_wins = int(roi["retained_source_wins"])
        if impact in {"matched", "retained-source-improvement"}:
            retained_source_wins = max(retained_source_wins, 1)
        negative_evidence = int(roi["negative_evidence"])
        if impact == "negative-evidence":
            negative_evidence = max(negative_evidence, 1)
        downstream_functions = sorted(set(generality_functions) - focus_functions)
        recommendation = _campaign_recommendation(
            status=issue["status"],
            impact=impact,
            retained_source_wins=retained_source_wins,
            negative_evidence=negative_evidence,
            generality_count=len(generality_functions),
        )
        rows.append({
            "id": issue["id"],
            "status": issue["status"],
            "kind": issue["kind"],
            "tool": issue.get("tool") or "",
            "summary": issue["summary"],
            "functions": issue_functions,
            "applies_to": applies_to,
            "generality_functions": generality_functions,
            "downstream_functions": downstream_functions,
            "impact": impact,
            "attempt_count": roi["attempt_count"],
            "retained_source_wins": retained_source_wins,
            "negative_evidence": negative_evidence,
            "recent_blockers": roi["recent_blockers"],
            "attempts_by_function": roi["by_function"],
            "open_follow_up_gap": issue["status"] == "open",
            "recommendation": recommendation,
        })

    summary = {
        "issue_count": len(rows),
        "open_follow_up_gaps": sum(1 for row in rows if row["open_follow_up_gap"]),
        "retained_source_wins": sum(int(row["retained_source_wins"]) for row in rows),
        "negative_evidence": sum(int(row["negative_evidence"]) for row in rows),
        "mature": sum(1 for row in rows if row["recommendation"] == "mature"),
        "keep_investing": sum(1 for row in rows if row["recommendation"] == "keep-investing"),
        "stop_or_defer": sum(1 for row in rows if row["recommendation"] == "stop-or-defer"),
    }
    payload = {
        "functions": sorted(focus_functions),
        "tool": tool,
        "summary": summary,
        "issues": rows,
    }

    if output_json:
        _echo_json(payload)
        return

    if not rows:
        console.print("[dim]No campaign issues found[/dim]")
        return

    table = Table(title="Tooling Campaign ROI")
    table.add_column("ID", justify="right")
    table.add_column("Status")
    table.add_column("Impact")
    table.add_column("ROI", justify="right")
    table.add_column("Generality")
    table.add_column("Recommendation")
    table.add_column("Summary", max_width=48)
    for row in rows:
        table.add_row(
            str(row["id"]),
            row["status"],
            row["impact"] or "-",
            f"+{row['retained_source_wins']} / -{row['negative_evidence']}",
            str(len(row["generality_functions"])),
            row["recommendation"],
            row["summary"],
        )
    console.print(table)
    console.print(
        "Summary: "
        f"{summary['mature']} mature, "
        f"{summary['keep_investing']} keep-investing, "
        f"{summary['stop_or_defer']} stop/defer, "
        f"{summary['open_follow_up_gaps']} open gaps"
    )


@issue_app.command("list")
def list_command(
    status: Annotated[str, typer.Option("--status", "-s", help="Filter by status: open, resolved, all")] = "open",
    tool: Annotated[str | None, typer.Option("--tool", "-t", help="Filter by tool")] = None,
    kind: Annotated[str | None, typer.Option("--kind", "-k", help="Filter by kind")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum issues to show")] = 50,
    available: Annotated[
        bool,
        typer.Option("--available", "--unclaimed", help="Show only unclaimed open issues"),
    ] = False,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """List reported tooling issues."""
    db = get_db()
    try:
        issues = db.list_tool_issues(
            status=status, tool=tool, kind=kind, limit=limit, unclaimed_only=available
        )
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
    table.add_column("Summary", max_width=48)
    table.add_column("Functions", max_width=22)
    table.add_column("Claimed", max_width=16)

    for issue in issues:
        table.add_row(
            str(issue["id"]),
            issue["status"],
            issue["kind"],
            issue.get("tool") or "-",
            issue["summary"],
            ", ".join(issue.get("functions") or []) or "-",
            issue.get("claimed_by") or "-",
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


@issue_app.command("note")
def note_command(
    issue_id: Annotated[int, typer.Argument(help="Issue ID")],
    body: Annotated[str, typer.Option("--body", "-b", help="Note text to append")],
    agent_id: Annotated[
        str | None,
        typer.Option("--agent-id", help="Noting agent ID; auto-detected when omitted"),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Append context to an open tooling issue without resolving it."""
    try:
        issue = get_db().note_tool_issue(
            issue_id,
            body=body,
            agent_id=agent_id or _get_agent_id(),
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    if issue is None:
        console.print(f"[red]Issue not found: {issue_id}[/red]")
        raise typer.Exit(1)

    if output_json:
        _echo_json(issue)
        return

    console.print(f"[green]Noted issue #{issue['id']}[/green]: {issue['summary']}")


@issue_app.command("resolve")
def resolve_command(
    issue_id: Annotated[int, typer.Argument(help="Issue ID")],
    note: Annotated[str | None, typer.Option("--note", "-n", help="Resolution note")] = None,
    impact: Annotated[
        str | None,
        typer.Option("--impact", help="Outcome tag: matched, retained-source-improvement, negative-evidence, infrastructure-only, diagnostic-only"),
    ] = None,
    agent_id: Annotated[
        str | None,
        typer.Option("--agent-id", help="Resolving agent ID; auto-detected when omitted"),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Mark a reported tooling issue as resolved."""
    try:
        resolution_note = _append_impact_note(note, impact)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    issue = get_db().resolve_tool_issue(
        issue_id,
        agent_id=agent_id or _get_agent_id(),
        resolution_note=resolution_note,
    )
    if issue is None:
        console.print(f"[red]Issue not found: {issue_id}[/red]")
        raise typer.Exit(1)

    if output_json:
        _echo_json(issue)
        return

    console.print(f"[green]Resolved issue #{issue['id']}[/green]: {issue['summary']}")


@issue_app.command("claim")
def claim_command(
    issue_id: Annotated[int, typer.Argument(help="Issue ID")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Take over a claim held by another agent"),
    ] = False,
    agent_id: Annotated[
        str | None,
        typer.Option("--agent-id", help="Claiming agent ID; auto-detected when omitted"),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Claim an open issue so other agents skip it."""
    resolved_agent = agent_id or _get_agent_id()
    try:
        issue = get_db().claim_tool_issue(issue_id, agent_id=resolved_agent, force=force)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    if issue is None:
        console.print(f"[red]Issue not found: {issue_id}[/red]")
        raise typer.Exit(1)

    if output_json:
        _echo_json(issue)
        return

    console.print(
        f"[green]Claimed issue #{issue['id']}[/green] ({issue['claimed_by']}): {issue['summary']}"
    )


@issue_app.command("release")
def release_command(
    issue_id: Annotated[int, typer.Argument(help="Issue ID")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Release a claim held by another agent"),
    ] = False,
    agent_id: Annotated[
        str | None,
        typer.Option("--agent-id", help="Releasing agent ID; auto-detected when omitted"),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Release your claim on an issue without resolving it."""
    resolved_agent = agent_id or _get_agent_id()
    try:
        issue = get_db().release_tool_issue(issue_id, agent_id=resolved_agent, force=force)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    if issue is None:
        console.print(f"[red]Issue not found: {issue_id}[/red]")
        raise typer.Exit(1)

    if output_json:
        _echo_json(issue)
        return

    console.print(f"[green]Released issue #{issue['id']}[/green]: {issue['summary']}")
