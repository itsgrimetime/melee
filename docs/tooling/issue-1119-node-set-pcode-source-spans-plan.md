# Issue 1119: Node-Set Pcode Source Spans

## Problem

`debug solve node-set-split` could not act on the
`mnDiagram2_HandleInput` node-set delta because several missing virtuals were
reported only as pcode load/store-address expressions:

- `lbz r36,72(r58)`
- `lwz r57,44(r113)`
- `lwz r58,44(r106)`
- copy/coalesce temps such as `mr r88,r53`

Those expressions named the allocator residue but not the C source span, field
type, or source line. The solver therefore stopped at "no bindable source
variable" instead of producing retained C probes.

## Design

Fix this at the attribution layer and keep the node-set split generator generic.

1. Add a reusable source-field attribution helper that can parse global
   declarations, local declarations, include-backed struct fields with offset
   comments, and simple assignment-based type refinements.
2. Teach virtual attribution to resolve pcode load chains recursively:
   `lwz base->field` can become a typed C expression, and dependent loads such
   as `lbz r36,72(r58)` can use the resolved base expression/type.
3. Propagate source attribution across simple copy/coalesce `mr` chains instead
   of dropping back to pcode-only diagnostics.
4. Let stale node-set deltas upgrade pcode-only source maps at request
   materialization time, so old issue artifacts remain usable after the fix.
5. Treat typed field expressions as introducible node-set requests, not blocked
   diagnostics.
6. Preserve evidence for retained generated probes: rows with source hunks and
   target-score hits should retain source and pcdump paths even when the final
   objective is a spill regression rather than a realized checkdiff win.

## Success Criteria

The reporter workflow is complete only when it produces one of:

- a retained scored source candidate that improves fresh checkdiff or hits a
  requested target register, with `source_hunks`, retained source, retained
  pcdump, and `target_score`; or
- a populated terminal proof showing the bounded candidate family was exhausted
  and naming the next source-level handoff.

For #1119 the bounded smoke command must resolve the stale pcode-only delta into
concrete typed source expressions for the mndiagram2 field loads and emit
retained full-function C probes.

## Tests

- Synthetic virtual-attribution regression for chained pcode loads resolving to
  named typed C fields and copy/coalesce source propagation.
- Synthetic node-set regression proving stale pcode-only source maps become
  introducible field-binding requests and generate C patches.
- Summary regression preserving plural `source_hunks`.
- CLI smoke on the original #1119 artifact verifying retained source, retained
  pcdump, `source_hunks`, and `target_score` rows.
