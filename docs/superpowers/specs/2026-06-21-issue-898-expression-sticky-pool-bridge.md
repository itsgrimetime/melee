# Issue 898: Expression Sticky-Pool Bridge

## Problem

`mnDiagram_DrawCellNumber` is stuck on an expression-anchored FPR Case C2
row/column swap. The live expression score expects `col_offset` IG32 in f28 and
`row_offset` IG37 in f26, but the baseline keeps them swapped at f26/f28.

Issue 897 added expression-scored ranking, but all retained lifetime-layout and
expression-interferer probes still score `0/2`. The current terminal summary
only says this is a sticky-pool residual, leaving the matcher without concrete
next source or order targets.

## Requirements

- Enrich the existing C2 expression-register-swap blocker with a reusable
  `sticky_pool_bridge` payload.
- Derive the bridge from existing expression-score anchors and first-def
  operands, not from hard-coded artifact paths.
- Name the focus and paired anchors, their current/target FPRs, and upstream
  FPR operands of the focus expression when available.
- Emit non-pair-only follow-up targets for source, pressure, and select/order
  exploration; do not present `[37, 32]` or `[32, 37]` as the whole plan.
- Add source-generation probes for product operand ownership in the live
  `col_offset = y_spacing * (f32) col` shape:
  `col_cast_owner_fpr`, `y_spacing_owner_fpr`, and a combined operand-owner
  probe.

## Non-Goals

- Do not add a new CLI command in this issue.
- Do not claim a source candidate is accepted without expression-score
  validation.
- Do not change matcher source files.
