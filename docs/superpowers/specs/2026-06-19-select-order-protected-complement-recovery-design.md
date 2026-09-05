# Select-Order Protected Complement Recovery Design

## Problem

Two current select-order repair reports have the same shape:

- `mnDiagram_SortNamesByKOs` has a protected hit for IG34->r27 and separate complement-hit candidates for IG44->r25. The guard repair summary records both sides, but the next repair frontier keeps following the protected side instead of backtracking from the IG44-hit source and trying to restore IG34.
- `mnDiagram_DrawCellNumber` has a four-hit FPR seed and misses IG38/IG46. The summary records the protected/complement ceiling, but the complement targets do not carry enough source-attribution detail to tell whether the next step is a source transform or a terminal blocker.

## Design

Guard repair should treat a complement-hit/protected-loss candidate as a recovery seed. When a candidate hits one or more complement force-phys targets but loses protected force-phys hits, the next frontier protects the candidate's achieved complement hits and sets the lost protected registers as its new complement targets. This lets depth-2 repair compose from the complement-hit source instead of only perturbing the original protected-hit source.

The recovery entry is additive to the normal width-selected frontier. The normal ranking remains unchanged, but at least one complement-hit/protected-loss candidate per round is carried forward with `reconciliation_seed` metadata. This preserves existing behavior for simple guard repair while giving bidirectional searches a path to recombine one-sided wins.

Protected complement summaries should also include source diagnostics for the current complement targets. The diagnostics are derived from window-order source attributions and source-probe lead diagnostics when present. For each complement target, the summary reports the attribution, whether it is source-actionable, the terminal blocker when no source probe can be materialized, and a small source excerpt when a source line is available.

## Non-Goals

- Do not invent new transform-corpus families in this fix.
- Do not change the select-order candidate ranking for final output.
- Do not make unsupported first-def FPR temporaries movable. They should be explained as terminal until a concrete source transform exists.

## Success Criteria

- A guard-repair campaign with width 1 still expands a complement-hit/protected-loss candidate at depth 2.
- The guard-repair ledger records the reconciliation seed, including achieved protected hits and lost protected targets.
- `protected_complement_repair` contains `complement_source_diagnostics` for complement targets with source attribution or explicit `source-attribution-missing` blockers.
- Regression tests cover the GPR recovery path and the FPR complement source-diagnostic path.
