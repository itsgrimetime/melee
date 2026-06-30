# Select-Order Protected Summary Follow-Up Design

## Problem

Two follow-up reports show gaps in the protected-complement guard-repair summary:

- `mnDiagram_SortNamesByKOs` emits `targeted_interference_source_transforms`, but the r34 protected target is still reported as `source-attribution-missing-for-r34` even though the campaign already has a `window_order_source_attributions["34"]` entry for `dst_iter`.
- `mnDiagram_DrawCellNumber` has partial FPR force-phys hits in bounded guard-repair candidates, but no `protected_complement_repair` or `protected_hit_composition` is emitted when no seed/repair label pair forms.

## Design

The targeted-interference plan must build source diagnostics over the union of complement hits and lost protected targets. Existing diagnostics only cover the preserving candidate's complement targets, so a complement-hit candidate that loses r34 never gives r34 to the attribution lookup. The fix threads `window_order_source_attributions` and `window_order_probe_diagnostics` into both the protected-complement summary path and reconciliation frontier helper, then builds diagnostics for hit complement targets plus lost protected targets before constructing `node_set_delta`.

The Draw FPR summary needs an evidence-only fallback. If the normal seed/repair grouping produces no protected-complement group, the summary should consider both seed candidates and repair candidates, dedupe by label, select the strongest partial force-phys hit, and emit a blocked or timed-out `protected_hit_composition`. This fallback must not claim a repair was found. It should preserve the existing candidate payload shape, including complement target statuses, frame deltas, spill deltas, and saved FPR deltas.

## Non-Goals

- Do not change final candidate ranking or search breadth.
- Do not treat pcode-first-def or FPR-temp attributions as automatically safe source edits.
- Do not add new transform families.

## Success Criteria

- Sort recomputation materializes r34 `dst_iter` in targeted-interference `node_set_delta` entries and removes `source-attribution-missing-for-r34`.
- Reconciliation frontier metadata carries the same source attribution for lost protected targets.
- Draw recomputation emits `protected_complement_repair.protected_hit_composition` for partial FPR hits, with `register_class: fpr`, complement statuses for unresolved force-phys targets, and retained frame/spill/saved-register evidence.
- Focused select-order tests cover the summary and reconciliation paths that failed in the artifacts.
