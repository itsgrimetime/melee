# Issue 1096/1097 Post-Source-Ceiling Axis Plan

## Root Cause

Sort `mnDiagram_SortNamesByKOs` and Draw `mnDiagram_DrawCellNumber` both had
terminal evidence that all modeled source-family routes were exhausted, but
`melee-agent` did not have a reusable post-source-ceiling handoff. The tools
either returned a Draw-specific `unsupported-source-family` result or pushed
Sort back toward source-family continuation, even though the remaining work was
now backend/codegen or allocator behavior.

## Implementation

Add a diagnostic-only post-source-ceiling axis command:

```bash
melee-agent debug search post-source-ceiling-axis \
  --function <function> \
  --source-model-json <path> \
  --retained-frontiers-json <path> \
  --allocator-ceiling-json <path> \
  --post-source-context-json <path> \
  --continuation-json <path> \
  --bank auto \
  --json
```

The command consumes terminal source-model, retained-frontiers,
allocator-ceiling, Draw post-source-context, and source-family-continuation
artifacts. It normalizes:

- closed source families and terminal reasons,
- exhausted source dimensions,
- retained source/pcdump evidence,
- remaining GPR/FPR target or expression anchors.

It then emits a `post-source-model-ceiling-next-axis-discovery` artifact with
ranked backend/codegen diagnostics and a terminal proof that no modeled
non-source axis is available yet. It must not re-emit a terminal source family
as the next action.

## Tests And Smokes

Regression coverage:

- Draw helper-boundary FPR terminal evidence emits FPR backend/codegen axes and
  preserves IG32/IG37/IG46 expression anchors.
- Sort cross-TU GPR terminal evidence emits GPR backend/codegen axes and
  preserves IG34/IG44 target anchors.
- CLI writes JSON, returns `3` for the terminal no-modeled-axis proof, and
  includes diagnostic command hints.
- Capability search finds `debug search post-source-ceiling-axis`.
- Debug help goldens include the current command surface.

Smoke commands use compact test fixtures when reporter diagnostics are not
present in the active checkout, and real issue artifact paths when available.
