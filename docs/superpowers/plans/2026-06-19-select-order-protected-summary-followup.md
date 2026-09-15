# Select-Order Protected Summary Follow-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit source-actionable targeted-interference plans for lost protected targets and evidence-only FPR protected-hit composition summaries when guard repair only finds partial hits.

**Architecture:** Keep the implementation inside the existing select-order summary helpers in `tools/melee-agent/src/cli/debug/__init__.py`. Add focused helper logic for union target diagnostics and fallback partial-hit summaries without changing search ranking or transform families.

**Tech Stack:** Python, pytest, existing `melee-agent debug select-order-search` summary helpers.

---

### Task 1: Source Diagnostics for Lost Protected Targets

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] **Step 1: Write failing summary-path test**

Add `test_select_order_targeted_interference_uses_window_attrs_for_lost_protected_target`. Build a guard-repair summary with a protected seed `34 -> 27`, a complement candidate that hits `44 -> 25` and loses `34`, and `window_order_source_attributions={"34": {"kind": "local", "name": "dst_iter", "source_file": "src/melee/mn/mndiagram.c", "source_line": 911, "expression": "dst_iter"}, "44": {"kind": "implicit-temp", "expression": "add r44,r49,r34"}}`. Assert the resulting `targeted_interference_source_transforms.node_set_delta.missing_virtuals` contains r34 with source name `dst_iter`, contains r44, and has no `source-attribution-missing-for-r34` blocker.

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_targeted_interference_uses_window_attrs_for_lost_protected_target -q
```

Expected before implementation: FAIL because r34 has no source attribution.

- [ ] **Step 2: Write failing reconciliation-path test**

Add `test_select_order_reconciliation_frontier_uses_window_attrs_for_lost_protected_target`. Call `_select_order_guard_repair_reconciliation_frontier_entry` with the same candidate shape and window attribution map. Assert the returned frontier metadata includes r34 `dst_iter` in `targeted_interference_source_transforms`.

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_reconciliation_frontier_uses_window_attrs_for_lost_protected_target -q
```

Expected before implementation: FAIL because the helper hardcodes attribution inputs to `None`.

- [ ] **Step 3: Implement union diagnostics**

Add optional `window_order_source_attributions` and `window_order_probe_diagnostics` parameters where the targeted plan is built. Build diagnostics for the union of complement hit targets and lost protected targets, then pass those diagnostics into `_select_order_targeted_interference_transform_plan`.

- [ ] **Step 4: Verify Task 1 tests pass**

Run both tests from Steps 1 and 2. Expected after implementation: PASS.

### Task 2: Evidence-Only FPR Composition Fallback

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] **Step 1: Write failing partial-hit summary test**

Add `test_select_order_guard_repair_summary_reports_fpr_partial_hit_composition_without_seed_pair`. Build a summary with `class_id=1`, force-phys targets `32:28,33:26,38:29,39:29,40:29,46:26`, no usable seed/repair pairing, and a direct candidate that hits `33,39,40` while mismatching `32,38,46`. Assert `protected_complement_repair` exists, has `register_class == "fpr"`, contains `protected_hit_composition`, lists protected hits `33,39,40`, complement targets `32,38,46`, and preserves saved FPR/frame evidence.

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_summary_reports_fpr_partial_hit_composition_without_seed_pair -q
```

Expected before implementation: FAIL because `protected_complement_repair` is absent.

- [ ] **Step 2: Implement partial-hit fallback**

If normal protected-complement grouping produces no groups, dedupe seed and repair candidates by label, choose the strongest candidate with at least one force-phys hit, derive protected registers from its achieved hits, derive complement target statuses from that same candidate, and emit `protected_hit_composition` with blocked or timed-out status. Include a terminal blocker such as `partial-protected-complement-no-seed-pair`.

- [ ] **Step 3: Verify Task 2 test passes**

Run the test from Step 1. Expected after implementation: PASS.

### Task 3: Integration Verification and Commit

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`
- Create: `docs/superpowers/specs/2026-06-19-select-order-protected-summary-followup-design.md`
- Create: `docs/superpowers/plans/2026-06-19-select-order-protected-summary-followup.md`

- [ ] **Step 1: Run focused suite**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_select_order_search.py -q
PYTHONPATH=tools/melee-agent python -m py_compile tools/melee-agent/src/cli/debug/__init__.py
```

Expected: PASS.

- [ ] **Step 2: Run CLI smokes**

Run:

```bash
/opt/homebrew/bin/melee-agent debug select-order-search --help | rg -- '--force-phys'
melee-agent issues list
```

Expected: both commands exit 0.

- [ ] **Step 3: Commit and resolve**

Stage only the new docs, `tools/melee-agent/tests/test_select_order_search.py`, and the related hunks in `tools/melee-agent/src/cli/debug/__init__.py`. Commit on `master`, refresh the editable install from `/Users/mike/code/melee`, resolve issues #842 and #843 with the commit hash, then verify the issue queue is empty.
