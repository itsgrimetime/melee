# Issue 1079: Sort semantic recombine source model

## Root Cause

`source-model-synthesis` could discover Sort semantic recombine candidates only as
estimated nested proof rows after the first score pass. Those rows carried source
hunks, but they were not materialized into retained C files or scored, so
retained-frontier triage correctly rejected them as estimate-only evidence.

## Fix

- Expose actionable nested semantic recombine rows on blocked/terminal source
  model payloads.
- Materialize non-overlapping semantic recombine hunks into full-unit retained
  source candidates with score-source metadata.
- Run a bounded second score pass for those materialized candidates in
  `source-model-synthesis --score`.
- Reclassify with the real recombine score rows so retained-frontier triage can
  see `source_retained`, `pcdump_path`, real target score, and real structural
  guard evidence.
- If materialization is attempted but no candidate can be produced, terminalize
  the semantic recombine layer instead of repeating the stale cross-TU source
  family.

## Verification

- Focused Sort semantic source-model tests cover materialization, hunk mismatch
  diagnostics, CLI second-pass scoring, and estimate-only triage rejection.
- Retained-frontier tests cover propagation of real semantic recombine
  `pcdump_path` evidence.
- The #1079 diagnostic artifact materializes four scoreable semantic recombine
  candidates against current `master`.
