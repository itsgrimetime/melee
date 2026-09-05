# Issue 1078: Draw Expression-Anchor Ownership Continuation

## Problem

`mnDiagram_DrawCellNumber` source-model synthesis handed off from the
post-stack loop-callsite source-context layer to
`draw-post-stack-loop-callsite-expression-anchor-source-ownership`, but the
Draw profile had no first-class dimension for that family. Candidate generation
returned no probes once the loop-callsite source-context dimension was marked
exhausted, so the matcher could not retry the retained row-offset owner split or
the remaining expression-anchor owner repairs.

## Plan

1. Add a Draw expression-anchor ownership dimension after the existing
   loop-callsite source-context dimension.
2. Let source-model generation enter that dimension before the old
   loop-callsite-exhausted early return.
3. Generate bounded retained-source owner probes from the loop-callsite seed:
   row-offset owner split, column-product owner split when the seed shape
   supports it, and digit-base owner split.
4. Preserve source route metadata on those candidates so `score-source` can
   validate target, expression, and structural guard outcomes.
5. Teach scored terminal proof construction to classify this dimension
   precisely and hand off to the final no-modeled-source owner family when the
   owner probes do not improve.
6. Cover generation, terminalization, and stale-dimension normalization with
   focused regressions.

## Verification

- `python -m py_compile tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
- `python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k 'post_stack_loop_callsite or expression_anchor'`
- `python -m src.cli debug search source-model-synthesis --function mnDiagram_DrawCellNumber --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1075_1077_rerun/draw_expression_anchor_ownership/source_model_scored.json --write-probes /tmp/melee-1078-expression-anchor-owner-probes --max-per-dimension 8 --no-score --json`

