# Issue 1061: Draw Post-Stack No-Anchor Next Source Family

## Scope

Plan/design only. Do not edit production or test files in this pass.

Issue #1061 is for `mnDiagram_DrawCellNumber` after the current Draw
post-stack/no-anchor source-shape family exhausts:

- `draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis`
- terminal reason:
  `draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis-exhausted/no-floor-improvement`
- final sentinel:
  `draw-no-modeled-source-actionable-family-after-post-stack-clean-no-anchor-fpr-source-shape-hypothesis`

The reporter artifacts reviewed are:

- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1058_1059_rerun/draw_frontiers_after_current_post_product/draw_allocator_after_current_post_product.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1058_1059_rerun/draw_post_stack_no_anchor_from_current/source_model_draw_post_stack_no_anchor_scored.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1058_1059_rerun/draw_frontiers_after_post_stack_terminal/draw_allocator_after_post_stack_terminal.json`

## Root Cause

The current implementation correctly fixed the previous handoff: post-product
terminal evidence now routes to
`DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION`, and
`source-model-synthesis` generates the expected post-stack/no-anchor probes.

The gap is one layer later. The final post-stack sentinel is represented as a
terminal "no modeled source-actionable family" state, but there is no modeled
source family that consumes that sentinel and the retained
`post_stack_clean_no_anchor_evidence`.

Concretely:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
  has constants and generation for the current layer:
  `DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION`,
  `_draw_post_stack_clean_no_anchor_source_shape_candidates()`, and
  `_draw_post_stack_clean_no_anchor_source_shape_specs()`.
- `_terminal_next_unsupported_source_model()` and
  `_terminal_next_unsupported_source_family()` return the final sentinel after
  that dimension is attempted.
- `_meta_ceiling_source_model_stage_rank()` ranks the post-stack final sentinel
  as the newest Draw stage.
- `generate_source_family_candidates()` has exclusive Draw branches through
  `draw_post_stack_clean_no_anchor_source_shape_only`, but no branch that
  activates when the current ceiling already names
  `DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY`.
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
  similarly treats the post-stack terminal as the latest concrete proof
  (`_source_model_proof_stage_rank()` returns stage 14), above the older helper
  boundary handoff stage 13. There is no stage 15 next-family proof.

The scored post-stack rows also show why another declaration/local packing
family is unlikely to help:

- `row-delta-callsite-late-materialize` preserves normalized opcode shape
  (`normalized_diff_lines=0`, opcode similarity 1.0) but grows the frame to
  184 and still has 0/3 target and expression anchors.
- `digit-base-post-anim-temp` and `row-delta-two-step-owner-reuse` produce
  signature-shape drift and still have 0/3 anchors.
- IG32 remains `f26`, IG37 is absent/`f27`/`f28`, and IG46 is `f2` or absent.

The missing layer therefore needs to change the source ownership around the
loop body/calls that create the FPR expression graph, seeded from the retained
post-stack source, not keep rearranging the same pre-loop locals.

## Candidate Next-Family Approaches

### 1. Post-Stack Loop/Callsite Ownership Source Model (Recommended)

Add a bounded family, tentatively:

```text
draw-post-stack-clean-no-anchor-loop-callsite-source-context
```

This family should consume the post-stack final sentinel and use the retained
post-stack seed source from `post_stack_clean_no_anchor_evidence` /
`retained_scored_probes`, then generate a small set of function-local C probes
around:

- loop digit object ownership: carry `HSD_JObjLoadJoint(...)` through a
  separate `digit_jobj` or `jobj_owner`;
- animation argument ownership: stage `(f32) digit` through one or two loop-local
  owners before `HSD_JObjReqAnimAll`;
- translate-X ownership: name `(x_spacing * (f32) i)` and/or the final
  translated X argument before the `SetTranslateX` branch;
- translate-Y ownership: name the selected row Y argument inside the branch,
  rather than just moving pre-loop `row_offset`;
- add-child parent ownership: carry `data_alias->jobjs[11]` through a parent
  owner used in the same loop body.

This is a direct continuation of the current evidence. It reuses already
implemented source-context patching ideas such as
`_patch_draw_source_context_loop_digit_jobj_local()`,
`_patch_draw_source_context_loop_translate_locals()`,
`_patch_draw_whole_function_animation_callarg_owner()`, and
`_patch_draw_source_context_parent_jobj_local()`, but applies them to the
retained post-stack seed instead of the earlier baseline/source-context stage.

Tradeoffs:

- Best fit for the reported failure because it targets the loop/callsite
  expression ownership that the current family never varied.
- Bounded and testable: 4-6 probes, all local to `mnDiagram_80241E78`.
- Some overlap with earlier source-context families, but the seed source is
  materially different after stack-clean/no-anchor recovery. The metadata and
  dimension must make that explicit to avoid reopening older stages.

### 2. Helper/Inline Boundary Extraction Around the Digit Loop

Add a family that uses helper extraction or inline-boundary probes for digit
rendering, translate application, or animation setup.

Tradeoffs:

- Plausible because the remaining FPR shape may be across an implicit helper
  or inline boundary rather than a local ownership issue.
- Higher blast radius: helper prototypes, callsite signatures, and `static`
  helper placement can cause large structural drift.
- There is already an older retained-frontier handoff
  `draw-coupled-fpr-expression-lifetime-helper-boundary-handoff` tied to the
  pre-post-stack coupled-expression lane. Reusing it directly would regress the
  now-current stage ordering unless a new post-stack-specific helper dimension
  is added and ranked above stage 14.

This should remain the follow-up if the recommended loop/callsite family
exhausts without any expression or frame improvement.

### 3. Whole-TU Data/Object Ownership Recontextualization

Re-run broader data/object/source-context probes from the post-stack retained
source: jobj table aliasing, joint-data table ownership, parent ownership, and
digit loop bound ownership across the whole TU.

Tradeoffs:

- Can cover cases where allocator pressure is controlled by nonlocal object or
  data ownership, not just the loop body.
- Significant overlap with older `draw-post-source-context-whole-function-*`
  and `draw-post-all-known-*` families.
- More likely to produce many structurally rejected probes unless bounded very
  tightly.

This is a reasonable third layer, but it is too broad for the immediate #1061
blocker.

## Recommended Design

Implement approach 1 as a new bounded source-model dimension:

```text
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION =
    "draw-post-stack-clean-no-anchor-loop-callsite-source-context"
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON =
    "draw-post-stack-clean-no-anchor-loop-callsite-source-context-exhausted/no-floor-improvement"
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_PATTERN_BLOCKER =
    "draw-post-stack-clean-no-anchor-loop-callsite-source-context/source-patterns-not-found"
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_NO_FLOOR_BLOCKER =
    "draw-post-stack-clean-no-anchor-loop-callsite-source-context/no-target-or-expression-floor-improvement"
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY =
    "draw-no-modeled-source-actionable-family-after-post-stack-loop-callsite-source-context"
```

Suggested final model text:

```text
Draw post-stack-clean/no-anchor loop-callsite source-context synthesis exhausted
bounded digit object, animation callarg, translate-X/translate-Y owner, and
add-child parent owner probes from the retained post-stack seed without
recovering IG32/IG37/IG46 expression anchors or eliminating stack-frame drift
under the structural guard.
```

Generation contract:

- Activate only for `mnDiagram_DrawCellNumber`, `register_class == "fpr"`.
- Trigger when any nested/current proof names
  `DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY` or
  `DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL`, or has
  exhausted `DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION`.
- Do not activate if the new dimension is already exhausted or the new final
  family/model is present.
- Use retained source in this priority order:
  1. best retained row in `post_stack_clean_no_anchor_evidence.retained_scored_probes`
     with `source_retained` and `pcdump_path`;
  2. `post_stack_clean_no_anchor_evidence.ranked_post_stack_clean_probes`;
  3. current `_draw_post_stack_clean_no_anchor_ranked_recovery_rows(context)`;
  4. `stack_clean_no_anchor_evidence.source_retained`.
- Preserve the seed metadata:
  `stack_clean_no_anchor_evidence`,
  `post_stack_clean_no_anchor_evidence`,
  `post_stack_loop_callsite_seed_candidate_id`,
  seed `source_retained`,
  seed `pcdump_path`, and seed structural/frame facts.
- Require target, expression, and structural-guard scoring.
- Candidate count should stay small. Start with 5 probes:
  `loop-digit-jobj-owner`,
  `animation-callarg-owner`,
  `translate-x-owner`,
  `translate-y-select-owner`,
  `combined-loop-callsite-owners`.

The first implementation can reuse existing patcher helpers where they already
match the retained source. Add only narrow new patchers for post-stack-specific
translate-Y branch ownership if the existing source-context patchers do not
materialize that shape.

## Production Files and Functions to Change

### `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add constants near the existing post-stack constants:

- new dimension/final family/model/terminal reason/blockers;
- new candidate prefix;
- required source-pattern strings for diagnostics.

Update `_PROFILES[DRAW_FUNCTION]["dimensions"]` to append the new dimension
after `DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION`.

Add stage predicates:

- `_draw_post_stack_loop_callsite_source_context_requested(context)`
- `_draw_post_stack_loop_callsite_source_context_exhausted(context)`
- `_draw_post_stack_loop_callsite_source_context_stage_active(context)`

Update candidate dispatch in `generate_source_family_candidates()`:

- compute `draw_post_stack_loop_callsite_source_context_only` before
  `draw_post_stack_clean_no_anchor_source_shape_only`;
- return `[]` for already exhausted new terminal contexts unless explicitly
  continuing to a later family in the future;
- suppress older Draw branches when this new branch is active;
- call `_draw_post_stack_loop_callsite_source_context_candidates(...)`.

Add candidate generation:

- `_draw_post_stack_loop_callsite_source_context_candidates(...)`
- `_draw_post_stack_loop_callsite_source_context_specs()`
- `_draw_post_stack_loop_callsite_source_context_spec(...)`
- seed selection helper, e.g.
  `_draw_post_stack_loop_callsite_seed_rows(context)`;
- post-stack seed source text helper, likely generalized from
  `_draw_stack_clean_no_anchor_seed_source_text(...)`.

Add or reuse patchers:

- reuse `_patch_draw_source_context_loop_digit_jobj_local`;
- reuse `_patch_draw_whole_function_animation_callarg_owner`;
- reuse `_patch_draw_source_context_loop_translate_locals` where applicable;
- reuse `_patch_draw_source_context_parent_jobj_local`;
- add post-stack-specific `_patch_draw_post_stack_loop_translate_y_select_owner`
  if needed to stage `row_offset`/`row_offset_adj` selection inside the loop.

Update zero-candidate and terminal handling:

- `_zero_candidate_generation_blockers(...)`
- `_draw_post_stack_loop_callsite_source_context_zero_candidate_generation_blockers(...)`
- `_should_terminalize_zero_candidate_generation(...)`
- `_zero_candidate_terminal_metadata(...)`
- `_draw_no_floor_terminal_blocker(...)`
- a new no-floor blocker helper for the dimension;
- `_terminal_next_unsupported_source_model(...)`
- `_terminal_next_unsupported_source_family(...)`
- `_meta_ceiling_source_model_stage_rank(...)`
- row detector and terminal attempt:
  `_is_draw_post_stack_loop_callsite_source_context_row(...)`
  and `_draw_post_stack_loop_callsite_source_context_terminal_attempt(...)`.

Update terminal evidence retention in `classify_source_family_scores(...)`:

- include the prior post-stack retained evidence in terminal payloads;
- add a new retained evidence helper similar to
  `_draw_post_stack_clean_no_anchor_source_shape_retained_terminal_evidence(...)`;
- ensure `attempted_equivalence_classes`, `exhausted_dimensions`,
  `retained_scored_probes`, `source_hunks_by_candidate`, and terminal blockers
  refer to the new dimension, not the previous post-stack dimension.

### `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`

Generalize the local `stack_clean_recovery_source_retained()` helper used by
`source_model_synthesis_cmd()` so it can resolve the default source file for
the new dimension from `post_stack_clean_no_anchor_evidence`.

Import the new dimension constant and include it in the default-source-file
condition. Without this, a CLI call against
`draw_allocator_after_post_stack_terminal.json` may fall back to
`src/melee/mn/mndiagram.c` instead of the retained post-stack seed.

### `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`

Add matching constants for the new dimension/final family/model.

Update ranking and terminal detection:

- `_source_model_proof_stage_rank(...)`: rank the new dimension/final sentinel
  above post-stack source-shape stage 14. Use stage 15.
- `_retained_meta_terminal_group_priority(...)`: prefer the new terminal over
  the old post-stack source-shape terminal when both exist.
- terminal group aggregation around the current post-stack special-case should
  add the new exhausted dimension and next family/model when the new proof is
  present.
- add `_retained_post_stack_loop_callsite_source_context_completed(...)` or a
  generic equivalent.
- update source-model evidence scoring so retained `post_stack_clean_no_anchor_evidence`
  plus the new dimension outranks stale stage-14 proofs.

No change should reopen the older
`draw-coupled-fpr-expression-lifetime-helper-boundary-handoff` lane when a
stage-14 or stage-15 terminal proof exists.

### `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_ceiling_baseline_escape.py`

Likely no large change is needed if retained-frontier triage emits the new
terminal proof with the normal `source_family_synthesis` schema. Do a focused
check of:

- `_retained_source_model_proof_summary(...)`
- `_retained_source_model_proof_concrete(...)`
- `_source_model_closed_families(...)`

Only add pass-through handling if allocator-ceiling drops the new
`next_unsupported_source_family`, evidence, or exhausted-dimension fields.

### Optional Docs/Capability Files

Add a short implementation note under:

- `/Users/mike/code/melee/tools/melee-agent/docs/source-model-synthesis/`

If capability search relies on static docs/catalog entries, update the relevant
capability metadata so:

```bash
melee-agent capabilities search "draw post stack no anchor loop callsite source context"
```

finds `debug search source-model-synthesis`.

## Regression Tests

### `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add focused tests:

1. `test_draw_post_stack_source_shape_final_handoff_generates_loop_callsite_probes`
   - Build a synthetic current ceiling equivalent to the #1061 terminal.
   - Include `post_stack_clean_no_anchor_evidence` with retained scored probes.
   - Assert generated candidates all use the new dimension and candidate prefix.
   - Assert no old `draw-post-stack-clean-no-anchor-shape-*` probes are emitted.
   - Assert validation metadata carries both stack-clean and post-stack evidence.

2. `test_draw_post_stack_loop_callsite_scored_rows_terminalize_with_next_family`
   - Score all new candidates at 0/3 target and 0/3 expression, structural
     guard accepted or rejected with no floor improvement.
   - Assert terminal reason is the new terminal reason.
   - Assert `next_unsupported_source_family` is the new final family, not the
     old post-stack source-shape final family.
   - Assert retained scored probes and source hunks are preserved.

3. `test_draw_post_stack_loop_callsite_actionable_on_anchor_or_frame_improvement`
   - One scored candidate improves IG32/IG37/IG46 expression or target floor,
     or fixes frame drift under accepted structural guard.
   - Assert `status == "actionable"` and the candidate is ranked.

4. `test_draw_post_stack_loop_callsite_zero_candidates_terminalize_with_blocker`
   - Use a malformed/abstract retained seed missing the digit-loop source span.
   - Assert zero-candidate terminal uses the new pattern blocker and final
     family/model.

5. `test_cli_source_model_synthesis_writes_draw_post_stack_loop_callsite_probes`
   - Use `CliRunner` with a fixture current ceiling naming the #1061 final
     family and a retained seed file.
   - Assert probes are written and candidate paths exist.

### `/Users/mike/code/melee/tools/melee-agent/tests/test_retained_frontier_triage.py`

Add tests:

1. New terminal proof beats old post-stack source-shape terminal regardless of
   artifact order.
2. A stale stage-14 terminal does not suppress a newer stage-15 terminal.
3. Existing helper-boundary handoff is not reopened when a post-stack
   source-shape or loop-callsite terminal exists.
4. `synthesize_retained_frontier_meta_ceiling(...)` reports the new final
   family/model in `terminal_groups[0]` and `terminal_proof`.

### `/Users/mike/code/melee/tools/melee-agent/tests/test_post_ceiling_baseline_escape.py`

Only add coverage if the focused allocator-ceiling check shows dropped fields.
The useful regression would feed a retained terminal proof with the new
`source_family_synthesis` and assert allocator output preserves:

- `current_ceiling.next_unsupported_source_family`;
- `current_ceiling.source_family_synthesis.exhausted_dimensions`;
- `post_stack_clean_no_anchor_evidence`.

### `/Users/mike/code/melee/tools/melee-agent/tests/test_capabilities.py`

Optional if capability metadata/docs are updated. Assert capability search text
includes the new family terms or at least still routes to
`debug search source-model-synthesis`.

## CLI Smoke Checks

Run from `/Users/mike/code/melee` after implementation.

Capability routing:

```bash
melee-agent capabilities search "draw post stack no anchor loop callsite source context"
```

Generation from the reported terminal allocator:

```bash
melee-agent debug search source-model-synthesis \
  --function mnDiagram_DrawCellNumber \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1058_1059_rerun/draw_frontiers_after_post_stack_terminal/draw_allocator_after_post_stack_terminal.json \
  --write-probes build/diagnostics/issue_1061_draw_post_stack_loop_callsite/probes \
  --max-per-dimension 8 \
  --json
```

Expected generation output:

- `status: "generated"`;
- `candidate_count > 0`;
- all generated candidates have
  `dimension_id == "draw-post-stack-clean-no-anchor-loop-callsite-source-context"`;
- no generated candidates start with
  `draw-post-stack-clean-no-anchor-shape-`;
- candidate metadata points at the retained post-stack source, not the baseline
  `src/melee/mn/mndiagram.c`, unless a source override was explicitly provided.

Live scoring smoke, using the same scoring inputs as the reporter rerun:

```bash
melee-agent debug search source-model-synthesis \
  --function mnDiagram_DrawCellNumber \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1058_1059_rerun/draw_frontiers_after_post_stack_terminal/draw_allocator_after_post_stack_terminal.json \
  --target build/diagnostics/mndiagram_1058_1059_rerun/draw_target.json \
  --cflags-from src/melee/mn/mndiagram.c \
  --expression-baseline /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1054_1055_rerun/draw_after_promoted_post_stack_source_model/probes/draw-post-product-translate-stack-clean-no-anchor-frame-clean-owner-prune.pcdump.txt \
  --write-probes build/diagnostics/issue_1061_draw_post_stack_loop_callsite/scored-probes \
  --max-per-dimension 8 \
  --score \
  --timeout 120 \
  --json
```

If `draw_target.json` is not available in this checkout, use the target JSON
from the reporter's scoring command or first run the existing Draw
`score-source` workflow to produce it. The smoke check is successful if it
returns either actionable retained probes or a terminal proof for the new
dimension/final family. It should not return the old
`draw-no-modeled-source-actionable-family-after-post-stack-clean-no-anchor-fpr-source-shape-hypothesis`
as the active next family.

Retained-frontier / allocator smoke after scoring:

```bash
melee-agent debug retained-frontiers \
  --function mnDiagram_DrawCellNumber \
  --artifact build/diagnostics/issue_1061_draw_post_stack_loop_callsite/source_model_scored.json \
  --json
```

Then rerun the allocator-ceiling command used by the reporter's
`draw_allocator_after_post_stack_terminal.json` production path and verify:

- current ceiling is the new stage if all new candidates terminalize;
- old post-stack source-shape terminal is retained as prior evidence, not the
  active unsupported family;
- `post_stack_clean_no_anchor_evidence` is still present.

## Implementation Notes

- Keep the family source-local and bounded. Do not introduce helper extraction
  in this issue unless the loop/callsite probes cannot be materialized from the
  retained source.
- Prefer existing patcher helpers in `post_meta_source_family_synthesis.py`.
  Add new string/regex patchers only for source shapes the existing helpers do
  not cover.
- Preserve all existing stage-order guarantees:
  old coupled-expression and helper-boundary evidence must not outrank
  post-stack source-shape evidence; the new loop/callsite layer should outrank
  both.
- Treat target/expression floor improvement as actionable only when the
  structural guard is accepted, consistent with the current post-stack family.
- The final family/model text should explicitly say that this new layer is
  exhausted, so future work does not loop back to declaration packing, row/col
  owner reuse, digit base lifetime, or frame-neutral coalescing.
