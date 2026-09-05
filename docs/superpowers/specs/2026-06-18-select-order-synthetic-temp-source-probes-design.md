# Select-Order Synthetic Temp Source Probes Design

## Context

Issues #821 and #822 are follow-ups to the protected-complement select-order
work. The allocator diagnostics now identify the remaining split registers, but
the source probe planner stops at attribution:

- Sort `mnDiagram_SortNamesByKOs`: IG34 maps to local `dst_iter`, but the local
  statement has no legal pure move. IG44 maps to a pcode-first-def
  `implicit-temp` expression `add r44,r49,r34`, and the planner reports
  `implicit-temp-no-safe-source-move`.
- Draw `mnDiagram_DrawCellNumber`: IG38 and IG46 map to pcode-first-def
  `fpr-temp` expressions such as `lfs f38,60(r47)` and `fsubs f46,f45,f44`.
  The planner reports `unsupported-source-attribution-kind`.

The current source planner, `src/search/directed/window_order_source.py`, only
generates probes for one uniquely movable local assignment. That is correct for
ordinary locals, but it leaves compiler-introduced address and FPR temporaries
without a source-level lever.

## Design

Extend `window_order_source.py` with a separate synthetic-owner probe layer.
The existing local-move path remains unchanged. When a lead is blocked because
its attribution is a supported synthetic temp, the planner asks the synthetic
layer for narrowly-scoped source variants and records the result in the same
`lead_diagnostics` format.

The first supported shapes are intentionally small:

- `implicit-temp` GPR `add`/`addi` source expressions. The planner parses the
  operand virtuals from the pcode-first-def expression and looks for a local
  source attribution among those operands. If exactly one operand maps to a
  unique local owner statement, it emits owner-split probes around that local.
- `fpr-temp` first-def expressions for `lfs`, `fsubs`, `fsub`, `fmuls`, and
  `fmul`. The planner maps these to exact float-expression owner statements or
  cast fragments already present in the source and emits owner-split probes for
  those assignments. If multiple concrete FPR load owners are plausible, the
  planner emits one source probe per safe candidate instead of stopping at an
  ambiguity blocker.

Owner-split probes are simple source rewrites that introduce a named temporary
for an expression owner without duplicating calls or memory loads. The probe
label and provenance identify the synthetic handler kind, target IG, source
owner, original attribution, source line range, and source diff. All probes use
the existing `LifetimeLayoutProbe` scoring pipeline so select-order ranking,
force-phys hit reporting, structural guard evaluation, and campaign artifacts
continue to work without a separate execution path.

## Diagnostics

The synthetic layer must be conservative and explain why it did not act. New
terminal blockers:

- `synthetic-temp-operands-unattributed`
- `synthetic-temp-no-unique-owner`
- `synthetic-temp-no-candidate-expression`
- `synthetic-temp-unsupported-shape`
- `synthetic-temp-duplicate-source`
- `source-owner-transform-unsafe`

When synthetic probes materialize, the lead diagnostic is marked
`status: materialized`, includes `materialized_probe_labels`, `source_diff`, and
a `synthetic_source_probe` payload. Existing JSON consumers should not need
schema changes.

## Non-Goals

- Do not add broad source proximity rewrites that are not tied to opcode,
  operand, expression, or owner evidence.
- Do not duplicate side-effecting calls or memory loads.
- Do not replace the existing transform corpus families.
- Do not promise an exact register match. The feature supplies source levers and
  records scored outcomes; exact matching remains a search result.

## Testing

Tests cover both direct planner behavior and CLI diagnostic threading:

- Local source-attribution behavior remains unchanged.
- Unsupported synthetic temps still produce explicit blockers.
- GPR implicit `add` with a mapped operand local materializes owner-split probes.
- FPR `lfs` and `fsubs` pcode-first-def temps materialize owner-split probes
  when exact expression owners or cast fragments are found.
- CLI JSON reports synthetic probes as listed window-order probes and exposes
  them through `source_bridge_summary` actions.
