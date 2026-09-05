# Issue 1038: Draw Retained Row Offset Split

## Root Cause

Issue #1037 added whole-function FPR source-model synthesis for
`mnDiagram_DrawCellNumber`, but its readiness gate still required the legacy
`y_offset` source shape. The live retained Draw source had already split that
work into the retained `row_offset`/`rowf` form:

```c
row_offset = HSD_JObjGetTranslationY(jobj2) - base;
rowf = (f32) row;
row_offset *= rowf;
row_offset_adj = row_offset - 0.4f;
```

The same retained source also uses `mnDiagram_ArchiveData* joint_data`,
`joint_data = &mnDiagram_804A07F4`, and typed `joint_data->...` asset fields
instead of the legacy `void**` array indexing. Because the readiness gate and
joint-data owner rewrite only recognized the older shape, the
`draw-post-source-context-whole-function-fpr-source-model` dimension blocked
with `source-patterns-not-found` and materialized no candidates.

## Fix Plan

1. Treat the existing Draw offset-region recognizer as the source of truth for
   both legacy `y_offset` and retained `row_offset`/`rowf` setup.
2. Loosen the data and joint-data anchors so they accept the live retained
   spelling: any `HSD_GObj*` parameter name and optional `&` before
   `mnDiagram_804A07F4`.
3. Make the joint-data owner transform work from the loop's current
   `HSD_JObjLoadJoint` and `HSD_JObjAddAnimAll` arguments, instead of assuming
   only `joint_data[0..3]`.
4. Add a retained-source regression fixture that uses the live split and typed
   archive-data fields, then assert that all six bounded whole-function
   candidates materialize with source hunks/components.

## Verification Target

The fixed generator should produce the six expected
`draw-post-source-context-whole-function-fpr-source-model` candidates from the
retained source and, when run from the retained worktree with scoring enabled,
each candidate should retain a pcdump and carry target/expression scores.
