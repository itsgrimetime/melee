# Issue 896: Case C2 Row/Col Sticky-Pool Repair

## Problem

`mnDiagram_DrawCellNumber` can reach a normalized structural match while two
expression-scored FPR anchors remain swapped: `col_offset` wants the FPR held by
`row_offset`, and `row_offset` wants the FPR held by `col_offset`. First
divergence classifies this as Case C2, where the target register needs to be in
the sticky nonvolatile pool by the row expression's allocation turn.

The existing `mixed-pcode-fpr-lifetime` focus only materialized probes for a
narrow row-adjust-owner plus digit-call shape. Live row/col source can lack that
shape while still exposing precise `expression_score` anchors and while the
existing expression-interferer source generator can build bounded row/product
repair candidates.

## Design

Use the existing expression-interferer repair backend as the reusable source
lever for the mixed-pcode lifetime focus:

- Detect pure expression-score register swaps with no residual payload and name
  them as Case C2 sticky-pool/source-order blockers.
- Preserve the existing mixed-pcode transform behavior when its narrow source
  anchors are present.
- When the narrow mixed-pcode family has no anchors, fall back to
  `generate_source_repair_candidates` and expose those candidates through the
  same `mixed_pcode_fpr_lifetime_pressure_repair` transform-corpus family.
- Emit exact function-replacement anchors using the existing
  `steer_mixed_pcode_fpr_lifetime_pressure` mutator, so generated probes keep
  stale-span validation and the normal lifetime-layout scoring pipeline.

## Validation

Regression coverage:

- `expression-interferer-repair` terminal summaries infer a Case C2 blocker from
  a row/col expression-register swap and pass that blocker into source
  generation.
- `lifetime-layout --focus mixed-pcode-fpr-lifetime` emits row/product source
  probes for a live-style row/col source shape instead of returning
  `transform-corpus-no-source-anchors`.
- Existing mixed-pcode source shapes still use the original anchors, and truly
  unsupported source still reports the empty-probe terminal summary.
