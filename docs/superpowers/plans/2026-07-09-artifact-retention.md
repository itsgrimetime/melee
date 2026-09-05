# Diagnostic Artifact Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ('- [ ]') syntax for tracking.

**Goal:** Preserve source-actionable diagnostic evidence in safe, bounded, ignored run bundles while deleting only disposable compiler and probe products.

**Architecture:** A new 'mwcc_debug.artifacts' module owns bundle creation, manifest finalization, reporting, and retention pruning. A small 'debug artifacts' CLI adapts that module to operators. 'debug target score-source' becomes the first producer: it writes source and score data to the bundle and moves retained pcdumps there, while preserving explicit legacy pcdump destinations.

**Tech Stack:** Python 3.11, pathlib, dataclasses, json, Typer, pytest.

## Global Constraints

- Retain candidate source, score/status payloads, manifests, provenance, and explicitly retained pcdumps as one evidence bundle.
- Only remove 'transient/' inside a manifest-owned run or whole terminal run directories below the configured artifact root.
- Never prune active/incomplete, malformed, symlinked, out-of-root, tracked, or user-owned paths.
- The default artifact root is 'build/diagnostics/runs'; default completed-run retention is 30 days and 10 GiB.
- 'build/mwcc_debug_cache' remains a separate source-hash-aware baseline cache and is report-only in this implementation.
- Keep score-source's existing '--pcdump-output' behavior byte-for-byte compatible when the option is supplied.

---

## File Structure

- 'tools/melee-agent/src/mwcc_debug/artifacts.py' — safe run-bundle primitives, manifest schema, reporting, and prune planning/execution.
- 'tools/melee-agent/src/cli/debug/artifacts.py' — Typer 'debug artifacts report' and 'debug artifacts prune' commands.
- 'tools/melee-agent/src/cli/debug/__init__.py' — registers the new command group.
- 'tools/melee-agent/src/cli/debug/target.py' — integrates score-source with the shared artifact bundle without changing its scoring algorithm.
- 'tools/melee-agent/tests/test_mwcc_debug_artifacts.py' — lifecycle, retention, and filesystem-safety regression tests.
- 'tools/melee-agent/tests/test_debug_cli_reorg.py' — command-group and score-source integration coverage.
- 'docs/mwcc-debug-permuter-integration.md' — operator-facing retention workflow.

## Task 1: Create the safe artifact-lifecycle core

**Files:**
- Create: 'tools/melee-agent/src/mwcc_debug/artifacts.py'
- Test: 'tools/melee-agent/tests/test_mwcc_debug_artifacts.py'

**Interfaces:**
- Consumes: a Melee root, optional artifact root, command/provenance mappings, and owned evidence/transient files.
- Produces: 'ArtifactRun', 'ArtifactReport', 'PrunePlan', 'create_run()', 'report_runs()', and 'prune_runs()'.

- [ ] **Step 1: Write the failing lifecycle tests**

~~~python
from datetime import datetime, timedelta, timezone

from src.mwcc_debug.artifacts import ArtifactRun, create_run

def test_completed_run_keeps_evidence_and_removes_transient(tmp_path: Path) -> None:
    run = create_run(tmp_path, command=["debug", "target", "score-source"])
    source = run.retain_text("source/candidate.c", "void fn(void) {}\n")
    transient = run.transient_path("compiler/discard.o")
    transient.parent.mkdir(parents=True)
    transient.write_bytes(b"object")

    manifest = run.finalize("completed", result={"score": 0})

    assert source.read_text() == "void fn(void) {}\n"
    assert not run.transient_dir.exists()
    assert manifest["state"] == "completed"
    assert manifest["evidence"]["source/candidate.c"] == len(source.read_bytes())

def test_failed_run_retains_existing_pcdump_and_score(tmp_path: Path) -> None:
    run = create_run(tmp_path, command=["debug", "target", "score-source"])
    run.retain_text("pcdump/candidate.txt", "Starting function fn\n")
    run.retain_json("score.json", {"score": 1 << 30, "error": "pcdump missing"})

    run.finalize("failed")

    assert (run.evidence_dir / "pcdump/candidate.txt").exists()
    assert json.loads((run.evidence_dir / "score.json").read_text())["error"] == "pcdump missing"
~~~

- [ ] **Step 2: Run the tests to verify RED**

Run: 'cd tools/melee-agent && pytest tests/test_mwcc_debug_artifacts.py -q'

Expected: collection fails with 'ModuleNotFoundError: No module named src.mwcc_debug.artifacts'.

- [ ] **Step 3: Implement the manifest-owned run API**

Create the module with this public contract:

~~~python
DEFAULT_ARTIFACT_ROOT = Path("build/diagnostics/runs")
DEFAULT_MAX_AGE_DAYS = 30.0
DEFAULT_MAX_TOTAL_BYTES = 10 * 1024**3
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})

@dataclass(frozen=True)
class ArtifactRun:
    root: Path
    run_dir: Path
    evidence_dir: Path
    transient_dir: Path
    manifest_path: Path

    def retain_text(self, relative: str, text: str) -> Path: ...
    def retain_json(self, relative: str, payload: Mapping[str, Any]) -> Path: ...
    def retain_file(self, source: Path, relative: str) -> Path: ...
    def transient_path(self, relative: str) -> Path: ...
    def finalize(self, state: str, *, result: Mapping[str, Any] | None = None) -> dict[str, Any]: ...

def create_run(
    melee_root: Path,
    *,
    command: Sequence[str],
    artifact_root: Path | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> ArtifactRun: ...
~~~

Use a UTC timestamp plus 'uuid4().hex' for a direct-child run directory. Resolve a relative root from 'melee_root' and reject any root resolving outside it. Write an 'active' manifest atomically before writing evidence. Validate every requested child path: it cannot be absolute, contain '..', traverse a symlink, or resolve outside its evidence/transient owner. 'finalize()' validates terminal state, computes evidence sizes from actual files below 'evidence_dir', removes only 'transient_dir', and atomically replaces the manifest with terminal state, timestamps, result, evidence byte map, and reclaimed transient bytes.

- [ ] **Step 4: Run the lifecycle tests to verify GREEN**

Run: 'cd tools/melee-agent && pytest tests/test_mwcc_debug_artifacts.py -q'

Expected: both lifecycle tests pass.

- [ ] **Step 5: Add failing report/prune safety tests**

~~~python
from src.mwcc_debug.artifacts import prune_runs, report_runs

def _completed_run(root: Path, name: str, *, age_days: int = 0, evidence_bytes: int = 0) -> ArtifactRun:
    run = create_run(root, command=["test", name])
    run.retain_text("source/candidate.c", "x" * evidence_bytes)
    run.finalize("completed")
    manifest = json.loads(run.manifest_path.read_text())
    manifest["finished_at"] = (
        datetime.now(timezone.utc) - timedelta(days=age_days)
    ).isoformat()
    run.manifest_path.write_text(json.dumps(manifest))
    return run

def test_report_and_dry_run_leave_completed_runs_intact(tmp_path: Path) -> None:
    old = _completed_run(tmp_path, "old", age_days=31, evidence_bytes=8)

    report = report_runs(tmp_path)
    plan = prune_runs(tmp_path, max_age_days=30, max_total_bytes=1024, apply=False)

    assert report.completed_runs == 1
    assert plan.removed_run_dirs == ()
    assert plan.planned_run_dirs == (old.run_dir,)
    assert old.run_dir.exists()

def test_prune_removes_whole_oldest_terminal_bundle_only(tmp_path: Path) -> None:
    oldest = _completed_run(tmp_path, "oldest", age_days=1, evidence_bytes=8)
    newest = _completed_run(tmp_path, "newest", age_days=0, evidence_bytes=8)

    plan = prune_runs(tmp_path, max_age_days=100, max_total_bytes=8, apply=True)

    assert plan.removed_run_dirs == (oldest.run_dir,)
    assert not oldest.run_dir.exists()
    assert newest.run_dir.exists()

def test_prune_skips_active_malformed_and_symlinked_entries(tmp_path: Path) -> None:
    active = create_run(tmp_path, command=["debug"])
    malformed = tmp_path / "build/diagnostics/runs/not-a-run"
    malformed.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "build/diagnostics/runs/linked").symlink_to(outside)

    plan = prune_runs(tmp_path, max_age_days=0, max_total_bytes=0, apply=True)

    assert active.run_dir.exists()
    assert malformed.exists()
    assert outside.exists()
    assert {item.reason for item in plan.skipped} >= {"active", "missing-manifest", "symlink"}
~~~

- [ ] **Step 6: Run the safety tests to verify RED**

Run: 'cd tools/melee-agent && pytest tests/test_mwcc_debug_artifacts.py -q'

Expected: failures identify missing 'report_runs' and 'prune_runs'.

- [ ] **Step 7: Implement report and pruning from filesystem facts**

Add:

~~~python
@dataclass(frozen=True)
class RunSummary:
    run_dir: Path
    state: str
    created_at: str
    finished_at: str | None
    evidence_bytes: int

@dataclass(frozen=True)
class SkippedRun:
    path: Path
    reason: str

@dataclass(frozen=True)
class ArtifactReport:
    artifact_root: Path
    completed_runs: int
    active_runs: int
    completed_bytes: int
    cache_bytes: int
    runs: tuple[RunSummary, ...]
    skipped: tuple[SkippedRun, ...]

@dataclass(frozen=True)
class PrunePlan:
    planned_run_dirs: tuple[Path, ...]
    removed_run_dirs: tuple[Path, ...]
    reclaimed_bytes: int
    skipped: tuple[SkippedRun, ...]
~~~

'report_runs()' scans direct children only, uses 'lstat()' before reading any manifest, accepts only regular 'manifest.json' files, and calculates size without following symlinks. It separately measures 'build/mwcc_debug_cache' for observability.

'prune_runs()' first selects terminal bundles older than 'max_age_days', then selects oldest remaining terminal bundles until completed evidence is at or below 'max_total_bytes'. In preview mode it populates only 'planned_run_dirs'. With 'apply=True', call a validated '_remove_owned_run_dir()' that rechecks direct-child ownership and non-symlink status immediately before 'shutil.rmtree()'.

- [ ] **Step 8: Run all lifecycle tests to verify GREEN**

Run: 'cd tools/melee-agent && pytest tests/test_mwcc_debug_artifacts.py -q'

Expected: all lifecycle and safety tests pass.

- [ ] **Step 9: Commit the lifecycle core**

~~~bash
git add tools/melee-agent/src/mwcc_debug/artifacts.py tools/melee-agent/tests/test_mwcc_debug_artifacts.py
git commit -m "feat: add diagnostic artifact lifecycle"
~~~

## Task 2: Add read-only reporting and explicit-prune CLI commands

**Files:**
- Create: 'tools/melee-agent/src/cli/debug/artifacts.py'
- Modify: 'tools/melee-agent/src/cli/debug/__init__.py:474-503'
- Modify: 'tools/melee-agent/tests/test_debug_cli_reorg.py:143-222'
- Modify: 'tools/melee-agent/tests/golden/debug_cli_help/debug.txt' only if its snapshot changes

**Interfaces:**
- Consumes: 'report_runs()' and 'prune_runs()' from Task 1.
- Produces: 'melee-agent debug artifacts report' and 'melee-agent debug artifacts prune'.

- [ ] **Step 1: Write failing CLI tests**

~~~python
from datetime import datetime, timedelta, timezone
from src.mwcc_debug.artifacts import ArtifactRun, create_run

def _make_cli_completed_run(root: Path, *, age_days: int = 0, evidence_bytes: int = 0) -> ArtifactRun:
    run = create_run(root, command=["test", "cli"])
    run.retain_text("source/candidate.c", "x" * evidence_bytes)
    run.finalize("completed")
    manifest = json.loads(run.manifest_path.read_text())
    manifest["finished_at"] = (
        datetime.now(timezone.utc) - timedelta(days=age_days)
    ).isoformat()
    run.manifest_path.write_text(json.dumps(manifest))
    return run

def test_debug_artifacts_report_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    _make_cli_completed_run(tmp_path, evidence_bytes=12)

    result = runner.invoke(app, ["debug", "artifacts", "report", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["completed_runs"] == 1
    assert payload["completed_bytes"] == 12

def test_debug_artifacts_prune_requires_apply(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    run = _make_cli_completed_run(tmp_path, age_days=31, evidence_bytes=12)

    preview = runner.invoke(app, ["debug", "artifacts", "prune", "--max-age-days", "30"])
    assert preview.exit_code == 0, preview.output
    assert run.run_dir.exists()

    applied = runner.invoke(app, ["debug", "artifacts", "prune", "--max-age-days", "30", "--apply"])
    assert applied.exit_code == 0, applied.output
    assert not run.run_dir.exists()
~~~

- [ ] **Step 2: Run the tests to verify RED**

Run: 'cd tools/melee-agent && pytest tests/test_debug_cli_reorg.py -q -k artifacts'

Expected: Typer reports 'No such command artifacts'.

- [ ] **Step 3: Implement the command group and registration**

Create:

~~~python
artifacts_app = typer.Typer(
    help="Inspect and safely prune retained diagnostic evidence."
)

@artifacts_app.command("report")
def artifacts_report(
    artifact_root: Path | None = typer.Option(None, "--artifact-root"),
    json_out: bool = typer.Option(False, "--json"),
) -> None: ...

@artifacts_app.command("prune")
def artifacts_prune(
    artifact_root: Path | None = typer.Option(None, "--artifact-root"),
    max_age_days: float = typer.Option(DEFAULT_MAX_AGE_DAYS, min=0),
    max_total_bytes: int = typer.Option(DEFAULT_MAX_TOTAL_BYTES, min=0),
    apply: bool = typer.Option(False, "--apply"),
    json_out: bool = typer.Option(False, "--json"),
) -> None: ...
~~~

Resolve the root from 'DEFAULT_MELEE_ROOT' at command time. 'prune' calls 'prune_runs(..., apply=apply)', labels non-'--apply' output 'dry-run', and returns planned/removed paths plus skipped reasons in JSON. Import 'artifacts_app' in 'cli/debug/__init__.py' and call 'debug_app.add_typer(_artifacts_app, name="artifacts")' beside the other groups. Update only the affected help fixture if its test shows a diff.

- [ ] **Step 4: Run CLI tests and help checks to verify GREEN**

Run: 'cd tools/melee-agent && pytest tests/test_debug_cli_reorg.py -q -k "artifacts or representative_grouped_command_help"'

Expected: report is read-only, pruning deletes only after '--apply', and help includes 'artifacts'.

- [ ] **Step 5: Commit the CLI surface**

~~~bash
git add tools/melee-agent/src/cli/debug/artifacts.py tools/melee-agent/src/cli/debug/__init__.py tools/melee-agent/tests/test_debug_cli_reorg.py tools/melee-agent/tests/golden/debug_cli_help/debug.txt
git commit -m "feat: add diagnostic artifact reporting"
~~~

## Task 3: Make score-source produce self-contained evidence bundles

**Files:**
- Modify: 'tools/melee-agent/src/cli/debug/target.py:2577-3353'
- Modify: 'tools/melee-agent/tests/test_debug_cli_reorg.py:7840-9530'

**Interfaces:**
- Consumes: 'ArtifactRun' and 'create_run()' from Task 1.
- Produces: score-source JSON fields 'artifact_run', 'artifact_manifest', 'artifact_source', and 'artifact_score'; retained default pcdumps live beneath the bundle.

- [ ] **Step 1: Write failing score-source integration tests**

~~~python
def _score_source_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    melee_root = tmp_path / "melee"
    candidate = melee_root / "src/melee/mn/sample.c"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("void fn_80000000(void) {}\n")
    compiler_dir = tmp_path / "compiler"
    compiler_dir.mkdir()
    (compiler_dir / "mwcceppc_debug.exe").write_text("")
    wibo = tmp_path / "wibo"
    wibo.write_text("")
    baseline = tmp_path / "baseline.pcdump.txt"
    baseline.write_text(
        _score_source_force_phys_pcdump_text(
            "fn_80000000", assigned_by_ig={53: 5}
        )
    )
    target = tmp_path / "force_phys_target.yaml"
    target.write_text(textwrap.dedent(f"""\
        function: fn_80000000
        class_id: 0
        baseline_dump: {baseline}
        force_phys:
          53: 4
    """))
    return melee_root, candidate, compiler_dir, wibo, target

def _stub_score_source_compiler(monkeypatch, *, pcdump: str, compiler_dir: Path, wibo: Path) -> None:
    def fake_process_tree_runner(cmd, *, cwd, timeout, env=None):
        (cwd / env["MWCC_DEBUG_PCDUMP_PATH"]).write_text(pcdump)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(debug_cli, "_resolve_src_relative", lambda _path: "src/melee/mn/sample.c")
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda _unit: ("-proc gekko", "mwcc"))
    monkeypatch.setattr(debug_cli, "_score_source_unsafe_lane_payload", lambda **_kwargs: None)
    monkeypatch.setattr(debug_cli, "_run_with_process_group_timeout", fake_process_tree_runner, raising=False)

def test_score_source_retains_source_score_and_pcdump_in_one_bundle(monkeypatch, tmp_path: Path) -> None:
    melee_root, candidate, compiler_dir, wibo, target = _score_source_fixture(tmp_path)
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    _stub_score_source_compiler(
        monkeypatch,
        compiler_dir=compiler_dir,
        wibo=wibo,
        pcdump=_score_source_force_phys_pcdump_text("fn_80000000", assigned_by_ig={53: 4}),
    )

    result = runner.invoke(app, [
        "debug", "target", "score-source", str(candidate.relative_to(melee_root)),
        "-f", "fn_80000000", "--target", str(target), "--json", "--retain-pcdump",
    ])

    payload = json.loads(result.output)
    run_dir = Path(payload["artifact_run"])
    assert (run_dir / "evidence/source/candidate.c").read_text() == candidate.read_text()
    assert (run_dir / "evidence/score.json").is_file()
    assert Path(payload["pcdump_path"]).is_relative_to(run_dir / "evidence")
    assert not (run_dir / "transient").exists()

def test_score_source_preserves_explicit_pcdump_output(monkeypatch, tmp_path: Path) -> None:
    melee_root, candidate, compiler_dir, wibo, target = _score_source_fixture(tmp_path)
    explicit = melee_root / "user-evidence" / "candidate.pcdump.txt"
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    _stub_score_source_compiler(
        monkeypatch,
        compiler_dir=compiler_dir,
        wibo=wibo,
        pcdump=_score_source_force_phys_pcdump_text("fn_80000000", assigned_by_ig={53: 4}),
    )

    result = runner.invoke(app, [
        "debug", "target", "score-source", str(candidate.relative_to(melee_root)),
        "-f", "fn_80000000", "--target", str(target), "--json", "--pcdump-output", str(explicit),
    ])

    assert Path(json.loads(result.output)["pcdump_path"]) == explicit
    assert "Starting function fn_80000000" in explicit.read_text()
~~~

Add a compiler-failure test that asserts the error payload, source copy, and terminal 'failed' manifest remain while 'transient/' is absent.

- [ ] **Step 2: Run the tests to verify RED**

Run: 'cd tools/melee-agent && pytest tests/test_debug_cli_reorg.py -q -k score_source_retains_source_score_and_pcdump'

Expected: current JSON has no 'artifact_run' and the old default retained pcdump is beside the source.

- [ ] **Step 3: Refactor score-source to finalize one bundle for every terminal payload**

After resolving 'melee_root', 'src_rel', and 'cflags_unit_rel', create:

~~~python
artifact_run = create_run(
    melee_root,
    command=["debug", "target", "score-source"],
    provenance={
        "function": function,
        "source": str(src_rel),
        "cflags_from": str(cflags_unit_rel),
        "remote_requested": remote,
    },
)
candidate_path = melee_root / src_rel
if candidate_path.is_file():
    artifact_run.retain_file(candidate_path, "source/candidate.c")
~~~

Introduce local '_emit_score_source_result(payload, *, state)'. It must retain 'payload' to 'evidence/score.json', finalize the run, add 'artifact_run', 'artifact_manifest', 'artifact_source', and 'artifact_score' before JSON serialization, and leave quiet integer stdout unchanged. Route every current JSON payload branch through it: unsafe local lane, remote failure, missing pcdump, missing function, force-phys, target score, and checkdiff result. Score-bearing payloads are 'completed'; compile/remote/missing-pcdump payloads are 'failed'. Setup errors that currently exit 2 finalize 'failed' with a minimal error payload before exit.

When '--pcdump-output' is given, keep the existing destination and returned 'pcdump_path'. When '--retain-pcdump' is set without an explicit output, write 'evidence/pcdump/candidate.txt' and return that path. Without either option do not persist pcdump text. Continue deleting the unique root-level temporary pcdump and discard object immediately after reading them.

- [ ] **Step 4: Run focused score-source tests to verify GREEN**

Run: 'cd tools/melee-agent && pytest tests/test_debug_cli_reorg.py -q -k "score_source_retains_source_score_and_pcdump or score_source_preserves_explicit_pcdump_output or score_source.*timeout or score_source.*remote"'

Expected: bundles are self-contained, explicit output is unchanged, and existing timeout/remote behavior remains green.

- [ ] **Step 5: Run the complete score-source regression subset**

Run: 'cd tools/melee-agent && pytest tests/test_debug_cli_reorg.py -q -k score_source'

Expected: all score-source safety, timeout, local, remote, target-score, and checkdiff tests pass.

- [ ] **Step 6: Commit score-source integration**

~~~bash
git add tools/melee-agent/src/cli/debug/target.py tools/melee-agent/tests/test_debug_cli_reorg.py
git commit -m "feat: retain score-source evidence bundles"
~~~

## Task 4: Verify the feature, document the workflow, and resolve the root cause

**Files:**
- Modify: 'docs/mwcc-debug-permuter-integration.md'
- Test: 'tools/melee-agent/tests/test_mwcc_debug_artifacts.py'
- Test: 'tools/melee-agent/tests/test_debug_cli_reorg.py'

**Interfaces:**
- Consumes: the lifecycle core, CLI, and score-source producer from Tasks 1–3.
- Produces: an operator-facing retention workflow and evidence-backed issue resolution notes.

- [ ] **Step 1: Document the operational workflow**

Add these exact commands and constraints to 'docs/mwcc-debug-permuter-integration.md':

~~~text
melee-agent debug artifacts report
melee-agent debug artifacts prune --max-age-days 30 --max-total-bytes 10737418240
melee-agent debug artifacts prune --max-age-days 30 --max-total-bytes 10737418240 --apply
~~~

Document that score-source stores source and score payloads in 'build/diagnostics/runs/<run-id>/evidence', retains pcdumps there only when '--retain-pcdump' is requested, report is read-only, prune is a preview until '--apply', active/incomplete bundles are never deleted, and 'mwcc_debug_cache' is report-only.

- [ ] **Step 2: Run feature-level verification**

Run:

~~~bash
cd tools/melee-agent
pytest tests/test_mwcc_debug_artifacts.py -q
pytest tests/test_debug_cli_reorg.py -q -k "artifacts or score_source or representative_grouped_command_help"
python -m src.cli debug artifacts report --json
python -m src.cli debug artifacts prune --max-age-days 30 --max-total-bytes 10737418240 --json
~~~

Expected: all tests pass; report/prune exit 0; prune reports a dry-run plan and deletes nothing without '--apply'.

- [ ] **Step 3: Run formatting and diff checks**

Run:

~~~bash
cd /Users/mike/code/melee/.claude/worktrees/codex-artifact-lifecycle
git diff --check HEAD~3..HEAD
python -m compileall -q tools/melee-agent/src/mwcc_debug/artifacts.py tools/melee-agent/src/cli/debug/artifacts.py
git status --short
~~~

Expected: no whitespace errors, Python compilation succeeds, and status lists only the intended documentation change before staging.

- [ ] **Step 4: Commit documentation and resolve grouped issues**

~~~bash
git add docs/mwcc-debug-permuter-integration.md
git commit -m "docs: describe diagnostic artifact retention"
DECOMP_AGENT_ID=issue-queue-root melee-agent issue resolve 1205 --note "Implemented bounded manifest-owned evidence bundles, report/prune CLI, and score-source retention; #1206 is covered by the shared lifecycle root cause."
DECOMP_AGENT_ID=issue-queue-root melee-agent issue resolve 1206 --note "Grouped with #1205: triage has no direct deletion path; bounded manifest-owned diagnostics prevent unsafe cleanup from erasing active evidence."
~~~

Do not resolve #1204 here: its worktree-wide audit, active-job exclusions, and shared immutable toolchain assets are explicitly outside this per-run feature.
