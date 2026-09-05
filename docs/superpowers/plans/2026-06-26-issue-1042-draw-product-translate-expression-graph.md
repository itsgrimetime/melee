# Issue 1042 Implementation Plan

> Implement with subagent-driven development. Preserve unrelated work in `/Users/mike/code/melee`.

## Files

- `tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
- `tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
- `tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`
- `tools/melee-agent/src/cli/capabilities.py`
- `tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`
- `tools/melee-agent/tests/test_retained_frontier_triage.py`
- `tools/melee-agent/tests/test_allocator_ceiling.py`

## Steps

- [ ] Add constants/profile entries for `draw-post-all-known-loop-product-translate-expression-graph`.
- [ ] Add stage predicates requiring `mnDiagram_DrawCellNumber`, FPR context, post-all-known exhaustion, and retained product/translate evidence from normalized source spans or score rows.
- [ ] Add bounded candidate specs using one prefix: `draw-post-all-known-product-translate-graph-`.
- [ ] Update generation gating so the new stage is not blocked by the already-exhausted whole-function or post-all-known stages.
- [ ] Update score classification and terminal proof construction so the new stage gets its own no-floor blocker, final family, terminal reason, evidence rows, and next unsupported source spans.
- [ ] Update retained-frontiers normalization/ranking so product-translate actionable and terminal rows outrank stale post-all-known evidence.
- [ ] Update allocator-ceiling next steps/text for product-translate actionable lanes and terminal ceilings.
- [ ] Add capability aliases for the new lane and final family.
- [ ] Add regression tests for generation, legacy/retained source spellings, actionability, terminal replay suppression, retained-frontiers ranking/evidence preservation, and allocator rendering.
- [ ] Run targeted tests and CLI smoke checks; refresh editable `melee-agent` install if tooling changed.

## Review Corrections Incorporated

- The primary generation guard to update is the `_draw_post_source_context_whole_function_exhausted` early return, not only post-all-known exhaustion.
- The new stage needs first-class booleans in actionability, floor, blocker, and terminal construction paths.
- Evidence scanning uses `context.source_spans`; normalization already folds `unmapped_source_spans` into that field.
- Use a single generated candidate prefix and final family everywhere.
- Retained-frontiers ranking is required so issue 1041 terminal evidence cannot keep winning aggregation.

## Test Commands

```bash
pytest -q tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k "post_all_known or product_translate"
pytest -q tools/melee-agent/tests/test_retained_frontier_triage.py -k "post_all_known or product_translate"
pytest -q tools/melee-agent/tests/test_allocator_ceiling.py -k "post_all_known or product_translate"
melee-agent capabilities search "draw loop product translate expression graph"
```
