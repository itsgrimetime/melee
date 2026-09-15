# Issue 899 Sticky-Pool Row Fsubs Repair Spec

## Problem

The Case C2 sticky-pool bridge can identify a product/row register swap, but
the handoff was still routing agents toward broad support-order probes such as
`34 < 32` and `46 < 32`. In the reported `mnDiagram_DrawCellNumber` case those
orders were already true in the baseline allocation, so they could not explain
or repair the remaining row/column FPR swap.

The same report also exposed a row owner blocker:

```c
row_offset = HSD_JObjGetTranslationY(jobj2) - base;
```

The window-order source bridge rejected that RHS through the generic local
float split safety filter because it contains a function call. That global rule
is still correct, but this narrow whitelisted call-minus-local row fsubs shape
needs either source probes with expression-score validation or a specific safety
blocker.

## Requirements

- Keep existing `target_virtuals` payloads for compatibility.
- Add structured sticky-pool target groups that distinguish verification-only
  support-before-product orders from actionable C2 row/product orders.
- Do not claim progress from structural similarity alone. Row fsubs owner probes
  require expression-score validation.
- Do not globally allow splitting arbitrary function-call RHS expressions.
- Replace generic terminal handoffs like `local-source-owner-unsupported-rhs`
  and `transform-family-exhausted` for this class with either concrete probes or
  a named row-fsubs safety/validation blocker.

## Design

The bridge derives target groups from the product anchor:

- support operands before product: verification route, baseline-satisfied checks
- product before paired row: primary C2 row/column crossing
- product before support operands: inverse-support exploration

The row fsubs path recognizes only:

```c
HSD_JObjGetTranslationY(simple_local) - simple_local
```

with a local float owner and, when available, an `fsubs` first-def. It emits
owner probes that materialize either the call result or the whole subtraction
into a temporary. Probe metadata carries `requires_expression_score_validation`
so downstream summaries do not treat the hunk as accepted until the protected
expression score moves.

## Review

An independent Codex planning subagent reviewed the issue artifacts and wrote
the detailed plan at:

`/Users/mike/.claude/plans/fix-899-sticky-pool-support-row-fsubs.md`
