# Worktree Artifact Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ('- [ ]') syntax for tracking.

**Goal:** Safely report/clean ignored worktree artifacts and reuse validated immutable compiler/tool assets.

**Architecture:** New 'worktree_doctor.artifacts' and 'worktree_doctor.assets' modules isolate deletion and cache policy. The legacy entrypoint dispatches their subcommands without changing '--fix' or '--banner'. PR/WIP creation performs non-fatal asset hydration.

**Tech Stack:** Python 3.11, argparse, pathlib, dataclasses, hashlib, json, shutil, subprocess, pytest, Bash.

## Global Constraints

- Default discovery is only Git-registered worktrees; extra discovery requires repeatable '--scan-root'.
- Candidates are only real direct 'build/' and '.cache/' children.
- Cleanup is dry-run by default, '--apply' revalidates, and it never deletes active, tracked, non-ignored, symlinked, malformed, out-of-root, or user-owned data.
- Defaults are 7 days and 1 GiB.
- Assets are only 'build/compilers/', 'build/tools/', and 'tools/table-typer/table-typer'; never share objects, reports, diagnostics, source, or virtual environments.
- Cache files are copied, SHA-256 validated, atomically published, read-only, and hydrated with file-level symlinks under real target directories.
- Existing worktree-doctor/bootstrap/DOL and PR overlay semantics remain compatible.

---

## Task 1: Safe artifact discovery, inspection, and deletion core

**Files:**
- Create: 'tools/worktree_doctor/artifacts.py'
- Create: 'tools/melee-agent/tests/test_worktree_artifacts.py'

**Interfaces:**
- Produces: 'ArtifactCandidate', 'ArtifactReport', 'CleanupResult', 'discover_worktrees()', 'inspect_artifacts()', 'cleanup_artifacts()'.
- Consumes: repository root, optional scan roots, age/size thresholds, and injectable process data.

- [ ] **Step 1: Write failing behavior tests**

~~~python
def test_default_discovery_only_uses_registered_worktrees(tmp_path: Path) -> None:
    repo, linked = _make_repo_and_linked_worktree(tmp_path)
    unregistered = tmp_path / "unregistered"
    unregistered.mkdir()

    assert artifacts.discover_worktrees(repo) == (repo.resolve(), linked.resolve())
    assert unregistered.resolve() not in artifacts.discover_worktrees(repo)

def test_inspection_rejects_tracked_and_symlinked_build(tmp_path: Path) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x")
    _track_file(linked, "build/keep.txt", "tracked")
    (linked / "build/link").symlink_to(tmp_path / "outside")

    candidate = _candidate(artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[],
    ), linked, "build")
    assert candidate.eligible is False
    assert set(candidate.skip_reasons) >= {"git-tracked", "nested-symlink"}

def test_cleanup_dry_run_then_revalidation_preserves_late_nonignored_file(tmp_path: Path) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x" * 32)
    report = artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[],
    )
    assert artifacts.cleanup_artifacts(report.candidates, apply=False).planned == (linked / "build",)

    (linked / "build/late.txt").write_text("user owned")
    result = artifacts.cleanup_artifacts(report.candidates, apply=True)
    assert result.removed == ()
    assert result.skipped[0].reason == "contains-nonignored"
    assert (linked / "build").exists()
~~~

- [ ] **Step 2: Verify RED**

Run: 'cd tools/melee-agent && pytest tests/test_worktree_artifacts.py -q'

Expected: collection fails because 'worktree_doctor.artifacts' is missing.

- [ ] **Step 3: Implement exact core API**

~~~python
ARTIFACT_DIRS = (Path("build"), Path(".cache"))
DEFAULT_MIN_AGE_DAYS = 7.0
DEFAULT_MIN_BYTES = 1024**3

@dataclass(frozen=True)
class ArtifactCandidate:
    worktree: Path
    root: Path
    kind: str
    size_bytes: int
    newest_mtime: float | None
    eligible: bool
    skip_reasons: tuple[str, ...]

@dataclass(frozen=True)
class ArtifactReport:
    worktrees: tuple[Path, ...]
    candidates: tuple[ArtifactCandidate, ...]

@dataclass(frozen=True)
class CleanupResult:
    planned: tuple[Path, ...]
    removed: tuple[Path, ...]
    reclaimed_bytes: int
    skipped: tuple[CleanupSkip, ...]

def discover_worktrees(repo_root: Path, scan_roots: Sequence[Path] = ()) -> tuple[Path, ...]: ...
def inspect_artifacts(worktrees: Sequence[Path], *, min_age_days: float, min_bytes: int, now: float | None = None, active_commands: Sequence[str] | None = None) -> ArtifactReport: ...
def cleanup_artifacts(candidates: Sequence[ArtifactCandidate], *, apply: bool, active_commands: Sequence[str] | None = None) -> CleanupResult: ...
~~~

Default discovery parses 'git worktree list --porcelain'. A scan root recursively accepts only a directory whose 'git rev-parse --show-toplevel' equals that directory; use lstat and do not follow symlinks. Inspect only direct candidates. Walk with scandir without following links; count regular files and newest mtime. In each worktree, require candidate/root and every regular file to be ignored, reject tracked paths with 'git ls-files --error-unmatch', and fail closed on a Git error. Reject an active command containing the resolved worktree/candidate path. Cleanup recomputes all checks immediately before rmtree.

- [ ] **Step 4: Add active/threshold tests and verify GREEN**

~~~python
def test_active_command_and_thresholds_skip_candidate(tmp_path: Path) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x" * 32)

    active = _candidate(artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=0, now=NOW,
        active_commands=[f"ninja -C {linked} build/GALE01/report.json"],
    ), linked, "build")
    assert active.skip_reasons == ("active-process",)

    small = _candidate(artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=64, now=NOW, active_commands=[],
    ), linked, "build")
    assert small.skip_reasons == ("below-min-bytes",)
~~~

Run: 'cd tools/melee-agent && pytest tests/test_worktree_artifacts.py -q'

Expected: discovery, Git safety, symlink, threshold, dry-run, and revalidation cases pass.

- [ ] **Step 5: Commit**

~~~bash
git add tools/worktree_doctor/artifacts.py tools/melee-agent/tests/test_worktree_artifacts.py
git commit -m "feat: add safe worktree artifact cleanup"
~~~

## Task 2: Artifact CLI with legacy compatibility

**Files:**
- Modify: 'tools/worktree_doctor/__init__.py:114-126'
- Modify: 'tools/worktree-doctor.py'
- Modify: 'tools/melee-agent/tests/test_worktree_artifacts.py'

**Interfaces:**
- Consumes: Task 1 API.
- Produces: 'worktree-doctor artifacts report' and 'artifacts cleanup'.

- [ ] **Step 1: Write failing CLI tests**

~~~python
def test_artifacts_report_json_is_read_only(monkeypatch, capsys) -> None:
    monkeypatch.setattr(artifacts, "discover_worktrees", lambda root, scan_roots=(): (ROOT,))
    monkeypatch.setattr(artifacts, "inspect_artifacts", lambda *args, **kwargs: REPORT)
    assert doctor.main(["artifacts", "report", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "report"

def test_artifacts_cleanup_requires_apply(monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(artifacts, "cleanup_artifacts", lambda candidates, apply: calls.append(apply) or RESULT)
    assert doctor.main(["artifacts", "cleanup"]) == 0
    assert doctor.main(["artifacts", "cleanup", "--apply"]) == 0
    assert calls == [False, True]
~~~

- [ ] **Step 2: Verify RED**

Run: 'cd tools/melee-agent && pytest tests/test_worktree_artifacts.py -q -k artifacts_cli'

Expected: current parser rejects 'artifacts'.

- [ ] **Step 3: Implement dispatch and output**

Make 'worktree_doctor.main(argv: Sequence[str] | None = None)' dispatch exact first token 'artifacts' before the legacy parser. The subcommand grammar is:

~~~
artifacts report [--scan-root PATH ...] [--min-age-days FLOAT] [--min-bytes INT] [--json]
artifacts cleanup [--scan-root PATH ...] [--min-age-days FLOAT] [--min-bytes INT] [--apply] [--json]
~~~

Text output contains worktree, candidate, bytes, age, eligibility, and reasons. JSON includes schema_version, mode, thresholds, candidates, planned, removed, reclaimed_bytes, and skipped. Non-apply cleanup reports mode 'dry-run'. No-subcommand invocation stays unchanged.

- [ ] **Step 4: Verify GREEN and commit**

Run:

~~~bash
cd tools/melee-agent
pytest tests/test_worktree_artifacts.py -q
pytest tests/test_worktree_doctor.py -q
~~~

Then commit:

~~~bash
git add tools/worktree_doctor/__init__.py tools/worktree-doctor.py tools/melee-agent/tests/test_worktree_artifacts.py
git commit -m "feat: expose worktree artifact lifecycle commands"
~~~

## Task 3: Validated immutable asset cache

**Files:**
- Create: 'tools/worktree_doctor/assets.py'
- Modify: 'tools/worktree_doctor/__init__.py'
- Modify: 'tools/melee-agent/tests/test_worktree_artifacts.py'

**Interfaces:**
- Produces: 'AssetResult', 'seed_shared_assets()', 'hydrate_shared_assets()', 'assets seed', and 'assets hydrate'.

- [ ] **Step 1: Write failing asset tests**

~~~python
def test_seed_and_hydrate_uses_file_level_symlinks(tmp_path: Path) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()

    assert assets.seed_shared_assets(source, cache).status == "seeded"
    assert assets.hydrate_shared_assets(target, cache).status == "hydrated"
    consumer = target / "build/compilers/GC/1.2.5n/mwcceppc.exe"
    assert consumer.is_symlink()
    assert consumer.read_bytes() == b"compiler"
    consumer.unlink()
    assert (cache / "files/build/compilers/GC/1.2.5n/mwcceppc.exe").read_bytes() == b"compiler"

def test_hydrate_preserves_real_file_and_rejects_bad_digest(tmp_path: Path) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()
    assets.seed_shared_assets(source, cache)
    existing = target / "build/tools/wibo"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"local")
    assert "build/tools/wibo" in assets.hydrate_shared_assets(target, cache).skipped

    manifest = json.loads((cache / "manifest.json").read_text())
    manifest["files"][0]["sha256"] = "0" * 64
    (cache / "manifest.json").write_text(json.dumps(manifest))
    assert assets.hydrate_shared_assets(target, cache).status == "invalid-cache"
~~~

- [ ] **Step 2: Verify RED**

Run: 'cd tools/melee-agent && pytest tests/test_worktree_artifacts.py -q -k assets'

Expected: collection fails because 'worktree_doctor.assets' is missing.

- [ ] **Step 3: Implement cache API**

~~~python
ASSET_PATHS = (Path("build/compilers"), Path("build/tools"), Path("tools/table-typer/table-typer"))
CACHE_SCHEMA_VERSION = 1

@dataclass(frozen=True)
class AssetResult:
    status: str
    cache_root: Path
    linked: tuple[Path, ...]
    skipped: tuple[str, ...]

def seed_shared_assets(source: Path, cache_root: Path) -> AssetResult: ...
def hydrate_shared_assets(target: Path, cache_root: Path, *, asset_source: Path | None = None) -> AssetResult: ...
~~~

Seed only regular non-symlink files below approved paths. Copy to a sibling staging directory, stream SHA-256, write sorted manifest, chmod files read-only, and atomically publish only after validation. A valid different cache remains 'cache-exists'. Hydration validates platform, relative paths, digests, and cache files before mutation; it builds real parent directories and creates relative file-level symlinks only for absent paths. Preserve real files/mismatched links. A missing cache seeds only when asset_source is supplied, otherwise returns non-fatal 'cache-missing'.

- [ ] **Step 4: Add assets CLI, run GREEN, commit**

Support:

~~~
assets seed --source PATH [--cache-root PATH]
assets hydrate [--asset-source PATH] [--cache-root PATH]
~~~

Run: 'cd tools/melee-agent && pytest tests/test_worktree_artifacts.py -q'

Then:

~~~bash
git add tools/worktree_doctor/assets.py tools/worktree_doctor/__init__.py tools/melee-agent/tests/test_worktree_artifacts.py
git commit -m "feat: share immutable worktree assets"
~~~

## Task 4: Hydrate new worktrees, document, verify, resolve #1204

**Files:**
- Modify: 'tools/workflow/pr-worktree.sh:255-261'
- Modify: 'tools/melee-agent/tests/test_pr_worktree.py'
- Create: 'docs/worktree-artifact-lifecycle.md'

- [ ] **Step 1: Write failing workflow test**

~~~python
def test_pr_worktree_create_hydrates_assets_from_main_checkout(tmp_path: Path) -> None:
    repo = _make_pr_worktree_fixture(tmp_path)
    (repo / "tools/worktree-doctor.py").write_text(
        "import pathlib, sys\npathlib.Path.cwd().joinpath('asset-source.txt').write_text(sys.argv[-1])\n"
    )
    result = subprocess.run(["bash", "tools/workflow/pr-worktree.sh", "create", "pr/demo"], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "melee-pr/asset-source.txt").read_text() == str(repo)
~~~

- [ ] **Step 2: Verify RED and integrate**

Run: 'cd tools/melee-agent && pytest tests/test_pr_worktree.py -q -k hydrates_assets'

Expected: marker is absent.

After 'ensure_base_dol' in 'cmd_create', add:

~~~bash
if python tools/worktree-doctor.py assets hydrate --asset-source "$REPO_ROOT"; then
    echo "Shared immutable assets checked."
else
    echo "Warning: shared asset hydration skipped; worktree remains usable."
fi
~~~

Do not fail creation when cache/source is absent or hydrate errors.

- [ ] **Step 3: Document, verify, commit, resolve**

Document discovery scope, candidate policy, dry-run/apply, active-process protection, cache contents, and non-fatal hydration. Run:

~~~bash
cd tools/melee-agent
pytest tests/test_worktree_artifacts.py -q
pytest tests/test_worktree_doctor.py -q
pytest tests/test_pr_worktree.py -q
cd ../..
python tools/worktree-doctor.py artifacts report --json
python tools/worktree-doctor.py artifacts cleanup --min-age-days 7 --min-bytes 1073741824 --json
python tools/worktree-doctor.py assets hydrate --asset-source "$(pwd)"
git diff --check
~~~

Then:

~~~bash
git add tools/workflow/pr-worktree.sh tools/melee-agent/tests/test_pr_worktree.py docs/worktree-artifact-lifecycle.md
git commit -m "feat: hydrate shared worktree assets"
DECOMP_AGENT_ID=issue-queue-root melee-agent issue resolve 1204 --note "Added safe registered-worktree artifact report/cleanup with explicit apply and active/tracked/symlink guards, plus validated file-level immutable asset cache hydration for new worktrees."
~~~

Verify #1204 remains claimed by 'issue-queue-root' immediately before resolving.
