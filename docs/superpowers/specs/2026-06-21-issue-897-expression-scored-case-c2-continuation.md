# Issue 897: Expression-Scored Case C2 Continuation

## Problem

After issue 896, `lifetime-layout --focus mixed-pcode-fpr-lifetime` can emit
Case C2 row/column source probes, but compiled results are ranked by
pressure/frame/match-percent signals alone. For `mnDiagram_DrawCellNumber`,
that surfaced candidates that kept the expression anchors at `0/2`.

One generated direct-row candidate also rewrote `row_offset_adj` after
`row_offset *= rowf`, effectively double-scaling the row while claiming to use
the unscaled row expression.

## Requirements

- Preserve the valid distinct-unscaled-local transform:
  `row_offset_adj = y_offset * rowf - 0.4f`.
- For adjacent self-scaled source:
  `row_offset *= rowf; row_offset_adj = row_offset - 0.4f;`
  generate the semantically valid order:
  `row_offset_adj = row_offset * rowf - 0.4f; row_offset *= rowf;`.
- Suppress the direct-row candidate when the self-scaled mutation and adjusted
  assignment are not the simple adjacent shape.
- Let `lifetime-layout` optionally expression-score compiled candidates with a
  target spec and baseline expression anchors.
- When expression scoring is available, demote pressure-only candidates with no
  expression-anchor progress so they are not reported as improved matcher
  candidates.

## Non-Goals

- Do not make expression scoring mandatory for all lifetime-layout runs.
- Do not broaden unrelated transform-corpus or validation-summary ranking.
- Do not change matcher source files.
