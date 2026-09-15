# Issue #1029 Plan: Terminal-Safe Sort Cross-TU Handoff

## Scope

Issue #1029 is a `melee-agent` tooling fix for
`mnDiagram_SortNamesByKOs`. Do not edit production game source. The affected
behavior is retained-frontier and allocator handoff after the Sort
cross-TU/linkage source-model layer has already been scored and manually
recombined.

Capability audit:

```bash
melee-agent capabilities search "source-model terminal handoff retained frontier allocator one-hit recombine"
```

The existing tools cover the workflow (`debug target score-source`,
`debug search combine`, retained-frontier triage internals). No new CLI is
needed for this issue.

## Root Cause

The previous Sort source-model chain could name
`sort-cross-tu-symbol-linkage-or-data-section-ownership-source-context` as the
next unsupported family after unbounded TU data ownership, but retained-frontier
triage did not model that family as a first-class terminal layer.

The real #1029 cross-TU score artifact contains bounded score rows and useful
one-hit evidence:

- IG34 one-hit evidence from
  `post-meta-source-family-sort-init-indexed-write-name-total-locals`
- IG44 one-hit evidence from call-return copy-local and byte-cache rows
- no candidate jointly preserving IG34->r27 and IG44->r25

The manual recombine artifact also closes the complementary one-hit route:
three ok combinations preserve at most IG44 and no combination preserves both
protected targets. Since retained-frontier triage did not consume that layer as
closed, allocator next steps repeated the already-attempted cross-TU family.

## Implementation Plan

1. Add a Sort cross-TU/linkage source-model dimension in retained-frontier
   triage, ranked after unbounded TU data ownership.
2. Normalize raw `score-rows-not-terminal-safe` artifacts into the cross-TU
   layer only when the artifact/context identifies that layer and every score
   row carries complete protected-target score data.
3. Preserve the original local dimensions as `origin_dimension_id`, full
   `target_score.virtuals`, structural-guard data, and retained score rows.
4. Summarize one-hit evidence by protected target and report that protected
   targets were not jointly preserved.
5. Consume standalone `debug search combine` artifacts for Sort cross-TU
   recombine evidence. Negative recombine runs become terminal evidence;
   joint-preserving recombine runs stay actionable.
6. Emit a non-circular terminal next family:
   `sort-no-modeled-source-actionable-family-after-cross-tu-linkage`.
7. Ensure terminal proof ranking prefers cross-TU evidence over stale
   unbounded-TU evidence.

## Regression Tests

Add focused coverage in
`tools/melee-agent/tests/test_retained_frontier_triage.py`:

- raw cross-TU score rows produce a terminal source-model proof with retained
  score rows, one-hit evidence, and a non-circular next family;
- generic legacy score rows without cross-TU context do not promote to the
  cross-TU layer;
- cross-TU terminal evidence outranks stale unbounded-TU terminal proof;
- negative recombine artifacts preserve recombine evidence in terminal proof;
- joint-preserving recombine artifacts remain actionable rather than terminal.

## Verification

Run:

```bash
python -m pytest tools/melee-agent/tests/test_retained_frontier_triage.py
python -m pytest tools/melee-agent/tests/test_allocator_ceiling.py -k retained_frontiers
python -m compileall -q tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py
git diff --check
```

Smoke the real #1029 artifacts by triaging the cross-TU scored artifact plus the
manual recombine artifact and asserting:

- status is `all-known-frontiers-exhausted`;
- attempted dimensions include
  `sort-cross-tu-symbol-linkage-or-data-section-ownership-source-context`;
- retained scored probes are preserved;
- recombine evidence reports zero joint-preserving combinations;
- next family is not the attempted cross-TU family.
