# FPR Copy-Propagation Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add source/copy-propagation repair reporting to `debug coalesce-search --trace-copy-json` for FPR copies that disappear after copy propagation.

**Architecture:** Extend the existing coalesce-search trace-copy path in `tools/melee-agent/src/cli/debug/__init__.py`. Keep scoring and ranking unchanged; add a deterministic repair summary that reuses trace-copy JSON mappings and the existing candidate-hit predicate.

**Tech Stack:** Python 3.11, Typer CLI, pytest, existing `melee-agent` debug/coalesce-search helpers.

## Global Constraints

- Preserve existing `copy_survived_repair` behavior and JSON keys.
- Do not generate source edits from pcode-only expressions.
- `source-actionable` requires a scored `.c` source candidate with retained source whose objective changes the target relation.
- Raw `.txt` pcdump candidates and unscored repair sketches must not produce `source-actionable`.
- Render FPR virtuals with `f` and GPR virtuals with `r`.
- Add or update regression tests before production code.
- Keep edits scoped to `tools/melee-agent/src/cli/debug/__init__.py`, `tools/melee-agent/tests/test_coalesce_search.py`, and these spec/plan files unless review finds a necessary helper extraction.

---

### Task 1: Add copy-propagation repair regression tests

**Files:**
- Modify: `tools/melee-agent/tests/test_coalesce_search.py`

**Interfaces:**
- Consumes: existing `debug coalesce-search --trace-copy-json` CLI output.
- Produces: failing tests for `copy_propagation_repair`.

- [ ] **Step 1: Write failing JSON terminal-blocker test**

Add a test that builds a trace-copy JSON for `fn_80000046` with `from_virtual=56`, `to_virtual=46`, class id `1`, `first_absent_pass="AFTER COPY PROPAGATION"`, and first occurrences `fmadds f56,...` and `fsubs f46,...`. Invoke:

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_coalesce_search.py::test_coalesce_search_trace_copy_after_copy_propagation_reports_unmapped_fpr_blocker -q
```

Expected before implementation: fail with missing `copy_propagation_repair`.

- [ ] **Step 2: Write failing scored source-actionable test**

Add a second test with a manual `.c` candidate path and monkeypatched `compile_source_variant` returning a candidate pcdump that changes the FPR target relation. Assert `copy_propagation_repair.status == "source-actionable"`, `best_source_candidate.source_retained` is present, and the candidate objective/frame or spill details are preserved.

Run:

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_coalesce_search.py::test_coalesce_search_trace_copy_after_copy_propagation_reports_scored_source_candidate -q
```

Expected before implementation: fail with missing `copy_propagation_repair`.

- [ ] **Step 3: Write failing source-actionable guard tests**

Add tests for these edge cases:

- a trace-copy JSON with source-mapped operands but no relation-changing `.c` candidate still reports `terminal-blocker`
- a raw `.txt` candidate that changes the relation does not produce `source-actionable`
- a mixed mapped/unmapped operand case reports `terminal-blocker` and names only the unmapped side
- non-copy-propagation disappearance reports `not-applicable`
- `transform_category` containing `copy-propagation` applies when `first_absent_pass` is absent

Run the specific tests added for each case with `PYTEST_ADDOPTS=--no-cov pytest ... -q`.

Expected before implementation: fail with missing `copy_propagation_repair`.

- [ ] **Step 4: Write failing text-output test**

Extend the existing FPR text-rendering test or add a new test so text output includes `copy-propagation repair: terminal-blocker` and the FPR pair `f56/f46`.

Run:

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_coalesce_search.py::test_coalesce_search_trace_copy_text_renders_copy_propagation_blocker -q
```

Expected before implementation: fail with missing text.

### Task 2: Implement repair summary helpers

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`

**Interfaces:**
- Consumes: `_load_trace_copy_repair_target`, `_trace_copy_json_summary`, `_copy_survived_variant_hit`.
- Produces: `_copy_propagation_repair_summary(trace_target, ranked_variants)`.

- [ ] **Step 1: Preserve trace-copy mapping details**

Update `_load_trace_copy_repair_target` to carry `first_absent_pass`, `first_copy`, `last_copy`, `likely_cause`, `transform_category`, and normalized `from_operand`/`to_operand` summaries from `from_mapping` and `to_mapping`.

Infer register class from explicit top-level `register_class`, then mapping `class_id`, then FPR/GPR tokens in mapping first/last occurrences. Use top-level copy operands only as a fallback because real FPR trace-copy artifacts can spell the pseudo-copy itself as `mr r46,r56` while the defining operands are FPR.

Normalization must use real trace-copy fields:

```python
expression = (
    call_return_origin.get("expression")
    or call_return_origin.get("call_symbol")
    or f"{first_occurrence['opcode']} {first_occurrence['operands']}"
)
mapped_to_source = bool(
    call_return_origin.get("source_file")
    and call_return_origin.get("source_line") is not None
)
```

- [ ] **Step 2: Add summary helper**

Add `_copy_propagation_repair_summary` that returns `not-applicable` unless the trace disappeared after copy propagation or is categorized as copy-propagation. If a ranked variant is a scored `.c` source candidate with retained source and `_copy_survived_variant_hit` is true, return `source-actionable` with `best_source_candidate`. Otherwise return `terminal-blocker`, including unmapped operand tokens and expressions when any operand is not source-mapped. If both operands are mapped but no scored source candidate changed the relation, keep `status == "terminal-blocker"` and include ranked repair sketches as advisory metadata only.

- [ ] **Step 3: Wire JSON output**

When `trace_copy_target is not None`, add `payload["copy_propagation_repair"] = _copy_propagation_repair_summary(trace_copy_target, ranked_variants)`.

- [ ] **Step 4: Wire text output**

For non-JSON output, render one line for applicable repair summaries:

```text
copy-propagation repair: terminal-blocker for f56/f46 - unmapped source operands: f56=..., f46=...
```

### Task 3: Verify and commit

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Modify: `tools/melee-agent/tests/test_coalesce_search.py`
- Add: `docs/superpowers/specs/2026-06-19-fpr-copy-prop-repair-design.md`
- Add: `docs/superpowers/plans/2026-06-19-fpr-copy-prop-repair.md`

- [ ] **Step 1: Run focused tests**

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_coalesce_search.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run adjacent regression tests**

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_suggest_coalesce.py tools/melee-agent/tests/test_allocator_intervention.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run smoke checks**

```bash
python -m py_compile tools/melee-agent/src/cli/debug/__init__.py
ruff check tools/melee-agent/src/cli/debug/__init__.py tools/melee-agent/tests/test_coalesce_search.py --select F821,F822,F823
PYTHONPATH=tools/melee-agent python -m src.cli debug coalesce-search --help | rg -- '--trace-copy-json'
```

Expected: compile succeeds, ruff reports no selected errors, help shows `--trace-copy-json`.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-06-19-fpr-copy-prop-repair-design.md docs/superpowers/plans/2026-06-19-fpr-copy-prop-repair.md tools/melee-agent/src/cli/debug/__init__.py tools/melee-agent/tests/test_coalesce_search.py
git commit -m "Add FPR copy-propagation repair summary"
```
