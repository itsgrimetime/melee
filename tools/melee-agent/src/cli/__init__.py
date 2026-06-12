"""
CLI interface for the Melee Decomp Agent tooling.

This package provides a modular CLI structure with separate modules for each
command group: extract, scratch, commit, docker, sync, pr, audit, hook, struct,
stub, state, analytics, setup, and mismatch.

Usage:
    python -m src.cli <command>
    melee-agent <command>
"""

import os
import shlex
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (gitignored, contains local config like DECOMP_API_BASE)
load_dotenv(Path(__file__).parent.parent.parent / ".env")

import typer

from ..mismatch_db.cli import mismatch_app
from ..mwcc_debug.diff_capture import _run_with_process_group_timeout

# Import common utilities for backward compatibility
from ._common import (
    DEFAULT_MELEE_ROOT,
    console,
)
from .analytics import analytics_app
from .audit import audit_app
from .commit import commit_app
from .compilers import list_compilers
from .debug import _acquire_checkdiff_repo_lock, debug_app
from .docker import docker_app

# Import sub-apps from modules
from .extract import extract_app
from .ghidra import ghidra_app
from .harvest import harvest_cmd
from .hook import hook_app
from .issue import issue_app
from .patterns import patterns_app
from .pr import pr_app
from .scratch import scratch_app
from .setup import setup_app
from .state import state_app
from .struct import struct_app
from .stub import stub_app
from .sync import sync_app
from .tracking import attempts_app
from .layout import layout_app
from .capabilities import capabilities_app


class ReportingTyper(typer.Typer):
    """Typer app that prints a tool-issue report command on failures."""

    def __call__(self, *args, **kwargs):
        try:
            return super().__call__(*args, **kwargs)
        except SystemExit as e:
            if _should_print_failure_report_hint(sys.argv[1:], exit_code=e.code):
                _print_failure_report_hint(sys.argv[1:], exit_code=e.code)
            raise
        except Exception as e:
            if _should_print_failure_report_hint(sys.argv[1:], error=repr(e)):
                _print_failure_report_hint(sys.argv[1:], error=repr(e))
            raise


# Create main app
app = ReportingTyper(
    name="melee-agent",
    help="Agent tooling for contributing to the Melee decompilation project",
)

# Register sub-apps
app.add_typer(extract_app, name="extract")
app.add_typer(scratch_app, name="scratch")
app.add_typer(commit_app, name="commit")
app.add_typer(debug_app, name="debug")
app.add_typer(docker_app, name="docker")
app.add_typer(sync_app, name="sync")
app.add_typer(pr_app, name="pr")
app.add_typer(audit_app, name="audit")
app.add_typer(hook_app, name="hook")
app.add_typer(issue_app, name="issue")
app.add_typer(issue_app, name="issues", hidden=True)
app.add_typer(struct_app, name="struct")
app.add_typer(stub_app, name="stub")
app.add_typer(state_app, name="state")
app.add_typer(analytics_app, name="analytics")
app.add_typer(attempts_app, name="attempts")
app.add_typer(setup_app, name="setup")
app.add_typer(mismatch_app, name="mismatch")
app.add_typer(ghidra_app, name="ghidra")
app.add_typer(patterns_app, name="patterns")
app.add_typer(layout_app, name="layout")
app.add_typer(capabilities_app, name="capabilities")

# Register standalone commands


@app.command(
    "opseq",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="Alias for tools/table-typer opseq opcode-sequence search.",
)
def opseq(ctx: typer.Context) -> None:
    """Run the table-typer opcode sequence matcher from melee-agent."""
    args = list(ctx.args)
    table_typer_dir = DEFAULT_MELEE_ROOT / "tools" / "table-typer"
    if not table_typer_dir.exists():
        typer.echo(
            "opseq requires tools/table-typer. From a full melee checkout, run:\n"
            "  cd tools/table-typer && go run . opseq <comma,separated,opcodes>",
            err=True,
        )
        raise typer.Exit(2)

    binary = table_typer_dir / "table-typer"
    if binary.exists():
        cmd = [str(binary), "opseq", *args]
    else:
        cmd = ["go", "run", ".", "opseq", *args]

    timeout = _opseq_timeout_seconds()
    try:
        with _acquire_checkdiff_repo_lock(DEFAULT_MELEE_ROOT, label="opseq build/report"):
            proc = _run_with_process_group_timeout(
                cmd,
                cwd=table_typer_dir,
                timeout=timeout,
            )
    except FileNotFoundError as exc:
        typer.echo(f"opseq helper could not start: {exc}", err=True)
        typer.echo(
            "Try: cd tools/table-typer && go run . opseq <comma,separated,opcodes>",
            err=True,
        )
        raise typer.Exit(127)
    except subprocess.TimeoutExpired:
        typer.echo(
            f"opseq timed out after {timeout:g}s while running: "
            f"{shlex.join(cmd)}",
            err=True,
        )
        raise typer.Exit(124)

    _forward_subprocess_output(proc)
    if proc.returncode != 0:
        raise typer.Exit(proc.returncode)


def _opseq_timeout_seconds() -> int:
    raw = os.environ.get("MELEE_AGENT_OPSEQ_TIMEOUT", "120")
    try:
        timeout = int(float(raw))
    except ValueError:
        return 120
    return max(timeout, 1)


def _forward_subprocess_output(proc: subprocess.CompletedProcess[str]) -> None:
    if proc.stdout:
        typer.echo(proc.stdout, nl=False)
    if proc.stderr:
        typer.echo(proc.stderr, err=True, nl=False)


app.command("compilers")(list_compilers)
app.command(
    "harvest",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(harvest_cmd)


def _build_failure_report_command(
    argv: list[str],
    exit_code: int | str | None = None,
    error: str | None = None,
) -> str:
    """Build a copyable command for reporting a failed melee-agent run."""
    command = " ".join(argv) if argv else "<no arguments>"
    summary = f"melee-agent command failed: {command}"
    if len(summary) > 180:
        summary = summary[:177] + "..."

    body_lines = [f"Command: melee-agent {command}"]
    if exit_code is not None:
        body_lines.append(f"Exit code: {exit_code}")
    if error:
        body_lines.append(f"Error: {error}")
    body = "\n".join(body_lines)

    parts = [
        "melee-agent",
        "issue",
        "report",
        summary,
        "--tool",
        "melee-agent",
        "--kind",
        "bug",
        "--body",
        body,
    ]
    return " ".join(shlex.quote(part) for part in parts)


def _should_print_failure_report_hint(
    argv: list[str],
    exit_code: int | str | None = None,
    error: str | None = None,
) -> bool:
    """Return whether a failed invocation should show an issue-report hint."""
    if exit_code in (0, None) and error is None:
        return False
    if exit_code == 2:
        return False
    if argv and argv[0] in {"issue", "issues"}:
        return False
    if any(arg == "--json" or arg.startswith("--json=") for arg in argv):
        return False
    return True


def _print_failure_report_hint(
    argv: list[str],
    exit_code: int | str | None = None,
    error: str | None = None,
) -> None:
    """Print an agent-facing issue-report hint for CLI failures."""
    report_command = _build_failure_report_command(argv=argv, exit_code=exit_code, error=error)
    typer.echo("", err=True)
    typer.echo("To report this tooling failure for follow-up, run:", err=True)
    typer.echo(f"  {report_command}", err=True)


def main():
    """Entry point for the CLI."""
    if os.environ.get("CLAUDE_CODE_REMOTE", "").lower() == "true":
        console.print(
            "[yellow]Warning:[/yellow] melee-agent commands are not supported in remote environments.\n"
            "The decomp.me server and related services are only accessible from local machines.",
            style="yellow",
        )
        raise SystemExit(1)
    app()


if __name__ == "__main__":
    main()
