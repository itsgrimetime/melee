# Campaign state — drv-levers2 (PR#2672 idiom application to remaining mndiagram walls)

Date: 2026-06-12. Driver: drv-levers2. Worktree HEAD at start/end: `aa0cf0672`.
Budget: 16 builds; used 10. Result: **0 wins — all 4 targets ceiling-confirmed.**
Worktree left CLEAN; protected sweep verified identical to baseline (74 fns, no
regressions, all at-100 stay 100, all floors held).

## Target 1 — mnDiagram_80240D94 (99.4729) — named-data-symbol lever: REGRESS, ceiling

The residual is TWO anonymous float-pool slots, not one:
- `@1199` at +050 = `0.0521f` (target names it `mnDiagram_804DBF88`)
- `@225` at +098 = `0.0f`    (target names it `mnDiagram_804DBF84`)
Plus a prologue scheduler split (`lis/addi r0,r7` for `mnDiagram_803EE728`,
`mr r28,r0` vs `addi r28,r7,0`) — fjooord's own tbl-hoist ceiling.

**Attempt:** replaced the bare `0.0f, 0.0f` in the first GetNameText-branch
`HSD_SisLib_803A6B98(text, 0.0f, 0.0f, GetNameText((u8)arg1))` with the named
`mnDiagram_804DBF84` (proven = `0.0f`; CreateStatRow uses it as the y-arg).
**Result: 99.4729 -> 97.2849 (REGRESS).** The line alignment broke; naming the
literal at the use-site forced a different/worse codegen path. Reverted.

**Verdict (do NOT re-try the named-symbol lever here):** fjooord's OWN PR#2672
keeps bare `0.0f`/`0.0521f` in 80240D94 and ALSO produces `@1199`/`@225` — this
is part of HIS residual, uncracked. The named `_804DBF88`/`_804DBF84` in the
target come from the upstream **.sdata2 pool LAYOUT/ORDERING** (a whole-TU
section-layout artifact), not a use-site named reference. fjooord's dead-literal
anchor idiom (`(void) -1.0F; (void) 4503601774854144.0;`) anchors DIFFERENT
symbols (`_804DBF94`/`_804DBF98`) and lives in `80241310` (already 100% in our
source WITHOUT the anchors). The 80240D94 source already matches fjooord's shape
(new_var reuse + bare 0.0f). This is fjooord's documented ceiling. Cracking the
pool order would need TU-wide anchor surgery risking all the at-100 fns.

## Target 2 — mnDiagram_80241E78 (99.8833) — f26<->f28 FPR dispense: ceiling

Opcode-100%; residual is a pure FPR dead-temp dispense tiebreak. col_offset and
row_offset products swap physical FPRs: target col_offset=f28/row_offset=f26;
ours col_offset=f26/row_offset=f28 (+154/+158/+15c/+1e8/+274/+2f4).

- Attempt A: lever #8 `col_offset = (new_var = y_spacing*(f32)col)` -> **99.8444 REGRESS**.
- Attempt B: lever #8 `row_offset = (new_var = y_offset*rowf)` -> **99.8833 INERT**.
- Attempt C: reorder (compute row_offset before col_offset) -> **98.1089 REGRESS**.
All reverted. **Verdict: coloring ceiling at 99.88%; lever #8 cannot flip this
dispense. Do NOT re-try lever #8 / reorder here.**

## Target 3 — mnDiagram3_HandleInput (98.4166) — callee-save coalescing cascade: ceiling

149 register-only diffs (callee-save swaps r26<->r27/r28/r30/r31) + a 32-byte
stack-slot offset cascade (Vec3 spDC/spC0/spA4 sit 0x20 higher: target lfs
f0,224(r1) vs ours 256(r1)) + an FPR dispense diff (`fsubs f30 vs f29`,
`fneg f29,f30 vs f29,f29`) inside the inlined `HSD_SisLib_803A5ACC` arg
`-spacing*(f32)i + -spDC.y` (line 660 mndiagram3.c).

- Attempt: lever #8 `(new_var = -spDC.y)` on the negated-y term ->
  **98.3758 REGRESS**. Reverted.
**Verdict: pressure-driven whole-function coalescing cascade (the hardest
class). One float-arg temp cannot resolve a 149-instr cascade. Do NOT re-try
lever #8 here.** If anything, the lever is the 0x20 frame-shift + the extra
callee-save, not a per-store temp — but that is a coloring ceiling.

## Target 4 — mnDiagram2_CreateStatRow (83.9332) — inline-boundary, NOT frame gap

Residual is dominated by an **inline-boundary scheduling divergence around
`HSD_JObjSetMtxDirtySub`** (the inlined `HSD_JObjSetTranslate*` helpers): target
emits `bl HSD_JObjSetMtxDirtySub` where ours reorders `bne`/`stw`/cmp around it
(+288/+2a4/+31c/+390). Also target keeps an EXTRA callee-save (stmw r21 vs r22)
and packs locals 28 bytes lower (sp20 Vec3 at 36/32/40 r1 vs ours 64/60/68).
fjooord NEVER touched mndiagram2.c in PR#2672 — no exact spelling to port.

- Attempt A: remove `PAD_STACK(16)` entirely -> **83.9144** (marginally LOWER;
  the frame gap is benign / not load-bearing).
- Attempt B (idiom #5): `u8 _[16];` positioned before the live locals, PAD_STACK
  removed -> **83.9332 INERT** (exactly ties the PAD_STACK(16) baseline; the
  unused array reserves the identical 16 bytes but touches nothing in the
  residual). Reverted.
**Verdict: idiom #5 ties baseline but does NOT match — per campaign rule, NOT
committed. The lever for this fn is the inline-boundary/scheduling of the
SetTranslate helpers + the r21 callee-save, not the 16-byte frame gap. The
PAD_STACK(16) is currently the (marginally) higher state vs removing it.**

## Meta
All four are fjooord-confirmed or diagnosis-confirmed coloring/inline-boundary
ceilings. The PR#2672 lever menu (#5, #8, named-symbol) was the right thing to
try and is now empirically exhausted on these specific walls. No tooling gap;
no new source shape surfaced. Next driver: do not re-attempt these levers on
these fns — pursue node-set/content levers (permuter arm) or different fns.
