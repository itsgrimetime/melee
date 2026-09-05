# Issue 873: Expression-Anchored FPR Target Scoring

## Problem

`debug target score-source` and `debug target score-dump` scored FPR targets by
raw MWCC virtual id. That is misleading when a source transform inserts or
removes visible FPR temporaries, because the same numeric virtual can name a
different expression after renumbering.

For `mnDiagram_DrawCellNumber`, the raw target spec expected `f33 -> f26`.
After the coupled FPR repair probe, `f33` became the column product and the
original digit call temp moved to `f32`. The raw scorer counted `f33 -> f26` as
progress even though the digit call temp was still assigned `f1`.

There was also an attribution bug: pcode-only FPR virtuals with no colorgraph
mapping fell back to GPR lookup, so `virtual-to-var --class fpr` could report a
GPR-ish first definition for an FPR temp.

## Design

Keep raw virtual-id scoring unchanged for compatibility, but add opt-in
expression scoring metadata:

- `--expression-baseline <pcdump>` derives expression anchors for the target
  virtuals from a trusted baseline dump.
- Target specs may also embed `expression_anchors` directly, so downstream
  validation does not need the baseline dump again.
- Candidate virtuals are attributed with the existing `explain_virtuals`
  bridge. The scorer compares normalized expression signatures, not raw virtual
  ids.
- The JSON output reports `expression_score`, including candidate virtual,
  actual physical register, renumbering, and explicit
  `virtual_id_false_positive` entries.
- Transform validation preserves `expression_score` and ranks guarded partials
  by expression score when present, falling back to raw `target_score`.

## Validation

Regression tests cover:

- Pcode-only FPR temps stay in FPR attribution and preserve their assigned
  physical register.
- A synthetic `f33` virtual-renumber false hit is flagged by
  `debug target score-dump --expression-baseline`.
- Embedded `expression_anchors` work without a baseline dump.
- Transform validation evidence preserves `expression_score` and ranking uses it
  over misleading raw virtual hits.

Manual smoke against the issue pcdumps:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug target score-dump \
  -f mnDiagram_DrawCellNumber \
  --target /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_785_target_spec_from_residual.json \
  /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_875_coupled1_baseline.pcdump.txt \
  --expression-baseline /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_874_clean_baseline.pcdump.txt \
  --json
```

The raw score reports `matched=4`; the expression score reports `matched=3`,
`false_positive_virtual_id_hit_count=1`, and shows the baseline digit temp
`f33` moved to candidate `f32` with actual `f1`.
