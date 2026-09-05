# Issue 1093: Draw Helper-Boundary Terminal Proof

## Problem

`mnDiagram_DrawCellNumber` helper-boundary scoring can exhaust the
`draw-coupled-fpr-expression-lifetime-helper-boundary-handoff` lane after
protected-expression reconciliation without recovering IG32/IG37/IG46 expression
anchors. The retained-frontier terminal proof preserved that handoff as the
exhausted family, but also reported it as `next_unsupported_source_family`.

That self-loop sent resolver/matcher agents back to a family that had already
been fully consumed.

## Fix Strategy

Keep helper-boundary terminal evidence source-actionable:

- Preserve `draw-coupled-fpr-expression-lifetime-helper-boundary-handoff` as the
  exhausted and closed family.
- Add a distinct final sentinel,
  `draw-no-modeled-source-actionable-family-after-post-helper-boundary-expression-lifetime`.
- Emit that sentinel from both helper-boundary terminal constructors:
  retained score rows and direct `suggest inlines` terminal reports.
- Normalize stale retained-frontier artifacts that still contain the old
  self-loop so allocator-ceiling guidance points at the final sentinel.
- Teach allocator-ceiling that the retained-score terminal reason
  `draw-coupled-fpr-expression-lifetime-helper-boundary-exhausted/no-expression-progress`
  is a helper-boundary terminal blocker.

## Verification

Regression tests cover:

- Raw helper-boundary `suggest inlines` terminal reports.
- Retained helper-boundary score rows with no expression progress.
- Allocator-ceiling rendering and next-step generation from stale helper-boundary
  terminal artifacts.

Reporter artifact smoke:

- `debug search retained-frontiers` over the #1093 retained artifacts.
- `debug solve allocator-ceiling` over that retained-frontier output.

Expected result: practical ceiling remains terminal, the exhausted source
dimension is the helper-boundary handoff, and the next unsupported source family
is the distinct post-helper-boundary final sentinel.
