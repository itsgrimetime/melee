# Issue 968: Post-Ceiling Continuation Route Closure

## Context

Issue #967 added a second-generation `post-ceiling-baseline-escape-continuation`
frontier. It emits retained select-order routes from candidate pcdump
first-divergence analysis after baseline-escape candidates score with no target
progress.

The matcher then ran all emitted select-order routes:

- Draw digit callarg route: terminal, `transform-family-exhausted`, 0/3 hits.
- Draw paired offset route: terminal, `ranked-owner-candidates-not-materializable`.
- Sort init pointer-walk route: terminal, `transform-family-exhausted`, 0/2 hits.
- Sort swap materialization route: terminal, `transform-family-exhausted`, 0/2 hits.

Despite this, retained-frontiers still reports the original
`post-ceiling-baseline-escape-continuation` as actionable. Baseline-escape then
cannot consume the route evidence because retained-frontiers is no longer in
the `all-known-frontiers-exhausted` state.

## Goal

Close post-ceiling continuation frontiers once every emitted route has matching
terminal/no-progress route evidence. The closure must also suppress nested
retained select-order command frontiers extracted from the continuation summary
so retained-frontiers reaches a stable exhausted state.

## Non-Goals

- Do not generate new source families.
- Do not change select-order search behavior.
- Do not treat force-distance-only progress as exact target progress.
- Do not close a continuation when any emitted route is missing evidence or
  lacks terminal/no-progress evidence.

## Design

Retained-frontiers is the right closure point. It already owns cross-artifact
frontier extraction, terminal suppression, and final next-frontier selection.
Adding closure there lets baseline-escape keep its existing readiness rule:
it can proceed when retained-frontiers reports `all-known-frontiers-exhausted`.

The implementation adds route-level closure signatures:

- Continuation route signatures are derived from each ranked continuation route:
  route kind, function, class id, target order, candidate force-phys map,
  retained source, and retained pcdump.
- Select-order terminal signatures are derived from route output artifacts:
  route kind, function, class id, target order, terminal force-phys targets,
  source, and baseline pcdump.

Source and pcdump paths are part of the route signature. If a continuation route
or terminal route output lacks enough data to form that exact signature,
retained-frontiers leaves the parent continuation open instead of falling back
to force-only matching.

Retained-frontiers then applies two suppression passes:

1. Generic select-order terminals close matching retained select-order command
   frontiers, including the GPR `select-order-source-exhaustion` shape as well
   as the existing FPR degree-zero terminal.
2. A post-ceiling continuation frontier is closed only when every route
   signature listed by the parent continuation has a matching route terminal.

The parent closure records a stable terminal reason:

`post-ceiling-continuation-routes-exhausted/current-source-shape-ceiling`

It preserves route residual facts by attaching the matched route terminal
blockers and `closed_by` artifacts to the public terminal frontier.

## Progress Handling

This feature only closes terminal/no-exact-progress route artifacts. If a route
artifact is not terminal, or if it exposes an actionable source-hunk/frontier,
retained-frontiers must leave the continuation open so the matcher can pursue
that route.

## Testing

Regression tests cover:

- Sort continuation plus two GPR select-order terminal artifacts closes the
  original post-ceiling continuation frontier.
- Draw continuation plus two FPR select-order terminal artifacts closes the
  original post-ceiling continuation frontier.
- Missing one route terminal leaves the continuation actionable.
- Same function/class/order/force with different source or pcdump does not
  suppress the wrong route.
- Generic select-order terminal evidence suppresses nested retained
  select-order command frontiers.
- The existing continuation terminal remains separate from the baseline-escape
  terminal family.

## Validation

Use focused pytest for retained-frontier and baseline-escape tests, syntax/lint
checks for touched files, and a live CLI smoke with the issue #968 artifacts to
confirm retained-frontiers reports `all-known-frontiers-exhausted` after all
route outputs are included.
