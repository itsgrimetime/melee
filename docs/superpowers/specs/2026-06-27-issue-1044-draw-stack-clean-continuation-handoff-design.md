# Issue 1044: Draw Stack-Clean Continuation Handoff Design

## Context

Issue #1044 is a follow-up to #1043. The source-model layer now recognizes the
Draw product/translate opcode-clean stack-layout seed, but the matcher still
receives a null retained frontier after the next continuation layer exhausts.

The observed continuation artifact is terminal with
`post-meta-fpr-expression-hit-continuation-exhausted/protected-anchor-ceiling`.
It carries `unsupported_source_expression_class` =
`draw-coupled-post-meta-fpr-expression-lifetime` and ranked retained candidate
evidence, but no `next_unsupported_source_dimension`, no actionable
`next_frontier`, and no explicit terminal blocker for the helper fallback.
The bounded `debug suggest inlines --verify` run produced only rejected
`void-helper` candidates, so it emitted no patches or scores.

## Goal

When Draw stack-clean/no-anchor continuation reaches the protected-anchor
ceiling, tooling must not silently collapse to `next_frontier: null`. It must
either expose an actionable handoff lane or preserve an explicit terminal
blocker that tells the matcher why no helper/inline route exists.

## Approach

Use an explicit handoff instead of trying to synthesize a larger recovery
family in this change. The artifact already names the next unsupported source
class and carries the retained source hunks and scores that explain the
ceiling. Retained-frontiers can turn that terminal proof into a source-actionable
helper/inline-boundary handoff lane, and allocator-ceiling can render that lane
as the next step. This unblocks the matcher without pretending there is a
bounded C patch family when the evidence says the remaining lever is an
unmodeled expression lifetime or helper boundary.

## Retained-Frontier Behavior

For `mnDiagram_DrawCellNumber`, terminal
`post-meta-source-family-continuation-proof` rows with
`unsupported_source_expression_class` =
`draw-coupled-post-meta-fpr-expression-lifetime` should produce one public
source-actionable lane when no newer modeled lane exists.

The lane must:

- use a stable dimension, `draw-coupled-fpr-expression-lifetime-helper-boundary-handoff`;
- retain the attempted force vector for IG32, IG37, and IG46;
- include the unsupported source model/class;
- include ranked retained candidates or candidate summaries from the terminal
  proof;
- preserve best-effort evidence from the terminal proof, including
  `source_retained`, `pcdump_path`, `source_hunks`, `target_score`,
  `expression_score`, `target_virtual_facts`, `expression_virtual_facts`, and
  `stack_frame_facts` when present on the terminal proof, source-model proof,
  source-family synthesis, or ranked retained candidates;
- include a continuation command that points the matcher at helper/inline
  boundary investigation, starting from `debug suggest inlines --verify` and
  `debug suggest inline-boundary-continuation` when an inline-leverage report is
  available;
- avoid reopening once a later terminal proof explicitly marks the same handoff
  exhausted.

The handoff ranks after `draw-post-product-translate-stack-clean-no-anchor-recovery`.
In retained-frontier stage terms this means stack-clean/no-anchor remains stage
12, and the helper-boundary handoff is stage 13. Later modeled lanes may rank
above 13, but older product/translate and stack-clean terminals must not
suppress this lane.

The terminal closure schema for this handoff is:

- `family_id` and `suppression_family`:
  `draw-coupled-fpr-expression-lifetime-helper-boundary-handoff`;
- `kind`: `draw-coupled-fpr-expression-lifetime-helper-boundary-terminal`;
- `status`: `terminal`;
- `terminal: true`;
- `terminal_reason`: `all-inline-helper-candidates-rejected`;
- `terminal_blocker`: `all-inline-helper-candidates-rejected`;
- `final_force_phys`: the same attempted force vector used by the handoff
  lane;
- `unsupported_source_expression_class`:
  `draw-coupled-post-meta-fpr-expression-lifetime`.

Retained-frontiers should treat either this terminal closure shape or a
terminal proof that already carries the handoff dimension with
`all-inline-helper-candidates-rejected` as completed evidence and must not
reopen the lane for the same function and force vector.

## Suggest-Inlines Behavior

`debug suggest inlines --verify --json` must make an all-rejected candidate set
explicit. If candidates exist but no patches are generated, the JSON payload
should include:

- `status: terminal`;
- `terminal_blocker: all-inline-helper-candidates-rejected`;
- `terminal_blockers`: a list of objects shaped as
  `{"reason": <rejection_reason>, "count": <candidate_count>, "candidate_ids": [...]}`;
- a message explaining that verification had no accepted patches to score.

This is expected for void-helper candidates that write locals without output
parameters. The command should keep returning successfully because it produced a
diagnostic report; the machine-readable terminal fields are the missing
contract.

Implement these fields on `SourceShapeReport` itself rather than as a
renderer-only envelope, so text and JSON rendering share the same terminal
contract.

## Tests

Add focused regressions for:

- retained-frontiers promoting a Draw coupled FPR lifetime terminal proof into
  a source-actionable helper-boundary handoff;
- retained-frontiers not reopening the handoff when a completed terminal proof
  for that handoff is present;
- allocator-ceiling rendering the helper-boundary handoff as actionable next
  steps;
- suggest-inlines JSON exposing a terminal blocker when all candidates are
  rejected and no patches/scores exist.

## Non-Goals

This change does not implement a new source synthesis search that can recover
IG32, IG37, or IG46. It only preserves the best available evidence and creates
an explicit handoff to the next unsupported helper/expression-lifetime layer.
