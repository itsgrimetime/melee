# Source Probe Safety And Shape Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix source-probe safety and structural guard regressions tracked by #786, #787, and #788.

**Architecture:** Keep validation at the generator/scorer boundaries already responsible for each workflow. Node-set-split filters invalid decl-order source before scoring, transform-corpus returns bounded node-set-delta plans by default, and source scoring/select-order output carries reusable checkdiff structural guard metadata.

**Tech Stack:** Python, Typer CLI, pytest, existing `tools/checkdiff.py`, melee-agent source tooling.

---

### Task 1: Node-Set-Split Decl-Order Source Rejections

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/source_patch.py`
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Modify: `tools/melee-agent/src/mwcc_debug/source_shape.py`
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_mwcc_debug_source_patch.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`
- Test: `tools/melee-agent/tests/search/solver/test_cli_solve.py`

- [x] Write a source-patch regression for UTF-8 text before the function so tree-sitter byte ranges are converted before Python string slicing.
- [x] Write a unit test showing `generate_node_set_split_patches()` emits valid decl-order patches with the UTF-8 prefix and does not duplicate local declarations.
- [x] Write a CLI test with a generated `CandidatePatch` carrying source rejection metadata and assert JSON output reports `objective_status == "source-rejected"` plus the rejection reason without retaining it under `compile_failed`.
- [x] Add minimal metadata support to `CandidatePatch` so source-rejection reason can flow without changing existing constructor callers.
- [x] Convert byte ranges in decl-order source slicing and keep a duplicate-local declaration safety check for malformed generated patches.
- [x] Teach solve-node-set-split scoring to convert source-rejected patches into `CandidateScore(status="source-rejected", compile_ok=False, score_reason=...)` without compiling.
- [x] Run the new source-patch, node-set-split, and CLI focused tests.

### Task 2: Bounded Node-Set-Delta Plan-Transforms

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus/orchestrator.py`
- Modify: `tools/melee-agent/src/search/cli/__init__.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`
- Test: `tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py`
- Test: `tools/melee-agent/tests/search/test_cli_smoke.py`

- [x] Write a regression test that monkeypatches an unrelated expensive anchor generator to raise, then calls `generate_transform_probes(..., node_set_delta=..., families=None)` and asserts the unrelated generator is never reached.
- [x] Add capped `max_candidates` node-set split/introduce-binding generation and stop before late slow families once the budget is filled.
- [x] Defer coupled node-set planning until singles fail to fill the remaining budget.
- [x] Add an early return after node-set-delta probe generation when no explicit families or scheduler target were requested.
- [x] Add a CLI regression for `plan-transforms --node-set-delta --write-probes --json` asserting bounded probe output plus `planning_summary.stop_condition`.
- [x] Preserve explicit-family behavior by continuing to enumerate requested families when `families` is passed.
- [x] Run the transform-corpus orchestrator and CLI focused tests.

### Task 3: Source Structural Guard For Target-Vector Scoring

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Modify: `tools/melee-agent/src/mwcc_debug/select_order_search.py`
- Test: `tools/melee-agent/tests/test_debug_cli_reorg.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [x] Write a test for a helper that converts checkdiff JSON into structural guard metadata with `shape_preserved`, `classification_primary`, `normalized_diff_lines`, `frame_delta`, and `rejection_reason`.
- [x] Write a select-order ranking test where a force-phys winner with `shape_preserved == False` ranks below a shape-preserving alternative.
- [x] Add optional checkdiff guard fields to `_SourceCandidateRealScore` and `_score_source_candidate_real_tree()`.
- [x] Add `--json` and `--checkdiff-guard/--no-checkdiff-guard` to `debug target score-source`, keeping the default integer output unchanged for permuter callers.
- [x] Attach structural guard metadata to select-order variants and beam ledger entries.
- [x] Demote guarded shape-drift variants in `rank_select_order_candidates()`.
- [x] Run focused debug CLI and select-order tests.

### Task 4: Verification, Commit, And Issue Resolution

**Files:**
- Commit all modified source, tests, spec, and plan files.

- [ ] Run focused pytest suites for node-set-split, transform-corpus orchestrator, score-source, and select-order.
- [ ] Run command-level smoke checks for `debug search plan-transforms --node-set-delta`, `debug target score-source --help`, and issue list/show.
- [ ] Refresh the editable `/opt/homebrew/bin/melee-agent` install from `/Users/mike/code/melee`.
- [ ] Resolve #786, #787, and #788 only if the matching regression and smoke evidence passed.
- [ ] Commit the completed batch on `master` and confirm `master` is clean except for pre-existing unrelated dirty files if they remain.
