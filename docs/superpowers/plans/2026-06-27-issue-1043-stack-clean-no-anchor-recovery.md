# Issue 1043 Implementation Plan

## Step 1: Constants And Evidence Helpers

- Add stack-clean/no-anchor recovery constants to
  `post_meta_source_family_synthesis.py`, `retained_frontier_triage.py`, and
  `allocator_ceiling.py`.
- Add source-model helpers to identify product/translate stack-clean/no-anchor
  rows, reading nested `structural_guard` fields for normalized diff, opcode
  similarity, expected/current frame, and frame delta.
- Add retained-frontier helpers to consume the published evidence, rank seed
  rows if needed, extract frame facts, extract virtual anchor facts, and build
  ranked repair handoffs.

## Step 2: Source-Model Evidence Publication

- When product/translate exhaustion contains stack-clean/no-anchor evidence,
  publish `stack_clean_no_anchor_evidence` on both the top-level source-model
  proof and nested `source_family_synthesis`.
- Set `next_unsupported_source_dimension` to
  `draw-post-product-translate-stack-clean-no-anchor-recovery`.
- Do not replace structural rejection with structural acceptance.
- Once the stack-clean/no-anchor recovery dimension has terminalized, publish
  the new final family/model instead of reopening the handoff.

## Step 3: Retained-Frontier Handoff

- When terminal product/translate source-model proof contains stack-clean
  evidence and no completed stack-clean terminal proof exists, synthesize an
  actionable frontier for
  `draw-post-product-translate-stack-clean-no-anchor-recovery`.
- Preserve seed candidate id, pcdump path, source-retained path, source hunks,
  target score, expression score, frame facts, and IG32/IG37/IG46 virtual facts.
- Rank this synthesized frontier above the product/translate terminal proof.
- Detect completed stack-clean terminal proofs through nested
  `attempted_equivalence_classes`, `exhausted_dimensions`, terminal reason, and
  next unsupported family/model/dimension so the lane does not reopen itself.

## Step 4: Terminal Propagation

- Support completed stack-clean/no-anchor terminal proofs.
- Ensure synthesized retained-frontier meta ceilings and allocator terminal
  output use the new final family/model once this recovery dimension is closed.

## Step 5: Allocator Output

- Teach allocator-ceiling to recognize the new recovery dimension as actionable.
- Add next-step text that points the matcher at the stack-clean seed source,
  pcdump, source hunks, frame delta, and missing FPR anchors.
- Add text rendering for terminal proof evidence.

## Step 6: Capability Search

- Add capability aliases for stack clean/no anchor continuation and the new
  dimension/final family.

## Step 7: Tests And Smokes

- Add source-model tests that assert the issue-shaped product/translate terminal
  output publishes the new evidence and next dimension before the final
  product/translate family.
- Add retained-frontier tests for synthesized actionable handoff and terminal
  replacement of the product/translate final family.
- Add allocator tests for actionable and terminal stack-clean/no-anchor lanes.
- Add capability search tests.
- Include false-positive checks for accepted guards, non-stack classifications,
  opcode below threshold, missing retained source/pcdump/hunks, non-product
  candidates, and non-Draw/non-FPR cases.
- Run focused pytest suites and command-level replay smokes over the #1042
  product/translate artifact.
