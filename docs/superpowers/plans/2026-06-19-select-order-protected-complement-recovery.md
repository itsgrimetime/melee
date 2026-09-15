# Select-Order Protected Complement Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make select-order guard repair backtrack from complement-hit/protected-loss sources and report source diagnostics for unresolved complement targets.

**Architecture:** Extend the existing guard-repair loop in `tools/melee-agent/src/cli/debug/__init__.py` with a reconciliation frontier helper, without changing final ranking. Extend the existing protected-complement summary with a diagnostics helper that consumes existing window-order attribution/probe diagnostic data.

**Tech Stack:** Python, Typer CLI, pytest, existing `melee-agent debug select-order-search` test harness.

---

### Task 1: Reconciliation Frontier

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] **Step 1: Write the failing CLI regression**

Add a test near the existing guard-repair CLI tests. It should:

```python
def test_select_order_guard_repair_expands_complement_hit_recovery_frontier(...):
    # Baseline seed hits only protected IG33->r30.
    # Depth 1 produces two candidates: one preserves IG33 only and one hits
    # complement IG32->r29 while losing IG33. Width is 1.
    # Depth 2 should still expand the complement-hit source and score a
    # recovery probe that hits both IG32 and IG33.
```

Use monkeypatched probe generation and fake compile/source scoring, following the existing tests in the file. Run:

```bash
pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_expands_complement_hit_recovery_frontier -q
```

Expected before implementation: FAIL because no depth-2 recovery entry is created.

- [ ] **Step 2: Implement the recovery helper**

Add a helper that inspects a scored repair candidate with the current protected hits and complement targets. If it hits complement targets and loses protected hits, return a new frontier entry that protects achieved registers and makes the lost registers the new complement targets. Include `reconciliation_seed` metadata.

- [ ] **Step 3: Integrate the helper into the guard-repair loop**

After `ranked_round` is built, keep the normal `guard_repair_width` frontier, then append recovery entries not already selected. Store recovery rows in `guard_repair_ledger["reconciliation_frontier"]`.

- [ ] **Step 4: Verify the regression passes**

Run:

```bash
pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_expands_complement_hit_recovery_frontier -q
```

Expected after implementation: PASS.

### Task 2: Complement Source Diagnostics

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] **Step 1: Write the failing summary regression**

Extend or add a protected-complement summary test that passes `window_order_source_attributions` and `window_order_probe_diagnostics` to `_select_order_guard_repair_summary`. Assert that unresolved complement targets include `complement_source_diagnostics` entries with:

```python
{
    "38": {
        "source_attribution": {"kind": "fpr-temp", ...},
        "terminal_blocker": "unsupported-source-attribution-kind",
        "source_actionable": False,
    },
    "46": {
        "terminal_blocker": "source-attribution-missing",
        "source_actionable": False,
    },
}
```

Run:

```bash
pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_summary_reports_fpr_complement_source_diagnostics -q
```

Expected before implementation: FAIL because the summary does not expose complement source diagnostics.

- [ ] **Step 2: Implement the diagnostics helper**

Add a helper that maps complement target IGs to source attribution and probe diagnostics. It should prefer the lead diagnostic source attribution, fall back to `window_order_source_attributions`, and report `source-attribution-missing` when neither exists.

- [ ] **Step 3: Thread diagnostics through summary creation**

Add optional parameters to `_select_order_guard_repair_summary` and `_select_order_protected_complement_summary`. Attach `complement_source_diagnostics` to the top-level protected-complement summary and each group.

- [ ] **Step 4: Verify the summary regression passes**

Run:

```bash
pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_summary_reports_fpr_complement_source_diagnostics -q
```

Expected after implementation: PASS.

### Task 3: Integration Verification

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tools/melee-agent/tests/test_select_order_search.py -q
```

Expected: PASS.

- [ ] **Step 2: Run CLI smoke checks**

Run:

```bash
DECOMP_AGENT_ID=codex-issue-resolver-3 melee-agent debug select-order-search --help >/tmp/select-order-help.txt
DECOMP_AGENT_ID=codex-issue-resolver-3 melee-agent issues list
```

Expected: help exits 0 and the issue list remains readable.

- [ ] **Step 3: Commit and resolve issues**

Stage only the new docs, test changes, and related hunks in `tools/melee-agent/src/cli/debug/__init__.py`. Commit on `master`, refresh the editable install from `/Users/mike/code/melee`, then resolve #819 and #820 with the commit hash.
