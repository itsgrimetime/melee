# Symbolic Local And Complement Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix #802 and #803 by preserving current symbolic stack-local evidence and reporting downhill FPR complement repair outcomes.

**Architecture:** Extend the existing frame model with symbolic `addi rX,r1,symbol` address traces, then let current stack objects and outgoing-floor attribution consume that evidence. Extend select-order guard repair summaries with a derived complement section that compares repair candidates against protected seed FPR hits.

**Tech Stack:** Python, Typer CLI internals, pytest, existing `melee-agent` debug modules.

---

### Task 1: Current Symbolic Local Address Attribution

**Files:**
- Modify: `tools/melee-agent/tests/test_frame_reservations.py`
- Modify: `tools/melee-agent/src/mwcc_debug/frame_reservations/__init__.py`

- [x] **Step 1: Write the failing regression test**

Add `test_frame_reservation_resolves_symbolic_addi_local_area_as_current_source_object`. Use final pcode with `addi r25,r1,totals`, `stw r28,0(r25)`, `addi r30,r1,totals`, and `lwzx r0,(r30,r0)`. Provide current and expected asm with concrete `addi ..., r1, 0x18`. Assert the current frame has an address-taken object for `totals`, the object records derived symbolic accesses for `0(r25)` and `(r30,r0)`, the false `outgoing_parameter_area_floor` disappears, and `frame_first_divergence.cause_hypothesis.kind` is not `local-area-vs-outgoing-floor-divergence`. Add `test_frame_reservation_leaves_unresolved_symbolic_addi_unmaterialized` to prove unresolved address materialization is reported but does not synthesize a stack object.

- [x] **Step 2: Verify the test fails**

Run:

```bash
pytest tools/melee-agent/tests/test_frame_reservations.py::test_frame_reservation_resolves_symbolic_addi_local_area_as_current_source_object -q
```

Expected initial result: failure because symbolic `addi rX,r1,totals` is not resolved into a current source object.

- [x] **Step 3: Implement symbolic address traces**

In `tools/melee-agent/src/mwcc_debug/frame_reservations/__init__.py`, add a helper that recognizes `addi rX,r1,<symbol>`. When `<symbol>` resolves through the existing symbolic offset map, append an address trace with `symbolic_home`, `original_operands`, and `resolved_operands`, and remember `rX` as a symbolic base register. Preserve unresolved symbolic address materializations in `unresolved_symbolic_homes`.

- [x] **Step 4: Carry symbols onto address-taken objects**

Update `_address_taken_ranges` and `_stack_objects` so address-taken ranges collect `source_symbols`, first access metadata, derived symbolic accesses through the remembered base register, and expected offsets from symbolic address traces.

- [x] **Step 5: Harden symbolic base alias lifetimes**

Add regressions proving derived symbolic accesses are not attributed after ordinary register clobbers, `lmw` multi-register clobbers, or call-clobbered volatile registers. Invalidate remembered symbolic base registers when instructions define those registers.

- [x] **Step 6: Run focused frame tests**

Run:

```bash
pytest tools/melee-agent/tests/test_frame_reservations.py::test_frame_reservation_resolves_symbolic_addi_local_area_as_current_source_object tools/melee-agent/tests/test_frame_reservations.py::test_frame_reservation_leaves_unresolved_symbolic_addi_unmaterialized tools/melee-agent/tests/test_frame_reservations.py::test_frame_reservation_attributes_same_frame_local_area_to_source_array -q
```

Expected result: both pass.

### Task 2: Downhill Complement Guard-Repair Reporting

**Files:**
- Modify: `tools/melee-agent/tests/test_select_order_search.py`
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`

- [x] **Step 1: Write the failing complement summary test**

Add `test_select_order_guard_repair_summary_reports_downhill_complement_ceiling`. Build a ranked seed with achieved registers `{32: 28, 33: 26, 39: 29, 40: 29}` and two repair candidates sharing the same `repair_seed_label`: one preserves all protected hits but remains guard-rejected with inline-boundary drift, and one has `guard_accepted=True` but `force_phys_satisfied_count=0`. Assert `guard_repair_summary.downhill_complement.status == "terminal-complement-ceiling"`, records `protected_registers`, reports no preserving structural repair, and exposes `best_preserving_candidate.guard_accepted is False` plus `best_structural_candidate.guard_accepted is True` with zero preserved protected hits.

- [x] **Step 2: Verify the test fails**

Run:

```bash
pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_summary_reports_downhill_complement_ceiling -q
```

Expected initial result: failure because the summary lacks `downhill_complement`.

- [x] **Step 3: Implement complement summary helpers**

Add helpers beside the guard-repair summary functions to group repair candidates by `repair_seed_label`, recover seed protected hits from candidate summaries and/or the guard-repair ledger, compute preserved hit counts for each repair candidate, and classify outcomes as `repair-preserves-protected-hits`, `repair-trades-off-protected-hits`, or `terminal-complement-ceiling`.

- [x] **Step 4: Attach complement summary to guard repair output**

Call the helper from `_select_order_guard_repair_summary` and include `downhill_complement` in the JSON summary. Keep existing `status`, `repair_candidates`, and `lanes` fields backward compatible.

- [x] **Step 5: Cover no-accepted-repair terminal ceiling**

Add a regression where all guard repair candidates remain guard-rejected while preserving protected hits. Assert the complement summary still reports `terminal-complement-ceiling` with best preserving and structural candidates.

- [x] **Step 6: Run focused select-order tests**

Run:

```bash
pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_summary_reports_downhill_complement_ceiling tools/melee-agent/tests/test_select_order_search.py::test_select_order_search_guard_repair_beam_expands_rejected_allocator_hit -q
```

Expected result: both pass.

### Task 3: Verification, Install Refresh, Commit, And Issue Resolution

**Files:**
- Verify: `tools/melee-agent/tests/test_frame_reservations.py`
- Verify: `tools/melee-agent/tests/test_select_order_search.py`

- [x] **Step 1: Run narrow regressions**

Run:

```bash
pytest tools/melee-agent/tests/test_frame_reservations.py tools/melee-agent/tests/test_select_order_search.py -q
```

Expected result: pass.

- [x] **Step 2: Run CLI smokes**

Run:

```bash
melee-agent debug inspect frame-reservations --help >/tmp/frame-reservations-help.txt
melee-agent debug select-order-search --help >/tmp/select-order-help.txt
```

Expected result: both commands exit 0.

- [x] **Step 3: Refresh editable install**

Run:

```bash
python -m pip install -e tools/melee-agent
```

Expected result: `/opt/homebrew/bin/melee-agent` imports from `/Users/mike/code/melee/tools/melee-agent`.

- [x] **Step 4: Commit and resolve issues**

Commit the spec, plan, tests, and implementation. Resolve #802 and #803 only after the tests and smokes pass.
