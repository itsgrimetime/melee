# Structure Search Scored Variants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `debug search structure` score retained source variants by default and explain every unscored candidate.

**Architecture:** Keep candidate generation in `src/search/structure.py`, add a scoring contract there, and put real repo-mutating scoring in `src/search/structure_scoring.py`. Wire the CLI default to build a real scorer while preserving a `--no-score` fast path.

**Tech Stack:** Python 3.11, Typer, pytest, existing structure-search axes, Ninja, objdiff report generation, `tools/checkdiff.py --no-build`, shared repo lock from `src.search.adapters`.

---

## File Structure

- Modify `tools/melee-agent/src/search/structure.py`
  - Add `StructureScoreResult`.
  - Add scoring application after candidate generation.
  - Add `compile_status` and `unscored_reason` to variant payloads.
  - Update stop-condition logic to distinguish scored no-improvement from unscored generated candidates.
- Create `tools/melee-agent/src/search/structure_scoring.py`
  - Resolve report entries.
  - Build baseline and candidate sources under the repo lock.
  - Restore source, object, and report on all exits.
  - Extract report percent and no-build checkdiff structural metrics.
- Modify `tools/melee-agent/src/search/cli.py`
  - Add `--score/--no-score` and `--score-timeout`.
  - Construct the real scorer only when scoring is enabled.
- Modify `tools/melee-agent/tests/search/test_structure.py`
  - Add fast tests for fake scoring, compile failures, no-score reasons, and ranking.
- Modify `tools/melee-agent/tests/search/test_cli_smoke.py`
  - Add CLI wiring tests for default scoring and `--no-score`.
- Create `tools/melee-agent/tests/search/test_structure_scoring.py`
  - Add fake-subprocess tests for baseline/candidate scoring, child env, and restoration.

## Task 1: Add The Structure Scoring Contract

**Files:**
- Modify: `tools/melee-agent/src/search/structure.py`
- Modify: `tools/melee-agent/tests/search/test_structure.py`

- [x] **Step 1: Write failing fake-scoring tests**

Add tests that call `run_structure_search` with `score_variants=True` and a fake
`score_runner`. The fake should return baseline `90.0`, a candidate score
`92.5`, structural metrics, and a second compile-failed result. Assert variants
are ranked by candidate percent, baseline is filled in the payload, successful
variants have `compile_status == "ok"`, failed variants have
`status == "unscored"` and a concrete `unscored_reason`.

- [x] **Step 2: Add no-score explicit reason test**

Call `run_structure_search` without a scorer on an axis that generates a
candidate. Assert the candidate has `status == "unscored"`,
`unscored_reason == "scoring disabled"`, and stop condition remains
`candidates-generated`.

- [x] **Step 3: Implement the dataclass and score application**

Add:

```python
@dataclass(frozen=True)
class StructureScoreResult:
    label: str
    baseline_percent: float | None
    candidate_percent: float | None
    compile_status: str
    unscored_reason: str | None = None
    structural: dict[str, Any] = field(default_factory=dict)
```

Extend `StructureVariant` with these optional fields:

```python
compile_status: str | None = None
unscored_reason: str | None = None
```

Update `run_structure_search` to accept:

```python
score_runner: Callable[[list[StructureVariant]], list[StructureScoreResult]] | None = None
score_variants: bool = False
```

Add `_apply_structure_scores(variants, score_results)` that maps score results
by `label`, updates `baseline_percent`, `match_percent`, `final_match_percent`,
`delta`, `compile_status`, and `metadata["structural"]`, and sets
`status="unscored"` plus a concrete `unscored_reason` when a variant has
retained source but no usable score.

- [x] **Step 4: Run focused tests**

Run:

```bash
cd tools/melee-agent && python -m pytest tests/search/test_structure.py -q
```

Expected: all structure tests pass.

## Task 2: Add Real Repo Scoring

**Files:**
- Create: `tools/melee-agent/src/search/structure_scoring.py`
- Create: `tools/melee-agent/tests/search/test_structure_scoring.py`

- [x] **Step 1: Write restoration and metric tests**

Use a temporary fake repo with `src/melee/demo.c`, `build/GALE01/report.json`,
and `build/GALE01/src/melee/demo.o`. Monkeypatch subprocess so:

- `ninja build/GALE01/src/melee/demo.o` succeeds;
- objdiff report generation rewrites report percent to baseline/candidate values;
- `tools/checkdiff.py ... --no-build` returns JSON structural metrics.

Assert the scorer returns one `StructureScoreResult`, passes
`CHECKDIFF_NO_LOCK=1` to child checkdiff, and restores source/object/report
bytes.

- [x] **Step 2: Implement report/unit resolution**

Implement `resolve_structure_score_context(melee_root, function, source_path)`
returning unit, source path, build object path, and report path. It should use
`build/GALE01/report.json` and reject source/function mismatches with explicit
reasons.

Use this return shape:

```python
@dataclass(frozen=True)
class StructureScoreContext:
    melee_root: Path
    function: str
    unit: str
    source_path: Path
    build_obj_path: Path
    report_path: Path
```

- [x] **Step 3: Implement the locked scorer**

Implement `score_structure_variants(...)` that reads each retained source,
builds baseline once, scores candidates, captures structural metrics, handles
compile/report/checkdiff errors as unscored results, and restores saved files in
`finally`.

Use this public signature:

```python
def score_structure_variants(
    *,
    melee_root: Path,
    function: str,
    source_path: Path,
    variants: list[StructureVariant],
    timeout: float,
) -> list[StructureScoreResult]:
    ...
```

Use the same child environment for no-build checkdiff every time:

```python
env = os.environ.copy()
env["CHECKDIFF_NO_LOCK"] = "1"
env["CHECKDIFF_NO_FINGERPRINT"] = "1"
```

The scorer must save and restore:

```python
original_source = source_path.read_bytes()
original_obj = build_obj_path.read_bytes() if build_obj_path.exists() else None
original_report = report_path.read_bytes() if report_path.exists() else None
```

- [x] **Step 4: Run focused scorer tests**

Run:

```bash
cd tools/melee-agent && python -m pytest tests/search/test_structure_scoring.py -q
```

Expected: all scorer tests pass.

## Task 3: Wire CLI Defaults

**Files:**
- Modify: `tools/melee-agent/src/search/cli.py`
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`

- [x] **Step 1: Write CLI wiring tests**

Add a test that monkeypatches `score_structure_variants` and
`run_structure_search`, invokes `search_app structure ... --json`, and asserts
`score_variants=True` and a callable score runner are passed by default.

Add a second test invoking `--no-score` and assert `score_variants=False` and
`score_runner is None`.

- [x] **Step 2: Add CLI options and scorer builder**

Add Typer options `--score/--no-score` and `--score-timeout`. When scoring is
enabled, build a closure that calls `score_structure_variants` with the resolved
repo root, function, source path, output directory, and timeout.

- [x] **Step 3: Run CLI smoke tests**

Run:

```bash
cd tools/melee-agent && python -m pytest tests/search/test_cli_smoke.py -k 'structure' -q
```

Expected: structure CLI smokes pass.

## Task 4: Verify And Resolve Issue #446

**Files:**
- All modified files above.

- [x] **Step 1: Run focused verification**

Run:

```bash
cd tools/melee-agent && python -m pytest tests/search/test_structure.py tests/search/test_structure_scoring.py tests/search/test_cli_smoke.py -k 'structure' -q
python -m py_compile tools/melee-agent/src/search/structure.py tools/melee-agent/src/search/structure_scoring.py tools/melee-agent/src/search/cli.py
cd tools/melee-agent && python -m src.cli debug search structure --help
git diff --check
```

- [ ] **Step 2: Commit only relevant files**

Stage only the spec, plan, structure-search files, and tests. Do not stage
`src/sysdolphin/baselib/hsd_3B34.c`.

- [ ] **Step 3: Resolve #446 after commit**

Run:

```bash
melee-agent issue resolve 446 --note "Fixed in <commit>: structure-search now scores retained variants by default, reports baseline/candidate/delta/compile status/structural movement, and records concrete unscored reasons."
```
