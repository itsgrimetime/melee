# Sticky-Pool Source Probes Implementation Plan

> For agentic workers: use subagent-driven development for implementation and
> review checkpoints. This plan intentionally avoids a human approval gate
> because the issue owner delegated decisions for this automation run.

## Goal

Resolve #774 and #775 by extending existing directed transform families with
ranked source probes that target allocator sticky-pool / upstream dispense
pressure after the first Case C probe set was exhausted.

## Design

Keep all work inside the existing transform corpus:

- `indexed_byte_address_temp_steering` owns Sort indexed-byte address probes.
- `coloring_register_steering` owns Draw FPR register-steering probes.
- Reuse existing validated-span mutator keys where possible. If a distinct
  mutator key is added, update `mutators.py`, `registry.py`,
  `source_transform_catalog.py`, and the relevant drift tests together.

The new probes must preserve the conservative expression forms the issue reports
call out. Do not materialize `&array[index]` element pointers for Sort, and do
not move side-effecting calls across other side-effecting statements for Draw.

## Task 1: Sort Implicit-Base Sticky Probes (#774)

Files:

- `tools/melee-agent/src/search/directed/transform_corpus/indexed_byte_address.py`
- `tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py`

Steps:

- [x] Add failing tests that require early implicit-store variants for:
  - long-lived final-store base owner temp, initialized from the proven `dst`
    base before the init loop, used by `dst_iter`, and used again in
    `base_temp[i] = temp`;
  - direct-global base-owner temp initialized from
    `mnDiagram_804A076C.sorted_names`, used by `dst_iter`, and used again in the
    final store;
  - final-store direct-global base plus index-owner temp, using
    `mnDiagram_804A076C.sorted_names[store_idx] = temp`;
  - loop-index owner for the init loop, assigning `init_idx = n` and using
    `dst[init_idx] = (u8) n` inside one combined init/totals loop with unchanged
    `tp++` and `*tp = mnDiagram_SumNameKOs(...)`.
- [x] Verify the new tests fail because the strategies are absent.
- [x] Implement narrow detectors from existing proven `dst`/global alias logic.
- [x] Ensure no candidate emits `&mnDiagram_804A076C.sorted_names[i]`.
- [x] Ensure the new strategies are yielded before broader loop rewrites under
  low `max_per_family` budgets.

## Task 2: Draw y_offset Sticky Probes (#775)

Files:

- `tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`
- `tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py`

Steps:

- [x] Add failing tests that require FPR Case C sticky variants for:
  - hoisting simple cast/product setup statements from between `y_offset` and
    `row_offset` to immediately before `y_offset`;
  - moving simple cast/product setup statements after the first dependent
    product to change y_offset/row_offset overlap without moving calls;
  - recomputing `row_offset_adj` directly from the product expression while
    preserving `row_offset = y_offset * rowf`.
- [x] Verify the new tests fail because the strategies are absent.
- [x] Implement only top-level, unique-span statement moves with data-dependency
  proof: crossed statements must be local scalar assignments, read/write
  independent of `y_offset`, `row_offset`, and each other, and must not contain
  calls, globals, members, indexed expressions, volatile, increments, control
  flow, preprocessor lines, or labels.
- [x] Reuse the existing `steer_fpr_case_c_temp_order` validated-span mutator
  unless distinct registry metadata is needed.
- [x] Keep the existing split/combined y_offset support and unsafe operand
  rejections intact.

## Task 3: Verification And Closure

- [ ] Run focused transform-corpus tests for both files.
- [ ] Run the full `test_select_order_search.py` file to preserve #773.
- [ ] Run command-level smoke checks for `debug search plan-transforms` or
  `debug search directed`/`debug select-order-search` with bounded probe counts
  against the affected functions when local artifacts are available.
- [ ] For #774/#775, collect residual first-divergence before/after evidence
  for the top ranked new probes, or explicitly document the non-source-actionable
  allocator-wall stop condition if no generated probe reaches the requested
  force assignment.
- [ ] Commit the code and this plan.
- [ ] Refresh the editable `melee-agent` install from `/Users/mike/code/melee`.
- [ ] Resolve #774 and #775 from this plan with notes tied to the commit and
  verification output. Resolve #773 separately from its restore-guard fix.
