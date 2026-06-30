# Issue 1042 Draw Product/Translate Expression-Graph Source Dimension

## Goal

Add the next bounded Draw source-model dimension after the post-all-known source-context layer added for issue 1041. The new layer models the coupled loop-index translate, col/row product, and object/base lifetime expression graph for `mnDiagram_DrawCellNumber`.

## Root Cause

The issue 1041 lane correctly generated and terminalized post-all-known source-context candidates, but the best retained candidate still plateaued at the current floor: target 0/3 and expression 1/3. The remaining misses are not another simple ownership alias. They are coupled FPR expression graph misses around IG32, IG37, and IG46:

- col product and loop translate use the wrong virtual relationship,
- row delta/product and col product appear swapped across `f26`/`f28`,
- one expression hit only survives by renumbering.

The current generator has no modeled dimension after `draw-post-all-known-frontiers-source-context-hypothesis`, so retained-frontiers and allocator-ceiling report that no modeled source-actionable lane remains.

## New Dimension

- Dimension id: `draw-post-all-known-loop-product-translate-expression-graph`
- Candidate prefix: `draw-post-all-known-product-translate-graph-`
- Terminal reason: `draw-post-all-known-loop-product-translate-expression-graph-exhausted/no-floor-improvement`
- No-floor blocker: `draw-post-all-known-loop-product-translate-expression-graph/no-target-or-real-expression-floor-improvement`
- Pattern blocker: `draw-post-all-known-loop-product-translate-expression-graph/source-patterns-not-found`
- Final family: `draw-no-modeled-source-actionable-family-after-post-all-known-loop-product-translate-expression-graph`

## Required Integration

The new stage activates only after post-all-known source-context is exhausted. It must be first-class in the same hard-coded paths as the older Draw stages:

- `generate_source_family_candidates`: include this stage in the whole-function-exhausted guard allowlist, alternate-terminal allowlist, generic-spec suppression, and stage-specific return branch.
- scoring/actionability: include a product-translate stage boolean in `_row_source_actionable_progress`, `_draw_post_ceiling_floor`, `_draw_no_floor_terminal_blocker`, and terminal-safe floor exhaustion.
- terminal proof: add product-translate terminal attempts, next hints, final model/family selection, retained evidence, and zero-candidate terminal metadata.
- retained-frontiers: rank this dimension above post-all-known, map the candidate prefix, preserve pcdump/scores/hunks, and suppress stale post-all-known hints when product-translate terminal proof exists.
- allocator-ceiling: render product-translate actionable and terminal evidence as the current ceiling.

Evidence scanning must use normalized `MetaCeilingContext.source_spans`, plus candidate/retained score rows and expression score payloads. Do not rely on a separate `unmapped_source_spans` field.

## Candidate Scope

The first implementation should stay bounded to four candidates:

1. `loop-index-row-col-product-owners`: seed from #1041 loop-index translate and materialize col/row product owners.
2. `row-delta-product-before-col-product`: retained split form with row product before col product.
3. `col-product-before-row-delta-with-y-offset`: legacy `y_offset` source spelling from the current checkout.
4. `translate-x-common-call-with-product-owners`: common `translate_x` call shape paired with product owners.

Support both current legacy `y_offset` and retained `row_offset/rowf` spelling. Defer base-snapshot and joint-table negative-control candidates unless the bounded four produce no usable structural facts.

## Acceptance

Issue 1042 is fixed when either:

- a generated product-translate candidate is actionable by improving target score, real expression score, or accepted structural guard beyond the retained floor, or
- the product-translate dimension terminalizes with ranked C candidates, source hunks, pcdump paths, target/expression score summaries, structural guard facts, and a final unsupported family that replaces the stale post-all-known handoff.
