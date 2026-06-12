# Campaign State: mnDiagram_80242C0C

## Target Function
`mnDiagram_80242C0C(void* arg0, int arg1, int arg2)` — src/melee/mn/mndiagram.c:2676
Two-loop draw routine (column-header fighter icons + row-header fighter icons).
Each loop: count-unlocked-fighters loop → if(count>i) find-walk resolves `fighter_id`
→ draw block (LoadJoint, AddAnimAll, Req/AnimAll, lb_80011E24, (f32)fighter_id Req,
spacing translate, AddChild).

Called by: mnDiagram_80243434 (matched 100), mnDiagram_InputProc (98.67),
mnDiagram_802427B4 (95.68 — sibling worktree, active driver).

## Status: ITERATION 4 COMPLETE — 96.34 -> 96.93 (commit 09384b217). **THE HOIST FELL.**
Per-loop `sorted = mnDiagram_804A0750.sorted_fighters;` (re-read INSIDE each for body)
puts the base in the loop's killed set, so `&sorted[argN]` is no longer loop-invariant
and IRO_FindLoops computes it in-block per iteration (matching retail). Opcode 98.3 ->
99.4; all four hoist blocks collapse to register-only. Classification flipped
inline-boundary-toolchain-artifact -> signature-type-mismatch (the artifact flag WAS the
hoist). Dump-first proved the mechanism (2 retro dumps, see ITERATION 4). Residual now:
40 register-only + 16 stack-slot (per-loop converted-float slots 76/68 vs 84/80) + col
jobj-copy +13c + BSS reloc ceiling. Budget 2/2 (Build 1 inert, Build 2 the win).

(Iteration 3: 96.29 -> 96.34, commit 80f374d45. Per-loop-locals form PARTIALLY landed:
B2b joint_data-per-loop BYTE-EQUAL at the row site; sp_jobj slots SEPARATED (84/80);
walk-init order matched. Four hoist spellings refuted: idx-derivation, (0,..) comma-expr,
int loop-var types, k=count — all leave both EADD operands invariant.)

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

---

## ITERATION 4 (2026-06-11, driver 2) — THE HOIST FELL (96.34 -> 96.93)

### STEP 1 — DUMP-FIRST: the trigger property, named (2 retro dumps)

**Dump A — our source, `melee-agent debug retro dump src/melee/mn/mndiagram.c
-f mnDiagram_80242C0C --phases frontend`** (62 per-phase IRO files). The hoist is
performed by **`IRO_FindLoops`** (phase 13 before -> 14 after). The trace logs it
literally:
```
Found loop invariant: 101        <- col: EADD(assets, arg2)
Found loop invariant: 502        <- row: EADD(assets, arg1)
IRO_FindLoops:Found loop with header 81   (the for(i) loop)
Killed in loop: 0,4,7-9,11-17,27-28,30-31,33-34
```
- **before-findloops node 7** (the if-block, LoopDepth 0 pre-analysis):
  `99:EINDIRECT assets, 98:EINDIRECT arg2, 101:EADD 100 98` then `104:EASS p,101`
  = `p = assets + arg2` computed in-block.
- **after-findloops node 0** (LoopDepth 0 = the for-loop PREHEADER) now holds
  `101:EADD 100 98` -> `908:EASS @1916,101` — the invariant address is hoisted and
  materialized into temp **@1916**. **node 7** (now LoopDepth 1, in-loop) reads it:
  `905:EINDIRECT @1916 -> 104:EASS p,905` (`p = @1916`; = the disasm `addi r19,r30,0`).
- **The trigger property, precise:** the address is an `EADD` whose BOTH operands
  (`assets`/`sorted` — a never-reassigned local pointer; `argN` — a never-reassigned
  parameter) are absent from the for-loop's *killed* (modified) set, so FindLoops flags
  it loop-invariant and lifts it to the preheader. Copy-prop (phase 6, BEFORE FindLoops)
  has already folded `idx=argN` into the address use, which is exactly why the 4 prior
  spellings (idx-derivation, comma, int-types, k=count) all failed: every one leaves both
  operands invariant. The trigger is NOT operand identity — it is **operand invariance**
  (membership in the killed set).

**Dump B — the matched sibling `mnDiagram_802427B4` (98.84%), same frontend dump.**
Its find-walk is the inlined helper `mnDiagram_GetVisibleNameFrom(sorted, argN, i)`.
**Its FindLoops finds ZERO `Found loop invariant` entries** — the inlined helper's
pointer became a compiler-temp **induction variable** (`@1732/@1733/@1744/@1745`) that
FindLoops strength-reduces (IV base set up in-block), NOT a hoistable invariant.
after-findloops node 0 has the `sorted=` init but NO `sorted+idx` address. ⟹ the
inline boundary converts the named-local invariant into an IV; that is WHY the helper
form does not hoist. (We may NOT rebuild the fighter helper — per campaign DO-NOT.)

### STEP 2 — THE PROPERTY'S CONTROL (build ledger, 2/2)

| Build | Edit | Fuzzy | Opcode | Hoist? | Verdict |
|-------|------|-------|--------|--------|---------|
| baseline | — | 96.34 | 98.3 | YES | — |
| 1 | function-top `u8* sorted = …804A0750.sorted_fighters;` + `p=sorted+idx` both loops | 96.34 | 98.3 | **YES (unchanged)** | **REFUTED — the queued in-block `u8* sorted` candidate. `sorted` is invariant exactly like `assets`; `idx->argN` still folds; FindLoops hoists `EADD(sorted,argN)` identically. Closes that candidate.** |
| **2** | move `sorted = …804A0750.sorted_fighters;` INSIDE each for body (re-read per iteration) | **96.93** | **99.4** | **NO** | **COMMITTED 09384b217.** Re-reading the base each for-iteration puts `sorted` in the for-loop killed set ⟹ `sorted+argN` no longer invariant ⟹ FindLoops computes it in-block per iteration (matches retail `add r19,r31,r24`). All 4 hoist blocks -> register-only. Δ flipped ours+1 -> ours-1; classification inline-boundary-artifact -> signature-type-mismatch. |

Protected verified after commit: 802437E8=100 (match=true), 80243434=100 (match=true),
InputProc=98.67, mnDiagram2_HandleInput=97.46. Pre-commit match-regressions gate passed.
No TU regressions (80242B38=100, 802427B4=98.84, CursorProc=98.57 unchanged).

### THE LICM-DEFEAT LAW (NEW, reusable)
To stop IRO_FindLoops from hoisting a loop-invariant address `base + index` out of an
OUTER loop when retail computes it in-block: **re-read the base into its local INSIDE the
loop body** (`base = GLOBAL.field;` as the first statement of the loop), placing the base
in the loop's killed set. The address then depends on a loop-modified value and is left
in-block (per-iteration recompute), semantically identical when the global is stable
mid-loop. This is the address-computation analogue of the per-loop-locals precedent (B2b)
— and the within-soup substitute for the inline-boundary IV conversion that the matched
sibling 802427B4 gets for free from its inlined helper. SCOPE: the comma-expr law defeats
LICM on DATA READS, not address computations; this killed-set law is the address-side tool.

### STEP 3 — RESIDUAL MAP for ITERATION 5 (post-09384b217, opcode 99.4, 23 hunks)
The hoist + its 4 blocks are GONE. Remaining (all the queued iter-5 items):
1. **Stack-slot arrangement (16 stack-slot lines):** target's converted-float scratch
   slots are PER-LOOP (col `r1,76`, row `r1,68`); ours single-ish (col `r1,84`, row
   `r1,80`); frame ours -168 vs target -160 (NB: Build 2 also shrank our frame by 8 —
   `stwu r1,-160` now on BOTH sides at +00c? verify: target -168 / ours -160 — re-check).
   This is the slot-arrangement search (explicitly the NEXT iteration's job; sibling
   80243434 ships `u8 stack_obj[8]` precedent).
2. **Col jobj-copy (+13c):** target `addi r26,r21,0` (copy LoadJoint result jobj into a
   second reg) before the cmplwi; ours goes straight to the compare. Row has no copy on
   either side. Allocator region-split copy; intermediate-copy lever candidate if it
   survives slot work.
3. **40 register-only paired lines:** the whole-function GPR-rename cascade (re-rolled,
   correctly metered now). Same family as 80243434's pop-order cascade.
4. **81 reloc-paired:** mostly the BSS section-anchor ceiling (mnDiagram_804A0750 vs
   .bss.0) — DO NOT chase.
PAD_STACK(32) still present — replace as part of the slot-arrangement work (natural
address-taken objects reaching the per-loop 76/68 slots).

### DUMP NOTES (tooling)
- `debug retro dump --phases frontend` ran clean (RC=0, 62 phase files + iro-summary +
  iro-trace), ~6 min each on macOS retrowin32+gdb. iro-trace.txt `Found loop invariant: N`
  + per-loop `Killed in loop:` sets are the authoritative LICM diagnostic. Output landed
  under build/mwcc_retro/... (the `-O` path became a directory of phase files).
- `melee-agent scratch list` showed no scratch for this fn; iterated on source+checkdiff
  directly (faster). `struct verify` not retried (no struct question arose).

---

## ITERATION 5 (2026-06-11, driver 2) — SLOTS LANDED, FRAME DECOMPOSED (96.93 -> 96.95)

### FRAME MAP (arithmetic-first; CORRECTS the iter-4 doc note AND the orchestrator recap:
TARGET = -168, OURS = -160 — the recap had it transposed)

| Offset | TARGET (-168, stmw r19,100, f30@152, f31@160) | OURS pre-build (-160, stmw r20,96, f30@144, f31@152) |
|--------|------------------------------------------------|------------------------------------------------------|
| 96-99 | align pad (locals top 100; lfd scratch 8-aligns DOWN to 88) | — (locals top 96, scratch flush) |
| 88-95 | conversion scratch double | same (88/92 both sides) |
| 80-87 | **8B object** | sp_jobj 84, sp_jobj2 80 |
| 76-79 | sp_jobj | — |
| 72-75 | **4B object** | PAD_STACK(32) @ 48-79 |
| 68-71 | sp_jobj2 | … |
| 48-67 | **20B object(s)** | … |
| 8-47 | param area 40B (both) | same |

KEY DERIVATION: the 32 invisible target bytes distribute **8 above sp_jobj + 4 between
+ 20 below** (sum = exactly our PAD_STACK(32)); because the scratch double 8-aligns to 88
at EITHER frame size, every offset below 88 is GPR-count-independent ⟹ **slots (76/68)
and frame size (-160 vs -168) are SEPARABLE**. The -168 frame = the 13th callee-save
(r19) = the +13c extra-live-range pressure, NOT arrangement-reachable.

### Build ledger (1 arrangement build + 1 jobj-copy build)

| Build | Edit | Fuzzy | Verdict |
|-------|------|-------|---------|
| A | `u8 stack_obj[8];` before sp_jobj + `u8 stack_obj2[4];` between + `u8 stack_obj3[20];` after sp_jobj2, `(void)&` each (80243434 idiom), PAD_STACK(32) REMOVED | **96.95** | **COMMITTED 04070ec05.** sp_jobj=76 / sp_jobj2=68 BYTE-EQUAL (addi r4 + lwz r3 ×4 all matched); hunks 21; stack-slot lines 16->14 (the 4 frame-group lines remain); opcode 99.4 held. Decl-order-top-down allocation confirmed (iter-3's +8 anomaly was the do-scope PAD interaction, not array alignment — pure decl arrays pack tight). |
| B | `jobj2 = jobj;` after the lb/AnimAll block + `AddChild(..., jobj2)` col-only | 96.95 | **INERT — reverted.** Codegen byte-identical: copy-prop folds it (the intermediate-copy persistence condition did not fire at this site). Attempts tracker: same fingerprint previously hit by another agent, same outcome. |

Protected after commit: 100/100/98.67/97.46. Pre-commit match-regressions gate OK.

### +13c JOBJ-COPY CHARACTERIZED (disasm-precise; build-B refuted the caller-side spelling)
Target col: jobj=r21 through ALL memory-ops of the SetTranslateX inline (stfs 56(r21),
dirty lwz 20(r21), asserts, flag reads); the +13c copy r26's ONLY consumers are the two
CALL ARGUMENTS — `mr r3,r26` (HSD_JObjSetMtxDirtySub, INSIDE the SetTranslateX expansion)
and `mr r4,r26` (HSD_JObjAddChild). A caller-side `jobj2` cannot produce checks-via-r21 +
SetMtxDirtySub-via-r26 within one inline expansion (one parameter ≠ two variables) ⟹ the
copy is the inline-parameter temp of the SetTranslateX/SetMtxDirty chain taking a separate
color under the target's 13-GPR pressure (row's same temp coalesces into r26 = row jobj
directly). Not found via the intermediate-copy spelling (copy-props); lever not found
despite the disasm read — inline-param band/cascade territory. **The frame group (stwu
-168 / stfd 160+152 / stmw r19,100 / 96-99 pad) hangs on this same extra live range.**

### Residual (post-04070ec05, 96.95, opcode 99.4, 21 hunks)
1. Frame group: 4 lines (stwu/stfd×2/stmw) — coupled to the +13c copy (above).
2. +13c copy: 1-line insert + cascade.
3. ~40 register-only lines (cascade; re-rolls if 1-2 ever land).
4. Reloc/BSS section-anchor ceiling — do not chase.
sp_jobj slots, PAD_STACK: DONE (natural form shipped).

---

## ITERATION 6 (2026-06-11, driver 2) — COALESCE QUESTION ANSWERED, FUNCTION PARKED (96.95)

### THE COALESCE MECHANISM (dump-first, 1 run of `debug dump local`, 0 builds)
Block for this fn in the pcdump: lines 136852-145499 (identified by call profile
IsFU=48/SetMtxDirtySub=24/lb=24/AddChild=24 = 4:2:2:2 x 12 stage prints).

**The premise of the question was inverted by the dump: there is NOTHING our compile
coalesces.** In OUR pre-coloring pcode the col tail is:
```
mr r3,r41 ; bl HSD_JObjSetMtxDirtySub   <- arg = jobj's virtual r41 DIRECTLY
lwz r3,36(r44) ; mr r4,r41 ; bl HSD_JObjAddChild
```
ONE virtual (r41) covers every jobj use (stfs 56(r41), flag lwz 20(r41), asserts, all
call args). No inline-param temp survives IRO into the allocator. The function's entire
[COALESCE] map is `75 -> 3 [r3]` and `88 -> 3 [r3]` — just the two LoadJoint
return-temps (`mr r88,r3; mr r48,r88` shape) folding into r3. Faithfulness verified:
post-coloring col jobj = r29 == retail ninja disasm (row shows the known one-reg DLL
divergence r28-vs-r27; structural conclusions unaffected — front-end IRO cross-validated
faithful per #543).

So: TARGET's `addi r26,r21,0` (+13c) is an EXTRA same-value IR range reaching its
allocator — {SetMtxDirtySub arg + AddChild arg} on r26, memory-ops on r21 — costing the
13th callee-save (the whole frame group). MWCC's allocator does not split non-promoted
webs (region machinery exists only for promoted loop-carried variables per the InputProc
band model; jobj is not loop-carried) ⟹ the copy existed in the original's IR, i.e. the
original SOURCE produced a copy node that survived IRO in the col block.

### COL/ROW ASYMMETRY + THE RECURRING CLASS
Target row = one web (r26) for everything (like ours). Target col = the split. This is
the SECOND col-only same-value copy in this function: (1) the k-init copy at +040
(iter-3: `k=count` spelling INERT — IRO folds), (2) this jobj copy at +13c (iter-5:
`jobj2 = jobj` + AddChild(jobj2) INERT — IRO folds, byte-identical). **Named residual
class: "original col-block same-value copies that survive IRO; every direct caller-side
copy spelling folds in ours."** No mismatch-db or discord-knowledge precedent found.

### VERDICT: (b) NOT caller-reachable with the catalogue — PARKED
- Caller copy spellings fold (proven build, iter-5 B).
- The SetMtxDirtySub arg is bound inside the SDK inline chain (SetTranslateX ->
  SetMtxDirty -> SetMtxDirtySub); no caller construct can bind it to a different
  variable than SetTranslateX's argument, and passing a second variable to SetTranslateX
  moves the memory-ops too (contradicts target: stores/flags on r21).
- Band/pressure/dead-anchor levers operate on EXISTING virtuals; ours has no second
  virtual to steer — the allocator cannot mint one.
- THE ONE HEAVY OPTION (NOT built, review-risky — flagged for the user): manually expand
  the HSD SDK inline at the col site, writing the body with memory-ops on `jobj` and the
  SetMtxDirtySub/AddChild args on a second local. This is caller-LOCAL control of the
  param web (the 80243434-style control surface) but hand-expanding an SDK inline in
  melee source needs an upstream-review ruling first.

### PARK CENSUS (final: 96.95, opcode 99.4, delta 1, 21 hunks)
- Campaign total: **94.98 -> 96.95** (+1.97pp) incl. one behavior fix (FaceB joints) and
  a SHIPPABLE NATURAL FRAME (PAD_STACK(32) GONE, slots byte-equal 76/68).
- Commits: 78266c20a ((f32)(x&0xFF) idiom) / 23fd94dec (FaceB) / 80f374d45 (per-loop
  locals+walk order) / 09384b217 (LICM-defeat per-loop sorted base) / 04070ec05
  (natural stack objects).
- Residual: (1) frame group 4 lines (stwu -168/stfd x2/stmw r19) + +13c copy + its
  cascade — ALL one fact: the col-only IR copy (mechanism above); (2) ~40 register-only
  cascade lines (re-roll if (1) ever lands); (3) BSS section-anchor reloc ceiling (do
  not chase); (4) col k-init li-vs-copy (same class as (1)).
- Laws banked this campaign: MWCC conversion-selection (iter-2), LICM-defeat killed-set
  (iter-4), frame/slot separability + decl-order packing (iter-5), allocator-cannot-mint-
  copies / col-only-copy class (iter-6).
- REOPEN CONDITIONS: (i) any campaign discovers a fold-blocking construct for same-value
  copies (reopens BOTH col sites here); (ii) an upstream ruling permitting manual SDK-
  inline expansion at the col site; (iii) upstream edits to this fn or jobj.h inline
  modeling; (iv) a coalesce/region-split class door from the tooling side (e.g. evidence
  MWCC CAN split non-promoted webs would invert the iter-6 inference).
- Per never-claim: the original col-block source provably exists; its copy-producing
  spelling was NOT FOUND despite dump-precise characterization, 2 direct spellings, and
  knowledge-base search. The function stays in the pool under the reopen conditions.
