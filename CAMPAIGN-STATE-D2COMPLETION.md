# Campaign State: mnDiagram2 TU-COMPLETION (the rank/stat trio)

Worktree: `/Users/mike/code/melee/.claude/worktrees/mndiagram-802427B4-investigation`
Branch: `claude/mndiagram-802427B4-investigation`
Source: `src/melee/mn/mndiagram2.c`
TU status: 14/21 matched. Driver 1 (this doc). Started 2026-06-11.

## Subjects (this iteration: TRIPLE OPENING MAP, no builds)

| Function | fuzzy% | size | classification |
|---|---|---|---|
| mnDiagram2_CreateStatRow            | 80.11 | 1496 | inline-boundary-toolchain-artifact + 121 reloc lines |
| mnDiagram2_GetRankedFighter         | 79.94 | 616  | indexed-struct-pointer-materialization |
| mnDiagram2_GetAggregatedFighterRank | 81.91 | 584  | control-flow-source-shape (switch) + indexed-ptr |

Siblings / context (DO NOT TOUCH the matched ones):
- mnDiagram2_GetRankedName 97.87 (536B) — **THE SORT EXEMPLAR**, matched-class, same `indexed-struct-pointer-materialization` class but spelled with whole-struct copy.
- mnDiagram2_GetStatValue 100% (876B) — matched callee, CreateStatRow calls it 5×. Correct signature: `int mnDiagram2_GetStatValue(int is_name_mode, u8 stat_type, u8 entity_idx)`.
- mnDiagram2_PopulateStatRows 100% — caller of CreateStatRow.
- mnDiagram2_Create 93.75, mnDiagram2_UpdateHeader 94.18 (banked levers) — out of scope this iter.
- mnDiagram2_HandleInput 97.46 — WALLED/parked, PROTECTED, do not touch.

Ground truth = build/GALE01/report.json fuzzy_match_percent (verified this driver).
.o is current (built 2026-06-08; report% matches). All maps below are
`checkdiff --no-build --normalize-reloc --format compact` reads (reloc-stripped).

---

## HEADLINE 1 — the three maps (reloc-stripped, precise)

### GetRankedFighter (79.94) — classification: indexed-struct-pointer-materialization
- Anchors: expected 159 lines / current 154 (Δ = current is 5 SHORTER → we're MISSING instructions, i.e. our shift is over-optimized into a pointer walk).
- 27 opcode-aligned paired instructions differ ONLY by register after normalization (volatile r3–r12).
- diagnostic PAD_STACK(8) present (frame gap, not the lever).
- Tool hint (verbatim): "expected keeps the array base plus byte/index offset for 1 indexed load/store, while current materializes an element pointer shape **4 element pointers** with add and then accesses fields through that pointer ... split the first field into a scalar local and keep later accesses as direct array.base+offset; avoid a live per-element pointer across calls/loops."
- First diffs: `+088 addi r24,r3,1` vs `addi r24,r9,1`; `+08c lwz r9,8(r31)` vs `lwz r10,8(r31)`; `+0a4 addi r8,r1,32` vs `addi r12,r1,32` — register-cascade rooted in the pointer-shape divergence.

### GetAggregatedFighterRank (81.91) — classification: control-flow-source-shape
- Anchors: expected 155 / current 141 (Δ = current 14 SHORTER).
- Reasons: "branch shape differs before downstream operand/stack/reloc noise"; "call shape differs; check prototypes/return types/inline boundaries"; 6 data/symbol reloc lines; 16 register-only paired; 1 stack-slot.
- Allocator hint: "callee-save swap r27<->r28; try loop-counter reuse, nested decl order, tree-index vs cursor-increment, discard/self-assignment liveness nudges."
- First diffs: `+010 addi r27,r1,40` vs `r28,r1,40`; `+014 addi r23,r3,0` vs `r24,r3,0`; `+018 addi r31,r4,0` vs `r30,r4,0`; `+01c addi r24,r5,0` vs `r25,r5,0` — a coherent callee-save renumber (one slot off) at the prologue arg-spill, then propagates.
- The "branch shape differs" + "call shape differs" almost certainly = the `switch ((s32) type)` dispatch (cases 0x15/0x16/0x17 + default goto) and/or the three callee call-shapes (`mnDiagram_GetRankedFighterForName(0/1,i,funcTable)` and `mnDiagram_GetLeastPlayedFighter((u8)i)`).

### CreateStatRow (80.11) — classification: inline-boundary-toolchain-artifact
- Anchors: expected 443 / current 464 (Δ = current 21 LONGER → we have EXTRA instructions; we are NOT inlining something the original inlined, OR we inline something it called out).
- Reasons: "branch shape differs"; "call shape differs; check prototypes/return types/inline boundaries"; **121 differing paired lines reference data/symbol relocations**; 8 register-only; 4 stack-slot.
- Inline-boundary hint (verbatim): "reference calls <...34 call sites...> but current omits that call and is larger; likely wibo/local compiler inlined locally across an inline boundary." → THE EXPECTED MAKES ~34 CALLS THAT OURS DOESN'T (ours inlined them). The 34 call offsets are listed in the dump (+0x4c, +0x6c, +0x84, +0xd0, ... +0x5b8).
- **This is a DIFFERENT domain from the sort trio.** The dominant residual is 121 reloc-line differences + an inline-boundary mismatch — NOT the sort idiom. Likely culprits:
  - The 5× `mnDiagram2_GetStatValue(...)` calls (matched fn) — are we re-inlining or duplicating? GetStatValue is a separate 100% fn, so the EXPECTED keeps it as a `bl`. Check we aren't accidentally inlining via macro.
  - The big `data->x10` base + offset addressing (`mnDiagram2_803EEAD0` indexed via `base + (stat_type<<1 & 0x1FE)` table). The 121 reloc lines = the float-pool / string-pool symbol references (`mnDiagram2_804DBFD0/D4/D8/DC/E0/E4/CC`, `mnDiagram2_804D4FBC/FD0`). A reloc-shape mismatch this large smells like the **data-linking recipe** (model the data blob as a file-local struct + named fields) rather than register work.

---

## HEADLINE 2 — shared-idiom analysis + TRIO worklist

### The shared inline/idiom (THE key finding)

GetRankedFighter, GetRankedName, GetAggregatedFighterRank all operate on
`mnDiagram2_SortEntry entries[N]` (a union; see src lines 50–65):
```c
typedef union {
    struct { u8 name; char pad1[7]; s32 x8; s32 xC; };  // name@0, x8@8, xC@0xC
    struct { f64 d0; f64 d8; };                          // d0@0, d8@8
    struct { char pad2[8]; u64 value; };                 // value@8
} mnDiagram2_SortEntry;  // 16 bytes
```
All three: populate `entries[]` (name + value), then SORT, then read `entries[idx]`.

**The decisive cross-function fact:** GetRankedName (97.87%, MATCHED-CLASS) and
GetRankedFighter (79.94%, STUCK) carry the **identical classification**
(`indexed-struct-pointer-materialization`) and the **same selection-sort algorithm**,
but spell the insertion-shift DIFFERENTLY:

- GetRankedName (works, ~98%): **whole-struct copy**
  ```c
  ptr = &entries[maxIdx];
  temp = *ptr;                 // SortEntry temp;  (struct copy)
  j = maxIdx - i;
  while (j > 0) { *ptr = *(ptr - 1); ptr--; j--; }
  *base = temp;
  ```
- GetRankedFighter (stuck, 80%): **field-by-field d0/d8 copy**
  ```c
  ptr = &entries[maxIdx];
  j = maxIdx - i;
  temp0 = ptr->d0; temp8 = ptr->d8;     // two f64 temps
  while (j > 0) { ptr->d0 = (ptr-1)->d0; ptr->d8 = (ptr-1)->d8; ptr--; j--; }
  base->d0 = temp0; base->d8 = temp8;
  ```

GetAggregatedFighterRank uses the SAME field-by-field d0/d8 idiom in its bubble-sort swap (src 1370–1375):
```c
temp0 = base->d0; temp8 = base->d8;
base->d0 = curr->d0; base->d8 = curr->d8;
curr->d0 = temp0;   curr->d8 = temp8;
```

**Hypothesis (HEADLINE):** the original wrote the sort element move as a
**whole-struct assignment** (`temp = *ptr; *ptr = *(ptr-1)` — the GetRankedName form),
which MWCC lowers via its struct-copy path. The d0/d8 field-by-field spelling in
GetRankedFighter/GetAggregatedFighterRank produces the over-materialized per-element
pointer + extra register pressure (4 element pointers vs the expected base+offset).
Converting both stuck functions to the GetRankedName whole-struct-copy spelling is
the single edit that **may pay all three sort sites** (the find-walk precedent: one
inline reconstruction fixes a family).

Caveat (must verify by build, NOT yet done): GetRankedFighter's `value`-guard
comparisons (`baseVal == (u64)neg1`, `curr->value != (u64)neg1`) and the
return-side `entries[rank]` access are extra vs GetRankedName; the whole-struct
copy must not perturb those. But the SHIFT body is the isolated, transferable unit.

### Secondary shared idiom: population-loop pointer walk
All three populate with `ptr->name = ...; ptr->xC = ...; ptr++;` (a live cursor).
GetRankedName (matched-class) ALSO does this and is fine, so the population walk is
probably NOT the lever — the indexed-pointer hint ("4 element pointers") points at
the SHIFT/return region, not population. Lower priority.

### Secondary shared idiom: the index functions + GetStatValue
`mnDiagram_GetFighterByIndex`/`GetNameByIndex` and `mnDiagram2_GetStatValue` are
shared callees (all matched). Call-shape for these should already be right since
GetRankedName matches; if GetRankedFighter shows a call-shape diff it's local.

### TRIO WORKLIST (ranked; which function first, what transfers)

1. **GetRankedFighter FIRST (79.94, smallest at 616B, cleanest signature).**
   Lever: rewrite the insertion-shift as the GetRankedName whole-struct form
   (`SortEntry temp = *ptr; *ptr = *(ptr-1); *base = temp;`). This is the
   exemplar-proven spelling. Expect it to close most of the 27 register-only diffs
   because the pointer-shape collapses to base+offset. EST: the highest-yield single edit.
   - If the value-guard logic blocks a clean struct-copy, keep the guards but still
     convert only the d0/d8 move pair to `*ptr = *(ptr-1)` / `*base = temp`.

2. **GetAggregatedFighterRank SECOND (81.91, 584B).** Two transfers:
   (a) the bubble-sort swap d0/d8 → whole-struct swap via a `SortEntry temp` (same idiom as #1, TRANSFERS);
   (b) the `control-flow/call-shape` residual is its OWN problem — the `switch((s32)type)`
   dispatch + 3 callee call-shapes. Investigate after (a): is the original a switch,
   an if-ladder, or a function-pointer table dispatch? The `funcTable` local
   (`(void*)mnDiagram_GetNamePlayTimeByFighter`) passed to GetRankedFighterForName
   hints the original may not branch on type the way m2c reconstructed it.
   The r27<->r28 callee-save swap at prologue is a 1-slot renumber — likely falls
   out once the struct-copy + branch shape land (structure-first).

3. **CreateStatRow LAST (80.11, 1496B — biggest, DIFFERENT domain).**
   NOT a sort function; no shared sort idiom. Its residual = 121 reloc-line diffs +
   inline-boundary (expected makes ~34 calls ours omits/inlines). This is a
   DATA-LINKING + inline-boundary problem, not register work. Approach:
   (a) confirm the 5× `mnDiagram2_GetStatValue` stay as `bl` (separate 100% fn) — are
       we accidentally inlining it?
   (b) the 121 relocs = the `mnDiagram2_803EEAD0` table base + the float/string pool
       (`804DBFxx`, `804D4Fxx`). Apply the data-linking recipe (model blob as
       file-local struct, named fields) — DIAGRAM2 §literal law / band arithmetic are
       PRICED walls; the reloc SHAPE is the lever, not the band.
   (c) the inline-boundary: identify which of the 34 listed call sites the expected
       keeps as `bl` vs ours inlines (likely `HSD_SisLib_*`, `lb_8000B1CC`, or the
       `var_r3`/`var_r0` ladder helpers). This is the inline-boundary-evidence-shape
       work from the methodology doc (per-arm truncation = inline-return).
   CreateStatRow is the LEAST likely to share a lever with the sort pair — treat as
   independent. Do it after banking the sort-pair wins.

---

## What transfers (one-line)
- GetRankedName whole-struct-copy SHIFT spelling → GetRankedFighter shift + GetAggregatedFighterRank swap. ONE idiom, TWO functions. (HEADLINE.)
- CreateStatRow shares NOTHING with the sort trio; its lever is data-linking + inline-boundary.

## PENDING-REVIEW (community-guideline risks)
- None retained this iteration (no edits made; analysis only). Any future PAD_STACK(8)/(16)
  retention or volatile/data-symbol edit goes here for the user to fix up pre-PR.
- NOTE for whoever builds: GetRankedFighter & GetAggregatedFighterRank carry diagnostic
  PAD_STACK(8); CreateStatRow carries PAD_STACK(16). Per project rule these are NOT
  shippable — replace with natural frame reservation (real local array/struct) once near-match.

## Budget used this iteration
4 dump runs (the 3 targets + GetRankedName exemplar), all `--no-build` reads. No builds. No permuter.

## Next-iteration entry point
Build GetRankedFighter with the whole-struct-copy shift (worklist #1). Gate: fuzzy% up
from 79.94, opcode similarity holds, line Δ shrinks toward 0 (currently -5). If it lands,
transfer to GetAggregatedFighterRank swap (#2a) the same iteration.

---

# ITERATION 2 (driver 1, 2026-06-11): the idiom-transfer ladder — BOTH LANDED

## Question: does the whole-struct-copy idiom land the sort pair? ANSWER: YES (both committed)

## Build ledger (5/5 used)

| # | Function | Edit | Result | Verdict |
|---|---|---|---|---|
| 1 | GetRankedFighter | shift → exemplar verbatim (`temp=*ptr; *ptr=*(ptr-1); *base=temp;`, union temp decl after entries) | 79.94 → **94.16** | LANDED. Line-Δ −5 closed; classification's structural reason gone. |
| 2 | GetRankedFighter | remove PAD_STACK(8) | 94.16 (flag cleared, frame still +8) | Kept (shippable form). |
| 3 | GetRankedFighter | delete `u64 baseVal`, re-read `base->value` at compare | **91.18 REGRESS** | REVERTED-BY-BUILD-4. Mechanism: `base` is in the outer loop's killed set (base++) → LICM hoist FAILED, halves loaded per-inner-iteration. The named u64 HAD hoisted to preheader (+08c/+094) but costs an 8B frame slot expected lacks. |
| 4 | GetRankedFighter | `entries[i].value == (u64) neg1` (non-killed array form) + sort `do/while` → `for (i...)` | **94.58 COMMIT cc052016f** | LANDED. Register-only 27→3 (i→r3 volatile permutation SNAPPED); IRO address-folds entries[i] to the walking base (loads via 8(r31)/12(r31)) with NO frame home. |
| 5 | GetAggregatedFighterRank | bubble swap → struct swap (`temp=*base; *base=*curr; *curr=temp;`), `u64 a/b` locals → expression compare, sort do/while → for | 81.91 → **85.19 COMMIT e2d172d4d** | TRANSFER LANDED. Line-Δ −14 → −10. |

## Mechanism laws extracted (new, this TU)

1. **u64-local frame law:** a named `u64` local gets an 8-byte frame home in MWCC even
   when never spilled; the expected frames here don't have one. To get a loop-invariant
   u64 load hoisted to the preheader WITHOUT the frame slot, spell it as an EXPRESSION
   through a non-killed object (`entries[i].value`, i invariant) — NOT through a walking
   pointer (`base->value`, killed by `base++`, hoist fails = build-3 regression) and NOT
   through a named u64 (slot appears = builds 1-2 frame residual).
2. **for-vs-do sort head:** m2c's `i = 0; do {...} while (i < 25)` places `li i,0` BEFORE
   the loop-invariant `&entries` temp materialization; the target order (addi-then-li)
   falls out of `for (i = 0; i < 25; i++)`. Snapped the whole 27-line volatile cascade
   (i colored r3 = first volatile pop).
3. **Whole-struct copy = the sort-element move idiom** (confirmed on 2nd + 3rd function):
   `SortEntry temp; temp=*p; *p=*(p-1); *base=temp` (shift) and `temp=*base; *base=*curr;
   *curr=temp` (swap). The d0/d8 field-pair spelling is m2c artifact, never original.

## GetRankedFighter residual @ 94.58 (next-iteration entry)

- exp 159 / cur 160 (+1: an unfolded `addi r6,r4,0` copy at +084 — ours mints TWO
  `&entries` temps at the sort preheader, expected ONE; find which source object holds
  the second &entries web live across the sort loop — suspect `ptr` or the hoisted
  entries[i] address temp; copy-init fold law applies).
- 4 stack lines: frame 480 vs 472 (+8). HYBRID-FORM HYPOTHESIS (untested, build it next):
  the expected's `stfd f1,16(r1); stfd f0,24(r1)` are SPILL slots of two f64 temps, not a
  named 16B union temp — i.e. original = `f64 temp0, temp8` decls (no union temp local)
  WITH the struct-copy loop body:
  `temp0 = ptr->d0; temp8 = ptr->d8; while (j>0) { *ptr = *(ptr-1); ptr--; j--; } base->d0 = temp0; base->d8 = temp8;`
  …or temp halves spelled f64 with struct-copy only inside the loop. Evidence: ours has a
  16B temp@24 + 8B hole@16; expected has 16B total at 16..31 written by stfd f1/f0; ALSO
  ours' stfd order f1@24/f0@32 vs expected f1@16/f0@24 (one register-only stfd line).
  The exemplar GetRankedName (97.87) shows the SAME 2 stack lines — if the hybrid form
  fixes GetRankedFighter, apply to GetRankedName too (it is NOT protected; open set).
- 3 register-only lines (+0c4/+0ec/+0fc xor/subfe operand regs — inner-loop compare temps;
  likely re-roll with the +1-line fix).
- The `subf.`+`mr r3,r0` site (j>0 guard, record-form vs expected's cmpw CR reuse from the
  maxIdx!=i compare): SHARED with the exemplar (its 141-vs-140 +1 line). Candidate spelling:
  explicit `if (j > 0)` entry guard + inner do-while, or guard propagation forms. Applies
  to BOTH GetRankedFighter and GetRankedName if found.

## GetAggregatedFighterRank residual @ 85.19 (next-iteration entry)

- exp 155 / cur 145 (−10): the switch dispatch region. classification
  control-flow-source-shape: "branch shape differs", "call shape differs". The
  `switch ((s32) type)` (cases 0x15/0x16/0x17, default goto next) + the 3 callee shapes
  (`mnDiagram_GetRankedFighterForName(0/1, i, funcTable)`, `GetLeastPlayedFighter((u8) i)`)
  need the target's branch topology read FIRST (orchestrator pointer: 80245BA4 S5
  branch-join precedent). −10 lines on a 584B fn = a missing/duplicated arm or merged tail.
- Whole-vector callee-save permutation persists at prologue (+010..+01c): expected
  {base→r27, out→r23, type→r31, idx→r24} vs ours {r28, r24, r30, r25}; one-slot shift =
  one web missing/extra; likely re-rolls after the switch-shape fix (structure first).
- 6 reloc lines + 3 stack lines: re-read after switch fix.

## PENDING-REVIEW

- Nothing diagnostic shipped: GetRankedFighter's PAD_STACK(8) was REMOVED (natural form
  now); GetAggregatedFighterRank never had one; both commits are natural C only.
- Style note for pre-PR pass: `// Bubble sort` / `// Selection sort with insertion shift`
  comments and the `zero`/`neg1` local names are inherited m2c-era artifacts; harmless.

## Commit stack (this iteration)
- cc052016f feat(mn): mnDiagram2_GetRankedFighter 79.94 -> 94.58
- e2d172d4d feat(mn): mnDiagram2_GetAggregatedFighterRank 81.91 -> 85.19
(protected-set pre-commit checks passed 11/11 on both)

## TU state after iteration 2
14/21 matched; open set now: CreateStatRow 80.11 (untouched, data-linking +
inline-boundary domain), GetRankedFighter 94.58, GetAggregatedFighterRank 85.19,
Create 93.75, GetRankedName 97.87, UpdateHeader 94.18 (banked levers),
HandleInput 97.46 (WALLED/parked — do not touch).

---

# ITERATION 3 (driver 1, 2026-06-11): the three priced levers — 1 landed big, 2 refuted-with-laws

## Build ledger (5/5 used)

| # | Function | Edit | Result | Verdict |
|---|---|---|---|---|
| 1 | GetRankedFighter | hybrid (f64 temp0/temp8) + `if (maxIdx > i) do {...} while (--j != 0)` | **65.50 CRASH** (116/159 lines) | The guard+do-while form DEFEATED THE 8x UNROLLER (function lost the unrolled copy block). |
| 2 | GetRankedFighter | same guard, canonical body (`j--;` stmt + `while (j > 0)` tail) | **65.50 identical** | Decrement form irrelevant — the EXPLICIT IF-GUARD is the unroll-killer. NEW LAW below. |
| 3 | GetRankedFighter | hybrid temps + original `while (j > 0)` (isolate hybrid) | **89.79** (155/159) | HYBRID REFUTED: f64 pair allocates differently (−4 lines, no spill shape). Expected's stfd f1,16/f0,24 = the UNION temp's own stores at offset 16. Reverted to committed 94.58 via git. |
| 4 | GetAggregatedFighterRank | switch round: drop default/goto, drop funcTable local (direct symbol), int type_val web, for-form | **87.64** (+2.45) | Dispatch landed STRUCTURALLY COMPLETE: per-arm `mr rCS,r3` appeared, default→join branch targets identical, single funcTable addi. Register-only exploded 18→51 (web re-roll, raw type→r21 deep). |
| 5 | GetAggregatedFighterRank | tail: per-branch DUPLICATED whole-struct copies via indexed entries[idx] (drop curr pointer region) | **93.56 COMMIT 05a5aaf91** (155/155!) | The −9 was the m2c-factored tail + the trio idiom a 3rd time + indexed-not-pointer. classification → instruction-sequence. |

## New laws minted (iteration 3)

1. **Guard-defeats-unroller law:** MWCC's 8x copy-loop unroll (srwi./mtctr/andi. split)
   fires on the self-canonicalized `while (cnt > 0) {...; cnt--;}` form ONLY. Wrapping the
   loop in an explicit `if (a > b)` entry guard with a source-level do-while inside kills
   the unroll entirely (−43 lines), regardless of decrement spelling. The j-guard `subf.`+`mr`
   +1-line residual is therefore NOT reachable via the explicit-guard spelling class.
   (Both attempts metered 65.50; reverted.)
2. **Hybrid-temp refutation:** the expected `stfd f1,16(r1); stfd f0,24(r1)` in the shift
   are the union temp's OWN stores (16B object at +16), not f64 spill slots. f64 temp pair
   = −4 lines (different allocation). Union `SortEntry temp` is the right form; the +8B
   hole below it (GetRankedFighter frame 480 vs 472, same-reg stmw) is STILL unexplained —
   open. (NOT the same mechanism as AggRank's +8, which is one extra callee-save SAVE.)
3. **Default-arm fall-through law (switch codegen):** m2c's `default: goto next` ≠ original.
   The original switch had NO default; control falls THROUGH to the join test with STALE
   res — making res loop-carried → callee-save home → the per-arm `mr r25,r3` copies.
   Removing the default arm reproduces the whole join pattern at zero cost.
4. **Trio idiom, third confirmation:** the whole-struct copy (`*(SortEntry*)out =
   entries[idx]`) + per-branch tail duplication + indexed (base+offset re-derived per site,
   `.value` folds base+8 into the addi) vs materialized element pointer. The
   indexed-struct-pointer-materialization classification's literal advice applied verbatim.

## j-guard two-function verdict (lever 2)

NOT LANDED — and closed as a spelling class: the only direct spelling of the CR-reuse
(`if (maxIdx > i)` explicit guard) breaks unrolling (law 1). The `subf r4` + ble-from-cmpw
form requires IRO to propagate `j > 0` → `maxIdx > i` on the WHILE-form guard, which our
verbatim spelling provably doesn't trigger (exemplar carries the same +1). Residual stays
+1 line on BOTH GetRankedFighter (160/159) and GetRankedName (141/140). Next idea-space
(untried): make j's def NOT immediately precede the guard (hoist `j = maxIdx - i` ABOVE
the temp loads), or eliminate j as a named local (`for (j = maxIdx - i; ...)` was iter-2's
form — already produces the +1). GetRankedName untouched this iteration (no verified win
to transfer; its 97.87 intact).

## GetAggregatedFighterRank residual @ 93.56 (next entry)

- 50 register-only + 4 stack + 2 reloc lines; classification instruction-sequence.
- The callee-save VECTOR: ours saves r21-r31 (11), expected r22-r31 (10) — frame 488 vs
  480 (+8 = exactly the extra save). Root: ours keeps raw `type` in r21 across
  GetNameCount; expected's raw type (r31) DIES at the type_val clrlwi and r31 is REUSED
  for `arr` (+064 addi r31,r1,40). One web too many. Guidance hints: decl order /
  loop-counter reuse / discard-liveness nudges. Candidates: move `type_val = type` decl
  position; or let arr/raw-type share via scope; permuter decl-chain peel (cardstate
  iter-12 precedent: 3 decl reorders each peeled ONE callee-save).
- Pairs: r25↔r26 (i vs res), r27↔r28 (base vs walker/type_val) swaps through the body.

## GetRankedFighter residual @ 94.58 (unchanged; next entry)

- +1 line (the +084 addi r6,r4,0 second &entries temp — copy-fold target) — NOTE: also
  one UNACCOUNTED −1 elsewhere (159 = 160 −2 +1; two extra-instr sites identified
  (+084 addi, +140 mr) ⟹ ours saves 1 instr somewhere unmapped — find it when either
  extra falls).
- +8 frame hole@16 (mechanism unknown — NOT the union temp, NOT baseVal, NOT PAD_STACK).
- 3 register-only inner-compare lines (+0c4/+0ec/+0fc).
- j-guard +1: closed spelling class (law 1), needs a new idea-space.

## PENDING-REVIEW (updated)

- mnDiagram2_GetAggregatedFighterRank: `res` is read at the join with NO default arm in
  the switch — intentionally uninitialized on the (never-taken-in-practice) default path
  to match original codegen (the original does exactly this; type is always 0x15-0x17
  from callers). A reviewer may want `res` initialized — that would break the match
  (re-adds the goto-next shape or kills the loop-carried web). Flag for pre-PR decision.

## Commit stack (cumulative)
- cc052016f GetRankedFighter 79.94 -> 94.58 (iter 2)
- e2d172d4d GetAggregatedFighterRank 81.91 -> 85.19 (iter 2)
- 05a5aaf91 GetAggregatedFighterRank 85.19 -> 93.56 (iter 3)

## TU state after iteration 3
Open set: CreateStatRow 80.11 (untouched — data-linking + inline-boundary round pending),
GetRankedFighter 94.58, GetAggregatedFighterRank 93.56, Create 93.75, GetRankedName 97.87,
UpdateHeader 94.18 (banked levers), HandleInput 97.46 (WALLED/parked).

---

# ITERATION 4 (driver 2, 2026-06-11): the priced callee-save peel — PARTIAL WIN (+0.58, boundary NOT flipped)

## THE ONE QUESTION: does the priced peel kill GetAggregatedFighterRank's extra callee-save (ours `stmw r21`, expected `stmw r22`)?

ANSWER: **NO — the r21→r22 boundary flip was NOT achieved by any spelling tried.** But the
investigation isolated the residual to ONE register and landed an unrelated +0.58 structural win.

## Mechanism (precise, from reloc-stripped side-by-side @ baseline 93.56)

The ENTIRE 50-register-only residual is a single coherent cascade rooted in ONE divergence at
the prologue arg-spill: `type` (param r4) lands in **r21 (ours)** vs **r31 (expected)**.
- Expected `+018 addi r31,r4,0` (type→r31), `+058 clrlwi r28,r31,24` (type_val cast, LAST read
  of r31), then `+064 addi r31,r1,40` — **r31 is REUSED for `arr`** (type dies at cast, arr born
  immediately after, they share the physical reg → 10 callee-saves, `stmw r22`, frame 480).
- Ours `+018 addi r21,r4,0` (type→r21), cast reads r21, but r21 is NEVER reused; `arr` gets a
  fresh callee-save → 11 callee-saves, `stmw r21`, frame 488 (+8).
- Raw `type` is read EXACTLY ONCE in source (the `type_val = type` cast); the switch reads
  type_val only. So lever family (1) "make type's last use the cast" was ALREADY structurally
  satisfied at baseline — it is a no-op. The peel is purely a coloring-ORDER decision.

ROOT (newly characterized this iteration): in OURS the funcTable invariant-hoist
(`mnDiagram_GetNamePlayTimeByFighter` symbol, used in cases 0x15/0x16) colors into **r31**
(`+058 addi r31,r4` = the lo half), pushing `type`'s spill down to r21. In expected, funcTable
is r30 and type owns r31. i.e. the preheader SCHEDULE order differs: expected emits the
`clrlwi`(type-cast) FIRST (+058) so type claims fresh-descending r31; ours emits funcTable +
arr first and the cast LAST (+064), so type colors after them into the bottom slot. MODEL GAP,
cause unattributed: no source spelling tried reorders the preheader so the type-cast schedules
before the funcTable/arr hoists.

## Build ledger (5/5 metered builds used)

| # | Edit | Result | Boundary | Verdict |
|---|---|---|---|---|
| 1 | decl: move `arr` ABOVE `type_val` (base,curr,arr,type_val,...) | 93.56 → 93.84 | still `stmw r21` | incidental band shuffle; no peel. Reverted. |
| 2 | decl: move `arr` LAST (after `zero`) | 93.56 (no change) | still `stmw r21` | decl-order band does not touch the type save. Reverted. |
| 3 | **inline cast `switch ((s32) type)`, drop `type_val` local** | 93.56 → **94.14** | still `stmw r21` | **KEPT (committed 2a01de812).** Removes the named-local copy/home noise; snaps 5 prologue regs to exact match (base→r27, out→r23, idx→r24, ptr→r28). type STILL lands r21 — proves the extra save is NOT caused by the type_val local. |
| 4 | named cast-temp `type_val = (s32) type;` before arr, used in switch | **93.56 REGRESS** (vs build-3 94.14) | still `stmw r21` | the named `type_val` local is WORSE than the inline cast (re-adds band noise). Reverted to build-3. |
| 5 | `arr = entries` moved BEFORE `count = GetNameCount()` | **92.73 REGRESS** (class → signature-type-mismatch) | still `stmw r21` | arr's earlier def hurt; reverted to build-3. |

## Laws extracted / confirmed (iteration 4)

1. **Inline-cast beats named-int-copy for a u8→switch operand:** `switch ((s32) type)` (94.14)
   strictly dominates `type_val = type; switch(type_val)` (93.56) AND
   `type_val = (s32) type; switch(type_val)` (93.56) here. The named int local mints a
   copy/home web that perturbs the prologue arg-spill band; inlining the cast lets the 5 spill
   pointers (base/out/idx/ptr) color to their exact target registers. (Generalizes the trio's
   "drop the m2c-minted intermediate local" pattern to a scalar switch operand.)
2. **The extra callee-save is a coloring-ORDER residual, not a source-object residual:** the
   peel survives removal of the only named local on type's path (build 3), decl-order moves of
   the competitor `arr` (builds 1,2), and assignment-order moves (build 5). The lever, if it
   exists, is whatever reorders the preheader invariant SCHEDULE so the type-cast precedes the
   funcTable hoist — not reachable via decl-order / assignment-order / cast-spelling here.
3. **funcTable-hoist-vs-type-spill contention (named, for next driver):** the residual r31 is
   contested between the hoisted `mnDiagram_GetNamePlayTimeByFighter` address and the `type`
   param spill; expected gives r31 to type, ours to funcTable. Driver-1 iter-3 already found
   that DROPPING a funcTable local (direct symbol) was load-bearing for landing 87.64→93.56, so
   a funcTable *local* is contraindicated (untried this iter precisely because it likely
   regresses). Next idea-space: force the type-cast to be the first-scheduled preheader op
   without a named int (e.g. reference `(s32)type` in the loop guard / a comma at loop entry),
   or investigate whether the switch arm ORDER (0x15/0x16 referencing funcTable before 0x17)
   controls the hoist priority.

## GetAggregatedFighterRank residual @ 94.14 (next entry)

- Boundary: ours `stmw r21,444(r1)` / frame 488 vs expected `stmw r22,440(r1)` / frame 480
  (+8 = the one extra callee-save holding `type` in r21, un-reused).
- The whole 50-line register-only cascade is ONE renumber off this single r21-vs-r31 type
  landing; everything downstream falls out if the type-cast colors into r31 (gets reused by
  arr). It is a preheader-schedule/coloring-order wall, NOT a structure or stack residual.
- 4 stack lines + 2 reloc lines are the same downstream cascade; re-read after a peel.
- Prologue band is otherwise EXACT after build 3 (base/out/idx/ptr/zero all match).

## PENDING-REVIEW (carried + unchanged)

- mnDiagram2_GetAggregatedFighterRank: `res` is read at the join with NO default arm in the
  switch (intentionally; original does this; type is always 0x15-0x17 from callers). Carried
  from iter-3 — reviewer may want `res` initialized; that would break the match. Build-3's
  inline `switch ((s32) type)` does NOT change this (still no default). No NEW guideline risk
  this iteration: the commit is natural C only (no PAD_STACK, no volatile, no data-symbol).

## Commit stack (cumulative)
- cc052016f GetRankedFighter 79.94 -> 94.58 (iter 2)
- e2d172d4d GetAggregatedFighterRank 81.91 -> 85.19 (iter 2)
- 05a5aaf91 GetAggregatedFighterRank 85.19 -> 93.56 (iter 3)
- 2a01de812 GetAggregatedFighterRank 93.56 -> 94.14 (iter 4, this driver)

## TU state after iteration 4
Open set: CreateStatRow 80.11 (untouched — data-linking + inline-boundary round still pending),
GetRankedFighter 94.58, **GetAggregatedFighterRank 94.14**, Create 93.75, GetRankedName 97.87,
UpdateHeader 94.18 (banked levers), HandleInput 97.46 (WALLED/parked).
Protected-set sweep (full ninja report.json): all 55 mndiagram/2/3 100s hold; all partials
unchanged (mndiagram3_8024714C 90.23, mndiagram3_80245BA4 94.07, fn_802461BC 98.42,
GetRankedFighter 94.58, GetRankedName 97.87, HandleInput 97.46, CreateStatRow 80.11,
Create 93.75, UpdateHeader 94.18, InputProc 98.67, 802427B4 98.84). Zero collateral.

---

# ITERATION 5 (driver 2, 2026-06-11): the preheader-schedule round — BOUNDARY FLIPPED (comma-at-arr)

## THE ONE QUESTION: does forcing the type-cast before the funcTable hoist flip the r31 contention (stmw r21→r22)?

ANSWER: **YES — via idea-space (2), the comma-expression at loop entry.**
`arr = ((s32) type, entries);` flips the save-restore boundary to the target's exact
`stmw r22,440(r1)` and the frame to 480 (both byte-exact). Committed 1d924db54.

## Mechanism check (the decisive refinement of iteration-4's model)

Iteration-4 framed the wall as preheader SCHEDULE order. The metered builds show the schedule
is DOWNSTREAM of the real mechanism: **linear-IR interference**. In the old form, the cast
(type's kill) was emitted AFTER `arr`'s def in the pre-coloring linear IR, so type and arr
INTERFERE — reuse impossible regardless of coloring order. The comma on arr's own assignment
places the cast reference immediately BEFORE arr's def (CSE merges it with the switch's
hoisted cast), the interference edge vanishes, and the extra callee-save peels.
Observed topology after the flip: ours coalesces the cast IN-PLACE on type
(`clrlwi r30,r30,24`, one merged web); expected keeps two webs (type r31 dies at cast →
result into r28 reusing dead ptr; arr reuses type's freed r31). Same save COUNT (10),
different reuse graph — the % residual lives there.

## Build ledger (4/4 used)

| # | Edit (on the 2a01de812 inline-cast substrate) | % | Boundary | clrlwi pos | Verdict |
|---|---|---|---|---|---|
| 1 | guard comma: `for (i = 0; (s32) type, i < count; i++)` | 94.14 | r21 | +064 (unmoved) | INERT — IRO normalizes/DCEs the discarded guard cast entirely. Reverted. |
| 2 | **loop-entry comma: `arr = ((s32) type, entries);`** | **94.11** | **r22 ✓ FLIP** | +060, in-place r30,r30 | **KEPT/committed.** Frame 488→480 exact; stack-slot diffs 4→0; reg-only 50→43; hunks 30→24. −0.03% = register noise (structure-over-match). |
| 3 | comma on count: `count = ((s32) type, GetNameCount());` | 94.25 | r22 ✓ | **+050 — BEFORE the bl** | GATE-FAIL despite best %: clrlwi emitted above GetNameCount, shifting the whole call region one slot; classification → signature-type-mismatch ("call shape differs"). Structure broken. Reverted. |
| 4 | build-2 + `base` decl moved LAST | 93.94 | r22 ✓ | — | Wrong direction: base r26→r25 (away from target r27). The "last-declared pops earlier" inference does NOT hold for this promoted web. Reverted. |

Idea-space (3) (switch-arm order) NOT spent: builds exhausted on (1)/(2)/(2-variant)/(decl);
arm order remains untried — low conviction (MWCC normalizes switch compare trees by value),
but it is the one authorized spelling still open.

## Laws minted (iteration 5)

1. **Comma-at-def linear-order law (the flip):** to let web B reuse web A's register, A's
   kill must precede B's def in linear IR; a comma carrying A's killing expression INSIDE
   B's defining assignment (`B = (kill_A_expr, B_value)`) achieves it without a named local.
   CSE merges the comma cast with the loop-hoisted switch cast — one clrlwi, repositioned.
   (Same family as the 802427B4 `(0,X)` LICM comma; cite docs/mndiagram-inputproc-campaign.md.)
2. **Guard-comma inertness:** a discarded invariant cast in a for GUARD is erased by IRO
   before it can anchor anything (byte-identical output). The comma must be on a statement
   with a live result.
3. **Comma-before-call overshoot:** carrying the cast on the call-result assignment emits the
   clrlwi BEFORE the bl (its source position), transposing the call region = structural fail.
   The comma site must sit between the call and the def whose interference you're killing.
4. **Schedule-is-downstream:** iteration-4's "preheader-schedule wall" framing refined — the
   emission position follows from the interference/coloring outcome, not vice versa. The C
   lever controls LINEAR ORDER of kill-vs-def, not the scheduler.

## GetAggregatedFighterRank residual @ 94.11 (next entry)

- Boundary/frame: EXACT (stwu -480, stmw r22,440).
- 43 register-only lines + 2 reloc lines = TWO adjacent callee-save transpositions in the
  fresh-dispense order (guidance names them): r26↔r27 (base/zero — cascades through the
  whole populate + sort loops, the high-line-count pair) and r30↔r31 (type/funcTable).
- Topology delta vs expected: ours cast-in-place-on-type (merged web) + arr→r28(ptr's slot);
  expected cast→r28(ptr's slot) + arr→r31(type's slot). For the exact assignment the merged
  type+cast web must SPLIT (two webs) while keeping the comma's linear order — a named local
  splits it but is contraindicated (iter-4 law 1); an untried spelling class would need to
  break the in-place coalesce without minting a home (e.g. self-assignment nudges
  `type = type`-family — UNTRIED, next iteration's first probe).
- Build-4 datum for the decl chain: moving base's decl LAST pushed base r26→r25 (wrong way);
  the direction model for promoted webs on this substrate is earlier-decl→earlier-pop —
  UNVERIFIED (one datum); the cardstate peel-chain (one decl at a time, keep-or-revert) on
  zero/curr/ptr/arr decls is the remaining decl idea-space.

## PENDING-REVIEW (updated)

- **NEW: the comma expression `arr = ((s32) type, entries);`** — unusual spelling retained
  for codegen (the save-boundary flip). Precedent: committed `(0,X)` comma in
  mnDiagram_802427B4 (a527c0227). A reviewer may ask for a comment or a different spelling;
  any rewrite must preserve the kill-before-def linear order or the boundary regresses.
- Carried: `res` uninitialized on the never-taken default path (iter-3; matches original).

## Commit stack (cumulative)
- cc052016f GetRankedFighter 79.94 -> 94.58 (iter 2)
- e2d172d4d GetAggregatedFighterRank 81.91 -> 85.19 (iter 2)
- 05a5aaf91 GetAggregatedFighterRank 85.19 -> 93.56 (iter 3)
- 2a01de812 GetAggregatedFighterRank 93.56 -> 94.14 (iter 4)
- 1d924db54 GetAggregatedFighterRank save-boundary flip, 94.14 -> 94.11 structural keep (iter 5)

## TU state after iteration 5
Open set: CreateStatRow 80.11 (untouched — the carried READ-ONLY opening survey did NOT
trigger this iteration: 4/4 builds spent; survey remains the iteration-6 contingent),
GetRankedFighter 94.58, **GetAggregatedFighterRank 94.11 (boundary+frame exact)**,
Create 93.75, GetRankedName 97.87, UpdateHeader 94.18, HandleInput 97.46 (WALLED/parked).
Protected-set sweep (full ninja report.json): all 55 mndiagram/2/3 100s hold; all other
partials byte-unchanged. Zero collateral.
