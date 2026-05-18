# mnVibration_80248644 — iteration findings using new toolkit

Using the new `debug pcdump`, `debug analyze`, `debug diff`, `debug simulate`, and `debug pcdump --force-phys` toolkit to systematically explore the 2-line register diff for scroll_offset (r36).

## Verified target reachability

`melee-agent debug pcdump src/melee/mn/mnvibration.c --output /tmp/forced.txt --force-phys "36:31"` confirms: forcing virtual r36 (scroll_offset) to physical r31 produces target ASM byte-for-byte in the j-loop:
- `li r31, 0` (cleanup NULL) ✓
- `stw r31, 112(r30)` (NULL store) ✓
- `lbz r31, 10(r28)` (scroll_offset load) ✓
- `add r0, r31, r29` (scroll_offset + j) ✓

So r36 → r31 IS the target. The remaining question is whether any natural C source produces this from MWCC's allocator.

## Baseline coloring analysis

`debug analyze` shows r36's interferer set in the baseline:
```
r36 -> r27 [callee-save]. interferers: r32, r35, r39, r41, r42
       Candidates: {r13..r25, r27, r30, r31}
```

At iter 16's coloring time:
- Pool (dispensed callee-save): {r27, r28, r29, r30, r31}
- Interferers' physicals to exclude: r26 (r32=arg0), r28 (r39=data)
- (r35=j hasn't been colored yet at iter 16; r29 not yet excluded)
- workingMask = {r27, r29, r30, r31}
- Lowest set bit → **r27**

## The structural constraint

For r36 to take r31 via MWCC's "lowest set bit" rule, workingMask must be `{r31}` alone. That requires excluding r27, r29, r30 from workingMask. Each exclusion requires r36 to interfere with the virtual holding that physical:
- r27: r38 (i counter, cleanup)
- r29: r35 (j) — already excluded eventually
- r30: r45 (ptr2 walker, cleanup)

So r36's live range must overlap r38 and r45's live ranges (cleanup loop body).

**The trilemma:** r38, r44, r45, r50 are ALL alive during cleanup loop body. If r36 extends to interfere with any of them, it interferes with the others too. In particular, r50 (NULL → r31). So extending r36 to exclude r27/r30 ALSO excludes r31.

## Iterations attempted (with new toolkit)

| # | Approach | Match | r36 result | Notes |
|---|----------|-------|------------|-------|
| baseline | Current source | 99.8% | r27 (5 interferers) | The 2-line target |
| v1 | Load scroll_offset BEFORE cleanup loop | 7.9% | r26 (13 interferers) | r36's life now spans cleanup, interferes with NULL too. Extra lbz at start. |
| v2 | Inline `data->scroll_offset` (no variable) | 77.8% | removed (no virtual) | Compiler uses temps in caller-save, scroll_offset isn't a callee-save virtual anymore. |
| v3 | `scroll_offset = 0; ... \|= data->scroll_offset` | 92.7% | r25 (more interferers, cascade) | Adds an OR instruction. Whole register map shifted. |
| v4 | Manual HSD_JObjGetChild inline expansion | 99.8% | same as baseline | No effect — inline call produces same ASM. |

## Diff tool's value

`debug diff` showed exactly what changed between attempts. For v1:
```
r36     removed(A) r27, degree=11, nIntfr=14    # Previous r36 removed
r34     changed   nIntfr 0→3                    # New temp appeared
r35     changed   r29→r27                       # j shifted to r27
r32     changed   r26→r25                       # arg0 cascaded down
```

This makes iteration FAST — no need to read full ASM diffs.

## Why MWCC won't naturally pick r31 for r36

From experimental evidence + the algorithm reference:

1. **Constant-inlining at PCode-gen creates a separate virtual** for the cleanup-loop NULL (r50 in our case). r50 lives 6..12, gets dispensed r31 first.
2. **scroll_offset is born in j-loop only** (live 34..42). It doesn't naturally overlap with cleanup virtuals.
3. **Any attempt to extend scroll_offset backward** creates interferences with BOTH cleanup walkers AND NULL constant, displacing r36 to a LOWER reg (worse than baseline).

The only way to get r36 → r31 naturally would require:
- NULL constant to NOT be in r31 (so r36 can take it)
- AND scroll_offset to interfere with i counter and ptr2 walker (to exclude r27/r30)

These are mutually-exclusive: both require touching the cleanup loop.

## What might work (untested speculation)

- **Move NULL constant out of callee-save entirely.** If the cleanup loop emitted `li r0, 0; stw r0, ...` each iteration (like mnDiagram2_ClearStatRows does), r31 wouldn't hold NULL. Then scroll_offset could naturally pick r31. But preventing MWCC's LICM hoist on a single store is hard.

- **Add another NULL store in cleanup** to multiple fields (like mnDiagram2's labels+values+icons). With multiple stores, LICM might not hoist a single constant, and each store would use a fresh `li r0, 0`. But changing semantics breaks the function.

## Decision

Keeping the 99.8% baseline. The remaining gap is well-understood: MWCC's PCode-gen creates two separate IGNodes (NULL constant r50, scroll_offset r36) with disjoint lives, both wanting r31. The trilemma between interfering-with-i-counter and not-interfering-with-NULL constraint blocks any structural fix from C source.

Tier 6 (interactive allocator biasing or IR-level coalescenodes patch) would be needed to break this. Out of scope for now.

This document captures the iteration loop so we don't re-tread the same ground. The new toolkit (especially `debug diff`) made these explorations 5-10x faster than they'd have been with checkdiff alone.
