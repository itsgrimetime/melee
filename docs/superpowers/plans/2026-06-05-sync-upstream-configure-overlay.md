# Sync Upstream Configure Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `tools/workflow/sync-upstream.sh` preserve upstream-owned `configure.py` content while reapplying only fork-owned configure deltas and clearing stale generated config JSON.

**Architecture:** Treat `configure.py` as a hybrid file, not a normal tooling overlay. Leave upstream's file in place after reset, apply fork deltas with a small anchor-checked Python transform, then delete `build/*/config.json` before committing the restored overlay.

**Tech Stack:** Bash workflow script, embedded Python 3 text transform, pytest regression using temporary git repositories.

---

### Task 1: Regression Test For Hybrid Configure Sync

**Files:**
- Create: `tools/melee-agent/tests/test_sync_upstream.py`
- Read: `tools/workflow/sync-upstream.sh`

- [ ] **Step 1: Write the failing test**

Create `tools/melee-agent/tests/test_sync_upstream.py` with a temp-repo test.
The fixture should define helpers:

```python
from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
```

The test should:

```python
def test_sync_upstream_preserves_upstream_configure_and_clears_config_json(
    tmp_path: Path,
) -> None:
    upstream_work = tmp_path / "upstream-work"
    upstream_work.mkdir()
    _git(upstream_work, "init", "-b", "master")
    _git(upstream_work, "config", "user.email", "agent@example.test")
    _git(upstream_work, "config", "user.name", "Agent")
    (upstream_work / "configure.py").write_text(
        _upstream_configure("Object(NonMatching, \"melee/it/old.c\")"),
        encoding="utf-8",
    )
    _git(upstream_work, "add", "configure.py")
    _git(upstream_work, "commit", "-m", "upstream baseline")

    upstream_bare = tmp_path / "upstream.git"
    _git(upstream_work, "clone", "--bare", str(upstream_work), str(upstream_bare))

    repo = tmp_path / "melee"
    _git(tmp_path, "clone", str(upstream_bare), str(repo))
    _git(repo, "config", "user.email", "agent@example.test")
    _git(repo, "config", "user.name", "Agent")
    _git(repo, "remote", "rename", "origin", "upstream")

    workflow_dir = repo / "tools" / "workflow"
    workflow_dir.mkdir(parents=True)
    shutil.copy2(
        REPO_ROOT / "tools" / "workflow" / "sync-upstream.sh",
        workflow_dir / "sync-upstream.sh",
    )
    (repo / "configure.py").write_text(
        _fork_configure("Object(NonMatching, \"melee/it/old.c\")"),
        encoding="utf-8",
    )
    _git(repo, "add", "tools/workflow/sync-upstream.sh", "configure.py")
    _git(repo, "commit", "-m", "fork tooling")

    stale_config = repo / "build" / "GALE01" / "config.json"
    stale_config.parent.mkdir(parents=True)
    stale_config.write_text('{"version": "v1.8.3", "units": []}\n', encoding="utf-8")
    assert "?? build/" in _git(repo, "status", "--porcelain").stdout

    (upstream_work / "configure.py").write_text(
        _upstream_configure("Object(NonMatching, \"melee/it/new_split.c\")"),
        encoding="utf-8",
    )
    _git(upstream_work, "add", "configure.py")
    _git(upstream_work, "commit", "-m", "upstream split")
    _git(upstream_work, "push", str(upstream_bare), "master")

    result = subprocess.run(
        ["bash", "tools/workflow/sync-upstream.sh"],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    committed_configure = _git(repo, "show", "HEAD:configure.py").stdout
    assert 'Object(NonMatching, "melee/it/new_split.c")' in committed_configure
    assert 'Object(NonMatching, "melee/it/old.c")' not in committed_configure
    assert '--no-require-protos' in committed_configure
    assert 'default=True' in committed_configure
    assert 'config.wibo_tag = "1.0.0"' in committed_configure
    assert 'def _purge_wrong_arch_wibo' in committed_configure
    assert '_purge_wrong_arch_wibo(config)' in committed_configure
    assert not stale_config.exists()
    assert _git(repo, "status", "--porcelain").stdout == ""
```

Add `_upstream_configure` and `_fork_configure` helpers that include the exact
anchors the transform will use: a `--require-protos` parser block, a
`config.wibo_tag = "0.7.0"` line in upstream input, `config.progress_report_args
= [...]`, and an `if args.mode == "configure":` block calling
`generate_build(config)`.

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
cd /Users/mike/code/melee
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= pytest --no-cov -p no:cacheprovider tools/melee-agent/tests/test_sync_upstream.py -q
```

Expected before implementation: failure because the committed `configure.py`
contains the old fork `Object(...)` entry or because stale `build/GALE01/config.json`
still exists.

### Task 2: Implement Safe Configure Overlay And Config Cleanup

**Files:**
- Modify: `tools/workflow/sync-upstream.sh`
- Test: `tools/melee-agent/tests/test_sync_upstream.py`

- [ ] **Step 1: Remove configure.py from wholesale tooling overlay**

In `tools/workflow/sync-upstream.sh`, remove `"configure.py"` from
`TOOLING_PATHS`.

- [ ] **Step 2: Add an anchor-checked configure overlay function**

Add a shell function after `TOOLING_PATHS`:

```bash
apply_configure_overlay() {
    python3 - "$REPO_ROOT/configure.py" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

def replace_once(label: str, old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"configure.py overlay failed: expected one {label} anchor, found {count}")
    text = text.replace(old, new, 1)

require_old = '''parser.add_argument(
    "--require-protos",
    dest="require_protos",
    action="store_true",
    help="require function prototypes",
)
'''
require_new = '''parser.add_argument(
    "--require-protos",
    dest="require_protos",
    action="store_true",
    default=True,
    help="require function prototypes (default: enabled)",
)
parser.add_argument(
    "--no-require-protos",
    dest="require_protos",
    action="store_false",
    help="disable function prototype requirement",
)
'''
replace_once("require-protos parser block", require_old, require_new)
replace_once("wibo tag", 'config.wibo_tag = "0.7.0"', 'config.wibo_tag = "1.0.0"')

helper = '''
def _purge_wrong_arch_wibo(config: ProjectConfig) -> None:
    """Fork-only: drop build/tools/wibo if it's wrong arch for this host."""
    import sys

    wibo = config.build_dir / "tools" / "wibo"
    if not wibo.exists():
        return
    try:
        with open(wibo, "rb") as f:
            magic = f.read(4)
    except OSError:
        return
    is_macho = magic in (
        b"\\xcf\\xfa\\xed\\xfe", b"\\xfe\\xed\\xfa\\xcf",
        b"\\xfe\\xed\\xfa\\xce", b"\\xce\\xfa\\xed\\xfe",
    )
    is_elf = magic == b"\\x7fELF"
    correct = is_macho if sys.platform == "darwin" else is_elf
    if not correct:
        kind = "Mach-O" if sys.platform == "darwin" else "ELF"
        print(
            f"warning: {wibo} is wrong arch (expected {kind} for {sys.platform}); "
            "removing so it will be re-downloaded"
        )
        wibo.unlink()

'''
insert_after = '''config.progress_report_args = [
    # Marks relocations as mismatching if the target value is different
    # Default is "functionRelocDiffs=none", which is most lenient
    # "--config functionRelocDiffs=data_value",
]

'''
replace_once("progress report args block", insert_after, insert_after + helper)
replace_once(
    "configure mode generate_build call",
    '''if args.mode == "configure":
    # Write build.ninja and objdiff.json
    generate_build(config)
''',
    '''if args.mode == "configure":
    # Write build.ninja and objdiff.json
    _purge_wrong_arch_wibo(config)
    generate_build(config)
''',
)

path.write_text(text, encoding="utf-8")
PY
}
```

Keep the full helper body consistent with the existing fork helper in
`configure.py`; if the docstring is shortened, preserve the runtime behavior.

- [ ] **Step 3: Add stale generated config cleanup**

Add a shell function:

```bash
remove_stale_build_configs() {
    if [[ ! -d "$REPO_ROOT/build" ]]; then
        return
    fi
    find "$REPO_ROOT/build" -mindepth 2 -maxdepth 2 -name config.json -type f -print -delete
}
```

Call `apply_configure_overlay` and `remove_stale_build_configs` after restoring
regular tooling and recreating symlinks, before `git add -A`.

- [ ] **Step 4: Leave current configure.py untouched**

This fix changes the sync script, not the current checked-in `configure.py`.
If the current worktree already has a repaired upstream-plus-fork
`configure.py`, preserve that state and do not restore an older whole-file
overlay.

- [ ] **Step 5: Run the test and verify it passes**

Run:

```bash
cd /Users/mike/code/melee
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= pytest --no-cov -p no:cacheprovider tools/melee-agent/tests/test_sync_upstream.py -q
```

Expected: test passes.

### Task 3: Verification, Commit, And Issue Resolution

**Files:**
- Commit: `configure.py`
- Commit: `tools/workflow/sync-upstream.sh`
- Commit: `tools/melee-agent/tests/test_sync_upstream.py`
- Commit: `docs/superpowers/specs/2026-06-05-sync-upstream-configure-overlay-design.md`
- Commit: `docs/superpowers/plans/2026-06-05-sync-upstream-configure-overlay.md`

- [ ] **Step 1: Run focused verification**

Run:

```bash
cd /Users/mike/code/melee
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= pytest --no-cov -p no:cacheprovider tools/melee-agent/tests/test_sync_upstream.py tools/melee-agent/tests/test_pr_worktree.py -q
bash -n tools/workflow/sync-upstream.sh
python -m py_compile tools/melee-agent/tests/test_sync_upstream.py
git diff --check -- configure.py tools/workflow/sync-upstream.sh tools/melee-agent/tests/test_sync_upstream.py docs/superpowers/specs/2026-06-05-sync-upstream-configure-overlay-design.md docs/superpowers/plans/2026-06-05-sync-upstream-configure-overlay.md
```

Expected: all commands exit 0.

- [ ] **Step 2: Commit**

Run:

```bash
git add configure.py tools/workflow/sync-upstream.sh tools/melee-agent/tests/test_sync_upstream.py docs/superpowers/specs/2026-06-05-sync-upstream-configure-overlay-design.md docs/superpowers/plans/2026-06-05-sync-upstream-configure-overlay.md
git commit -m "Fix upstream sync configure overlay"
```

- [ ] **Step 3: Resolve issues and recheck queue**

Run:

```bash
FIX_COMMIT="$(git rev-parse --short HEAD)"
/opt/homebrew/bin/melee-agent issue resolve 426 --note "Fixed in ${FIX_COMMIT}: sync-upstream now keeps upstream configure.py as base and reapplies only fork configure deltas with anchor checks."
/opt/homebrew/bin/melee-agent issue resolve 427 --note "Fixed in ${FIX_COMMIT}: sync-upstream removes stale build/*/config.json after sync."
/opt/homebrew/bin/melee-agent issue list --status open
git status --short --branch
```

Expected: no open issues and clean `master`.
