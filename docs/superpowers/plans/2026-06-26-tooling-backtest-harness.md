# Tooling-Backtest Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a harness that replays historical single-function match commits at their pre-match state, runs our tooling blind, and scores whether the tooling would have led an agent to the known fix — producing a lever-class × tier coverage matrix and a feedback loop.

**Architecture:** A new `melee-agent backtest` CLI group (deterministic primitives: corpus construction, blind sandbox, advisory/generative tier runners, scoring, storage, report) plus a thin Workflow that orchestrates the LLM-dependent parts (advisory judge, blind-agent tier). Structurally mirrors the already-shipped `inline_leverage` harness (`tools/melee-agent/src/inline_leverage/`).

**Tech Stack:** Python 3.11, Typer (CLI), sqlite3, pytest + `typer.testing.CliRunner`, `tools/checkdiff.py` (scoring), git (corpus + sandbox), `melee-agent debug …` tools (units under test).

**Spec:** `docs/superpowers/specs/2026-06-26-tooling-backtest-harness-design.md` (Revision 1).

## Global Constraints

Every task's requirements implicitly include this section. Values are verbatim from the grounding investigation.

- **CLI package root is `tools/melee-agent/`.** Run ALL `melee-agent`/`python -m src.cli` and `pytest` commands from `tools/melee-agent/` so `from src…` imports resolve. There is a *separate, limited* top-level `<repo>/src/` — do not use it. The installed `melee-agent` binary may resolve to a different checkout (`~/.codex/worktrees/eeff`); the harness must invoke the CLI under test as `python -m src.cli …` from `tools/melee-agent/` (pin to the worktree), not the homebrew binary.
- **checkdiff scoring invocation (verbatim):** `python tools/checkdiff.py <FUNCTION> --format json --no-tty`, `cwd=<melee_root>`, env `CHECKDIFF_NO_LOCK=1` and `CHECKDIFF_NO_FINGERPRINT=1`. Exit codes: 0=match, 1=mismatch (both normal). Never pass `--no-build` when a score is needed (it forces `fuzzy_match_percent=null`).
- **Structural score key:** `payload["classification"]["structural_truth_gate"]["normalized_diff_lines"]` (int; 0 = true structural match). **Fuzzy score:** top-level `payload["fuzzy_match_percent"]` (float or null). The top-level `structural` block does NOT contain `normalized_diff_lines`.
- **A build is mandatory** before checkdiff / any `debug` tool / `opseq`: `python configure.py && ninja` (or `worktree-doctor --fix`, which also refreshes `report.json`). Tools resolve functions via `build/GALE01/report.json` and emit `<fn> not in report.json` otherwise.
- **`orig/GALE01/sys/main.dol` and `build/` are gitignored** — never carried by clone/archive. Always symlink the DOL to `/Users/mike/code/melee/orig/GALE01/sys/main.dol`.
- **Blind sandbox** = empty-repo single-commit fetch (a `git worktree` or full clone CANNOT exclude the answer commit). The answer commit `C` MUST be provably absent before any blind tier runs.
- **Tier tools take function names + local `.c` paths, never decomp.me scratch slugs.** They mutate the working tree in some modes — fine in a throwaway sandbox.
- **No auto-commit** of pattern-DB entries or source. Gaps → `melee-agent issue report` + a staged proposal file under `build/backtest/staged/` (gitignored).
- **Result store:** a dedicated `BacktestStore` SQLite at `~/.config/decomp-me/backtest_results.db` (mirrors `InlineLeverageStore`; do not migrate `agent_state.db` or the mining schema).
- **Headline metric is held-out coverage** (in-corpus reported separately). The report MUST print the estimand caveat verbatim (see Task 5.1).
- **Lever classes (the `LEVER_CLASSES` vocabulary):** `embedded_assign_temp`, `hoist_to_local`, `split_local`, `retype`, `struct_overlay`, `literal_vs_named`, `decl_reorder`, `count_down_or_compare_reuse`, `inline_arg_or_schedule`, `backend_coloring`, `other`.

---

## Milestone 0 — Package scaffold + types + calibration fixtures

Produces: a registered, discoverable `melee-agent backtest` group and the shared types, with the synthetic calibration dataset committed.

### Task 0.1: Scaffold the `backtest` CLI group

**Files:**
- Create: `tools/melee-agent/src/backtest/__init__.py`
- Create: `tools/melee-agent/src/cli/backtest.py`
- Modify: `tools/melee-agent/src/cli/__init__.py` (add import + `app.add_typer` next to the other groups, ~lines 34–110)
- Test: `tools/melee-agent/tests/cli/test_backtest_cli.py`

**Interfaces:**
- Produces: `backtest_app: typer.Typer`; subcommand `status` echoing a JSON object `{"harness": "backtest", "ready": true}`.

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/cli/test_backtest_cli.py
import json
from typer.testing import CliRunner
from src.cli import app

def test_backtest_status_is_registered():
    result = CliRunner().invoke(app, ["backtest", "status", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"harness": "backtest", "ready": True}
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/cli/test_backtest_cli.py -q`
Expected: FAIL — `No such command 'backtest'` (exit code 2).

- [ ] **Step 3: Implement the group + wiring**

```python
# tools/melee-agent/src/backtest/__init__.py
"""Tooling-backtest harness: replay pre-match state, run tooling blind, score."""
```

```python
# tools/melee-agent/src/cli/backtest.py
"""`melee-agent backtest` — replay historical match commits and score the tooling."""
from __future__ import annotations

import json as _json
from typing import Annotated

import typer

backtest_app = typer.Typer(
    help="Backtest the matching tooling against historical single-function match commits.",
    no_args_is_help=True,
)


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
```

In `tools/melee-agent/src/cli/__init__.py`, add alongside the other group imports:

```python
from .backtest import backtest_app
```

and alongside the other `add_typer` calls:

```python
app.add_typer(backtest_app, name="backtest")
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/cli/test_backtest_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Confirm no unregistered-app warning**

Run: `cd tools/melee-agent && melee-agent capabilities generate 2>&1 | grep -i 'WARNING: Typer apps' || echo 'all apps registered'`
Expected: `all apps registered` (and the brief is refreshed — commit the regenerated brief if it changed).

- [ ] **Step 6: Commit**

```bash
git add tools/melee-agent/src/backtest/__init__.py tools/melee-agent/src/cli/backtest.py tools/melee-agent/src/cli/__init__.py tools/melee-agent/tests/cli/test_backtest_cli.py
git commit -m "feat(backtest): scaffold backtest CLI group"
```

### Task 0.2: Shared types

**Files:**
- Create: `tools/melee-agent/src/backtest/types.py`
- Test: `tools/melee-agent/tests/backtest/test_types.py`

**Interfaces:**
- Produces:
  - `LEVER_CLASSES: tuple[str, ...]` (the Global-Constraints vocabulary).
  - `@dataclass Case` with fields: `function: str`, `c_sha: str`, `cprev_sha: str`, `unit: str`, `file: str`, `ground_truth_diff: str`, `lever_locus: str`, `author: str`, `provenance: str`, `lever_class: str`, `baseline_pct: float | None`, `baseline_ndl: int | None`, `target_pct: float | None`, `target_ndl: int | None`; a computed `case_id: str` property = `sha256(f"{c_sha}\x00{function}").hexdigest()[:16]`; and a computed `target_ndl_is_zero: bool` property = `self.target_ndl == 0`.
  - Literals: `AdvisoryVerdict = Literal["names-lever","hints-adjacent","silent-or-wrong"]`; `GenerativeVerdict = Literal["byte-match-reproduced","improved-toward","no-progress"]`; `AgentVerdict = Literal["matched","improved","stuck"]`; `CaseVerdict = Literal["SOLVED-BY-TOOLING","PARTIAL","GAP"]`.
  - `@dataclass CaseResult`: `case_id: str`, `advisory: AdvisoryVerdict | None`, `generative: GenerativeVerdict | None`, `agent: AgentVerdict | None`, `rollup: CaseVerdict | None`, `evidence: dict` (raw tool outputs / scores), with `to_row() -> dict` (JSON-encodes `evidence`).

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_types.py
from src.backtest.types import Case, CaseResult, LEVER_CLASSES

def test_case_id_is_stable_and_short():
    c = Case(function="grIceMt_801F9ACC", c_sha="3ce0722cd"*4 + "abcd",
             cprev_sha="13ccea114"*4 + "abcd", unit="main/melee/gr/gricemt",
             file="src/melee/gr/gricemt.c", ground_truth_diff="@@ ...",
             lever_locus="in_function", author="other", provenance="held_out",
             lever_class="retype", baseline_pct=99.98, baseline_ndl=4, target_pct=100.0)
    assert len(c.case_id) == 16
    assert c.case_id == c.case_id  # deterministic

def test_lever_classes_include_backend_coloring():
    assert "backend_coloring" in LEVER_CLASSES
    assert "other" in LEVER_CLASSES

def test_case_result_row_jsonifies_evidence():
    r = CaseResult(case_id="abc", advisory="names-lever", generative=None,
                   agent=None, rollup="PARTIAL", evidence={"k": [1, 2]})
    row = r.to_row()
    assert row["evidence"] == '{"k": [1, 2]}'
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_types.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.backtest.types'`.

- [ ] **Step 3: Implement `types.py`**

```python
# tools/melee-agent/src/backtest/types.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal, Optional

LEVER_CLASSES: tuple[str, ...] = (
    "embedded_assign_temp", "hoist_to_local", "split_local", "retype",
    "struct_overlay", "literal_vs_named", "decl_reorder",
    "count_down_or_compare_reuse", "inline_arg_or_schedule", "backend_coloring",
    "other",
)

AdvisoryVerdict = Literal["names-lever", "hints-adjacent", "silent-or-wrong"]
GenerativeVerdict = Literal["byte-match-reproduced", "improved-toward", "no-progress"]
AgentVerdict = Literal["matched", "improved", "stuck"]
CaseVerdict = Literal["SOLVED-BY-TOOLING", "PARTIAL", "GAP"]


@dataclass
class Case:
    function: str
    c_sha: str
    cprev_sha: str
    unit: str
    file: str
    ground_truth_diff: str
    lever_locus: str
    author: str
    provenance: str
    lever_class: str
    baseline_pct: Optional[float] = None
    baseline_ndl: Optional[int] = None
    target_pct: Optional[float] = None
    target_ndl: Optional[int] = None

    @property
    def case_id(self) -> str:
        return hashlib.sha256(f"{self.c_sha}\x00{self.function}".encode()).hexdigest()[:16]

    @property
    def target_ndl_is_zero(self) -> bool:
        return self.target_ndl == 0


@dataclass
class CaseResult:
    case_id: str
    advisory: Optional[AdvisoryVerdict] = None
    generative: Optional[GenerativeVerdict] = None
    agent: Optional[AgentVerdict] = None
    rollup: Optional[CaseVerdict] = None
    evidence: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        d = dict(self.__dict__)
        d["evidence"] = json.dumps(self.evidence)
        return d
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_types.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/types.py tools/melee-agent/tests/backtest/test_types.py
git commit -m "feat(backtest): shared types and lever-class vocabulary"
```

### Task 0.3: Synthetic calibration fixtures

The Phase-0 two-sided calibration (spec §10) needs known-answer cases that do not depend on a live build. These fixtures are pure data + a loader; the calibration *assertions* land in Task 4.4.

**Files:**
- Create: `tools/melee-agent/tests/backtest/fixtures/calibration.json`
- Create: `tools/melee-agent/src/backtest/fixtures.py`
- Test: `tools/melee-agent/tests/backtest/test_fixtures.py`

**Interfaces:**
- Produces: `load_calibration_fixtures() -> list[dict]`. Each fixture: `{"name": str, "kind": "positive"|"negative", "expected_rollup": "SOLVED-BY-TOOLING"|"GAP", "lever_class": str, "ground_truth_diff": str, "note": str}`. `positive` = a lever our tooling owns (must SOLVE); `negative` = a backend-coloring tie-break deliberately withheld from the DBs (must GAP).

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_fixtures.py
from src.backtest.fixtures import load_calibration_fixtures

def test_fixtures_have_both_polarities():
    fx = load_calibration_fixtures()
    kinds = {f["kind"] for f in fx}
    assert kinds == {"positive", "negative"}
    # negatives must expect GAP, positives must expect SOLVED
    for f in fx:
        if f["kind"] == "negative":
            assert f["expected_rollup"] == "GAP"
        else:
            assert f["expected_rollup"] == "SOLVED-BY-TOOLING"

def test_negatives_are_backend_coloring():
    fx = load_calibration_fixtures()
    negs = [f for f in fx if f["kind"] == "negative"]
    assert negs and all(f["lever_class"] == "backend_coloring" for f in negs)
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_fixtures.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create the dataset + loader**

```json
// tools/melee-agent/tests/backtest/fixtures/calibration.json
[
  {
    "name": "pos_retype_u8_param",
    "kind": "positive",
    "expected_rollup": "SOLVED-BY-TOOLING",
    "lever_class": "retype",
    "ground_truth_diff": "@@ fn @@\n-    int mode = get_mode();\n+    u8 mode = get_mode();\n",
    "note": "u8/clrlwi retype is in mismatch-db; advisory must name it."
  },
  {
    "name": "pos_literal_vs_named",
    "kind": "positive",
    "expected_rollup": "SOLVED-BY-TOOLING",
    "lever_class": "literal_vs_named",
    "ground_truth_diff": "@@ fn @@\n-    foo(name_str);\n+    foo(0.0f);\n",
    "note": "bare literal vs named symbol; a documented scheduler lever."
  },
  {
    "name": "neg_fpr_window_rotation",
    "kind": "negative",
    "expected_rollup": "GAP",
    "lever_class": "backend_coloring",
    "ground_truth_diff": "@@ fn @@\n# equal-lifetime f26<->f28 callee-save rotation; no source lever\n",
    "note": "backend coloring tie-break withheld from DBs; tooling MUST score GAP."
  },
  {
    "name": "neg_gpr_select_order",
    "kind": "negative",
    "expected_rollup": "GAP",
    "lever_class": "backend_coloring",
    "ground_truth_diff": "@@ fn @@\n# r24-27 vs r25-28 select-order rotation; no zero-cost source lever\n",
    "note": "equal-count window rotation; tooling MUST score GAP."
  }
]
```

```python
# tools/melee-agent/src/backtest/fixtures.py
from __future__ import annotations

import json
from pathlib import Path

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "tests" / "backtest" / "fixtures" / "calibration.json"
)


def load_calibration_fixtures() -> list[dict]:
    """Return the committed synthetic calibration cases (positives + negatives)."""
    return json.loads(_FIXTURE_PATH.read_text())
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_fixtures.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/fixtures.py tools/melee-agent/tests/backtest/fixtures/calibration.json tools/melee-agent/tests/backtest/test_fixtures.py
git commit -m "feat(backtest): synthetic two-sided calibration fixtures"
```

---

## Milestone 1 — Corpus construction

Produces: `melee-agent backtest build-corpus` that enumerates verified small/singular match commits, classifies and labels them, and stores `Case` rows.

### Task 1.1: Resolve a function to its unit/file via report.json

**Files:**
- Create: `tools/melee-agent/src/backtest/corpus.py`
- Test: `tools/melee-agent/tests/backtest/test_corpus_resolve.py`

**Interfaces:**
- Produces: `resolve_function_unit(report: dict, function: str) -> tuple[str, str] | None` returning `(unit_name, file_path)` where `file_path = "src/" + unit_name.removeprefix("main/") + ".c"`. Returns `None` if the function isn't in the report.

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_corpus_resolve.py
from src.backtest.corpus import resolve_function_unit

REPORT = {"units": [
    {"name": "main/melee/gr/gricemt", "functions": [{"name": "grIceMt_801F9ACC", "fuzzy_match_percent": 100.0}]},
    {"name": "main/melee/mn/mnmain", "functions": [{"name": "other_fn", "fuzzy_match_percent": 80.0}]},
]}

def test_resolves_unit_and_file():
    assert resolve_function_unit(REPORT, "grIceMt_801F9ACC") == ("main/melee/gr/gricemt", "src/melee/gr/gricemt.c")

def test_missing_function_returns_none():
    assert resolve_function_unit(REPORT, "nope") is None
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_corpus_resolve.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.backtest.corpus'`.

- [ ] **Step 3: Implement `resolve_function_unit`**

```python
# tools/melee-agent/src/backtest/corpus.py
from __future__ import annotations

from typing import Optional


def resolve_function_unit(report: dict, function: str) -> Optional[tuple[str, str]]:
    """Map a function name to (unit_name, src .c path) using build/GALE01/report.json.

    This mirrors tools/checkdiff.py:find_unit_for_function — authoritative, unlike
    symbols.txt (address-only) or splits.txt (range lookups mis-attribute).
    """
    for unit in report.get("units", []):
        for fn in unit.get("functions", []):
            if fn.get("name") == function:
                name = unit["name"]
                return name, "src/" + name.removeprefix("main/") + ".c"
    return None
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_corpus_resolve.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/corpus.py tools/melee-agent/tests/backtest/test_corpus_resolve.py
git commit -m "feat(backtest): resolve function to unit/file via report.json"
```

### Task 1.2: Enumerate candidate match commits via git

**Files:**
- Modify: `tools/melee-agent/src/backtest/corpus.py`
- Test: `tools/melee-agent/tests/backtest/test_corpus_enumerate.py`

**Interfaces:**
- Consumes: a `git_runner` callable `(args: list[str]) -> str` (returns stdout) so tests inject fakes instead of shelling out.
- Produces:
  - `find_match_commit(git_runner, function: str, file: str) -> str | None` — runs `git log --pretty=%H -S <function> -- <file>` and returns the newest (first) full SHA, else `None`.
  - `parent_sha(git_runner, sha: str) -> str` — `git rev-parse <sha>~1`.
  - `commit_author_is_us(git_runner, sha: str, *, me: str = "itsgrimetime") -> bool` — `git log -1 --pretty=%an <sha>` compared case-insensitively to `me`.

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_corpus_enumerate.py
from src.backtest.corpus import find_match_commit, parent_sha, commit_author_is_us

def make_runner(responses):
    def run(args):
        key = " ".join(args)
        for prefix, out in responses.items():
            if key.startswith(prefix):
                return out
        raise AssertionError(f"unexpected git call: {key}")
    return run

def test_find_match_commit_returns_newest():
    run = make_runner({"log --pretty=%H -S grIceMt_801F9ACC": "3ce0722cd\n0badc0de1\n"})
    assert find_match_commit(run, "grIceMt_801F9ACC", "src/melee/gr/gricemt.c") == "3ce0722cd"

def test_find_match_commit_none_when_empty():
    run = make_runner({"log --pretty=%H -S grIceMt_801F9ACC": "\n"})
    assert find_match_commit(run, "grIceMt_801F9ACC", "src/melee/gr/gricemt.c") is None

def test_parent_and_author():
    run = make_runner({"rev-parse 3ce0722cd~1": "13ccea114\n", "log -1 --pretty=%an 3ce0722cd": "Some Contributor\n"})
    assert parent_sha(run, "3ce0722cd") == "13ccea114"
    assert commit_author_is_us(run, "3ce0722cd", me="itsgrimetime") is False
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_corpus_enumerate.py -q`
Expected: FAIL — `ImportError: cannot import name 'find_match_commit'`.

- [ ] **Step 3: Implement (append to `corpus.py`)**

```python
import subprocess
from typing import Callable

GitRunner = Callable[[list], str]


def default_git_runner(repo_root: str) -> GitRunner:
    def run(args: list) -> str:
        return subprocess.run(
            ["git", "-C", repo_root, *args],
            check=True, capture_output=True, text=True,
        ).stdout
    return run


def find_match_commit(git_runner: GitRunner, function: str, file: str) -> Optional[str]:
    """Newest commit that changed the symbol in its file (pickaxe). None if none."""
    out = git_runner(["log", "--pretty=%H", "-S", function, "--", file]).strip()
    return out.splitlines()[0].strip() if out else None


def parent_sha(git_runner: GitRunner, sha: str) -> str:
    return git_runner(["rev-parse", f"{sha}~1"]).strip()


def commit_author_is_us(git_runner: GitRunner, sha: str, *, me: str = "itsgrimetime") -> bool:
    return git_runner(["log", "-1", "--pretty=%an", sha]).strip().lower() == me.lower()
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_corpus_enumerate.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/corpus.py tools/melee-agent/tests/backtest/test_corpus_enumerate.py
git commit -m "feat(backtest): git-based match-commit enumeration"
```

### Task 1.3: Small/singular diff filter + per-function hunk extraction

**Files:**
- Create: `tools/melee-agent/src/backtest/diffutil.py`
- Test: `tools/melee-agent/tests/backtest/test_diffutil.py`

**Interfaces:**
- Consumes: a `git_runner`.
- Produces:
  - `function_diff(git_runner, c_sha: str, file: str) -> str` — `git show <c_sha> -- <file>` (the unified diff for that file at the commit).
  - `diff_stats(diff: str) -> dict` — `{"added": int, "removed": int, "hunks": int, "files": int}` parsed from a unified diff.
  - `is_small_singular(diff: str, *, max_changed_lines: int = 30, max_hunks: int = 2, single_file: bool = True) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_diffutil.py
from src.backtest.diffutil import diff_stats, is_small_singular

DIFF = """diff --git a/src/melee/gr/gricemt.c b/src/melee/gr/gricemt.c
--- a/src/melee/gr/gricemt.c
+++ b/src/melee/gr/gricemt.c
@@ -10,3 +10,3 @@ void f(void) {
-    int x = 1;
+    u8 x = 1;
"""

def test_diff_stats():
    s = diff_stats(DIFF)
    assert s == {"added": 1, "removed": 1, "hunks": 1, "files": 1}

def test_is_small_singular_true():
    assert is_small_singular(DIFF) is True

def test_is_small_singular_false_when_too_big():
    big = DIFF + "".join(f"+line{i}\n" for i in range(40))
    assert is_small_singular(big) is False
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_diffutil.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `diffutil.py`**

```python
# tools/melee-agent/src/backtest/diffutil.py
from __future__ import annotations


def function_diff(git_runner, c_sha: str, file: str) -> str:
    return git_runner(["show", c_sha, "--", file])


def diff_stats(diff: str) -> dict:
    added = removed = hunks = files = 0
    for line in diff.splitlines():
        if line.startswith("@@"):
            hunks += 1
        elif line.startswith("+++ "):
            files += 1
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {"added": added, "removed": removed, "hunks": hunks, "files": files}


def is_small_singular(diff: str, *, max_changed_lines: int = 30,
                      max_hunks: int = 2, single_file: bool = True) -> bool:
    s = diff_stats(diff)
    if single_file and s["files"] != 1:
        return False
    if s["hunks"] > max_hunks:
        return False
    return (s["added"] + s["removed"]) <= max_changed_lines
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_diffutil.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/diffutil.py tools/melee-agent/tests/backtest/test_diffutil.py
git commit -m "feat(backtest): small/singular diff filter + stats"
```

### Task 1.4: Lever classifier

**Files:**
- Create: `tools/melee-agent/src/backtest/levers.py`
- Test: `tools/melee-agent/tests/backtest/test_levers.py`

**Interfaces:**
- Produces: `classify_lever(diff: str) -> str` returning a member of `LEVER_CLASSES`. Rule-based, ordered; falls back to `"other"`. (An LLM refinement pass is out of scope here; the rule classifier is the deterministic baseline and is what calibration fixtures assert against.)

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_levers.py
from src.backtest.levers import classify_lever
from src.backtest.types import LEVER_CLASSES

def test_retype_detected():
    d = "@@\n-    int mode = get();\n+    u8 mode = get();\n"
    assert classify_lever(d) == "retype"

def test_literal_vs_named_detected():
    d = "@@\n-    foo(name_str);\n+    foo(0.0f);\n"
    assert classify_lever(d) == "literal_vs_named"

def test_unknown_is_other():
    assert classify_lever("@@\n-    a();\n+    b();\n") == "other"

def test_always_in_vocabulary():
    assert classify_lever("@@\n+x\n") in LEVER_CLASSES
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_levers.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `levers.py`**

```python
# tools/melee-agent/src/backtest/levers.py
from __future__ import annotations

import re

from .types import LEVER_CLASSES

_TYPE_TOKENS = r"(?:u8|s8|u16|s16|u32|s32|int|unsigned|char|short|long|float|double|bool)"
# (added_line, removed_line) pair predicates, evaluated against the union of changed lines.
_RETYPE = re.compile(rf"^[+-]\s*{_TYPE_TOKENS}\b")
_FLOAT_LIT = re.compile(r"[-+]?\d+\.\d+f?\b")
_DECL_INIT = re.compile(r"^\+\s*\w[\w ]*\b\w+\s*=")


def classify_lever(diff: str) -> str:
    added = [l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    removed = [l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
    changed = added + removed

    # retype: same identifier reappears with a different leading type token
    if any(_RETYPE.match(l) for l in added) and any(_RETYPE.match(l) for l in removed):
        return "retype"
    # literal_vs_named: a named identifier arg replaced by a numeric/float literal (or vice versa)
    if any(_FLOAT_LIT.search(l) for l in added) != any(_FLOAT_LIT.search(l) for l in removed):
        return "literal_vs_named"
    # hoist_to_local / embedded_assign_temp: a new local decl-with-initializer appears
    if any(_DECL_INIT.match(l) for l in added) and not removed:
        return "hoist_to_local"
    if "for (" in " ".join(added) and "for (" in " ".join(removed):
        # counter rename / count-down heuristic
        if any("--" in l for l in added) or any("--" in l for l in removed):
            return "count_down_or_compare_reuse"
    if any("inline" in l for l in changed):
        return "inline_arg_or_schedule"
    if any(re.search(r"->\s*\w+|\.\w+\s*=", l) for l in added) and any("struct" in l for l in changed):
        return "struct_overlay"
    result = "other"
    assert result in LEVER_CLASSES
    return result
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_levers.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/levers.py tools/melee-agent/tests/backtest/test_levers.py
git commit -m "feat(backtest): rule-based lever classifier"
```

### Task 1.5: In-corpus determination (contamination control)

**Files:**
- Create: `tools/melee-agent/src/backtest/provenance.py`
- Test: `tools/melee-agent/tests/backtest/test_provenance.py`

**Interfaces:**
- Produces:
  - `weighted_jaccard(candidate: dict, pattern: dict) -> float` — port of `mismatch_db/backfill.py:773 _compute_similarity` (opcodes 0.30, categories 0.20, name-words 0.30, signal-types 0.20, normalized by active weights).
  - `is_in_corpus(candidate: dict, all_patterns: list[dict], *, threshold: float = 0.5) -> bool` — max weighted_jaccard ≥ threshold.
  - `diff_to_feature_vector(diff: str, lever_class: str) -> dict` — reduces a diff to `{"opcodes": [], "categories": [lever_class-derived], "name": "", "signals": []}` (best-effort; opcodes empty for source diffs, so the practical signal is category + name overlap — documented limitation).

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_provenance.py
from src.backtest.provenance import weighted_jaccard, is_in_corpus

PATTERNS = [
    {"id": "u8-mask", "name": "u8 parameter mask clrlwi", "opcodes": ["clrlwi"],
     "categories": ["register", "type"], "signals": [{"type": "opcode_mismatch"}]},
]

def test_exact_name_overlap_scores_high():
    cand = {"name": "u8 parameter mask clrlwi", "opcodes": ["clrlwi"],
            "categories": ["register", "type"], "signals": [{"type": "opcode_mismatch"}]}
    assert weighted_jaccard(cand, PATTERNS[0]) > 0.9
    assert is_in_corpus(cand, PATTERNS) is True

def test_unrelated_is_held_out():
    cand = {"name": "frame slot rotation", "opcodes": [],
            "categories": ["frame"], "signals": [{"type": "register"}]}
    assert is_in_corpus(cand, PATTERNS, threshold=0.5) is False
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_provenance.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `provenance.py`**

```python
# tools/melee-agent/src/backtest/provenance.py
from __future__ import annotations


def _jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return (len(a & b) / len(a | b)) if (a | b) else 0.0


def weighted_jaccard(candidate: dict, pattern: dict) -> float:
    """Port of mismatch_db.backfill._compute_similarity (weights: opcodes .3,
    categories .2, name-words .3, signal-types .2; normalized by active weights)."""
    score = 0.0
    weights = 0.0
    if candidate.get("opcodes") and pattern.get("opcodes"):
        score += 0.30 * _jaccard(candidate["opcodes"], pattern["opcodes"]); weights += 0.30
    if candidate.get("categories") and pattern.get("categories"):
        score += 0.20 * _jaccard(candidate["categories"], pattern["categories"]); weights += 0.20
    if candidate.get("name") and pattern.get("name"):
        score += 0.30 * _jaccard(candidate["name"].lower().split(),
                                 pattern["name"].lower().split()); weights += 0.30
    c_types = {s.get("type") for s in candidate.get("signals", [])}
    p_types = {s.get("type") for s in pattern.get("signals", [])}
    if c_types and p_types:
        score += 0.20 * _jaccard(c_types, p_types); weights += 0.20
    return score / weights if weights else 0.0


def is_in_corpus(candidate: dict, all_patterns: list, *, threshold: float = 0.5) -> bool:
    return any(weighted_jaccard(candidate, p) >= threshold for p in all_patterns)


def diff_to_feature_vector(diff: str, lever_class: str) -> dict:
    # Source diffs carry no opcodes; category derives from lever_class, name from changed identifiers.
    cat_map = {
        "retype": ["type", "register"], "literal_vs_named": ["value", "float"],
        "backend_coloring": ["register", "ceiling"], "decl_reorder": ["register"],
        "struct_overlay": ["struct", "data-layout"], "inline_arg_or_schedule": ["inline"],
    }
    names = " ".join(
        tok for l in diff.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))
        for tok in l[1:].split() if tok.isidentifier()
    )
    return {"opcodes": [], "categories": cat_map.get(lever_class, [lever_class]),
            "name": names, "signals": []}
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_provenance.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/provenance.py tools/melee-agent/tests/backtest/test_provenance.py
git commit -m "feat(backtest): in-corpus/held-out determination via weighted-Jaccard port"
```

> **Note for the implementer:** the live pattern list comes from `melee-agent mismatch list --json` parsed with `json.loads(s, strict=False)` (embedded newlines). The mining-ledger exact-hit check (`TransformMiningStore._ledger_contains`) is wired in Task 1.6's `build-corpus` command, not unit-tested here (it needs the real DB).

### Task 1.6: `build-corpus` subcommand

**Files:**
- Modify: `tools/melee-agent/src/cli/backtest.py`
- Create: `tools/melee-agent/src/backtest/build_corpus.py`
- Test: `tools/melee-agent/tests/backtest/test_build_corpus.py`

**Interfaces:**
- Consumes: `resolve_function_unit`, `find_match_commit`, `parent_sha`, `commit_author_is_us`, `function_diff`, `is_small_singular`, `classify_lever`, `diff_to_feature_vector`, `is_in_corpus`, `Case`.
- Produces: `build_corpus(*, functions: list[str], report: dict, git_runner, patterns: list[dict], score_flip) -> list[Case]`. `score_flip(function, sha) -> tuple[float|None, int|None]` returns `(fuzzy_pct, normalized_diff_lines)` at a commit (injected; real impl in Task 1.7). A `Case` is emitted only if: function resolves, a match commit exists, diff is small/singular, AND the structural flip verifies (`ndl==0` at C and `ndl>0` at C~1) — the confound guard (spec §4.3).
- CLI: `backtest build-corpus --functions-file PATH [--limit N] [--json] [--db PATH]` stores Cases via `BacktestStore` (Task 3.1) and prints a summary.

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_build_corpus.py
from src.backtest.build_corpus import build_corpus

REPORT = {"units": [{"name": "main/melee/gr/gricemt",
                     "functions": [{"name": "grIceMt_801F9ACC", "fuzzy_match_percent": 100.0}]}]}
DIFF = ("diff --git a/src/melee/gr/gricemt.c b/src/melee/gr/gricemt.c\n"
        "--- a/src/melee/gr/gricemt.c\n+++ b/src/melee/gr/gricemt.c\n"
        "@@ -1,2 +1,2 @@\n-    int x = f();\n+    u8 x = f();\n")

def make_git(c_sha):
    def run(args):
        k = " ".join(args)
        if k.startswith("log --pretty=%H -S"):
            return c_sha + "\n"
        if k.startswith("rev-parse"):
            return "13ccea114000\n"
        if k.startswith("log -1 --pretty=%an"):
            return "Some Contributor\n"
        if k.startswith("show"):
            return DIFF
        raise AssertionError(k)
    return run

def test_emits_case_when_flip_verifies():
    # ndl==0 at C, ndl>0 at C~1 -> verified
    def score_flip(fn, sha):
        return (100.0, 0) if sha.startswith("3ce0722cd") else (99.98, 4)
    cases = build_corpus(functions=["grIceMt_801F9ACC"], report=REPORT,
                         git_runner=make_git("3ce0722cd000"),
                         patterns=[], score_flip=score_flip)
    assert len(cases) == 1
    c = cases[0]
    assert c.lever_class == "retype" and c.provenance == "held_out"
    assert c.author == "other" and c.baseline_ndl == 4 and c.target_ndl_is_zero

def test_drops_case_when_flip_does_not_verify():
    # ndl>0 at C as well -> the in-function hunk is NOT the lever (confound) -> dropped
    def score_flip(fn, sha):
        return (99.0, 5)
    cases = build_corpus(functions=["grIceMt_801F9ACC"], report=REPORT,
                         git_runner=make_git("3ce0722cd000"),
                         patterns=[], score_flip=score_flip)
    assert cases == []
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_build_corpus.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `build_corpus.py`** (`Case.target_ndl` and `Case.target_ndl_is_zero` are already defined in Task 0.2)

```python
# tools/melee-agent/src/backtest/build_corpus.py
from __future__ import annotations

from .corpus import resolve_function_unit, find_match_commit, parent_sha, commit_author_is_us
from .diffutil import function_diff, is_small_singular
from .levers import classify_lever
from .provenance import diff_to_feature_vector, is_in_corpus
from .types import Case


def build_corpus(*, functions, report, git_runner, patterns, score_flip,
                 max_changed_lines=30) -> list:
    cases: list[Case] = []
    for fn in functions:
        resolved = resolve_function_unit(report, fn)
        if not resolved:
            continue
        unit, file = resolved
        c_sha = find_match_commit(git_runner, fn, file)
        if not c_sha:
            continue
        cprev = parent_sha(git_runner, c_sha)
        diff = function_diff(git_runner, c_sha, file)
        if not is_small_singular(diff, max_changed_lines=max_changed_lines):
            continue
        # Confound guard (spec §4.3): structural flip must be real and attributable.
        c_pct, c_ndl = score_flip(fn, c_sha)
        p_pct, p_ndl = score_flip(fn, cprev)
        if c_ndl != 0 or (p_ndl is None) or p_ndl <= 0:
            continue  # not a genuine structural flip -> drop (mislabeled / header/caller lever)
        lever = classify_lever(diff)
        feat = diff_to_feature_vector(diff, lever)
        provenance = "in_corpus" if is_in_corpus(feat, patterns) else "held_out"
        cases.append(Case(
            function=fn, c_sha=c_sha, cprev_sha=cprev, unit=unit, file=file,
            ground_truth_diff=diff, lever_locus="in_function",
            author="us" if commit_author_is_us(git_runner, c_sha) else "other",
            provenance=provenance, lever_class=lever,
            baseline_pct=p_pct, baseline_ndl=p_ndl, target_pct=c_pct, target_ndl=c_ndl,
        ))
    return cases
```

Add the CLI subcommand to `src/cli/backtest.py`:

```python
@backtest_app.command("build-corpus")
def build_corpus_cmd(
    functions_file: Annotated[Path, typer.Option("--functions-file", help="One function name per line.")],
    limit: Annotated[int, typer.Option("--limit")] = 0,
    db: Annotated[Optional[Path], typer.Option("--db")] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Enumerate verified small/singular match commits into the backtest store."""
    from src.backtest.run import build_and_store_corpus  # Task 1.7
    summary = build_and_store_corpus(functions_file=functions_file, limit=limit, db=db)
    typer.echo(_json.dumps(summary) if json_out else f"corpus: {summary['stored']} cases")
```

(`Path`, `Optional` imports added at the top of `backtest.py`.)

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_build_corpus.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A tools/melee-agent/src/backtest tools/melee-agent/src/cli/backtest.py tools/melee-agent/tests/backtest/test_build_corpus.py
git commit -m "feat(backtest): corpus builder with structural-flip confound guard"
```

### Task 1.7: Real flip-scorer + corpus wiring (`run.py`)

**Files:**
- Create: `tools/melee-agent/src/backtest/run.py`
- Test: `tools/melee-agent/tests/backtest/test_run_scorer.py`

**Interfaces:**
- Consumes: `BacktestStore` (Task 3.1 — this task may land after 3.1; if executing strictly in order, stub the store call behind a flag and complete in 3.1).
- Produces:
  - `run_checkdiff_at(repo_root: str, function: str, *, timeout: float = 600.0) -> dict` — the verbatim checkdiff invocation (Global Constraints), returns parsed JSON.
  - `score_at_commit(main_repo: str, function: str, sha: str, *, scratch_root: Path, timeout: float = 600.0) -> tuple[float|None, int|None]` — creates a detached worktree at `sha` (C is intentionally present here — this is harness-side ground truth, not blind), `worktree-doctor --fix`, runs checkdiff, returns `(fuzzy_match_percent, normalized_diff_lines)`, removes the worktree in `finally`.
  - `build_and_store_corpus(*, functions_file, limit, db) -> dict`.

- [ ] **Step 1: Write the failing test** (mock subprocess; do not build)

```python
# tools/melee-agent/tests/backtest/test_run_scorer.py
import json
from src.backtest import run as R

def test_run_checkdiff_at_parses_json(monkeypatch):
    payload = {"function": "f", "match": True, "fuzzy_match_percent": 100.0,
               "classification": {"structural_truth_gate": {"normalized_diff_lines": 0, "status": "structural-match"}}}
    class P: returncode = 0; stdout = json.dumps(payload); stderr = ""
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: P())
    out = R.run_checkdiff_at("/repo", "f")
    assert out["fuzzy_match_percent"] == 100.0

def test_run_checkdiff_uses_required_flags_and_env(monkeypatch):
    seen = {}
    class P: returncode = 1; stdout = '{"fuzzy_match_percent": 99.9, "classification": {"structural_truth_gate": {"normalized_diff_lines": 3}}}'; stderr = ""
    def fake_run(cmd, **kw):
        seen["cmd"] = cmd; seen["env"] = kw["env"]; seen["cwd"] = kw["cwd"]; return P()
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    R.run_checkdiff_at("/repo", "grIceMt_801F9ACC")
    assert seen["cmd"][1:] == ["tools/checkdiff.py", "grIceMt_801F9ACC", "--format", "json", "--no-tty"]
    assert seen["env"]["CHECKDIFF_NO_LOCK"] == "1" and seen["env"]["CHECKDIFF_NO_FINGERPRINT"] == "1"
    assert seen["cwd"] == "/repo"
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_run_scorer.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `run.py`** (the checkdiff runner mirrors `inline_leverage/run.py:254`)

```python
# tools/melee-agent/src/backtest/run.py
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MAIN_REPO = "/Users/mike/code/melee"


def _structural_ndl(payload: dict):
    gate = (payload.get("classification") or {}).get("structural_truth_gate") or {}
    return gate.get("normalized_diff_lines")


def run_checkdiff_at(repo_root: str, function: str, *, timeout: float = 600.0) -> dict:
    env = os.environ.copy()
    env["CHECKDIFF_NO_LOCK"] = "1"
    env["CHECKDIFF_NO_FINGERPRINT"] = "1"
    proc = subprocess.run(
        [sys.executable, "tools/checkdiff.py", function, "--format", "json", "--no-tty"],
        cwd=repo_root, capture_output=True, text=True, timeout=timeout, env=env,
    )
    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    return json.loads(proc.stdout)


def score_at_commit(main_repo: str, function: str, sha: str, *,
                    scratch_root: Path, timeout: float = 600.0):
    wt = scratch_root / f"at_{sha[:12]}"
    subprocess.run(["git", "-C", main_repo, "worktree", "add", "--detach", str(wt), sha], check=True)
    try:
        subprocess.run([sys.executable, "tools/worktree-doctor.py", "--fix"], cwd=str(wt), check=True)
        payload = run_checkdiff_at(str(wt), function, timeout=timeout)
        return payload.get("fuzzy_match_percent"), _structural_ndl(payload)
    finally:
        subprocess.run(["git", "-C", main_repo, "worktree", "remove", "--force", str(wt)], check=False)


def build_and_store_corpus(*, functions_file: Path, limit: int, db):
    from .build_corpus import build_corpus
    from .corpus import default_git_runner
    from .store import BacktestStore  # Task 3.1
    import subprocess as sp

    functions = [l.strip() for l in Path(functions_file).read_text().splitlines() if l.strip()]
    if limit:
        functions = functions[:limit]
    report = json.loads(Path(MAIN_REPO, "build/GALE01/report.json").read_text())
    patterns = _load_patterns()
    scratch_root = Path(MAIN_REPO) / "build" / "backtest" / "ground_truth"
    scratch_root.mkdir(parents=True, exist_ok=True)

    def score_flip(fn, sha):
        return score_at_commit(MAIN_REPO, fn, sha, scratch_root=scratch_root)

    cases = build_corpus(functions=functions, report=report,
                         git_runner=default_git_runner(MAIN_REPO),
                         patterns=patterns, score_flip=score_flip)
    store = BacktestStore(db)
    store.ensure_schema()
    for c in cases:
        store.insert_case(c)
    return {"considered": len(functions), "stored": len(cases),
            "held_out": sum(1 for c in cases if c.provenance == "held_out")}


def _load_patterns() -> list:
    try:
        out = subprocess.run(["melee-agent", "mismatch", "list", "--json"],
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out, strict=False)
    except Exception:
        return []
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_run_scorer.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/run.py tools/melee-agent/tests/backtest/test_run_scorer.py
git commit -m "feat(backtest): checkdiff runner + ground-truth flip scorer"
```

---

## Milestone 2 — Blind sandbox

Produces: `sandbox.py` — build a C~1 sandbox with the answer commit provably absent, with a build that scores the known pre-match baseline.

### Task 2.1: Build sandbox with provable answer-absence + leak probe

**Files:**
- Create: `tools/melee-agent/src/backtest/sandbox.py`
- Test: `tools/melee-agent/tests/backtest/test_sandbox.py`

**Interfaces:**
- Produces:
  - `assert_commit_absent(repo: str, c_sha: str) -> None` — raises `LeakError` unless `git cat-file -e <c_sha>^{commit}` fails AND `<c_sha>` not in `git rev-list --all`.
  - `build_sandbox(*, main_repo: str, c_sha: str, cprev_sha: str, dest: Path) -> Path` — empty-repo `git init` + `git fetch --depth 1 origin <cprev>` + checkout FETCH_HEAD + fetch `master` ref + `assert_commit_absent` + symlink DOL. Returns `dest`.
  - `teardown_sandbox(dest: Path) -> None`.
  - `class LeakError(RuntimeError)`.

- [ ] **Step 1: Write the failing test** (inject a fake runner; assert command sequence + leak logic)

```python
# tools/melee-agent/tests/backtest/test_sandbox.py
import pytest
from src.backtest.sandbox import assert_commit_absent, LeakError

class FakeProc:
    def __init__(self, rc, out=""): self.returncode = rc; self.stdout = out; self.stderr = ""

def test_assert_commit_absent_passes_when_object_missing(monkeypatch):
    import src.backtest.sandbox as S
    def fake_run(cmd, **kw):
        if "cat-file" in cmd: return FakeProc(1)            # object absent -> good
        if "rev-list" in cmd: return FakeProc(0, "13ccea114\n")  # C not present
        return FakeProc(0)
    monkeypatch.setattr(S.subprocess, "run", fake_run)
    assert_commit_absent("/sandbox", "3ce0722cd" * 4 + "abcd")  # no raise

def test_assert_commit_absent_raises_when_present(monkeypatch):
    import src.backtest.sandbox as S
    def fake_run(cmd, **kw):
        if "cat-file" in cmd: return FakeProc(0)            # object PRESENT -> leak
        return FakeProc(0)
    monkeypatch.setattr(S.subprocess, "run", fake_run)
    with pytest.raises(LeakError):
        assert_commit_absent("/sandbox", "3ce0722cd" * 4 + "abcd")
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_sandbox.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `sandbox.py`**

```python
# tools/melee-agent/src/backtest/sandbox.py
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

MAIN_REPO_DOL = "/Users/mike/code/melee/orig/GALE01/sys/main.dol"


class LeakError(RuntimeError):
    """Raised when the answer commit is reachable inside a 'blind' sandbox."""


def _git(repo: str, args: list, check=True):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=check)


def assert_commit_absent(repo: str, c_sha: str) -> None:
    cat = subprocess.run(["git", "-C", repo, "cat-file", "-e", f"{c_sha}^{{commit}}"],
                         capture_output=True, text=True)
    if cat.returncode == 0:
        raise LeakError(f"answer commit {c_sha} is present in sandbox object store")
    revs = subprocess.run(["git", "-C", repo, "rev-list", "--all"],
                          capture_output=True, text=True).stdout
    if c_sha in revs:
        raise LeakError(f"answer commit {c_sha} is reachable from a ref in sandbox")


def build_sandbox(*, main_repo: str, c_sha: str, cprev_sha: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    _git(str(dest), ["init", "-q"])
    _git(str(dest), ["remote", "add", "origin", f"file://{main_repo}"])
    _git(str(dest), ["fetch", "-q", "--depth", "1", "origin", cprev_sha])
    _git(str(dest), ["checkout", "-q", "FETCH_HEAD"])
    # so worktree-doctor restore_from_master can resolve (does not reach C)
    _git(str(dest), ["fetch", "-q", "--depth", "1", "origin", "master:refs/heads/master"], check=False)
    assert_commit_absent(str(dest), c_sha)
    dol = dest / "orig" / "GALE01" / "sys" / "main.dol"
    dol.parent.mkdir(parents=True, exist_ok=True)
    if not dol.exists():
        dol.symlink_to(MAIN_REPO_DOL)
    return dest


def teardown_sandbox(dest: Path) -> None:
    shutil.rmtree(dest, ignore_errors=True)
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_sandbox.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/sandbox.py tools/melee-agent/tests/backtest/test_sandbox.py
git commit -m "feat(backtest): blind sandbox with provable answer-absence leak probe"
```

### Task 2.2: Integration smoke — build a real sandbox + score baseline

This is an **integration test, marked slow** (it builds). It is the live proof that the sandbox + leak probe + baseline scoring work end-to-end. Uses the verified anchor `grIceMt_801F9ACC` / `C=3ce0722cd`.

**Files:**
- Test: `tools/melee-agent/tests/backtest/test_sandbox_integration.py`

- [ ] **Step 1: Write the test (skipped unless `BACKTEST_SLOW=1`)**

```python
# tools/melee-agent/tests/backtest/test_sandbox_integration.py
import os, json, subprocess, sys
import pytest
from pathlib import Path
from src.backtest.sandbox import build_sandbox, teardown_sandbox
from src.backtest.run import run_checkdiff_at, _structural_ndl

pytestmark = pytest.mark.skipif(os.environ.get("BACKTEST_SLOW") != "1",
                                reason="set BACKTEST_SLOW=1 to run the building integration test")

def test_baseline_scores_below_match(tmp_path):
    main = "/Users/mike/code/melee"
    c = subprocess.run(["git", "-C", main, "rev-parse", "3ce0722cd"], capture_output=True, text=True).stdout.strip()
    cprev = subprocess.run(["git", "-C", main, "rev-parse", "3ce0722cd~1"], capture_output=True, text=True).stdout.strip()
    sb = build_sandbox(main_repo=main, c_sha=c, cprev_sha=cprev, dest=tmp_path / "sb")
    try:
        subprocess.run([sys.executable, "tools/worktree-doctor.py", "--fix"], cwd=str(sb), check=True)
        payload = run_checkdiff_at(str(sb), "grIceMt_801F9ACC")
        assert payload["match"] is False           # pre-match state
        assert _structural_ndl(payload) > 0         # structurally not yet matched
    finally:
        teardown_sandbox(sb)
```

- [ ] **Step 2: Run it (opt-in)**

Run: `cd tools/melee-agent && BACKTEST_SLOW=1 python -m pytest tests/backtest/test_sandbox_integration.py -q`
Expected: PASS (takes minutes — full build). Without `BACKTEST_SLOW=1` it is skipped.

- [ ] **Step 3: Commit**

```bash
git add tools/melee-agent/tests/backtest/test_sandbox_integration.py
git commit -m "test(backtest): slow sandbox+baseline integration smoke"
```

---

## Milestone 3 — Store, cheap tiers, scoring

### Task 3.1: `BacktestStore`

**Files:**
- Create: `tools/melee-agent/src/backtest/store.py`
- Test: `tools/melee-agent/tests/backtest/test_store.py`

**Interfaces:** (mirrors `inline_leverage/store.py`)
- Produces: `class BacktestStore(db_path: Path | None = None)` with `ensure_schema()`, `insert_case(case: Case)`, `get_case(case_id) -> dict | None`, `list_cases(provenance: str | None = None) -> list[dict]`, `upsert_result(result: CaseResult)`, `results() -> list[dict]`. Default path `~/.config/decomp-me/backtest_results.db`. Tables below.

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_store.py
from src.backtest.store import BacktestStore
from src.backtest.types import Case, CaseResult

def make_case():
    return Case(function="f", c_sha="a"*40, cprev_sha="b"*40, unit="main/melee/gr/g",
                file="src/melee/gr/g.c", ground_truth_diff="@@", lever_locus="in_function",
                author="other", provenance="held_out", lever_class="retype",
                baseline_pct=99.0, baseline_ndl=4, target_pct=100.0, target_ndl=0)

def test_roundtrip_case_and_result(tmp_path):
    s = BacktestStore(tmp_path / "bt.db"); s.ensure_schema()
    c = make_case(); s.insert_case(c)
    got = s.get_case(c.case_id)
    assert got["function"] == "f" and got["provenance"] == "held_out"
    s.upsert_result(CaseResult(case_id=c.case_id, advisory="names-lever", rollup="PARTIAL", evidence={"x": 1}))
    rows = s.results()
    assert rows[0]["advisory"] == "names-lever" and rows[0]["rollup"] == "PARTIAL"

def test_list_filter_by_provenance(tmp_path):
    s = BacktestStore(tmp_path / "bt.db"); s.ensure_schema()
    s.insert_case(make_case())
    assert len(s.list_cases(provenance="held_out")) == 1
    assert s.list_cases(provenance="in_corpus") == []
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_store.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `store.py`**

```python
# tools/melee-agent/src/backtest/store.py
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from .types import Case, CaseResult

DEFAULT_DB_PATH = Path.home() / ".config" / "decomp-me" / "backtest_results.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_cases (
    case_id TEXT PRIMARY KEY,
    function TEXT NOT NULL, c_sha TEXT NOT NULL, cprev_sha TEXT NOT NULL,
    unit TEXT, file TEXT, ground_truth_diff TEXT, lever_locus TEXT,
    author TEXT, provenance TEXT, lever_class TEXT,
    baseline_pct REAL, baseline_ndl INTEGER, target_pct REAL, target_ndl INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cases_provenance ON backtest_cases(provenance);
CREATE INDEX IF NOT EXISTS idx_cases_lever ON backtest_cases(lever_class);
CREATE TABLE IF NOT EXISTS backtest_results (
    case_id TEXT PRIMARY KEY REFERENCES backtest_cases(case_id) ON DELETE CASCADE,
    advisory TEXT, generative TEXT, agent TEXT, rollup TEXT,
    evidence JSON, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class BacktestStore:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def ensure_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def insert_case(self, case: Case) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO backtest_cases
               (case_id, function, c_sha, cprev_sha, unit, file, ground_truth_diff,
                lever_locus, author, provenance, lever_class, baseline_pct, baseline_ndl,
                target_pct, target_ndl)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (case.case_id, case.function, case.c_sha, case.cprev_sha, case.unit, case.file,
             case.ground_truth_diff, case.lever_locus, case.author, case.provenance,
             case.lever_class, case.baseline_pct, case.baseline_ndl, case.target_pct,
             case.target_ndl),
        )
        self.conn.commit()

    def get_case(self, case_id: str):
        row = self.conn.execute("SELECT * FROM backtest_cases WHERE case_id=?", (case_id,)).fetchone()
        return dict(row) if row else None

    def list_cases(self, provenance: Optional[str] = None) -> list:
        if provenance:
            rows = self.conn.execute("SELECT * FROM backtest_cases WHERE provenance=?", (provenance,)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM backtest_cases").fetchall()
        return [dict(r) for r in rows]

    def upsert_result(self, result: CaseResult) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO backtest_results
               (case_id, advisory, generative, agent, rollup, evidence)
               VALUES (?,?,?,?,?,?)""",
            (result.case_id, result.advisory, result.generative, result.agent,
             result.rollup, json.dumps(result.evidence)),
        )
        self.conn.commit()

    def results(self) -> list:
        return [dict(r) for r in self.conn.execute("SELECT * FROM backtest_results").fetchall()]
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_store.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/store.py tools/melee-agent/tests/backtest/test_store.py
git commit -m "feat(backtest): BacktestStore SQLite (cases + results)"
```

### Task 3.2: Generative scoring + verdict

**Files:**
- Create: `tools/melee-agent/src/backtest/score.py`
- Test: `tools/melee-agent/tests/backtest/test_score.py`

**Interfaces:**
- Produces:
  - `generative_verdict(*, baseline_ndl: int, baseline_pct: float, best_ndl: int | None, best_pct: float | None) -> GenerativeVerdict` — `byte-match-reproduced` iff `best_ndl == 0`; else `improved-toward` iff `best_ndl < baseline_ndl` or `best_pct > baseline_pct + 0.05`; else `no-progress` (also when `best_ndl is None`, i.e. timeout/failed).
  - `rollup_verdict(advisory, generative, agent) -> CaseVerdict` — `SOLVED-BY-TOOLING` iff `generative == "byte-match-reproduced"` or `agent == "matched"`; `PARTIAL` iff `advisory == "names-lever"` or `generative == "improved-toward"` or `agent == "improved"`; else `GAP`.

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_score.py
from src.backtest.score import generative_verdict, rollup_verdict

def test_byte_match():
    assert generative_verdict(baseline_ndl=4, baseline_pct=99.0, best_ndl=0, best_pct=100.0) == "byte-match-reproduced"

def test_improved():
    assert generative_verdict(baseline_ndl=4, baseline_pct=99.0, best_ndl=2, best_pct=99.4) == "improved-toward"

def test_no_progress_on_timeout():
    assert generative_verdict(baseline_ndl=4, baseline_pct=99.0, best_ndl=None, best_pct=None) == "no-progress"

def test_rollup():
    assert rollup_verdict("silent-or-wrong", "byte-match-reproduced", None) == "SOLVED-BY-TOOLING"
    assert rollup_verdict("names-lever", "no-progress", None) == "PARTIAL"
    assert rollup_verdict("silent-or-wrong", "no-progress", "stuck") == "GAP"
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_score.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `score.py`**

```python
# tools/melee-agent/src/backtest/score.py
from __future__ import annotations

from typing import Optional


def generative_verdict(*, baseline_ndl: int, baseline_pct: float,
                       best_ndl: Optional[int], best_pct: Optional[float]) -> str:
    if best_ndl == 0:
        return "byte-match-reproduced"
    if best_ndl is None:
        return "no-progress"
    if best_ndl < baseline_ndl or (best_pct is not None and best_pct > baseline_pct + 0.05):
        return "improved-toward"
    return "no-progress"


def rollup_verdict(advisory: Optional[str], generative: Optional[str],
                   agent: Optional[str]) -> str:
    if generative == "byte-match-reproduced" or agent == "matched":
        return "SOLVED-BY-TOOLING"
    if advisory == "names-lever" or generative == "improved-toward" or agent == "improved":
        return "PARTIAL"
    return "GAP"
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_score.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/score.py tools/melee-agent/tests/backtest/test_score.py
git commit -m "feat(backtest): generative + rollup verdict scoring"
```

### Task 3.3: Tier runners (advisory capture + generative search)

**Files:**
- Create: `tools/melee-agent/src/backtest/tiers.py`
- Test: `tools/melee-agent/tests/backtest/test_tiers.py`

**Interfaces:**
- Consumes: a `cli_runner(args: list[str], *, cwd: str, timeout: float) -> tuple[int, str, str]` injected so tests fake subprocess. Default impl shells `python -m src.cli …` from `tools/melee-agent` with the sandbox repo as the working tree target.
- Produces:
  - `ADVISORY_TOOLS: list[tuple[str, list[str]]]` and `GENERATIVE_TOOLS: list[tuple[str, list[str]]]` — the exact tool argv templates (with `{fn}`/`{unit}` placeholders) from the grounded cheat-sheet. Advisory: `mismatch search`, `debug suggest inlines --json`, `debug inspect diagnose --json`, `opseq --like`, `patterns similar`. Generative: `debug search directed -u {unit} --max-iters 8`, `debug coalesce-search --discover` (via `suggest coalesce --discover`), `debug mutate decl-orders`, `debug search structure --axis decl-order --axis control-flow --json`.
  - `run_advisory(case, *, sandbox: str, cli_runner, budget_s: float = 120) -> dict` — runs each advisory tool, returns `{tool: {"rc": int, "stdout": str}}` (raw; the judge interprets).
  - `run_generative(case, *, sandbox: str, cli_runner, score_fn, budget_s: float = 600, max_iters: int = 8) -> dict` — runs each generative tool with a per-tool wall-clock cap; after each, calls `score_fn(sandbox, case.function)` (current best ndl/pct); returns `{"best_ndl": int|None, "best_pct": float|None, "ran": [...], "timed_out": [...]}`. A tool that raises `TimeoutExpired` is recorded in `timed_out` and never stalls the loop.

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_tiers.py
import subprocess
from src.backtest.tiers import run_advisory, run_generative, ADVISORY_TOOLS
from src.backtest.types import Case

def make_case():
    return Case(function="grIceMt_801F9ACC", c_sha="a"*40, cprev_sha="b"*40,
                unit="main/melee/gr/gricemt", file="src/melee/gr/gricemt.c",
                ground_truth_diff="@@", lever_locus="in_function", author="other",
                provenance="held_out", lever_class="retype",
                baseline_pct=99.98, baseline_ndl=4, target_pct=100.0, target_ndl=0)

def test_run_advisory_captures_each_tool():
    calls = []
    def fake_cli(args, *, cwd, timeout):
        calls.append(args); return (0, "Found 1 pattern: u8-mask", "")
    out = run_advisory(make_case(), sandbox="/sb", cli_runner=fake_cli)
    assert len(out) == len(ADVISORY_TOOLS)
    assert all(v["rc"] == 0 for v in out.values())

def test_run_generative_records_timeout_and_best():
    seq = iter([4, 2])  # ndl after tool 1, then tool 2
    def fake_cli(args, *, cwd, timeout):
        if "directed" in " ".join(args):
            raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)
        return (0, "{}", "")
    def score_fn(sb, fn):
        return (99.5, next(seq, 2))
    out = run_generative(make_case(), sandbox="/sb", cli_runner=fake_cli, score_fn=score_fn)
    assert out["best_ndl"] == 2
    assert any("directed" in " ".join(t) for t in out["timed_out"])
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_tiers.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `tiers.py`**

```python
# tools/melee-agent/src/backtest/tiers.py
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MELEE_AGENT_DIR = "/Users/mike/code/melee/.claude/worktrees/awesome-lamport-fe4b0b/tools/melee-agent"

# (label, argv template). {fn} and {unit} are substituted. These invoke the CLI under
# test from the worktree (python -m src.cli), pinned per Global Constraints.
ADVISORY_TOOLS = [
    ("mismatch_search", ["debug", "inspect", "explain-diff", "{fn}", "--json"]),
    ("suggest_inlines", ["debug", "suggest", "inlines", "-f", "{fn}", "--json"]),
    ("inspect_diagnose", ["debug", "inspect", "diagnose", "{fn}", "--json"]),
    ("patterns_similar", ["patterns", "similar", "{fn}"]),
]

GENERATIVE_TOOLS = [
    ("search_directed", ["debug", "search", "directed", "-f", "{fn}", "-u", "{unit_short}", "--max-iters", "8"]),
    ("search_structure", ["debug", "search", "structure", "-f", "{fn}",
                          "--axis", "decl-order", "--axis", "control-flow", "--json"]),
    ("mutate_decl_orders", ["debug", "mutate", "decl-orders", "-f", "{fn}"]),
    ("suggest_coalesce", ["debug", "suggest", "coalesce", "-f", "{fn}", "--discover", "--top", "5", "--json"]),
]


def default_cli_runner(args, *, cwd: str, timeout: float):
    """Run the worktree CLI against the sandbox tree. cwd is the sandbox (so report.json
    resolves there); we invoke the pinned CLI via PYTHONPATH to the worktree package root."""
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = MELEE_AGENT_DIR + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run([sys.executable, "-m", "src.cli", *args],
                          cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    return proc.returncode, proc.stdout, proc.stderr


def _subst(template, case):
    short = case.unit.removeprefix("main/")  # e.g. melee/gr/gricemt
    return [t.replace("{fn}", case.function).replace("{unit}", case.unit).replace("{unit_short}", short)
            for t in template]


def run_advisory(case, *, sandbox: str, cli_runner=default_cli_runner, budget_s: float = 120) -> dict:
    out = {}
    for label, template in ADVISORY_TOOLS:
        args = _subst(template, case)
        try:
            rc, stdout, _ = cli_runner(args, cwd=sandbox, timeout=budget_s)
        except subprocess.TimeoutExpired:
            rc, stdout = 124, ""
        out[label] = {"rc": rc, "stdout": stdout[:8000]}
    return out


def run_generative(case, *, sandbox: str, cli_runner=default_cli_runner, score_fn=None,
                   budget_s: float = 600, max_iters: int = 8) -> dict:
    best_ndl = case.baseline_ndl
    best_pct = case.baseline_pct
    ran, timed_out = [], []
    for label, template in GENERATIVE_TOOLS:
        args = _subst(template, case)
        try:
            cli_runner(args, cwd=sandbox, timeout=budget_s)
            ran.append(args)
        except subprocess.TimeoutExpired:
            timed_out.append(args)
            continue
        if score_fn is not None:
            pct, ndl = score_fn(sandbox, case.function)
            if ndl is not None and (best_ndl is None or ndl < best_ndl):
                best_ndl, best_pct = ndl, pct
    return {"best_ndl": best_ndl, "best_pct": best_pct, "ran": ran, "timed_out": timed_out}
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_tiers.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/tiers.py tools/melee-agent/tests/backtest/test_tiers.py
git commit -m "feat(backtest): advisory + generative tier runners with budgets"
```

> **Implementer note:** `MELEE_AGENT_DIR` is hard-coded to the current worktree for the plan; before shipping, replace it with a resolver (walk up from `__file__` to the `tools/melee-agent` dir) so the path isn't worktree-specific. Add a `test_melee_agent_dir_resolves` test asserting the path ends in `tools/melee-agent` and exists.

---

## Milestone 4 — Judge, blind-agent tier, orchestration, calibration gate

### Task 4.1: Advisory judge I/O (label-blinded)

**Files:**
- Create: `tools/melee-agent/src/backtest/judge.py`
- Test: `tools/melee-agent/tests/backtest/test_judge.py`

**Interfaces:**
- Produces:
  - `build_judge_input(case, advisory_outputs: dict) -> dict` — returns `{"function": ..., "ground_truth_diff": ..., "lever_class": ..., "tool_outputs": {...}}` with **`provenance`/`author` deliberately omitted** (M2 label-blinding).
  - `JUDGE_PROMPT: str` — instructs the model to return strict JSON `{"verdict": "names-lever|hints-adjacent|silent-or-wrong", "rationale": str}`, comparing tool outputs to the diff; default to `silent-or-wrong` when nothing references the actual lever.
  - `parse_judge_verdict(text: str) -> AdvisoryVerdict` — robust JSON extraction; raises `ValueError` on an out-of-vocabulary verdict.

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_judge.py
import pytest
from src.backtest.judge import build_judge_input, parse_judge_verdict
from src.backtest.types import Case

def make_case():
    return Case(function="f", c_sha="a"*40, cprev_sha="b"*40, unit="u", file="x.c",
                ground_truth_diff="@@ retype", lever_locus="in_function", author="us",
                provenance="in_corpus", lever_class="retype", baseline_pct=99.0,
                baseline_ndl=4, target_pct=100.0, target_ndl=0)

def test_judge_input_is_label_blinded():
    ji = build_judge_input(make_case(), {"t": {"rc": 0, "stdout": "x"}})
    assert "provenance" not in ji and "author" not in ji
    assert ji["lever_class"] == "retype" and "tool_outputs" in ji

def test_parse_verdict_ok():
    assert parse_judge_verdict('prefix {"verdict": "names-lever", "rationale": "ok"} suffix') == "names-lever"

def test_parse_verdict_rejects_garbage():
    with pytest.raises(ValueError):
        parse_judge_verdict('{"verdict": "totally-made-up"}')
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_judge.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `judge.py`**

```python
# tools/melee-agent/src/backtest/judge.py
from __future__ import annotations

import json
import re

_VALID = {"names-lever", "hints-adjacent", "silent-or-wrong"}

JUDGE_PROMPT = """You are scoring whether a set of tool outputs would lead an engineer to a
specific known source fix, WITHOUT being told the fix in advance by the tools.

You are given: the function name, the ground-truth diff (the fix), the lever class, and the
raw outputs of several advisory tools that were run BLIND (they did not see the fix).

Decide one verdict:
- "names-lever": a tool output explicitly identifies the change in the ground-truth diff
  (the same variable/type/literal/structural move). An engineer reading it would make the fix.
- "hints-adjacent": a tool points at the right region/mechanism but not the specific change.
- "silent-or-wrong": no tool references the actual lever (DEFAULT when uncertain).

Return STRICT JSON only: {"verdict": "<one of the three>", "rationale": "<one sentence>"}.
"""


def build_judge_input(case, advisory_outputs: dict) -> dict:
    return {
        "function": case.function,
        "ground_truth_diff": case.ground_truth_diff,
        "lever_class": case.lever_class,
        "tool_outputs": advisory_outputs,
    }


def parse_judge_verdict(text: str) -> str:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON object in judge output: {text[:200]}")
    verdict = json.loads(m.group(0)).get("verdict")
    if verdict not in _VALID:
        raise ValueError(f"out-of-vocabulary verdict: {verdict!r}")
    return verdict
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_judge.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/judge.py tools/melee-agent/tests/backtest/test_judge.py
git commit -m "feat(backtest): label-blinded advisory judge I/O"
```

### Task 4.2: Escalation selection

**Files:**
- Modify: `tools/melee-agent/src/backtest/score.py`
- Test: `tools/melee-agent/tests/backtest/test_escalation.py`

**Interfaces:**
- Produces: `select_escalation(results: list[dict], cases_by_id: dict, *, control_n: int = 12, seed_token: str = "backtest") -> list[str]` — returns case_ids for the blind-agent tier: all `GAP`/`PARTIAL` from cheap tiers, PLUS up to `control_n` held-out `SOLVED-BY-TOOLING` cases as a control (deterministic selection by sorting on `sha256(seed_token+case_id)` — no RNG, per the workflow no-`Math.random` rule).

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_escalation.py
from src.backtest.score import select_escalation

def test_escalation_includes_gaps_and_control_sample():
    results = [{"case_id": f"c{i}", "rollup": "SOLVED-BY-TOOLING"} for i in range(20)]
    results += [{"case_id": "g1", "rollup": "GAP"}, {"case_id": "p1", "rollup": "PARTIAL"}]
    cases = {f"c{i}": {"provenance": "held_out"} for i in range(20)}
    cases["g1"] = {"provenance": "held_out"}; cases["p1"] = {"provenance": "held_out"}
    sel = select_escalation(results, cases, control_n=5)
    assert "g1" in sel and "p1" in sel
    controls = [cid for cid in sel if cid.startswith("c")]
    assert len(controls) == 5  # capped control sample
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_escalation.py -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement (append to `score.py`)**

```python
import hashlib


def select_escalation(results, cases_by_id, *, control_n: int = 12, seed_token: str = "backtest"):
    must = [r["case_id"] for r in results if r["rollup"] in ("GAP", "PARTIAL")]
    solved_heldout = [
        r["case_id"] for r in results
        if r["rollup"] == "SOLVED-BY-TOOLING"
        and cases_by_id.get(r["case_id"], {}).get("provenance") == "held_out"
    ]
    solved_heldout.sort(key=lambda cid: hashlib.sha256((seed_token + cid).encode()).hexdigest())
    return must + solved_heldout[:control_n]
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_escalation.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/score.py tools/melee-agent/tests/backtest/test_escalation.py
git commit -m "feat(backtest): deterministic blind-agent escalation selection"
```

### Task 4.3: `run --cheap` subcommand (cheap-tier pipeline)

**Files:**
- Modify: `tools/melee-agent/src/cli/backtest.py`, `tools/melee-agent/src/backtest/run.py`
- Test: `tools/melee-agent/tests/backtest/test_run_cheap.py`

**Interfaces:**
- Produces: `run_cheap_tiers(*, store, sandbox_factory, advisory_judge, score_fn, limit=0) -> dict` — for each stored case: build sandbox → build → `run_advisory` → `advisory_judge(case, outputs)` (returns AdvisoryVerdict) → `run_generative` → `generative_verdict` → `rollup_verdict` (agent=None) → `store.upsert_result` → teardown sandbox. Returns counts. `sandbox_factory(case) -> contextmanager[str]` and `advisory_judge`/`score_fn` are injected (tests fake them; the Workflow supplies the real LLM judge).
- CLI: `backtest run --cheap [--limit N] [--db PATH] [--json]`.

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_run_cheap.py
import contextlib
from src.backtest.run import run_cheap_tiers
from src.backtest.store import BacktestStore
from src.backtest.types import Case

def make_case(cid_fn):
    return Case(function=cid_fn, c_sha="a"*40, cprev_sha="b"*40, unit="main/melee/gr/g",
                file="src/melee/gr/g.c", ground_truth_diff="@@", lever_locus="in_function",
                author="other", provenance="held_out", lever_class="retype",
                baseline_pct=99.0, baseline_ndl=4, target_pct=100.0, target_ndl=0)

def test_run_cheap_scores_and_stores(tmp_path):
    s = BacktestStore(tmp_path / "bt.db"); s.ensure_schema()
    s.insert_case(make_case("f1"))

    @contextlib.contextmanager
    def sandbox_factory(case):
        yield "/fake/sb"

    # advisory names the lever; generative reaches byte-match -> SOLVED
    summary = run_cheap_tiers(
        store=s,
        sandbox_factory=sandbox_factory,
        advisory_judge=lambda case, outputs: "names-lever",
        score_fn=lambda sb, fn: (100.0, 0),
        advisory_runner=lambda case, sandbox: {"t": {"rc": 0, "stdout": "x"}},
        generative_runner=lambda case, sandbox, score_fn: {"best_ndl": 0, "best_pct": 100.0, "ran": [], "timed_out": []},
    )
    assert summary["SOLVED-BY-TOOLING"] == 1
    assert s.results()[0]["rollup"] == "SOLVED-BY-TOOLING"
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_run_cheap.py -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement (append to `run.py`)**

```python
def run_cheap_tiers(*, store, sandbox_factory, advisory_judge, score_fn,
                    advisory_runner=None, generative_runner=None, limit: int = 0) -> dict:
    from .tiers import run_advisory, run_generative
    from .score import generative_verdict, rollup_verdict
    from .types import CaseResult, Case

    advisory_runner = advisory_runner or (lambda case, sandbox: run_advisory(case, sandbox=sandbox))
    generative_runner = generative_runner or (
        lambda case, sandbox, score_fn: run_generative(case, sandbox=sandbox, score_fn=score_fn))

    cases = store.list_cases()
    if limit:
        cases = cases[:limit]
    counts = {"SOLVED-BY-TOOLING": 0, "PARTIAL": 0, "GAP": 0}
    for row in cases:
        case = Case(**{k: row[k] for k in (
            "function", "c_sha", "cprev_sha", "unit", "file", "ground_truth_diff",
            "lever_locus", "author", "provenance", "lever_class", "baseline_pct",
            "baseline_ndl", "target_pct", "target_ndl")})
        with sandbox_factory(case) as sandbox:
            adv_out = advisory_runner(case, sandbox)
            adv_verdict = advisory_judge(case, adv_out)
            gen = generative_runner(case, sandbox, lambda sb, fn: score_fn(sb, fn))
        gv = generative_verdict(baseline_ndl=case.baseline_ndl, baseline_pct=case.baseline_pct,
                                best_ndl=gen["best_ndl"], best_pct=gen["best_pct"])
        rollup = rollup_verdict(adv_verdict, gv, None)
        counts[rollup] += 1
        store.upsert_result(CaseResult(case_id=case.case_id, advisory=adv_verdict,
                                       generative=gv, rollup=rollup,
                                       evidence={"advisory": adv_out, "generative": gen}))
    return counts
```

Add the CLI command in `backtest.py`:

```python
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
```

> **Implementer note:** `cheap_tiers_with_real_judge` wires real `sandbox_factory` (a contextmanager around `build_sandbox`+build+`teardown_sandbox`), `score_fn` = `lambda sb, fn: (lambda p: (p.get("fuzzy_match_percent"), _structural_ndl(p)))(run_checkdiff_at(sb, fn))`, and an `advisory_judge` that, for the CLI path, falls back to a deterministic keyword judge (the LLM judge is supplied by the Workflow in Task 4.4). Add a `test_cheap_tiers_with_real_judge_smoke` behind `BACKTEST_SLOW=1`.

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_run_cheap.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/run.py tools/melee-agent/src/cli/backtest.py tools/melee-agent/tests/backtest/test_run_cheap.py
git commit -m "feat(backtest): cheap-tier pipeline + run subcommand"
```

### Task 4.4: Phase-0 two-sided calibration gate

**Files:**
- Create: `tools/melee-agent/src/backtest/calibrate.py`
- Test: `tools/melee-agent/tests/backtest/test_calibrate.py`

**Interfaces:**
- Produces: `calibrate(fixtures: list[dict], *, score_advisory, score_generative) -> dict` — runs the cheap-tier verdict logic over the synthetic fixtures (no build): for each, compute `rollup` from injected `score_advisory(fixture)`/`score_generative(fixture)`, compare to `expected_rollup`. Returns `{"passed": bool, "failures": [...], "positives_ok": int, "negatives_ok": int}`. **Gate rule:** `passed` iff every positive scores `SOLVED-BY-TOOLING` and every negative scores `GAP`.

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_calibrate.py
from src.backtest.calibrate import calibrate
from src.backtest.fixtures import load_calibration_fixtures

def test_calibration_passes_with_correct_scorers():
    fx = load_calibration_fixtures()
    # ideal scorers: positives solved, negatives gap
    def adv(f): return "names-lever" if f["kind"] == "positive" else "silent-or-wrong"
    def gen(f): return "byte-match-reproduced" if f["kind"] == "positive" else "no-progress"
    out = calibrate(fx, score_advisory=adv, score_generative=gen)
    assert out["passed"] is True

def test_calibration_fails_when_negative_leaks_to_solved():
    fx = load_calibration_fixtures()
    def adv(f): return "names-lever"
    def gen(f): return "byte-match-reproduced"   # everything "solved" -> negatives leak
    out = calibrate(fx, score_advisory=adv, score_generative=gen)
    assert out["passed"] is False
    assert any(fl["kind"] == "negative" for fl in out["failures"])
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_calibrate.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `calibrate.py`**

```python
# tools/melee-agent/src/backtest/calibrate.py
from __future__ import annotations

from .score import rollup_verdict


def calibrate(fixtures: list, *, score_advisory, score_generative) -> dict:
    failures = []
    positives_ok = negatives_ok = 0
    for f in fixtures:
        rollup = rollup_verdict(score_advisory(f), score_generative(f), None)
        if rollup == f["expected_rollup"]:
            if f["kind"] == "positive":
                positives_ok += 1
            else:
                negatives_ok += 1
        else:
            failures.append({"name": f["name"], "kind": f["kind"],
                             "expected": f["expected_rollup"], "got": rollup})
    return {"passed": not failures, "failures": failures,
            "positives_ok": positives_ok, "negatives_ok": negatives_ok}
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_calibrate.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/calibrate.py tools/melee-agent/tests/backtest/test_calibrate.py
git commit -m "feat(backtest): Phase-0 two-sided calibration gate"
```

### Task 4.5: Orchestration Workflow script

**Files:**
- Create: `docs/superpowers/plans/backtest-run.workflow.js`

This is the Workflow that supplies the **LLM advisory judge** and the **blind-agent tier** the CLI cannot. It is not unit-tested (it's an orchestration script); it is validated by a dry run against a 2-case corpus.

**Interfaces:** uses `agent()` for the judge (with `judge.JUDGE_PROMPT` + `build_judge_input`) and for blind attempts; calls the CLI primitives via the `Bash`-equivalent inside agents, or reads/writes the `BacktestStore`.

- [ ] **Step 1: Write the workflow script**

```javascript
// docs/superpowers/plans/backtest-run.workflow.js
export const meta = {
  name: 'backtest-run',
  description: 'Orchestrate the tooling-backtest: cheap tiers + LLM judge + blind-agent escalation',
  phases: [{ title: 'Cheap tiers' }, { title: 'Blind agents' }, { title: 'Report' }],
}

const WT = '/Users/mike/code/melee/.claude/worktrees/awesome-lamport-fe4b0b'
const AGENT = `${WT}/tools/melee-agent`

phase('Cheap tiers')
// build-corpus + cheap tiers are deterministic CLI; the LLM judge runs per-case here.
// (Cases must already be built via `backtest build-corpus`.)
const VERDICT_SCHEMA = { type: 'object', additionalProperties: false,
  properties: { verdict: { type: 'string', enum: ['names-lever','hints-adjacent','silent-or-wrong'] },
                rationale: { type: 'string' } }, required: ['verdict','rationale'] }

// One judge agent per case's advisory bundle (the CLI writes bundles to build/backtest/advisory/<case_id>.json).
const caseIds = JSON.parse(await agent(
  `List backtest case ids needing a judge verdict: read ${AGENT} BacktestStore (backtest_results.db) ` +
  `for cases with advisory bundles in ${WT}/build/backtest/advisory/ and no advisory verdict yet. ` +
  `Return a JSON array of case_id strings only.`,
  { label: 'enumerate-cases', phase: 'Cheap tiers' }))

await parallel(caseIds.map(cid => () =>
  agent(`Read ${WT}/build/backtest/advisory/${cid}.json (a label-blinded judge input: function, ` +
        `ground_truth_diff, lever_class, tool_outputs). Apply this rubric and return the verdict:\n` +
        `names-lever = a tool output identifies the exact change in ground_truth_diff; ` +
        `hints-adjacent = right region/mechanism, not the specific change; ` +
        `silent-or-wrong = nothing references the actual lever (DEFAULT when uncertain). ` +
        `Then write the verdict back via: cd ${AGENT} && python -m src.cli backtest set-advisory ${cid} <verdict>.`,
        { label: `judge:${cid}`, phase: 'Cheap tiers', schema: VERDICT_SCHEMA })))

phase('Blind agents')
const escalate = JSON.parse(await agent(
  `cd ${AGENT} && python -m src.cli backtest escalation --json  (returns case_ids for the blind tier). Echo only the JSON array.`,
  { label: 'escalation-list', phase: 'Blind agents' }))

await parallel(escalate.map(cid => () =>
  agent(`Blind matching attempt for backtest case ${cid}. ` +
        `Run: cd ${AGENT} && python -m src.cli backtest open-sandbox ${cid} --json  → gives {sandbox, function}. ` +
        `In that sandbox dir ONLY, use the /decomp workflow (checkdiff) to match the function. ` +
        `You are BLIND: do NOT inspect git history for future commits. ` +
        `Stop after a fixed effort budget. Then record the outcome: ` +
        `python -m src.cli backtest set-agent ${cid} <matched|improved|stuck>. Finally close-sandbox ${cid}.`,
        { label: `blind:${cid}`, phase: 'Blind agents', isolation: 'worktree' })))

phase('Report')
const report = await agent(`cd ${AGENT} && python -m src.cli backtest report --json. Echo the JSON.`,
  { label: 'report', phase: 'Report' })
return { report }
```

- [ ] **Step 2: Add the supporting CLI subcommands** (`set-advisory`, `set-agent`, `escalation`, `open-sandbox`, `close-sandbox`) — thin wrappers over `BacktestStore` + `sandbox.py` + `score.select_escalation`. Each gets a CliRunner test in `tests/cli/test_backtest_cli.py` (mock the store/sandbox). Follow the Task 0.1 pattern.

- [ ] **Step 3: Dry-run validation**

Run (after building a 2-case corpus): `cd tools/melee-agent && python -m src.cli backtest escalation --json` returns a JSON array; `python -m src.cli backtest report --json` returns the matrix object. Then launch the workflow with a 2-case corpus and confirm it completes.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/backtest-run.workflow.js tools/melee-agent/src/cli/backtest.py tools/melee-agent/tests/cli/test_backtest_cli.py
git commit -m "feat(backtest): orchestration workflow + judge/agent/sandbox CLI hooks"
```

---

## Milestone 5 — Report + feedback

### Task 5.1: Coverage matrix

**Files:**
- Create: `tools/melee-agent/src/backtest/report.py`
- Test: `tools/melee-agent/tests/backtest/test_report.py`

**Interfaces:**
- Produces:
  - `ESTIMAND_CAVEAT: str` — the verbatim spec §2 caveat ("measures whether tooling can rediscover easy already-won levers; NOT 'tooling owns X% of the matching surface'").
  - `coverage_matrix(cases: list[dict], results: list[dict]) -> dict` — `{lever_class: {provenance: {"SOLVED-BY-TOOLING": n, "PARTIAL": n, "GAP": n, "total": n}}}`.
  - `render_report(matrix: dict) -> str` — text table with the headline held-out solve-rate first, in-corpus second, and `ESTIMAND_CAVEAT` printed at the top.

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_report.py
from src.backtest.report import coverage_matrix, render_report, ESTIMAND_CAVEAT

CASES = [
    {"case_id": "a", "lever_class": "retype", "provenance": "held_out"},
    {"case_id": "b", "lever_class": "retype", "provenance": "held_out"},
    {"case_id": "c", "lever_class": "backend_coloring", "provenance": "held_out"},
]
RESULTS = [
    {"case_id": "a", "rollup": "SOLVED-BY-TOOLING"},
    {"case_id": "b", "rollup": "PARTIAL"},
    {"case_id": "c", "rollup": "GAP"},
]

def test_matrix_counts():
    m = coverage_matrix(CASES, RESULTS)
    assert m["retype"]["held_out"]["SOLVED-BY-TOOLING"] == 1
    assert m["retype"]["held_out"]["total"] == 2
    assert m["backend_coloring"]["held_out"]["GAP"] == 1

def test_report_prints_caveat():
    out = render_report(coverage_matrix(CASES, RESULTS))
    assert ESTIMAND_CAVEAT.split(".")[0] in out
    assert "held_out" in out
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_report.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `report.py`**

```python
# tools/melee-agent/src/backtest/report.py
from __future__ import annotations

from collections import defaultdict

ESTIMAND_CAVEAT = (
    "This measures P(tooling leads to the fix | a small-lever match exists in history). "
    "It is a PROXY for P(tooling leads to the fix | function is currently blocked). "
    "A high score means tooling can rediscover the easy, already-won levers; it is NOT "
    "evidence that tooling owns X% of the matching surface (the stuck frontier is excluded)."
)

_VERDICTS = ("SOLVED-BY-TOOLING", "PARTIAL", "GAP")


def coverage_matrix(cases: list, results: list) -> dict:
    by_id = {c["case_id"]: c for c in cases}
    matrix: dict = defaultdict(lambda: defaultdict(lambda: {v: 0 for v in _VERDICTS} | {"total": 0}))
    for r in results:
        case = by_id.get(r["case_id"])
        if not case:
            continue
        cell = matrix[case["lever_class"]][case["provenance"]]
        cell[r["rollup"]] += 1
        cell["total"] += 1
    return {lc: dict(pv) for lc, pv in matrix.items()}


def render_report(matrix: dict) -> str:
    lines = [ESTIMAND_CAVEAT, ""]
    for provenance in ("held_out", "in_corpus"):
        lines.append(f"== {provenance} ==")
        lines.append(f"{'lever_class':32} {'solved':>7} {'partial':>8} {'gap':>5} {'total':>6}")
        for lc in sorted(matrix):
            cell = matrix[lc].get(provenance)
            if not cell:
                continue
            lines.append(f"{lc:32} {cell['SOLVED-BY-TOOLING']:>7} {cell['PARTIAL']:>8} "
                         f"{cell['GAP']:>5} {cell['total']:>6}")
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_report.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/report.py tools/melee-agent/tests/backtest/test_report.py
git commit -m "feat(backtest): coverage matrix + estimand-captioned report"
```

### Task 5.2: `report` subcommand + feedback emit

**Files:**
- Modify: `tools/melee-agent/src/cli/backtest.py`
- Create: `tools/melee-agent/src/backtest/feedback.py`
- Test: `tools/melee-agent/tests/backtest/test_feedback.py`

**Interfaces:**
- Produces:
  - `stage_gap(case: dict, *, staging_dir: Path) -> Path` — writes `build/backtest/staged/<case_id>.json` with `{function, lever_class, ground_truth_diff, suggested_action}` (a proposed mismatch/mining entry). Returns the path. Never commits.
  - `issue_report_argv(case: dict) -> list[str]` — builds the `melee-agent issue report` argv (does NOT execute; the CLI executes after a `--emit-issues` opt-in).
- CLI: `backtest report [--json] [--emit-issues] [--db PATH]` prints the matrix and, with `--emit-issues`, stages gap proposals and (only if `--emit-issues`) runs `issue report` per GAP-with-clear-lever (lever_class != "backend_coloring").

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/backtest/test_feedback.py
import json
from pathlib import Path
from src.backtest.feedback import stage_gap, issue_report_argv

def test_stage_gap_writes_file(tmp_path):
    case = {"case_id": "abc123", "function": "f", "lever_class": "retype", "ground_truth_diff": "@@"}
    p = stage_gap(case, staging_dir=tmp_path)
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["function"] == "f" and data["lever_class"] == "retype"

def test_issue_argv_targets_the_function():
    case = {"function": "grIceMt_801F9ACC", "lever_class": "retype", "case_id": "x"}
    argv = issue_report_argv(case)
    assert argv[:3] == ["issue", "report"]
    assert "grIceMt_801F9ACC" in argv
```

- [ ] **Step 2: Run it; verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_feedback.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `feedback.py`**

```python
# tools/melee-agent/src/backtest/feedback.py
from __future__ import annotations

import json
from pathlib import Path


def stage_gap(case: dict, *, staging_dir: Path) -> Path:
    staging_dir.mkdir(parents=True, exist_ok=True)
    path = staging_dir / f"{case['case_id']}.json"
    path.write_text(json.dumps({
        "function": case["function"],
        "lever_class": case["lever_class"],
        "ground_truth_diff": case["ground_truth_diff"],
        "suggested_action": "Review for a new mismatch-db/mining-ledger pattern (staged, not committed).",
    }, indent=2))
    return path


def issue_report_argv(case: dict) -> list:
    summary = f"backtest GAP: tooling missed {case['lever_class']} lever on {case['function']}"
    return [
        "issue", "report", summary,
        "--tool", "backtest", "--kind", "feature",
        "--function", case["function"],
        "--body", f"Lever class {case['lever_class']} not surfaced by advisory/generative tiers "
                  f"(case {case['case_id']}). Ground-truth diff staged under build/backtest/staged/.",
    ]
```

Add to `backtest.py` a `report` command that loads the store, prints `render_report`, and with `--emit-issues` calls `stage_gap` for every GAP and runs `issue_report_argv` (via `subprocess` to `python -m src.cli`) for GAPs whose `lever_class != "backend_coloring"`.

- [ ] **Step 4: Run the test; verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/test_feedback.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/backtest/feedback.py tools/melee-agent/src/cli/backtest.py tools/melee-agent/tests/backtest/test_feedback.py
git commit -m "feat(backtest): report subcommand + staged gap feedback"
```

### Task 5.3: Full suite + golden + docs

**Files:**
- Modify: `.gitignore` (add `build/backtest/`)
- Modify: `tools/melee-agent/README` or the capabilities brief (via `capabilities generate`)

- [ ] **Step 1: Run the whole backtest test module**

Run: `cd tools/melee-agent && python -m pytest tests/backtest/ tests/cli/test_backtest_cli.py -q`
Expected: PASS (slow integration tests skipped without `BACKTEST_SLOW=1`).

- [ ] **Step 2: Run the full suite to confirm no regressions** (per memory: reorg/golden-only checks are insufficient — run the whole suite vs baseline)

Run: `cd tools/melee-agent && python -m pytest -q`
Expected: no new failures vs the pre-change baseline (the known env-only failures may remain).

- [ ] **Step 3: Refresh the capability brief**

Run: `cd tools/melee-agent && melee-agent capabilities generate`
Expected: brief now lists `backtest`; no "Typer apps declared but NOT registered" warning.

- [ ] **Step 4: Commit**

```bash
git add .gitignore tools/melee-agent
git commit -m "chore(backtest): gitignore build artifacts; refresh capability brief"
```

---

## Self-Review (completed by plan author)

**Spec coverage:** §2 estimand → Task 5.1 (`ESTIMAND_CAVEAT`). §3.1 in-corpus/held-out → Tasks 1.5, 1.6. §3.2 blindness + provable absence → Tasks 2.1, 2.2. §4 structural ground truth + confound guard → Tasks 1.3, 1.6, 1.7. §5 tool surface → Task 3.3 (bound to live CLI). §6 tiers + judge hardening + budgets → Tasks 3.2, 3.3, 4.1. §7 lever taxonomy + matrix → Tasks 0.2, 1.4, 5.1. §8 feedback → Task 5.2. §9 orchestration/sandbox lifecycle → Tasks 2.1, 4.5. §10 two-sided Phase-0 → Tasks 0.3, 4.4. §11 open questions → all resolved against the live CLI in the named tasks.

**Placeholder scan:** no TBD/TODO; every code step has complete code. Two explicit implementer notes (resolve `MELEE_AGENT_DIR`; wire `cheap_tiers_with_real_judge`) are scoped follow-ups within their tasks, not gaps.

**Type consistency:** `Case` (incl. `target_ndl` + `target_ndl_is_zero`), `CaseResult`, and the `*_verdict` literals are defined once in Task 0.2 and used unchanged in Tasks 1.6, 3.1, 3.2, 4.3, 5.1. `score_flip`/`score_fn` signatures are `(fn, sha)->(pct,ndl)` and `(sandbox,fn)->(pct,ndl)` respectively — kept distinct and consistent across corpus vs tier code.
