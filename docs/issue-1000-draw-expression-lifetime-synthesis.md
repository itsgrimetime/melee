# Issue 1000 Draw Expression-Lifetime Synthesis Plan

## Scope

Resolve tooling issue #1000: Draw FPR allocator ceilings can identify an
unsupported coupled expression-lifetime source model, but source-model synthesis
only emitted the three older Draw probe families. That left matcher agents with
no generated probes for the next requested source-shape class.

## Fix

- Reuse the existing `expression_interferer_repair` Draw generator as an
  adapter for post-meta source-model synthesis.
- Gate the adapter to Draw FPR ceilings that name
  `draw-coupled-post-meta-fpr-expression-lifetime` or equivalent next-model
  text.
- Preserve distinct provenance with `adapted_from_expression_interferer` and
  `requires_expression_score_validation` metadata.
- Resolve the retained source symbol before generation, so public
  `mnDiagram_DrawCellNumber` ceilings can emit and score probes against
  `mnDiagram_80241E78`.
- Build terminal attempted-class proofs from the dimensions that were actually
  generated or scored, including adapted expression-lifetime dimensions.

## Verification

- Focused regression tests cover adapted Draw expression-lifetime generation,
  source alias fallback, CLI probe writing, score-command metadata, and terminal
  attempted-class proof emission.
- Command-level smokes regenerate #1000 Draw probes and run bounded live
  scoring against the retained Draw target artifact.
