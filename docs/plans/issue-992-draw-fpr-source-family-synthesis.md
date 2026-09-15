# Issue 992: Draw FPR Source-Family Synthesis

## Problem

`mnDiagram_DrawCellNumber` reached a retained-frontiers/meta-ceiling state where
all modeled frontiers are exhausted, but the final proof named an unsupported
source model: broader Draw FPR expression source-family synthesis. The missing
layer needed to consume `meta_ceiling_draw.json`, generate score-source-ready
probes for the remaining expression families, and either surface ranked progress
or close the family with a retained-frontiers-compatible terminal proof.

## Scope

- Reuse the issue 991 `debug search source-model-synthesis` command.
- Generalize the implementation by function profile instead of adding a second
  command.
- Preserve Sort/GPR behavior.
- Add Draw/FPR support for:
  - `draw-col-cast-product-local`
  - `draw-row-translation-scale-split`
  - `draw-digit-callarg-fsubs-temp`
- Score Draw probes with `--expression-reg-class fpr`.
- Treat either `expression_score` progress or `target_score` progress as
  actionable when the structural guard is accepted.
- Emit terminal evidence using the existing
  `post-ceiling-source-model-proof` / `source_family_synthesis` contract.

## Verification Targets

- Draw context normalization selects IG32->f28, IG37->f26, and IG46->f26 from
  allocator facts.
- Generated Draw candidates include all three required dimensions and carry FPR
  score hints.
- Offline score classification ranks expression progress.
- Terminal proofs preserve expression anchors for `col_offset`, `row_offset`,
  and `fsubs f46,f45,f44`.
- `debug search retained-frontiers --artifact <terminal.json>` consumes the
  terminal proof as a `post-ceiling-source-model-proof` frontier.
