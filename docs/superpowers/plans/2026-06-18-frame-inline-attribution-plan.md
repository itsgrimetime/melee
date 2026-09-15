# Frame And Inline Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add source-actionable attribution and ranking to select-order inline-boundary and frame local-area diagnostics.

**Architecture:** Preserve existing score/report pipelines and enrich their JSON payloads at existing summary points. Select-order keeps raw checkdiff payload private and emits compact drift evidence. Frame reservations accepts optional source context, adds a conservative local-array range bridge, and scores attributed local-area probes independently of frame-size deltas.

**Tech Stack:** Python, Typer CLI, pytest, existing `melee-agent` debug modules.

---

### Task 1: Select-Order Checkdiff Drift

**Files:**
- Modify: `tools/melee-agent/tests/test_select_order_search.py`
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`

- [x] **Step 1: Write the failing test**

Add a test near the existing inline-boundary drift tests that builds a guarded variant with `_checkdiff_payload` containing `classification.inline_boundary_artifact`, `diff`, `target_asm`, and `current_asm`. Assert the guard repair summary includes `inline_boundary_drift.checkdiff_drift.opcode_hunk`, the raw diff hunk, and expanded transform routes.

- [x] **Step 2: Run the focused test and verify it fails**

Run:

```bash
pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_inline_boundary_drift_includes_checkdiff_opcode_hunk -q
```

Expected initial failure: `checkdiff_drift` or the localized call hunk is missing.

- [x] **Step 3: Implement compact drift summarization**

In `tools/melee-agent/src/cli/debug/__init__.py`, copy `real_score.checkdiff_payload` into a private variant key, summarize raw unified diff and the first opcode/call mismatch, include the compact result in guard repair candidate summaries, pass force-phys and target-order context to repair route construction, and remove the private payload before final JSON output.

- [x] **Step 4: Run the focused test and verify it passes**

Run:

```bash
pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_inline_boundary_drift_includes_checkdiff_opcode_hunk -q
```

Expected: pass.

### Task 2: Frame Source-Array Range Attribution And Scoring

**Files:**
- Modify: `tools/melee-agent/tests/test_frame_reservations.py`
- Modify: `tools/melee-agent/src/mwcc_debug/frame_reservations/__init__.py`
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`

- [x] **Step 1: Write failing attribution and scoring tests**

Add a frame reservation test with source containing `u32 totals[0x78];` and address materialization. Add a frame-transform evaluation test proving a candidate that removes the attributed local-area floor wins over a neutral same-frame candidate.

- [x] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
pytest tools/melee-agent/tests/test_frame_reservations.py::test_frame_reservation_attributes_same_frame_local_area_to_source_array tools/melee-agent/tests/test_frame_reservations.py::test_frame_transform_scores_attributed_local_area_before_frame_size -q
```

Expected initial failure: source context is unsupported and local-area ranking is absent.

- [x] **Step 3: Implement source context attribution**

Add optional `source_text`, `source_path`, and `source_function_names` parameters to `analyze_frame_reservations`. Parse literal local arrays, compute primitive/pointer element sizes, detect address materialization evidence, and update unresolved anonymous expected address-taken divergences when a source array exactly matches the expected range and current low floor covers it.

- [x] **Step 4: Implement local-area transform scoring**

Add a local-area objective to `evaluate_frame_transform_probe_results` that measures remaining bytes of the attributed expected range still covered by the candidate low unused floor. Rank target-local-area-fixed candidates before neutral frame-size matches and carry transform force-phys target counts as supporting metadata.

- [x] **Step 5: Thread source context through CLI commands**

In `debug inspect frame-reservations`, `debug suggest frame`, and `debug mutate frame-transform-search`, auto-resolve the source file for the report function and aliases when available and pass source text/function aliases into `analyze_frame_reservations`. Keep existing CLI arguments compatible.

- [x] **Step 6: Run focused tests and verify they pass**

Run:

```bash
pytest tools/melee-agent/tests/test_frame_reservations.py::test_frame_reservation_attributes_same_frame_local_area_to_source_array tools/melee-agent/tests/test_frame_reservations.py::test_frame_transform_scores_attributed_local_area_before_frame_size -q
pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_inline_boundary_drift_includes_checkdiff_opcode_hunk -q
```

Expected: all pass.

### Task 3: Regression And Smoke Verification

**Files:**
- Verify only unless focused failures require fixes in files above.

- [x] **Step 1: Run narrow regression tests**

Run:

```bash
pytest tools/melee-agent/tests/test_select_order_search.py tools/melee-agent/tests/test_frame_reservations.py -q
```

Expected: pass.

- [x] **Step 2: Run CLI smoke checks**

Run:

```bash
melee-agent debug select-order-search --help >/tmp/select-order-help.txt
melee-agent debug inspect frame-reservations --help >/tmp/frame-reservations-help.txt
melee-agent debug suggest frame --help >/tmp/suggest-frame-help.txt
```

Expected: all exit 0.

- [x] **Step 3: Refresh editable install if CLI tooling changed**

Run the editable install refresh path from `/Users/mike/code/melee` so `/opt/homebrew/bin/melee-agent` imports this checkout.

- [x] **Step 4: Commit and resolve issues**

Commit the spec, plan, tests, and implementation. Resolve #800 and #801 only after tests and smoke checks pass.
