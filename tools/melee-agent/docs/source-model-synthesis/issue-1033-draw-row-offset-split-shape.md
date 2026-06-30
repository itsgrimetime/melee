# Issue 1033: Draw row_offset split shape

## Summary

The Draw alternate FPR expression-structure family supports both retained
offset shapes used by `mnDiagram_DrawCellNumber` probes:

- Legacy shape:
  `y_offset = HSD_JObjGetTranslationY(jobj2); y_offset -= base;`
  followed by direct `col_offset` and `row_offset` products.
- Retained split shape:
  `row_offset = HSD_JObjGetTranslationY(jobj2) - base;`,
  `col_offset = (f32) col; col_offset *= y_spacing;`,
  `rowf = (f32) row; row_offset *= rowf;`.

The split replacements keep generated source in terms of `row_offset`, `rowf`,
and `post_alt_*` locals. They do not introduce `y_offset`, since the retained
split source does not safely declare it in real source.

## Candidate Contract

The retained split shape materializes the same eight alternate candidate IDs as
the legacy shape:

- `draw-alternate-fpr-paired-cast-staging-digit-copy`
- `draw-alternate-fpr-row-inline-product-digit-inline`
- `draw-alternate-fpr-row-translation-owner-digit-copy`
- `draw-alternate-fpr-reversed-col-product-digit-fsubs`
- `draw-alternate-fpr-shared-expression-block`
- `draw-alternate-fpr-digit-inline-col-row-reorder`
- `draw-alternate-fpr-paired-cast-staging-digit-fsubs-temp`
- `draw-alternate-fpr-row-delta-before-col-delayed-scale`

Unsupported retained row-product variants in the alternate stage terminalize
with blocker reason `unsupported-retained-row_offset-product-shape` and hand off
to the alternate exhausted next family/model.
