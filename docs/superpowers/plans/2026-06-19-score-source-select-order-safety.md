# Score-Source Safety and Select-Order Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix issues #834 and #835 by making local score-source retries lane-safe and by ranking select-order candidates by semantic force-phys movement rather than spill-only score drops.

**Architecture:** Reuse `mwcc_debug.local_safety` for scorer-compatible preflight and post-timeout diagnostics. Extend `SelectOrderObjective` with baseline-relative force-phys assignment metadata and a semantic progress bucket used before spill/frame/match tie-breakers.

**Tech Stack:** Python, Typer CLI, pytest, existing `tools/melee-agent` modules.

---

## File Structure

- Modify `tools/melee-agent/src/cli/debug/__init__.py`: score-source guard payload helpers and timeout JSON metadata.
- Modify `tools/melee-agent/src/mwcc_debug/select_order_search.py`: assignment metadata, progress classification, ranking, and terminal rendering.
- Modify `tools/melee-agent/tests/test_debug_cli_reorg.py`: score-source unsafe-lane regressions.
- Modify `tools/melee-agent/tests/test_select_order_search.py`: select-order assignment/progress/ranking/render regressions.

### Task 1: Score-Source Lane Safety

**Files:**
- Modify: `tools/melee-agent/tests/test_debug_cli_reorg.py`
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`

- [ ] **Step 1: Write failing preflight guard test**

Add `test_target_score_source_refuses_unsafe_local_lane_before_launch` next to the existing score-source timeout tests. The test monkeypatches `debug_cli.local_safety.guard_local_pcdump_lane` to return a matching uninterruptible `LocalWiboProcess`, invokes:

```bash
debug target score-source <source> -f fn_80000000 --target <target> --timeout 0.25 --json
```

and asserts exit code 0, `score == 2**30`, `returncode == 124`, `unsafe_local_pcdump_lane.processes[0].pid == 4242`, and that no compiler runner was called.

- [ ] **Step 2: Run preflight guard test red**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_debug_cli_reorg.py::test_target_score_source_refuses_unsafe_local_lane_before_launch -q
```

Expected: FAIL because score-source launches the runner and emits no `unsafe_local_pcdump_lane`.

- [ ] **Step 3: Write failing timeout payload test**

Add `test_target_score_source_timeout_reports_unsafe_local_lane` next to the timeout test. The fake runner raises `subprocess.TimeoutExpired`; the first guard call returns safe and the second returns the matching uninterruptible process. Assert the JSON has `timeout_seconds`, `returncode`, and `unsafe_local_pcdump_lane.source == "src/melee/mn/sample.c"`.

- [ ] **Step 4: Run timeout payload test red**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_debug_cli_reorg.py::test_target_score_source_timeout_reports_unsafe_local_lane -q
```

Expected: FAIL because timeout JSON currently has only free-form stderr/error text.

- [ ] **Step 5: Implement lane guard**

In `score_source`, after `src_rel` and `cflags_unit_rel` are known and before constructing/launching `wibo`, call a helper equivalent to:

```python
lane_guard = local_safety.guard_local_pcdump_lane(
    source_rel=src_rel,
    function=function,
    allow_unsafe=local_safety.allow_unsafe_local_pcdump(),
)
```

If unsafe, return scorer-compatible penalty output and do not call the runner. Extend `_score_source_failure_payload` to accept `unsafe_lane` and include it as `unsafe_local_pcdump_lane`.

- [ ] **Step 6: Implement post-timeout scan**

When `proc.returncode == 124` and no pcdump was produced, rescan with `allow_unsafe=False` for the same `src_rel`. Include the structured unsafe-lane payload in JSON when matching processes remain.

- [ ] **Step 7: Run score-source tests green**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_debug_cli_reorg.py::test_target_score_source_refuses_unsafe_local_lane_before_launch tools/melee-agent/tests/test_debug_cli_reorg.py::test_target_score_source_timeout_reports_unsafe_local_lane tools/melee-agent/tests/test_debug_cli_reorg.py::test_target_score_source_timeout_uses_process_tree_runner -q
```

Expected: PASS.

### Task 2: Select-Order Force-Phys Progress

**Files:**
- Modify: `tools/melee-agent/tests/test_select_order_search.py`
- Modify: `tools/melee-agent/src/mwcc_debug/select_order_search.py`

- [ ] **Step 1: Write failing assignment/progress test**

Add `test_select_order_force_phys_assignments_are_baseline_relative`. It scores `MISSING_SECOND` with `proof_force_phys={32: 28, 33: 31}` and asserts `force_phys_progress_kind == "target-missing"`, `force_phys_assignments["33"]["status"] == "missing_or_coalesced"`, `baseline_actual == 30`, `actual is None`, and `changed is True`.

- [ ] **Step 2: Run assignment/progress test red**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_force_phys_assignments_are_baseline_relative -q
```

Expected: FAIL because the objective has no assignment map or progress kind.

- [ ] **Step 3: Write failing progress-vs-spill ranking/render tests**

Add `test_select_order_ranking_prefers_force_phys_progress_over_spill_only` with a baseline candidate that only removes spill virtual 45 and a candidate that moves virtual 32 closer to its requested physical register. Add `test_render_select_order_variant_shows_force_phys_progress_assignments` and assert the rendered output includes `progress=target-progress` and a compact assignment token such as `r32:r29->r28!=r27`.

- [ ] **Step 4: Run ranking/render tests red**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_ranking_prefers_force_phys_progress_over_spill_only tools/melee-agent/tests/test_select_order_search.py::test_render_select_order_variant_shows_force_phys_progress_assignments -q
```

Expected: FAIL because spill-only and progress candidates are not bucketed semantically and rendering lacks assignment details.

- [ ] **Step 5: Implement objective metadata**

Add a small frozen dataclass or tuple-based helper for force-phys assignment rows with `virtual`, `expected`, `baseline_actual`, `actual`, `baseline_status`, `status`, and `changed`. Add `force_phys_assignments`, `force_phys_baseline_distance`, `force_phys_distance_delta`, and `force_phys_progress_kind` to `SelectOrderObjective.to_dict()`.

- [ ] **Step 6: Implement progress classification and ranking**

Compute baseline and candidate distances from the same force-phys targets. Classify as `target-hit`, `target-progress`, `target-no-progress`, `spill-only`, `target-missing`, or `no-force-phys-targets`. Add the progress-rank value immediately after the exact-satisfaction bit in `_objective_sort_key`, before spill/frame/match tie-breakers.

- [ ] **Step 7: Implement rendering**

Extend the `force_phys:` line in `render_select_order_variant` with `progress=<kind>` and `assignments=<tokens>`, where tokens show baseline-to-candidate movement and missing/coalesced status.

- [ ] **Step 8: Run select-order tests green**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_force_phys_assignments_are_baseline_relative tools/melee-agent/tests/test_select_order_search.py::test_select_order_ranking_prefers_force_phys_progress_over_spill_only tools/melee-agent/tests/test_select_order_search.py::test_render_select_order_variant_shows_force_phys_progress_assignments tools/melee-agent/tests/test_select_order_search.py::test_select_order_score_tracks_force_phys_satisfaction tools/melee-agent/tests/test_select_order_search.py::test_select_order_ranking_prefers_near_force_phys_over_order_only -q
```

Expected: PASS.

### Task 3: Verification, Install Refresh, and Issue Resolution

**Files:**
- No new source files.

- [ ] **Step 1: Run narrow regression suite**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_debug_cli_reorg.py::test_target_score_source_refuses_unsafe_local_lane_before_launch tools/melee-agent/tests/test_debug_cli_reorg.py::test_target_score_source_timeout_reports_unsafe_local_lane tools/melee-agent/tests/test_debug_cli_reorg.py::test_target_score_source_timeout_uses_process_tree_runner tools/melee-agent/tests/test_select_order_search.py::test_select_order_force_phys_assignments_are_baseline_relative tools/melee-agent/tests/test_select_order_search.py::test_select_order_ranking_prefers_force_phys_progress_over_spill_only tools/melee-agent/tests/test_select_order_search.py::test_render_select_order_variant_shows_force_phys_progress_assignments -q
```

Expected: PASS.

- [ ] **Step 2: Run command smoke checks**

Run:

```bash
melee-agent debug target score-source --help >/tmp/score-source-help.txt
melee-agent debug select-order-search --help >/tmp/select-order-help.txt
```

Expected: both commands exit 0.

- [ ] **Step 3: Refresh editable install**

Run from `/Users/mike/code/melee`:

```bash
python -m pip install -e tools/melee-agent
python - <<'PY'
import src.cli.debug as debug_cli
print(debug_cli.__file__)
PY
```

Expected: the printed file is under `/Users/mike/code/melee/tools/melee-agent/src`.

- [ ] **Step 4: Commit and resolve issues**

Stage only the files modified for this plan and commit. Resolve #834 and #835 with notes that include the commit hash.
