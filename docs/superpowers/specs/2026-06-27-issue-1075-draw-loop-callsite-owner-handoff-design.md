# Issue 1075: Draw Loop-Callsite Owner Handoff Design

## Context

`mnDiagram_DrawCellNumber` has a bounded post-stack-clean/no-anchor
loop-callsite source-context family. That family tests digit object,
animation callarg, translate-X/translate-Y owner, and add-child parent owner
spelling from the retained post-stack source-shape proof.

The current terminal proof reports the exhausted loop-callsite dimension, but
its next family is the generic
`draw-no-modeled-source-actionable-family-after-post-stack-loop-callsite-source-context`.
That tells the matcher that the layer is done, but not what source owner problem
remains.

## Goal

When the loop-callsite family exhausts without improving the target or
expression floor, the terminal proof must name the next unsupported source
owner problem precisely enough for matcher continuation. It must still mark the
loop-callsite dimension exhausted so old post-stack, source-shape, and
loop-callsite families do not regenerate.

## Design

Add a new terminal handoff family and model:

- family: `draw-post-stack-loop-callsite-expression-anchor-source-ownership`;
- model: a Draw-specific owner/lifetime handoff naming the row/column FPR
  owners, `col_product_owner` split product, `y_offset`/`row_offset` row-delta
  block, and digit base assignment feeding `HSD_JObjReqAnimAll`.

The existing generic family remains a legacy marker for previously emitted
artifacts. New terminal proofs, continuation payloads, retained-frontier
summaries, allocator ceilings, and post-source-context next-dimension discovery
should report the precise handoff family/model as
`next_unsupported_source_family` and `next_unsupported_source_model`.

The exhausted source dimension remains
`draw-post-stack-clean-no-anchor-loop-callsite-source-context`. This is the
suppression key that prevents the completed loop-callsite layer from reopening.

## Integration Points

- `post_meta_source_family_synthesis`: terminal classification, zero-candidate
  terminal metadata, continuation payloads, and normalized context emit the
  precise owner handoff after the loop-callsite dimension exhausts.
- `post_source_context_discovery`: next-dimension discovery recognizes both
  legacy and new loop-callsite terminal artifacts, then returns the precise
  owner handoff.
- `retained_frontier_triage`: completed loop-callsite terminal groups rank
  above source-shape evidence and surface the precise owner handoff.
- `allocator_ceiling`: current-ceiling selection inherits the retained terminal
  handoff and presents it as the current terminal proof.

## Tests

Regression coverage asserts that scored loop-callsite rows terminalize with the
new owner handoff, source-family continuation preserves it, old Draw families
do not regenerate, next-dimension discovery prefers it over stale stack-clean
artifacts, and retained-frontier/allocator ceiling summaries promote it from
the newest loop-callsite terminal.

## Non-Goals

This change does not implement a new candidate generator for the expression
anchor owner family. It satisfies the issue stop condition by emitting a more
precise terminal proof for the next unsupported source owner/lifetime problem.
