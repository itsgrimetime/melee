# Backtest Harness Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Make the tooling-backtest harness actually produce coverage data against real master history, by fixing the two blockers the real-run validation campaign exposed: (A) fragile per-commit build provisioning, (B) broken function-first corpus construction.

**Why (empirical, 2026-06-26):** The machinery works on a clean recent commit, but: `find_match_commit -S` misses stub-preserving matches; the ≤30-line filter excludes genuine structural-add matches; small single-`.c` matches are dominated by coloring/data-order/inline tweaks; and building at arbitrary historical commits fails because fresh worktrees can't provision the toolchain (`worktree-doctor` purges/redownloads a working x86_64 `wibo`, and `binutils`/`objdiff-cli` downloads fail). See `tooling-backtest-harness-project` memory + the SDD ledger.

## Global Constraints (verbatim)

- Run CLI/pytest from `tools/melee-agent/`. `MAIN_REPO` resolves via `paths.main_repo_root()` (the shared main checkout `/Users/mike/code/melee`).
- **Validated provisioning recipe** (de-risked by real builds 2026-06-26): in a worktree/sandbox checked out at the target commit —
  1. `git checkout master -- tools` (bootstrap fork tooling — `tools/checkdiff.py`/`worktree-doctor.py` are absent from older commits).
  2. Copy main's known-good toolchain: `cp -Rp <main>/build/tools <wt>/build/tools`, same for `build/binutils`, `build/compilers`. (main's `wibo` is **x86_64 Mach-O**, runs via Rosetta; `_purge_wrong_arch_wibo` accepts any Mach-O on darwin so `configure.py` will NOT purge it.)
  3. Symlink the DOL: `<wt>/orig/GALE01/sys/main.dol -> <main>/orig/GALE01/sys/main.dol`.
  4. `python configure.py` (generates `build.ninja`; preserves the Mach-O `wibo`).
  5. `ninja build/GALE01/report.json` (REQUIRED before checkdiff — `checkdiff.py:3676 find_unit_for_function` reads `report.json` before its own build).
  6. Then `checkdiff <fn> --format json --no-tty` (env `CHECKDIFF_NO_LOCK=1 CHECKDIFF_NO_FINGERPRINT=1`).
  - Do **NOT** run `worktree-doctor --fix` for tools (it purges/redownloads `wibo` and triggers flaky `binutils`/`objdiff-cli` downloads). Provision directly.
- **Structural gate (unchanged):** a valid case requires `c_ndl == 0` at C AND `p_ndl > 0` at C~1 (`build_corpus` already enforces this).
- Builds are slow (~2-5 min each with the toolchain pre-seeded, no downloads). Real-build tests gated behind `BACKTEST_SLOW=1`.
- No `worktree-doctor` download reliance; never mutate the main working tree (worktrees/clones off it are read-side; clean up in `finally`).

---

## Task 1: `provision.py` — robust worktree provisioning

**Files:** Create `tools/melee-agent/src/backtest/provision.py`; Test `tools/melee-agent/tests/backtest/test_provision.py`.

**Interfaces — Produces:**
- `provision_worktree(workdir: str, *, main_repo: str, runner=subprocess.run) -> None` — performs steps 1-5 of the recipe (bootstrap tools, copy toolchain, symlink DOL, configure, ninja report.json). Raises `ProvisionError` (new) with the failing step + stderr tail on any non-zero step.
- `class ProvisionError(RuntimeError)`.

- [ ] **Step 1: failing unit test** (inject a fake runner; assert the command/sequence, no real build):

```python
# tests/backtest/test_provision.py
import subprocess
import pytest
from pathlib import Path
from src.backtest.provision import provision_worktree, ProvisionError

class Rec:
    def __init__(self): self.calls=[]
    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        class P: returncode=0; stdout=""; stderr=""
        return P()

def test_provision_runs_recipe_in_order(tmp_path, monkeypatch):
    rec = Rec()
    monkeypatch.setattr("src.backtest.provision.shutil.copytree", lambda *a, **k: None)
    monkeypatch.setattr("src.backtest.provision.Path.symlink_to", lambda *a, **k: None)
    monkeypatch.setattr("src.backtest.provision.Path.is_symlink", lambda self: False)
    provision_worktree(str(tmp_path/"wt"), main_repo="/main", runner=rec)
    joined = [" ".join(c) for c in rec.calls]
    assert any("checkout master -- tools" in j for j in joined)            # bootstrap
    assert any(j.endswith("configure.py") or "configure.py" in j for j in joined)
    assert any("ninja" in j and "report.json" in j for j in joined)        # report.json before checkdiff
    # configure precedes ninja report.json
    assert next(i for i,j in enumerate(joined) if "configure.py" in j) < \
           next(i for i,j in enumerate(joined) if "report.json" in j)

def test_provision_raises_on_failed_step(tmp_path, monkeypatch):
    def boom(cmd, **kw):
        class P: returncode=(1 if "configure.py" in " ".join(cmd) else 0); stdout=""; stderr="cfg boom"
        return P()
    monkeypatch.setattr("src.backtest.provision.shutil.copytree", lambda *a, **k: None)
    monkeypatch.setattr("src.backtest.provision.Path.symlink_to", lambda *a, **k: None)
    monkeypatch.setattr("src.backtest.provision.Path.is_symlink", lambda self: False)
    with pytest.raises(ProvisionError):
        provision_worktree(str(tmp_path/"wt"), main_repo="/main", runner=boom)
```

- [ ] **Step 2: run, confirm fail** (`ModuleNotFoundError`).
- [ ] **Step 3: implement** `provision.py`:

```python
# tools/melee-agent/src/backtest/provision.py
from __future__ import annotations
import shutil, subprocess, sys
from pathlib import Path


class ProvisionError(RuntimeError):
    pass


def _run(runner, cmd, *, cwd=None, step):
    p = runner(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise ProvisionError(f"{step} failed (rc={p.returncode}): {(p.stderr or p.stdout)[-300:]}")
    return p


def provision_worktree(workdir: str, *, main_repo: str, runner=subprocess.run) -> None:
    """Make `workdir` (a checkout at the target commit) buildable, using main's
    known-good toolchain — no worktree-doctor download/purge. See plan Global Constraints."""
    wt = Path(workdir)
    # 1) bootstrap fork tooling (older commits lack tools/checkdiff.py & worktree-doctor.py)
    _run(runner, ["git", "-C", str(wt), "checkout", "master", "--", "tools"], step="bootstrap-tools")
    # 2) copy main's known-good toolchain (x86_64 Mach-O wibo is fine on darwin via Rosetta)
    (wt / "build").mkdir(parents=True, exist_ok=True)
    for d in ("tools", "binutils", "compilers"):
        src = Path(main_repo) / "build" / d
        dst = wt / "build" / d
        if src.exists() and not dst.exists():
            shutil.copytree(src, dst, symlinks=True)
    # 3) symlink the ground-truth DOL
    dol = wt / "orig" / "GALE01" / "sys" / "main.dol"
    dol.parent.mkdir(parents=True, exist_ok=True)
    if not dol.is_symlink():
        dol.symlink_to(str(Path(main_repo) / "orig" / "GALE01" / "sys" / "main.dol"))
    # 4) configure (won't purge the Mach-O wibo) + 5) generate report.json before checkdiff
    _run(runner, [sys.executable, "configure.py"], cwd=str(wt), step="configure")
    _run(runner, ["ninja", "build/GALE01/report.json"], cwd=str(wt), step="ninja-report")
```

- [ ] **Step 4: run unit tests, pass.**
- [ ] **Step 5: commit** `feat(backtest): robust provision_worktree (no worktree-doctor downloads)`.

## Task 2: wire provision into `score_at_commit`

**Files:** Modify `tools/melee-agent/src/backtest/run.py`; Test extend `tests/backtest/test_run_scorer.py`.

**Interfaces — Consumes** `provision_worktree`. `score_at_commit` keeps its signature/return `(fuzzy, ndl)` but provisions via H1 instead of `worktree-doctor --fix`.

- [ ] **Step 1: failing test** — monkeypatch `provision_worktree` + `run_checkdiff_at`, assert `score_at_commit` calls provision (not worktree-doctor) and returns the parsed `(pct, ndl)`:

```python
def test_score_at_commit_uses_provision(monkeypatch, tmp_path):
    from src.backtest import run as R
    calls = {}
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: type("P",(),{"returncode":0,"stdout":"","stderr":""})())
    monkeypatch.setattr("src.backtest.provision.provision_worktree", lambda *a, **k: calls.setdefault("prov", True))
    monkeypatch.setattr(R, "run_checkdiff_at", lambda sb, fn, timeout=600: {"fuzzy_match_percent": 100.0, "classification": {"structural_truth_gate": {"normalized_diff_lines": 0}}})
    pct, ndl = R.score_at_commit("/main", "fn", "abc123", scratch_root=tmp_path)
    assert calls.get("prov") and pct == 100.0 and ndl == 0
```

- [ ] **Step 2: run, fail.**
- [ ] **Step 3: implement** — rewrite `score_at_commit`:

```python
def score_at_commit(main_repo: str, function: str, sha: str, *, scratch_root: Path, timeout: float = 600.0):
    from .provision import provision_worktree
    wt = scratch_root / f"at_{sha[:12]}_{function[:16]}"   # include fn -> no concurrent-name collision
    subprocess.run(["git", "-C", main_repo, "worktree", "add", "--detach", str(wt), sha], check=True,
                   capture_output=True, text=True)
    try:
        provision_worktree(str(wt), main_repo=main_repo)
        payload = run_checkdiff_at(str(wt), function, timeout=timeout)
        return payload.get("fuzzy_match_percent"), _structural_ndl(payload)
    finally:
        subprocess.run(["git", "-C", main_repo, "worktree", "remove", "--force", str(wt)], check=False)
```

- [ ] **Step 4: run tests** (incl. existing `test_run_scorer.py`), pass.
- [ ] **Step 5: commit** `fix(backtest): score_at_commit provisions toolchain (no worktree-doctor); fn in wt name`.

## Task 3: wire provision into `build_sandbox` (blind tier)

**Files:** Modify `tools/melee-agent/src/backtest/sandbox.py` (+ the `cheap_tiers_with_real_judge` sandbox_factory in `run.py` which currently calls `worktree-doctor --fix`); Test extend `tests/backtest/test_sandbox.py`.

**Interfaces:** `build_sandbox` keeps the empty-repo fetch + `assert_commit_absent` (the leak probe is unchanged), but after the fetch+checkout it calls `provision_worktree` (which bootstraps tools, copies toolchain, symlinks DOL, configure, ninja report.json) instead of relying on `worktree-doctor`. Remove the now-redundant DOL-symlink block from `build_sandbox` (provision does it). Update `run.py`'s `cheap_tiers_with_real_judge.sandbox_factory` to drop its `worktree-doctor --fix` subprocess call (build_sandbox now fully provisions).

- [ ] **Step 1: failing test** — monkeypatch `provision_worktree`; assert `build_sandbox` still asserts C absent AND calls provision; the leak-probe tests stay green.
- [ ] **Step 2: run, fail.**
- [ ] **Step 3: implement** — in `build_sandbox`, after `assert_commit_absent`, call `provision_worktree(str(dest), main_repo=main_repo)`; drop the manual DOL block. In `run.py`, remove the `worktree-doctor --fix` line from `sandbox_factory`.
- [ ] **Step 4: tests pass** (sandbox + leak probe).
- [ ] **Step 5: commit** `fix(backtest): blind sandbox provisions via provision_worktree`.

## Task 4: commit-first discovery — `discover.py`

**Files:** Create `tools/melee-agent/src/backtest/discover.py`; Test `tools/melee-agent/tests/backtest/test_discover.py`.

**Interfaces — Produces:**
- `classify_shape(diff: str) -> str` ∈ {`stub_to_def`, `new_fn`, `tweak`} — `stub_to_def` iff a removed line matches `///\s*#?\s*(\w+)` (stub marker removed); `new_fn` iff a function-definition line is added and there are no removed content lines; else `tweak`.
- `parse_match_function(diff: str) -> str | None` — the matched function name: prefer the stub-marker symbol; else the first added `(?:static\s+)?<type> <name>(` definition (excluding keywords `if/for/while/switch/return/sizeof`); else None.
- `discover_match_commits(git_runner, *, limit: int = 20, max_lines: int = 60, scan: int = 4000) -> list[dict]` — `git log master -n <scan> --numstat --format=...`, keep commits changing **exactly one** `src/melee/**/*.c` with `added+removed <= max_lines`, parse `(function, shape)` from `git show <sha> -- <file>`, return up to `limit` dicts `{"function","c_sha","cprev_sha","file","added","removed","shape"}` (skip ones where `parse_match_function` is None or the symbol looks like a data/inline helper: `sdata2`, `order_sdata2`, `*_inline`, `*_noinline`). git_runner injected for tests.

(Note the size policy: `max_lines=60` admits some `stub_to_def`/`new_fn` structural adds the old ≤30 filter excluded; the structural gate in `build_corpus` remains the real validity filter.)

- [ ] **Step 1: failing tests** — `classify_shape` on a stub-removal diff → `stub_to_def`; on a +N/-0 def-add → `new_fn`; on an in-place edit → `tweak`. `parse_match_function` returns the stub symbol / the def name / None. `discover_match_commits` with a fake git_runner (canned `--numstat` + `show` outputs) returns the expected triples and skips a `sdata2_order` helper.
- [ ] **Step 2: run, fail.**
- [ ] **Step 3: implement** `discover.py` (regex helpers + the git scan; mirror the validated discovery logic from the campaign's `discover.py` scratch prototype).
- [ ] **Step 4: tests pass.**
- [ ] **Step 5: commit** `feat(backtest): commit-first match-commit discovery (replaces find_match_commit -S)`.

## Task 5: commit-first corpus build + CLI

**Files:** Modify `build_corpus.py` (add `build_corpus_from_commits`), `run.py` (add `build_and_store_corpus_from_commits`), `src/cli/backtest.py` (add `discover` + `build-corpus --from-commits`); Test `tests/backtest/test_build_corpus.py` (+ a CLI test).

**Interfaces — Produces:**
- `build_corpus_from_commits(*, triples, report, git_runner, patterns, score_flip) -> list[Case]` — like `build_corpus` but takes discovered `triples` (C/C~1 already known; no `find_match_commit`). Applies the structural gate (`c_ndl==0`, `p_ndl>0`), `classify_lever`, provenance labeling; sets `lever_locus="in_function"`. Records the diff shape in `lever_class` only via `classify_lever` (shape is informational).
- CLI `backtest discover [--limit N] [--max-lines 60] [--json]` → prints discovered triples (cheap, no builds).
- CLI `backtest build-corpus --from-commits [--limit N] [--db PATH] [--json]` → discover → `score_flip` (provisioned builds) gate → store Cases.

- [ ] **Step 1: failing tests** — `build_corpus_from_commits` emits a Case when the injected `score_flip` reports a structural flip and drops it when not (mirror existing `test_build_corpus`); a CliRunner test for `discover --json` with a monkeypatched `discover_match_commits`.
- [ ] **Step 2: run, fail.**
- [ ] **Step 3: implement** the function + the two CLI commands (deferred imports; `discover` uses `default_git_runner(main_repo_root())`).
- [ ] **Step 4: tests pass; `backtest --help` lists `discover`.**
- [ ] **Step 5: commit** `feat(backtest): commit-first build-corpus + discover CLI`.

## Task 6: real coverage batch (the payoff)

Not a code task — the end-to-end run, executed by the controller (slow, real builds).

- [ ] `backtest discover --limit 12 --json` → inspect candidates (favor a mix incl. `stub_to_def`/`new_fn`).
- [ ] `backtest build-corpus --from-commits --limit 8 --db <scratch.db>` → provisioned ground-truth builds + structural gate → stored Cases. Record the **yield** (valid structural flips / dropped-coloring / build-fail).
- [ ] If yield > 0: `backtest calibrate` (gate), then `backtest run --cheap --db <scratch.db>` → the FIRST real coverage rows; `backtest report --db <scratch.db>`.
- [ ] Report the coverage matrix + yield. Update the `tooling-backtest-harness-project` memory with real numbers.

---

## Self-Review
- **Spec coverage:** provisioning (H1-H3) + commit-first discovery (H4-H5) + run (H6) — the two workstreams the user approved.
- **Placeholder scan:** the provisioning recipe is verbatim-validated; discovery mirrors the proven scratch prototype; no TBDs.
- **Type consistency:** `score_at_commit`/`score_flip` keep `(fn,sha)->(pct,ndl)`; `Case` fields unchanged; `provision_worktree(workdir,*,main_repo,runner)` used by H2/H3.
- **Risk:** H6 builds may still surface per-commit edge cases (old commits predating arm64 toolchain compatibility); H4's `max_lines=60` + helper-skip list may need tuning — both are run-time tunables, not blockers.
