# Issue 1044: Draw Stack-Clean Continuation Handoff Plan

## Global Constraints

- Preserve the existing #1043 stack-clean/no-anchor recovery behavior.
- Do not mark a terminal helper/inline fallback as actionable unless it carries
  enough command/evidence for a matcher to continue.
- Keep all changes inside `tools/melee-agent`, tests, and this spec/plan.
- Use focused regression tests before or alongside production changes.

## Task 1: Retained-Frontier Helper Handoff

Add a retained-frontier lane for terminal Draw coupled FPR expression lifetime
proofs. The lane should be source-actionable, carry the force vector and ranked
candidate evidence, and use the dimension
`draw-coupled-fpr-expression-lifetime-helper-boundary-handoff`.

Regression tests:

- a Draw terminal continuation with unsupported class and ranked retained
  candidates yields `status: actionable` and a non-null `next_frontier`;
- the handoff preserves pcdump/source-hunk/score/virtual-fact/stack-frame
  evidence when present on the terminal proof or ranked candidates;
- a completed terminal proof for the same handoff does not reopen the lane.
- the handoff ranks after stack-clean/no-anchor stage 12 and before any future
  stage above 13.

## Task 2: Allocator-Ceiling Rendering

Teach allocator-ceiling to recognize the retained-frontier handoff and render
useful next steps. The output should name the unsupported class/model and show
the continuation command. It should also preserve any pcdump/source evidence in
the payload so downstream command-level smoke checks can inspect it.

Regression test:

- feeding allocator-ceiling retained meta with the handoff reports
  `status: actionable` and includes a helper/inline-boundary next step.

## Task 3: Suggest-Inlines Terminal Blocker

Teach `debug suggest inlines --verify --json` to report a terminal blocker when
all discovered candidates are rejected and therefore no patches/scores can be
generated. Preserve the existing candidate details. Add the terminal fields to
`SourceShapeReport`, with `terminal_blockers` shaped as
`{"reason": str, "count": int, "candidate_ids": [str, ...]}`.

Regression tests:

- a `SourceShapeReport` with only rejected candidates reports terminal status,
  blocker, and rejection counts in JSON;
- text output includes the terminal blocker message.
- retained-frontiers recognizes a suggest-inlines terminal closure artifact with
  `family_id: draw-coupled-fpr-expression-lifetime-helper-boundary-handoff` and
  does not reopen the helper-boundary lane.

## Task 4: Smoke Verification

Replay the issue artifacts:

- retained-frontiers on
  `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1043_rerun/draw_stack_clean_continuation/source_family_continuation_1043.json`;
- allocator-ceiling on the retained output;
- `debug suggest inlines --verify --json` for `mnDiagram_DrawCellNumber` with
  the issue pcdump.

Expected result: the retained/allocator path is actionable, and suggest-inlines
reports an explicit terminal blocker instead of an empty patch/score set.
