# Expression-Aware Interferer Repair Design

## Context

Issue #876 covers the final `mnDiagram_DrawCellNumber` 5/6 FPR frontier. The
natural retained source keeps all protected expression anchors but leaves
`col_offset_product_fpr` in `f25` instead of the expected `f28`. A force proof
shows the source shape is reachable when the focus virtual is forced to `f28`,
but the natural allocator path is blocked by Case A: `f28` is already held by
the `row_offset` interferer. Existing select-order probes can move the focus
expression, but they regress protected anchors and end in a Case C2 sticky-pool
residual.

The matcher needs a governance layer that treats expression identity as the
source of truth. Raw virtual-id hits are not enough because renumbering can make
the target score look better while the actual source expression regresses.

## Design

Add a pure evaluator in
`tools/melee-agent/src/mwcc_debug/expression_interferer_repair.py`. It consumes
existing score and residual JSON payloads without compiling or editing source.
The evaluator:

- defines a focus/protected expression policy where one named expression must
  reach its expected register and every other anchor is protected;
- derives force maps from the focus anchor's candidate virtual after renumbering;
- rejects raw virtual-id false positives and protected expression regressions;
- labels Case A residuals from expression-score identity first, then attaches
  advisory low-confidence source names separately;
- attaches blocker source labels such as `row_offset` from FPR attribution-style
  payloads;
- ranks natural 5/6 protected candidates ahead of exploratory 2/6 select-order
  candidates that lose protected hits;
- emits a terminal summary naming the remaining Case A `row_offset`/product
  blocker and Case C2 sticky-pool blocker.

Expose the evaluator through
`debug suggest expression-interferer-repair`, accepting one or more candidate
JSON files and returning the same terminal summary as JSON or compact text. This
keeps the repair lane reusable from shell automation while preserving the helper
as a unit-testable pure module.

## Non-Goals

This feature does not synthesize new C source variants or force allocator
registers directly. It is a bounded evaluator and stop-condition reporter for
candidate payloads produced by the existing mutation, force-proof, and scoring
tools.
