# Expression-Aware FPR Source Generation Design

## Context

Issue #878 follows the expression-scored `mnDiagram_DrawCellNumber` frontier:
the retained source preserves the protected FPR anchors but leaves
`col_offset_product_fpr` in `f25` instead of the expected `f28`. Existing
ranking can explain the failure as Case A row_offset interference plus a C2
sticky-pool residual, but it did not emit source-actionable C candidates.

## Contract

`debug suggest expression-interferer-repair` remains the pure ranker for
pre-scored candidate JSON. When passed `--source-file`, it also emits a
`source_generation` payload with bounded row/product source candidates:

- `row-offset-owner-split`: introduces a source-visible owner for the unscaled
  `row_offset` value and scales from that owner later.
- `product-owner-sticky-copy`: introduces a source-visible owner copy for
  `col_offset_product_fpr` to probe C2 sticky-pool compensation.
- `row-owner-product-interleave`: moves the product assignment between the
  row-offset owner and scaled row-offset use to probe the Case A boundary.

The generated JSON includes `candidate_id`, `family`, `strategy`, `priority`,
`rationale`, `expected_effect`, `blocker_cases`, `source_hunks`, and either
full `source_text` (`--include-source`) or written candidate paths
(`--write-probes`). The command never treats a force-only proof as success.
Validation remains the existing `debug target score-source` expression-score
workflow so compile behavior stays in one place.

## Source Function Aliases

Diagnostic labels can differ from the C symbol in a retained source file. The
command accepts `--function` for the diagnostic label and `--source-function`
for the function definition to patch. If the source function is absent, the JSON
payload reports a source-function diagnostic instead of silently returning an
empty generated set.

## Stop Semantics

The ranker summary keeps its existing `status` and Case A/C2 blocker fields.
The generation payload has its own status:

- `generated`: retained source candidates and hunks were emitted for external
  scoring.
- `blocked`: the requested source function or row/product anchors could not be
  found.

Matching agents should score emitted candidates and accept only natural 6/6
expression scores that keep protected anchors matched.
