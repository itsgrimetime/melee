# Target-Only Allocator Backprojection

## Problem

`melee-agent debug solve allocator-ceiling` could prove that a force-phys
target matches while the exhausted source-transform corpus still left the
natural build at a target-only allocator rotation. The classifier then stopped
at `target-only-allocator-rotation`, which told matcher agents that the current
shape was terminal but did not explain which allocator decision differed or
whether the existing node-set source attribution still gave them a source lever.

## Scope

For allocator-ceiling evidence that already contains:

- a structurally different node-set delta,
- a force-vector verification with union status `match`,
- exhausted wrong-register or mixed target-only node-set evidence,
- exhausted negative transform validation, and
- retained natural and forced pcdumps,

the classifier should backproject the force-vs-natural allocator decision before
declaring the target-only ceiling terminal.

## Implementation

The classifier now parses force-vector targets from successful union-match
force evidence, locates a retained natural pcdump and a matching forced pcdump,
and reuses the first-divergence analyzer on the natural dump with the force-phys
target map. It records the divergent allocator decision, requires the forced
pcdump to differ from natural and assign the requested physical register, and
maps the decision back to node-set `missing_virtuals[].source` attribution when
the first-divergence virtual itself has source attribution.

When a source attribution is available, the result becomes:

`actionable (target-only-allocator-rotation-backprojection)`

When the allocator decision is real but no source attribution is available, the
result becomes:

`practical-ceiling (target-only-allocator-rotation-backprojection-terminal)`

Evidence without retained pcdumps keeps the legacy target-only ceiling behavior
so older reports remain classifiable.

## Verification

Regression tests cover source-actionable and terminal-no-source paths, stale
forced pcdump rejection, failed force evidence scoping, unrelated source
attribution, non-divergent force-target attribution, and CLI text rendering.
The filed `mnDiagram_DrawCellNumber` FPR artifact classifies as terminal with a
backprojected Case-C2 first divergence, while the filed
`mnDiagram_SortNamesByKOs` GPR artifact classifies as actionable with a
backprojected Case-C first divergence and source-lever output.
