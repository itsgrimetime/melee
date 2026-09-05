# Issue 1080: Draw Post-Row-Offset Owner Expression Lifetime

## Problem

`mnDiagram_DrawCellNumber` source-model synthesis reached
`draw-no-modeled-source-actionable-family-after-post-row-offset-owner-split`,
but the next `source-model-synthesis` / `source-family-continuation` pass fell
back to the older
`draw-post-stack-loop-callsite-expression-anchor-source-ownership` family.

That left matcher agents with no source-actionable continuation after the
retained row-offset/digit-base owner split floor.

## Root Cause

The Draw source-family pipeline had first-class stages through
`draw-post-stack-loop-callsite-expression-anchor-source-ownership`, but no
first-class successor for the post-row-offset owner split terminal family.
Mixed meta-ceiling payloads also let older nested loop-callsite source-context
proofs outrank the newer owner-split terminal, and a prior-stage terminal
suppression blocker could terminalize a new generation pass even after a newer
candidate had been emitted.

## Fix Plan

1. Add a `draw-post-row-offset-owner-expression-lifetime` dimension with
   source candidates for row-offset-adj, column-product, digit-callsite, and
   coupled lifetime ownership.
2. Teach stage detection, generated payload filtering, zero-candidate terminal
   metadata, terminal proof construction, and continuation handoff logic about
   the new dimension and final family.
3. Rank direct owner-split and owner-lifetime terminal handoffs above stale
   nested loop-callsite source-context evidence.
4. Suppress prior loop-callsite source-context terminal blockers while the
   newer owner-lifetime stage is active.
5. Add regression tests covering generation from an owner-split terminal and
   continuation preservation of the owner-split final family.

## Verification

Use the focused Draw source-family pytest subset plus command-level smoke
checks against the real `draw_expression_anchor_ownership/source_model_scored`
diagnostic artifact. The smoke should generate a
`draw-post-row-offset-owner-expression-lifetime` candidate with retained seed
source and pcdump metadata instead of terminalizing back to the stale
loop-callsite owner family.
