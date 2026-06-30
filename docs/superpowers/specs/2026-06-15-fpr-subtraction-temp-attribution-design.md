# FPR Subtraction Temp Attribution Design

## Goal

Issue #727 asks `node-set-split` to handle coupled residuals where one missing
virtual is source-bound and the other is a compiler-generated temp. Current
`master` already has introduce-binding and coupled candidate composition. The
original report's `mnDiagram_80241E78` FPR evidence included a raw pcode source:

```text
fsubs f33,f38,f50
```

Because that source has no C expression or type, `node-set-split` cannot turn it
into either a bindable request or an introduce-binding request.

The goal of this slice is to map safe FPR subtraction temps back to existing
typed C local assignments, so the existing node-set-split pipeline can generate
coupled candidates without adding a second realizer.

## Current Evidence

The original issue evidence showed:

- `ig32`/`ig33`: one bindable float local and one raw `fsubs` temp.
- `ig39`: raw `lfs f39,60(r47)`, untyped, not bindable.

The current source contains the directly corresponding local:

```c
row_offset = y_offset * (f32) row;
row_offset_adj = row_offset - 0.4f;
```

`virtual_attribution` already maps ranked `fmuls` virtuals to floating local
assignments (`fpr-expression-order`). It does not map `fsubs`, and the ranker
would be wrong if it counted compiler-generated integer-to-float conversion
`fsubs` instructions. That is the narrow gap.

Fresh post-refresh live evidence can differ from the original stale-cache
residual. In the verified run for this slice, direct inspection of virtual
`f38` proves the subtraction temp maps to `row_offset_adj`, while current
`solve coloring` residuals for `mnDiagram_80241E78` have shifted to two
bindable product locals plus a conservative raw `lfs` temp. The closure note
must not claim that `row_offset_adj` itself was part of the current coupled
node-set residual.

The GPR half of #727 (`mnDiagram_8023FC28`, `add r44,r48,r35`) is different:
it is an address cursor synthesized from base/index virtuals. Existing
inspection does not safely bind the base and index to a unique source expression.
This slice must not guess that mapping. It should leave that case as structured
triage unless a later backend/source bridge can prove it.

## Selected Design

Extend the existing FPR expression-order attribution in
`tools/melee-agent/src/mwcc_debug/virtual_attribution.py`.

1. Add `fsub` and `fsubs` to the FPR source-expression operator map.
2. Teach the FPR ranker to skip conversion-only subtracts. A subtraction is
   conversion-only when both operands were just produced by constant/stack `lfd`
   setup in the same block and the destination is a temporary used as a cast
   operand. The implementation should use a conservative helper and abstain
   when unsure.
3. Include simple compound floating subtraction assignments as source
   candidates:

   ```c
   y_offset -= base;
   ```

   is treated as expression `y_offset - base`, with name/type from `y_offset`.
4. Keep all existing type guards. Only unique floating scalar locals/params
   (`float`, `f32`, `double`, `f64`) are accepted.

This changes only attribution. Existing `request_from_node_set_delta`,
`generate_coupled_node_set_split_patches`, and CLI routing should consume the
richer source metadata unchanged.

Also tighten introducible-request eligibility so typed expressions that are
unsafe to bind (for example call expressions) do not enter coupled mode and
then fail later with zero generated patches.

## Non-Goals

- No GPR address-cursor inference in this slice.
- No pcode-to-C decompiler.
- No automatic source edit to `src/melee`.
- No weakening of introduce-binding safety rules.

## Tests

Add TDD regression coverage before production changes:

- `test_explain_virtuals_binds_fpr_subtraction_to_float_local_assignment`
  proves a pcdump with normal `fsubs` assignments plus conversion `fsubs` maps
  the real local assignment to a typed source.
- `test_node_set_delta_can_include_fpr_subtraction_temp_after_attribution`
  proves a `node_set_delta` shaped like the live `mnDiagram_80241E78` residual
  becomes a coupled request set with both `col_offset` and `row_offset_adj`.
- `test_requests_from_node_set_delta_rejects_unsafe_introducible_entries`
  proves typed call expressions are filtered before coupled composition.
- Negative tests keep raw pcode output for ambiguous or non-floating
  subtraction expressions.

## Live Verification

After implementation:

```bash
melee-agent debug solve coloring -f mnDiagram_80241E78 --class fpr --json
melee-agent debug solve node-set-split --coupled --node-set-delta <json> --json --budget 180 --max-candidates 0
melee-agent debug solve coloring -f mnDiagram_8023FC28 --class gpr --json
melee-agent debug solve node-set-split --coupled --node-set-delta <json> --json --budget 120 --max-candidates 0
```

#727 can be resolved if the FPR path now emits/evaluates coupled candidates and
the GPR path is recorded as not safely source-inferable from current evidence,
or if one of the live runs finds a verified improving candidate.
