# Conservative Worktree Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add report, dry-run, and explicit-apply commands that retire only clean, idle, inactive agent worktrees while preserving branches, retained evidence, shared assets, and every unknown ignored file.

**Architecture:** A new `worktree_doctor.worktrees` module owns strict Git record parsing, immutable inspection records, eligibility, and locked retirement. Existing asset validation gains a read-only consumer API. The legacy wrapper dispatches the new command and serializes one versioned result model for human and JSON output.

**Tech Stack:** Python 3.11, stdlib `argparse`, `dataclasses`, `fcntl`, `os`/descriptor-relative filesystem APIs, `selectors`, `subprocess`, Git 2.39 porcelain, pytest.

## Global Constraints

- Default minimum idle time is exactly 24 hours; negative or non-finite values are rejected.
- Discovery uses only strict `git worktree list --porcelain -z`; malformed or unknown records fail closed globally.
- Retirement never uses `--force`, `rm -rf`, branch deletion, ref mutation, or `git worktree prune`.
- Dirty, detached, active, locked, prunable, primary/current, PR, WIP, outside-agent-root, unknown, or changed worktrees are never removed.
- Ignored files are disposable only when they match the approved typed allowlist; retained evidence, logs, dumps, real assets, environments, and agent runtime files block retirement.
- Retained diagnostic evidence remains governed by its 30-day/10-GiB artifact lifecycle.
- Process commands are bounded to 15 seconds, 8 MiB stdout, 1 MiB stderr, and 200,000 records; failure or overflow fails closed.
- Apply takes a common-Git-dir advisory lock, performs a complete preflight, and revalidates every candidate immediately before normal Git removal.
- Every disk-byte field is explicitly estimated block usage.

---

### Task 1: Strict registered-worktree parsing and policy classification

**Files:**
- Create: `tools/worktree_doctor/worktrees.py`
- Create: `tools/melee-agent/tests/test_worktree_retirement.py`

**Interfaces:**
- Produces: `RegisteredWorktree`, `WorktreeParseError`, `repository_object_hex_length(repo_root: Path) -> int`, and `parse_worktree_porcelain(data: bytes, *, object_hex_length: int) -> tuple[RegisteredWorktree, ...]`.
- Produces: `discover_registered_worktrees(repo_root: Path) -> tuple[RegisteredWorktree, ...]` and `policy_skip_reasons(record, *, main_worktree, current_worktree, agent_roots) -> tuple[str, ...]`.
- Later tasks consume these exact immutable records; path bytes decode with `os.fsdecode`/`surrogateescape` and round-trip through `os.fsencode`.

- [ ] **Step 1: Write parser failure tests before production code**

Add table-driven tests whose payloads include a branch record, detached/locked/prunable records, paths containing a literal newline, Unicode, and undecodable filesystem bytes, and each malformed case: unknown field, duplicate field, missing HEAD, invalid OID, branch plus detached, relative path, duplicate canonical path, missing double-NUL record terminator, and trailing data. Mock `git rev-parse --show-object-format` for `sha1` and `sha256`; reject a 64-digit OID in a SHA-1 repo, a 40-digit OID in a SHA-256 repo, and any unknown object format.

```python
def record(path: bytes, head: bytes = b"a" * 40, branch: bytes = b"codex/test") -> bytes:
    return b"worktree " + path + b"\0HEAD " + head + b"\0branch refs/heads/" + branch + b"\0\0"

def test_parse_worktree_porcelain_preserves_newline_path(tmp_path: Path) -> None:
    path = os.fsencode(tmp_path / "line\nbreak")
    parsed = worktrees.parse_worktree_porcelain(record(path), object_hex_length=40)
    assert parsed[0].path == Path(os.fsdecode(path))
    assert parsed[0].branch == "codex/test"

@pytest.mark.parametrize("payload", [
    b"worktree /tmp/x\0HEAD " + b"a" * 40 + b"\0future x\0branch refs/heads/codex/x\0\0",
    b"worktree relative\0HEAD " + b"a" * 40 + b"\0branch refs/heads/codex/x\0\0",
    b"worktree /tmp/x\0HEAD " + b"a" * 40 + b"\0branch refs/heads/codex/x\0",
])
def test_parse_worktree_porcelain_rejects_malformed(payload: bytes) -> None:
    with pytest.raises(worktrees.WorktreeParseError):
        worktrees.parse_worktree_porcelain(payload, object_hex_length=40)
```

- [ ] **Step 2: Run the focused tests and confirm the red state**

Run: `python -m pytest tools/melee-agent/tests/test_worktree_retirement.py -q`

Expected: collection fails because `worktree_doctor.worktrees` does not exist.

- [ ] **Step 3: Implement strict parsing and immutable records**

Create frozen dataclasses with exact fields:

```python
@dataclass(frozen=True)
class RegisteredWorktree:
    path: Path
    head: str
    branch: str | None
    detached: bool
    locked_reason: str | None
    prunable_reason: str | None

class WorktreeParseError(ValueError):
    pass
```

Split only on NUL, require a final empty-record field, accept only `worktree`, `HEAD`, `branch`, `detached`, `locked`, and `prunable`, validate singleton counts against the repository's one exact object format, and reject duplicate canonical paths. `repository_object_hex_length` runs `git -C <repo> rev-parse --show-object-format` and maps only `sha1` to 40 and `sha256` to 64. `discover_registered_worktrees` must run exactly `git -C <repo> worktree list --porcelain -z`, require zero exit, and pass stdout bytes plus that exact length to the parser.

- [ ] **Step 4: Add policy classification tests and implementation**

Cover main/current paths, detached, locked, prunable, `pr/*`, `wip/*`, `melee-pr`/`pr-*` path components, unrecognized branches, outside roots, and eligible `codex/*`, `claude/*`, and `wall/*`. Assert PR/WIP reasons win before generic branch rejection.

```python
assert policy_skip_reasons(pr_record, ...) == ("protected-pr-branch",)
assert policy_skip_reasons(wip_record, ...) == ("protected-wip-branch",)
assert policy_skip_reasons(codex_record, ...) == ()
```

- [ ] **Step 5: Run task tests and commit**

Run: `python -m pytest tools/melee-agent/tests/test_worktree_retirement.py -q`

Expected: all Task 1 tests pass.

```bash
git add tools/worktree_doctor/worktrees.py tools/melee-agent/tests/test_worktree_retirement.py
git commit -m "feat: classify registered agent worktrees"
```

---

### Task 2: Fail-closed inspection, ignored inventory, retained evidence, assets, and processes

**Files:**
- Modify: `tools/worktree_doctor/worktrees.py`
- Create: `tools/worktree_doctor/retained_evidence.py`
- Modify: `tools/worktree_doctor/assets.py`
- Modify: `tools/worktree_doctor/__init__.py` (export the new asset validator only)
- Modify: `tools/melee-agent/tests/test_worktree_retirement.py`
- Modify: `tools/melee-agent/tests/test_worktree_artifacts.py`

**Interfaces:**
- Consumes: `RegisteredWorktree` and policy helpers from Task 1.
- Produces: `IgnoredEntry`, `ProcessSnapshot`, `WorktreeRecord`, `WorktreeReport`, and `inspect_worktrees(repo_root: Path, *, current_worktree: Path, min_idle_hours: float, now: float | None = None, process_snapshot: ProcessSnapshot | None = None) -> WorktreeReport`.
- Produces in `assets.py`: frozen `HydratedAssetLink(relative: Path, link_device: int, link_inode: int, link_text: str, target_device: int, target_inode: int)` and `HydratedAssetSnapshot(cache_root: Path, cache_identity: tuple[int, int], manifest_identity: tuple[int, int], links: tuple[HydratedAssetLink, ...])`, plus `inspect_hydrated_assets(target: Path, cache_root: Path) -> tuple[HydratedAssetSnapshot | None, tuple[str, ...]]`; it must reuse the existing sealed-cache manifest and link identity checks, not trust pathname text.
- Produces in `retained_evidence.py`: `RetainedEvidenceSnapshot(roots: tuple[Path, ...], manifests: tuple[tuple[Path, int, int, int, float], ...])` and `discover_retained_evidence(worktree: Path, ignored: Sequence[IgnoredEntry]) -> tuple[RetainedEvidenceSnapshot, tuple[str, ...]]`. It recognizes exact artifact-format manifests and derives custom roots from validated run layout; no external registry is assumed.

- [ ] **Step 1: Write tree/activity and Git-cleanliness tests**

Use temporary real Git repositories/worktrees. Set mtimes explicitly and assert that an old HEAD commit never makes a newly created worktree old; fresh source/build/admin activity resets idle age; staged, unstaged, untracked, and submodule changes yield `dirty-worktree`; ignored rebuildable files do not. Assert the walk sums `st_blocks * 512`, never follows symlinks, and fails on scan errors/future timestamps.

- [ ] **Step 2: Write ignored-inventory and retained-evidence tests**

Monkeypatch the Git runner with strict NUL payloads, then cover unterminated/empty/absolute/traversing/duplicate/overflow entries. Test every allowlisted class and denial precedence. Required assertions include:

```python
assert "contains-unapproved-ignored" in inspect_with_ignored(".env").skip_reasons
assert "contains-unapproved-ignored" in inspect_with_ignored("build/crash.dump").skip_reasons
assert "retained-evidence-present" in inspect_with_ignored(
    "build/diagnostics/runs/<valid-run>/manifest.json"
).skip_reasons
```

Build retained-run fixtures using `src.mwcc_debug.artifacts.create_run` at both the default root and `artifact_root=Path("build/custom-evidence")`; call `run.finalize("completed")` before pruning. Verify manifest discovery returns each run directory's parent as its protected root, inspection blocks before `prune_runs(..., artifact_root=<same root>, max_age_days=0, max_total_bytes=0, apply=True)`, and can become eligible afterward. A malformed manifest-like ignored file must remain `contains-unapproved-ignored` rather than disappearing from protection.

- [ ] **Step 3: Write shared-asset and DOL identity tests**

Use existing asset seed/hydrate helpers. Assert real container directories plus expected symlink leaves pass, while a real file, extra leaf, dangling/replaced link, or wrong cache target yields `asset-validation-failed`. Bind cache-root, manifest, and every target/link identity into `HydratedAssetSnapshot`; coherently replace the cache directory and manifest between plan/apply and assert revalidation rejects it even when path text and file contents match. Assert `orig/GALE01/sys/main.dol` passes only as an identity-checked symlink to a `DOL_CANDIDATES` file and blocks as a copied real file.

- [ ] **Step 4: Write bounded process-snapshot tests**

Inject a fake `Popen` factory and cover `lsof` cwd/open paths, non-absolute socket/device names, `ps` argv references, self-PID exclusion, malformed records, timeout, nonzero exit, 8-MiB/1-MiB byte overflow, and 200,000-record overflow. Expected failures are global `process-query-failed` or `process-query-overflow`, never an empty snapshot.

- [ ] **Step 5: Run tests to verify the inspection layer is red**

Run: `python -m pytest tools/melee-agent/tests/test_worktree_retirement.py tools/melee-agent/tests/test_worktree_artifacts.py -q`

Expected: new inspection/validation tests fail because the APIs are absent.

- [ ] **Step 6: Implement one descriptor-bound inspection pipeline**

Add frozen records with exact public fields from the design JSON. Implement:

```python
def inspect_worktrees(... ) -> WorktreeReport:
    registered = discover_registered_worktrees(repo_root)
    snapshot = process_snapshot or collect_process_snapshot()
    return WorktreeReport(
        repo_root=repo_root,
        common_git_dir=common_git_dir(repo_root),
        current_worktree=current_worktree,
        min_idle_hours=min_idle_hours,
        records=tuple(_inspect_one(item, snapshot=snapshot, ...) for item in registered),
        global_errors=snapshot.errors,
    )
```

Inventory ignored files with exactly `git ls-files --others -i --exclude-standard -z --`, enforce 32 MiB/500,000 entries, and bind sorted `(relative, kind, device, inode, size, mtime)` tuples into `WorktreeRecord`. Walk via directory descriptors/no-follow operations. Use `retained_evidence.discover_retained_evidence` to protect default and custom manifest-owned roots before generic `build/**`; malformed classifier state fails closed. Bind the full public asset snapshot and independently bind the DOL target identity. Use an incremental bounded subprocess reader for `lsof` and `ps`; do not use unbounded `capture_output=True`.

- [ ] **Step 7: Run inspection tests and commit**

Run: `python -m pytest tools/melee-agent/tests/test_worktree_retirement.py tools/melee-agent/tests/test_worktree_artifacts.py -q`

Expected: all Task 1–2 and existing artifact tests pass.

```bash
git add tools/worktree_doctor/worktrees.py tools/worktree_doctor/retained_evidence.py tools/worktree_doctor/assets.py tools/worktree_doctor/__init__.py tools/melee-agent/tests/test_worktree_retirement.py tools/melee-agent/tests/test_worktree_artifacts.py
git commit -m "feat: inspect worktree retirement safety"
```

---

### Task 3: Locked retirement with complete preflight and per-candidate revalidation

**Files:**
- Modify: `tools/worktree_doctor/worktrees.py`
- Modify: `tools/melee-agent/tests/test_worktree_retirement.py`

**Interfaces:**
- Consumes: `WorktreeReport` and bound inspection identities from Task 2.
- Produces: `RetirementCandidate`, `RetirementSkip`, `RetirementRemoval`, `RetirementResult`, and `retire_worktrees(report: WorktreeReport, *, apply: bool) -> RetirementResult`.

- [ ] **Step 1: Write dry-run and lock tests**

Assert dry-run returns eligible candidates in canonical-path order and executes no mutation. Hold `.git/worktree-doctor-retirement.lock` from the test and assert apply returns a global preflight failure with no remove command. Assert malformed porcelain/process failure during preflight also prevents every removal.

- [ ] **Step 2: Write revalidation race tests**

Parameterize a mutation injected between planning and removal: dirty file, active process, lock flag, detach, unregister, HEAD change, branch change, branch-ref mismatch, inode replacement, newer mtime, disk/inventory change, new retained evidence, new unknown ignored file, asset-link replacement, and process/porcelain global failure. Each candidate must be skipped with the stable design reason; no force flag may appear.

- [ ] **Step 3: Write real integration removal and partial-failure tests**

Create an old, clean linked `codex/*` worktree with only approved ignored outputs. Apply retirement and assert:

```python
assert not worktree_path.exists()
assert git(repo, "show-ref", "--verify", f"refs/heads/{branch}").returncode == 0
assert git(repo, "rev-parse", branch).stdout.strip() == original_head
```

With two candidates, inject a global process failure only after the first removal. Assert the first removal is reported, remaining candidates are unattempted, the top-level error is present, and the eventual CLI status maps to 2.

In a separate two-candidate test, make the first candidate fail only its local revalidation and keep the second valid. Assert the first is recorded in `skipped`, the second is removed, and no top-level global error stops the plan.

- [ ] **Step 4: Run tests and confirm the red state**

Run: `python -m pytest tools/melee-agent/tests/test_worktree_retirement.py -q`

Expected: retirement tests fail because `retire_worktrees` is absent.

- [ ] **Step 5: Implement lock, preflight, revalidation, normal removal, and verification**

Use nonblocking `fcntl.flock` on the common Git directory. In apply mode, acquire the lock and perform a fresh full report before the first mutation. Reinspect each candidate and require equality of path device/inode, HEAD/branch/ref, activity, estimated bytes, ignored inventory, retained roots, and asset identities. Invoke only:

```python
subprocess.run(
    ["git", "-C", os.fspath(report.repo_root), "worktree", "remove", "--", os.fspath(candidate.path)],
    ...,
)
```

Then strictly rediscover worktrees, require the path absent, and require the branch ref still points to the original HEAD. Stop on late global failures; continue only after per-candidate failures as specified by the design.

- [ ] **Step 6: Add negative command assertions and run tests**

Assert collected subprocess arguments never contain `--force`, `branch -d`, `branch -D`, `update-ref`, or `worktree prune`, and monkeypatch `shutil.rmtree` to raise if called.

Run: `python -m pytest tools/melee-agent/tests/test_worktree_retirement.py -q`

Expected: all Task 1–3 tests pass.

- [ ] **Step 7: Commit**

```bash
git add tools/worktree_doctor/worktrees.py tools/melee-agent/tests/test_worktree_retirement.py
git commit -m "feat: safely retire idle agent worktrees"
```

---

### Task 4: CLI, schema-versioned output, compatibility documentation, and live verification

**Files:**
- Modify: `tools/worktree_doctor/__init__.py`
- Modify: `tools/worktree-doctor.py` only if legacy re-export tests require the new module binding
- Modify: `tools/workflow/cleanup-stale.sh`
- Modify: `tools/melee-agent/tests/test_worktree_retirement.py`
- Modify: `tools/melee-agent/tests/test_worktree_doctor.py`

**Interfaces:**
- Consumes: `inspect_worktrees` and `retire_worktrees`.
- Produces: `_worktrees_main(argv: Sequence[str]) -> int`, version-1 JSON payload, deterministic human output, and the documented exit codes 0/1/2.

- [ ] **Step 1: Write CLI and exact payload tests**

Call `worktree_doctor.main([...])` with monkeypatched reports/results. Assert `report` has empty `planned/removed/skipped`; dry-run contains planned only; apply contains exact removed/skipped/errors shapes and estimated-byte labels. Test `--min-idle-hours nan`, `inf`, and negative errors. Test status 1 for global preflight failure and status 2 for partial apply/late global failure.

- [ ] **Step 2: Write human-output and compatibility tests**

Assert human rows include branch, abbreviated HEAD, estimated bytes, idle duration, eligibility, and ordered reasons. Re-run existing doctor, banner, assets, artifacts, and symlinked-wrapper tests unchanged. Assert `cleanup-stale.sh --apply` still only prints commands and now points to `worktree-doctor.py worktrees retire` without executing it.

Create a real linked-worktree fixture and record the linked admin `index` mtime. Run report and dry-run, assert the mtime is byte-for-byte unchanged, and capture the status invocation to require exactly `git --no-optional-locks status --porcelain=v2 -z --untracked-files=all --ignore-submodules=none`. Add true/false/null `merged_into_master` fixtures and assert eligibility is identical in all three.

- [ ] **Step 3: Run CLI tests and confirm the red state**

Run: `python -m pytest tools/melee-agent/tests/test_worktree_retirement.py tools/melee-agent/tests/test_worktree_doctor.py tools/melee-agent/tests/test_worktree_artifacts.py -q`

Expected: new CLI tests fail before dispatch/payload implementation.

- [ ] **Step 4: Implement dispatch, serialization, printing, and exit mapping**

Dispatch only when `arguments[0] == "worktrees"`. Add `report` and `retire` subparsers, `--json`, `--min-idle-hours`, and `--apply` only on retire. Validate with `math.isfinite`. Build all modes from the same payload function so JSON/human facts cannot diverge. Keep report and dry-run read-only.

- [ ] **Step 5: Update the legacy script guidance without changing behavior**

Edit comments/final help in `cleanup-stale.sh` to call it a legacy commit-age report and recommend:

```text
python tools/worktree-doctor.py worktrees report
python tools/worktree-doctor.py worktrees retire
```

Do not change its existing `--apply` execution semantics in this issue.

- [ ] **Step 6: Run focused and full tooling verification**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_worktree_retirement.py tools/melee-agent/tests/test_worktree_doctor.py tools/melee-agent/tests/test_worktree_artifacts.py -q
python -m compileall -q tools/worktree_doctor tools/worktree-doctor.py
git diff --check
```

Expected: all tests pass, compileall exits 0, and diff check is empty.

- [ ] **Step 7: Exercise report/dry-run and a disposable fixture apply**

Run the branch-local CLI, never the installed editable main checkout:

```bash
python tools/worktree-doctor.py worktrees report --json
python tools/worktree-doctor.py worktrees retire --json
```

Create a temporary linked `codex/retirement-smoke-*` fixture under a recognized agent root and run `retire --apply --min-idle-hours 0 --json`; assert its checkout disappears while `refs/heads/codex/retirement-smoke-*` and HEAD remain. A separate test must still prove the default is 24 hours and a newly created fixture is ineligible. Do not apply to unrelated real worktrees during verification.

- [ ] **Step 8: Commit**

```bash
git add tools/worktree_doctor/__init__.py tools/worktree-doctor.py tools/workflow/cleanup-stale.sh tools/melee-agent/tests/test_worktree_retirement.py tools/melee-agent/tests/test_worktree_doctor.py
git commit -m "feat: expose worktree retirement lifecycle"
```

---

### Task 5: Final independent review and merge readiness

**Files:**
- Review only: all commits from the design commit through Task 4.

**Interfaces:**
- Consumes: the complete feature and approved design.
- Produces: review findings resolved, fresh verification evidence, and a clean branch ready for fast-forward merge.

- [ ] **Step 1: Request independent spec-compliance review**

Give a fresh reviewer the approved design, this plan, and full diff. Require Critical/Important/Minor findings, with special attention to data loss, TOCTOU, process bounds, retained evidence, asset validation, branch preservation, and exit semantics.

- [ ] **Step 2: Resolve findings test-first and commit each correction**

For every legitimate finding, add or tighten a regression test, observe it fail, apply the minimal correction, rerun the focused suite, and commit with a focused `fix:` message. If no findings exist, make no review-only commit.

- [ ] **Step 3: Run final verification from a clean tree**

```bash
python -m pytest tools/melee-agent/tests/test_worktree_retirement.py tools/melee-agent/tests/test_worktree_doctor.py tools/melee-agent/tests/test_worktree_artifacts.py -q
python -m compileall -q tools/worktree_doctor tools/worktree-doctor.py
git diff --check master...HEAD
git status --short
```

Expected: tests pass, compileall/diff check exit 0, and status is empty.

- [ ] **Step 4: Fast-forward merge, verify branch-local behavior on main, and resolve issue #1234**

Fast-forward `codex/worktree-retirement` into `master`, rerun the focused suite and both report/dry-run commands from `/Users/mike/code/melee`, then resolve with a note naming the merge commit and safety guarantees. Remove only this feature's completed isolated worktree with normal `git worktree remove`; preserve its branch.
