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

---

# ITERATION 6 (driver 3, 2026-06-11): CreateStatRow OPENING MAP + top-rung (base-reuse)

## THE ONE QUESTION
What is mnDiagram2_CreateStatRow's (80.11) divergence structure, and does the top rung land?

## OPENING MAP — classification CORRECTED (the iter-1 read was checkdiff-display-distorted)

**Ground-truth method (important for next drivers):** the default `checkdiff` side-by-side
ALIGNMENT SLIPS on this +11-instr function — it showed phantom `blt`/`@595`/121-reloc-lines
and a fictitious inline-boundary ("expected makes 34 calls ours omits"). ALL FALSE. Every
`bl` is present in both. The `@595/@598/@599` are checkdiff's name-magic renames of
**anonymous .sdata2 float-pool** entries, NOT missing string links. The real map comes from
disassembling **both** objdiff objects and diffing with only VA/offset/byte + `.L`-label
normalization:
- TARGET (expected)  = `build/GALE01/obj/melee/mn/mndiagram2.o`  (DTK-extracted from DOL) — 421 instrs
- OURS    (base)     = `build/GALE01/src/melee/mn/mndiagram2.o`  (built from src/) — 432 instrs (+11)
- objdiff.json confirms target_path=obj/, base_path=src/. (checkdiff's "current" column = OURS.)

**True classification: cached-base re-materialization + flag-register/cast cascade.** NOT
inline-boundary, NOT data-linking. Zero genuine string/data-symbol link diffs — all symbol
refs (`mnDiagram2_803EEAD0`, `_804D4FC0`/`FC8` asserts, `_804DBFD0..E8` floats, `_804D4FBC`,
all `bl` targets) are byte-identical-once-linked. The float-pool `@5xx/@6xx` are anonymous
.sdata2 residuals that resolve AT match-time (per the mndiagram3 .sdata2-float law — do NOT
force named float symbols).

## The divergence, in dependency order (root first)

**ROOT (R1) — `base` (`mnDiagram2_803EEAD0`) is materialized 3× in OURS, 1× in TARGET.**
- TARGET: ONE `lis r3,@ha; addi r31,r3,@l` (line 14) → keeps base in **r31** the whole fn;
  computes all three `lb_8000B1CC` 2nd-args as `addi r4, r31, 0xC` / `addi r4, r31, 0x18`
  (offsets from the cached base). The `table` deref also uses it.
- OURS: materializes base into r30 (line14), then RE-materializes `lis/addi` at the 1st and
  3rd `lb_8000B1CC` sites (lines 35-36, 276-277), plus an extra `addi r23,r4,0xC; addi r4,r23,0`.
- CAUSE IN SOURCE: `base = (char*)&mnDiagram2_803EEAD0;` IS cached (src 634), but the three
  calls pass `(Vec3*) &mnDiagram2_803EEAD0[0xC]` / `[0x18]` (src 644, 667, 733) — indexing the
  GLOBAL directly, defeating the cache. Fix = `(Vec3*)(base + 0xC)` / `(base + 0x18)`.
- This is the EARLIEST divergence; it forces the whole r29/r30/r31-vs-r30/r31 + callee-save
  renumber. Structure-first: collapsing it should cascade-fix much downstream. Lever class =
  inline-base-cast / cached-base-reuse (MEMORY dispform_inline_base_cast + accessor_macro lever).

**R2 — flag-register in the var_r3/var_r0 if-ladders: OURS `li r0,0/1` + `blt`, TARGET
`li r3,0/1` + `bge`.** TARGET computes each 0/1 flag in **r3** with `bge` (test-and-branch-to-set,
default-below), then the immediately-following `stb`/store reuses r3. OURS uses **r0** + `blt`
(inverted, test-and-fall-through, inline `li`). The four ladders (`>=0x12/>=0xE`, `>=0x18/>=0x15`
×2, `>=0xC/==3/>=0xE`) all diverge this way. Candidate: the flag must land in a GPR that the
sink reuses — likely an `int`-vs-`u8` / explicit-temp spelling, OR the ladder result feeds a
call/store that wants r3. LOWER conviction than R1; re-read after R1 (may re-roll).

**R3 — redundant `clrlwi` at the `mnDiagram2_GetStatValue(is_name_mode, ...)` arg sites.**
OURS emits `clrlwi r3,r24,24` (re-truncate `(u8)is_name_mode`) before several GetStatValue
calls (diff lines 105a113, 133, 142a157, plus the `clrlwi r3,r3,24` on a return); TARGET passes
`addi r3,r24,0` — the arg is already the clrlwi'd `is_name_mode` cached in r24. Source passes
`is_name_mode` (a `u8` param) directly; MWCC re-truncates. Candidate: the cached `(u8)` form /
matching GetStatValue's exact prototype arg type so no re-clrlwi. MEDIUM conviction.

**R4 — float-temp stack offsets (0x20/0x24/0x28 vs 0x3c/0x40/0x44) + `stmw r21`(T) vs
`r23`(O) + frame 0x4c vs 0x54.** TARGET saves r21-r31 (11 saves) yet is SHORTER; OURS saves
r23-r31 (9) but +11 instrs from re-materialization. Frame/slot offsets are DOWNSTREAM of R1+R4
register pressure. PAD_STACK(16) present (diagnostic, do NOT ship — replace w/ natural frame).
Re-read after R1.

## RANKED LEVER LADDER (iteration-6)
1. **R1: cached-base reuse** — rewrite the 3 `lb_8000B1CC` 2nd-args `&mnDiagram2_803EEAD0[N]`
   → `(Vec3*)(base + N)`. EARLIEST divergence, highest conviction, structure-first. ← TOP RUNG.
2. **R3: kill redundant clrlwi** at GetStatValue calls (cache `(u8)is_name_mode` or fix arg type).
3. **R2: flag-register/comparison-form** in the four if-ladders (r0→r3 / blt→bge spelling).
4. **R4: frame/callee-save** — falls out of R1+R3 (structure-first); revisit last.

## Build ledger (2/5 used — early report, top rung landed + 1 rung-2 datum)

| # | Lever | Edit | % | Mechanism check | Verdict |
|---|---|---|---|---|---|
| 1 | R1 cached-base | 3× `(Vec3*) &mnDiagram2_803EEAD0[N]` → `(Vec3*)(base + N)` | 80.11 → **81.54** | base materializations 3→1; instr 432→427 (+11→+6); stmw r23→r22 (9→10 saves) | **LANDED, committed 47b40968d.** Structure-first root collapsed. |
| 2 | R2 flag-reg probe | first ladder → `var_r3=1;` preset + empty `>=0xE` arm | **80.71 REGRESS** | flag DID flip to r3 + `bge` (line14) + 427→425, BUT `default_alignment=1` `li r0,1` and var_r3 `li r3,1` did NOT CSE — two `1`-consts minted → net worse | REVERTED (git checkout). DATUM: preset-1 alone insufficient; R2 needs the `1`-web to coalesce, a coloring/CSE tiebreak. |

## TOP-RUNG VERDICT
R1 (cached-base reuse) LANDED clean: **80.11 → 81.54**, committed 47b40968d, protected sweep
zero-collateral (all 55 mndiagram* 100s + every partial byte-identical). The single highest-
conviction structural lever paid as predicted; base now materialized once, frame tightened one
callee-save toward target.

## CreateStatRow residual @ 81.54 (rung-2 entry for next driver)
Remaining vs target (build/GALE01/src vs obj, reloc+label normalized): +6 instrs, ~300
normalized-diff lines, ALL in two interlocked register/CSE residuals (NOT structure, NOT data):

- **R2 (flag-register + comparison-form) — the LARGEST contributor (4 if-ladders).** TARGET
  presets the flag in **r3** (CSE'd from the immediately-preceding `text2->default_alignment = 1`
  / `text3->default_alignment = 2` store constant) and uses `bge`-override-to-0 (default-below);
  OURS mints the flag in **r0** with `blt` + inline `li`. Probe #2 proved preset-1 alone flips
  polarity but does NOT force the `1`-constant to coalesce with var_r3's web (two `li`s minted).
  Next idea-space (UNTRIED): make var_r3 and the `default_alignment` value LITERALLY the same
  object/expression (e.g. compute the alignment store from var_r3, or a shared `int one = 1`
  feeding both), so the `1`-web spans both — a coalesce nudge, cardstate-decl-peel territory.
  Conviction MEDIUM; this is a coloring/CSE tiebreak (cf. this file's GetAggregatedFighterRank
  iter-4/5 — register-coloring residuals here take multi-build hunts, not one clean lever).

- **R3 (redundant clrlwi at GetStatValue args) — intertwined with R2.** TARGET passes
  `addi r3, r24, 0` (r24 = `is_name_mode`, trusted u8-clean); OURS re-truncates `clrlwi r3,r24,24`
  at each of the ~5 `mnDiagram2_GetStatValue(is_name_mode, ...)` calls (+ a `clrlwi r3,r3,24` on
  a return). Source passes the `u8 is_name_mode` param directly to GetStatValue's `int` first arg.
  Hypothesis: the original cached `(u8) is_name_mode` ONCE into a local (so r24 is the already-
  clrlwi'd value and the call sites are plain copies), OR GetStatValue's prototype first-arg type
  differs from what we declare. Re-read GetStatValue's exact matched signature + how the matched
  callers (PopulateStatRows) pass is_name_mode. Conviction MEDIUM.

- R4 (frame/callee-save: stmw r22 vs target r21, float-temp slots 0x3c/0x40/0x44 vs 0x20/0x24/0x28):
  pure downstream of R2+R3 register pressure; PAD_STACK(16) diagnostic still present (must become
  natural frame reservation before PR). Re-read AFTER R2/R3, do not chase directly.

**RECOMMENDED RUNG-2: R3 first (kill the GetStatValue clrlwi via a cached `(u8) is_name_mode`
local or prototype-arg fix — cleaner, more isolated than R2), then R2 (flag-web coalesce nudge).**
Both are register/CSE-class; expect a multi-build hunt per this file's coloring-wall precedent.

## PENDING-REVIEW (iteration 6)
- R1 commit is natural C only (offset arithmetic off an already-declared cached base). NO new
  guideline risk. PAD_STACK(16) in CreateStatRow is UNCHANGED/diagnostic — still must be replaced
  with natural frame reservation before any PR (carried; not introduced this iteration).
- Carried from prior iters: GetAggregatedFighterRank `res` uninitialized-on-default + comma
  spelling; unaffected this iteration.

## Commit stack (cumulative)
- cc052016f GetRankedFighter 79.94 -> 94.58 (iter 2)
- e2d172d4d GetAggregatedFighterRank 81.91 -> 85.19 (iter 2)
- 05a5aaf91 GetAggregatedFighterRank 85.19 -> 93.56 (iter 3)
- 2a01de812 GetAggregatedFighterRank 93.56 -> 94.14 (iter 4)
- 1d924db54 GetAggregatedFighterRank save-boundary flip, 94.14 -> 94.11 (iter 5)
- 47b40968d **CreateStatRow 80.11 -> 81.54 (iter 6, this driver — cached-base reuse R1)**

## TU state after iteration 6
Open set: **CreateStatRow 81.54** (R1 landed; rung-2 = R3 clrlwi then R2 flag-web, both
register/CSE-class), GetRankedFighter 94.58, GetAggregatedFighterRank 94.11, Create 93.75,
GetRankedName 97.87, UpdateHeader 94.18, HandleInput 97.46 (WALLED/parked),
mnDiagram3_HandleInput 98.42 (sibling-branch territory). Protected-set sweep (full report.json):
all 55 mndiagram* 100s hold; every partial byte-unchanged. Zero collateral.

---

# ITERATION 7 (driver 3, 2026-06-11): R3 (the is_name_mode clrlwi) — 1/7 LANDED, 6/7 walled by a consistency triangle; R2 contingent refuted (const-prop)

## THE ONE QUESTION: does R3 land? ANSWER: PARTIALLY — the return-cast mask landed (+0.27,
committed); the 6 param-handoff masks are pinned by a THREE-FUNCTION BYTE-CONSISTENCY TRIANGLE
that no single-TU consistent typing can satisfy (every candidate breaks a protected 100).

## The MWCC conversion-node rule (the iteration's foundational evidence, read pre-build)
From PopulateStatRows' single call site (4 arg styles at once) + GetStatValue's body:
- u8 value → u8 param: PLAIN (no mask) — `addi r4, r27`
- int value → u8 param: MASK — `clrlwi r5/r6/r7`
- u8 value → int param: MASK — CreateStatRow's 6 sites
- lbz-loaded value: PROVEN CLEAN — conversions elided (HandleInput's 9 inlined
  PopulateStatRows sites pass `data->is_name_mode` mask-free)
- u8-returning callee → int context: MASK (caller-side; `clrlwi r3,r3,24` after
  GetLeastPlayedFighter; callers do NOT trust callee returns)
The mask is attached to the CONVERSION NODE; provability (lbz) elides it, but a u8 PARAM is
untrusted. Tests of u8 params fuse mask+test (`clrlwi. r0, rX, 24`).

## Build ledger (4/5 used)

| # | Lever | Edit | Result | Verdict |
|---|---|---|---|---|
| 1 | R3 lever-(1): cached u8 local | `u8 mode = is_name_mode;` + 7 call sites pass `mode` | **BYTE-IDENTICAL** to baseline (81.54, same 10-clrlwi census, same boundary) | REFUTED, strongest form. u8→u8 alias is IR-transparent; the conversion mask is unreachable by u8-typed respelling. |
| 2 | R3 lever-(2): int-chain flip | CreateStatRow + PopulateStatRows params u8→int (h+c), `(u8)`-cast test spellings | CreateStatRow 81.54→**83.58**, 6 masks DIED — but **PopulateStatRows 100→99.88** (frame 0x28→0x30: int-param HOME +8) + Create 93.75→93.04 | REVERTED (fence: zero collateral). The +2.04 is unreachable at this cost. |
| 3 | R3-b: return-cast drop | drop `(u8)` at the 80242B38 site (its proto = `(int, int)`; value guarded < 0x19) | 81.54→**81.81 COMMIT 35391757f**; census 10→9 (exactly the return-mask); sweep CLEAN (all gates exact, Create restored to 93.746475 precisely) | LANDED. |
| 4 | R2 contingent: copy-channel | `var_r3 = 1; text2->default_alignment = var_r3;` + empty middle arm | **81.60 REGRESS**; the two-li signature PERSISTS (`li r0,1` store + `li r3,1` web) — const-prop re-split | REVERTED. R2 banked as front-end-const-prop class. |

## Laws minted (iteration 7)

1. **u8-local alias transparency (b1, byte-identity):** a u8 local initialized from a u8 param
   compiles to NOTHING; masks at u8→int conversion sites are conversion-node artifacts, not
   home-provability artifacts. No u8-typed respelling can reach them.
2. **int-param frame-home law (b2):** flipping a u8 param to int mints an 8-byte-aligned frame
   home (+8 on stwu) even for a never-spilled register-resident param; the u8 home fit existing
   padding. Sibling of iter-2's u64-local frame law. A protected-100 caller FRAME is therefore a
   param-type ORACLE: PopulateStatRows' 0x28 frame pins its is_name_mode param as u8 in the original.
3. **The is_name_mode consistency triangle (the R3 wall, fully characterized):**
   (a) PopulateStatRows@100 pins {its param u8 (frame law), its arg2 mask-free (bytes)} ⟹
   CreateStatRow's param was u8 in the original;
   (b) CreateStatRow@target passes that u8 to GetStatValue mask-free ⟹ the call saw a u8-typed
   first param;
   (c) GetStatValue@100 pins its first param int-typed WITHIN the TU: its default tail
   (`return is_name_mode;` = ZERO instructions, bgt straight to epilogue) and its
   HitPercentage/PlayPercentage arms (`return mnDiagram_GetHitPercentage(is_name_mode, idxVal);`
   — raw bl, mask-free forwards ⟹ int→int) would all GAIN masks under a u8 param.
   Every consistent single-TU typing violates one leg. The original's mask-free mechanism is
   UNATTRIBUTED. Two candidate resolutions, both out of this iteration's scope:
   - **cross-TU u8-chain**: GetStatValue param-1 u8 + co-flip mnDiagram_GetHitPercentage /
     mnDiagram_GetPlayPercentage param-1 (mndiagram.c TU + their other callers) — UNTESTED;
     a 1-build empirical closure exists (flip GetStatValue alone, gate GetStatValue==100.0:
     predicted FAIL at tail+2 arms, but converts the inference to instrument fact);
   - original header/def prototype mismatch (decl u8, def int) — unshippable and untestable
     under -requireprotos.
   NOT "unmatchable": the masks are byte-reachable (b2 proved it at 83.58); the BLOCKER is the
   zero-collateral fence, not the codegen.
4. **Front-end const-prop defeats copy-channels for LITERAL webs (b4, 2nd R2 datum):**
   `var = 1; field = var;` is re-split by const-prop (store gets its own `li r0,1`; the web
   gets `li r3,1`). Copy-channels bind opaque values (call results — cardstate precedent), not
   literals. Target's shared-1 (`li r3,1` feeding both stb and ladder preset) requires the
   constant to survive as ONE node — an opacity device (volatile/call) would be needed, out of
   bounds here. R2 = BANKED (front-end-const-prop + coloring tiebreak class). Do not retry
   assignment-topology spellings.

## Anomaly note (for tooling, possibly issue-worthy)
During b2's sweep, mnDiagram2_Create read 93.04225 (from 93.746475) while its pre/post
instruction extract diffed EMPTY (extraction verified non-empty; bl census 2/2 — Create does
NOT inline CreateStatRow, my in-flight hypothesis was wrong). Restored to exactly 93.746475
on revert. Unexplained — possibly report-pipeline sensitivity to sibling-function size changes
within the unit. PopulateStatRows' frame regression was instruction-verified and alone decisive.

## CreateStatRow residual @ 81.81 (rung-3 entry for next driver)
- 9 clrlwi vs target 4+... precisely: ours-only = the 6 is_name_mode conversion masks
  (TRIANGLE-walled, see law 3); target-only = a SECOND `clrlwi rX, r25, 24` (stat_type).
- **RUNG-3 (NEW, structural, high conviction): the stat_type two-region truncation.** TARGET
  truncates `(u8) stat_type` TWICE — region 1 (`clrlwi r23,r25,24`: table index + ladder-1,
  short-lived) and region 2 (`clrlwi r22,r25,24` right before `cmpwi 0x18`: ladders 2-5).
  OURS mints ONE `int r23 = (u8) stat_type` (src line ~659) spanning the whole function in a
  long-lived callee-save (r31). Splitting the local into two region-scoped derivations
  (re-derive `(u8) stat_type` in the text3 block) mirrors the target's web structure, frees a
  long-lived callee-save mid-function, and may move the save boundary toward target's stmw r21.
  This is the same family as iter-3's "per-branch duplication" + the campaign's web-split lever.
- RUNG-4 (1-build empirical closure, optional): the GetStatValue-u8 flip test (law 3 bullet 1).
- The +5-line delta (426 vs 421) and the r26/r27 row_idx/entity_idx prologue swap: re-read
  after rung-3 (web-structure first).
- UpdateHeader:217 carries the same `(u8)`-cast-before-80242B38 artifact — transferable to ITS
  round (not touched; out of scope).

## PENDING-REVIEW (iteration 7)
- 35391757f drops a semantically-no-op `(u8)` cast (value guarded < 0x19 by the preceding
  branch) — natural C, no guideline risk.
- Carried: CreateStatRow PAD_STACK(16) diagnostic (must become natural frame reservation
  pre-PR); GetAggregatedFighterRank res-uninitialized + comma spelling.

## Commit stack (cumulative)
- cc052016f GetRankedFighter 79.94 -> 94.58 (iter 2)
- e2d172d4d GetAggregatedFighterRank 81.91 -> 85.19 (iter 2)
- 05a5aaf91 GetAggregatedFighterRank 85.19 -> 93.56 (iter 3)
- 2a01de812 GetAggregatedFighterRank 93.56 -> 94.14 (iter 4)
- 1d924db54 GetAggregatedFighterRank save-boundary flip, 94.14 -> 94.11 (iter 5)
- 47b40968d CreateStatRow 80.11 -> 81.54 (iter 6 — cached-base reuse R1)
- 35391757f **CreateStatRow 81.54 -> 81.81 (iter 7, this driver — R3-b return-cast drop)**

## TU state after iteration 7
Open set: **CreateStatRow 81.81** (rung-3 = stat_type two-region split; 6 is_name_mode masks
triangle-walled per law 3; R2 ladders banked as const-prop class), GetRankedFighter 94.58,
GetAggregatedFighterRank 94.11, Create 93.75, GetRankedName 97.87, UpdateHeader 94.18,
HandleInput 97.46 (WALLED/parked), mnDiagram3_HandleInput 98.42. Protected-set sweep:
all 55 mndiagram* 100s hold; every partial exact. Zero collateral.

---

# ITERATION 8 (driver 4, 2026-06-11): the cross-TU u8-chain co-flip (triangle resolution path a) — REFUTED by the default-tail pin, HARD-REVERTED

## THE ONE QUESTION: does the cross-TU u8-chain co-flip close the consistency triangle —
killing the 6 CreateStatRow masks with ZERO collateral?
ANSWER: **NO. The co-flip closes 3 of GetStatValue's 4 pins (the forward arms, perfectly) but
the default-tail pin (law 3c-i) is REAL and now INSTRUMENT-CONFIRMED: `return is_name_mode;`
under a u8 param emits `clrlwi r3,r3,24` (u8→int return promotion) that the int-param form
elides → GetStatValue 100 → 99.06. Hard-reverted (zero-collateral fence).** The win on
CreateStatRow (+1.84 → 83.65) is real but unbankable at the cost of GetStatValue's 100.

## Pre-build evidence (ground-truth disassembly, the decisive read)
Method: `build/binutils/powerpc-eabi-objdump -dr` on BOTH objects (obj/ = target DTK-extract,
src/ = ours), reloc+label normalized. The whole triangle's handoffs read MASK-FREE in the
target — the smoking gun for an original u8 chain:
- PopulateStatRows→CreateStatRow (target 12a8): `addi r4,r27,0` — is_name_mode arg MASK-FREE
  (r27 = raw incoming r5 param; prologue `clrlwi. r0,r5,24` tests into r0, leaves r27 raw).
- CreateStatRow→GetStatValue (target de4): `addi r3,r24,0` — is_name_mode arg MASK-FREE
  (r24 = CreateStatRow's clean u8 param). OURS masks it (`clrlwi r3,r24,24`) at all 6 sites.
- GetStatValue→Hit/Play/Avg (target 994/aec/af4): plain `bl`, NO preceding clrlwi.
- GetStatValue default tail (target): switch default `bgt c50` jumps STRAIGHT to the epilogue
  with r3 = raw is_name_mode, NO mask. (`c4c clrlwi r3,r3,24` is exclusively the
  GetLeastPlayedFighter u8-return mask, falls through from c48.)
- The three legs (GetHit int / GetPlay u8 / GetAvg int) ALL emit identical `clrlwi. r0,r3,24`
  for `(u8) is_name_mode != 0` — PROVING the int↔u8 param flip is body-codegen-INVISIBLE for
  them (GetPlay already ships u8 at 100). Gate-b safe for those legs by construction.

## The co-flip design (path a, exactly as built)
4 type-line edits, NO bodies touched (verified `git diff`: 4 files, 6 ins / 11 del):
1. `mnDiagram2_GetStatValue`: param `int`→`u8` (mndiagram2.c def + mndiagram2.h proto).
2. `mnDiagram_GetHitPercentage`: param `int`→`u8` (mndiagram.c def + mndiagram.h proto).
3. `mnDiagram_GetAveragePlayerCount`: param `int`→`u8` (mndiagram.c def + mndiagram.h proto).
4. `mnDiagram_GetPlayPercentage`: def already u8; **collapsed the `#ifdef MNDIAGRAM_SOURCE`
   conditional proto** (which gave mndiagram2.c an `int` view) to always-u8.
Scope verified: Hit/Play/Avg referenced only in mndiagram.c+mndiagram2.c; GetStatValue also in
mndiagram3.c (80245BA4) but those pass `data->is_name_mode` (lbz-loaded = PROVEN CLEAN, elided)
+ `0`/`1` literals → flip-invisible. PopulateStatRows/CreateStatRow params left u8 (correct;
iter-7 build-2 flipped THOSE = the wrong flip).

## Build ledger (2/2 used — 1 closure + 1 revert-rebuild)

| # | Edit | CreateStatRow | GetStatValue | Other protected | Verdict |
|---|---|---|---|---|---|
| 1 | full co-flip (4 type lines) | 81.81 → **83.652405** (6 masks DIED) | **100 → 99.06393** | PopulateStatRows 100, GetHit/GetPlay/GetAvg 100, Create 93.746475 EXACT; 51/52 hundreds hold | **GATE-B FAIL** on GetStatValue. Forward legs closed perfectly; default tail broke. |
| 2 | hard-revert (git checkout 4 files) + rebuild | 81.81016 EXACT | 100.0 | all 72 mndiagram* == baseline | Baseline restored exactly. |

## Instrument fact (the refutation, from the build-1 src/.o)
GetStatValue (u8 param) default tail diverges from target by EXACTLY ONE instruction:
- TARGET: default `bgt c50` → epilogue, r3 raw, no mask.
- OURS (u8): default branches to **`c5c clrlwi r3,r3,24`** → epilogue. The +1 mask (60 vs 59
  clrlwi in the fn) IS the u8→s32 return promotion on `return is_name_mode;`.
- The forward arms (99c Hit / af4 Play / afc Avg) in OURS-u8 are now plain `bl` with NO
  preceding clrlwi — i.e. **the co-flip DID close the forward-arm legs** (u8→u8 mask-free,
  byte-matching target). The ONLY residual is the default tail. Pin law 3c-i CONFIRMED.

## Laws minted / sharpened (iteration 8)

1. **GetStatValue is a DUAL-CONSTRAINT param (the triangle's irreducible core):** its first
   param faces TWO opposing conversion demands that no single C type satisfies —
   (i) the default tail `return is_name_mode;` wants **int** (int→int return = 0 instrs; u8→int
   = +1 `clrlwi r3,r3,24`), and (ii) the CreateStatRow handoff + forward arms read mask-free in
   the target, which the iter-7 conversion rule attributes to **u8** (u8→u8 plain). int param:
   tail OK + forwards OK + CreateStatRow MASKS (baseline, 6 masks). u8 param: forwards OK +
   CreateStatRow OK + tail BREAKS. The param-type axis is a SEE-SAW; the original satisfied both
   ends simultaneously, which a single param type provably cannot. ⟹ path (a) is the WRONG axis.
2. **Provable-clean-u8 exception to the conversion rule (the real mechanism, MODEL GAP):** the
   target passes CreateStatRow's u8 `is_name_mode` (r24) to GetStatValue's **int** param WITH NO
   MASK (`addi r3,r24,0`). The iter-7 rule "u8 value → int param = MASK" predicts a mask here and
   is WRONG for this case. The exception: a u8 value that is **provably clean** (a clean u8 param
   threaded through the body without redefinition) converts to int MASK-FREE — MWCC's front end
   tracks the cleanliness. OURS masks because our IRO does NOT prove r24 clean across
   CreateStatRow's long body (4 GetStatValue call regions, interleaved stat_type work). The lever
   is therefore PROVABILITY (make MWCC see is_name_mode as clean at the call sites), NOT the param
   type. Cause unattributed at the IRO level (no front-end trace pulled this iteration). This is
   the same family as the iter-7 "lbz-loaded = elided" provability rule and mndiagram3's clean
   `data->is_name_mode` handoff — both are PROVABLE-clean sources that skip the mask.
3. **The conditional-proto device (`#ifdef MNDIAGRAM_SOURCE`) is a per-TU view skew, ALREADY
   PRESENT for GetPlayPercentage** (def u8, but mndiagram2.c saw int via `#else`). This is the
   mechanism a cross-TU co-flip WOULD use — and it is shippable precedent IF a consistent typing
   existed. It does not (law 1). The device cannot manufacture a type that is both int (for the
   tail) and u8 (for the call) within the SAME TU (mndiagram2.c sees ONE GetStatValue signature).

## Why the co-flip cannot be repaired (the one-repair-build was NOT spent on a doomed retry)
The default tail returns the VALUE of is_name_mode as int. Any C spelling that returns the u8
value promotes it (mask). The only mask-free form is an int-typed value = int param = re-opens
the 6 CreateStatRow masks. There is no within-GetStatValue spelling (verified by the see-saw law)
that frees the tail while keeping the param u8. The repair build was instead spent reverting
(correct per the zero-collateral fence). Rung-3 (stat_type split) NOT reached: contingent required
≥2 builds unspent; 0 were unspent (closure + mandatory revert = the 2-build budget).

## CreateStatRow residual @ 81.81 (UNCHANGED — rung-3 entry for iteration 9)
Reverted to baseline. The map is unchanged from iter-7:
- 9 clrlwi vs target's mixed 4: ours-only = the **6 is_name_mode masks** (now proven to be a
  PROVABILITY residual per law 2, NOT a param-type residual — the iter-7 "triangle" framing is
  refined: it is not that no consistent typing exists in the abstract, it is that the mask-free
  CreateStatRow→GetStatValue handoff requires MWCC to prove r24 clean, which our IRO doesn't);
  target-only = a SECOND `clrlwi rX, r25, 24` (stat_type, the two-region split).
- **RUNG-3 (iteration-9 TOP RUNG, structural, carried high-conviction): stat_type two-region
  truncation split.** TARGET truncates `(u8) stat_type` TWICE (region 1 `clrlwi r22,r26,24` +
  `clrlwi r23,r25,24`; region 2 `clrlwi r22,r25,24` right before the cmpwi 0x18 ladders). OURS
  mints ONE long-lived `int r23 = (u8) stat_type` (src line ~659) in a callee-save spanning the
  whole fn. Split into two region-scoped re-derivations (re-`(u8) stat_type` in the text3 block)
  to mirror the target web structure; frees a long-lived callee-save mid-fn. **Save-boundary note
  (from iter-6/7): OURS = `stmw r22` (10 saves), TARGET = `stmw r21` (11 saves) — target saves
  ONE MORE; the split should move OUR boundary DOWN toward r21 (more saves, shorter-lived webs),
  i.e. the direction is r22→r21.** Same family as iter-3 per-branch duplication + the campaign
  web-split lever. ≤2 builds. Watch: row_idx/entity_idx r26/r27 prologue swap + the +5-line delta
  (re-read after the split — web-structure first).
- **RUNG-4 (provability probe, NEW from law 2, MEDIUM conviction):** make MWCC prove
  is_name_mode clean at the 6 GetStatValue call sites WITHOUT changing the param type. Candidate
  idea-spaces (all UNTRIED): (i) a single `is_name_mode &= 0xFF;`-style clean at fn entry that
  IRO can forward as a clean fact (risk: u8 param `&= 0xFF` may DCE to nothing like the u8-alias,
  iter-7 law 1 — but it is an int-context AND so might anchor a clean web); (ii) cache the cleaned
  value through an explicit int that IS proven clean (the opposite of iter-7 lever-1's u8-alias —
  try `int mode = (u8) is_name_mode;` ONCE, pass `mode` to all 6 — this mints an int web that is
  PROVABLY the masked value, so the call sites become int→int mask-free AND the masks coalesce to
  ONE; this is the untried inverse of the see-saw and is the single most promising probe).
  CAVEAT: (ii) failed as a *u8* local (iter-7 b1 byte-identical); the NEW hypothesis is that an
  *int* local holding the pre-masked value behaves differently (one shared clrlwi feeding an int
  web vs six conversion-node masks). Build it FIRST in iteration 9 if rung-3 stalls — it directly
  targets law-2's provability mechanism and may collapse 6 masks → 1.

## PENDING-REVIEW (iteration 8)
- **Nothing shipped this iteration** (co-flip hard-reverted; working tree == baseline). No
  PENDING-REVIEW entry earned. The cross-TU type-edit precedent class (consistency-fixing type
  corrections that keep .text byte-identical) was NOT validated here because the co-flip was not
  byte-identical (GetStatValue regressed). Had it landed, it would have flagged for pre-PR review.
- Carried (unchanged, no edits): CreateStatRow PAD_STACK(16) diagnostic (must become natural
  frame reservation pre-PR); GetAggregatedFighterRank res-uninitialized-on-default + comma spelling.

## Commit stack (cumulative — UNCHANGED; iteration 8 added no code commit)
- cc052016f GetRankedFighter 79.94 -> 94.58 (iter 2)
- e2d172d4d GetAggregatedFighterRank 81.91 -> 85.19 (iter 2)
- 05a5aaf91 GetAggregatedFighterRank 85.19 -> 93.56 (iter 3)
- 2a01de812 GetAggregatedFighterRank 93.56 -> 94.14 (iter 4)
- 1d924db54 GetAggregatedFighterRank save-boundary flip, 94.14 -> 94.11 (iter 5)
- 47b40968d CreateStatRow 80.11 -> 81.54 (iter 6 — cached-base reuse R1)
- 35391757f CreateStatRow 81.54 -> 81.81 (iter 7 — R3-b return-cast drop)
- (iteration 8: docs-only commit; co-flip refuted + reverted, zero code change)

## TU state after iteration 8 (== iteration 7; co-flip reverted)
Open set: **CreateStatRow 81.81** (path-a co-flip REFUTED by default-tail dual-constraint pin;
iteration-9 = rung-3 stat_type two-region split THEN rung-4 int-clean-local provability probe),
GetRankedFighter 94.58, GetAggregatedFighterRank 94.11, Create 93.746475, GetRankedName 97.87,
UpdateHeader 94.18, HandleInput 97.46 (WALLED/parked), mnDiagram3_HandleInput 98.42,
mnDiagram3_80245BA4 94.07. Protected-set sweep (full report.json): all 52 mndiagram* 100s hold;
every partial byte-exact (verified all 72 mndiagram* == /tmp/baseline_census.json). Zero collateral.

## Iteration-9 recommendation
1. **Rung-3 FIRST (stat_type two-region split)** — structural, high-conviction, carried from
   iter-7, independent of the (now-refuted) is_name_mode axis. Direction: OUR `stmw r22` should
   move toward target's `stmw r21` (one MORE save, shorter webs). ≤2 builds.
2. **Rung-4 (int-clean-local provability probe) if rung-3 stalls** — `int mode = (u8) is_name_mode;`
   ONCE, pass `mode` to all 6 GetStatValue calls. Hypothesis (law 2): collapses the 6 conversion
   masks to ONE shared int web (int→int mask-free at the calls). This is the untried inverse of
   iter-7's refuted u8-alias (b1) and directly targets the provable-clean mechanism. 1-2 builds.
3. The is_name_mode param-type axis (path a) is CLOSED — do NOT re-flip GetStatValue's param;
   it is a dual-constraint see-saw (law 1). Any further is_name_mode work must attack PROVABILITY
   (law 2), not type.

---

# ITERATION 9 (driver 4, 2026-06-11): the two priced rungs — rung-3 REFUTED (3-spelling trichotomy), rung-4 LANDED (+1.43, the provability law confirmed)

## THE ONE QUESTION: do the two remaining priced rungs close CreateStatRow's conversion/web residual?
- **Rung-3 (stat_type two-region split): NO — refuted at the source-spelling level** across the
  full spelling space; the target's two webs are an allocator-emergent live-range outcome, not a
  source structure (law 3 below).
- **Rung-4 (is_name_mode provability probe): YES — landed exactly as the iteration-8 law-2
  hypothesis predicted.** 81.81 → **83.24064**, committed 914e7ae31, zero collateral.

## Build ledger (4 metered + 1 revert-hygiene)

| # | Rung | Edit | % | Mechanism check | Verdict |
|---|---|---|---|---|---|
| 1 | 3 | two sibling-scoped `int r23 = (u8) stat_type;` locals (region boundary after the r21 block, exactly at target's e1c/cmpwi-0x18 seam) | 81.79 (−0.02) | census STILL 9 (no new clrlwi); `cmpwi r31,24` still reads the MERGED web; stwu −136→**−144** + stmw ofs 80→88 (the 2nd local minted a DEAD frame home) | REFUTED+reverted. Front-end CSE re-unifies a re-derivation of an available expression (sibling of iter-7 law b1). |
| 2 | 3 | NO local — `stat_type` used directly at all 12 ladder compares (the natural-developer spelling; let MWCC region it) | **79.24 REGRESS** | census 9→**13**: per-compare `clrlwi r0,r26,24` ×4 fresh volatile masks, dying immediately; NO callee-save webs; prologue band churned | REFUTED+reverted. Direct u8-param ordered-compares mask per compare-group into r0; MWCC does NOT self-region them into webs. |
| 3 | 4 | `int mode = is_name_mode;` decl + all 7 GetStatValue sites pass `mode` | **83.24064 COMMIT 914e7ae31** | census 9→**4** (== target count); the 6 masks → ONE `clrlwi r27,r4,24` (mode's prologue def); all 7 call sites `addi r3,r27,0` = plain copies, shape-matching target's 7× `addi r3,r24,0`; frame/boundary UNCHANGED (−136, stmw r22) — mode's web replaced the raw-param web 1-for-1 | **LANDED.** |
| 4 | 4 | mode decl moved FIRST (band probe toward target's r24) | 83.24064 — **byte-identical** | identical prologue (stat r24/row r26/entity r25/mode r27) | INERT; reverted to committed (mode-last). Decl position does not move an init-from-param web. |

## Laws minted (iteration 9)

1. **Re-derivation transparency (rung-3 spelling space CLOSED):** the three spellings of a
   u8-truncation web bracket the space — ONE named int local = 1 merged callee-save web
   (baseline 81.81); TWO scoped locals = CSE re-unifies (the 2nd init is deleted as redundant)
   + a DEAD 8B frame home appears (81.79); ZERO locals (direct param compares) = per-site
   fused volatile masks, no webs at all (79.24). A region-scoped re-truncation of an
   available expression is IR-transparent — generalizes iter-7 law b1 from values to webs.
2. **Target's two-region truncation = allocator-emergent, not source:** target derives BOTH
   clrlwi from raw r25 on the UNCONDITIONAL path (d4c dominates e1c), so source scoping cannot
   produce the split either (a dominated re-derivation is exactly what build-1 proved CSE
   eats). The split is MWCC's own live-range/pressure decision — target runs 11 callee-saves
   (stmw r21) vs our 10 (r22), and the extra pressure plausibly comes from the banked R2
   shared-1 flag webs. MODEL GAP, cause unattributed (no IRO trace pulled). PREDICTION: if R2
   ever lands, re-measure — region-2 may appear for free.
3. **int-local provability law (THE WIN, the see-saw's caller-side resolution):** for a u8
   param consumed by N int-param call sites, `int local = u8param;` converts ONCE at the def
   (one clrlwi, prologue) and makes every call site a PLAIN COPY (int→int, provably clean).
   The 6 conversion-node masks are not individually reachable (iter-7 b1) and the param-type
   axis is a see-saw (iter-8) — but the conversion NODE can be hoisted and shared via an
   int-typed local. Cost vs the unreachable ideal: +1 instruction (the def clrlwi; target
   keeps the raw param clean for free) — 83.24 vs the co-flip's demonstrated 83.65.
4. **Init-from-param web is decl-position-inert (build 4):** its def site (and color) is
   pinned by the prologue param-read, not the locals band. Don't spend builds rotating it.

## CreateStatRow residual @ 83.24 (NEARLY FULLY ATTRIBUTED — the endgame map)

clrlwi census 4 vs 4 (composition: ours = mode-def + 1 stat_type + 2 row_idx; target = 2
stat_type + 2 row_idx). Every remaining divergence now hangs off attributed walls:

1. **R2 const-prop/shared-1 flag webs (BANKED, iter-6/7):** target's ladders preset the flag
   in r3 CSE'd with the `default_alignment = 1/2` store constants + bge polarity; ours mints
   per-ladder `li r0` + blt. Copy-channel and preset spellings refuted (iter-6 #2, iter-7 b4).
   UNTRIED candidate (flag for a FUTURE driver, requires explicit authorization since it is in
   the banned assignment-topology class): the store-VALUE spelling
   `var_r3 = (text2->default_alignment = 1);` — binds the flag to the store's value node,
   which const-prop may not re-split (store nodes are opaque, unlike the refuted copy-channel).
2. **stat_type region-2 web (law 2):** allocator-emergent; possibly downstream of R2's
   pressure. No source lever found despite the full spelling-space search (law 1).
3. **Prologue band permutation (coloring-order):** ours {stat r24, entity r25, row r26,
   mode r27} vs target {is_name r24, stat r25, row r26, entity r27} — row_idx r26 now MATCHES
   (baseline had row r27). The rest is one rotation; plausibly re-rolls if 1/2 ever land.
4. **The mode-def clrlwi (+1 instr):** intrinsic to the caller-side resolution; only the
   closed see-saw's int-param side removes it. PRICED, accept.
5. **Frame slots (float temps 0x3c.. vs 0x20..) + PAD_STACK(16):** downstream of 1-3;
   PAD_STACK must become natural frame reservation pre-PR regardless.

**Endgame:** CreateStatRow has reached its attributed structural frontier at 83.24. The two
remaining levers are (a) the R2 store-value spelling (banned-class, needs authorization) and
(b) nothing else source-reachable — everything further is register-cascade hunting on walls
1-3. Recommend BANKING the function here and rotating; reopen only with the R2 exception or
an IRO-trace round that attributes the live-range splitter's trigger.

## PENDING-REVIEW (iteration 9)
- 914e7ae31 adds `int mode = is_name_mode;` — natural C, no guideline risk (named local,
  no PAD_STACK/volatile/data-symbol change). The name `mode` is bland; rename at /understand
  time if desired (keep the int type and the single-init shape — they are load-bearing).
- Carried: CreateStatRow PAD_STACK(16) diagnostic (must become natural frame pre-PR);
  GetAggregatedFighterRank res-uninitialized + comma spelling.

## Commit stack (cumulative)
- cc052016f GetRankedFighter 79.94 -> 94.58 (iter 2)
- e2d172d4d GetAggregatedFighterRank 81.91 -> 85.19 (iter 2)
- 05a5aaf91 GetAggregatedFighterRank 85.19 -> 93.56 (iter 3)
- 2a01de812 GetAggregatedFighterRank 93.56 -> 94.14 (iter 4)
- 1d924db54 GetAggregatedFighterRank save-boundary flip, 94.14 -> 94.11 (iter 5)
- 47b40968d CreateStatRow 80.11 -> 81.54 (iter 6 — cached-base reuse R1)
- 35391757f CreateStatRow 81.54 -> 81.81 (iter 7 — R3-b return-cast drop)
- 914e7ae31 **CreateStatRow 81.81 -> 83.24 (iter 9, this driver — is_name_mode provability probe)**

## TU state after iteration 9
Open set: **CreateStatRow 83.24 (BANKED-recommended — attributed frontier, see endgame)**,
GetRankedFighter 94.58, GetAggregatedFighterRank 94.11 (reserved self-assignment probe),
Create 93.746475, GetRankedName 97.87, UpdateHeader 94.18, HandleInput 97.46 (WALLED/parked),
mnDiagram3_HandleInput 98.42, mnDiagram3_80245BA4 94.07. Protected sweep: all 52 mndiagram*
100s hold; every other partial byte-exact vs baseline. Zero collateral.

## Iteration-10 recommendation
1. **UpdateHeader 94.18 FIRST** — it carries the PRICED 1-build transfer from iter-7
   (35391757f): the `(u8) name` cast at `mnDiagram_80242B38((u8) name, 0)` (line ~217), the
   exact artifact whose drop paid +0.27 on CreateStatRow ('name' is int but provably u8-clean
   from the ByIndex_s macros; the cast mints a mask the target may lack — VERIFY against
   target bytes first, same method). Then its iter-1 banked levers.
2. **Create 93.75 second** (iter-1 banked levers; also the iter-7 anomaly note — its
   pre/post extract diffed empty while % moved; treat its meter with care).
3. **AggRank reserved self-assignment probe third** (iter-5's named next probe: split the
   merged cast-in-place type web without minting a home).
4. CreateStatRow: BANK at 83.24. Do not re-enter without (a) R2 store-value authorization or
   (b) an IRO-trace round. The is_name_mode and stat_type axes are both closed with laws.
