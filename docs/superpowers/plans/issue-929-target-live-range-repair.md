# Issue 929 Target Live-Range Repair Plan

## Root Cause

`retained_gpr_case_c_window_order_continuation` only materialized ranked
indexed-byte probes from select-order evidence. The #929 frontier needed a
separate target/interferer repair step: IG44 wants r25, but r39 currently takes
that register, so the next probes must explicitly try r39 live-range shrinkage
or IG44 interference shaping while tracking protected IG34.

## Design Decision

Add a distinct `retained_gpr_case_c_target_live_range_repair` transform family
instead of folding this into the exhausted #928 continuation. The family reuses
the existing transform-corpus writer/validator pipeline and
`LifetimeLayoutProbe` conversion, but has its own mutator key, diagnostics,
validation classifier, and summary.

An independent review pointed out the adjacent `node_set_delta` path. That path
is useful when a node-set-delta payload already exists, but #929 provides only a
retained source frontier plus guide-level r44/r39 evidence. This implementation
therefore acts as a bounded retained-source probe producer. It does not edit the
debug select-order producer in this change.

## Implementation Scope

- Add target-aware live-range/interference probe planning in
  `window_order_source.py`.
- Register and route `retained_gpr_case_c_target_live_range_repair` for the
  SortNames force-phys frontier.
- Generalize retained `LifetimeLayoutProbe` conversion so target-aware probes
  keep their own mutator key and protected/attempted target metadata.
- Add CLI loading for optional `retained_case_c_repair_goals`, exact/protected
  classification, and terminal summaries.
- Preserve explicit `--transform-family` behavior when `--select-order-json` is
  present, so #929 runs do not silently include the old #928 continuation.

## Verification

Regression tests cover planner materialization and blocking diagnostics,
transform conversion, registry routing, CLI probe writing, protected-negative
classification, exact-hit stop behavior, and source-transform catalog metadata.

Command-level smoke checks use the #928 retained frontier artifact to generate
two target-aware probes and score them against the IG34/IG44 target spec. The
current candidates produce bounded negative evidence: both compile and score,
but both lose protected IG34, so the summary reports
`target-aware-live-range-interference-probes-exhausted` with the exhausted
`target-aware-live-range-anchor` and `target-aware-interference-shape` spans.
