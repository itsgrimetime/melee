# Issue 896 Case C2 Row/Col Sticky-Pool Plan

## Root Cause

`debug target score-source` can identify the relevant row/col FPR expression
anchors, but `debug mutate lifetime-layout --focus mixed-pcode-fpr-lifetime`
previously depended on a narrow transform-corpus source shape. When the live
source lacked that structural shape, the focus stopped with
`transform-corpus-no-source-anchors` even though `expression-interferer-repair`
could already build row/product source probes.

The terminal summary also did not infer a Case C2 blocker from a pure two-anchor
swap when no first-divergence residual payload was attached.

## Implementation

1. Add expression-score swap inference to
   `mwcc_debug.expression_interferer_repair`, so a focused anchor such as
   `col_offset` holding the paired anchor's expected FPR reports a Case C2
   sticky-pool/source-order blocker.
2. Reuse the existing expression-interferer source generator as the fallback
   repair backend for `mixed_pcode_fpr_lifetime_pressure_repair`.
3. Keep the existing mixed-pcode structural anchors preferred when present.
4. When no narrow structural anchors exist, expose expression-interferer
   row/product candidates as exact transform-corpus probes under the existing
   mixed-pcode family and `steer_mixed_pcode_fpr_lifetime_pressure` mutator.
5. Preserve unsupported-source behavior: sources with neither mixed-pcode nor
   row/product materialization still report the empty-probe terminal summary.

## Verification

Regression tests cover:

- Case C2 row/col expression-register swap inference.
- C2 blocker propagation into expression-interferer source generation.
- Lifetime-layout mixed-pcode fallback probe generation for live-style row/col
  source.
- Existing mixed-pcode structural probe generation.
- Existing empty-summary behavior for unsupported source.

Real-artifact smoke checks run against the `mnDiagram_DrawCellNumber` reporter
worktree showed:

- `expression-interferer-repair` reports the row/col Case C2 swap.
- `lifetime-layout --focus mixed-pcode-fpr-lifetime` emits fallback probes
  instead of an empty blocker.
- Compile/scoring retained four fallback probes; one candidate preserved the
  168-byte frame and removed the target row/col interference.
