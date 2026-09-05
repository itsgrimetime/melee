# Issue 884: Mixed Pcode/FPR Lifetime Pressure Repair

## Scope

Resolve issue #884 by adding a source-actionable `lifetime-layout` lane for the
retained `mnDiagram_DrawCellNumber` frontier where `row_offset`,
`row_offset_adj_owner_fpr`, and a digit call-argument FPR temp combine to keep
extra FPR pressure around `f25`.

This is intentionally narrower than issue #883. It does not implement broad
dual-frontier expression-vs-structure reconciliation.

## Root Cause

The tooling already had separate probes for:

- pcode-only FPR fsubs/cast-owner assignments,
- pcode-only FPR call-argument temps,
- generic lifetime/layout declaration and call-argument perturbations.

It did not have a composed transform family for the retained source shape:

- `row_offset_adj_owner_fpr = row_offset - 0.4f;`
- `row_offset_adj = row_offset_adj_owner_fpr;`
- `rowf = (f32) digit;`
- `HSD_JObjReqAnimAll(jobj, rowf);`
- paired `HSD_JObjSetTranslateY` calls for `row_offset` and `row_offset_adj`.

As a result, `lifetime-layout` spent probe budget on generic source moves or
standalone pcode probes instead of the mixed `f32/f39` and `f36/f39` pressure
window.

## Implemented Design

Added transform family `mixed_pcode_fpr_lifetime_pressure_repair` with mutator
key `steer_mixed_pcode_fpr_lifetime_pressure`.

The family generates bounded exact-span candidates:

- direct adjusted translate use of `row_offset_adj_owner_fpr`,
- branch-local adjusted translate temp,
- fresh digit call-argument temp,
- composed adjusted-temp plus fresh digit-callarg candidate.

`debug mutate lifetime-layout --focus mixed-pcode-fpr-lifetime` now selects this
transform family directly and reserves probe budget for it unless the caller
also supplies native lifetime-layout `--operator` filters.

Objective metadata now reports:

- `saved_f25_removed`,
- `frame_reaches_168`,
- `target_pair_improved`,
- `target_pair_all_clear`.

## Verification

The retained frontier list smoke generated four mixed transform probes for the
real #884 source and no generic filler probes. Compile-scoring those retained
external-source candidates against the main checkout did not succeed because the
diagnostic source came from a separate worktree; the generated candidate sources
were retained for follow-up inspection.
