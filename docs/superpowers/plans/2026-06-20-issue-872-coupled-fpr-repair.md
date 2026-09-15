# Issue 872: Coupled FPR Coalesce/Product Repair

## Problem

`mnDiagram_DrawCellNumber` can reach the target FPR allocation under the same
source with a coupled force-phys proof, but the transform corpus currently
mostly emits isolated product/cast/lifetime candidates. The known clean source
shape needs two source-visible changes in one probe:

- split the `col_offset = y_spacing * (f32) col` product/conversion lifetime
- fence the digit-to-FPR value used by `HSD_JObjReqAnimAll`

Running those independently can improve one virtual while regressing another,
so the planner reports exhausted negative evidence without a source-actionable
combined candidate.

## Implementation Plan

1. Extend `coloring_register_steering` with a conservative coupled FPR anchor
   that pairs one source-bound FPR product assignment with one later FPR call
   argument conversion/owner assignment.
2. Materialize the candidate as an exact-span replacement through the existing
   transform-corpus mutator path. The payload must identify the product local,
   product temp, call function, call argument local, call-arg temp, and force
   assignments inherited from the family.
3. Keep the generator source-local and guarded:
   - one top-level product assignment with a unique span
   - one later call statement using a unique FPR local argument
   - optional immediately preceding FPR assignment to the call argument local
   - no generated `_product_fpr` inputs, duplicate spans, preprocessor regions,
     labels, macro-like statements, or address-taken locals
4. Register the new mutator key in directed dispatch, the transform family,
   the orchestrator direct-key allowlist, and the source transform catalog.
5. Add regression tests for a Draw-like source that contains both
   `col_offset = y_spacing * (f32) col` and `base = (f32) digit;`
   before `HSD_JObjReqAnimAll(jobj, base)`, plus a negative test that proves
   generated product temps are not recursively re-split.

## Verification

- Run the focused register-steering tests.
- Run the source-transform catalog tests.
- Smoke `melee-agent debug search plan-transforms` on `mnDiagram_80241E78`
  with the issue force-phys vector and confirm the new coupled strategy is
  emitted in JSON.
