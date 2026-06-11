# Campaign State: mnDiagram2_HandleInput (802427B4)

## Objective
Match `mnDiagram2_HandleInput` in `src/melee/mn/mndiagram2.c` to 100%.

## Baseline & Current State

| Metric | Value |
|--------|-------|
| Starting baseline | 89.34% (from extract) |
| Verified worktree baseline | 91.59% (pre-session) |
| **Current committed state** | **95.91%** |
| Commits this campaign | d229127e4, 384761931, 54f8e1157, 8de2c73ea |

## Commits

### d229127e4 — RefreshStatRows static inline
Added `static inline void mnDiagram2_RefreshStatRows(void)` in mndiagram2.c.

### 384761931 — x48 fusion in 0x20 arm (+0.27%)
```c
gmMainLib_8015CC34()->xD = (x48 = data2->is_name_mode);
```

### 54f8e1157 — data3 reload in bottom body (+0.26%)
Introduced `Diagram2* data3` reloading from `mnDiagram2_804D6C18->user_data` at the
start of the bottom body. Fixes 3-way callee-save rotation wall: data→r30, result→r31, mn_addr→r29.

### 8de2c73ea — RefreshStatRows new_var alias (+3.79%)
Added `Diagram2* new_var` in RefreshStatRows inline body, with `new_var = data` before
PopulateStatRows call. Uses `new_var->is_name_mode` in PopulateStatRows arg.
Mechanism: adds ig-node that changes interference graph for all ~8 inline expansions,
dropping 58 register-only diffs to 7. Callee-saves now correct in both outer and inline.

## Current Diff Analysis (95.91%)

### Callee-saves: CORRECT
- `stmw r27,60(r1)` on both sides (5 regs r27-r31, matching target)
- gobj→r27, var_r28→r28, mn_addr→r29, data→r30, result→r31

### Instruction count: expected=464, current=472 (8 extra in current)

### Remaining 8 extra instructions — ROOT CAUSE ANALYSIS

Instruction delta breakdown (from diff analysis 2026-06-11):
- **+5 `mr`**: from `new_var = data` copy in each of ~5 RefreshStatRows expansions
- **+3 `lwz`**: mnDiagram2_804D6C18 reloads that expected CSEs via r28
- **+1 `li`**: CP of entering_menu (`li r0,0; stb r0` vs expected `stb r28`)
- **-1 `lbz`**: one fewer lbz than expected
- **-2 `addi`**: expected has 2 `addi r3,r28,0` (CSE'd gobj) that current replaces with lwz

**Root cause of +3 lwz**: At the end of the 0xC00 arm, expected CSEs `mnDiagram2_804D6C18`
into r28 for the second `mnDiagram2_UpdateHeader(mnDiagram2_804D6C18, x48, var_r5)` call.
Expected sequence:
```
lwz r28, sda21          ; data2 base cached in r28
lwz r29, 44(r28)        ; data2 into r29
... JObj calls via r29 ...
addi r3, r28, 0         ; second UpdateHeader reuses r28 (CSE'd)
addi r4, r30, 0         ; x48 reuses r30
bl mnDiagram2_UpdateHeader
```
Our current code puts the data2 base in volatile r3 (not callee-save r28), so it spills.

**Root cause of lwz r3 instead of r28**: The `new_var = data` in the inline creates extra
interference on r28, making the data2 base assignment use volatile r3 instead.

**Paradox**: Removing `new_var` from inline → 92.1% (wrong callee-saves). Keeping it → 95.91%
with 8 extra instructions. The target achieves correct callee-saves WITHOUT `new_var` in inline.
→ The real source has a different structural change that achieves the same callee-save layout
without the extra interference.

### 7 register-only paired differences (remaining body diffs)
- addi ordering (+028): scheduler artifact, unfixable
- CP entering_menu (+04c/+050): `li r0,0; stb r0` vs `stb r28`
- x48 register in 0x20 arm: lbz using different register
- Various inline expansion register mismatches

### Diffs that match (matched region)
- All structural/opcode sequences match (97.9% opcode similarity)
- Function structure, control flow, all call sites

## Walls Banked

### addi ordering — SCHEDULER CEILING
`addi r31,r3,0` vs `addi r29,r4,0` order swap. Not source-fixable.

### entering_menu CP — SEMI-WALL
`var_r28=0` is CP-folded to `li r0,0; stb r0`. The `stb r28` in target means the
developer's source had `mn_804A04F0.entering_menu = var_r28` WITHOUT CP happening.
This implies the target's interference graph didn't fold var_r28.

### new_var inline paradox — THE CORE WALL
- Without `new_var` in inline: 92.1% (58 register mismatches, callee-saves wrong)
- With `new_var` in inline: 95.91% but +8 extra instructions from mr/lwz overhead
- The target has NEITHER the mr copies NOR the wrong callee-saves
- → Target source achieves correct callee-saves via different structural means

## Permuter Candidates (top scores as of 2026-06-11)

All scored against 95.91% base (8de2c73ea committed state):

| Score | Candidate | Key change | Safe? |
|-------|-----------|-----------|-------|
| 4530 | output-4530-1 | u8 new_var in inline + Diagram2 *new_var in HandleInput | Partial semantic hacks |
| 4515-2 | output-4515-2 | volatile return type on inline + move JObjSetFlagsAll | NOT SAFE |
| 4515-1 | output-4515-1 | double data reload in inline + empty if(1) block | Hacks |
| 4480-1 | output-4480-1 | u8 new_var=entity_idx in inline + Diagram2 *new_var in HandleInput | Mixed |
| 4475-1 | output-4475-1 | u8 new_var=entity_idx in inline + data3 alias in fighter arm | Mixed |
| 1535 | output-1535-1 | HSD_GObj *new_var in HandleInput, new_var = mnDiagram2_804D6C18 | Safe but +0.1% only |
| 1310 (remote coder2) | | new_var2=data alias + new_var=global for data3 | Partial safe |

None of the safe candidates eliminate the core 8 extra instructions.

## Permuter Jobs

- **coder2 (active)**: `mnDiagram2_HandleInput-coder2-20260611-112616` (re-submitted at 95.91%)
- **coder3 (active)**: `mnDiagram2_HandleInput-coder3-20260611-112626` (re-submitted at 95.91%)
- **local permuter**: ran, found up to score 4530. Output preserved in `/Users/mike/code/decomp-permuter/nonmatchings/mnDiagram2_HandleInput/`

## Structural Levers Tried This Session

| Lever | Result |
|-------|--------|
| HSD_GObj *new_var in HandleInput + use for 2nd UpdateHeader | +0.1% only, no instr count reduction |
| u8 new_var in inline (for is_name_mode) | 92.1% regression — wrong callee-saves |
| new_var->scroll_offset instead of data->scroll_offset | no change |
| split data decl/assignment in inline | no change |
| data reload before PopulateStatRows | 91.5%, 481 instructions (WORSE) |

## Target ASM Key Reference (0xC00 arm end)

```
/* 80243EE0 */  bl mnDiagram2_PopulateStatRows
/* 80243EE4 */  lbz r0, 0x48(r30)      -- r30 = outer data (post-inline check of is_name_mode)
/* 80243EFC */  lwz r3, mnDiagram2_804D6C18@sda21    -- first UpdateHeader gobj arg
/* 80243F04 */  bl mnDiagram2_UpdateHeader
/* 80243F08 */  lbz r30, 0x48(r30)     -- x48 = data->is_name_mode stored into r30
/* 80243F0C */  lwz r28, sda21         -- data2 base → r28 (CSE target!)
/* 80243F14 */  lwz r29, 0x2c(r28)    -- data2 → r29
...
/* 80243F64 */  addi r3, r28, 0x0     -- second UpdateHeader reuses r28 (CSE!)
/* 80243F68 */  addi r4, r30, 0x0     -- x48 from r30
/* 80243F6C */  bl mnDiagram2_UpdateHeader
```

## Next Steps for Driver 2

1. **Investigate why `new_var` in inline creates correct callee-saves**: Run COLORGRAPH diff
   with and without `new_var` to see what ig-node change matters. The `new_var = data` at
   the PopulateStatRows call site creates extra interference for the data variable that
   shifts some outer function callee-save. Need to identify WHICH outer variable moved.

2. **Find the natural C equivalent**: The developer's source likely doesn't have `new_var`.
   Look at what structural change in HandleInput (NOT the inline) would achieve the same
   callee-save outcome without mr copies. Candidates:
   - Different declaration order (diagnose showed no decl-order win, but that was WITH new_var)
   - Different expression structure in the 0xC00 arm
   - An additional local variable in HandleInput that creates the same interference

3. **Test without new_var + decl-order permutation**: Run diagnose WITHOUT new_var in inline
   (at 92.1% base) to see if any decl-order wins exist there.

4. **CP entering_menu**: Currently +1 instruction. May be linked to the callee-save issue.
   Target uses `stb r28` which means r28 is live there — if our source had var_r28 not
   CP-folded, the live range extends and could change interference graph.

5. **Check remote permuter progress**: coder2/coder3 jobs submitted at 95.91% base.
   May have found higher-score candidates by driver-2 time.

## Structural Insights

- The inline `new_var = data` creates interference that shifts outer callee-saves correctly
  BUT also generates mr copies and prevents r28 CSE of mnDiagram2_804D6C18 in 0xC00 arm
- The 8 extra instructions are causally linked: mr copies + prevented r28 CSE from same change
- Target achieves correct layout through different means (unknown)
- PAD_STACK(40) is diagnostic placeholder — natural C for frame reservation not found yet
