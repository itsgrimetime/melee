# Issue 1069: Sort Protected One-Hit Continuation

## Problem

`mnDiagram_SortNamesByKOs` post-inline source-model scoring can find separate
one-target improvements, such as an IG34 hit in one retained source family and
an IG44 hit in another, without producing a dual protected hit. Before this
fix, the post-inline terminal path could treat those rows as ordinary final
source-model exhaustion. That lost the lower-drift protected row as a concrete
continuation candidate and could also report `best_target_matched` as `0`
despite retained candidate rows or target anchors showing one protected hit.

The reported case used these rows:

- `post-meta-source-family-sort-init-indexed-write-name-total-locals`:
  IG34=r27, IG44 missing, normalized diff 5.
- `post-meta-source-family-sort-call-return-copy-local-max-text-copy`:
  IG44=r25, IG34 missing, normalized diff 9.

Manual combine evidence did not preserve IG34 and IG44 together, but it did
produce a lower-drift one-hit retained source route that should remain
actionable.

## Approach

- Broaden Sort one-hit recombine eligibility to include the later post-ceiling
  Sort source-model ladder through the post-inline boundary-selection emission
  source-shape dimension.
- Continue building Sort protected one-hit summaries even when the classified
  source-model payload has a final post-inline terminal hint.
- Do not mark a terminal recombine dimension as exhausted when no actual
  recombine candidate was generated; a lone one-hit row remains evidence, not a
  synthetic exhausted recombine family.
- Convert real `debug search combine` rows that preserve exactly one protected
  target, have low normalized drift, and carry both retained source and pcdump
  paths into `sort-semantic-protected-loss-repair` continuation lanes.
- Keep failed dual-hit recombine evidence terminal; do not accept estimated
  dual-hit candidates after real combine scoring shows protected loss.
- Normalize retained-frontier source-model proof metrics from terminal summary,
  target anchors, candidate rows, nested target scores, and virtual matches so
  one-hit evidence reports `1/2` instead of stale `0/2`.

## Acceptance

- A Sort post-inline terminal source-model payload with complementary one-hit
  rows and concrete retained source/pcdump evidence becomes actionable via a
  protected continuation route.
- The same payload without a concrete route terminalizes with the post-inline
  final source family named and `best_target_matched == 1`.
- Retained-frontier triage promotes the protected route and preserves satisfied
  and missing protected assignments.
- Allocator-ceiling propagates the retained-frontier actionable lane.
- Existing semantic recombine and protected-loss tests continue to pass.
