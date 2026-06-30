# Issue 1053: Draw Post-Stack-Clean Source-Shape Layer

## Problem

`mnDiagram_DrawCellNumber` reached the stack-clean/no-anchor recovery terminal
state after issue 1051, but the source-model tooling had no next bounded
source-family to test. Raw post-source-context reruns still needed to preserve
the issue 1051 final unsupported-family contract; only explicit
source-model-synthesis reruns from that final proof should advance into a new
source-shape layer.

## Design

- Add a Draw-only FPR dimension:
  `draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis`.
- Generate a bounded candidate set from the retained stack-clean final proof,
  targeting declaration packing, row-delta materialization, translate-product
  ownership, digit-base lifetime, and frame-neutral coalescing.
- Keep raw `post-source-context-next-dimension` output terminal on the original
  stack-clean final family. The new layer is entered only by
  `source-model-synthesis` when it sees the stack-clean final proof.
- Mark rows actionable only for real target/expression anchor progress, or for
  frame-only progress when the structural guard is accepted and opcode/diff
  shape remains clean.
- Extend retained-frontier and allocator-ceiling recognition only for artifacts
  that explicitly contain the new post-stack-clean source-shape terminal proof.

## Verification

- Focused pytest coverage for generation, terminalization, continuation
  preservation, actionable row filtering, capability search, retained-frontier
  recognition, and allocator rendering.
- Real #1051 artifact smoke confirms raw post-source-context output remains the
  existing stack-clean final unsupported family with no next dimension.
- Real #1049/#1051 source-model-synthesis smoke confirms the new layer
  generates three bounded source-shape probes and terminalizes cleanly after all
  score without an anchor/frame improvement beyond the retained floor.
