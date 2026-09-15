"""`melee-agent backtest` — replay historical match commits and score the tooling."""
from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Annotated, Optional

import typer

backtest_app = typer.Typer(
    help="Backtest the matching tooling against historical single-function match commits.",
    no_args_is_help=True,
)


@backtest_app.command("discover")
def discover_cmd(
    limit: Annotated[int, typer.Option("--limit")] = 20,
    max_lines: Annotated[int, typer.Option("--max-lines")] = 60,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Scan master for single-function match commits (cheap, no builds)."""
    from src.backtest.discover import discover_match_commits
    from src.backtest.corpus import default_git_runner
    from src.backtest.paths import main_repo_root
    triples = discover_match_commits(default_git_runner(str(main_repo_root())), limit=limit, max_lines=max_lines)
    if json_out:
        typer.echo(_json.dumps(triples))
    else:
        for t in triples:
            typer.echo(f"{t['shape']:11} {t['function']} {t['c_sha'][:9]} {t['file']}")


@backtest_app.command("build-corpus")
def build_corpus_cmd(
    functions_file: Annotated[Optional[Path], typer.Option("--functions-file", help="One function name per line.")] = None,
    from_commits: Annotated[bool, typer.Option("--from-commits", help="Discover commits automatically (no functions file).")] = False,
    limit: Annotated[int, typer.Option("--limit")] = 0,
    max_lines: Annotated[int, typer.Option("--max-lines")] = 60,
    db: Annotated[Optional[Path], typer.Option("--db")] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Enumerate verified small/singular match commits into the backtest store."""
    if from_commits:
        from src.backtest.run import build_and_store_corpus_from_commits
        summary = build_and_store_corpus_from_commits(limit=limit, max_lines=max_lines, db=db)
    elif functions_file is not None:
        from src.backtest.run import build_and_store_corpus  # Task 1.7
        summary = build_and_store_corpus(functions_file=functions_file, limit=limit, db=db)
    else:
        raise typer.BadParameter("Either --functions-file or --from-commits is required.")
    typer.echo(_json.dumps(summary) if json_out else f"corpus: {summary['stored']} cases")


@backtest_app.command("run")
def run_cmd(
    cheap: Annotated[bool, typer.Option("--cheap", help="Run advisory+generative tiers.")] = True,
    limit: Annotated[int, typer.Option("--limit")] = 0,
    db: Annotated[Optional[Path], typer.Option("--db")] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run the cheap tiers over the stored corpus. (Judge + blind-agent run via the Workflow.)"""
    from src.backtest.run import cheap_tiers_with_real_judge  # thin wrapper; see implementer note
    summary = cheap_tiers_with_real_judge(limit=limit, db=db)
    typer.echo(_json.dumps(summary) if json_out else str(summary))


@backtest_app.command("status")
def status_cmd(
    json_out: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Report harness readiness."""
    payload = {"harness": "backtest", "ready": True}
    if json_out:
        typer.echo(_json.dumps(payload))
        return
    typer.echo("backtest harness ready")


_CASE_FIELDS = (
    "function", "c_sha", "cprev_sha", "unit", "file", "ground_truth_diff",
    "lever_locus", "author", "provenance", "lever_class", "baseline_pct",
    "baseline_ndl", "target_pct", "target_ndl",
)


def _case_from_row(row: dict):
    """Reconstruct a Case dataclass from a stored case row."""
    from src.backtest.types import Case

    return Case(**{k: row[k] for k in _CASE_FIELDS})


@backtest_app.command("judge-input")
def judge_input_cmd(
    case_id: str,
    db: Annotated[Optional[Path], typer.Option("--db")] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Print the label-blinded judge input (function, ground_truth_diff, lever_class,
    tool_outputs) the LLM advisory judge consumes for a case. Sourced from the store."""
    from src.backtest.store import BacktestStore
    from src.backtest import judge

    store = BacktestStore(db)
    store.ensure_schema()
    case_row = store.get_case(case_id)
    if case_row is None:
        raise typer.BadParameter(f"case_id {case_id!r} not found in store", param_hint="CASE_ID")
    result = store.get_result(case_id)
    if result is None:
        raise typer.BadParameter(
            f"case_id {case_id!r} has no result row yet (run `backtest run --cheap` first)",
            param_hint="CASE_ID",
        )
    raw_evidence = result.get("evidence") or "{}"
    evidence = _json.loads(raw_evidence) if isinstance(raw_evidence, str) else raw_evidence
    case_obj = _case_from_row(case_row)
    payload = judge.build_judge_input(case_obj, evidence.get("advisory", {}))
    typer.echo(_json.dumps(payload))


@backtest_app.command("pending-judge")
def pending_judge_cmd(
    db: Annotated[Optional[Path], typer.Option("--db")] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Print the JSON list of case_ids that have a result row (ready for judging)."""
    from src.backtest.store import BacktestStore

    store = BacktestStore(db)
    store.ensure_schema()
    case_ids = [r["case_id"] for r in store.results()]
    typer.echo(_json.dumps(case_ids))


@backtest_app.command("calibrate")
def calibrate_cmd(
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run the Phase-0 two-sided calibration gate and exit non-zero if it fails.

    This gate validates the advisory keyword-judge + rollup logic + the
    negative-control non-leak on the shipped synthetic fixtures. It does NOT run
    the real generative tooling (there is no build behind synthetic fixtures) — it
    uses a known-answer generative oracle. The generative tier and full-pipeline
    blindness are validated separately by the slow sandbox integration test
    (`BACKTEST_SLOW=1`).
    """
    from src.backtest.fixtures import load_calibration_fixtures
    from src.backtest.calibrate import calibrate
    from src.backtest.judge import keyword_advisory_verdict

    fixtures = load_calibration_fixtures()

    def score_advisory(f: dict) -> str:
        # Exercise the REAL keyword-judge logic on a synthesized advisory bundle:
        #  - positive: a tool's stdout = the fixture's ground_truth_diff (so the
        #    identifier-overlap check fires -> "names-lever").
        #  - negative: an empty bundle (nothing references the lever -> "silent-or-wrong").
        if f["kind"] == "positive":
            bundle = {"synthetic_tool": {"rc": 0, "stdout": f["ground_truth_diff"]}}
        else:
            bundle = {}
        return keyword_advisory_verdict(f["ground_truth_diff"], bundle)

    def score_generative(f: dict) -> str:
        return "byte-match-reproduced" if f["kind"] == "positive" else "no-progress"

    result = calibrate(fixtures, score_advisory=score_advisory, score_generative=score_generative)
    typer.echo(_json.dumps(result))
    if not result["passed"]:
        raise typer.Exit(1)


@backtest_app.command("escalation")
def escalation_cmd(
    db: Annotated[Optional[Path], typer.Option("--db")] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List case IDs that should be escalated to the blind-agent tier."""
    from src.backtest.store import BacktestStore
    from src.backtest.score import select_escalation

    store = BacktestStore(db)
    store.ensure_schema()
    results = store.results()
    cases_by_id = {c["case_id"]: c for c in store.list_cases()}
    ids = select_escalation(results, cases_by_id)
    if json_out:
        typer.echo(_json.dumps(ids))
    else:
        for cid in ids:
            typer.echo(cid)


@backtest_app.command("set-advisory")
def set_advisory_cmd(
    case_id: str,
    verdict: str,
    db: Annotated[Optional[Path], typer.Option("--db")] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Record the LLM advisory-judge verdict for a case."""
    from src.backtest.store import BacktestStore
    from src.backtest.score import rollup_verdict
    from src.backtest.types import CaseResult

    valid = {"names-lever", "hints-adjacent", "silent-or-wrong"}
    if verdict not in valid:
        raise typer.BadParameter(
            f"verdict must be one of {sorted(valid)}, got {verdict!r}",
            param_hint="VERDICT",
        )

    store = BacktestStore(db)
    store.ensure_schema()
    existing = store.get_result(case_id)
    if existing is None:
        generative = None
        agent = None
        evidence: dict = {}
    else:
        generative = existing.get("generative")
        agent = existing.get("agent")
        raw_evidence = existing.get("evidence") or "{}"
        if isinstance(raw_evidence, str):
            import json as _j
            evidence = _j.loads(raw_evidence)
        else:
            evidence = raw_evidence

    rollup = rollup_verdict(verdict, generative, agent)
    new_result = CaseResult(
        case_id=case_id,
        advisory=verdict,
        generative=generative,
        agent=agent,
        rollup=rollup,
        evidence=evidence,
    )
    store.upsert_result(new_result)
    typer.echo(_json.dumps({"rollup": rollup}) if json_out else rollup)


@backtest_app.command("set-agent")
def set_agent_cmd(
    case_id: str,
    verdict: str,
    db: Annotated[Optional[Path], typer.Option("--db")] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Record the blind-agent outcome verdict for a case."""
    from src.backtest.store import BacktestStore
    from src.backtest.score import rollup_verdict
    from src.backtest.types import CaseResult

    valid = {"matched", "improved", "stuck"}
    if verdict not in valid:
        raise typer.BadParameter(
            f"verdict must be one of {sorted(valid)}, got {verdict!r}",
            param_hint="VERDICT",
        )

    store = BacktestStore(db)
    store.ensure_schema()
    existing = store.get_result(case_id)
    if existing is None:
        advisory = None
        generative = None
        evidence: dict = {}
    else:
        advisory = existing.get("advisory")
        generative = existing.get("generative")
        raw_evidence = existing.get("evidence") or "{}"
        if isinstance(raw_evidence, str):
            import json as _j
            evidence = _j.loads(raw_evidence)
        else:
            evidence = raw_evidence

    rollup = rollup_verdict(advisory, generative, verdict)
    new_result = CaseResult(
        case_id=case_id,
        advisory=advisory,
        generative=generative,
        agent=verdict,
        rollup=rollup,
        evidence=evidence,
    )
    store.upsert_result(new_result)
    typer.echo(_json.dumps({"rollup": rollup}) if json_out else rollup)


@backtest_app.command("open-sandbox")
def open_sandbox_cmd(
    case_id: str,
    db: Annotated[Optional[Path], typer.Option("--db")] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Build an isolated sandbox worktree for a blind matching attempt."""
    import subprocess
    import sys as _sys

    from src.backtest.store import BacktestStore
    from src.backtest.sandbox import build_sandbox
    from src.backtest.run import MAIN_REPO

    store = BacktestStore(db)
    store.ensure_schema()
    case = store.get_case(case_id)
    if case is None:
        raise typer.BadParameter(f"case_id {case_id!r} not found in store", param_hint="CASE_ID")

    dest = Path(MAIN_REPO) / "build" / "backtest" / "sandboxes" / case_id
    build_sandbox(
        main_repo=MAIN_REPO,
        c_sha=case["c_sha"],
        cprev_sha=case["cprev_sha"],
        dest=dest,
    )
    proc = subprocess.run(
        [_sys.executable, "tools/worktree-doctor.py", "--fix"],
        cwd=str(dest),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        typer.echo(
            f"worktree-doctor --fix failed in sandbox {dest} "
            f"(rc={proc.returncode}): {(proc.stderr or proc.stdout).strip()}",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo(_json.dumps({"sandbox": str(dest), "function": case["function"]}))


@backtest_app.command("report")
def report_cmd(
    db: Annotated[Optional[Path], typer.Option("--db")] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
    emit_issues: Annotated[bool, typer.Option("--emit-issues")] = False,
) -> None:
    """Print the coverage matrix. With --emit-issues, stage gap proposals and file issues."""
    import subprocess
    import sys as _sys

    from src.backtest.store import BacktestStore
    from src.backtest.report import coverage_matrix, render_report

    store = BacktestStore(db)
    store.ensure_schema()
    cases = store.list_cases()
    results = store.results()
    matrix = coverage_matrix(cases, results)

    if json_out:
        typer.echo(_json.dumps(matrix))
    else:
        typer.echo(render_report(matrix))

    if emit_issues:
        from src.backtest.feedback import stage_gap, issue_report_argv
        from src.backtest.run import MAIN_REPO

        staging_dir = Path(MAIN_REPO) / "build" / "backtest" / "staged"
        results_by_id = {r["case_id"]: r for r in results}
        for case in cases:
            r = results_by_id.get(case["case_id"])
            if r is None or r.get("rollup") != "GAP":
                continue
            stage_gap(case, staging_dir=staging_dir)
            if case.get("lever_class") != "backend_coloring":
                argv = issue_report_argv(case)
                proc = subprocess.run(
                    [_sys.executable, "-m", "src.cli"] + argv,
                    cwd=str(MAIN_REPO),
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    typer.echo(
                        f"warning: `issue report` failed for {case['function']} "
                        f"(case {case['case_id']}, rc={proc.returncode}): "
                        f"{(proc.stderr or proc.stdout).strip()}",
                        err=True,
                    )


@backtest_app.command("close-sandbox")
def close_sandbox_cmd(
    case_id: str,
    db: Annotated[Optional[Path], typer.Option("--db")] = None,
) -> None:
    """Tear down the sandbox worktree for a case."""
    from src.backtest.sandbox import teardown_sandbox
    from src.backtest.run import MAIN_REPO

    dest = Path(MAIN_REPO) / "build" / "backtest" / "sandboxes" / case_id
    teardown_sandbox(dest)
    typer.echo(f"sandbox {case_id} closed")
