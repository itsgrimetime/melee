# Issue 1043: Draw Stack-Clean No-Anchor Recovery

## Problem

The #1042 Draw product/translate expression-graph lane generated and scored
four candidates. One candidate,
`draw-post-all-known-product-translate-graph-col-product-before-row-delta-with-y-offset`,
preserved normalized opcode shape (`normalized_diff_lines: 0`,
`opcode_similarity: 1.0`) but was rejected by the structural guard as
`stack-layout` with a +8 frame delta. It also recovered none of the protected
FPR anchors for IG32, IG37, or IG46.

Today that useful lower-hill state is flattened into the product/translate
terminal proof. Retained-frontiers returns `next_frontier: null`, and
allocator-ceiling reports that no modeled source-actionable lanes remain. The
matcher loses the seed source, pcdump, source hunks, frame facts, and virtual
anchor facts needed for the next bounded recovery step.

## Goal

Add a reusable post-product/translate recovery lane for stack-clean/no-anchor
evidence:

`draw-post-product-translate-stack-clean-no-anchor-recovery`

The lane must preserve the stack-clean seed candidate as a repair handoff and
rank it above the exhausted product/translate terminal proof. If a later
artifact proves that bounded recovery cannot use the seed, the terminal proof
must close this new dimension explicitly instead of falling back to the
product/translate final family.

## Design

Source-model synthesis owns the durable evidence marker. It must publish the
stack-clean/no-anchor evidence and set the next unsupported source dimension to
the recovery lane before retained-frontiers consumes the artifact. Retained-
frontiers then turns that published evidence into an actionable repair handoff.
This avoids weakening structural guards or re-running broad source generation.

A stack-clean/no-anchor row is one that:

- belongs to the product/translate dimension,
- has structural guard classification `stack-layout`,
- has `normalized_diff_lines == 0`,
- has `opcode_similarity >= 0.999`,
- has a nonzero frame delta or expected/current frame facts,
- targets all protected anchors but matches zero target/expression anchors,
- retains source hunks and preferably pcdump/source-retained paths.

The synthesized frontier carries:

- seed candidate id and dimension,
- source hunks, pcdump path, and retained source path,
- target score and expression score,
- structural/frame facts,
- virtual facts for IG32, IG37, and IG46,
- ranked recovery handoffs for row-delta anchor, digit fsubs anchor, col product
  anchor transfer, and frame-clean owner pruning.

The source-model proof and nested source-family synthesis proof both carry the
same `stack_clean_no_anchor_evidence` block so non-retained-frontier consumers do
not see the old product/translate layer as final.

Allocator-ceiling treats this frontier as actionable and renders the recovery
instructions and evidence. Terminal proofs for the new dimension advance to:

`draw-no-modeled-source-actionable-family-after-post-product-translate-stack-clean-no-anchor-recovery`

## Non-Goals

- Do not mark the stack-layout row structurally accepted.
- Do not hide or ignore the +8 frame delta.
- Do not broaden product/translate candidate generation for this fix.
- Do not edit `src/melee/mn/mndiagram.c`.

## Verification

Regression tests cover retained-frontier synthesis, terminal proof propagation,
allocator actionable/terminal rendering, and capability search aliases. Command
smokes replay the #1042 artifact through retained-frontiers and
allocator-ceiling to verify it no longer collapses to a null frontier at the
product/translate layer.
