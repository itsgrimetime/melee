# Issue 998/999 Terminal Source-Model Proof Plan

## Scope

Resolve the shared root cause behind tooling issues #998 and #999: terminal
post-meta source-family artifacts carried useful source-model proof data, but
retained-frontier and allocator-ceiling aggregation could drop or de-prioritize
that data when older compatibility terminal groups were also present.

## Fix

- Treat source-family continuation candidates as actionable only when they have
  an executable retained-source route and clear the prior expression floor.
- For Draw FPR post-meta ceilings, name the unsupported source expression class
  as `draw-coupled-post-meta-fpr-expression-lifetime` and propagate its source
  spans through terminal proofs.
- Enrich retained terminal groups from embedded `source_model_proof` payloads so
  source spans, residual blockers, exhausted dimensions, and unsupported-model
  text survive compatibility terminal wrapping.
- Rank terminal next-source-model summaries by evidence quality, so rich
  continuation proofs outrank high-count legacy summaries without source spans.
- Render unsupported source expression class and next unsupported source model
  in allocator-ceiling text.

## Verification

- Focused regression tests cover route-less Draw plateaus, Draw source-expression
  class propagation, retained-frontier proof enrichment, allocator-ceiling
  rendering, and Sort mixed legacy/continuation model ranking.
- Command-level smokes regenerate the #998 Draw continuation, retained-frontier,
  and allocator-ceiling artifacts, and the #999 Sort retained-frontier and
  allocator-ceiling artifacts.
