# mnvibration.c — full-session findings

Comprehensive notes from a session working through all unmatched functions in `src/melee/mn/mnvibration.c`. Uses the full new debugger toolkit (`debug pcdump`, `debug analyze`, `debug simulate`) plus existing skills (mismatch-db, opseq, discord-knowledge).

## Final state

| Function | Before | After | Status |
|----------|--------|-------|--------|
| mnVibration_80248644 | 98.4% | **99.8%** | Structural ceiling (PCode-gen constant inlining, see `mwcc-allocator-mechanism-deep-dive.md`) |
| mnVibration_80248444 | 91.6% | **95.1%** | Improved via pos_y reorder; remaining 16 lines blocked on iter-order register cascade |
| fn_802487A8 | 87.4% | 87.4% | Blocked — 11 callee-save vs expected 9 (2 too many simultaneous live virtuals) |
| mnVibration_80248ED4 | 81.6% | 81.6% | Blocked — expected loads &mnVibration_803EECE0 early; need to identify what it's used for |
| fn_80247510 | 73.8% | 73.8% | Too large/complex; needs section-by-section analysis |

## mnVibration_80248444 — 91.6% → 95.1%

**Fix:** Reorder `text->pos_y` assignment **before** `text->pos_x`. The conversion of `(f32) arg2` happens during pos_y's computation; reordering puts the FP conversion ahead of the consecutive pos stores, matching the expected schedule.

```c
// Before
text->pos_x = sp20.x;
text->pos_y = -(spacing * (f32) arg2 + sp20.y);
text->pos_z = sp20.z;

// After (matches expected)
text->pos_y = -(spacing * (f32) arg2 + sp20.y);
text->pos_x = sp20.x;
text->pos_z = sp20.z;
```

**Remaining diff (16 lines):**

- r26/r27 swap for `name_flag` (expected r27) vs `text`/`new_jobj` (expected r26)
- @471, @520, @548 anonymous SDA2 relocs (should be mnVibration_804DC018, _804DC030, _804DC034)

**What I tried for the cascade:**
- Decl reorder: same 95.1%
- PAD_STACK adjustments: regressed
- Named extern declarations + `mnVibration_804DC030/034` references: regressed to 88.3% (extra FP saves)

**Root cause** (per debug analyze): r36 (name_flag) interferes with r35 (new_jobj) and r37 (text). Both other virtuals take r27 in iteration order before r36's coloring, forcing r36 to r26. Chaitin's simplification iter order isn't directly influenceable from source.

## fn_802487A8 — stuck at 87.4%

**Root cause:** 11 callee-save GPRs (`stmw r21`) vs expected 9 (`stmw r23`). Function has THREE separate "walk through HSD_JObjGetChild + HSD_JObjGetNext chain" patterns (`var_r3_2`, `var_r3_3`, `var_r26`), each kept as a separate IGNode despite their disjoint live ranges.

**What I tried:**
- Replaced manually-expanded HSD_JObjGetChild/Next with proper inline calls → regressed to 84.4% (probably due to interaction with `(HSD_JObj*)` casts in the inline expansion)
- Past attempt note: unifying var_r26/var_r3_3 worsens

**Possible path:** The complex `(((s8) var_r3 != 0) && B) || (((s8) var_r3 == 0) && !B)` boolean reduces to `var_r3 != 0 == B != 0`. A different boolean structure might affect coloring, but it'd risk other ASM regressions.

## mnVibration_80248ED4 — stuck at 81.6%

**Root cause:** Expected ASM loads `&mnVibration_803EECE0` at the top of the function (saved to r28), but our source has no reference to it. The variable is presumably used later in the function (which we can't pinpoint from the diff alone). Symbol is 12 bytes in `.data`, typed as `MnVibrationFloatData` (only fields x18, x1C currently known).

**What I tried:**
- Adding `MnVibrationFloatData* floats = &mnVibration_803EECE0;` alone: MWCC eliminates as unused
- Loop conversion of `data->x6[i]` initialization: regressed to 80.7%

**Possible path:** Find what fields of `mnVibration_803EECE0` are actually used — likely related to the title text positioning floats (-9.5f, 9.1f, 17.0f, 364.68332f, 38.38772f) or HSD_PadCopyStatus indexing offsets. Requires more knowledge of the struct's full layout.

## fn_80247510 — stuck at 73.8%

**Root cause:** Massive function (2932 bytes, 891 ASM lines). 261 reloc diffs + 35 register-only diffs. 12 callee-save GPRs (`stmw r26`) vs expected 11 (`stmw r27`). Complex input/menu/rumble logic with multiple manually-expanded inlines.

**What I tried:** Just opened it — full investigation would take a dedicated session.

**Possible path:** Section-by-section. Likely many small wins available (inline cleanup, single-load pattern for `mnVibration_804D6C28->user_data` instead of repeated re-loads, etc.).

## Tools used effectively

- **`debug pcdump` + `debug analyze`**: confirmed virtual register live ranges, interferences, and forced phys assignments. Was definitive for diagnosing the mnVibration_80248644 ceiling.
- **`debug simulate`**: shows what the allocator *would* pick under simpler models; the gap from actual is the signal.
- **`/decomp` skill**: standard checkdiff workflow.
- **`mismatch-db`**: not directly applicable to these cases.
- **`/discord-knowledge`**: didn't dig into for this session.
- **`/opseq`**: not used.

## Patterns observed

1. **Reorder assignments to match FP conversion scheduling.** Multiple stores in a row + FP conversion: put the FP-computing store first so the conversion sequence emits ahead of the simple stores. (mnVibration_80248444 win)
2. **Manually-expanded inlines** that look like m2c output (`if (X == NULL) { Y = NULL; } else { Y = X->child; }`) sometimes match best as-is; replacing with proper inline calls can regress due to subtle type-cast differences. Test before assuming cleanup helps.
3. **PCode-gen constant inlining** (per mwcc-debug-mnvibration-followup-2.md) is a structural ceiling for functions like mnVibration_80248644 where a constant-initialized variable is reassigned later. No source pattern defeats it without other regressions.
4. **Anonymous SDA2 relocations (@N)** for FP constants can sometimes be fixed via named externs, but only when the named-extern reference doesn't introduce extra FP load instructions. For 0.0f references via mnVibration_804DC030, the named-extern approach forced an extra f30 save (regressed mnVibration_80248444 from 95.1 to 88.3%).

## Recommended next steps for this file

1. **mnVibration_80248444** — investigate what makes the original devs' decl/use order yield name_flag → r27. Likely needs the live-range-splitter hook (Tier 3.5+).
2. **mnVibration_80248ED4** — discover what fields of `mnVibration_803EECE0` are accessed. Maybe via Ghidra inspection of the original. Once known, the function's match should jump significantly.
3. **fn_802487A8** — restructure the boolean condition or the child-walk patterns. The 2-extra-callee-save problem is structural; might require Ghidra to see how the original lays things out.
4. **fn_80247510** — Section-by-section pass. Likely many small wins. Highest value-per-time if approached systematically.

All committed to `wip/mn-heartbeat`. Attempt log entries recorded for each function.
