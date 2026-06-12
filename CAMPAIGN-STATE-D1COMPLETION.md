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

---

## ITERATION 3 (2026-06-11, driver 2) — 80241E78: CLASSIFICATION IS A FALSE FLAG; GAP = PURE data↔row CALLEE-SAVE PERMUTATION (95.14, NO CHANGE)

### THE ONE QUESTION — ANSWERED: **NO.** The iteration-2 cast model does NOT close 80241E78.
The "signature-type-mismatch + call-shape" classification is a **difflib alignment artifact**, not a real type/cast/call-shape gap. There are **no mask sites and no call-shape divergences to address**. Proven below.

### DECISIVE EVIDENCE — the C is already structurally perfect (NORMALIZED DIFF = IDENTICAL)
Disassembled OUR object (`build/GALE01/obj/melee/mn/mndiagram.o` via `build/tools/dtk elf disasm`) and the TARGET (`build/GALE01/asm/melee/mn/mndiagram.s`, dtk disasm of orig DOL, lines 3833–4115). Normalized BOTH streams (strip addr/byte prefix; `rNN→rR`, `fNN→fF`; strip `@sda21/@ha/@l`; immediates→IMM; labels→LBL; `<sym>`→SYM) and `diff`'d:
- **257 lines each, ZERO diff.** Same opcodes, same operand structure, same call sequence, same instruction count, same scheduling — modulo register numbers + reloc targets + immediates.
⟹ The entire 95.14→100 gap is a **pure register-coloring cascade**. The 37 hunks / 44 "register-only" / 11 "data/symbol" / 1 "stack" / "call shape differs" lines are ALL the difflib slipping by the swap offset (exactly the iter-1 framing phenomenon, now PROVEN by object-level normalization, not inferred).

### THE ROOT: data↔row swap r25↔r26 (col=r27 and arg3=r23 are pinned-correct in BOTH)
- TARGET: `lwz r25,44(r3)`=**data**→r25; `addi r26,r5,0`=**row(arg2)**→r26; `clrlwi r30,r26,24` = `(u8)row` from r26.
- OURS:   `lwz r26,44(r3)`=data→r26; `addi r25,r5,0`=row→r25; `clrlwi r30,r25,24` from r25.
- **Only data and row swap r25↔r26.** Everything downstream (`stfs f0,56(rN)`, `mr r3,rN`, `lwz r0,20(rN)`, `lwz r3,52(rN)`, the fmadds f28-vs-f27, the stfs f26/f27/f28 trio) re-rolls off this one swap + its FP-coloring shadow.

### MECHANISM (GPR COLORGRAPH, debug dump confirms the swap is REAL not a debug artifact)
`build/mwcc_debug_cache/melee/mn/mndiagram.txt` (COLORGRAPH DECISIONS class=0, n_nodes=100): the debug compiler **reproduces OUR swap** (`lwz r26,44(r3)` / `mr r25,r5` in AFTER REGISTER COLORING) — so this is a genuine source-driven coloring outcome the debug compiler shares (NOT the "debug colors correctly, retail diverges" invisible class of [[reread_field_materializes_arg_register]]'s sibling). Nodes pop DESCENDING-ig and fresh-dispense r31→r30→…: `col`=ig63→r27, `data`=ig58→r26, `row`=ig47→r25. **data(58) ALWAYS pops before row(47)** ⟹ data takes the higher reg r26. TARGET needs row→r26, i.e. **row's ig must exceed data's (58)**. row's ig sits at 47 — BELOW the find-walk temps (ig 48–57 = the `data->jobjs[N]` loads + GetTranslation calls, lines 2340–2353) — because **row is first-used (line 2357, `(f32)row`) only AFTER those loads, and row's value cannot be produced before `data` in this dataflow** (every float input derives from `data->jobjs[...]`). The swap is pinned by dataflow order, not by any movable spelling.

### Build ledger (4 builds, 0 commits, all reverted; 8024227C floor 94.32 untouched throughout)
| Build | Edit | 80241E78 | 8024227C | Mechanism check / verdict |
|-------|------|----------|----------|---------------------------|
| 1 | `Diagram* data;` moved to FIRST-declared local | 95.14 | 94.32 | **INERT.** Pointer-local decl order does NOT touch the param-derived data/row node ig. (Refutes "reverse-decl flips this pair.") |
| 2 | `1.0f`→`0.4f` at lines 2358 + 2371 | 95.14 | 94.32 | **INERT — and a key finding:** the object loads `mnDiagram_804DBFA0` (=0.4f, 0x3ECCCCCD) at the `row_offset_adj`/`col>=7` sites REGARDLESS of the source literal; our `1.0f` pools to `mnDiagram_804DBFB4` (0x3F800000) which 80241E78 NEVER references. ⟹ the literal at 2358/2371 is **folded/dead w.r.t. these instructions** (the matching 0.4 comes from the shared-constant fold, not this expression). NOT a lever; the apparent `@1519`/named-symbol "data-symbol" diff in checkdiff was a slip artifact (object already uses the named 804DBFA0, byte-equal to target). |
| 3 | move `mn_GetDigitCount(arg3)` AFTER the col/row offset computes | **89.19** | 94.32 | **REGRESSION −5.95.** The call MUST stay before the offsets — `digit_count`/r27 reuses col's reg at that exact point; reordering breaks the reuse. Confirms current call placement is correct (and that the call is NOT mis-scheduled — refutes any "call-shape" reading). |
| 4 | drop `u8 col`/`u8 row` locals; use `arg1`/`arg2` directly at all 6 sites | 95.14 | 94.32 | **INERT.** MWCC treats the local-copy and direct-param forms identically (the copies were pure aliases); arg2's node identity unchanged. Param-vs-local homing is NOT the lever. |

Protected sweep after restore-to-committed: 802437E8=100, 80243434=100, InputProc=98.67, 80242C0C=96.95, mnDiagram2_HandleInput=97.46, 8024227C=94.32, 80241E78=95.14. Build RC=0. Tree clean, HEAD=259dca914.

### LAWS (confirmed / extended)
1. **Classification-vs-reality law (NEW, sharp):** checkdiff's `signature-type-mismatch` + "call shape differs" banner can be a **pure difflib artifact** of an upstream callee-save swap; the offset slip re-renders equal instructions as "call-shape"/"data-symbol"/"register-only" diffs. **Object-level normalized diff (dtk disasm both sides; strip reg#/reloc/imm/label) is the authoritative structural verdict** — run it BEFORE trusting the classification on any swap-cascade function. Here it returned 0 diff over 257 lines. (Generalizes the iter-1 "24% opcode = shift artifact" framing to a reproducible procedure.)
2. **ig-pinned-by-dataflow law (extends InputProc band model):** a callee-save swap between a loaded pointer (`data`, high ig) and a param copy (`row`, low ig) is **structurally unmovable** when the param cannot be first-used before the pointer's loads (all the param's consumers derive from the pointer). Decl-order (B1), literal-value (B2), and param-vs-local (B4) are all INERT against it; call-reorder (B3) regresses. Matches the [[mwcc_ignode_ordering_ceiling]] / clean-callee-save-PERMUTATION-byte-identical class. NOT a missing C lever — characterized as dataflow-pinned ig ordering; the function stays in the pool (permuter-territory only, and permuter is FENCED this branch).
3. **Folded-literal caution (NEW):** a float literal can be DCE'd/shared-folded such that editing it changes NO bytes (the matching constant arrives via the TU-wide constant pool). Verify a literal is load-bearing (object reloc points at ITS pool slot) before treating it as a lever. (80241E78's `1.0f`/`0.4f` proven inert.)

### RE-ROLLED RESIDUAL CENSUS (80241E78 @ 95.14, committed source)
- **Sole family: data↔row callee-save swap r25↔r26** (+034 lwz, +02c addi, every downstream rN use) + its **FP-coloring shadow** (fmadds f31,f0,f28-vs-f27 at +1e8/+274; stfs f26/f27/f28 trio at +2f4/+368/+16c…). One root, ~44 register-only paired lines.
- NO structural / call-shape / scheduling / instruction-count residual (normalized diff = 0).
- NO data-symbol residual (object uses named 804DBFA0/804DBF98/804DBF78 byte-equal to target; the "11 data/symbol" lines are slip artifacts).
- Lever NOT FOUND despite: pointer-decl-first, literal-value, call-position, param-direct (4 builds) + GPR/FPR colorgraph mechanism analysis. row's ig is dataflow-pinned below data's.

### TEACHING FOR THE CLUSTER {80240D94 97.35, CursorProc 98.57, 802417D0 97.73, 8023FC28 97.82}
80241E78 did NOT reach 100, but its dissection yields a transferable triage gate for the rest of the cluster (all carry inline/coloring-flavored classification banners):
- **Run the object-level normalized diff FIRST on each** (the iter-3 procedure). If it returns ~0, the banner is a swap-cascade artifact and the function is a coloring ceiling (park or permuter-only), NOT a structural/cast target — do NOT spend the iter-2 cast/mask budget on it.
- 8023FC28 (opcode 100, 2 reloc lines) and 802417D0 (56 register-only, "indexed-struct-ptr-materialization") are the strongest candidates to ALSO be pure-coloring artifacts — normalized-diff them before any source edit.
- Of the cluster, **80240D94 (opcode 75%, Δ2, 1404B)** is the one whose classification is LEAST likely to be a swap artifact (75% opcode + Δ2 ≠ a pure register swap, which preserves opcode count) — its normalized diff should show REAL structural delta. **Recommended next target = 80240D94** (genuine inline-boundary structural gap), with the normalized-diff gate applied first to confirm.

### PENDING-REVIEW: none added (no source retained; all 4 builds reverted).

---

## ITERATION 4 (2026-06-11, driver 2) — ITER-3 ERRATA + CORRECTED LAW-1 GATE SWEEP + 80240D94 TOP RUNG (3 spellings refuted)

### ERRATA for ITERATION 3 (critical — read before trusting iter-3's evidence section)
**The iter-3 "object-level normalized diff" compared the TARGET WITH ITSELF.** `build/GALE01/obj/**`
is the TARGET object tree (objdiff.json: `target_path=build/GALE01/obj/...`, `base_path=build/GALE01/src/...`).
The "0 diff over 257 lines" proof was circular. **LAW 1's PROCEDURE is corrected: disassemble
`build/GALE01/src/melee/mn/<tu>.o` (OURS) vs `build/GALE01/asm/melee/mn/<tu>.s` (target).**
Consequences, re-verified against the TRUE object:
- **80241E78 corrected residual: FULLNORM-DIFF = 20, NOT 0.** The r25<->r26 data/row swap (29+8 sites)
  and FP perm (f26/f27/f28 cycle) are real AS STATED, but there is ALSO a ~20-line structural/scheduling
  window in the GetDigitCount/float-setup region: ours defers the y_offset fsubs PAST the call (raw load
  held in callee-save f30, fsubs into volatile f1 after; target: load to volatile f0, fsubs into
  callee-save f26 BEFORE the call). Iter-3's "no structural residual" claim is RETRACTED; the wall
  characterization must include this window. Builds 1-4 of iter-3 stand (metered via report.json).
- **Iter-3 LAW 3 (folded-literal) RETRACTED.** Our object's `@1519` = 0x3F800000 = **1.0f**; the target
  loads named `mnDiagram_804DBFA0` = **0.4f** at the same site. Build-2's inertness = fuzzy%'s
  insensitivity to anonymous-pool VALUES (reloc-identity penalty equal either way), NOT constant folding.
  **The committed source is semantically divergent from retail: `row_offset - 1.0f` (line 2358) and
  `+ 1.0f` (line 2371) should be `0.4f`.** PENDING-REVIEW: function is fenced this round; the value fix is
  match%-neutral (proven, iter-3 Build 2) and behavior-correcting — apply in the queued 80241E78 round,
  and try `extern const f32 mnDiagram_804DBFA0` named reference for the data/symbol reloc lines.

### GATE PARTITION TABLE (corrected procedure; read-only; baseline = 357fa8723 build)
| Fn | % | instrs tgt/our | FULLNORM | Verdict | Root / swapped pair |
|----|-----|-----------|----------|---------|---------------------|
| 8023FC28 | 97.82 | 108/108 | **0** | **ARTIFACT** | whole-web callee-save rotation rooted at the assets-base materialization (TGT `addi r29,r3,&804A0750` vs OUR `addi r31,...`; 48 reg sites) + ours emits `.bss.0` section-anchor reloc vs target NAMED symbol — iter-2 LAW-2 spelling lever may fix the reloc lines (endgame round) |
| 80240D94 | 97.35 | 351/**353** | **8** | **STRUCTURAL Δ+2** | ROOT B: `(u8) arg2` mask-pair CSE-cached (clrlwi r22 + addi r3,r22 + mr r3,r22) vs target per-site `clrlwi r3,r29,24` x2 at the two GetNameText calls (src 1807/1822); ROOT A: `tbl = &803EE728` init emitted as `addi r0` (hoisted above stwu) + `mr r27,r0` vs target direct `addi r28` post-stmw |
| 802417D0 | 97.73 | 198/198 | **2** | **STRUCTURAL 1-site** | ours `clrlwi. r0,r0,24` (redundant re-mask as the test) vs target `cmpwi r0,0x0` after the single mask — int-vs-u8 TEST-home retype (LAW-4 family), likely roots the 96-site coloring cascade |
| OnFrame | 99.72 | 160/160 | **0** | **ARTIFACT** | single-pair r28<->r29: the `lwz rX,0x2c(r30)` user_data ptr loaded mid-function (9 sites) — same class as 80241E78's data/row swap |
| 802427B4 | 98.84 | 225/225 | **0** | **ARTIFACT** | callee-save rotation: arg homes shift (TGT r26/r27 vs OUR r27/r28) + assets-base TGT r31 vs OUR r25 (86 reg sites) |
| CursorProc | 98.57 | 221/**222** | **3** | **STRUCTURAL Δ+1** | target `lhzu` (load-half-update) vs ours `addi`+`lhz` 2-instr form, +40 immediate-cascade lines off the updated base — InputProc §4 lhzu family; HERE adopting lhzu SHORTENS ours to the target count (unlike InputProc where it widened Δ) |

### PHASE 2 — 80240D94 build ledger (4 builds: 3 levers + restore; 0 commits; floor 94.32 untouched)
| Build | Edit | Fuzzy | FULLNORM | Verdict |
|-------|------|-------|----------|---------|
| 1 | per-block `u8 name_id = (u8) arg2;` reassignment x2 | 97.32 | 8 | **FOLDED** — copy-prop unified both assignments back into ONE cached mask web (r21); destination kills don't split the RHS VN |
| 2 | `static inline mnDiagram_SetPopupNameText(text, slot)` with `(u8) slot` INSIDE | 97.350426 (byte-identical to baseline) | 8 | **FOLDED** — inline param copies are fully transparent to VN/copy-prop (refines iter-2's inline-node evidence: init NODES survive expansion, pass-through params do NOT) |
| 3 | `(u8) (0, arg2)` comma at site 2 | 91.82 | 20 (361 instrs) | **SPLIT THE MASKS but over-perturbed** — two per-site `clrlwi r3` appeared and the cache web died, BUT arg2 re-homed (reads via r0, +8 instrs). Comma = VN-splitter that also breaks operand homing; wrong tool |
| 4 | restore committed source | 97.350426 | 8 | sweep green: all 13 protected/tracked fns at baseline |

### MECHANISM BANK (80240D94 ROOT B — precise wall statement)
Target's two masks ⟹ the two AND(arg2,0xFF) nodes carried DIFFERENT value numbers in the original IR.
In-TU existence proof that same-path per-site masks DO occur: committed 8024227C emits `clrlwi r3,r16,24`
TWICE 4 instrs apart (SumNameFalls inline; r16 = IRO-PROMOTED loop-carried counter — region-renamed
per the InputProc band model). A plain never-killed s32 param = ONE VN ⟹ IRO CSE caches across the 3
intervening calls (callee-save + 2 transfer instrs) — costlier in instructions yet chosen; CSE here is
not cost-modeled. Splitter requirements (discovered empirically): change the AND's VN withOUT changing
arg2's home class. Refuted: local-reassign + inline-param (fail VN-split), comma (splits but re-homes),
`& 0xFF` (same VN), `(u8)(s32)` (identity-folds), self-assign (DCE'd), memory round-trip (adds loads).
**Lever not found despite 3 built spellings + 4 analysis-refuted shapes.** Function stays in the pool.
ITERATION-5 HYPOTHESIS (new evidence): the fn carries PAD_STACK(24) — per doctrine, missing
locals/inline structure. The m2c `{ f32 y; f32 z; }` scoped pos-blocks repeat 6x and suggest per-block
helper locals in the original; missing per-block homes would change BOTH the VN landscape (ROOT B) and
the frame/decl picture (ROOT A + the r21..r24 home rotation). A PAD_STACK-elimination reconstruction
(find the real 24B of locals / the block helper) is the recommended dedicated round for this fn.
ROOT A note: sibling PopupAnimProc uses the IDENTICAL `tbl` decl-init spelling and emits the
direct-home `addi r28` ⟹ ROOT A is spelling-independent (scheduler/pressure-conditioned); expect it to
re-roll if ROOT B / the frame lands. No direct lever identified.

### ITERATION-5 RECOMMENDATION
1. **802417D0 retype (cheapest, 1 site):** route the tested value through an int home so the test emits
   `cmpwi` instead of the redundant `clrlwi.` re-mask (LAW-4 recipe; find the `if ((u8) ...)`-shaped test
   at the lhz 0x3c site). ≤2 builds; may re-roll the 96-site cascade.
2. **CursorProc lhzu (small, recipe exists):** pointer-walk spelling to fuse addi+lhz → lhzu
   (InputProc §4 documented the fusion fires with the right base-reg life; here it CLOSES Δ).
3. **80240D94:** dedicated PAD_STACK-reconstruction round (NOT single-lever; see mechanism bank).
4. ARTIFACT bucket {8023FC28, OnFrame, 802427B4} → register-endgame/permuter rotation; EXCEPT first try
   the iter-2 LAW-2 named-reloc spelling on 8023FC28 (that part is a source lever, not coloring).
5. The queued 80241E78 round must include the ERRATA items: 0.4f value fix + named-float-extern attempt
   + the fsubs-across-call window (now known structural — try computing y_offset into its consumer's
   shape, e.g. statement order around the mn_GetDigitCount call, BEFORE any register-endgame).

### PENDING-REVIEW (iter-4)
- **Committed 80241E78 semantic divergence (1.0f vs retail 0.4f)** at src lines 2358/2371 — fenced this
  round; fix is match%-neutral + behavior-correcting; apply in its queued round (see ERRATA).

---

## ITERATION 5 (2026-06-11, driver 3) — BOTH STRUCTURAL Δ TARGETS LANDED: 802417D0 + CursorProc to FULLNORM 0 (2 commits, 2 builds)

### THE ONE QUESTION — ANSWERED: **YES.** The 802417D0 test-home retype lands.
The iter-4 partition's verdict held exactly: the entire structural divergence was ONE site
(FULLNORM 2), ours `clrlwi. r0,r0,24` (re-mask-as-test) vs target `cmpwi r0,0x0`. The LAW-4
TEST variant closed it on the first build.

### Build ledger (2 builds, 2 commits, 0 reverts; floor 94.32 untouched throughout)
| Build | Fn | Edit | Site form | FULLNORM | % old->new | Δ | Verdict |
|-------|-----|------|-----------|----------|------------|---|---------|
| **1** | 802417D0 | Left-arrow merge test value routed through existing `s32 i` (was `u8 result`): `i = (u8) data->name_cursor_pos` / `i = (u8) data->fighter_cursor_pos`; `if (i != 0)` | `clrlwi. r0,r0,24` **-> `cmpwi r0,0x0`** | **2 -> 0** | 97.73 -> **98.0303** | 198/198 (unchanged) | **COMMITTED e8c3b0a5e** |
| **2** | CursorProc | `hovered_selection` (u16 @ off 2) read via pre-incremented `u16* hov=(u16*)&mn_804A04F0`: `col = *++hov >> 8`; `row = (u8)*hov` (was direct `mn_804A04F0.hovered_selection` x2) | `addi rN,base,2`+`lhz 2(base)` **-> `lhzu r0,0x2(r30)`** | **3 -> 0** | 98.57 -> **99.5158** | 222 **-> 221** = target (Δ+1 -> **Δ0**) | **COMMITTED d858e94ae** |

Protected sweep after EACH commit: 0 regressions. 802437E8/80243434=100, InputProc 98.6726,
80242C0C 96.9513, HandleInput 97.4605, OnFrame 99.7188, 8023FC28 97.8241, 8024227C 94.3234,
80241E78 95.1362, 80240D94 97.3504, 802427B4 98.8444. Build RC=0 both times. Tree clean, HEAD=d858e94ae.

### LAWS (confirmed / extended)
1. **LAW-4 TEST variant CONFIRMED + recipe sharpened (802417D0):** when two branch arms each
   emit `(u8)`-cast values (per-arm `clrlwi`) that merge into a `u8`-typed local tested `!= 0`,
   MWCC re-truncates at the merge (`clrlwi.` re-mask-as-test). Routing the merged value through
   an **int/s32 home** (each arm still emits its per-branch `(u8)` clrlwi cast) makes the merge
   value byte-provable so the compare is a plain `cmpwi r0,0`. The in-function Up-arrow
   (`i = ...>>8; if (i != 0)`) already demonstrated the int-home -> `cmpwi` form; reusing its
   `s32 i` for the Left arrow was the developer-natural fix (no new local). **Recipe: find the
   `if ((u8-local) != 0)` test whose value is assigned in both arms of an if/else; retype the
   merge home to int (or reuse an existing s32), keep the per-arm `(u8)` cast.**
2. **lhzu walking-pointer recipe CLOSES Δ here (CursorProc; confirms iter-4 partition + InputProc §4):**
   target reads a u16 field twice via a single base pointer that it pre-increments one element
   (`lhzu rD,2(rA)` = load-half-with-update: EA=rA+2 AND rA:=rA+2), re-reading at offset 0 after.
   Ours emitted the 2-instruction `addi &field`+`lhz disp(base)` form (the addi materialized
   `&field` into a dead reg = the Δ+1 extra instr). Expressing the access as a pre-incremented
   `u16*` (`hov=(u16*)&base; *++hov; ...; *hov`) makes MWCC select the update form. UNLIKE
   InputProc §4 (where the same fusion WIDENED Δ because the walking reg was clobbered downstream,
   blocking the count), HERE the walked pointer (r30) is free after the two reads, so adopting
   lhzu SHORTENS ours to the target count exactly (222 -> 221). **The §4 wall arithmetic is
   site-specific: adopt lhzu when the walking reg is dead after the field reads; refuse it when a
   downstream walk clobbers the reg (count would drop below target).** Semantics preserved:
   `(u16*)&mn_804A04F0` has [0]=cur_menu|prev_menu, [1]=hovered_selection; `++hov` -> &hovered_selection.
3. **The corrected LAW-1 gate procedure is sound + the `__assert`-reloc normalizer caveat (NEW):**
   the iter-4 errata gate (disasm OURS `build/GALE01/src/melee/mn/mndiagram.o` via `dtk elf disasm`
   vs TARGET `build/GALE01/asm/melee/mn/mndiagram.s`) returned FULLNORM 2 for 802417D0 and Δ+1 for
   CursorProc EXACTLY as the iter-4 partition predicted — the partition table is trustworthy. CAVEAT
   discovered: a naive normalizer that maps `0x...`->IMM but leaves quoted `__assert` string relocs
   (`li rN,"@1234"`) un-canonicalized INFLATES CursorProc's count to 151 (every assert-string line
   reads as a diff because ours renders the reloc as `"@IMM"` while target renders the named SDA
   symbol). Canonicalize ALL symbol/quoted-reloc operands to one token (regex `"[^"]*"`->SYM +
   named-addr `\w+_[0-9A-Fa-f]{6,}`->SYM) BEFORE diffing; then CursorProc FULLNORM = 0 (validated:
   same normalizer gives 802417D0=0 Δ0, 80240D94=Δ2 nonzero — discriminates correctly).

### PARTITION UPDATES (iter-4 GATE TABLE -> post-iter-5)
- **802417D0: STRUCTURAL 1-site -> RESOLVED-STRUCTURAL (FULLNORM 0).** Now 98.0303; the predicted
  96-site coloring cascade did NOT meaningfully re-roll on the flip (+0.30 only) — residual is a
  clean pure-coloring cascade (the test-form was the only structural divergence). Coloring-ceiling
  / permuter-territory from here (permuter FENCED this branch).
- **CursorProc: STRUCTURAL Δ+1 -> RESOLVED-STRUCTURAL (FULLNORM 0, Δ0).** Now 99.5158; residual is
  pure coloring (~0.48% to 100). The 3 STRUCTURAL targets of the partition are now 2/3 resolved
  (802417D0 + CursorProc); 80240D94 remains (Δ+2 mask-CSE wall + ROOT A, its dedicated PAD_STACK-
  reconstruction round still pending).
- ARTIFACT bucket {8023FC28, OnFrame, 802427B4} unchanged (PARKED, not this round).

### RESIDUAL RE-ROLLS (post-d858e94ae)
- **802417D0 @ 98.03:** sole family = the post-flip register-coloring cascade (callee-save renumber,
  FULLNORM 0 so no structural/scheduling/count residual). Permuter-only; FENCED.
- **CursorProc @ 99.52:** sole family = coloring cascade (FULLNORM 0, Δ0). The 2 commits removed
  the only structural divergences each function had. Both are now coloring ceilings.

### PENDING-REVIEW (iter-5)
- **CursorProc `u16* hov = (u16*)&mn_804A04F0; *++hov; *hov`** (d858e94ae) — the pre-increment walk
  is the idiom retail used (proven by `lhzu`), but a reviewer may find `*++hov` less readable than
  the field accessor. It is semantically identical and load-bearing for the match (the direct
  `mn_804A04F0.hovered_selection` form costs Δ+1 / the addi+lhz pair). Keep; comment if questioned.
  No new PAD_STACK, no semantic divergence (behavior byte-identical to the field reads).
- 802417D0 `i = (u8) data->name_cursor_pos` reusing `s32 i` for the Left-arrow test — clean (the
  Up-arrow already homes its test in `i`); no review risk.

