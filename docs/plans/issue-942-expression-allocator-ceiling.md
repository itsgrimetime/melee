# Issue 942: Expression Interferer Allocator-Ceiling Handoff

## Problem

`debug solve allocator-ceiling` rejected expression-interferer terminal JSON from
`mnDiagram_DrawCellNumber` with:

```text
evidence item 0 has no function scope for mnDiagram_DrawCellNumber
```

The command produced a zero-byte `--json` output even though the evidence was a
specific terminal source-shape result:

- `kind`: `expression-scored-fpr-case-a-c2-exhaustion`
- `post_bridge_terminal_summary.kind`:
  `no-expression-progress-after-row-fsubs-and-support-orders`
- `terminal_blocker`: `current-source-shape-allocator-ceiling`
- FPR swap evidence for `col_offset` IG32 and `row_offset` IG37

## Root Cause

`allocator_ceiling.py` had two handoff gaps:

1. Function-scope validation did not inspect `source_generation.function`, so
   existing expression terminal artifacts could be rejected before
   classification.
2. The classifier had no expression-interferer terminal adapter, so even scoped
   expression terminal evidence would fall through to generic legacy missing
   evidence instead of returning a practical expression-scored FPR ceiling or a
   precise expression-specific evidence gap.

## Implementation Plan

- Keep rejecting arbitrary unscoped evidence.
- Accept unscoped evidence only when it has the recognized expression-interferer
  terminal shape.
- Recurse into `source_generation` during function-scope discovery and still
  reject mismatched nested function metadata.
- Add an `expression_interferer_terminal` classifier branch that:
  - requires blocked post-bridge terminal status,
  - requires the expected terminal blocker,
  - requires exhausted row-fsubs and non-satisfied select-order routes,
  - requires no-progress expression scoring,
  - requires complete FPR swap evidence,
  - emits backend blocker rows for IG32 and IG37 when complete,
  - emits expression-specific `missing_evidence` when incomplete.
- Render expression-terminal details in text output so non-JSON users see the
  exhausted routes and FPR swap.

## Verification

- Unit tests for complete expression terminal evidence.
- Unit tests for recognized unscoped terminal evidence.
- Unit tests preserving rejection of arbitrary unscoped evidence.
- Unit tests for mismatched `source_generation.function`.
- Unit tests for missing exhausted route and missing FPR swap evidence.
- CLI JSON test proving non-empty practical-ceiling output.
- CLI text test proving source-actionable expression terminal output.
- Manual smoke against the issue artifact in the matcher worktree.
