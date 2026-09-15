# Issue 1054: Sort Post-Cross-TU Broader Natural Rewrite

## Problem

The post-cross-TU selection/swap source hypothesis layer for `mnDiagram_SortNamesByKOs`
now scores real full-TU probes and terminalizes cleanly, but its terminal proof still
ends the modeled source-family search. The best retained candidate preserves
`IG44->r25` and loses `IG34->r27`, so the next layer should keep that one-hit seed
available while trying broader natural C rewrites of the Sort region.

## Design

Add one source-actionable layer after
`sort-post-cross-tu-selection-swap-source-hypothesis`:

- dimension: `sort-post-cross-tu-broader-natural-c-rewrite`
- source output: ranked full-function or region-level `.c` candidates with
  `source_hunks`, `source_components`, target score requirements for `IG34->r27`
  and `IG44->r25`, structural guard requirements, and seed one-hit evidence
- terminal output: a proof that retains the scored broader rewrite rows and names
  `sort-no-modeled-source-actionable-family-after-post-cross-tu-broader-natural-c-rewrite`
  if no scored candidate jointly preserves both protected targets under the guard

The layer is opt-in through the existing `--continue-after-final-source-family`
flag. The default behavior remains terminal for the previous final family unless
an agent explicitly asks to continue.

## Verification

- Unit tests should fail before production changes by asserting that a
  post-cross-TU selection/swap terminal proof generates only the new broader
  natural rewrite dimension.
- Classification tests should verify that an IG44-only scored row terminalizes
  with retained evidence and that an accepted IG34+IG44 row is actionable.
- Smoke checks should run `source-model-synthesis --continue-after-final-source-family`
  against the real #1052 scored artifact, then classify an offline score row and
  confirm the terminal proof carries `target_score`, `structural_guard`,
  `source_hunks`, and the new final family.
