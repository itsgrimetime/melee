# Campaign State: mnDiagram_80242C0C

## Target Function
`mnDiagram_80242C0C(void* arg0, int arg1, int arg2)` — src/melee/mn/mndiagram.c:2676
Two-loop draw routine (column-header fighter icons + row-header fighter icons).
Each loop: count-unlocked-fighters loop → if(count>i) find-walk resolves `fighter_id`
→ draw block (LoadJoint, AddAnimAll, Req/AnimAll, lb_80011E24, (f32)fighter_id Req,
spacing translate, AddChild).

Called by: mnDiagram_80243434 (matched 100), mnDiagram_InputProc (98.67),
mnDiagram_802427B4 (95.68 — sibling worktree, active driver).

## Status: ITERATION 3 COMPLETE — 96.29 -> 96.34 (commit 80f374d45). Per-loop-locals
form PARTIALLY landed: B2b joint_data-per-loop BYTE-EQUAL at the row site; sp_jobj
slots SEPARATED (84/80, placement residual vs 76/68); walk-init order matched.
THE HOIST IS THE WALL: four spellings refuted this iteration (idx-derivation,
(0,..) comma-expr, int loop-var types, k=count). Budget 4/4. See ITERATION 3 section.

(Iteration 2: 94.98 -> 96.29, commits 78266c20a + 23fd94dec — MECH-A & 0xFF idiom,
MECH-B1 FaceB per ruling.)

Branch: claude/mndiagram-80242C0C-campaign (worktree mndiagram-80243434-campaign).
Protected (hard stop): mnDiagram_802437E8 (100), mnDiagram_80243434 (100),
mnDiagram_InputProc (98.67); mnDiagram2_HandleInput (97.46) in mndiagram2.c.

---

## STEP 1 — BASELINE (verified, clean branch, default checkdiff)

| Anchor | Value |
|--------|-------|
| Match (fuzzy) | **94.98%** (checkdiff --summary); 95.0% rounded in side-by-side header |
| Opcode similarity | 93.2% |
| Line delta | **+2 — TARGET has MORE** (expected 321, current 319). NB: prompt said "ours has +4"; the clean-baseline truth is target +2. Internally consistent: the two missing `clrlwi` truncations (one per loop) = exactly the +2. |
| Hunks | 7 |
| Line edit (full-penalty) | 171 instrs / sim 36.0% |
| Classification | signature-type-mismatch; diagnostic_pad_stack=32 (PAD_STACK(32) present at line 2693) |
| Build | configure.py + ninja OK (exit 0) |
| Instr counts | EXPECTED 267 / CURRENT 265 (matches +2) |

checkdiff header machine-flags:
- "call shape differs; check prototypes, return types, and inline boundaries"
- "8 differing paired lines reference stack slots"
- "**94 differing paired lines reference data/symbol relocations**" ← dominant; mostly the
  BSS section-anchor ceiling, NOT structural
- "BSS section-anchor ceiling: mnDiagram_804A0750 vs ...bss.0" ← our build references the
  assets global via section-anchor `.bss.0`; target uses the named symbol. RELOC NOISE, not a
  matchable divergence. Inflates the visible diff massively.
- "8 differing paired lines look register-only after normalization"

### CRITICAL framing: the diff is NOT mostly structural
After stripping reloc-only lines, the OPCODE-ONLY difflib alignment (mnemonic sequence,
registers blanked) collapses to **5 tiny divergence sites**. The rest of the ~200 visible
diff lines are (a) the BSS section-anchor reloc difference on every `mnDiagram_804A0750`
reference, and (b) a whole-function register-rename cascade (different GPR numbers, same
roles) downstream of the few real sites. This is a near-clean function with a small
mechanism, in the same family as the closed 80243434 wall (register cascade off a small root).

---

## STEP 2 — PRECISE STRUCTURAL MAP (difflib opcode alignment, NOT checkdiff paired view)

Opcode-only difflib (EXP 267 mnemonics vs CUR 265) yields exactly these non-equal blocks:

| # | difflib block | Offset (tgt) | What it is | Class |
|---|---------------|--------------|-----------|-------|
| S1a | `insert CUR[11]='add'` | tgt +02c region | **Ours HOISTS `&sorted_fighters[arg2]` (`add r30,r31,r24`) before the col loop.** Target computes it INSIDE the if-block at +074 (`add r19,r31,r24`). | scheduling/placement (count-neutral; cascades regs) |
| S1b | `replace EXP[16]='addi' / CUR[17]='li'` | tgt +040 / cur +03c | count/k init shuffle (`addi r21,r26,0` vs `li r20,0; li r21,0`) — downstream of S1a/S2 reg cascade | register cascade |
| S1c | `replace EXP[29]='add' / CUR[30]='addi'` | tgt +074 / cur +078 | mirror of S1a: target's in-loop `add r19,r31,r24` aligns against ours' `addi r19,r30,0` (reads the hoisted r30) | scheduling/placement |
| **S2** | `replace EXP[68:80] (12) / CUR[69:79] (10)` | **tgt +110** | **COL-DRAW (f32) conversion: target emits leading `clrlwi r0,r30,24` (mask to u8) before the unsigned-int→float magic; ours does NOT.** +1 instr here. Also `crclr` placement + stack-slot differ (see below). | **type/cast — u8 truncation** |
| S3a | `replace EXP[137]='addi' / CUR[136]='add'` | tgt +234 region | ROW-loop mirror of S1: pointer placement (`addi r22,r21,0` vs `add` shape) | scheduling/placement |
| S3b | `replace EXP[154]='add' / CUR[153]='addi'` | tgt +268 | ROW mirror of S1c (`add r20,r31,r23` in-loop vs ours' hoisted-read) | scheduling/placement |
| **S4** | `replace EXP[193:196] ['clrlwi','lwz','xoris'] / CUR[192:194] ['xoris','lwz']` | **tgt +304** | **ROW-DRAW (f32) conversion: identical to S2 — target's leading `clrlwi r0,r28,24`; ours absent.** +1 instr. | **type/cast — u8 truncation** |

**Two real mechanisms, each appearing once per loop (col + row):**
- **MECH-A (S2+S4): the `(f32) fighter_id` cast — target truncates to u8 first.** This is the
  entire +2 line delta and the "call shape differs" flag. HIGH-VALUE.
- **MECH-B (S1+S3): count-loop base-pointer placement + the joint_data field.** Register
  cascade root. Includes the joint_data field discrepancy (see below).

### MECH-A detail (the conversion idiom), col block tgt +110, row block tgt +304
```
TARGET col (+110):  clrlwi r0,r30,24      <-- MASK fighter_id to low 8 bits (u8)
                    lwz    r3,76(r1)
                    xoris  r0,r0,32768     <-- unsigned-int->f32 magic (flip sign bit)
                    stw    r0,92(r1)
                    stw    r22,88(r1)      (r22 = 0x43300000 hi word, lis 17200)
                    lfd    f0,88(r1)       (load 0x4330000000000000 + value)
                    fsubs  f1,f0,f31       (f31 = the 0x4330..0 bias double, lfd at +038)
OURS col (+114):    xoris  r0,r28,32768    <-- NO clrlwi; xoris straight on r28 (fighter_id)
                    lwz    r3,80(r1)       <-- different stack slot (80 vs 76)
                    ...
```
- Both sides use the SAME **unsigned**-int->float magic (`xoris 0x8000` + `0x43300000` bias).
  The ONLY difference is target's leading `clrlwi rX,rY,24`.
- `clrlwi r0,rX,24` = `rlwinm r0,rX,0,24,31` = mask to low 8 bits = **a `(u8)` truncation**.
- Stack slots: TARGET uses TWO distinct converted-float slots — `r1,76` (col) and `r1,68`
  (row). OURS uses `r1,80` for BOTH. (The magic-double scratch `r1,88`/`r1,92` is shared on
  both sides.) This is the "8 stack-slot-referencing diffs."
- `crclr 4*cr1+eq` (varargs FP marker for the `lb_80011E24(jobj,&sp_jobj,2,-1)` variadic
  call) sits at a different position in the stream (tgt after conversion; ours at [64] before
  the addi r4 setup) — a side effect of the same cast/scheduling difference, not separate.

### MECH-B detail (count-loop pointers), col prologue
```
TARGET:  +028 addi r29,r31,180   <-- r29 = assets+0xB4 = &assets->FaceB[0]  == joint_data base
         (no hoist of sorted_fighters base)
         +074 add  r19,r31,r24   <-- p = &assets->sorted_fighters[arg2]  (INSIDE if-block)
OURS:    +028 addi r26,r31,244   <-- r26 = assets+0xF4 = &assets->ConB3[0] == joint_data base
         +02c add  r30,r31,r24   <-- p = &assets->sorted_fighters[arg2]  HOISTED before loop
```
- **joint_data field: TARGET reads from FaceB (0xB4); OURS from ConB3 (0xF4).** Verified: both
  bases are `r31 + immediate` (no reloc on the addi; r31 = mnDiagram_804A0750), loads are
  `[0/4/8/12]` off the cached base on both sides (tgt r29, ours r26). The joint_data base
  pointer is re-derived at the TOP of each loop on both sides (tgt +028/+224, ours +028/+224
  region). 0xF4 - 0xB4 = 0x40 exactly.
- **sorted_fighters base placement:** ours hoists `add r..,r31,r24` (=`&sorted_fighters[arg2]`)
  to +02c, before the count loop; target computes it inside the `if(count>i)` block at +074.
  This is the `insert add` in the opcode diff. Count-neutral (target recomputes inside), but it
  shifts our register numbering for the whole prologue.

### Register-rename families (downstream cascade — NOT independent sites)
The remaining ~190 diff lines are systematic GPR renames with identical roles, e.g.
col-loop find-walk: count tgt=r26 / ours=r20; remaining tgt=r26 / ours=r29; the draw
`fighter_id` holder tgt=r30/r21 / ours=r28/r29. These all follow from S1/S2 (the prologue
pointer placement and the missing clrlwi shift which virtuals get which colors). Treat as
one cascade, not a census of sites. (Same character as 80243434's r26<->r28 pop-order cascade.)

---

## STEP 3 — MECHANISM HYPOTHESES (evidence per site; ranked levers for iter-2)

### MECH-A (S2+S4): `(f32) fighter_id` should truncate to u8 — HYPOTHESIS CLASS: type/cast
**Evidence:**
- Target emits `clrlwi r0,rX,24` (mask low 8 bits) immediately before the unsigned->f32
  magic, in BOTH the col (+110) and row (+304) draw blocks. Ours never emits it.
- `fighter_id` is declared `int` (line 2680) and the call is
  `HSD_JObjReqAnimAll(sp_jobj, (f32) fighter_id)` (jobj.h:165 — `(HSD_JObj*, f32)`, scalar).
- The mask is REDUNDANT by value (fighter_id is always 0..0x19: a u8 `lbz` load or literal
  0x19) — so MWCC emits it because the SOURCE asked for a u8-width conversion, not from range
  analysis. ⟹ the original cast was **`(f32)(u8)fighter_id`** OR **`fighter_id` is typed `u8`**.
- This matches the cross-campaign PROTOTYPE-VISIBILITY / u8-truncation signature: an explicit
  (u8)/u8-typed value reproduces the `clrlwi` the decompiler dropped. (Same family as
  InputProc's restored `(u8)` casts → clrlwi, campaign doc §1 "Cast restoration".)
- This is the "call shape differs; check ... return types" flag: the (f32) conversion shape
  at the call site differs.
- **NOTE — NOT an inline boundary.** The inline-return refutation rule (an inline that is
  5-7 instrs shorter both arg-forms is NOT an inline): here the difference is exactly +1 instr
  (a single clrlwi) per site, with identical surrounding conversion — a per-arg truncation, the
  classic cast signature, not an inline-return dataflow.

### MECH-B (S1+S3): joint_data field + count-loop pointer placement
**Two sub-hypotheses:**

**B1 (joint_data field) — HYPOTHESIS CLASS: source field discrepancy (MODEL GAP, cause
unattributed):**
- Our source: `void** joint_data = assets->ConB3;` (ConB3 @ 0xF4). Target loads joint_data
  base from 0xB4 (FaceB). 0x40 lower.
- Either (i) the original `joint_data` source field was a DIFFERENT struct member at 0xB4
  (FaceB), or (ii) our `mnDiagram_Assets` field layout/naming around 0xB4-0xF4 is mis-modeled.
  Cannot attribute from disasm alone. Flag for orchestrator: this changes which joint assets
  the icons load — potentially a real behavior difference, so verify against the original
  intent before committing a field swap. The relocation base is identical on both sides
  (mnDiagram_804A0750), only the +imm differs (180 vs 244).
- LEVER (iter-2): try `joint_data = assets->FaceB;` (0xB4). Cheap to test; gated on whether it
  also fixes the register cascade and does not regress callers. Verify behavior plausibility.

**B2 (sorted_fighters base placement) — HYPOTHESIS CLASS: source-shape/hoisting:**
- Ours hoists `p = &assets->sorted_fighters[arg2]` to before the count loop (one `add`,
  count-neutral but reorders prologue regs); target computes it inside the `if(count>i)` block.
- In our source line 2706 `p = &assets->sorted_fighters[arg2];` sits inside `if(count>i)`,
  AFTER `idx=arg2; remaining=i;` — so structurally it IS inside the block already. The hoist is
  MWCC LICM pulling the loop-invariant base out. Target evidently does NOT hoist it.
- LEVER (iter-2): perturb the base computation so MWCC does not hoist — e.g. compute `p` from
  `idx` after the `remaining==0` check, or reorder the `idx`/`remaining`/`p` init statements,
  or a comma-expr LICM-defeat (cf. [[comma_expr_defeats_licm_hoist]] cracked the sibling
  802427B4 95.68->97.96). LOW confidence this is the primary lever; likely a cascade follower
  of B1/A. Test only after A and B1.

### Ranked iteration-2 lever candidates
1. **MECH-A: change `(f32) fighter_id` -> `(f32)(u8) fighter_id` at BOTH call sites
   (lines 2733, 2780).** Highest confidence; directly explains the +2 delta, the "call shape"
   flag, and the clrlwi presence; matches the documented cast-restoration mechanism. Cheapest
   possible edit. If the clrlwi appears but regs still cascade, the residual is then MECH-B.
   - Variant 1b: type `fighter_id` as `u8` instead (then every assignment truncates; check it
     does not change the `= 0x19` / `lbz` codegen or the find-walk).
2. **MECH-B1: `joint_data = assets->FaceB;` (0xB4 not 0xF4).** Test after A. May be the
   register-cascade root (re-bases the joint_data pointer the whole draw block hangs off).
   GATE: confirm this is the intended field (behavior), not just a score chase — flag to
   orchestrator. If it is a struct-layout error, the FaceB/ConB1/ConB2/ConB3 names at
   0xB4-0xF4 may all need re-examination.
3. **MECH-B2: defeat the `&sorted_fighters[arg2]` LICM hoist** (statement reorder / comma-expr).
   Lowest confidence; likely a follower. Test last.

### Things NOT to chase
- The BSS section-anchor reloc (`mnDiagram_804A0750` vs `.bss.0`) — ceiling reloc noise, not
  matchable from source here (94 of the visible diff lines).
- The whole-function GPR renames as individual sites — they are one cascade off A+B.
- PAD_STACK(32) — diagnostic only; the real frame need comes from the (u8) conversion scratch
  slots + lb_80011E24 result slots once A lands. Do NOT commit PAD_STACK; replace per doctrine.

---

## ITERATION 2 (2026-06-11, driver 1) — BUILD RESULTS

### Build ledger (4/4 budget)

| Build | Edit | Fuzzy | Opcode | Δ | Verdict |
|-------|------|-------|--------|---|---------|
| baseline | — | 94.98 | 93.2 | tgt+2 | — |
| A | `(f32)(u8)fighter_id` ×2 | 93.30 | 92.5 | ours+4 | **REFUTED — wrong form.** clrlwi appears at the right slot but MWCC selects the UNSIGNED u8->float path: NO xoris + a SECOND bias constant (2^52 vs 2^52+2^31) => `lfd f30` ×2 added, f29 spilled, frame 168->176, +6 instrs. Decisive: the loop-counter conversion `(f32)i` (x_spacing*i — a SECOND int->float per loop, missed in iter-1 map) shares the f31 bias with the fighter_id site in the target; the u8 cast splits them. |
| 1b | `u8 fighter_id;` (typed) | 93.30 | — | — | **REFUTED — identical codegen to A.** MWCC folds u8->float the same whether by cast or by variable type. |
| **A''** | `(f32)(fighter_id & 0xFF)` ×2 (lines 2733/2780) | **96.28** | **98.1** | **0** | **COMMITTED 78266c20a.** The int-typed mask reproduces clrlwi + SIGNED xoris path exactly. File-idiomatic (GetNameText(i & 0xFF) ×10+ in this TU). Line-edit 171/36.0% -> 135/49.4%; stack-slot diffs 8->4; reloc-paired diffs 94->25; hunks 7->42 (structure now aligns 1:1, register diffs scatter into honest small hunks); register-only 8->65 (cascade now correctly metered). |
| **B1** | `joint_data = assets->FaceB;` (line 2683) | **96.29** | 98.1 | 0 | **COMMITTED 23fd94dec** ("loads FaceB joints per retail"). +028 base site now `addi rX,r31,180` BOTH sides (register-only residual r29 vs r25). Cascade re-roll: net flat (65->66 reg-only) — B1 fixed the offset but the surrounding register draw is governed by the still-standing B2 web. |

Protected verified after each commit: 802437E8=100 (match=true), 80243434=100
(match=true), InputProc=98.67, mnDiagram2_HandleInput=97.46. Pre-commit
match-regressions gate passed both commits.

### MWCC conversion-selection law (NEW, reusable)
For int->float of a u8-masked value, the SPELLING decides the conversion flavor:
- `(f32)(u8)x` and `u8 x; (f32)x` => UNSIGNED path: clrlwi, NO xoris, bias 2^52
  (needs its own constant — costly if another signed conversion exists nearby).
- `(f32)(x & 0xFF)` (int-typed mask) => clrlwi + SIGNED path: xoris, bias 2^52+2^31
  (shares the constant with plain `(f32)int_var` sites).
Target draws with clrlwi+xoris = the original spelled an int-typed mask, not a u8 cast.

### STRUCT-VERIFY VERDICT (MECH-B1 label gate)
- `melee-agent struct verify` FAILED in this worktree (ModuleNotFoundError
  src.cli.common at struct/__init__.py:2072) — reported as issue #569.
- Labels verified by two independent means instead: (1) arithmetic — all offset
  comments chain exactly to STATIC_ASSERT(sizeof==0x118), no padding ambiguity
  (u8 arrays + 4-aligned void* arrays); (2) **the loader oracle: mnDiagram_802437E8
  (PROTECTED, 100% byte-match) pairs `&assets->FaceB[0..3]` with `tbl->FaceB_*`
  archive-section name strings** — its displacement codegen is byte-verified vs
  retail, so 0xB4 = FaceB-named sections, 0xF4 = ConB3-named. LABELS CORRECT =>
  per the FaceB ruling, the original simply used FaceB. (Semantics agree: the
  function draws fighter FACE icons.)

### POST-A''+B1 RESIDUAL MAP (fresh difflib, EXP=CUR=267 instrs, 6 opcode blocks)

| Block | Target | Ours | Mechanism |
|-------|--------|------|-----------|
| insert C+02c | — | `add r30,r31,r24` | **B2a (col):** ours hoists `&sorted_fighters[arg2]` pre-loop |
| E+074 / C+078 | `add r19,r31,r24` | `addi r19,r30,0` | **B2a (col):** target computes p in-block; ours reads hoisted r30 |
| E+224 / C+224 | `addi r29,r31,180` | `add r30,r31,r23` | **B2b + B2a (row):** target RE-derives the FaceB base at the row-loop top (computes it once per loop); ours holds one copy live across both loops AND hoists the row sorted_fighters base here |
| E+268 / C+268 | `add r20,r31,r23` | `addi r22,r30,0` | **B2a (row):** in-block compute vs hoisted read |
| E+040 / C+044 | `addi r21,r26,0` | `li r21,0` | **NEW-1 (col only):** target inits k by COPY from count (`count = 0; k = count;` shape — mr); ours `li` both. Row loop already matches the copy shape. |
| delete E+13c | `addi r26,r21,0` | — | **NEW-2 (col only):** target copies jobj (LoadJoint result, r21) into r26 after `lwz r19,36(r27)`; draw-tail then uses r26. Ours keeps jobj in one register. Row block has no copy on either side (target row jobj lands in r26 directly). An allocator/web artifact of the col loop being first — possibly falls out of B2a, or needs an intermediate-copy lever (campaign doc "intermediate-copy persistence law"). |

Plus: 66 register-only paired lines (cascade; checkdiff names "callee-save swap
r25<->r29"), 25 reloc-paired (mostly BSS section-anchor ceiling), 4 stack-slot lines:
**target sp_jobj slots are PER-LOOP (76 col / 68 row); ours single slot 80 for both**
=> the original likely had per-loop `HSD_JObj* sp_jobj` locals (address-taken =>
distinct stack homes). PAD_STACK(32) currently absorbs the difference — per doctrine,
replacing PAD_STACK with the two extra address-taken locals (and whatever else the 32
bytes cover) is the natural-frame path once B2 lands.

## DOC FEEDBACK (mndiagram-inputproc-campaign.md methodology)
- The "Cast restoration" lever-class (§1) and the prototype-visibility signature transferred
  cleanly to diagnose MECH-A here from the disasm alone — strong, reusable.
- Methodology worked as intended: difflib opcode alignment (not checkdiff's paired view)
  was ESSENTIAL — the checkdiff paired view shows ~200 diff lines (reloc + cascade) that hide
  the 5 real sites; the opcode-blanked difflib collapsed it to the true mechanism in one pass.
  Recommend the campaign doc explicitly prescribe "strip registers + strip relocs, then difflib
  the mnemonic stream" as STEP 2 of the map (it is implied but not spelled out).
- The BSS section-anchor ceiling is a big visible-diff inflator on functions that touch a
  .bss global; worth a one-line note in the doc that it is reloc noise to subtract first.

---

## ITERATION 3 (2026-06-11, driver 1) — PER-LOOP-LOCALS FORM, PARTIAL LAND

### Build ledger (4/4)

| Build | Edit | Fuzzy | Mechanism verdict |
|-------|------|-------|-------------------|
| 1 | `remaining=i; idx=argN; p=&sorted[idx];` both loops | **96.42** | Order matched (kept). **idx-derivation did NOT kill the hoist** (MWCC copy-props idx=argN -> invariant again). |
| 2 | bundle: joint_data=FaceB per loop + `k=count` + sp_jobj2 row | 96.34 | **B2b LANDED — row +224 `addi r29,r31,180` BYTE-EQUAL** (per-loop defs not CSE'd; col register-only). **k=count INERT** (copy-props: count is literal-0; emission identical to k=0; reverted). **sp_jobj slots SEPARATED 80/80 -> 84/80** (target 76/68; placement residual). |
| 3 | `(0, &sorted[idx])` comma + k revert | 96.27 | **comma-expr REFUTED** — identical 6 blocks; MWCC optimizes through `(0, addr)`. (The 802427B4 precedent wrapped a DATA READ, not an address computation.) |
| 4 | `int idx/remaining` + interleaved UNUSED pads (8/4) + PAD 20 | 96.27 | **int types INERT** (hoist + all meters unchanged; kept for helper-style consistency). **pad interleave REFUTED** — slots moved only 4 (84/76) AND frame grew -168 -> -176 (decl-arrays align differently than the do-scope pad); reverted. |

Final committed state (80f374d45): build-1 order + build-2 joint_data/sp_jobj2 + int
decls; comma and pad interleave removed. 96.34 / opcode 98.3 / delta ours+1 / hunks 12 /
line-edit 168/37.3. Protected: 100/100/98.67/97.46 verified; match-regressions gate OK.

### THE HOIST WALL (B2a) — 4 refuted spellings, mechanism characterized
Target computes `add rX,r31,argN` (`&sorted_fighters[argN]`) INSIDE if(count>i), per
iteration, in both loops; ours LICM-hoists it to each loop preheader (+02c col, +228 row
— note ours re-derives PER LOOP too, so it is preheader-LICM not function-wide CSE).
Refuted: (1) idx-derivation `&sorted[idx]` — copy-prop restores invariance; (2)
`(0, &sorted[idx])` comma — optimized through; (3) `int` vs `s32` idx/remaining — inert;
(4) k=count — different site, copy-props. NOT refuted candidates for iteration 4:
- GetVisibleFighterFrom inline call — REJECTED on shape evidence (helper's `while(>0)`
  + post-loop fetch cannot produce the target's `>=0`/`==0`-inside walk, which our soup
  already byte-matches). Do NOT rebuild.
- ONE mwcc-debug dump on the current tree to read WHERE the address node gets hoisted
  (IRO LICM pass) and what gates it — then spell against the gate. (Dump budget unused.)
- A spelling where the base genuinely involves per-iteration state, e.g. deriving p
  from the count-loop's terminal k? (k==0x19 post-loop — no.) Or reading sorted via a
  pointer local reassigned per iteration INSIDE the if-block:
  `u8* sorted = assets->sorted_fighters; p = sorted + idx;` (sorted as an in-block
  reassigned local — MWCC may keep the add on the sorted web). Untested.
- Per never-claim doctrine: the in-block form provably exists in retail compiled from
  C; lever NOT FOUND despite 4 spellings — MODEL GAP, cause unattributed.

### Remaining residual (post-80f374d45): 6 opcode blocks + accounting
1-2. col hoist (insert +02c, replace +074/+078) — THE WALL above.
3. k-init li-vs-copy (+040/+044, col only) — RE-DIAGNOSED as the ZERO-COALESCE channel
   (our row loop emits the copy from identical `k=0` source; target col copies, ours
   mints two zero li's). InputProc fusion/zero-cluster family; NOT spelling-addressable
   (k=count refuted; 8 spelling classes failed in InputProc). Cascade-watch only.
4. col jobj copy (delete E+13c `addi r26,r21,0`) — allocator region-split copy;
   cascade-watch; if it survives the hoist fix, try intermediate-copy lever
   (`jobj2 = HSD_JObjLoadJoint(...)` col only).
5-6. row hoist (insert +228, replace +268/+26c) — THE WALL.
Plus: sp_jobj slot placement (ours 84/80, target 76/68 — needs +8 bytes of address-taken
objects ABOVE sp_jobj and +4 between, WITHOUT growing the -168 frame; the do-scope
PAD_STACK packs differently than decl arrays — iteration-4 must find the natural-object
arrangement; sibling 80243434 ships `u8 stack_obj[8]` as precedent), ~66 register-only
lines (cascade), 25 reloc-ceiling lines (do not chase).

## ITERATION-4 ENTRIES (pending)
- STEP 0: reproduce 96.34 on 80f374d45; re-confirm 6 blocks.
- PRIMARY: the hoist — take the mwcc-debug dump FIRST (read the LICM/IRO placement of
  the add node and its gate), then spell against the mechanism. Untested spelling in
  queue: in-block `u8* sorted` local (see wall notes).
- SECONDARY: slot accounting — find an arrangement reaching 76/68 inside -168
  (try: single PAD_STACK(8) BEFORE sp_jobj decl is illegal (statement); try
  `u8 stack_obj[8];` as first local + sp_jobj + `u8 stack_obj2[4];` + sp_jobj2 and
  REMOVE PAD_STACK entirely — total address-taken 8+4+4+4=20; frame may then need
  +12 more from elsewhere; METER the frame line first).
- Cascade-watch: blocks 3/4 (zero-coalesce k-init, jobj copy) after any structural land.
- Tool issue #569 (struct verify ModuleNotFoundError in worktree) — retry after
  resolver fixes if struct questions recur.
