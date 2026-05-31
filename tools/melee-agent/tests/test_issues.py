"""Tests for agent-reported tool issues."""

import json
import re
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from src.cli import _build_failure_report_command, _should_print_failure_report_hint, app
from src.db import StateDB, get_db, reset_db

runner = CliRunner()
AGENT_ROOT = Path(__file__).parent.parent


def strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text for reliable string matching."""
    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_escape.sub("", text)


def test_issue_report_json_records_detected_context(tmp_path, monkeypatch):
    """The report command should store issue context and emit JSON."""
    reset_db()
    db = get_db(tmp_path / "state.db")
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-cli-test")

    result = runner.invoke(
        app,
        [
            "issue",
            "report",
            "mwcc-debug local dump hangs before AFTER REGISTER COLORING",
            "--tool",
            "mwcc-debug",
            "--kind",
            "bug",
            "--body",
            "Command timed out while working on the allocator cascade.",
            "--function",
            "fn_80247510",
            "--function",
            "mnVibration_80248644",
            "--agent-id",
            "agent-cli-test",
            "--worktree",
            "/tmp/melee-tooling",
            "--branch",
            "codex/tool-issues",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["id"] == 1
    assert payload["status"] == "open"
    assert payload["functions"] == ["fn_80247510", "mnVibration_80248644"]
    assert payload["session_id"] == "thread-cli-test"

    stored = db.get_tool_issue(payload["id"])
    assert stored is not None
    assert stored["tool"] == "mwcc-debug"
    assert stored["agent_id"] == "agent-cli-test"

    db.close()
    reset_db()


def test_plural_issues_alias_routes_to_report_help():
    """The documented plural alias should route to the issue reporter."""
    result = runner.invoke(app, ["issues", "report", "--help"])

    assert result.exit_code == 0, result.stdout
    assert "Report a tooling issue" in strip_ansi(result.stdout)


def test_usage_errors_do_not_suggest_recursive_issue_report():
    """Typer usage errors should not print recursive tool-failure hints."""
    proc = subprocess.run(
        [sys.executable, "-m", "src.cli", "issue", "report"],
        cwd=AGENT_ROOT,
        capture_output=True,
        text=True,
    )
    combined = strip_ansi(proc.stdout + proc.stderr)

    assert proc.returncode == 2
    assert "Missing argument" in combined
    assert "To report this tooling failure for follow-up" not in combined


def test_issue_list_and_resolve_work_from_cli(tmp_path):
    """Agents should be able to list and resolve reported issues."""
    reset_db()
    db = StateDB(tmp_path / "state.db")
    first = db.report_tool_issue("mwcc-debug score-source lacks useful timeout output", tool="mwcc-debug")
    db.report_tool_issue("opseq should suggest broader opcode windows", tool="opseq", kind="feature")
    db.close()
    reset_db()
    get_db(tmp_path / "state.db")

    list_result = runner.invoke(app, ["issue", "list", "--tool", "mwcc-debug", "--json"])

    assert list_result.exit_code == 0, list_result.stdout
    listed = json.loads(list_result.stdout)
    assert [issue["id"] for issue in listed] == [first["id"]]

    resolve_result = runner.invoke(
        app,
        [
            "issue",
            "resolve",
            str(first["id"]),
            "--note",
            "Added bounded timeout output and tests.",
            "--agent-id",
            "fixer-agent",
            "--json",
        ],
    )

    assert resolve_result.exit_code == 0, resolve_result.stdout
    resolved = json.loads(resolve_result.stdout)
    assert resolved["status"] == "resolved"
    assert resolved["resolved_by_agent"] == "fixer-agent"

    open_result = runner.invoke(app, ["issue", "list", "--status", "open", "--tool", "mwcc-debug", "--json"])
    assert open_result.exit_code == 0, open_result.stdout
    assert json.loads(open_result.stdout) == []

    reset_db()


def test_issue_show_reports_missing_issue(tmp_path):
    """Showing a missing issue should fail with a useful message."""
    reset_db()
    get_db(tmp_path / "state.db")

    result = runner.invoke(app, ["issue", "show", "9999"])

    assert result.exit_code == 1
    assert "Issue not found: 9999" in strip_ansi(result.stdout)

    reset_db()


def test_failure_report_command_quotes_command_and_error():
    """The failure hint should produce a copyable issue-report command."""
    command = _build_failure_report_command(
        argv=["debug", "dump", "local", "src/melee/mn/foo.c"],
        exit_code=124,
        error="timed out after 120s",
    )

    assert command.startswith("melee-agent issue report ")
    assert "--tool melee-agent" in command
    assert "--kind bug" in command
    assert "--body " in command
    assert "debug dump local src/melee/mn/foo.c" in command
    assert "timed out after 120s" in command


def test_failure_report_hint_is_suppressed_for_json_mode_errors():
    """Machine-readable commands should not get human hint text on failure."""
    assert not _should_print_failure_report_hint(
        [
            "debug",
            "permute",
            "verify",
            "nonmatchings/fn/output/source.c",
            "-f",
            "fn_80000000",
            "--json",
        ],
        exit_code=7,
    )
