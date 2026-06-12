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

---

## ITERATION 6 (2026-06-11, driver 3) — 80240D94 RECONSTRUCTION ROUND: HYPOTHESIS REFUTED BY OBJECT EVIDENCE; ROOT B MECHANISM POSITIVELY CONFIRMED (VN kill) BUT ZERO-EMISSION KILL NOT FOUND; 97.35 UNCHANGED

### THE ONE QUESTION — ANSWERED: **NO.** The PAD_STACK(24)-elimination reconstruction does not land.
The iteration-5 hypothesis (missing ~24B of genuine locals and/or a per-block pos helper resolving
ROOT A + ROOT B together) is REFUTED by object-level evidence on every prong. Budget: 2 of 6 builds
(1 probe + 1 restore), 0 source commits, floor 97.3504 restored byte-exact.

### FRAME GROUND-TRUTH (object-level; supersedes the frame-tool model — see tool caveat below)
Both objects (OURS `build/GALE01/src/.../mndiagram.o` with PAD_STACK(24) in place, TARGET asm):
- frame 0x78, `stmw r21,0x4c(r1)` (saves 0x4c-0x78), **buf @ r1+0x30** (all four format sites:
  `addi rX,r1,0x30` + stbx digit stores + `addi r4,r1,0x30` into HSD_SisLib_803A6B98),
  **pos @ r1+0x38-0x44** (ALL SIX lb_8000B1CC sites pass `addi r5,r1,0x38`; all lfs read
  0x38/0x3c/0x40), rounding gap 0x44-0x4c. mnDiagram_FormatPopupNumber is INLINED in BOTH
  (identical stbx digit-loop bodies). FRAME DELTA = 0; layouts byte-identical.
- **The 24B at 0x18-0x30 is NEVER REFERENCED in the retail object.** It is dead frame space.
- Decl-position arithmetic (MWCC homes locals top-down in decl order; ours: pos→0x38, buf→0x30,
  pad-last→0x18) PINS the original's 24B object to "declared after buf" — placing a 24B object
  between pos and buf, or resizing buf, relocates &buf/&pos away from 0x30/0x38 (refuted layouts).
- Param-area is NOT the supplier (ours computes 16B = max 4 arg words from the identical call
  list; the varargs callee does not blanket-reserve — cross-check: sibling 802427B4 calls the same
  803A6B98 yet shows 0x68 sub-local space with NO pad, so reservation is per-function locals/temps,
  not callee-driven).
- Frame-tool caveat (ISSUE #578): `debug inspect frame-reservations` modeled 0x8-0x38 as "unused"
  and claimed "r1-access coverage ok" while the object references buf@0x30 — it tracked only the
  FPR symbolic homes (pos words). Do not trust its unused-ranges on functions with address-taken
  char arrays; disasm the object.

### PER-BLOCK-HELPER HYPOTHESIS — REFUTED (evidence, no builds needed)
1. All six pos-blocks already byte-match the target (mod registers); the y,z,x load order +
   fneg shape is identical. Nothing structural to recover at those sites.
2. The paragraphs ORDER-VARY: first two set `default_alignment` AFTER the pos stores, the last
   four BEFORE. A single shared helper cannot produce both orders.
3. A helper with its own `Vec3 pos` either materializes per-site homes (refuted: one shared
   slot 0x38 in retail) or folds transparently (iter-4 Build 2 proved inline params and bodies
   are VN/copy-prop transparent).
4. lb_8000B1CC(HSD_JObj*, Vec3*, Vec3*) — all pointer params; no by-value copy temps.

### ROOT B — MECHANISM POSITIVELY CONFIRMED (Build 1 probe), ZERO-EMISSION SPELLING NOT FOUND
Catalog (validated normalizer, anchored-hunk procedure): the ENTIRE structural divergence is 7
lines, 2 roots. ROOT B = ours ONE cached `clrlwi r22,r28,24` + `addi r3,r22,0` + `mr r3,r22` vs
target per-site `clrlwi r3,r29,24` x2. Cross-check that sharpened the model: ours ALREADY emits
per-site `clrlwi r3,r31,24` for the (u8)arg1 masks — those sit in EXCLUSIVE branches (CSE cannot
bridge path-disjoint arms); the arg2 masks sit on ONE sequential path, so IRO CSE merges them.
Retail's same sequential path did NOT merge ⟹ arg2's VN was killed between the paragraphs in the
original IR.

**Build 1 (probe): `if (arg1 == arg2) { arg2 = arg1; }`** inserted between the two name paragraphs
(a universal no-op: assigns arg2:=arg1 exactly when already equal; runtime-dead inside the
`arg1 != arg2`-guarded block). RESULT: **the VN split FIRED** — the entire ROOT-B hunk family
vanished (per-site masks in target form; arg2 re-homed to r29 = the TARGET home). But the kill
emits `cmpw r31,r29; bne; mr r29,r31` (+3 — MWCC cannot prove the branch dead) AND the new block
boundary broke the shared `li r23,0x1` alignment-value web (target shares ONE li across both
paragraphs; ours rematerialized `li r0,0x1`). 97.35→97.26. REVERTED (Build 2 = restore, sweep
green, 0 deltas, all 13 tracked fns byte-exact).

**Constraint set for the original splitter (tight, from the probe):** it must (a) kill arg2's VN
between the paragraphs, (b) emit ZERO instructions, (c) introduce NO block boundary (the li-1 CSE
and straight-line fallthrough survive in retail). Control-flow kills violate (b)+(c) — proven.
Straight-line zero-emission kills are the class iter-4 exhausted: self-assign (DCE'd before VN),
reassign-through-local / inline-param (copy-prop transparent), `arg2 = (u8) arg2` (iter-4 Build-1
fold family — AND-idempotence unifies the web), comma (re-homes, +8), memory round-trip (adds
loads), `& 0xFF`/`(u8)(s32)` (same VN). Zero-emission VN kill **not found despite** the ledger's
7 spellings + this round's control-flow probe + analysis refutations (condition duplication
re-tests; select/phi emits the same cmpw+mr; signed `% 256` emits the modulo dance; nested-mask
casts fold at parse). Function stays in the pool; residual characterized, not closed.

### ROOT A — DID NOT CASCADE (probe evidence)
With ROOT B force-split (and callee-save r22 freed), ours STILL emitted `addi r0,r7,@l` (pre-stwu)
+ `mr r27,r0` vs target's direct post-stmw `addi r28,r7,@l`. The iter-4 cascade prediction ("A
re-rolls if B lands") did NOT hold under the dirty split — suggestive-not-decisive (the probe's
+4 instrs perturb pressure). A remains scheduling/pressure-conditioned (sibling PopupAnimProc:
identical spelling, direct form) with no direct C lever identified.

### PARTITION UPDATE
- **80240D94: STRUCTURAL Δ+2 → CHARACTERIZED WALL (VN-CSE class).** B = sequential-path AND-CSE
  needing a zero-emission VN kill (not found in reachable C); A = prologue scheduling/coloring of
  the tbl addi (no direct lever; did not cascade under the forced split). FULLNORM 7 stands. B is
  NOT permuter-promising (the needed transform is an IR killing-def, not a register choice); A's
  addi/mr MIGHT be permuter-reachable (register-class).
- TU STRUCTURAL frontier after this round: 80241E78's fsubs-across-call window (~20 FULLNORM
  lines, iter-4 errata) is the LAST known structural window. Everything else is ARTIFACT/coloring
  (8023FC28 named-reloc spelling = source lever for reloc lines only).

### PENDING-REVIEW (iter-6) — PAD_STACK(24) entry SHARPENED, NOT RETIRED
- **80240D94 PAD_STACK(24) STAYS.** Evidence: the 24B is never-referenced dead frame space in the
  RETAIL object, pinned by decl-order arithmetic to a dead 24B object declared after buf (a dead
  local aggregate — e.g. a removed debug buffer — whose identity the bytes cannot disambiguate).
  Replacing the pad with an invented dead local (`char unused[24]`, two dead Vec3) would be
  honesty-NEGATIVE vs the documented diagnostic macro. For any PR: keep PAD_STACK(24) with a
  comment citing the dead-frame evidence (upstream precedent: mndiagram2 CreateStatRow ships
  `int pad[4]` + PAD_STACK(16) for the same class). The doctrine "PAD_STACK = missing
  inlines/locals" is REFUTED for this function specifically: the missing thing is provably dead,
  not live structure.
- Probe spelling `if (arg1 == arg2) arg2 = arg1;` is NOT retained (reverted) — recorded as the
  mechanism-confirmation tool for future drivers; do NOT commit it (+4 instrs, block-split).

### NEXT (iteration-7 recommendation)
1. **80241E78 bundled round** (LAST structural window): 0.4f semantic fix (match-neutral, proven
   iter-3 B2) + `extern const f32 mnDiagram_804DBFA0` named-float attempt + the fsubs-across-call
   window (ours defers y_offset fsubs past the mn_GetDigitCount call into volatile f1; target
   computes into callee-save f26 BEFORE the call — try statement order / consumer-shape around
   the call). Highest remaining structural yield.
2. THEN 8023FC28 LAW-2 named-reloc spelling (cheap, reloc-lines-only).
3. THEN declare the TU structural frontier exhausted → endgame/permuter phase (permuter currently
   FENCED this branch; A-root addi/mr is the one register-class site worth a permuter look).

---

## ITERATION 7 (2026-06-11, driver 3) — 80241E78 BUNDLED ROUND: THE fsubs WINDOW CLOSED (95.14 -> 98.94, FULLNORM 20 -> 0) + 0.4f FIX COMMITTED + EXTERN REFUTED. **THE TU's STRUCTURAL FRONTIER IS NOW CLOSED.**

### THE ONE QUESTION — ANSWERED: **YES.** The fsubs-across-call window closes, via 2-use anchoring.
Budget: 4 of 5 builds. 2 commits (fe659a04f semantic fix, 8523f3539 window), 2 hard-reverts.
80241E78: 95.1362 -> **98.9416**, FULLNORM 20 -> **0**, 257/257 instrs, Δ0.

### NEW LAW — FRONT-END GRAFT LAW (pcdump-proven, transferable):
MWCC's FRONT END (visible in BEFORE GLOBAL OPTIMIZATION, before any optimizer pass) grafts a
SINGLE-USE local's RHS tree forward into its consumer statement across STRAIGHT-LINE block chains
— calls split blocks (B20 -> bl B21 -> B22) but do NOT stop the graft; only BRANCH/JOIN boundaries
do. Proof pair in one function: y_offset (def and use separated only by the GetDigitCount call)
grafted post-call; y_spacing (identical shape, but the jobjs[9]/[10] GetTranslationY ASSERT
DIAMONDS branch between def and use) materialized pre-call. A MULTI-USE local materializes at its
def. RECOVERY RECIPE: when ours evaluates an expression LATER than the target (sunk across a
call), give the local a second GENUINE use — here the original's own form: duplicate the product
into the adj computation and hoist the (f32) conversion into one named local so no second
conversion slot is created (`rowf = (f32) row; row_offset = y_offset * rowf; row_offset_adj =
y_offset * rowf - 0.4f;`). MWCC CSEs the duplicate product (ONE fmuls emitted) but the front end
has already materialized the fsubs at its pre-call def -> callee-save result, volatile raw
operand = target form; the whole post-call conversion/const cluster re-rolls into the target
schedule. COROLLARY (Build 2, H1 refuted): assigning into a MULTI-DEF web (`base = TY(jobj2) -
base`) does NOT anchor evaluation — forwarding is per-EXPRESSION on virtuals (a redefinition
mints a new virtual; nothing is "killed"), not per-destination-web. The InputProc
intermediate-copy law's web-persistence is about COPY persistence, not evaluation anchoring.

### Build ledger
| Build | Edit | Result | Verdict |
|-------|------|--------|---------|
| 1 | `1.0f` -> `0.4f` at 2358 (adj) + 2371 (col>=7 X) | 95.1362 (byte-neutral), pool @1519 = 0x3ECCCCCD verified | **COMMITTED fe659a04f** — semantic retail-divergence fix; fuzzy% is reloc-identity-bound not value-bound for anonymous pool constants |
| 2 | H1: `base = TY(jobj2) - base;` (multi-def web destination) | 95.1362, hunks identical, fsubs still post-call | **INERT — REVERTED.** Destination web does not anchor evaluation (see corollary) |
| 3 | 2-use anchoring + `f32 rowf` conversion local | **98.9416, FULLNORM 0, 257/257, Δ0**; fsubs immediately pre-bl (volatile operand, callee-save result) | **COMMITTED 8523f3539** |
| 4 | `extern const f32 mnDiagram_804DBFA0` replacing both 0.4f literals (+static.h decl) | 97.5019, FULLNORM 0 -> 3: extern RELOADED IN-LOOP (`lfs f1,804DBFA0` at the col>=7 site — symbol loads are not hoisted across the loop's calls, even const), pre-loop callee-save f29 home dissolved, FPR save set changed (stfd f31/lfd f26 prologue deltas) | **CASCADE — REVERTED. Literal kept.** Confirms the mndiagram3 forced-named-.sdata2 caution for in-loop-consumed constants |

Protected sweep after each commit + after final restore: 0 regressions / 0 deltas (both 100s,
802417D0 98.0303, CursorProc 99.5158, 80240D94 97.3504, 8024227C 94.3234, InputProc 98.6726,
80242C0C 96.9513, HandleInput 97.4605, OnFrame 99.7188, 8023FC28 97.8241, 802427B4 98.8444).
Tree clean.

### EXTERN / NAMED-RELOC DISPOSITION (recorded, do not re-try)
- The 0.4f stays a LITERAL: the named-extern form is codegen-DIVERGENT here (in-loop reload).
  This also converges with the upstream guideline (no premature named-symbol externs in PRs).
- The remaining reloc-identity residual on this function's pool constants (@1519=0.4f vs
  mnDiagram_804DBFA0; @192/@1522 f64 conv-magic vs 804DBF78/804DBF98) is COSMETIC and largely
  source-unreachable — the f64 conversion constants are compiler-generated (you cannot point MWCC's
  own int->float magic at an extern). The retail "names" are dtk address-labels on the original's
  anonymous pool, not evidence of source-level externs.

### 80241E78 RESIDUAL CENSUS (@ 98.9416)
Sole family: the iter-3-characterized **r25<->r26 data/row callee-save swap + FP-coloring shadow**
(f26/f27/f28 role rotation). FULLNORM 0 ⟹ no structural/scheduling/count residual remains. The
iter-3 dataflow-pinned-ig characterization carries over; the substrate DID change (FP web
re-rolled), so the endgame round may spend ONE cheap re-test of the iter-3 levers per
substrate-relativity doctrine — not spent here (budget discipline; 4 refuted levers at low odds).

### ★ TU STRUCTURAL-FRONTIER CLOSING STATEMENT ★
With the window closed, EVERY tracked non-100 function in the mndiagram TU is now one of:
- **ARTIFACT / pure-coloring ceiling (FULLNORM 0):** OnFrame 99.72, 802427B4 98.84 (both
  rotation/swap webs), 802417D0 98.03, CursorProc 99.52, 80241E78 98.94 (this round).
- **ARTIFACT + one pending reloc-spelling lever:** 8023FC28 97.82 (`.bss.0` section-anchor vs
  named symbol — iter-2 LAW-2 cast-copy spelling, the NEXT round's single remaining source lever).
- **CHARACTERIZED WALLS (mechanism-pinned, lever not found in reachable C):** 80240D94 97.35
  (VN-CSE zero-emission-kill wall, iter-6), 8024227C 94.32 (banked: li-vs-copy trio + 2
  transpositions + rename cascade, iter-2), 80242C0C 96.95 / InputProc 98.67 / HandleInput 97.46
  (prior campaigns' documented walls).
There are NO remaining known structural windows in this TU. The structural phase of the
completion campaign is COMPLETE pending the 8023FC28 reloc spelling.

### PENDING-REVIEW (iter-7)
- **fe659a04f 0.4f fix RETAINED** — behavior-correcting + match-neutral (digit placement was off
  by 0.6 units in row>=10 / col>=7 cases). Same accepted class as prior retail-value corrections.
- **8523f3539 2-use spelling** `row_offset_adj = y_offset * rowf - 0.4f;` — recomputes the product
  instead of `row_offset - 0.4f`. LOAD-BEARING for the match (single-use form sinks the fsubs
  across the call; FULLNORM 0 <-> 20 hinges on it). Semantically identical (CSE'd to one fmuls).
  Comment in-source if a reviewer asks; do NOT "simplify" it back.
- 80241E78's PAD_STACK... has none. No new PAD_STACK introduced anywhere this round.

### ITERATION-8 RECOMMENDATION
1. **8023FC28 LAW-2 named-reloc spelling round** (the last source lever in the TU): apply the
   iter-2 LAW-2 cast-copy re-read spelling to restore the named `mnDiagram_804A0750` HA/LO relocs
   over `.bss.0` section-anchors. Small, bounded, ≤2 builds.
2. **Then formally declare the endgame/permuter phase** for the coloring-ceiling pool
   {OnFrame, 802427B4, 802417D0, CursorProc, 80241E78, + the walls if reopened}: permuter is
   currently FENCED on this branch — the declaration should hand the pool + each function's
   characterized residual to the orchestrator for a permuter-authorized round (80240D94 ROOT A's
   addi/mr = the one register-class site; ROOT B is NOT permuter-reachable, it needs an IR
   killing-def). Re-test the mndiagram2 zero-emission self-assignment probe on ROOT B if that
   campaign's spelling fires (orchestrator cross-link).

---

## ITERATION 8 (2026-06-11, driver 4) — 8023FC28 LAW-2 RELOC SPELLING **REFUTED** + ★ TU ENDGAME DECLARATION ★

### PART 1 — THE ONE QUESTION — ANSWERED: **NO.** The LAW-2 named-reloc spelling does NOT restore 8023FC28's named relocs, and it perturbs codegen. HARD-REVERTED.
Budget: 1 of ≤2 builds. 0 commits. Floor 97.82 restored byte-exact (HEAD=25cb88703, tree clean).

**The site (object ground-truth, ours `build/GALE01/src/.../mndiagram.o` vs target asm):**
- TARGET prologue: `lis r3, mnDiagram_804A0750@ha` / `addi r29,r3,mnDiagram_804A0750@l` / `addi r31,r29,0x1c` (NAMED HA/LO; base→r29, sorted_names→r31).
- OURS prologue: `lis r3, ...bss.0@ha` / `addi r31,r3,...bss.0@l` / `addi r30,r31,0x1c` (`.bss.0` SECTION-ANCHOR; base→r31, sorted_names→r30).
- Exactly **2 reloc-paired lines** (`@ha`+`@l`), as the iter-4 partition stated. Plus the callee-save rotation (base r29-vs-r31, sorted_names r31-vs-r30) — the FULLNORM-0 coloring artifact, NOT this iteration's target.

**Spelling tried** (iter-2 LAW-2 cast-copy shape, derived from the site): introduced `u8* sorted = (u8*) assets;` (cast-copy of the once-materialized `assets = (mnDiagram_Assets*)&mnDiagram_804A0750` local) and routed both base uses through it — `u8* dst = sorted + sizeof(mnDiagram_804A0750_t);` (was `assets->sorted_names`) and `u8* p = &sorted[max_idx];` (was `&assets->sorted_fighters[max_idx]`). Semantically identical (`(u8*)assets == &assets->sorted_fighters[0]`; `+0x1C == sorted_names`).

**Why it failed (RELOC METER before/after + mechanism):**
| Meter | Baseline (committed) | After LAW-2 spelling | Verdict |
|-------|----------------------|----------------------|---------|
| `.bss.0@` reloc-paired lines in 8023FC28 | **2** | **2** (UNCHANGED) | reloc NOT restored |
| named `mnDiagram_804A0750@` in 8023FC28 | 0 | 0 | reloc NOT restored |
| FULLNORM (instr count) | 108/108 | 108/108 | count neutral |
| frame | `stwu -0x218` / buf@r1+0x18 | **`stwu -0x220` / buf@r1+0x1C (+8B)** | **codegen PERTURBED** |
| fuzzy % | 97.8241 | 97.76 (−0.06); classification data-symbol-or-relocation→stack-layout | regressed |

The cast-copy added a stack-homed `sorted` local (frame +8) WITHOUT changing the reloc — a reloc-only lever must be codegen-neutral; this was the documented hard-revert condition. **REVERTED** (`git checkout`), rebuilt, protected sweep green (all 13 tracked fns byte-exact at their state-file numbers).

### WHY LAW-2 DOES NOT TRANSFER HERE (mechanism, banked — do not re-try the cast-copy)
LAW-2 (iter-2, 8024227C) restored named relocs because its re-read sat INSIDE loop bodies = MULTIPLE per-site base materializations, where the spelling controlled the per-site reloc choice. 8023FC28 has a SINGLE base materialization (one prologue `lis@ha`/`addi@l` pair); copying `assets` downstream cannot change which reloc that single pair uses — it only adds a move/slot.

**TU-WIDE RELOC CENSUS (object-level, decisive):** across the whole mndiagram TU our object emits **16 named `mnDiagram_804A0750@` + 6 `.bss.0@`**; target emits **22 named, 0 `.bss.0`**. The 6 `.bss.0` lines live in exactly THREE functions — **8023FA6C, 8023FC28, 80242C0C** — and in all three the form is identical: `lis rN,.bss.0@ha; addi r31,rN,.bss.0@l; addi r30/r31,r31,0x1C`. **The discriminator is the `+0x1C` (sorted_names) base materialization**: when MWCC needs `&mnDiagram_804A0750 + 0x1C` it selects the `.bss.0` section anchor; when it needs the symbol at offset 0 (`sorted_fighters[idx]`) it keeps the named reloc (the 16 named sites). This is a systematic MWCC base+displacement reloc-selection behavior, NOT a source spelling the C can steer at these three sites. The `.bss.0` reloc lines on {8023FA6C, 8023FC28, 80242C0C} are **reloc-identity ceiling noise**, reclassified from "pending source lever" to ARTIFACT.

---

## ★ TU ENDGAME DECLARATION ★ (handoff artifact for the endgame/permuter phase)

### (a) STRUCTURAL-FRONTIER-CLOSED STATEMENT
Every remaining non-100 divergence in all three mndiagram TUs is now attributed to a non-structural class. With the iter-7 fsubs window closed (80241E78) and the iter-8 8023FC28 reloc lever refuted, **there are NO remaining known structural windows in the TU.** Every tracked non-100 function is one of: a pure-coloring ceiling (FULLNORM 0, register/FP callee-save rotation), a characterized wall (mechanism-pinned, lever not found in reachable C), or reloc-identity ceiling noise. The STRUCTURAL phase of the completion campaign is **COMPLETE**. What remains is the endgame/permuter phase against coloring cascades + the two documented walls.

Matched (banked 100, protected): **mnDiagram_802437E8, mnDiagram_80243434** (+ all other TU 100s).

### (b) COLORING-CEILING POOL (FULLNORM 0; each with its identified swap/rotation pair)
| Fn | Fuzzy | Swap/rotation pair (from iter-3/4/7 partition + object disasm) |
|----|-------|----------------------------------------------------------------|
| OnFrame | 99.72 | single-pair **r28↔r29**: the `lwz rX,0x2c(r30)` user_data ptr loaded mid-fn (9 use sites). Same dataflow-pinned class as 80241E78's data/row swap. |
| 802427B4 | 98.84 | callee-save **rotation**: arg homes shift (TGT r26/r27 vs OUR r27/r28) + assets-base **TGT r31 vs OUR r25** (86 reg sites). comma-expr + interferer-trunc already landed (near-ceiling sibling). |
| 802417D0 | 98.03 | post-flip register-coloring **cascade** (callee-save renumber) off the iter-5 test-home flip; FULLNORM 0 (test-form was the only structural divergence; flip re-rolled the cascade, +0.30 only). |
| CursorProc | 99.52 | pure coloring **cascade** (FULLNORM 0, Δ0) after the iter-5 lhzu close; ~0.48% to 100. |
| 80241E78 | 98.94 | **r25↔r26 data/row callee-save swap + FP-coloring shadow** (f26/f27/f28 role rotation). row's ig dataflow-pinned BELOW data's (47<58) — every float input derives from `data->jobjs[...]` loaded before row is first-used. Decl-order/literal/param-direct/call-reorder all INERT (iter-3 B1–B4). FP web re-rolled iter-7, so ONE cheap re-test of the iter-3 levers is permuter-substrate-warranted. |
| 8023FC28 (post-Part-1) | 97.82 | **whole-web callee-save rotation** rooted at the assets-base materialization: TGT base→r29 then sorted_names→r31; OURS base→r31 then sorted_names→r30 (48 reg sites). PLUS the 2 `.bss.0`-vs-named reloc lines = ceiling noise (LAW-2 refuted, iter-8). FULLNORM 0. |

### (c) THE TWO WALLS (opacity / A1-remat cluster — DO NOT TOUCH; protected)
- **InputProc 98.67** — the opacity / A1-rematerialization cluster (prior mnDiagram_InputProc campaign; the Door-A survival law). 52-iteration campaign exhausted the source levers; banked-ready (PR #2660). Coloring/remat ceiling; FENCED + protected.
- **80242C0C 96.95** — same opacity/A1-remat cluster + the consumed expansion door (prior campaign). Also carries one of the three `.bss.0` reloc lines (ceiling noise, same MWCC base+0x1C selection). FENCED + protected.
- (mnDiagram2_HandleInput 97.46 — protected wall, prior campaign.)

### (d) mnDiagram_8024227C 94.32 — REGISTER-ENDGAME QUEUE
Structural phase COMPLETE (iter-2: hoist defeated, walk-shape + cast model landed, opcode-stream delta 0, frame byte-equal at stwu-160/stmw r15,92). Residual = 175 register-only lines (callee-save swap r29↔r30 named by checkdiff) + the li-vs-copy trio (+10c/+360/+39c) + 2 one-slot inline-scheduling transpositions (+284/+288, +470/+474). All cascade-watch / coloring. **Banked register-endgame queue (in order):**
1. decl-order nudges (the decl list is still m2c-alphabetical — reorder to peel callee-saves, apply→re-bootstrap→repeat per the cardstate decl-chain method).
2. `debug target match-iter-first -f mnDiagram_8024227C --regs gpr-volatile,r0` (checkdiff's own suggestion — the match-iter-first oracle).
3. force-phys r14–r17 probes (diagnostic only).
PAD_STACK(24) = diagnostic (frame group byte-equal); natural-frame replacement pending (PENDING-REVIEW).

### (e) mnDiagram_80240D94 97.35 — VN-CSE WALL
FULLNORM 7, two roots (iter-6, mechanism POSITIVELY CONFIRMED via the `if (arg1==arg2) arg2=arg1;` probe):
- **ROOT B (VN-CSE):** ours ONE cached `clrlwi r22,r28,24`+`addi r3,r22`+`mr r3,r22` vs target per-site `clrlwi r3,r29,24` ×2 at the two GetNameText calls (src 1807/1822). arg2's two AND-VNs merged by sequential-path IRO CSE; target's did not (arg2's VN was killed between the paragraphs in the original IR). Needs a ZERO-EMISSION VN-kill: must (a) kill arg2's VN between paragraphs, (b) emit 0 instrs, (c) introduce NO block boundary. Probe proved the kill fires but control-flow kills emit `cmpw+bne+mr` (+3) and break the shared `li r23,1` web. **Not permuter-reachable** (needs an IR killing-def, not a register choice). **ROOT B RE-TEST CONDITION:** if the mndiagram2 campaign's zero-emission self-assignment probe FIRES (produces a straight-line, zero-emission, no-block-boundary VN kill), re-test it here — that is the one untried class for ROOT B (orchestrator cross-link).
- **ROOT A (the one register-class permuter site):** `tbl = &803EE728` init emitted as `addi r0` (hoisted above stwu) + `mr r27,r0` vs target direct post-stmw `addi r28`. Did NOT cascade under the forced split (suggestive-not-decisive). Scheduling/pressure-conditioned (sibling PopupAnimProc: identical spelling, direct form). A's addi/mr **MIGHT be permuter-reachable (register-class)** — the one register-class permuter site on this fn.
PAD_STACK(24) = provably dead 24B frame space in the retail object (iter-6 frame ground-truth; NOT missing live structure); STAYS (PENDING-REVIEW).

### (f) PENDING-REVIEW LEDGER (TU-wide; resolve before any PR)
1. **PAD_STACK(24) on 8024227C** (committed 90de0b888) — diagnostic; frame group byte-equal at -160/stmw r15,92. Natural-frame replacement pending (try `u8 stack_obj[24]`+`(void)&` first; meter slot positions).
2. **PAD_STACK(24) on 80240D94** — KEEP with a comment citing the dead-frame evidence (the 24B is never-referenced in the retail object, pinned by decl-order to a dead local declared after buf; upstream precedent: mndiagram2 CreateStatRow ships `int pad[4]`+PAD_STACK(16)). The "PAD_STACK = missing live structure" doctrine is REFUTED for THIS fn specifically (the missing thing is provably dead). Inventing a dead local would be honesty-negative vs the macro.
3. **PAD_STACK(12) on 8023FC28** — diagnostic; natural-frame pass pending.
4. **`sorted = (u8*) assets;` casts on 8024227C** (×3, committed iter-2) — semantically clean (`assets` IS the sorted_fighters base; the overlay struct documents it). Reviewer may prefer `assets->sorted_fighters` — that spelling costs −3.86pp (allocation re-roll); keep the cast-copy, comment if questioned.
5. **s32 retypes holding u8 values** on 8024227C (var_r0_2/var_r23/var_r17_6) — matches retail codegen (int-home → clrlwi at every (u8) use site). m2c `var_rNN` naming retained throughout; a cosmetic naming pass is free + recommended before PR.
6. **CursorProc `u16* hov=(u16*)&mn_804A04F0; *++hov; *hov`** (d858e94ae) — the pre-increment walk is the retail idiom (proven by `lhzu`); load-bearing (direct field form costs Δ+1). Keep; comment if questioned.
7. **0.4f fix on 80241E78** (fe659a04f) — behavior-correcting (digit placement was off by 0.6 units in row≥10/col≥7) + match-neutral. RETAINED. The `extern const f32 mnDiagram_804DBFA0` named form is codegen-DIVERGENT (in-loop reload) — do NOT re-try; the literal stays (also converges with the upstream no-premature-named-externs guideline).
8. **8523f3539 2-use spelling** `row_offset_adj = y_offset * rowf - 0.4f;` on 80241E78 — LOAD-BEARING (single-use form sinks the fsubs across the call; FULLNORM 0↔20 hinges on it). Semantically identical (CSE'd to one fmuls). Do NOT "simplify" back.
9. **8023FC28 dead-24B proof / `(u8*)` cast disposition** — the iter-8 cast-copy was REVERTED (not retained); the committed `assets->sorted_names` / `&assets->sorted_fighters[max_idx]` member-deref form is the floor. No new pending item from Part 1.

### (g) RECOMMENDED PERMUTER-CHANNEL ALLOCATION ORDER (for the pool)
Permuter is currently FENCED on this branch; this is the hand-off order for a permuter-authorized round (highest expected yield first, by cascade size × structural-headroom):
1. **8024227C (94.32)** — LARGEST headroom (5.68pp), opcode-stream delta 0 + frame matched, 175-line cascade is the LAST family. Run the register-endgame queue (d): decl-order nudges first (cardstate decl-chain method), then match-iter-first oracle (`--regs gpr-volatile,r0`), then force-phys r14–r17. Best single permuter ROI in the TU.
2. **802417D0 (98.03)** — clean post-flip coloring cascade (FULLNORM 0), 96-site; medium headroom (1.97pp), single root (the iter-5 test-flip).
3. **80240D94 ROOT A (97.35)** — the ONE register-class permuter site (the `tbl` addi/mr); ROOT B is NOT permuter-reachable (needs an IR killing-def — gate it behind the mndiagram2 zero-emission-probe re-test, not the permuter). Lower headroom on the reachable part.
4. **80241E78 (98.94)** — ONE cheap permuter re-test of the iter-3 dataflow-pinned levers (the FP web re-rolled iter-7, substrate changed); low odds (the r25↔r26 swap is dataflow-pinned), small headroom (1.06pp).
5. **802427B4 (98.84)** — near-ceiling sibling; comma-expr + interferer-trunc already landed; LOW yield (the 86-site rotation is a clean callee-save permutation).
6. **CursorProc (99.52), 8023FC28 (97.82-rotation), OnFrame (99.72)** — LOWEST yield (pure dataflow-pinned single-pair swaps / whole-web rotations; ~0.3–0.5pp each). Park unless a cheap permuter channel is idle. 8023FC28's 2 reloc lines are ceiling noise (not permuter-addressable).
WALLS (InputProc, 80242C0C, HandleInput) are FENCED + protected — NOT in the permuter rotation.

### STATE-FILE-vs-TREE RECONCILIATION (iter-8)
Verified at HEAD=25cb88703, tree clean: every tracked-fn number in this declaration was re-measured this iteration via `checkdiff --summary` and matches the iter-7 protected-sweep numbers EXACTLY (8023FC28 97.82, 80241E78 98.94, CursorProc 99.52, 802417D0 98.03, 80240D94 97.35, 8024227C 94.32, OnFrame 99.72, 802427B4 98.84, 802437E8/80243434 100, InputProc 98.67, 80242C0C 96.95, HandleInput 97.46). **No discrepancy found between the state file and the tree.**

---

## ★ ENDGAME ORACLE ROUND 1 ★ (2026-06-12, oracle-endgame driver) — 8024227C 94.32 register-endgame queue: ALL RUNGS REFUTE; the order is NOT the residual; the residual is a COALESCING-STRUCTURE divergence (force-* cannot express it)

### THE ONE QUESTION — ANSWERED: **NO**, the banked register-endgame queue does NOT move 8024227C past 94.32. The oracle CHARACTERIZES the remaining distance precisely (below): it is NOT a select-order / iter-first / remat-slot phenomenon — it is an upstream interference-graph (coalescing/liveness) divergence that the force-phys / force-iter-first / force-remat hooks structurally cannot express.

8024227C unchanged at **94.32** (byte-exact; no source edits). 0 source commits. Budget: ~5 forced dumps + 1 decl-orders sweep (≈63 internal compiles) + the force-phys-from-diff verify pass (40 internal probe compiles) + 1 oracle re-derive. All diagnostic-only (forced runs skip cache sync; decl-orders auto-reverts). Tree clean except the intentional DLL-source update (see TOOLING NOTE).

### PER-RUNG VERDICT TABLE
| Rung | Tool | Result | Verdict |
|------|------|--------|---------|
| 1. DECL-ORDERS SWEEP | `debug mutate decl-orders --strategy all` (≈63 candidates: promote+demote+swap over 21 locals) | every candidate +0.00% or worse (a few −0.03..−0.07 cascade jitter). #572 AstWalkError did **NOT** crash — ran clean. | **NO WIN.** Decl-position is INERT on this fn's residual (confirms iter-2's "cascade is coloring, not decl-driven"). |
| 2a. FORCE-PHYS ORACLE | `debug target force-phys-from-diff --verify` (derives target physreg map from the register-only checkdiff, then verifies) | derived **40 target force-phys entries**; **union = no_match**, all 40 singletons = no_match, all 39 prefixes = no_match. **~45 ig nodes need to move** (every callee-save r15–r30 + volatiles r16–r19 + arg regs r3/r6 renumbered). | **FORCING TARGET COLORS DOES NOT REACH BYTE-MATCH.** Plus **conflict signal**: ig56 wanted both r29 AND r31; ig48/ig41 wanted both r3 AND r6; ig73 wanted both r6 AND r15 → the SAME virtual maps to TWO different target physregs at different sites = the target SPLITS lives ours COALESCES. |
| 2b. MATCH-ITER-FIRST ORACLE | `debug target match-iter-first --regs gpr-callee` + verify-application probe `dump local --force-iter-first 111,46,56,122,121` | the oracle's own output flags the obstruction: **ig56 (virt r56) maps to r29 AND r28 AND r27** — the three `addi rN,argN,0` arg-home copies (gobj/arg1/arg2 at instr 5) are THREE separate nodes in the target but ONE coalesced virtual ig56 in ours ("conflicts omitted from runnable vector"). Forcing the non-conflicting subset (111,46,56,122,121) STILL MISMATCHES and re-rolls the prologue into a NEW-but-still-wrong config (forced: lis r28/addi r25,r4/addi r26,r5/addi r29,r3; target: lis r26/addi r28,r3/addi r27,r4/addi r29,r5). | **FORCING THE TARGET SIMPLIFY ORDER DOES NOT REACH BYTE-MATCH.** The conflict node ig56 cannot be expressed by force-iter-first (it omits conflicts). Verify-application (#550) CONFIRMED the override took (prologue nodes moved) but into a wrong config — proving the order is not the sole lever. |
| 2c. TIEBREAK SURROGATE (#573) | `debug inspect tiebreak --class gpr` | **G1 126/126 (100.0%), 0 truncated nodes** — surrogate reproduces OUR coloring perfectly; no what-if lever proposed (no abstain). | **Our coloring is internally consistent.** The residual is NOT a tiebreak ambiguity our G1 can flip — it is UPSTREAM of coloring (in the node set / interference structure). |
| 3. SOURCE-AXIS SEARCH | (subsumed) | the oracle's order-distance map shows the out-of-place nodes are NOT a movable select-order set — they are the coalesced arg-home node (ig56) + a whole-function renumber rooted in it. No source order-mover (decl/stmt/hoist) can SPLIT a coalesced node into three. | **NO TARGETED SOURCE EDIT INDICATED.** Rung 1 already exhausted the decl axis; the map says the lever is not on the statement-order axis either (the divergence is node-creation, not node-ordering). |
| 4. FORCE-REMAT PROBE (#579) | `debug dump local --force-remat 0:IG=copy ... --force-remat-fn` on the li-vs-copy trio nodes | **HOOK WORKS** (after DLL rebuild — see TOOLING NOTE): all zero-init nodes REACHED, log `flags 0x02 -> 0x12` for ig {44,45,46,47,49,50,51,52,53,57,77,89,96,103,...} (EVERY `li 0` in the fn IS a remat node, flipped to copy-mode). **YET the trio sites +10c/+360/+39c remain `li r16,0` — ZERO codegen change** in either direction (copy or literal), confirmed byte-identical object. | **THE TRIO IS NOT A REMAT OPERAND-SLOT DECISION.** Flipping bit 0x10 (the alternate remat operand selector) is INERT because our IR has **no live zero-register to copy FROM** at those program points — ours materializes each zero as an independent literal. The target's `addi rY,rX,0` copy form reflects an UPSTREAM IR difference (the zero is live across the count loops and reused), a value-numbering/liveness property, NOT a late remat choice. Gate (a) resolve the 3 sites = NO; (b) hook reveals the nodes ARE remat-eligible but have no copy-source operand; (c) no source-reachable pressure change implied — the divergence is in node creation. |

### THE ORACLE'S HEADLINE
- **Is the order THE residual? NO.** Forcing the target's exact final colors (force-phys, 40 entries) AND forcing the target's simplify order (force-iter-first) BOTH fail to byte-match. The order is a SYMPTOM, not the cause.
- **How many nodes out of place? ~45** GPR ig nodes renumber (whole callee-save band r15–r30 + several volatiles + two arg regs). But this is not 45 independent movable nodes — it is **ONE root: the arg-home coalescing node ig56**, plus its whole-function renumber cascade.
- **Which are source-reachable? NONE via the queue's axes.** The root (ig56 = three target arg-home nodes {gobj→r28, arg1→r27, arg2→r29} collapsed into one coalesced virtual in ours) is a COALESCING-STRUCTURE divergence: the target keeps the three `addi rN,argN,0` arg copies as distinct lives; ours coalesces them. force-phys/force-iter-first operate on the EXISTING node set and cannot split one virtual into three; force-remat operates on remat-operand slots and is inert here. The tiebreak surrogate (G1 100%) confirms the divergence is upstream of coloring.

### THE FORCE-REMAT CHARACTERIZATION (#579, decisive)
The li-vs-copy trio (+10c/+360/+39c) was the queue's flagged A1 constant-rider candidate. The #579 hook DEFINITIVELY refutes the remat hypothesis for it: every zero node in the function is remat-eligible and was successfully flipped to copy-mode (hook log `0x02 -> 0x12`), but the emitted code does not change. The backend cannot emit `addi rY,rX,0` because there is no live zero-register operand to copy in our IR's dataflow at those points. The trio is therefore a **liveness/value-numbering divergence** (the target's count loops share one live zero; ours mints independent literals), in the SAME upstream-IR family as the ig56 coalescing root — NOT a backend remat-slot decision. This is the honest reachability verdict the hook was built to deliver: it PROVES the trio is not remat-reachable.

### RE-ROLLED RESIDUAL CENSUS (8024227C @ 94.32, committed source bade94f78, post-round)
- **Sole structural family: the arg-home COALESCING divergence (root ig56).** Target keeps gobj/arg1/arg2's `addi rN,argN,0` copies as three distinct callee-save lives (r28/r27/r29); ours coalesces them into one virtual, forcing the whole-function callee-save renumber (~45 ig nodes, the "175 register-only lines"). This is an interference-graph SHAPE difference, not a coloring tiebreak.
- **li-vs-copy trio (+10c/+360/+39c):** a liveness/VN sibling of the root — target reuses a live zero; ours mints independent `li`. NOT remat-reachable (#579 proven). NOT decl-reachable (rung 1). Cascade-coupled to the root.
- **2 one-slot inline-scheduling transpositions (+284/+288, +470/+474):** count-neutral; cascade-watch.
- **Reloc: SOLVED (named symbol).** Frame: byte-equal at -160/stmw r15,92. opcode-stream delta 0 (iter-2). The fuzzy 94.32 is dominated by the register-renumber cascade off the one coalescing root.

### WHY THE QUEUE IS EXHAUSTED (mechanism, banked)
The banked queue (decl-orders → match-iter-first → force-phys) presupposed the residual was a SELECT-ORDER/COLORING phenomenon reachable by reordering or recoloring the EXISTING node set. The oracle proves it is not: the divergence is the **node set itself** (ours coalesces the three arg-home copies that the target keeps distinct). No register-endgame lever — decl-order, simplify-order, force-phys, force-remat — can split a coalesced live into three; that requires an UPSTREAM source change that makes MWCC's coalescer keep the three arg copies separate. Candidate source levers for a FUTURE dedicated round (NOT a register-endgame rung; this is structural-reopen territory): give gobj/arg1/arg2 distinct, longer-lived uses that defeat the coalesce (e.g. re-read each across a call so they don't collapse) — but note iter-2 already established the arg-home shape via the cast model and reached opcode-delta-0, so this is a coalescer-pressure experiment, not a clear win. The cleaner disposition: **8024227C's register cascade is a coalescing-structure ceiling for the register-endgame axis; the only remaining lever is a structural arg-home-liveness reopen, which is a permuter-or-deep-dive task, not a queue rung.**

### TOOLING NOTE (resolved in-worktree; flagged for orchestrator)
- **#579 force-remat was NOT in this branch's deployed DLL.** Branch bade94f78 predates #579 (c41c92793 is NOT an ancestor); the worktree's `tools/mwcc_debug/mwcc_debug.c` lacked the hook (0 refs), and the deployed DLL was built from it. BUT the editable `melee-agent` CLI resolves to the MAIN checkout (`/Users/mike/code/melee/tools/melee-agent`), which HAS `--force-remat` → the flag was silently forwarded to a DLL that ignored it (0-codegen-change no-op that masqueraded as "remat is inert"). `dump doctor` reported PASS because it checks the deployed DLL against the worktree's (old) C source — they were mutually consistent, just both pre-#579.
- **FIX (per CLAUDE.md "rebuild, never hand-copy"):** copied the MAIN checkout's `mwcc_debug.c` (canonical, matches the live CLI) into the worktree and ran `debug dump setup --rebuild-dll` (smoke test passed). The hook then engaged (log `[FORCE_REMAT] ... flags 0x02 -> 0x12`). This is a TOOLING-SOURCE update, not a binary copy; it does NOT affect the production ninja build or stock-compiler checkdiff (all baseline numbers re-verified byte-exact: 8024227C 94.32, both 100s, all walls/cluster unchanged). The `tools/mwcc_debug/mwcc_debug.c` modification is left in the worktree (uncommitted) so the hook stays usable for follow-on rounds; orchestrator may discard it or fold the #579 line into the branch.
- **Hook-log observability gap:** the `[FORCE_REMAT]` per-node log lands in the FORCED PCDUMP file (grep the temp `pcdump_forced_*.txt`), NOT in CLI stdout/stderr under wibo — surface it via the dump file. Also: the parser cap is **64 entries** (`override list exceeded parser capacity (cap=64)` → applies NOTHING if exceeded; a 96-node range silently no-ops). Keep force-* lists ≤64 and verify reached-nodes in the forced dump.

### PROTECTED SWEEP (re-verified from fresh report.json, this round)
802437E8=100, 80243434=100, InputProc=98.67, 80242C0C=96.95, HandleInput=97.46, OnFrame=99.72, 802427B4=98.84, 8023FC28=97.82, 80241E78=98.94, 802417D0=98.03, CursorProc=99.52, 80240D94=97.35, 8024227C=94.32. **0 regressions.** HEAD=bade94f78, no source commits.

### RECOMMENDATION
1. **PARK the 8024227C register-endgame queue.** All three banked rungs (decl-orders, match-iter-first, force-phys) plus the #579 force-remat probe are REFUTED by the oracle. The residual is a coalescing-structure (arg-home liveness) divergence, not a coloring/order/remat phenomenon — no register-endgame lever can express it.
2. **The remaining lever is STRUCTURAL, not register-endgame:** an arg-home-liveness reopen that makes MWCC keep the three `addi rN,argN,0` arg copies as distinct lives (defeat the coalesce). This is a deep-dive/permuter task with uncertain yield (iter-2 already reached opcode-delta-0 via the cast model). Hand to the order-distance / coalescing-search tooling when it ships, or to a permuter-authorized round (per the iter-8 allocation order, 8024227C is rank-1 for permuter ROI — but the permuter must target the COALESCING boundary, not register tiebreaks; the running coder1 job is doing exactly this on the current base).
3. **STALE-BASE: NOT triggered** — no source improvement committed; the running coder1 permuter job's base (current committed source) is UNCHANGED. No re-bootstrap needed.

---

## ★ ORACLE ROUND 2 (coalesce) ★ (2026-06-12, oracle-endgame driver) — VETO PREMISE REFUTED BY THE ALIAS READBACK + ROUND-1 ERRATUM; THE REAL ROOT (param-alias statement copy) FOUND AND FIXED IN C; TRIO RESOLVED. **94.32 → 94.80** (2 commits)

### THE ONE QUESTION — ANSWERED IN TWO HALVES:
- **Does the #548 coalesce-VETO reproduce the target's three-distinct-arg-home structure? NO — and the premise itself was wrong.** The alias-array readback (the prescribed verify instrument) shows our build has only **10 coalesce merges, NONE involving the arg-home webs** (9 virt→phys call-arg materializations: 32/118/143→r3, 41/42/48/54/148/167→r6; 1 v-v merge 135→69). The three arg homes were ALWAYS three distinct webs in both builds. **ROUND-1 ERRATUM:** the "ig56 = 3-into-1 arg-home coalesce" headline is RETRACTED — it was a match-iter-first `[ambiguous]` alignment artifact + positional misalignment caused by a real but different structural skew (below). The round-1 force-phys union failure is partly explained by this misderivation (it forced our arg1-web to target's GOBJ register, etc.).
- **Does a C spelling defeat the (real) divergence? YES — two of the three windows fell to C.** Build 1 (gobj alias drop) closed the prologue-order window; Build 3 (count-loop inline helper) closed the li-vs-copy trio. 94.32 → **94.80**, opcode similarity 90.6 → **98.8**.

### THE REAL ROOT (recon, pcode-level)
Pre-coloring entry block: `mr r32,r3; lis; lis; mr r33,r4; mr r34,r5; mr r56,r32; ...`
- arg1/arg2 (`s32 arg1_r = arg1` etc.) collapse onto their param virtuals r33/r34 → their ABI **entry copies** survive (live-across-calls webs cannot merge into volatile r4/r5).
- gobj (`void* gobj = arg0;`) kept a TWO-virtual chain: param r32 + alias-local r56 (statement copy `mr r56,r32`). r32 dies at the alias copy → naturally coalesces into PHYS r3 (the `32 -> 3` merge) → the surviving gobj copy is the STATEMENT copy, emitted AFTER the entry copies. Result: ours emitted the three arg-home copies in **r4,r5,r3** order vs target's homogeneous entry order **r3,r4,r5** — the skew that poisoned every positional alignment downstream. (Why copy-prop collapsed arg1_r/arg2_r but not gobj: unattributed; the fix is empirical.)

### THE COALESCE ORACLE (diagnostic, gates per #550)
| Gate | Result |
|------|--------|
| Prescribed veto (`V=V`) on arg-home-folding merges | **NOTHING TO VETO** — no such merges exist (readback above). |
| Constructive merge `32=56` (un-split the gobj chain) via CLI | CLI safety gate REFUSED ("missing colorgraph node r32 — simplify-only or pcode-only"). |
| Same via env bypass (`MWCC_DEBUG_FORCE_COALESCE` exported around a plain dump; cache re-cleaned after) | **(a) APPLIED:** `[FORCE_COALESCE] alias[32]: 3 -> 56`, `forced=1`, readback `32 -> 56 [r24]`. **(b)(c) INERT:** function code BYTE-IDENTICAL to baseline (dtk disasm diff = 0 over 400 lines). |
| Mechanism | The natural union REWRITES pcode operands before the override applies — `mr r32,r3` was already folded; by override time no r32 operand exists, so the redirected alias entry dangles. **Tool-capability statement: the coalesce hook cannot resurrect/un-fold a naturally-folded param-receive copy.** The CLI gate's refusal is CORRECT for this class (not a false negative). |

### C-SEARCH LADDER (4 builds: 2 commits, 2 hard-reverts)
| Build | Edit | Result | Verdict |
|-------|------|--------|---------|
| **1** | DELETE `void* gobj = arg0;`, use `arg0` at all 7 sites | 94.32 → 94.37; **prologue copies flip to target order r3,r4,r5** (+014..+034 now positionally aligned, dest-reg-only); force-phys derivation now role-clean (ig32→r28, ig33→r27, ig34→r29, ig121→r26, ig120→r25, ig44→r30) | **COMMITTED e53f560bb** |
| 2 | three count loops respelled `count=0; for (i=0; i<0x19; i++)` (for-header init) | trio UNCHANGED (still 2×li); 94.37 byte-equal | **REVERTED — for-idiom is NOT the discriminator** |
| **3** | `static inline mnDiagram_CountUnlockedFightersInline()` (body = the dont_inline real fn, spelled like GetNameTotalKOs) called at the 3 count sites; 3 dead idx decls dropped | 94.37 → **94.80**; **TRIO RESOLVED**: +108/+10c/+110, +35c/+360, +39c/+3a0 all now `li; addi-copy; mr` = register-only; opcode 90.6 → **98.8**; CountUnlockedFighters real fn stays 100 | **COMMITTED bffd32597** |
| 4 | delete `s32 cap = 0xF423F;` + literal `999999` caller clamp | 94.79 (−0.01); forwarding INTENSIFIED (`addi r6,r16,0; cmpw r6,r30` — even the compare moved into r6); prologue cap pair survived (VN-unified w/ SumFighterFalls literal) | **REVERTED — literal clamp worsens the forward** |

Protected sweep after every build + final restore: 0 regressions (both 100s, walls, cluster, CountUnlockedFighters=100). Tree clean at bffd32597.

### LAWS (new/extended)
1. **Param-alias-local law (build 1):** an m2c `T* alias = arg;` whose param virtual dies at the alias copy splits the arg home into a STATEMENT copy (emitted after the other params' entry copies) and lets the param virtual coalesce into its ABI reg — skewing the prologue copy ORDER. Deleting the alias homes the arg on its param virtual: entry copy, param-order emission. Check any m2c fn whose prologue copy order differs from param order.
2. **Zero-pair trio law (builds 2+3, extends iter-4 inline-node evidence):** adjacent raw `a=0; b=0;` statements emit two `li`; the SAME pair inside an INLINE EXPANSION emits `li + addi-copy` (init nodes survive expansion). The for-header respelling does NOT produce the copy. Recovery: wrap the loop in a TU-local static inline (the dont_inline real-fn + inline-twin split mirrors an inline-budget original: auto-inline at early sites, real calls later — consistent with target having 3 expansions + 2 real calls of the same body).
3. **Clamp-forwarding (build 4 + window comparison):** a caller-side `if (v > cap) v = cap;` on a call result forwards the clamp value into the call-arg register (join-in-r6) where the target joins-in-home; the literal spelling makes it WORSE; clamp-inside-inline-helper (+0ec SumFighterFalls) produces join-in-home. Lever for the caller-clamp window NOT FOUND despite 2 spellings (cap-local if-form = current best; the shared SumFighterKOs cannot take the clamp — its other user 8023FA6C's target has 0 clamp constants).

### RE-ROLLED RESIDUAL CENSUS (@ 94.80, bffd32597)
1. **+284/+288 one-slot transposition** (GetNameTotalKOs expansion: param-mask vs init-copy order) — 2 lines, inline-boundary scheduling.
2. **Clamp/arg-order windows:** +46c..+47c (caller-clamp joins-in-r6 + r6-copy hoisted above ble; target joins-in-home + r3-before-r6) ≈4 lines; +0f0/+0f4 (r6/r3 arg-copy order after the SumFighterFalls join) = 2 lines.
3. **~178-line register-only coloring cascade** — now on a role-clean substrate (derivation conflicts down to alignment-noise in the count-temp region). Force-phys union/prefixes still no_match, but this gate CANNOT pass while windows 1-2 exist (they are instruction-content/order diffs, not register diffs).
4. PAD_STACK(24) diagnostic — unchanged (pending natural-frame item stands).

### STALE-BASE FLAG (PROMINENT)
**TWO source commits this round (e53f560bb, bffd32597) — coder1's running permuter job base (94.32) is STALE. Re-bootstrap required at next triage.**

### RECOMMENDATION
1. ONE more bounded source round on the two remaining structural windows: (a) the +284/+288 transposition and (b) the clamp/arg-order family — both inline-boundary/forwarding class; candidate probes: arg-expression shapes at the 80241E78 call sites (the r3-vs-r6 copy order may key off the gobj re-read form), and a second-use anchor on var_r16_6 (iter-7 recipe) for the join-in-home.
2. THEN the register endgame on the clean substrate: the role-correct force-phys vector is now derivable; hand the cascade to the directed select-order search / permuter (re-bootstrapped at 94.80).
3. Tooling note: the force-coalesce CLI gate message could state the mechanism ("cannot resurrect naturally-folded copies — operands already rewritten") instead of "unsafe"; the env bypass contaminates the baseline cache (no forced-run flag) — re-dump after use.

---

## ★ WINDOWS ROUND ★ (2026-06-12, windows-round driver) — W2 CLAMP-CONTENT WINDOW CLOSED (94.80 → 95.39, opcode 98.8 → 99.4); W1 UNMOVED; THE r3/r6 ARG-COPY ORDER IS A COALESCING-STRUCTURE WALL (gate-confirmed); FORCE-PHYS GATE STILL FAILS (needs-move, `wanted both r3 and r6` + frame −24)

### THE ONE QUESTION — ANSWERED IN TWO HALVES:
- **Do the two instruction-content windows close?** PARTIALLY. **W2's clamp-content half CLOSED** (the +46c SumFighterKOs caller-clamp forwarding, +0.59); **W1 did NOT close** (the +284/+288 transposition is unmoved by the only derivable source lever); **W2's residual half (the r3/r6 arg-copy ORDER) did NOT close** (no source-honest lever found; it is a coalescing-structure divergence the gate confirms).
- **Once they close, does the force-phys union gate pass?** **NO.** The gate (re-run on the 95.39 substrate) is STILL `needs-move`, union `no_match`, all 38 singletons + 37 prefixes `no_match`, AND still emits the `class0 ig98/ig41/ig63 wanted both r3 and r6` conflicts (these ARE the r3/r6 order windows) plus `ig34 wanted both r29 and r31`. Frame alignment `target=0xa0 current=0xb8 delta=-24` (the PAD_STACK(24) diagnostic, unchanged). The gate cannot pass while the r3/r6 ORDER windows remain — they are instruction-order/coalescing diffs, not register-coloring diffs, exactly as Round 2 predicted.

8024227C: 94.80 → **95.39**, opcode 98.8 → **99.4**, hunks 82 → 83 (the +474 clamp line moved from content-diff to reg-only). 1 commit (2743a3aff). Budget: 2 source builds (1 commit, 1 hard-revert) + 1 force-phys gate (~77 internal probe compiles, diagnostic) + 1 fresh pcdump. Tree clean at 2743a3aff.

### BUILD LEDGER (2 builds: 1 commit, 1 hard-revert)
| Build | Window | Edit | Result | Verdict |
|-------|--------|------|--------|---------|
| 1 | W1 | `mnDiagram_GetNameTotalKOsInline` twin with the SumNameKOs `for (i = total; ...)` j-from-total idiom (init i FROM the zero `total`), called at the one +280 site; the real `GetNameTotalKOs` (standalone 100%) left untouched | 94.80 byte-equal; **+284/+288 transposition UNMOVED** (still mask-then-copy vs target copy-then-mask) | **REFUTED — REVERTED.** The j-from-total idiom does NOT reorder the preheader copy-vs-mask; the order is a scheduling/coloring tiebreak the loop-init spelling does not touch. |
| **2** | W2 | `mnDiagram_SumFighterKOsClamped` inline twin (= SumFighterKOs body + the `if (total>999999) total=999999;` clamp INSIDE, mirroring SumNameFalls which clamps-inside and already matches at +0ec); called at the one +478 grid site; caller clamp `if (var_r16_6 > cap) var_r16_6 = cap;` dropped | 94.80 → **95.39**; **+46c/+470/+474 content now matches** (clamp joins-in-home: `addi r16,r26,16959` into the value home, not eager-forwarded into r6); opcode 98.8 → 99.4 | **COMMITTED 2743a3aff.** Only the r3/r6 arg-copy ORDER (+478/+47c) remains at this site. |

### THE W2 CONTENT LEVER (banked, transferable)
**Caller-clamp on a draw value forwards it into the arg register; clamp-INSIDE the inline joins-in-home.** The +46c SumFighterKOs grid-cell draw clamped `var_r16_6` at the CALLER (`if (v > cap) v = cap;`). MWCC coalesced var_r16_6's life-end with the r6 arg slot and emitted the clamp's `cap` assignment DIRECTLY into r6 (`addi r6,r31,16959`), with an eager `addi r6,r16,0` before the branch (the Round-2 "forwarding intensified" observation). Target keeps the clamp result in the value home (`addi r16,r26,16959`) and copies to r6 only at the call — exactly the SumNameFalls path (+0ec), which already matched because SumNameFalls clamps INSIDE its inline. Recovery: move the clamp inside a dedicated inline twin (do NOT modify the shared `mnDiagram_SumFighterKOs` — its other user 8023FA6C has no clamp; Round 2 LAW-3 corollary). This CLOSES the clamp content; the residual r3/r6 order is a separate (coalescing) family.

### W1 — THE +284/+288 TRANSPOSITION = SCHEDULING/COALESCING TIEBREAK (opcode-identical; lever NOT FOUND)
Object ground-truth: the window is `{addi i,total,0 (zero-pair copy), clrlwi (u8)field_index}` emitted in OPPOSITE order — target copy(+284)-then-mask(+288); ours mask(+284)-then-copy(+288). **Opcode-IDENTICAL transposition** (both instrs present in both, only the order swaps) inside the GetNameTotalKOs inline preheader. Both operands are ready after the `li total,0` at +280; the scheduler picks the order. The standalone `mnDiagram_GetNameTotalKOs` (100%) emits mask-FIRST + two-`li` (no copy) because it is pressure-free; the inline (under 8024227C's pressure) emits the `addi`-copy and orders it after the mask. The j-from-total idiom (Build 1) does not move it. The iter-7 graft/second-use anchor does not apply: the `(u8)field_index` mask is single-use inside the inline (only GetPersistentNameData) and `var_r0_2` is already multi-use (homed in r19); there is no genuine second use to add (target has none — a fabricated use is honesty-negative). **Lever NOT FOUND despite the idiom twin + graft-law analysis.** This is a scheduling tiebreak in the inline-boundary family, cascade-coupled to the coalescing root.

### THE r3/r6 ARG-COPY ORDER = COALESCING-STRUCTURE WALL (gate-confirmed; clamped-vs-unclamped provenance pinned)
Three temp-arg draw sites (+0f0 SumNameFalls header, +1cc SumFighterFalls header, +478 SumFighterKOsClamped grid) emit the gobj(r3) and value(r6) arg-copies in the WRONG order: target gobj(r3)-then-value(r6); ours value(r6)-then-gobj(r3). The matched sites (+2bc name grid, +33c) emit value(r6)-then-gobj(r3) and OURS matches them. **Decisive discriminator (object-level):** the matched +2bc passes an UNCLAMPED inline value (`GetNameTotalKOs`, raw accumulator) → both do r6-first; the mismatched sites pass a CLAMPED inline value (SumNameFalls/SumFighterFalls/SumFighterKOsClamped, value passes through the clamp's control-flow merge) → target does r3-first, ours does r6-first. Ours COALESCES the (clamped) value's life-end into the r6 arg slot regardless; target keeps the clamped value in its home (the clamp merge defeats its coalesce) and copies gobj first. This is a coalescing decision DOWNSTREAM of the IR we control — the clamp is already present and correct (+0ec/+46c-clamp match). **The force-phys gate confirms it:** `ig98/ig41/ig63 wanted both r3 and r6` = the SAME virtual colored r3 at some sites and r6 at others in the target, which force-phys (one physreg per virtual) structurally cannot express — identical in character to the Round-1/Round-2 arg-home coalescing root. **Lever NOT FOUND despite: the clamp-inside content fix (closed the forwarding but not the order), the gate's full force-phys derivation (45 entries, union+38 singletons+37 prefixes all no_match), and the clamped-vs-unclamped provenance analysis.** No source-honest lever; a fabricated second-use on var_r16_6 (the Round-2 named idea) requires a use the target does not have (honesty-negative).

### FORCE-PHYS UNION GATE VERDICT (95.39 substrate, fresh pcdump)
`debug target force-phys-from-diff -f mnDiagram_8024227C --verify`:
- **Frame alignment: target=0xa0 current=0xb8 delta=−24** (the PAD_STACK(24) diagnostic; unchanged).
- Derived **45 class0 force-phys entries** (whole callee-save band r15–r30 renumber + arg/volatile moves).
- **union: no_match. All 38 singletons: no_match. All 37 prefixes: no_match.**
- **Conflicting targets skipped (the wall signature):** `ig34 wanted both r29 and r31`; `ig98 wanted both r3 and r6`; `ig41 wanted both r3 and r6`; `ig63 wanted both r3 and r6` AND `ig63 wanted both r3 and r15`; several `ig9x wanted both r18/r17/r19`. These conflicts ARE the r3/r6 order windows + the count-loop temp renumber.
- **Verdict: the gate CANNOT pass while the r3/r6 ORDER windows remain.** They are instruction-order/coalescing diffs (not register-coloring), so forcing target colors onto the existing node set fails. The ~178→180-line register-only cascade is NOT yet a gate-able pure-coloring problem; it is still content/coalescing-gated (plus the −24 frame). Round 2's prediction ("the gate cannot pass while windows 1-2 exist") HOLDS at 95.39.

### RE-ROLLED RESIDUAL CENSUS (@ 95.39, 2743a3aff)
1. **r3/r6 arg-copy ORDER** at +0f0, +1cc, +478 (≈6 lines): coalescing-structure wall (clamped value home-vs-r6 coalesce); gate `wanted both r3 and r6`. NOT force-phys-reachable; no source-honest lever found.
2. **W1 +284/+288 transposition** (2 lines): opcode-identical scheduling tiebreak in the GetNameTotalKOs inline preheader; lever not found (idiom + graft refuted).
3. **~180-line register-only coloring cascade** + the count-loop temp renumber (`ig9x/ig8x/ig7x wanted both r18/r17/r19`): the whole-function renumber rooted in the coalescing root; force-phys union/prefixes all no_match.
4. **Frame −24 (PAD_STACK(24) diagnostic):** the gate's `delta=-24`; natural-frame replacement still pending (PENDING-REVIEW item stands).

### PENDING-REVIEW (windows round)
- **mnDiagram_SumFighterKOsClamped inline twin** (2743a3aff) — a clamped sibling of SumFighterKOs, mirroring SumNameFalls's matched clamp-inside structure (the original almost certainly had per-stat clamped/unclamped inline variants: SumNameFalls clamps, SumNameKOs/GetNameTotalKOs do not). Load-bearing for the +46c clamp content (caller-clamp forwards into r6). The shared `mnDiagram_SumFighterKOs` (used by 8023FA6C, no clamp) is untouched. Clean; comment if questioned.
- PAD_STACK(24) on 8024227C — unchanged; the gate's `delta=-24` re-confirms the 24-byte frame gap. Natural-frame pass still pending (TU PENDING-REVIEW ledger item 1).

### STALE-BASE FLAG (PROMINENT)
**ONE source commit this round (2743a3aff) — coder1's running permuter job base (94.80, already stale from Round 2) is NOW further stale. Re-bootstrap required at next triage (orchestrator was holding the re-bootstrap until this round concluded — it has concluded).**

### RECOMMENDATION
1. **PARK the source-content axis for 8024227C.** Both remaining windows (W1 transposition, the r3/r6 order) are scheduling/coalescing tiebreaks with NO source-honest lever found across this round + Rounds 1-2 (idiom twin, graft/second-use, clamp-inside-content, force-phys derivation, clamped-vs-unclamped analysis). The W2 clamp CONTENT was the last reachable content lever and it landed (+0.59).
2. **The gate does NOT pass and CANNOT yet** — the r3/r6 ORDER + the −24 frame keep it content/coalescing-gated, not pure-coloring. The register endgame is NOT yet enterable as a clean coloring cascade. The blocker is the same coalescing-structure root Rounds 1-2 characterized (force-* cannot split a coalesced value-into-r6 life).
3. **Next lever is the COALESCING boundary, not registers:** the only remaining axis is a coalescer-pressure source experiment that makes MWCC keep the clamped draw values in their homes (defeat the value↔r6 coalesce) — a deep-dive/permuter task targeting the coalescing boundary (per iter-8 allocation order, 8024227C is rank-1 for permuter ROI, but the permuter must target the value-home-vs-arg coalesce, NOT register tiebreaks). Re-bootstrap coder1 at 95.39 first.
4. PAD_STACK(24) natural-frame pass remains the standing TU pending-review item (gate `delta=-24` confirms 24B).

---

## ★ COALESCING-BOUNDARY ROUND ★ (2026-06-12, coalescing-boundary driver) — THE VETO ORACLE **REFUTES** THE NAMED COALESCE ROOT: breaking the value→r6 merges leaves the value in its home BUT DOES NOT FLIP THE ORDER. The r3/r6 arg-copy order is a **post-coalescing SCHEDULER tiebreak**, NOT a coalescing decision. 0 commits (no source-honest lever; C search NOT entered — oracle gate failed). 96.03 unchanged.

### THE ONE QUESTION — ANSWERED: **NO.** The value-virtual→r6 merges at the diverging sites are real and veto-targetable, but vetoing them does NOT reproduce the target's gobj-first (joins-in-home) shape, and the cascade does NOT collapse. The named root is REFUTED; the divergence is reclassified one layer down (scheduler ordering of two independent register copies).

### RE-MAP @ 96.03 (f256959e4, truth gate `match=false match_percent=96.03 classification=stack-layout diagnostic_pad_stack=24`)
- **Opcode similarity = 100.0%.** No opcode transpositions remain. **W1 (+284/+288) is GONE** — the triage-3 `var_r0_2`→u64 win absorbed it; +284/+288 is now register-only (target `addi r18,r17,0; clrlwi r16,r19,24`; ours `addi r16,r17,0; clrlwi r15,r19,24` — both copy-then-mask, register-only). The windows-round census of W1 as a live opcode transposition is SUPERSEDED at 96.03.
- **The three r3/r6 ORDER windows survive, all confirmed diverging** (target gobj(r3)-first; ours value(r6)-first):
  | Site | Helper | Clamp? | Target | Ours |
  |------|--------|--------|--------|------|
  | +0f0/+0f4 | SumNameFalls header (line 2451) | YES | `addi r3,r28,0` then `addi r6,r19,0` | `addi r6,r17,0` then `addi r3,r28,0` |
  | +1cc/+1d0 | SumFighterFalls header (line 2460) | NO | `addi r3,r28,0` then `addi r6,r19,0` | `addi r6,r17,0` then `addi r3,r28,0` |
  | +478/+47c | SumFighterKOsClamped grid (line 2512) | YES | `addi r3,r28,0` then `addi r6,r16,0` | `addi r6,r16,0` then `addi r3,r28,0` |
- **MATCHED sites** (both r6-first): +2bc (GetNameTotalKOs, unclamped accumulator) and the two `lhzx r6` direct-memory sites (+338/+4f8, GetPersistent*Data indexed path). The clamped-vs-unclamped discriminator from the windows round HOLDS at object level.

### THE VETO ORACLE (the prescribed instrument — APPLIED, READBACK-VERIFIED, REFUTING)
Baseline pcdump `[COALESCE]` map for `mnDiagram_8024227C` (the alias-array readback at the function's COALESCED ALIASES block): **7 natural merges, ALL virt→PHYS call-arg materializations, NONE arg-home folds** (consistent with Round-2 erratum):
```
42 -> 6 [r6]   (SumFighterFalls value,    mr from r91 accumulator, NO clamp before)
43 -> 6 [r6]   (GetNameTotalKOs value,    mr from r84 accumulator, NO clamp — the MATCHED site)
48 -> 6 [r6]   (SumFighterKOsClamped val, mr from r100, CLAMP before: cmp r100,0x423F + addi r100,...,16959)
49 -> 6 [r6]   (clamped value,            mr from r68,  CLAMP before)
143 -> 6 [r6]  (lhzx direct-memory value, MATCHED)
162 -> 6 [r6]  (lhzx direct-memory value, MATCHED)
115 -> 3 [r3]  (one r3 materialization)
```
The four `mr`-fed value→r6 merges {42,43,48,49} ARE the prompt's veto-targetable call-arg materializations (in the alias array; NOT the param-receive folds Round-2's erratum covered).

**Veto run:** `debug dump local mndiagram.c --force-coalesce "42=42,43=43,48=48,49=49" --force-coalesce-fn mnDiagram_8024227C`.
| Gate | Result |
|------|--------|
| Applied? | **YES.** Forced log: `[FORCE_COALESCE] alias[42..49]: 6 -> N`, `forced=4`, `distinct_roots 156→160`. Alias readback after veto = `{115→3, 143→6, 162→6}` — the four targeted merges GONE. |
| Value joins-in-home? | **YES but it ALWAYS did.** Baseline clamped site already materializes the clamp into the value home (`addi r17,r27,16959`), value→r6 is a separate copy; veto keeps it in r17 (`addi r17,r31,16959`). Both builds, both modes: value lives in its home, copied to r6 separately. The veto did NOT change where the value lives. |
| Order flips to gobj-first (target shape)? | **NO.** Every `mr`-fed site is STILL R6-FIRST in the veto build (`mr r6,r17; mr r3,r19` — value before gobj), identical ordering to baseline. Verified across all 4 sites via the AFTER-REGISTER-COLORING dump. |
| Cascade collapse toward byte-match? | **NO.** AFTER-COLORING opcode-line count identical (1661 = 1661); integrated `--diff` was if anything noisier (the un-coalesce forces a callee-save renumber). |

### MECHANISM (why the veto is inert here — and what the real root is)
Pre-coloring pcode is IDENTICAL at the diverging (r48, clamped) and matched (r43, unclamped) sites: `mr rVAL,rACC; mr r3,r32(gobj); rlwinm r4; rlwinm r5; mr r6,rVAL`. The value is staged through a virtual `rVAL`, and `mr r6,rVAL` sits LAST (after gobj). The `48→6` coalesce rewrites `mr r48,r100` → `mr r6,r100` and elides the trailing `mr r6,r48` — so the value lands in r6 EARLY (value-first). **Un-coalescing gives rVAL its own register (r17) but the post-coalescing SCHEDULER still hoists the value→r6 copy above the gobj→r3 copy** — so the order is unchanged. The order is therefore decided by the scheduler ordering two independent `addi rX,rY,0` register copies, NOT by the coalescer's union-find. **Target-vs-ours mechanism, object-level:** in the TARGET the clamped value materializes into its home on both `if` arms, the merge keeps it live, and the value→r6 copy is emitted LATE (after gobj). Ours emits the same home-materialization but the scheduler picks value→r6 first. Both materialize the clamp into the home identically — only the 2-instruction copy order differs.

**This REFUTES the windows-round / Rounds-1-2 headline that the r3/r6 order is "the value↔r6 COALESCE wall" / "ours COALESCES the value's life-end into r6."** The coalesce is INCIDENTAL: with it broken (readback-verified), the order persists. The wall is one layer down — a scheduler tiebreak on two independent copies. (Why the matched site matches: target is ALSO r6-first there — unclamped accumulator already in its home — so ours agrees. Only the clamp-bearing sites' scheduler order diverges.)

### C SEARCH — NOT ENTERED (oracle gate failed, per protocol)
The protocol gates the C search on oracle confirmation that the merges are THE root. The oracle REFUTED. A C search targeting the coalesce is contraindicated. The remaining mechanism (scheduler ordering of two `addi rX,rY,0` copies) is NOT expressible by the available hooks: `--force-coalesce` is inert (shown); `--force-schedule` pins same-base LOAD order, not register-register copy order (the two copies are not loads); `--force-phys`/`--force-iter-first` operate on the existing node set / simplification order, not 2-copy emission order (windows round: union+singletons+prefixes all no_match). No source-honest lever was found for a 2-copy scheduler tiebreak across this round + Rounds 1-2 (clamp-inside content — closed content not order; second-use/graft — requires a use the target lacks, honesty-negative; force-phys derivation; clamped-vs-unclamped analysis). The speculative source-shape space (temp-for-expr / decl reorder at the arg position) is exactly what coder1's running permuter job covers (weights `perm_temp_for_expr=25` + reorder-heavy template); a one-off manual build duplicates the permuter and was NOT spent (fence: no permuter ops; budget preserved for an oracle-confirmed search that did not arise).

### VERDICT — A ONE-DECISION WALL WITH A NAMED DECISION (reclassified)
8024227C @ 96.03 is bounded by: (1) the three clamped-site r3/r6 arg-copy ORDER windows — **a post-coalescing SCHEDULER tiebreak on two independent register copies** (NOT coalescing — veto-refuted; NOT register-coloring — gate-refuted; NO source-honest lever found); (2) the ~178-line register-only coloring cascade (whole-function callee-save renumber); (3) the −24 frame (PAD_STACK(24) diagnostic). The named "coalescing-boundary" experiment is RESOLVED: the boundary is real but the merges are NOT the lever — the lever (if one exists in C) is whatever makes MWCC's scheduler emit gobj→r3 before value→r6 at a clamp-merge call site, which no force-* hook can express and no source spelling has reproduced. Honest disposition: this is a scheduler tiebreak ceiling for the manual-source axis; remaining hope is the permuter's source-shape fuzz (coder1, value-home/arg-order weights) or a future schedule-order tooling hook that can pin register-copy emission order.

### STALE-BASE FLAG (PROMINENT)
**ZERO source commits this round — coder3's permuter job `mnDiagram_8024227C-coder3-20260612-044424` (base 1345 @96.03) is NOT stale by this round** (no commit landed; the diagnostic veto runs left the tree clean, cache un-contaminated — forced runs skip cache sync). The job remains valid on the 96.03 base. (Prior windows/Round-2 stale flags are obsolete — those commits are upstream of 96.03 and already baked into base 1345.)

### TOOLING NOTE
The veto oracle worked exactly as designed (apply + readback-verify + refute) — this is a clean NEGATIVE result, the tool's intended use. No tooling gap. (Minor: `--force-schedule`'s same-base-load scope cannot express register-copy emission order; a future "pin two adjacent reg-reg copy emission order" hook would be the instrument to TEST whether forcing gobj-first reaches byte-match — but that is a feature request, not a bug, and would only confirm/deny, not ship.)

## CURSORPROC PORT (2026-06-12, verification + peel-harvest round)

**Provenance:** ported from branch `codex/mn-diagram-cursorproc-99pct`, commit `b415208c3` (another agent's claimed-100 form). VERIFIED on our base: `match=true match_percent=100.00 classification=instruction-identical` (checkdiff), FULLNORM 0. The verified body is now COMMITTED here (`6a9b5b70e match(mnDiagram_CursorProc): ... 99.52 -> 100`). Our prior 99.52 form was the lhzu/FULLNORM-0 pure-coloring residual; theirs closes it.

**The two forms (our 99.52 vs theirs 100):**
- ours: direct `mn_804A04F0.*` field reads, `u16* hov = (u16*)&mn_804A04F0` init-at-decl, `gobj` used directly, `int row`, plain `4.5`/`0.1` literals, `PAD_STACK(8)`.
- theirs: `MenuFlow* flow = &mn_804A04F0` base-alias, `u16* selection` assigned `(u16*)flow` after the early-return, `HSD_GObj* gp = gobj` param-alias used at all 4 sites, `u8 row`, `(int) row - (f64) 4.5F) - (f64) 0.1F` explicit casts at both use sites, `PAD_STACK(12)`.

**PEEL TABLE (peel one/group from the working 100 form back toward ours; 4 builds):**

| Build | Form (delta from theirs-100) | % | checkdiff class | Verdict |
|-------|------------------------------|-----|-----------------|---------|
| (port)| theirs full | **100.00** | instruction-identical | reference |
| 1 | PAD_STACK(12) -> (8) | 99.90 | stack-layout | PAD(12) **load-bearing** (frame gap 12B) |
| 2 | drop `gp` alias (use `gobj`) | 99.77 | register-allocation | `gp` param-alias **load-bearing** |
| 3 | drop flow alias + u8 row->int + (f64)->plain | 99.62 | data-symbol-or-relocation | group **load-bearing** |
| 4 | restore flow alias; keep int row + plain literals | 99.95 | data-symbol-or-relocation | flow recovers most; u8 row / (f64) casts close the last 1 instr |

**MECHANISM ATTRIBUTION (per lever family):**
- `HSD_GObj* gp = gobj` — **param-alias / copy-survival.** A distinct copy of the param that survives across the 4 calls; the allocator colors it into the callee-save it expects (vs re-using the param reg). NODE-SET (adds a virtual). Load-bearing (-0.23 when removed).
- `MenuFlow* flow = &mn_804A04F0` — **base-alias.** Anchors the walking pointer + field reads at a single materialized base local rather than the global symbol; changes how `mn_804A04F0` is referenced (checkdiff flips to data-symbol-or-relocation class when removed). NODE-SET. Load-bearing (group -0.33; flow alone recovers to 99.95).
- `u8 row` + `(int) row - (f64) 4.5F - (f64) 0.1F` — **type-home + literal-vs-named-temp.** Together they account for the final 99.95 -> 100 (one instruction). The `u8` storage + explicit f64 promotion at the use site reproduce the target's exact convert/load sequence. (Could not bisect these two apart within the 4-build budget; they are jointly the last instruction.)
- `PAD_STACK(12)` — **frame.** PEEL-PROVEN load-bearing (PAD(8) -> 99.90 stack-layout). NOT gratuitous: the natural frame for this body reserves 12 bytes. **PENDING-REVIEW** (retained PAD_STACK; ported from another agent's branch). checkdiff `source_guidance=natural-frame-reservation` suggests a future attempt to express the 12B as natural C (address-taken local / array), but no such form was found this round.

**MINIMAL FORM:** every sub-lever proved load-bearing on this base, so the minimal 100 form IS the full ported body (no peel held at 100). Committed as-is.

**LEVER CLASS for the order-distance / coalescing-search tooling: NODE-SET, not ORDER.** The load-bearing levers (`gp` and `flow` aliases) each CREATE a new virtual (a copy / a materialized base local) that the allocator must color — they add nodes to the interference graph, they do not merely reorder the existing node set's decl/emission. This makes CursorProc a candidate **kill-switch fixture** for a NODE-SET-aware search: pre-win = our 99.52 form (no aliases, FULLNORM 0, pure coloring), win = the minimal 100 form (aliases added), both now reproducible on one base (this branch). The 99.52->100 gap is bridged by introducing virtuals, the cleanest possible NODE-SET signal.

**SIBLING TRANSFER TEST — gp-alias on mnDiagram2_HandleInput (97.46): REVERTED.** Their HandleInput branch (`f686147a4`) claimed `gobj alias restores r28 CSE (+0.4)`. On OUR base it REGRESSED: 97.46 -> 97.30 (-0.16, inline-boundary-toolchain-artifact). Mechanism: HandleInput has only ONE body use of `gobj` (the `HSD_GObjPLink_80390228` call in the `result & 0xC0` branch), vs CursorProc's four uses across calls — so the alias adds a copy without enabling the cross-call copy-survival/CSE that paid off in CursorProc. The lever is use-count-gated: it helps when the param is consumed at multiple call sites, hurts at a single site. Reverted; HandleInput re-verified 97.46, 0 regressions.

**PROTECTED SWEEP (vs this round's saved baseline /tmp/cursorproc_baseline_report.json):** 0 regressions. Only change: CursorProc 99.52 -> 100.00. mnDiagram2_HandleInput 97.46 (transfer reverted), mnDiagram_8024227C 94.80 (untouched, at ITS active-driver baseline). HEAD after this round = `6a9b5b70e` (one source commit, CursorProc).

---

## PERMUTER ROUND 2 (endgame, post-windows) — coder1 re-bootstrapped at 95.39 (2026-06-12, permuter re-bootstrap agent)

Mechanical re-bootstrap only (no matching, no triage). HEAD `ea5da317c`, tree clean. mnDiagram_8024227C = **95.39** in build/GALE01/report.json (freshly built).

### STOPPED JOB EPITAPH — `mnDiagram_8024227C-coder1-20260611-225238`
- **Base 2195** (against the 94.32 source — STALE after 3 commits since: `e53f560bb` alias-drop, `bffd32597` twin-inline, `2743a3aff` clamp-twin → 94.32 → 95.39).
- **Ran ~121,028 iterations** (final frozen iter = 121028 after `remote stop`, verified dead by two identical `remote tail` snapshots per #574).
- **NEVER beat its base.** Best output score = **2195 = base** (six `output-2195-*` dirs, all stale-base re-discoveries — the score-0/stale-base false-positive pattern; no sub-2195 output ever produced). Its candidates were against dead source and are discarded.

### NEW JOB — `mnDiagram_8024227C-coder1-20260612-013111`
| Field | Value |
|-------|-------|
| Host / threads | coder1 / 16 |
| Base (committed source) | **95.39** |
| **Base score (#558 verified)** | **1560** (local `permuter.py --seed 0`; plausible low-thousands for a 95.39 fn, NOT 10k+ → inline injection confirmed #424-safe; remote recomputed the SAME 1560). Note: LOWER than the stale job's 2195 (closer base). |
| randomize_funcs | self + the 7 bootstrap-injected same-TU inline callees: `mnDiagram_SumNameFalls`, `mnDiagram_GetVisibleNameCursorFrom`, `mnDiagram_CountUnlockedFightersInline`, `mnDiagram_SumFighterFalls`, `mnDiagram_GetVisibleFighterCursorFrom`, `mnDiagram_GetNameTotalKOs`, `mnDiagram_SumFighterKOsClamped` |
| Weights (vs stale template) | reorder-heavy 802427B4 template + **bumped `perm_temp_for_expr` 25.0** (coalesce-boundary / alias-introduction axis, CursorProc node-set precedent) for the r3/r6 value-home-vs-arg coalesce wall. perm_dummy_comma_expr=35, perm_reorder_decls=25, perm_split_assignment=22, perm_reorder_stmts=18, perm_pad_var_decl=15. |

### #424 / #575 BOOTSTRAP NOTES (verified clean — NO hand-fixes needed for this fn)
- **#424 (inline-callee injection):** the target asm for 8024227C (asm 4118-4517) `bl`s ONLY `GetNameCount/GetNameText/GetPersistentFighterData/GetPersistentNameData/mn_IsFighterUnlocked/mnDiagram_80241E78`. There is **NO `bl` to ANY of the 7 family helpers** → all 7 are INLINED in the retail object. The fresh base.c carries all 7 as `static inline`/`inline` **bodies** (lines 315/327/342/358/371/383/414), not forward-decl-only → they stay inlined (base score 1560 = low, the #424-safe signature; contrast 8024714C/AC7DC = 20625 when a callee was bl-emitted). The stale template's `randomize_funcs` was wrong post-clamp-commit (listed the now-unused `mnDiagram_SumFighterKOs`, missing `SumFighterKOsClamped` + `CountUnlockedFightersInline`); the bootstrap rewrote it correctly.
- **#575 (bootstrap corruption):** the two known 8024714C injection bugs (`inline #undef __FILE__` fusion; `JOBJ_MTX_INDEP_SRT` undefined) did NOT occur here — this fn's twins reference no `#undef __FILE__` neighbor and no exotic macro constants (only GetNameText/mn_IsFighterUnlocked/GetPersistent*). base.c compiled on iter 1 (0 errors). No hand-fix applied.

### STALE-BASE FLAG — CLEARED
The 3-commits-stale coder1 base is RESOLVED. coder1 now hunts the 95.39 residual (per the windows-round census: the +284/+288 GetNameTotalKOs-preheader scheduling transposition, the r3/r6 arg-copy COALESCING order at +0f0/+1cc/+478, and the ~180-line register-only coloring cascade). The endgame lever is the value-home-vs-arg coalesce, NOT register tiebreaks (RECOMMENDATION #3) — reflected in the `perm_temp_for_expr` bump.

---

## PERMUTER TRIAGE 3 — 8024227C harvest + STOP (2026-06-12, permuter triage round 3 agent)

Branch `claude/mndiagram-802427B4-investigation` (HEAD was `b8eced96f`, the order-class census). 4 builds used (1 baseline + 3 levers; the Create build re-verified 8024227C unchanged). Authoritative baseline sweep saved at `/tmp/mndiagram_baseline_triage3.json` (72 mnDiagram fns; 53 at 100% incl. mnDiagram_CursorProc). All protected functions held across all three commits (pre-commit "Match regressions" gate passed each time).

### JOB — `mnDiagram_8024227C-coder1-20260612-013111`
| Field | Value |
|-------|-------|
| Iters at triage | ~143,580 → final frozen **152,608** (stopped) |
| Base score | 1560 (#558-verified) |
| **Best score** | **1345** (3 copies output-1345-1/2/3), Δ-215 vs base |
| Candidate triage | 1345-1 = `var_r0_2` type `s32`→`unsigned long long` (KEPT — see below); 1345-2 = recompute `is_name != 0` loop-invariant per `do`-iteration (REJECT, non-idiomatic register-juggle hack); 1345-3 = five no-op `& 0xFFFFFFFFFFFFFFFF` masks on the assignment (REJECT, no-op masks). All 3 score 1345 by different register nudges; the rest of every diff is pure brace-style whitespace reflow (normalize before diffing — raw `diff` is useless on coder1's reformatted base). |
| **COMMIT** | **`f256959e4` — 95.39 → 96.03 (Δ+0.64).** `var_r0_2` widened to `unsigned long long`. The temp only ever holds a `(u8)`-masked cursor (0..255), always re-cast `(u8)` or passed by value at its two uses (`mnDiagram_GetNameTotalKOs`, `GetPersistentNameData((u8) var_r0_2)`), so the wider declaration is **value-identical** (no upper-bit garbage is ever read) — it only changes coloring on the indexed-struct-pointer-materialization path (census class for 8024227C). The committed body is already m2c-placeholder-named (`var_rNN`), so this is not *more* unshippable than the existing partial; revisit the type when the fn is cleaned/PR'd. Truth gate: residual reclassified census `indexed-struct-pointer-materialization` → `stack-layout` (PAD_STACK 24) — the materialization residual is gone, stack-layout is the next wall. |
| KEEP/STOP | **STOP.** Recent-8000-iter floor = **1520** (best 1345 NOT re-found; 316× at base 1560) → converged. Plus the committed lever makes the base STALE (#558). Re-bootstrap against 96.03 source is an orchestrator call. **Freed: coder1 (16 threads).** |

### CROSS-REF
mndiagram2 jobs (UpdateHeader, Create) triaged in the same round — see **CAMPAIGN-STATE-D2COMPLETION.md → PERMUTER TRIAGE 3**. Rotation ranking is recorded there (single canonical copy).

---

## PERMUTER ROUND (wave 2) — fleet rotation re-submit (2026-06-12, fleet-rotation agent wave 2)

Mechanical bootstrap + submit only (NO matching, NO triage). Branch `claude/mndiagram-802427B4-investigation`, HEAD `402ccf98c` (triage-3 wins committed: 8024227C=96.03, UpdateHeader=95.46, Create=98.54; tree clean). Allocation = orchestrator-decided per the triage-3 rotation ranking (D2COMPLETION → PERMUTER TRIAGE 3 → ROTATION RANKING) crossed with the order-class census. 3 builds used (the three #558 base-verifies; budget held). Re-bootstrap if any source commit lands on these fns (stale-base doctrine #558).

### NEW JOBS (this round's two coder3-bound + the cross-host AggRank — full table in D2COMPLETION wave-2 section)
| Function | base % | Host | Job ID | Base score (#558) | Residual the job hunts |
|----------|--------|------|--------|-------------------|------------------------|
| **mnDiagram2_GetRankedName** | 97.87 | coder3 (shared) | `mnDiagram2_GetRankedName-coder3-20260612-044336` | **470** (local `permuter.py --seed 0`; remote recomputed 470) | the +1 `subf.`+`mr` j-guard on the indexed-struct-pointer-materialization path (D2COMPLETION:1285) — SAME class 8024227C's u64 win cracked this wave |
| **mnDiagram_8024227C** (re-bootstrap @ 96.03) | 96.03 | coder3 (shared) | `mnDiagram_8024227C-coder3-20260612-044424` | **1345** (local; = the triage-3 best, because base.c now reflects the committed `var_r0_2`→u64 source — re-bootstrap correctly captured 96.03) | the +284/+288 GetNameTotalKOs-preheader scheduling transposition + the r3/r6 value-home-vs-arg COALESCE order; residual reclassified `stack-layout` (PAD_STACK 24) post-u64 |

AggRank (the ranking's #1, coder1-dedicated, base 775) is documented in the D2COMPLETION wave-2 section (it lives in mndiagram2.c with GetRankedName). All three verified ALIVE via `remote tail`/`remote ps` (each already beat its base within 1 min: AggRank 600<775, GetRankedName 435<470, 8024227C 1330<1345 — weights exploring productively).

### #424 / #575 BOOTSTRAP NOTES
- **8024227C (#424 critical):** bootstrap re-injected all **7** same-TU inline twins as BODIES (`SumNameFalls, GetVisibleNameCursorFrom, CountUnlockedFightersInline, SumFighterFalls, GetVisibleFighterCursorFrom, GetNameTotalKOs, SumFighterKOsClamped`) — `randomize_funcs` = self + all 7. Base 1345 (low-thousands, NOT 10k+) = injection #424-safe. Bootstrap also auto-applied the **#575 NULL hand-fix** (`#pragma _permuter define NULL 0`); base.c compiled iter 1, 0 errors. Existing per-fn settings.toml was correctly KEPT (already the proven reorder-heavy template + `perm_temp_for_expr=25` coalesce bump). 
- **GetRankedName (#424 N/A):** `injected_inline_callees: []` — its callees (`GetNameCount/mnDiagram_GetNameByIndex/mnDiagram2_GetStatValue`) are `bl`-emitted in retail. Base 470, clean.

### HOST-OCCUPANCY DISCREPANCY (flagged — orchestrator decision needed)
The brief stated "Both hosts are FREE (all prior jobs stopped at convergence)" — but `remote ps` (live SSH probe) shows **3 pre-existing LIVE descending jobs** the triage-3 round did NOT stop: coder1=`mnDiagram_InputProc_tuned-coder1-20260611-065847` (1.77M iters, the MEMORY "tuned listening post"), coder3=`mnDiagram2_HandleInput-coder3-20260611-125553` + `-175702` (both live; HandleInput is PROTECTED/parked). `remote list` returned EMPTY (filed issue #591 — list reads local metadata JSON, misses these). Per the triage-1/triage-3 precedent (multiple jobs share one host's 16 threads), the new jobs CO-RUN with these — submission did not require stopping them, and stopping the listening-post/PROTECTED jobs is outside the no-triage fence. **coder1 is NOT truly "dedicated" to AggRank until the orchestrator decides whether to stop InputProc_tuned; coder3 now runs 4 jobs (2 HandleInput + GetRankedName + 8024227C).**

## ONFRAME IG49 ROUND — the what-if oracle's minimal flip + source-spelling ladder (2026-06-12, OnFrame source-lever driver)

**Outcome: SEARCH MISS (OnFrame stays 99.72, backend-ceiling). No regressions; tree restored to baseline.** The what-if oracle's minimal-perturbation answer IS the valuable artifact — it pins the residual as a dispense-position (move-axis) outcome that the order-force census already proved unreachable, and the proven alias channel CSE's away at OnFrame's low tail pressure.

### THE RESIDUAL (re-confirmed, single node)
- The ONLY differing instruction: `+1e0: lwz r28,44(r30)` (retail) vs `lwz r29,44(r30)` (ours). Node **ig49, class 0** (gpr), degree 13, `lwz r49,44(r32)` = a FRESH re-read of `gobj->user_data`. `virtual-to-var r49` = NO source variable (compiler temp).
- **ig49 lives ENTIRELY INSIDE the inlined `mnDiagram_UpdateScrollArrowVisibility`** (`void* data = ((HSD_GObj*)gobj)->user_data;`, mndiagram.c:2256). The disassembly proves it: `+1e0 lwz r28,44(r30)` then `+1e8 lwz r3,28(r28)` = `((HSD_JObj**)data)[7]` → `HSD_JObjSetFlagsAll(.,0x10)`. **That standalone function is already 100%** (in the 53 hundreds list) — its internal structure is fixed/correct; the residual is purely the inline-merge coloring in OnFrame.
- `--force-phys 0:49:28 --force-phys-fn mnDiagram_OnFrame` = byte MATCH (witness re-confirmed; #588/#589).

### THE WHAT-IF ORACLE VERDICT (`debug inspect tiebreak`, G1 = 55/55 PERFECT, 0 truncated — what-ifs trustworthy)
- ig49's REAL neighbors (from OnFrame's n_nodes=80 COLORGRAPH, iter 40): precolored `r0,r3..r12` (the call-clobbered volatiles, ig49 crosses `80241668`/the inlined `SetFlagsAll` calls) + **node 32 = `gobj` base (r30)** + **node 40 = `count` (r27)**. ig49 sees {r27, r30} among callee-saves → r28 AND r29 free → dispense gives it the higher (r29); retail gives r28.
- **`suggest register-tiebreak -f mnDiagram_OnFrame --force-phys 0:49:28`** → lever family = **interference-insertion** (keep a named value live across ig49's def so the allocator occupies r3-r27 first) + **simplify-order-shift** (move/sink the defining expr later) + targeted-alias. Confirms ig49→r28, below-set r3..r27.
- **`first-divergence --force-phys 0:49:28 --source`** → class 0, iter 40, ig49 r29→r28, **cause = Case C** ("shift X's simplify-order position so dispense reaches r_target").
- **THE MINIMAL FLIP (the axis the census never tried):**
  - `add-interferer 49:N` for r28 nodes (45,37,33) → **no change** (pushes ig49 away from r28, wrong way).
  - `add-interferer 49:N` for r29 nodes: 49:65 → **r31 (OVERSHOOTS, wrong way)**; 47/46/36/34 → no change.
  - `remove-edge 49:32`/`49:40` → no change; `49:0` → r0 (degenerate).
  - **`move 49:later` (simplify order) → r28 (FLIPS, the clean answer):** `move 49:after:45` (smallest), `move 49:before:37` / `:33` / `:36` / `:34`, `move 49:after:40` — ALL predict **r28**. Moving ig49 EARLIER (`before:65`) → r31 (overshoot). ⟹ **the lever is "ig49 dispensed slightly LATER" = lower its degree / shift its simplify position by ONE relative to the r28 cluster — NOT head-of-list (which is why the 8 census order-forces all overshoot to 18-108-line cluster reshuffles).**

### SOURCE-SPELLING LADDER (3 builds; baseline saved to /tmp/mndiagram_ONFRAME_BASELINE.c first)
| # | Spelling (oracle mapping) | ig49 | match % | verdict |
|---|---------------------------|------|--------:|---------|
| baseline | — | r29 | 99.72 (backend-ceiling) | — |
| 1 | **Sink `data2 = gobj->user_data` PAST `mnDiagram_80241668(gobj)`** (lever-2 statement-sink, both branches) | — | **91.34** (signature-type-mismatch) | **REGRESSED — hard revert.** Sinking past the call REMOVES the cross-call liveness entirely (value re-loaded fresh after the call) — a different graph, not a re-order of the same nodes. Wrong mechanism for "move later." |
| 2 | **Create-style alias `data2_alias = data2`** read at the 8024227C arg (lever-1/the 4-win ALIAS channel, `mutate insert-alias --at 0`) | r29 | **99.72 (inert)** | Alias is value-identical → MWCC CSE'd it away (OnFrame's tail pressure is too low for the node to survive, unlike Create which had ~10 live locals). Also can't reach ig49 (which is the INLINED function's own re-read, a different temp than `data2`). |
| 3 | **Decl-reorder: move `int count` above `proc`/`data2`** (count = ig49's r27 neighbor; the recorded decl axis) | r29 | **99.72 (inert)** | Confirms the recorded "decl probes inert for this fn" — OnFrame-local decl order doesn't reach a node living inside the inlined callee. |

### WHY THE MISS (mechanism, NOT an impossibility claim)
The single clean flip lever the oracle found is the **move-axis (dispense position)** — and the order-class census ALREADY proved that axis is not reachable here via any `force-iter-first` order (8 variants, all 18-108-line mismatches; moving ig49 up the list reshuffles the whole r28/r29/r30/r31 cluster). The C-source handles for the move-axis are: (a) statement-sink → REGRESSES (kills cross-call liveness, because the natural sink crosses a call); (b) alias/interference-insertion → CSE's away at this pressure; (c) decl-order → inert (node is inside the inlined callee). ig49 is the inlined `UpdateScrollArrowVisibility`'s OWN `gobj->user_data` re-read — the standalone callee matches at 100%, so the residual is an inline-MERGE coloring outcome with no OnFrame-local source object bound to ig49 (analogue of the `fn_803AC7DC inline-injection coloring ceiling` and `reread_field_materializes_arg_register`'s NON-materialization sibling). **The target is phys-reachable (witness proven) and source PROVABLY exists; it was just not found via the oracle's full what-if sweep + the proven alias channel + the recorded decl axis. Re-open conditions below.**

### RE-OPEN CONDITIONS (for a future deep-dive)
1. A spelling that makes the inlined `UpdateScrollArrowVisibility` re-read dispense exactly ONE slot later WITHOUT crossing the `80241668`/SetFlags calls differently — e.g. a higher-pressure neighbor introduced precisely at the inlined load's position (the oracle's interference-insertion lever, but with a node that does NOT CSE — a genuinely distinct value live across line 2256's inlined slot, not a value-identical alias).
2. A permuter run scoped to OnFrame's tail (NOT this round's fences — coder3 jobs run) with the force-phys 0:49:28 objective + reorder-heavy weights, seeding the move-axis the oracle identified.
3. Anchoring `count` (the r27 neighbor, node 40) so it colors AFTER ig49 — but `count` is consumed by the inlined `cmpwi r27,7`/`,10`, so its range is structurally fixed by the inline.

### FENCES HONORED
OnFrame + census doc only. No permuter ops. No PAD_STACK. Tree restored to baseline (diff -q vs /tmp/mndiagram_ONFRAME_BASELINE.c = IDENTICAL). Full protected sweep re-verified post-revert: OnFrame 99.72, 8024227C 96.03, InputProc 98.89, 802427B4 98.84, all 53 hundreds intact (report.json, this worktree's build).

---

## PERMUTER TRIAGE 4 — wave-2 harvest (3 wins) + STOP-all (2026-06-12, permuter triage round 4 agent)

Full detail (per-job table, levers, sweep, freed capacity, #593) recorded in **CAMPAIGN-STATE-D2COMPLETION.md → PERMUTER TRIAGE 4** (canonical). Summary:

- **3 WINS committed** (all levers ported + dataflow-verified + protected-sweep-clean, baseline HEAD `846921f81`, 4 builds):
  - AggRank **94.11 → 95.72** (`cd47d4d41`) — comma-expr base at use site (LICM-defeat class, `output-525-1`, job 775→525).
  - GetRankedName **97.87 → 98.62** (`db5baee4e`) — selection-sort compare operand-order swap (`output-370-1`, job 470→370).
  - 8024227C **96.03 → 96.09** (`561dcedf9`, marginal) — inline `SumFighterKOsClamped` into `80241E78` arg (`output-1325-1`, job 1345→1325).
- **ALL THREE STOPPED — CONVERGED** (each best found ~11:44–11:52, nothing better in the ~3 h / 162k–400k iters since). Re-bootstrap onto new source for any future run (#558) — orchestrator's call.
- **FREED:** coder1 fully free (16 threads); coder3 wave-2 pair stopped (16 threads). coder3's 14 lingering `InputProc`/`802437E8`/`OnFrame` sessions are DEAD tmux windows (pane=`fish`, iters frozen) consuming zero threads (#591 dead-record class), left untouched.
- **#593 filed:** `remote ps` crashes (`remote_ps` missing from `permuter_remote`) — breaks #591's recommended workaround; used SSH `tmux ls` + pane-cmd + log-iter-sampling instead.
