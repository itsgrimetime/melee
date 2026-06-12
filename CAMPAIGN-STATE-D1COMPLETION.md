# Campaign State: mndiagram.c TU-COMPLETION (Driver 1)

Worktree: `/Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign`
Branch: `claude/mndiagram-tu-completion` (fresh from consolidated main campaign branch).
TU status at start: 35/45 matched.
Mode: AUTONOMOUS (orchestrator makes the calls; ONE question per iteration).

PROTECTED (hard stop, pre-commit hook): every matched fn in all three mndiagram TUs,
plus parked InputProc (98.67), 80242C0C (96.95), HandleInput (97.46). DO NOT touch
the walled pair {InputProc, 80242C0C}. DO NOT touch the permuter.

---

## ITERATION 1 (2026-06-11, driver 1) — OPENING MAP of mnDiagram_8024227C (NO BUILDS)

### Target
`mnDiagram_8024227C(void* arg0, s32 arg1, s32 arg2, u8 arg3)` — mndiagram.c:2374,
size 0x538 (1336B). The TU's biggest gap. The per-cell DRAW DISPATCHER: for the
column-header cell (var_r30==0xA) and each grid cell, resolve the fighter/name id
via count + find-walk, compute a stat (SumFalls / TotalKOs / summed vs_kos /
summed fighter_kos), and call `mnDiagram_80241E78(gobj,(u8)col,(u8)row,value)` to
draw. Called by OnFrame (2014), 802427B4-region callers (2275/2290), and
80240D94-region callers (2948/2961). `is_name=arg3` selects name-grid vs
fighter-grid; `var_r30` is the outer row index (0..0xA, with 0xA = header row).

### STEP 1 — BASELINE (clean branch, default checkdiff, NO build)
| Anchor | Value |
|--------|-------|
| Match (fuzzy) | **87.84%** |
| Opcode similarity | 24.0% (POISONED — see framing) |
| Line edit sim | -29.6% / 433 instrs (POISONED) |
| Line delta | **10 — TARGET has MORE** (expected 366, current 356) |
| Hunks | 10 |
| Classification | **control-flow-source-shape** |
| diagnostic_pad_stack | 32 (PAD_STACK(32) at line 2412) |
| Prior attempts | 16 recorded; ledger best 89.6% (#12); current committed 87.84%; no-progress streak 4; current source == attempt #17 fingerprint (4th time here) |

checkdiff machine-flags:
- "control-flow/source shape differs: branch shape differs before downstream operand,
  stack, or relocation noise"
- "call shape differs; check prototypes, return types, and inline boundaries"
- "1 stack-slot line; 50 data/symbol reloc lines; 29 register-only after normalization"

### CRITICAL framing: the 24% opcode similarity is a SHIFT ARTIFACT, not 76% structural mismatch
The diff aligns 1:1 from +000 to +0bc (prologue + first name-find-walk body), then
ours and target DIVERGE in PROLOGUE INSTRUCTION COUNT (ours +2 prologue instrs from a
hoist) and the whole-function difflib alignment slips by the offset, painting every
subsequent line as a "diff". The real structure is identical (same do-loop, same
branch shape, same find-walks, same draw calls in the same order). Confirm: the +000-0bc
window aligns perfectly; +0bc/+0cc/+0e0/+0e8/+100/+114/+118... are EQUAL lines scattered
through. This is the SAME phenomenon the sibling 80242C0C campaign documented (checkdiff
paired view inflated by a small root); subtract the shift and the residual is small.

### STEP 2 — PRECISE MAP (the prologue divergence is the root)

**TARGET prologue (-160 frame, stmw r15,92(r1) = 17 callee-saves r15-r31):**
```
+018 addi r28,r3,0   ; gobj
+01c addi r27,r4,0   ; arg1
+020 addi r29,r5,0   ; arg2
+024 addi r31,r7,0   ; r31 = mnDiagram_804A0750 base (LO reloc here)
+028 addi r25,r26,16959  ; cap = 0xF423F
+02c clrlwi r20,r6,24 ; is_name = (u8)arg3
+030 li   r30,0      ; outer index
   -- bases NOT hoisted; computed in-block:
+054 add  r16,r31,r29 ; = &sorted_fighters[arg2]  (INSIDE name-walk? NB r29=arg2)
+140 add  r17,r31,r29 ; in-block
+21c add  r17,r31,r27 ; = &sorted_fighters[arg1] in-block
+2d4 add  r15,r31,r29 ; in-block
+3d0 add  r16,r31,r27 ; in-block
+498 add  r16,r31,r29 ; in-block
```

**CURRENT prologue (-160 frame, stmw r14,88(r1) = 18 callee-saves r14-r31 — ONE MORE):**
```
+018 addi r27,r4,0   ; arg1
+01c addi r24,r7,0   ; r24 = mnDiagram_804A0750 base (LO reloc here)
+020 addi r28,r5,0   ; arg2
+024 add  r22,r24,r28 ; <-- HOISTED &sorted_fighters[arg2]  (EXTRA)
+028 add  r23,r24,r27 ; <-- HOISTED &sorted_fighters[arg1]  (EXTRA)
+02c addi r31,r3,0   ; gobj
+030 addi r25,r26,16959 ; cap
+034 clrlwi r14,r6,24 ; is_name
+038 li   r30,0
   -- downstream uses cached r22/r23: e.g. +064 addi r20,r22,28; +218 addi r19,r23,28
```

#### THE ROOT MECHANISM — IRO_FindLoops LICM HOIST (identical to 80242C0C iter-4 wall)
Source lines 2504 + 2547:
```c
var_r16_5 = &assets->sorted_fighters[arg1_r];   // fighter name-grid find-walk base
var_r16_7 = &assets->sorted_fighters[arg2_r];   // fighter grid-cell find-walk base
```
- `assets` (line 2381, `= (mnDiagram_Assets*)&mnDiagram_804A0750`) is a function-top,
  NEVER-reassigned local; `arg1_r`/`arg2_r` (lines 2378-79) are NEVER-reassigned local
  copies of params. Both EADD operands are ABSENT from the OUTER `do{var_r30++}while`
  loop's killed set ⟹ IRO_FindLoops flags `EADD(assets, argN)` loop-invariant w.r.t.
  the outer loop and HOISTS both to the function preheader (+024/+028).
- Target computes each base IN-BLOCK per outer-loop iteration (the `add rX,r31,argN`
  scattered through the find-walk blocks).
- The two hoisted bases (r22, r23) must then stay LIVE across the entire outer loop ⟹
  ours burns the 13th... actually the EXTRA callee-save r14 (stmw r14,88 vs target
  stmw r15,92). The whole-function GPR renumber and the +2 prologue line delta both
  follow from this single hoist.

This is the EXACT mechanism + EXACT structural pattern the sibling 80242C0C campaign
named and cracked (CAMPAIGN-STATE-80242C0C.md iter-4 "THE LICM-DEFEAT LAW"): re-read
the base into its local INSIDE the loop body so the base joins the loop's killed set.

#### Secondary / cascade (all DOWNSTREAM of the hoist; not independent sites)
- **29 register-only paired lines:** whole-function GPR-rename cascade off the prologue
  placement. Same family as 80243434's pop-order cascade. Will re-roll if the hoist falls.
- **Extra callee-save (r14):** the frame consequence of the hoist (two long-lived base
  regs). Likely collapses to target's r15-r31 set when the hoist is defeated.
- **50 data/symbol reloc lines:** dominated by the BSS section-anchor ceiling
  (`mnDiagram_804A0750` vs `.bss.0`) on every assets reference. RELOC NOISE — do not chase.
- **1 stack-slot line:** PAD_STACK(32) frame-reservation diagnostic. Replace with natural
  C only AFTER the hoist lands (frame need will change).
- **Branch-shape flag:** the "branch shape differs before downstream operand" is the
  +0xA header-row dispatch / the find-walk goto structure aligning against the offset
  shift — verify it is NOT a genuine branch inversion after the hoist falls (LOW prob;
  the +000-0bc window shows identical branch forms `bne/beq/blt/bgt/bge`).

### STEP 3 — PRIOR-ATTEMPTS RECONCILIATION
- 16 recorded attempts, all `neutral`, no class/blocker/note recorded (the ledger does
  not store spellings; `attempts show` has no detail view). Match band: most at 87.8%,
  one dip to 83.8% (#9), peaks 89.0% (#11) and 89.6% (#12 — ledger best). Current
  committed source = attempt #17 fingerprint, 4th time here (the m2c `var_rNN` soup at
  87.84%).
- mismatch-db: NO patterns for "8024227C" (function-specific search empty).
- HISTORY NOTE (orchestrator) verified: the 64-entry interferer-truncation DLL fix and
  the comma-expr LICM win landed on the SIBLING 802427B4 (98.84), NOT here. The
  comma-expr law defeats LICM on DATA READS, not address computations (per
  80242C0C iter-3, comma on an address was REFUTED — MWCC optimizes through it). So the
  comma-expr lever is NOT the tool for this function's address hoist; the killed-set
  re-read law is.
- The current 89.6% ledger-best spelling is NOT in the committed source (committed is
  87.84%). Unknown what #12 did; not recoverable from the ledger. Treat 89.6% as the
  bar to beat, not a known recipe.
- **No recorded dead spelling matches the killed-set re-read approach** — the sibling's
  law was discovered AFTER these 16 attempts (80242C0C iter-4 was 2026-06-11). The
  killed-set re-read of the fighter bases is UNTESTED here.

### RANKED LEVER LADDER (for the next build iteration)
1. **[HIGHEST] Defeat the FindLoops hoist via the killed-set re-read law.** Re-read the
   assets base into a local INSIDE the relevant loop body so the `&sorted[argN]` EADD
   operands join the killed set. Two candidate spellings:
   - (a) Move `assets = (mnDiagram_Assets*)&mnDiagram_804A0750;` (or a fresh
     `u8* sorted = mnDiagram_804A0750.sorted_fighters;`) re-assignment to be the FIRST
     statement INSIDE the outer `do{var_r30}` loop body, and compute `var_r16_5/7` from
     that loop-local base. Mirrors 80242C0C iter-4 Build 2 (the WIN) exactly.
   - (b) If (a) over-kills (the name-arm passes `assets->sorted_fighters` directly to
     GetVisibleName*From at 2456/2463 — those are NOT hoisted as `&sorted[argN]`; re-read
     scope must not perturb them), scope the re-read to the fighter `else` branch only.
   GATE: confirm the two prologue `add` instrs DISAPPEAR and the bases appear in-block;
   expect the extra callee-save r14 to collapse and the cascade to re-roll. Watch the
   +2 line delta → 0.
   - NOTE on the sibling 802427B4 (98.84, matched-ish): it gets the in-block IV for free
     because its find-walk is the INLINED helper `mnDiagram_GetVisibleNameFrom` (the
     inline boundary converts the named-local invariant into an induction variable that
     FindLoops strength-reduces in-block — 80242C0C iter-4 Dump B). We may NOT rebuild
     the fighter helper here (the soup already byte-matches the walk body); the
     within-soup substitute is the killed-set re-read.
2. **[AFTER 1] Re-meter the cascade + callee-save count.** If the hoist falls but a
   register-rename residual remains, it is the post-hoist coloring cascade (re-roll);
   re-map with a FRESH difflib (strip regs + strip relocs) to see the true remaining
   sites. Do NOT chase individual GPR renames before the structure aligns (structure
   first, registers last).
3. **[AFTER 1] Replace PAD_STACK(32) with natural frame.** Only after the hoist lands
   (the frame need changes when r14 collapses). Per doctrine: real local array /
   address-taken local, not committed PAD_STACK. (sibling 80243434 ships `u8
   stack_obj[N]`; 80242C0C iter-5 shipped a natural decl-array arrangement.)
4. **[LOW / verify-only] Branch-shape flag.** Confirm no genuine branch inversion after
   the shift is removed; the +000-0bc window suggests there is none.

### Things NOT to chase
- BSS section-anchor reloc (`mnDiagram_804A0750` vs `.bss.0`) — ceiling noise (most of
  the 50 reloc lines).
- The 24% opcode / -29.6% line-edit numbers — alignment-shift artifacts; meaningless
  until the +2 prologue delta is fixed.
- Whole-function GPR renames as individual sites — one cascade off the hoist.
- comma-expr on the address — REFUTED for address computations (80242C0C iter-3).

### DUMP BUDGET: 0/3 used this iteration (pure map, no builds, no dumps — the mechanism
is read directly from the disasm + confirmed identical to the sibling's dump-proven wall).
A retro frontend dump (`debug retro dump ... -f mnDiagram_8024227C --phases frontend`,
read `iro-trace.txt` for `Found loop invariant:` + `Killed in loop:`) would confirm the
two hoisted EADDs before the first build — recommended as STEP 1 of the next iteration
if a build of lever 1(a) does not immediately drop the prologue `add`s.

---

## 95-99 CLUSTER ANCHOR TABLE (one checkdiff line each; map-only, NO maps yet)

| Fn | Fuzzy | Opcode | Δ | Hunks | Classification | Notes |
|----|-------|--------|---|-------|----------------|-------|
| OnFrame | 99.72 | 100.0 | 0 | 9 | backend-ceiling | all paired diffs register-token-only; 9 instrs/sim 94.4. Pure coloring ceiling. |
| 802427B4 | 98.84 | 100.0 | 0 | 26 | stack-layout | opcode identical; 2 stack-slot lines. (THE sibling — comma-expr+interferer-trunc already landed; near-ceiling.) |
| 8023FC28 | 97.82 | 100.0 | 0 | 15 | data-symbol-or-relocation | opcode identical; 2 data/symbol reloc lines. Likely BSS-anchor ceiling noise. |
| 802417D0 | 97.73 | 99.5 | 0 | 27 | indexed-struct-pointer-materialization | 56 register-only lines; volatile target r0. Coloring cascade off a struct-ptr materialization. |
| CursorProc | 98.57 | 99.3 | 1 | 7 | inline-boundary-toolchain-artifact | exp 274/cur 275; call-shape flag. Δ1 + low hunks = a small inline-boundary lever. |
| 80240D94 | 97.35 | 75.0 | 2 | 1 | inline-boundary-toolchain-artifact | exp 417/cur 419; ONLY 1 hunk but opcode 75% + Δ2 = a real structural inline-boundary gap (1404B, the cluster's 2nd-biggest). |
| 80241E78 | 95.14 | 96.5 | 0 | 37 | signature-type-mismatch | THE DRAW CALLEE 8024227C calls. call-shape flag; 1 stack-slot; 37 hunks. Δ0 but opcode 96.5 = a type/cast or inline-shape gap. |

### RECOMMENDED FOLLOW-ON ORDER (after 8024227C)
1. **80241E78 (95.14, signature-type-mismatch).** Lowest %, and it is the DRAW CALLEE of
   8024227C — understanding its signature/cast gap may also inform the (u8) cast forms at
   8024227C's call sites. Δ0 + opcode 96.5 = a tractable type/cast lever (the cross-campaign
   cast-restoration class). Highest structural yield in the cluster.
2. **80240D94 (97.35, inline-boundary-toolchain-artifact).** Opcode 75% + Δ2 = a genuine
   structural inline-boundary gap (not a coloring ceiling), 1404B. The 1-hunk/Δ2 signature
   suggests ONE missing inline or call-shape choice. Good structural target.
3. **CursorProc (98.57, inline-boundary-toolchain-artifact).** Δ1, 7 hunks — a small,
   well-bounded inline-boundary lever. Cheap to attempt.
4. **802417D0 (97.73, indexed-struct-pointer-materialization).** 56 register-only lines —
   likely a coloring cascade off a struct-pointer materialization root; medium difficulty,
   may need a materialization lever (cf. memory [[reread_field_materializes_arg_register]]).
5. **8023FC28 (97.82, data-symbol-or-relocation).** Opcode 100%, only 2 reloc lines —
   probably BSS-anchor ceiling noise; LOW yield, verify-then-park.
6. **802427B4 (98.84, stack-layout).** Opcode 100%, 2 stack-slot lines — near-ceiling
   sibling; already heavily worked. LOW yield.
7. **OnFrame (99.72, backend-ceiling).** Pure register-token coloring ceiling; LOWEST
   yield — likely a true ceiling. Park.

Structural levers (best yield) cluster at the TOP (80241E78, 80240D94, CursorProc);
coloring/reloc ceilings (OnFrame, 8023FC28, 802427B4) at the bottom.

---

## ITERATION 2 (2026-06-11, driver 1) — THE HOIST FELL + WALK-SHAPE + CAST MODEL (87.84 -> 94.32)

### Build ledger (4 builds + in-slot respins; 3 commits; 1 retro dump)

| Build | Edit | Fuzzy | Verdict |
|-------|------|-------|---------|
| 1 | per-OUTER-loop `sorted = mnDiagram_804A0750.sorted_fighters;` + 8 use sites | 87.23 | **MISS — placement too shallow.** Prologue adds remained; frame grew. |
| dump | `debug retro dump --phases frontend` on Build-1 source | — | **MECHANISM PINNED:** round-1 FindLoops kill-gates the EADDs at the OUTER loop (sorted killed) but hoists them out of the INNER loops (sorted not killed there) into CSE temps (`@1688` at LoopDepth-1 preheader, survives to iro-61); the BACKEND then lifts the temp (operands prologue-invariant) to +024/+034. Target's adds are IV BASE SETUPS (feed walk pointers redefined in-loop = unliftable) — no shared temp may exist. |
| **2** | re-read moved INSIDE each of the 3 inner cell-loop bodies | **89.41** | **COMMITTED 0d83e28f6 — THE HOIST FELL.** Prologue adds gone; in-block `add` at +054 family (register-only); frame -160 both; line delta 10 -> 9. |
| **3** | (a) name-helper tail = PROVEN GetVisibleNameFrom idiom `p = sorted; p += idx; return p[0x1C];` (add+lbz-28 at 3 sites; 4 fetch spellings refuted: `sorted[idx+0x1C]` / `(sorted+idx)[0x1C]` = addi+lbzx int-domain reassociation; struct-field = CSE lbzx; single-stmt p2-copy = folds); (b) fighter helper REWRITTEN as rotated `while (remaining >= 0)` + `==0`-inside + breaks (m2c goto-soup defeats MWCC while-rotation: top-check+blt+b-back vs target b-to-bottom-check+bge-back); called at ALL 3 fighter sites (0xA call restored; BOTH raw soups deleted); (c) col TotalKOs m2c loop -> existing `mnDiagram_SumFighterKOs` inline (its `(u8) i` index = retail's fused rlwinm; cap stays at caller per name-arm architecture) | **94.37** | **COMMITTED b09ddbd1e.** Classification control-flow-source-shape -> signature-type-mismatch; opcode 24 -> 90; delta 9 -> 2. |
| **4** | CAST MODEL: name helper returns int; `var_r0_2`/`var_r23`/`var_r17_6` -> s32 (int-ness defeats byte-provability elision so every (u8) use emits retail's clrlwi: +278 assignment, +288 TotalKOs param, +32c PersistentNameData param, +428 SumFighterKOs param); fighter helper STAYS u8-return (var_r24 u8 home takes lbzx direct + fused rlwinm — int-return poisons it both ways); 0xA arms DIRECT-NEST the cursor helpers into SumNameFalls/SumFighterFalls (m2c temps var_r0/var_r21 dropped); re-read spelled `sorted = (u8*) assets;` (kill intact + NAMED reloc restored, reloc-paired 32 -> 0, frame -8); PAD_STACK 32 -> 24 (diagnostic) | **94.32** | **COMMITTED 90de0b888.** **Opcode-stream delta 0 (334 v 334)**; frame group stwu -160 / stmw r15,92 / epilogue BYTE-EQUAL; callee-saves match. (Fuzzy -0.05 vs Build 3 = cascade noise; structurally strictly superior.) |

Protected verified after each commit: 802437E8/80243434 match=true; InputProc 98.67; 80242C0C 96.95; HandleInput 97.46. Build RC=0 each time.

### LAWS BANKED (new, this function)
1. **Killed-set placement law (extends sibling iter-4):** the re-read must sit at the SAME loop depth as the EADD uses. One level too shallow and round-1 FindLoops still hoists out of the inner loops into a CSE temp, and the BACKEND (not IRO) finishes the lift to the prologue — the final IRO IR can look correct (adds at LoopDepth 1) while the emitted code is hoisted. Target adds = per-inner-iteration IV setups.
2. **Re-read spelling vs reloc form:** `sorted = (u8*) assets;` (cast-copy of the once-materialized address-of local) keeps the kill AND the named-symbol HA/LO reloc; direct `mnDiagram_804A0750.sorted_fighters` / `(u8*) &mnDiagram_804A0750` re-reads flip MWCC to .bss.0 section-anchor relocs (32 paired-line noise); the member-deref form `assets->sorted_fighters` is the only one that damages allocation (-3.86pp, re-rolls into r14).
3. **m2c goto-soup defeats while-rotation:** the target rotated-loop shape (`b` to bottom check, `bge` back) requires a real `while` + `break`s; label/goto renderings emit top-check + `blt`-exit + `b`-back. The fighter-cursor find-walk was therefore re-helperized (one inline, 3 call sites) — REVERSES the sibling 80242C0C's "soup matches, helper rejected" verdict for THIS function (their target was the unrotated form; ours is rotated).
4. **int-vs-u8 home decides clrlwi emission (sharpens the InputProc law):** an int-typed home makes EVERY (u8) use site emit clrlwi (no byte-provability); a u8 home lets MWCC elide redundant masks. Map target masks site-by-site: assignment-mask = u8 home + int RHS; use-masks-only = s32 home + u8 params; no masks anywhere = u8 home + u8-returning producer.
5. **Tail fetch via existing-web reassignment:** `p = sorted; p += idx; return p[0x1C];` (two statements, existing walked local) materializes add+lbz-disp; ALL single-expression spellings reassociate or CSE away.

### RESIDUAL (post-90de0b888: 94.32 fuzzy / opcode 93.7 / delta 0 / 81 hunks / 175 register-only)
1. **li-vs-copy trio** (+10c/+360/+39c): target inits the count-loop pair `li count,0; addi k,count,0`; ours two `li`. = the sibling's zero-coalesce class (k=count refuted there; CHAINED `k = count = 0` refuted HERE — folds). NOTE: GetNameTotalKOs's INLINE emits the same li+copy for its `total=0; i=0` (+280/+284) — the class lives inside inline expansions too. mnDiagram_CountUnlockedFighters exists but is #pragma dont_inline (real call at 2309/2863) — NOT these loops' source. Lever not found despite 2 spellings; banked, cascade-watch.
2. **Two one-slot inline-scheduling transpositions:** +284/+288 (param-mask vs inline `i=copy` init order at the GetNameTotalKOs expansion); +470/+474 (addi). Count-neutral; inline-boundary scheduling family.
3. **Register-rename cascade** (~175 lines; checkdiff names callee-save swap r29<->r30). Re-rolls on any structural land.
4. **PAD_STACK(24)** — diagnostic; frame group byte-equal at -160 / stmw r15,92. Natural-frame replacement pending (24B; sibling precedents `u8 stack_obj[N]` + `(void)&`).
5. Reloc: SOLVED (named symbol, 0 reloc-paired lines).

### PENDING-REVIEW (community-guideline risk)
- **PAD_STACK(24) committed as diagnostic** (90de0b888) — doctrine says do-not-ship; natural-frame pass pending. Flagged for replacement before any PR.
- `sorted = (u8*) assets;` x3 — unusual but semantically clean (assets IS the sorted_fighters base; the struct documents the overlay). Reviewer may prefer `assets->sorted_fighters` — that spelling costs -3.86pp (allocation re-roll); keep the cast-copy, comment it if questioned.
- var_r0_2/var_r23/var_r17_6 retyped s32 holding u8 values — matches retail codegen; m2c var_rNN naming retained throughout (a naming pass is cosmetic and free, recommended before PR).

### NEXT-ITERATION QUEUE
1. Natural-frame: replace PAD_STACK(24) (try `u8 stack_obj[24]` + (void)& first; meter slot positions).
2. Cascade attack: with delta 0 + frame matched, the 175 register-only lines are the LAST family — candidates: decl-order nudges (the decl list is still m2c-alphabetical), `debug target match-iter-first -f mnDiagram_8024227C --regs gpr-volatile,r0` (checkdiff's own suggestion), force-phys r14-r17 probes (diagnostic only).
3. The 2 transpositions + li-vs-copy trio: cascade-watch (may fall with the cascade).
4. 95-99 cluster follow-on per iteration-1 ranking (80241E78 first — its signature-type-mismatch class is exactly what the iteration-2 cast model addresses; the laws transfer directly).

