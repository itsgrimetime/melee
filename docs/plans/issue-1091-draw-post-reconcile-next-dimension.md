# Issue #1091 Plan: Draw Post-Reconcile Next-Dimension Discovery

## Scope

Fix `melee-agent` tooling only. Do not modify Melee C source.

## Root Cause

Fresh Draw post-reconcile artifacts have an authoritative current ceiling with:

- `next_unsupported_source_family = draw-no-modeled-source-actionable-family-after-protected-expression-subhunk-reconcile`
- `terminal_reason = draw-protected-expression-subhunk-reconcile-exhausted/protected-expression-not-retained`

`post-source-context-next-dimension` still emits the stale loop-callsite stage because `post_source_context_discovery._draw_post_source_context_stage()` checks `_has_post_stack_loop_callsite_final_stage()` first. That detector recursively scans every nested value in all artifacts, so historical `draw-post-stack-clean-no-anchor-loop-callsite-source-context` entries inside retained-frontier and allocator metadata outrank the fresh current/meta ceiling.

There is no explicit protected-expression reconcile terminal stage in `post_source_context_discovery.py`, so the fresh post-reconcile handoff cannot win.

## Fix

File: `tools/melee-agent/src/mwcc_debug/post_source_context_discovery.py`

Add constants for the protected-expression reconcile stage:

- `draw-protected-expression-subhunk-reconcile`
- `draw-protected-expression-subhunk-reconcile-exhausted/protected-expression-not-retained`
- `draw-no-modeled-source-actionable-family-after-protected-expression-subhunk-reconcile`
- the existing terminal model text from retained-frontier/source-model synthesis.

Add a detector that inspects only authoritative direct proof paths, not broad recursive history:

- `source_model.context.current_ceiling`
- `source_model.context.current_ceiling.source_family_synthesis`
- `allocator_ceiling.current_ceiling`
- `allocator_ceiling.current_ceiling.source_family_synthesis`
- `allocator_ceiling.retained_frontiers_meta_ceiling.terminal_proof`
- `retained_frontiers.meta_ceiling.terminal_proof`
- `retained_frontiers.functions[*].meta_ceiling.terminal_proof`

Treat a direct proof as protected-reconcile terminal when it has the protected final family, terminal reason, or exhausted protected-reconcile dimension.

Call this detector before the loop-callsite detector in `_draw_post_source_context_stage()`.

Return an `unsupported-source-family` stage with protected-reconcile trigger/exhaustion metadata and direct-proof exhausted dimensions. Avoid collecting global exhausted dimensions from all artifacts for this stage, because stale loop-callsite dimensions are the reported bug.

## Regression Tests

File: `tools/melee-agent/tests/test_post_source_context_discovery.py`

Add fixtures that model a fresh protected-reconcile current ceiling plus stale nested loop-callsite history.

Add tests that verify:

1. Direct protected-reconcile current ceiling beats stale nested loop-callsite terminal history.
2. Output preserves retained target/expression evidence and does not emit loop-callsite as `trigger_dimension` or `exhausted_source_dimension`.
3. `triage_retained_frontiers()` accepts the new discovery output and its meta-ceiling proof carries the protected-reconcile final family.
4. `classify_allocator_ceiling()` carries the protected-reconcile family in `current_ceiling` and `post_source_context_next_dimension`.

## Smoke Checks

Run focused tests:

```bash
PYTHONPATH=tools/melee-agent python -m pytest -q \
  tools/melee-agent/tests/test_post_source_context_discovery.py \
  -k "protected_reconcile or loop_callsite or post_whole" --tb=short
```

Run the real artifact smoke from the reporter worktree:

```bash
cd /Users/mike/.codex/worktrees/eeff/melee
PYTHONPATH=/Users/mike/code/melee/tools/melee-agent python -m src.cli debug search post-source-context-next-dimension \
  --function mnDiagram_DrawCellNumber \
  --source-model-json build/diagnostics/mndiagram_1088_1089_rerun/draw_post_reconcile/source_model/source_model_scored.json \
  --retained-frontiers-json build/diagnostics/mndiagram_1088_1089_rerun/draw_post_reconcile/source_model/triage/retained_frontiers.json \
  --allocator-ceiling-json build/diagnostics/mndiagram_1088_1089_rerun/draw_post_reconcile/source_model/triage/allocator_ceiling.json \
  --continuation-json build/diagnostics/mndiagram_1088_1089_rerun/draw_post_reconcile/source_model/triage/source_family_continuation.json \
  --source-file src/melee/mn/mndiagram.c \
  --json
```

Expected: exit code `3`, `status = unsupported-source-family`, `trigger_family = draw-no-modeled-source-actionable-family-after-protected-expression-subhunk-reconcile`, and no stale `draw-post-stack-clean-no-anchor-loop-callsite-source-context` trigger/exhaustion.

## Risks

The detector must stay direct-proof based. A recursive search for the protected family would create the same stale-stage bug in reverse after future stages. The stage should preserve retained score evidence but avoid importing stale global exhausted dimensions into the proof.
