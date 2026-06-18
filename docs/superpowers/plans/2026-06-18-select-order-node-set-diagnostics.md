# Select-Order Node-Set Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Resolve issues #776, #777, #778, #780, #781, and #782 by making node-set attribution/scoping safer and select-order beam diagnostics bucketed enough to identify the next source lever.

**Architecture:** Keep the existing command surface. Add small data fields and helper functions in `node_set_split.py` and `debug/__init__.py`, with focused regression tests in the existing suites.

**Tech Stack:** Python, Typer CLI, existing `mwcc_debug` parser/AST helpers, pytest.

---

### Task 1: Node-Set Attribution Safety

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/search/solver/test_cli_solve.py`

- [x] **Step 1: Write the failing test**

Add a test that builds a fake report source with `confidence="low-confidence"` and asserts `_derive_node_set_delta_payload` does not emit `source.name` for that IG.

- [x] **Step 2: Verify failure**

Run: `python -m pytest tools/melee-agent/tests/search/solver/test_cli_solve.py::test_derive_node_set_delta_payload_drops_low_confidence_source_binding -q`

Expected: fail because the current payload keeps the misleading source.

- [x] **Step 3: Implement the guard**

Add a helper that returns `None` for source attributions with confidence in `{"low-confidence", "ambiguous", "ambiguous-nested", "unsupported", "rejected"}` before building `missing_virtuals`.

- [x] **Step 4: Verify**

Run the same test and the nearby solver CLI tests.

### Task 2: Node-Set Scope Anchoring and Zero-Candidate Reporting

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`
- Test: `tools/melee-agent/tests/search/solver/test_cli_solve.py`

- [x] **Step 1: Write failing scope test**

Add a test where two loops both declare/read `j`; the request source line points at the second loop. Assert generated alias/lifetime patches mention only the second loop body.

- [x] **Step 2: Implement source scope on requests**

Extend `NodeSetSplitRequest` with `source_scope_path`. Resolve it from source text, source name, and source line via `ast_walker.walk_function`. Pass it to `mutate_insert_alias_before_use` and `mutate_preserve_lifetime_after_use`.

- [x] **Step 3: Write failing coupled blocked tests**

Add CLI tests where `requests_from_node_set_delta` returns no coupled requests and where two bindable requests produce zero patches. Assert JSON includes `generated_count=0`, `scored_count=0`, no baseline compile/scoring, and a blocked/no-probes stop condition.

- [x] **Step 4: Implement bounded blocked summary**

When coupled mode has zero requests or zero patches from generation, emit a specific blocked summary and no candidate scoring. For compile-failed retained sources, preserve the direct compile/build error in JSON rather than reducing it to a pcdump omission.

- [x] **Step 5: Verify**

Run the two focused node-set test files.

### Task 3: Select-Order Diagnostic Buckets

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [x] **Step 1: Write failing bucket test**

Create three scored variants: a global top miss, a one-target force-phys hit outside the top residual count, and an opcode/frame-preserving candidate. Assert JSON has `diagnostic_buckets`, each standard bucket key exists even when empty, and the bucketed variants get `residual_analysis`.

- [x] **Step 2: Implement bucket selection**

Add helper functions to collect diagnostic bucket members from ranked variants and `proof_force_map`. Annotate the union of global top N and bucket members with residual analysis. Do not change ranking semantics.

- [x] **Step 3: Add provenance assertions**

Extend the existing beam test to assert JSON variants include `chain` and probe provenance for composed candidates.

- [x] **Step 4: Verify**

Run `python -m pytest tools/melee-agent/tests/test_select_order_search.py -q`.

### Task 4: Integration, Install Refresh, and Issue Resolution

**Files:**
- Modify as above.
- Update issue queue only after verification.

- [x] **Step 1: Run focused tests**

Run:
`python -m pytest tools/melee-agent/tests/test_node_set_split.py tools/melee-agent/tests/search/solver/test_cli_solve.py tools/melee-agent/tests/test_select_order_search.py -q`

- [x] **Step 2: Run smoke checks**

Run `git diff --check`, `python -m py_compile` on touched modules, and CLI help/synthetic smoke commands.

- [x] **Step 3: Commit and refresh editable install**

Commit spec, plan, tests, and implementation. Then run `python -m pip install -e tools/melee-agent` from `/Users/mike/code/melee`.

- [x] **Step 4: Resolve issues**

Resolve only #776, #777, #778, #780, #781, and #782 with notes describing the verified root causes.
