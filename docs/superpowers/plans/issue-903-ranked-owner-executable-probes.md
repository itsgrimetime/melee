# Issue 903: Ranked Owner Executable Probes Plan

## Goal

Make `melee-agent debug select-order-search` turn #902 ranked owner diagnostics
into executable `window-order-source-steering` probes for the
`mnDiagram_SortNamesByKOs` retained pointer-walk source, or emit a specific
terminal summary showing why every ranked candidate is unsafe.

## Implementation Plan

1. Add stable source span metadata to ranked candidate payloads so
   materializers do not rely on duplicated `span_text` alone.
2. Add ranked local-owner materialization for safe loop-body reads of locals
   such as `i`, with C89-safe temporary declarations and provenance tied back
   to the ranked candidate.
3. Add ranked indexed-byte materialization for executable indexed expressions,
   while rejecting array declarations and other unsafe spans with explicit
   reason codes.
4. Thread materialized ranked-owner diagnostics through
   `source_bridge_summary` and add terminal reason counts when nothing
   materializes.
5. Avoid planning the same window-order source probes twice in
   `debug select-order-search`; diagnostics and returned probes should come
   from the same plan call.
6. Count scored window-order source probes only from successful retained
   variants with pcdump or target-score evidence.

## Regression Coverage

- Planner test for materializing a ranked loop-index read anchor.
- Planner test proving array declarators are rejected as indexed-byte probes.
- Planner test for materializing a ranked indexed-byte expression from an
  implicit-temp/copy-chain blocker.
- Planner test for terminal reason summaries when all ranked spans are unsafe.
- CLI test proving listed/scored ranked owner probes flow into retained
  variants and bridge actions.
- CLI negative test proving failed variants do not count as scored window-order
  source probes.

## Smoke Checks

Rerun the original issue source from the matcher artifact worktree with the
implementation pinned to the current main checkout's `tools/melee-agent`, for
both `r34<r41` and `r42<r34`. Acceptance requires nonzero listed and successful
scored window-order source probes, retained `.c`/`.pcdump.txt` artifacts, and
source bridge output that no longer leaves ranked owner candidates
non-actionable without explanation.
