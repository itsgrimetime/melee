# Target-Only Backprojection Terminal Attribution

## Context

Issue #955 reported a target-only GPR Case C backprojection for
`mnDiagram_SortNamesByKOs`: forced allocator evidence can place IG34 in r27
while preserving IG44 in r25, but the only source lever is the PCode-only
implicit temp `addi r34,r52,28`. The retained simplify-order continuation for
that artifact compiled bounded candidates and found no progress.

Issue #956 reported a target-only FPR Case C2 backprojection for
`mnDiagram_DrawCellNumber`: forced allocator evidence can place IG37 in f26
while preserving IG32 in f26, but the backprojection had no direct source
lever. Existing retained live-range and alternate-owner lanes had already
exhausted the relevant source expressions.

## Decision

Teach `mwcc-debug solve allocator-ceiling` to consume the already-produced
target-only continuation artifacts and emit explicit terminal attribution:

- `target-only-backprojection-source-probe-continuation` for PCode `addi`
  source levers when retained continuation evidence compiles bounded probes
  with zero progress.
- `target-only-c2-sticky-pool-source-attribution` for Case C2 sticky-pool
  backprojections when retained live-range/source-owner lanes exhaust the
  source expressions that could affect the sticky pool.

The broader transform-family design remains a future extension. For these
reports, the available artifacts already satisfy the required terminal stop
conditions once the classifier preserves the source family, source expressions,
force targets, counts, and bounded blocker in its output.

## Acceptance Checks

- #955 real artifacts classify as
  `target-only-backprojection-source-probe-continuation-terminal` and name
  `target-only-backprojection-addi-copy-product`.
- #956 real artifacts classify as
  `target-only-c2-sticky-pool-source-attribution-terminal` and list the
  exhausted source expressions and upstream virtuals.
- Existing source-actionable target-only backprojection remains actionable until
  matching continuation evidence is supplied.
