# Issue 1032: Draw Alternate FPR Expression Source Model

`mnDiagram_DrawCellNumber` has a bounded post-ceiling source-model family for
the alternate Draw FPR expression structure:

- dimension: `draw-alternate-fpr-expression-structure`
- trigger: Draw FPR context whose terminal evidence names an alternate Draw FPR
  expression structure and also shows the previous source-family/coupled lanes
  are exhausted
- non-trigger: `draw-coupled-post-meta-fpr-expression-lifetime` by itself

When the alternate stage is active, source-family synthesis suppresses the
older Draw local, expression-interferer, and coupled lanes. The generated probes
only cover the alternate dimension, so stale `1/3` rows from older lanes are not
reintroduced as actionable candidates.

The bounded set changes at least two of the related FPR expression sites or
adds cross-site ordering:

- `col_offset` product/cast ownership
- `row_offset` row delta/translation/scale ownership
- digit animation call argument/fsubs temp

The default generation path emits the full bounded set for this dimension. An
explicit lower `--max-per-dimension` still caps it; `--max-per-dimension 12`
requests the complete modeled set.

Score classification treats the retained post-1031 ceiling as a floor:

- target floor: at least `1/3`
- expression floor: at least `1/3`

An alternate-stage row is source-actionable only when its structural guard is
accepted, score-source returned no error, required assignments are satisfied,
and either target or expression matched count exceeds that floor. Rows at the
floor are retained as evidence.

If all bounded candidates score at or below the floor, synthesis emits a
terminal proof with:

- `status: "terminal"`
- terminal blocker
  `draw-alternate-fpr-expression-structure-no-floor-improvement`
- exhausted dimension `draw-alternate-fpr-expression-structure`
- next family
  `draw-no-modeled-source-actionable-family-after-alternate-fpr-expression-structure`
- next model stating that no modeled source-actionable Draw family remains

Retained-frontier triage ranks this alternate terminal above older coupled Draw
proofs, and allocator ceiling reports the retained-frontier terminal as a
practical ceiling with the alternate next model/family preserved in next steps.
