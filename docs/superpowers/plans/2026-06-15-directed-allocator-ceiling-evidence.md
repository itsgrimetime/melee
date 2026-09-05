# Directed Allocator-Ceiling Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach `debug solve allocator-ceiling` to classify `debug search directed` telemetry as backend practical-ceiling evidence.

**Architecture:** Keep verdict logic in `tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`. Add top-level `function` and `unit` metadata to directed-search JSON in `tools/melee-agent/src/search/directed/run.py`, then extend allocator-ceiling tests and rendering around that structured payload.

**Tech Stack:** Python 3.11, Typer, pytest, existing `src.cli.debug.solve_app`, existing directed-search JSON schema.

**Review Corrections:** Practical-ceiling classification requires
`gate.passed == false`, `gate.reason == "no_smooth_gradient"`, at least one
real `transform-corpus:` row, blocked proof assignments, and no candidate-limit,
budget, or producer-failure accounting. `gate.passed == true` is actionable
progress, not exhausted evidence. Score failures and invalid directed telemetry
are bounded; compile failures from discarded generated probes are not bounded
when byte-mismatch telemetry exists for scored candidates. Directed source
shape generation must emit `source_shape_drained == true`; reaching `max_iters`
without that signal is incomplete evidence, not closure proof.

---

## File Structure

- Modify `tools/melee-agent/tests/test_allocator_ceiling.py`: add failing helper and CLI tests for directed telemetry evidence.
- Modify `tools/melee-agent/tests/search/directed/test_run_smoke.py`: assert directed run payload includes top-level `function` and `unit`.
- Modify `tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`: detect directed telemetry, classify directed exhaustion, aggregate backend blockers, and render blockers in text output.
- Modify `tools/melee-agent/src/search/directed/run.py`: include top-level `function` and `unit` for dry and live directed results.
- Modify `tools/melee-agent/src/search/directed/source.py`: expose a `drained` flag when proposal generation returns `None`.
- Modify `tools/melee-agent/src/search/scheduler.py`: persist source drain accounting as `source_drained` and `source_drained_names`.

### Task 1: Directed Evidence Tests

**Files:**
- Modify: `tools/melee-agent/tests/test_allocator_ceiling.py`

- [ ] **Step 1: Add directed evidence fixtures**

Add helper fixtures near the existing `_transform_negative` helper:

```python
def _directed_exhausted(function="fn_test"):
    blocked = [
        {
            "original_ig": 32,
            "new_ig": 32,
            "desired_phys": 28,
            "assigned_phys": 26,
        }
    ]
    return {
        "function": function,
        "unit": "melee/mn/mndiagram",
        "gate": {
            "passed": False,
            "reason": "no_smooth_gradient",
            "evidence": {
                "n_treatment": 3,
                "best_delta": 0.0,
            },
        },
        "directed_telemetry": [
            {
                "valid": True,
                "applied_mutator": "transform-corpus:coloring_register_steering:0",
                "checkdiff_gate": "byte_mismatch",
                "proof_assignments": {
                    "satisfied": [],
                    "blocked": blocked,
                    "abstained": [],
                },
                "non_actionable": False,
            },
            {
                "valid": True,
                "applied_mutator": "reorder_local_decls",
                "checkdiff_gate": "byte_mismatch",
                "proof_assignments": {
                    "satisfied": [],
                    "blocked": blocked,
                    "abstained": [],
                },
                "non_actionable": True,
            },
        ],
        "accounting": {
            "compiled": 2,
            "budget_exhausted": False,
            "source_shape_drained": True,
            "producer_failed": 0,
        },
    }
```

- [ ] **Step 2: Add the practical-ceiling test**

Add:

```python
def test_directed_exhausted_byte_mismatches_classify_as_practical_ceiling():
    result = classify_allocator_ceiling([_directed_exhausted()], function="fn_test")

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "directed-source-exhausted"
    assert result["directed_source_exhausted"] is True
    assert result["source_shape_exhausted"] is True
    assert result["backend_blockers"] == [
        {
            "original_ig": 32,
            "new_ig": 32,
            "desired_phys": 28,
            "assigned_phys": 26,
            "mutators": ["transform-corpus:coloring_register_steering:0", "reorder_local_decls"],
        }
    ]
    assert result["exit_code"] == 3
```

- [ ] **Step 3: Add directed positive and incomplete tests**

Add:

```python
def test_directed_byte_match_is_actionable():
    evidence = _directed_exhausted()
    evidence["directed_telemetry"][0]["checkdiff_gate"] = "byte_match"

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "actionable"
    assert "directed byte_match" in result["positive_proofs"]
    assert result["exit_code"] == 0


def test_directed_without_blocked_assignments_is_incomplete():
    evidence = _directed_exhausted()
    for row in evidence["directed_telemetry"]:
        row["proof_assignments"]["blocked"] = []

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert "directed telemetry with blocked proof assignments" in result["missing_evidence"]
```

- [ ] **Step 4: Add review-boundary tests**

Add:

```python
def test_directed_budget_exhaustion_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["budget_exhausted"] = True

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search budget exhausted" in result["bounded_reasons"]
    assert result["exit_code"] == 4


def test_directed_without_source_transform_rows_is_incomplete():
    evidence = _directed_exhausted()
    for row in evidence["directed_telemetry"]:
        row["applied_mutator"] = "force_phys_assignment"

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert "directed telemetry from source-transform candidates" in result["missing_evidence"]


def test_directed_unknown_byte_outcome_is_incomplete():
    evidence = _directed_exhausted()
    for row in evidence["directed_telemetry"]:
        row.pop("checkdiff_gate")

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert "directed byte-mismatch outcomes" in result["missing_evidence"]


def test_directed_without_source_shape_drained_signal_is_incomplete():
    evidence = _directed_exhausted()
    evidence["accounting"].pop("source_shape_drained")

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert "directed source-shape drained signal" in result["missing_evidence"]


def test_directed_gate_progress_is_actionable_not_ceiling():
    evidence = _directed_exhausted()
    evidence["gate"]["passed"] = True
    evidence["gate"]["reason"] = "attributable_progress"

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "actionable"
    assert "directed attributable_progress" in result["positive_proofs"]
    assert result["directed_source_exhausted"] is False
    assert result["backend_blockers"] == []


def test_directed_producer_failure_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["producer_failed"] = 1

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search producer failed" in result["bounded_reasons"]


def test_directed_score_failure_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["score_failed"] = 1

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search score failed" in result["bounded_reasons"]


def test_directed_invalid_telemetry_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["directed_invalid"] = 1

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search invalid directed telemetry" in result["bounded_reasons"]


def test_directed_invalid_telemetry_row_is_bounded_without_accounting_counter():
    evidence = _directed_exhausted()
    evidence["directed_telemetry"].append(
        {
            "valid": False,
            "invalid_reason": "pcdump_missing",
            "applied_mutator": "transform-corpus:coloring_register_steering:bad",
        }
    )

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search invalid directed telemetry" in result["bounded_reasons"]


def test_directed_compile_failures_with_scored_rows_do_not_bound():
    evidence = _directed_exhausted()
    evidence["accounting"]["compile_failed"] = 2

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "practical-ceiling"
    assert "directed search compile failed" not in result["bounded_reasons"]


def test_directed_candidate_limit_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["stop_reason"] = "candidate-limit"

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search candidate-limit" in result["bounded_reasons"]
```

- [ ] **Step 5: Add CLI rendering test**

Add:

```python


def test_allocator_ceiling_cli_text_lists_backend_blockers(tmp_path):
    evidence_path = _write_json(tmp_path / "directed.json", _directed_exhausted())
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 3
    assert "allocator-ceiling fn_test: practical-ceiling" in result.output
    assert "backend blockers:" in result.output
    assert "ig32->ig32 wants 28 got 26" in result.output
```

- [ ] **Step 6: Run the new allocator-ceiling tests and verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_allocator_ceiling.py -q -k 'directed or backend_blockers'
```

Expected before implementation: failures showing missing directed classification and missing `backend_blockers` rendering.

### Task 2: Directed Payload Metadata Tests

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_run_smoke.py`

- [ ] **Step 1: Add dry-run metadata assertions**

Update `test_run_directed_dry` after top-level shape assertions:

```python
    assert res["function"] == "grIceMt_801F9ACC"
    assert res["unit"] == "melee/gr/gricemt"
```

- [ ] **Step 2: Run the directed smoke test and verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/directed/test_run_smoke.py::test_run_directed_dry -q
```

Expected before implementation: failure for missing `function` or `unit`.

### Task 3: Implement Allocator-Ceiling Directed Evidence

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`

- [ ] **Step 1: Extend positive proof detection**

In `_positive_proofs`, scan `directed_telemetry` rows and append `"directed byte_match"` when any row has `checkdiff_gate == "byte_match"`.

- [ ] **Step 2: Add directed evidence helpers**

Add helpers:

```python
def _directed_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    ...

def _directed_backend_blockers(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    ...
```

The summary should report:

- `present`
- `source_rows`
- `compiled`
- `has_byte_match`
- `has_blocked_assignments`
- `bounded_reasons`
- `backend_blockers`

Deduplicate blockers by `(original_ig, new_ig, desired_phys, assigned_phys)`.

- [ ] **Step 3: Wire directed summary into classification**

In `classify_allocator_ceiling`:

- compute `directed = _directed_summary(items)`,
- add directed bounded reasons to `bounded`,
- set `status=practical-ceiling` and `reason=directed-source-exhausted` when no positive or bounded evidence exists and directed evidence is complete,
- set directed evidence complete only when `gate.passed == false` and
  `gate.reason == "no_smooth_gradient"`,
- add `"directed telemetry with blocked proof assignments"` to missing evidence when directed evidence exists but has no blockers,
- add `"directed telemetry from source-transform candidates"` to missing evidence when directed evidence exists but has no `transform-corpus:` rows,
- include `directed_source_exhausted` and `backend_blockers` in the result.

- [ ] **Step 4: Render backend blockers**

In `render_allocator_ceiling_text`, print:

```text
backend blockers:
- ig32->ig32 wants 28 got 26 via transform-corpus:coloring_register_steering:0, reorder_local_decls
```

- [ ] **Step 5: Run allocator-ceiling tests and verify GREEN**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_allocator_ceiling.py -q
```

Expected: all tests in the file pass.

### Task 4: Add Directed Payload Metadata

**Files:**
- Modify: `tools/melee-agent/src/search/directed/run.py`

- [ ] **Step 1: Include top-level metadata in dry result**

In `_run_dry`, return:

```python
        "function": function,
        "unit": unit,
```

beside `gate`, `directed_telemetry`, and `accounting`.

- [ ] **Step 2: Include top-level metadata in live result**

In both live-result return dictionaries, include:

```python
        "function": function,
        "unit": unit,
```

- [ ] **Step 3: Run directed smoke tests and verify GREEN**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/directed/test_run_smoke.py -q
```

Expected: directed smoke tests pass.

### Task 5: Integration Smoke And Issue Resolution

**Files:**
- No production files unless verification exposes a small bug.

- [ ] **Step 1: Run focused tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/test_allocator_ceiling.py \
  tools/melee-agent/tests/search/directed/test_run_smoke.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run command-level smoke on current master evidence**

Produce fresh directed evidence and classify it. Use enough iterations to avoid
using capped evidence as closure proof:

```bash
mkdir -p build/issue-726
melee-agent debug search directed \
  -f mnDiagram_80241E78 \
  -u melee/mn/mndiagram \
  --directed-from-diff \
  --directed-class 1 \
  --max-iters 80 > build/issue-726/mnDiagram_80241E78-directed.json

melee-agent debug solve allocator-ceiling \
  --function mnDiagram_80241E78 \
  --evidence build/issue-726/mnDiagram_80241E78-directed.json \
  --json > build/issue-726/mnDiagram_80241E78-ceiling.json
```

Expected: the second command exits `3`; JSON contains
`status == "practical-ceiling"`, `terminal_reason == "directed-source-exhausted"`,
and non-empty `backend_blockers`.

- [ ] **Step 3: Refresh editable install**

Run:

```bash
python tools/worktree-doctor.py --fix
```

Expected: `/opt/homebrew/bin/melee-agent` imports
`/Users/mike/code/melee/tools/melee-agent/src/cli/__init__.py`.

- [ ] **Step 4: Resolve #726 if the smoke passes**

Run:

```bash
melee-agent issue resolve 726 --impact diagnostic-only --note "Implemented directed-search telemetry ingestion for allocator-ceiling in <commit>; mnDiagram_80241E78 directed evidence now classifies as practical-ceiling with backend_blockers."
```

If smoke does not classify current evidence as `practical-ceiling`, add a note to
#726 with the missing evidence and do not resolve it.
