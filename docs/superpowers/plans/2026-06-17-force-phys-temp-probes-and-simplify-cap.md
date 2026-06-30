# Force-Phys Temp Probes And Simplify Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Resolve issues #751, #752, and #753 by adding the missing force-phys source probe families and making bounded simplify-order searches return immediately after the compile cap.

**Architecture:** Extend existing transform-corpus families rather than adding new CLI commands. Keep all new source edits as exact-span `Anchor` replacements through the current mutator dispatcher. Fix the simplify cap at the search-driver loop boundary.

**Tech Stack:** Python, Typer CLI, pytest, existing `melee-agent` transform-corpus and simplify-search modules.

---

### Task 1: Simplify Search Cap

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/simplify_search.py`
- Test: `tools/melee-agent/tests/test_mwcc_debug_simplify_search.py`

- [x] **Step 1: Write the failing test**

Add `test_search_does_not_enter_later_sources_after_max_candidates` and `test_search_does_not_pull_same_source_after_max_candidates` near the existing max-candidate tests. The first covers later source entry after a one-variant cap; the second covers an active adapter that would fail if the driver asks it for a post-cap next candidate.

- [x] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_mwcc_debug_simplify_search.py::test_search_does_not_enter_later_sources_after_max_candidates -q`

Expected: FAIL because the second source is entered after the cap is reached.

- [x] **Step 3: Implement the cap guard**

In `search()`, check `compiled >= max_candidates` before entering each source adapter and before pulling the next variant from an active adapter. Preserve duplicate deduplication so repeated variants do not consume compile slots.

- [x] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_mwcc_debug_simplify_search.py::test_search_does_not_enter_later_sources_after_max_candidates -q`

Expected: PASS.

### Task 2: FPR Product Temp Probes

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus/registry.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus/orchestrator.py`
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Test: `tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py`
- Test: `tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py`

- [x] **Step 1: Write failing tests**

Add tests asserting DrawCellNumber-style source emits `steer_fpr_product_temp_split` and `steer_fpr_paired_product_temp_split`, with candidate text that introduces product temp locals and payload metadata for product locals and expressions.

- [x] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py::test_coloring_register_steering_emits_product_temp_split_variants tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py::test_coloring_register_steering_metadata_is_executable -q`

Expected: FAIL because the mutator keys are absent.

- [x] **Step 3: Implement anchors and dispatch**

Add conservative product-temp anchor generators beside the existing FPR product steering helpers. Register the new mutator keys in the family metadata, direct steering key allow-list, and mutator dispatcher.

- [x] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py::test_coloring_register_steering_emits_product_temp_split_variants tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py::test_coloring_register_steering_metadata_is_executable -q`

Expected: PASS.

### Task 3: Indexed Byte Index Temp Probes

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus/indexed_byte_address.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus/registry.py`
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Test: `tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py`
- Test: `tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py`

- [x] **Step 1: Write failing tests**

Add tests asserting SortNames-style source emits `steer_indexed_byte_index_temp`, with candidate text that assigns an `int` index temp and still reads `mnDiagram_804A076C.sorted_names[index_temp]`. Include a condition-expression fixture capped at eight probes to match the reported command budget.

- [x] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py::test_indexed_byte_address_temp_generates_index_lifetime_temp tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py::test_indexed_byte_address_temp_metadata_is_executable -q`

Expected: FAIL because the mutator key is absent.

- [x] **Step 3: Implement anchors and dispatch**

Add guarded index-temp anchors for assignment and general expression reads. Reject side-effecting index expressions and reuse the exact-span replacement path.

- [x] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py::test_indexed_byte_address_temp_generates_index_lifetime_temp tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py::test_indexed_byte_address_temp_metadata_is_executable -q`

Expected: PASS.

### Task 4: Integration Verification

**Files:**
- No new production files unless tests expose gaps.

- [x] **Step 1: Run focused tests**

Run: `PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_mwcc_debug_simplify_search.py tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py -q`

Expected: PASS.

- [x] **Step 2: Run CLI probe smokes**

Run the reported select-order commands with `--no-compile-probes --json` and confirm probe metadata includes the new product-temp and index-temp mutator keys.

- [x] **Step 3: Refresh editable install and resolve issues**

Run `python -m pip install -e tools/melee-agent`, verify `/opt/homebrew/bin/melee-agent` imports from `/Users/mike/code/melee`, resolve only #751, #752, and #753, then confirm `melee-agent issues list` is empty or contains only blocked/unrelated work.
