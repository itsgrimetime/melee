# Issue 1126/1123 Indexed Struct Terminal Proof Plan

## Root Cause

`debug mutate indexed-struct-search` already generated bounded retained
source probes for indexed-struct pointer materialization hints, but exhausted
runs only reported `no-indexed-struct-candidate`. The JSON payload did not
include a per-candidate target score or a terminal proof that named the
exhausted source family and the next concrete source-level handoff.

That left matcher workflows for `mnDiagram2_GetRankedFighter` and
`fn_80247510` without enough evidence to decide whether to continue with the
same pointer-shape family or move to frame/layout and lifetime levers.

## Design

- Keep the existing indexed-struct source generator and real-tree scorer.
- Attach a lightweight target score to every compiled indexed-struct candidate.
  The score is based on whether the candidate reaches a true 100% checkdiff
  match, because this command is currently matching whole-function source probes
  rather than explicit force-phys register targets.
- When retained indexed-struct candidates are scored but none validates, include
  a terminal proof with:
  - exhausted source families
  - evaluated candidate count
  - retained source and pcdump paths
  - source hunks
  - target score and compact checkdiff evidence
  - a concrete next handoff to frame/layout or base/index lifetime changes

## Regression Coverage

- Synthetic indexed-struct fixture proves that scored non-winning probes produce
  a terminal proof with retained source, retained pcdump, source hunks, and
  target score.
- Existing validated indexed-struct JSON regression now asserts the successful
  target score.
- Existing explicit-candidate regression now asserts unvalidated candidates are
  surfaced through the terminal proof.

## Validation Artifacts

- `build/diagnostics/issue1126_indexed_struct_terminal.json`:
  `mnDiagram2_GetRankedFighter` retained two indexed-struct pointer candidates
  at 95.454544% and 83.62987%, both scored and retained with pcdumps, then
  emitted `indexed-struct-pointer-materialization-exhausted`.
- `build/diagnostics/issue1123_indexed_struct_terminal.json`:
  `fn_80247510` retained one indexed-struct pointer candidate at 92.36562%,
  scored and retained with a pcdump, then emitted the same terminal proof.

