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


def test_issue_note_appends_context_without_resolving_from_cli(tmp_path):
    """Agents should be able to annotate an open issue without closing it."""
    reset_db()
    db = StateDB(tmp_path / "state.db")
    issue = db.report_tool_issue(
        "mwcc-debug score-source lacks useful timeout output",
        tool="mwcc-debug",
        body="Initial report.",
    )
    db.close()
    reset_db()
    get_db(tmp_path / "state.db")

    result = runner.invoke(
        app,
        [
            "issue",
            "note",
            str(issue["id"]),
            "--body",
            "Reproduced after refreshing the scratch context.",
            "--agent-id",
            "annotator-agent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "open"
    assert payload["resolution_note"] is None
    assert "Initial report." in payload["body"]
    assert "Note by annotator-agent" in payload["body"]
    assert "Reproduced after refreshing" in payload["body"]

    reset_db()


def test_issue_note_rejects_resolved_issue_from_cli(tmp_path):
    """Notes should be reserved for still-open issue threads."""
    reset_db()
    db = StateDB(tmp_path / "state.db")
    issue = db.report_tool_issue("mwcc-debug score-source lacks useful timeout output")
    db.resolve_tool_issue(issue["id"], agent_id="fixer", resolution_note="fixed")
    db.close()
    reset_db()
    get_db(tmp_path / "state.db")

    result = runner.invoke(
        app,
        [
            "issue",
            "note",
            str(issue["id"]),
            "--body",
            "Follow-up after close.",
        ],
    )

    assert result.exit_code == 2
    assert "cannot note resolved issue" in strip_ansi(result.stdout)

    reset_db()


def test_feature_issue_requires_governance_metadata(tmp_path):
    """Feature requests should carry reuse/source-actionability metadata."""
    reset_db()
    get_db(tmp_path / "state.db")

    result = runner.invoke(
        app,
        [
            "issue",
            "report",
            "mwcc-debug needs a new source search objective",
            "--kind",
            "feature",
            "--tool",
            "mwcc-debug",
        ],
    )

    assert result.exit_code == 2
    assert "Feature issues require governance metadata" in strip_ansi(result.stdout)

    reset_db()


def test_feature_issue_governance_flags_are_normalized_into_body(tmp_path):
    """Dedicated governance flags should be stored as a normalized body section."""
    reset_db()
    db = get_db(tmp_path / "state.db")

    result = runner.invoke(
        app,
        [
            "issue",
            "report",
            "Frame target scorer needed",
            "--kind",
            "feature",
            "--tool",
            "mwcc-debug",
            "--function",
            "gm_801A9DD0",
            "--reusable-class",
            "stack/local unused home reservation",
            "--applies-to",
            "fn_80175A94",
            "--source-actionable-output",
            "ranked frame source transforms and score-source target",
            "--stop-condition",
            "no candidate improves frame score after 50 probes",
            "--existing-workflow-failed",
            "inspect diagnose was register-only and reported no fast transform",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    stored = db.get_tool_issue(payload["id"])
    assert stored is not None
    body = stored["body"]
    assert "Governance:" in body
    assert "Reusable class: stack/local unused home reservation" in body
    assert "Applies to: fn_80175A94" in body
    assert "Source-actionable output: ranked frame source transforms" in body
    assert "Stop condition: no candidate improves frame score after 50 probes" in body
    assert "Existing workflow failed: inspect diagnose was register-only" in body

    reset_db()


def test_feature_issue_governance_body_labels_are_accepted(tmp_path):
    """Structured body labels should satisfy the feature request gate."""
    reset_db()
    db = get_db(tmp_path / "state.db")
    body = "\n".join(
        [
            "Observed during a stuck function campaign.",
            "",
            "Governance:",
            "Reusable class: select-order swaps among interfering callee-saves",
            "Applies to: grGreatBay_801F5460, grIceMt_801F9ACC",
            "Source-actionable output: ranked source transforms with real-tree validation",
            "Stop condition: no retained source improvement after a bounded candidate set",
            "Existing workflow failed: coalesce-search cannot target interfering nodes",
        ]
    )

    result = runner.invoke(
        app,
        [
            "issue",
            "report",
            "select-order search needs source-transform coverage",
            "--kind",
            "feature",
            "--tool",
            "mwcc-debug",
            "--body",
            body,
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    stored = db.get_tool_issue(payload["id"])
    assert stored is not None
    assert stored["body"] == body

    reset_db()


def test_feature_issue_governance_waiver_is_stored(tmp_path):
    """Waived feature requests should remain visible in the stored body."""
    reset_db()
    db = get_db(tmp_path / "state.db")

    result = runner.invoke(
        app,
        [
            "issue",
            "report",
            "exploratory compiler pass trace hook",
            "--kind",
            "feature",
            "--tool",
            "mwcc-debug",
            "--governance-waiver",
            "one-off exploratory issue from active matching session",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    stored = db.get_tool_issue(payload["id"])
    assert stored is not None
    assert "Governance waiver: one-off exploratory issue" in stored["body"]

    reset_db()


def test_feature_like_blocker_warns_but_reports(tmp_path):
    """Blocker reports that look like feature requests should warn, not fail."""
    reset_db()
    db = get_db(tmp_path / "state.db")

    result = runner.invoke(
        app,
        [
            "issue",
            "report",
            "mwcc-debug needs a stack-frame model before this can continue",
            "--kind",
            "blocker",
            "--tool",
            "mwcc-debug",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "looks like a feature request" in strip_ansi(result.stdout)
    stored = db.list_tool_issues(status="open")
    assert len(stored) == 1
    assert stored[0]["kind"] == "blocker"

    reset_db()


def test_issue_resolve_accepts_impact_tag(tmp_path):
    """Resolution impact should be appended to the stored note."""
    reset_db()
    db = StateDB(tmp_path / "state.db")
    issue = db.report_tool_issue("mwcc-debug scorer found no retained source", kind="feature")
    db.close()
    reset_db()
    get_db(tmp_path / "state.db")

    result = runner.invoke(
        app,
        [
            "issue",
            "resolve",
            str(issue["id"]),
            "--note",
            "Ran the bounded search and found no improving candidate.",
            "--impact",
            "negative-evidence",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["resolution_note"].endswith("impact=negative-evidence")

    reset_db()


def test_issue_campaign_report_links_issue_impacts_and_attempt_roi(tmp_path, monkeypatch):
    """Campaign reporting should expose ROI/generalization signals together."""
    reset_db()
    db = StateDB(tmp_path / "state.db")
    retained = db.report_tool_issue(
        "register tiebreak scorer",
        kind="feature",
        tool="mwcc-debug",
        functions=["ftCo_8009E7B4", "fn_80175A94"],
        body="\n".join(
            [
                "Governance:",
                "Reusable class: coupled force-phys tiebreak",
                "Applies to: ftCo_8009E7B4, fn_80175A94, un_803147C4",
                "Source-actionable output: ranked force-phys source edits",
                "Stop condition: retained source win or bounded negative evidence",
                "Existing workflow failed: generic diagnose advice",
            ]
        ),
    )
    negative = db.report_tool_issue(
        "deep probe exhausted one branch",
        kind="feature",
        tool="mwcc-debug",
        functions=["ftCo_8009E7B4"],
    )
    open_gap = db.report_tool_issue(
        "source coverage matrix missing",
        kind="feature",
        tool="mwcc-debug",
        functions=["ftCo_8009E7B4"],
    )
    db.resolve_tool_issue(
        retained["id"],
        agent_id="agent-test",
        resolution_note=(
            "Used on later functions and kept one source edit.\n"
            "impact=retained-source-improvement"
        ),
    )
    db.resolve_tool_issue(
        negative["id"],
        agent_id="agent-test",
        resolution_note="Exhausted bounded search.\nimpact=negative-evidence",
    )
    db.close()
    reset_db()
    get_db(tmp_path / "state.db")

    ledger_path = tmp_path / "attempts.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger_path))
    from src.cli.tracking import record_attempt

    record_attempt(
        "ftCo_8009E7B4",
        match_percent=91.0,
        outcome="improved",
        retained=True,
        note="kept source probe result",
    )
    record_attempt(
        "fn_80175A94",
        match_percent=80.0,
        outcome="blocked",
        classification="register-allocation",
        blocker="same tiebreak family",
    )

    result = runner.invoke(
        app,
        ["issue", "campaign-report", "--function", "ftCo_8009E7B4", "--json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    by_id = {entry["id"]: entry for entry in payload["issues"]}
    assert by_id[retained["id"]]["impact"] == "retained-source-improvement"
    assert by_id[retained["id"]]["recommendation"] == "mature"
    assert by_id[retained["id"]]["retained_source_wins"] == 1
    assert "fn_80175A94" in by_id[retained["id"]]["downstream_functions"]
    assert "un_803147C4" in by_id[retained["id"]]["generality_functions"]
    assert by_id[negative["id"]]["recommendation"] == "stop-or-defer"
    assert by_id[negative["id"]]["negative_evidence"] >= 1
    assert by_id[open_gap["id"]]["recommendation"] == "keep-investing"
    assert payload["summary"]["open_follow_up_gaps"] == 1
    assert payload["summary"]["retained_source_wins"] >= 1

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


def test_failure_report_hint_is_suppressed_for_debug_solve_abstain():
    """Solver exit 3 is an expected abstain, not a reportable tool failure."""
    assert not _should_print_failure_report_hint(
        ["debug", "solve", "coloring", "-f", "mnDiagram_8024227C"],
        exit_code=3,
    )


def test_failure_report_hint_is_suppressed_for_debug_solve_no_candidate():
    """Solver exit 4 is an expected no-candidate result, not a tool failure."""
    assert not _should_print_failure_report_hint(
        ["debug", "solve", "node-set-split", "-f", "mnDiagram2_Create"],
        exit_code=4,
    )


def test_issue_claim_from_cli(tmp_path):
    """claim sets the owner; a second agent conflicts; --force takes over."""
    reset_db()
    db = get_db(tmp_path / "state.db")
    issue = db.report_tool_issue(summary="claimable issue", agent_id="reporter")

    result = runner.invoke(
        app, ["issue", "claim", str(issue["id"]), "--agent-id", "agent-1"]
    )
    assert result.exit_code == 0, result.stdout
    assert "Claimed issue" in strip_ansi(result.stdout)
    assert db.get_tool_issue(issue["id"])["claimed_by"] == "agent-1"

    # Second agent conflicts (exit 2), message names owner and --force.
    result = runner.invoke(
        app, ["issue", "claim", str(issue["id"]), "--agent-id", "agent-2"]
    )
    assert result.exit_code == 2
    out = strip_ansi(result.stdout)
    assert "agent-1" in out
    assert "--force" in out

    # Force takeover succeeds.
    result = runner.invoke(
        app, ["issue", "claim", str(issue["id"]), "--agent-id", "agent-2", "--force"]
    )
    assert result.exit_code == 0, result.stdout
    assert db.get_tool_issue(issue["id"])["claimed_by"] == "agent-2"


def test_issue_claim_missing_issue(tmp_path):
    reset_db()
    get_db(tmp_path / "state.db")
    result = runner.invoke(app, ["issue", "claim", "9999", "--agent-id", "agent-1"])
    assert result.exit_code == 1
    assert "not found" in strip_ansi(result.stdout).lower()


def test_issue_release_from_cli(tmp_path):
    """Owner releases; non-owner needs --force."""
    reset_db()
    db = get_db(tmp_path / "state.db")
    issue = db.report_tool_issue(summary="releasable", agent_id="reporter")
    db.claim_tool_issue(issue["id"], "agent-1")

    # Non-owner without --force fails.
    result = runner.invoke(
        app, ["issue", "release", str(issue["id"]), "--agent-id", "agent-2"]
    )
    assert result.exit_code == 2
    assert "agent-1" in strip_ansi(result.stdout)

    # Owner releases.
    result = runner.invoke(
        app, ["issue", "release", str(issue["id"]), "--agent-id", "agent-1"]
    )
    assert result.exit_code == 0, result.stdout
    assert "Released issue" in strip_ansi(result.stdout)
    assert db.get_tool_issue(issue["id"])["claimed_by"] is None

    # Releasing an unclaimed issue errors.
    result = runner.invoke(
        app, ["issue", "release", str(issue["id"]), "--agent-id", "agent-1"]
    )
    assert result.exit_code == 2
    assert "not claimed" in strip_ansi(result.stdout)


def test_issue_list_claim_column_and_available_filter(tmp_path):
    """list annotates the owner and --available hides claimed-by-others
    identically in --json and table modes."""
    reset_db()
    db = get_db(tmp_path / "state.db")
    claimed = db.report_tool_issue(summary="claimed one", agent_id="r")
    free = db.report_tool_issue(summary="free one", agent_id="r")
    db.claim_tool_issue(claimed["id"], "agent-1")

    # Plain table render works.
    assert runner.invoke(app, ["issue", "list"]).exit_code == 0

    # Default --json shows both and annotates the owner.
    payload = json.loads(runner.invoke(app, ["issue", "list", "--json"]).stdout)
    by_id = {i["id"]: i for i in payload}
    assert by_id[claimed["id"]]["claimed_by"] == "agent-1"
    assert by_id[free["id"]]["claimed_by"] is None

    # --available hides claimed-by-others.
    payload = json.loads(
        runner.invoke(app, ["issue", "list", "--available", "--json"]).stdout
    )
    ids = {i["id"] for i in payload}
    assert free["id"] in ids
    assert claimed["id"] not in ids

    # The --unclaimed alias behaves the same and the table render works.
    assert runner.invoke(app, ["issue", "list", "--unclaimed"]).exit_code == 0


def test_issue_show_displays_claim_owner(tmp_path):
    reset_db()
    db = get_db(tmp_path / "state.db")
    issue = db.report_tool_issue(summary="x", agent_id="r")
    db.claim_tool_issue(issue["id"], "agent-1")

    result = runner.invoke(app, ["issue", "show", str(issue["id"])])
    assert result.exit_code == 0, result.stdout
    out = strip_ansi(result.stdout)
    assert "Claimed by:" in out
    assert "agent-1" in out


def test_issue_show_unclaimed_has_no_claim_line(tmp_path):
    reset_db()
    db = get_db(tmp_path / "state.db")
    issue = db.report_tool_issue(summary="x", agent_id="r")

    result = runner.invoke(app, ["issue", "show", str(issue["id"])])
    assert result.exit_code == 0, result.stdout
    assert "Claimed by:" not in strip_ansi(result.stdout)


def test_note_allowed_on_claimed_issue_by_other_agent(tmp_path):
    """note is not ownership-gated: any agent may annotate a claimed (open)
    issue, and noting does not disturb the claim."""
    reset_db()
    db = get_db(tmp_path / "state.db")
    issue = db.report_tool_issue(summary="x", agent_id="r")
    db.claim_tool_issue(issue["id"], "agent-1")

    result = runner.invoke(
        app,
        [
            "issue",
            "note",
            str(issue["id"]),
            "--body",
            "extra context from a passer-by",
            "--agent-id",
            "agent-2",
        ],
    )
    assert result.exit_code == 0, result.stdout
    updated = db.get_tool_issue(issue["id"])
    assert "extra context from a passer-by" in (updated["body"] or "")
    assert updated["claimed_by"] == "agent-1"
