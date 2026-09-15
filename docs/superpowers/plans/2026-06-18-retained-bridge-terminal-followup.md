# Retained Bridge Terminal Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix retained seed scoring, empty inline-boundary drift attribution, and terminal stack-repair bridge diagnostics for issues #797, #798, and #799.

**Architecture:** Reuse existing scorer, source parser, select-order summary, and frame-transform command paths. The patch adds small validation and diagnostic helpers, not new CLI commands or inline heavy scoring.

**Tech Stack:** Python, Typer CLI, pytest, existing `src.mwcc_debug.source_patch.find_function`, existing `debug mutate frame-transform-search`.

---

## File Structure

- Modify `tools/melee-agent/src/search/structure_scoring.py` for retained seed validation.
- Modify `tools/melee-agent/tests/search/test_structure_scoring.py` for retained seed and rejection regressions.
- Modify `tools/melee-agent/src/cli/debug/__init__.py` for inline drift fallback and terminal stack-repair lane diagnostics.
- Modify `tools/melee-agent/tests/test_select_order_search.py` for select-order summary regressions.
- Add this plan and the matching spec under `docs/superpowers/`.

## Task 1: Retained Seed Structure Scoring

**Files:**
- Modify: `tools/melee-agent/src/search/structure_scoring.py`
- Test: `tools/melee-agent/tests/search/test_structure_scoring.py`

- [x] **Step 1: Write the failing retained seed test**

Add a test where `source_path` is `diagnostics/seed.c`, the generated variant is `diagnostics/generated.c`, both contain `fn_80000000`, and the real TU is `src/melee/demo.c`. Assert the generated candidate compiles and the real TU is restored.

- [x] **Step 2: Write the in-tree rejection test**

Add a test where `source_path` is an existing wrong in-tree file such as `src/melee/other.c` with a function body. Assert `score_structure_variants` raises `ValueError` with `source mismatch`.

- [x] **Step 3: Run red tests**

Run:

```bash
python -m pytest \
  tools/melee-agent/tests/search/test_structure_scoring.py::test_score_structure_variants_accepts_retained_seed_distinct_from_candidate \
  tools/melee-agent/tests/search/test_structure_scoring.py::test_score_structure_variants_rejects_wrong_in_tree_source_path \
  -q
```

Expected: both fail before production changes.

- [x] **Step 4: Implement retained seed validation**

Import `find_function` from `src.mwcc_debug.source_patch`. Replace the retained-source regex check with parser-based validation. Accept a mismatched source if it is an existing `.c` outside `melee_root/src` and `find_function(text, function)` returns a span.

- [x] **Step 5: Run structure scoring tests**

Run:

```bash
python -m pytest tools/melee-agent/tests/search/test_structure_scoring.py -q
```

Expected: all structure scoring tests pass.

## Task 2: Inline-Boundary Unmapped Source Attribution

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [x] **Step 1: Write the failing unmapped drift test**

Create a retained source whose compact function hunk has only signature/declarations but whose body contains executable statements later. Build a guarded inline-boundary candidate and assert `inline_boundary_drift` includes:

- `source_attribution_status == "unmapped"`
- `terminal_blocker == "source-hunk-no-executable-lines"`
- non-empty `nearest_executable_source_spans`
- `next_probe.kind == "score-retained-inline-boundary-source"`
- `--score` in the next probe command.

- [x] **Step 2: Run the red drift test**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_inline_boundary_drift_reports_unmapped_source_spans -q
```

Expected: fails because the fields do not exist.

- [x] **Step 3: Implement executable span fallback**

Add helpers that use `find_function` to scan the function body, strip comments through existing source-line filtering, and return up to two line-numbered executable spans. Update `_select_order_inline_boundary_drift_summary` to set the unmapped blocker and next probe only when executable lines are empty.

- [x] **Step 4: Run select-order drift tests**

Run:

```bash
python -m pytest \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_summary_localizes_inline_boundary_drift \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_inline_boundary_drift_uses_executable_source_lines \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_inline_boundary_drift_reports_unmapped_source_spans \
  -q
```

Expected: all pass.

## Task 3: Terminal Stack-Repair Frame Lane

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [x] **Step 1: Write the failing frame lane test**

Extend the terminal bridge tests with a stack-layout candidate whose `objective.frame_delta` is non-zero. Assert `terminal_next_lane.frame_repair_lane` includes:

- `status == "blocked"`
- `terminal_blocker == "frame-transform-not-materialized"`
- `candidate_frame_delta`
- `frame_reservation_bytes_hint`
- a command containing `debug mutate frame-transform-search`, `--source-file`, `--frame-reservation-bytes`, and `--json`.

- [x] **Step 2: Run the red frame lane test**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_source_bridge_reports_terminal_frame_repair_lane -q
```

Expected: fails because `frame_repair_lane` does not exist.

- [x] **Step 3: Implement frame repair lane diagnostics**

Add a helper called from `_select_order_source_bridge_terminal_next_lane`. It should collect stack-layout candidates, compute absolute frame reservation hints from `objective.frame_delta`, build durable output-dir hints when a campaign/base source is available, and preserve existing `actions`.

- [x] **Step 4: Run terminal bridge tests**

Run:

```bash
python -m pytest \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_source_bridge_reports_terminal_recombine_lane \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_source_bridge_single_terminal_candidate_has_action \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_source_bridge_reports_terminal_frame_repair_lane \
  -q
```

Expected: all pass.

## Task 4: Verification and Issue Closure

**Files:**
- No production code changes beyond Tasks 1-3.

- [x] **Step 1: Run focused suite**

Run:

```bash
python -m pytest tools/melee-agent/tests/search/test_structure_scoring.py tools/melee-agent/tests/test_select_order_search.py -q
```

Expected: all pass.

- [x] **Step 2: Run CLI smoke checks**

Run:

```bash
python -m py_compile tools/melee-agent/src/search/structure_scoring.py tools/melee-agent/src/cli/debug/__init__.py
melee-agent debug search structure --help >/dev/null
melee-agent debug select-order-search --help >/dev/null
melee-agent debug mutate frame-transform-search --help >/dev/null
```

Expected: all commands exit 0.

- [ ] **Step 3: Commit, refresh editable install, resolve issues**

Stage only this task's hunks because `/Users/mike/code/melee` has unrelated dirty files. Commit the spec, plan, tests, and production changes. Then run:

```bash
python -m pip install -e tools/melee-agent
DECOMP_AGENT_ID=codex-issue-resolver-3 melee-agent issue resolve 797 --note "fixed in <commit>"
DECOMP_AGENT_ID=codex-issue-resolver-3 melee-agent issue resolve 798 --note "fixed in <commit>"
DECOMP_AGENT_ID=codex-issue-resolver-3 melee-agent issue resolve 799 --note "fixed in <commit>"
melee-agent issues list
```

Expected: editable install imports `/Users/mike/code/melee`; no unresolved issue remains from this root-cause set.
