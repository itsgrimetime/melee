# Issue 1015: Baseline-Escape After All-Known Frontiers

## Problem

After the Sort lower-drift init-lifetime family from issue 1014 was generated
and scored, retained-frontiers could prove that no modeled source-actionable
frontier remained. Allocator-ceiling correctly summarized that state as
`retained-frontiers-all-known-frontiers-exhausted/current-source-shape-ceiling`.

`baseline-escape` still rejected the workflow as incomplete because the Sort
readiness gate only accepted the older residual-case-C allocator terminal and
required legacy select-order, node-set, and coalesce supplemental evidence. It
also did not consume raw post-meta source-model score artifacts whose top-level
`score_rows` showed lower-drift init-lifetime exhaustion.

## Plan

1. Teach retained-frontiers to ingest targeted raw Sort source-model synthesis
   score artifacts as terminal negative evidence when they are
   `score-rows-not-terminal-safe` and contain concrete score rows.
2. Add `sort-protected-loss-init-lifetime` to Sort source-family proof handling
   and prefer newer lower-drift exhaustion proof over stale next-model text.
3. Let baseline-escape accept the retained-frontiers all-known practical ceiling
   only when retained-frontiers is exhausted, the function entry has no
   `next_frontier`, and the meta-ceiling contains concrete terminal proof.
4. Keep legacy Sort residual-case-C requirements intact for the older path.
5. If all locally supported baseline-escape families are already closed, emit a
   terminal final summary that names the next unsupported Sort source model
   instead of reporting incomplete post-ceiling evidence.

## Verification

Regression coverage exercises raw lower-drift source-model score ingestion,
source-model proof priority, retained-frontiers all-known practical-ceiling
readiness, and terminal baseline-escape summaries. Real-artifact smoke checks
cover retained-frontiers, allocator-ceiling, and baseline-escape in sequence.
