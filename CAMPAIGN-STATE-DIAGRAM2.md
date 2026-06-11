# Campaign State: mnDiagram2_HandleInput (802427B4)

## Objective
Match `mnDiagram2_HandleInput` in `src/melee/mn/mndiagram2.c` to 100%.

## Baseline & Current State

| Metric | Value |
|--------|-------|
| Starting baseline | 89.34% (from extract) |
| Verified worktree baseline | 91.59% (pre-campaign) |
| Iteration-1 end | 95.91% |
| **Iteration-2 end (committed)** | **97.5%** |
| Commits | d229127e4, 384761931, 54f8e1157, 8de2c73ea, a97f93631, 92775a644, 213a63310 |

## Iteration-2 Headline: the +8 paradox resolved (IG verdict)

Iteration-1 banked: "`new_var = data` buys correct callee-saves but costs +8
instructions (5 mr at expansion sites + 3 lwz)". **Both halves of that
attribution were wrong**, exposed by a precise difflib alignment of the
full instruction streams (normalize registers/labels, anchor structure,
list pure insertions):

- The `mr new_var,data` copies NEVER EXISTED in final code — they were
  fully coalesced (the degree-0/0-interferer r0 nodes in COLORGRAPH are
  the coalesced-away copies). new_var was innocent.
- The real +8 lines = +6 instructions:
  - +1 `li r0,0` — CP/remat of entering_menu store (known)
  - +2 `lwz r3,sda21; lwz r30,44(r3)` — the data3 reload ITSELF
    (54f8e1157's own cost; the target has NO reload — its bottom body
    uses the entry-loaded `data` in r30)
  - +4 `mr r31,r3` — new_val copies after the 4 GetPrev/NextName/Fighter
    calls; the target instead has `clrlwi r28,r3,24` at those sites
  - -1 `lbz r4,72(r30)` — target reloads is_name_mode for UpdateHeader1's
    arg; ours CSEs the test load (we are SHORTER here)
  - (+224 `addi r3,r28→lwz r3,sda21` is count-neutral: the lost r28 CSE)

**Schedule-oracle verdict (TASK 1b):** `explain-schedule` finds NO
same-base load window at ANY divergence site (+028 addi swap, +04c CP,
+1cc/+224 CSE sites all "status=missing"). The residuals are allocator
facts, not placement facts. The new force-schedule family is the wrong
instrument class for this function.

## Iteration-2 Wins (committed)

### a97f93631 — index-temp masks + var_r28 reuse (95.91 → 97.1%)
1. Target emits `clrlwi r28,r3,24` after each GetXIndex call = the
   original TU called these WITHOUT a u8-returning prototype visible
   (implicit int). The callee (`mnDiagram_GetPrevNameIndex`, matched)
   masks its own return; the target caller masks AGAIN — double-masking
   is the no-prototype signature. Fix: `_s` int-cast macros (same idiom
   as the existing `GetNameByIndex_s`) + `(u8)` cast on assignment.
   The clrlwi lands at the target's own offsets (+32c/+3a8/+4fc/+578).
2. The index temp colors r28 in the target = var_r28's register. Tested
   three identities: `u8 new_val` (clrlwi colors r31), `var_r28` reuse
   (r29, line-edit 232), `int new_val` (96.4% regression). Kept var_r28
   reuse. NOTE: variable reuse does NOT bind the IG node — MWCC webs are
   du-chain based; the bottom-body defs form separate webs regardless.
   The identity still moves the dispenser (r31 vs r29).

### 213a63310 — d2 gobj alias restores the r28 CSE (97.1 → 97.5%)
`data2 = (d2 = mnDiagram2_804D6C18)->user_data;` + `mnDiagram2_UpdateHeader(d2,
x48, var_r5)` reproduces the target's lwz r28,sda21 / addi r3,r28 CSE at the
second UpdateHeader (S4 closed). The FUSED assignment is required — the
two-statement form stages through r3 + `mr r28,r3` (+1). Derived from the safe
core of remote candidate output-800-1 (raw candidate read the alias
uninitialized on non-0xC0 paths — rejected on full-file diff).

### 92775a644 — data re-assignment replaces data3
`data = mnDiagram2_804D6C18->user_data;` re-assigned into the SAME
variable splits the web identically to a separate `data3` (97.1% both
ways) — kept the natural single-variable form.

## Current Residuals at 97.5% (line delta 3)

Structural:
- S1 (+2): the bottom-body reload. Target = single web, no reload, yet
  result=r31. Our single-web test: data (deg 27, 92 intf) pops FIRST in
  SIMPLIFY → takes r31 → whole-function permutation (96.7%, delta 1).
  The reload is currently the price of the rotation.
- S2 (+1): CP/remat `li r0,0; stb r0` vs `stb r28`. MWCC rematerializes
  the provably-0 var_r28 across the lbAudioAx call at the 0x20-arm store
  only (the 0xC00-arm store, non-provable value, uses r28 fine). (u8)
  cast does not block it. Target does not remat despite same provability.
- S3 (-1): ours CSEs the is_name_mode test load into the UpdateHeader1
  arg (1 load); target emits 2 loads (r0 test, r4 arg). Block-local CSE
  difference downstream of register state.
- S4: CLOSED by 213a63310.

Register-only (post-d2 alignment, 107 paired diffs, ONE systematic
pattern):
- R0: ALL 9 RefreshStatRows expansions: ours (d,data)=(r31|r30, r29) vs
  target uniform (r29, r28). Target's dispenser is stable across pops;
  ours alternates. new_var alias in the inline still REQUIRED on the
  new base (removing it: 93.7%).
- R1: 4× clrlwi r29-vs-r28 (same family; r28 proven legal via
  force-phys 44-47:r28 — exact target shape, cascades elsewhere)
- R2: x48 r29-vs-r30 in 0x20 arm (fusion keeps it; unfused = 96.9%)
- R3: +028/+02c addi order swap (scheduler; outside the oracle's
  same-base-load window class)
The whole register family reduces to: arm-local temps should draw
{r28,r29} stably; ours draw {r29,r30,r31} with rotation. One dispenser
fact away from ~99%.

## Key COLORGRAPH facts (fresh DLL, 2026-06-11)

- HandleInput single COLORGRAPH pass, 194 nodes (both with/without
  new_var — the alias adds 9 colored coalesce-roots, no new IG nodes).
- Outer callee-saves came from the data web split, NOT new_var:
  with split: iter0=result→r31, iter1=data-bottom→r30, iter2=data→r30,
  iter90=mn_addr→r29, var_r28→r28, gobj→r27 (all correct).
  Without split: iter0=data(deg 27)→r31 (rotation wall).
- new_var's +3.79% (iter-1) was INLINE-temp alignment: per-expansion
  d=ROOT nodes alternating r31/r30, data=r29 nodes; the alias changed
  which alternation pattern the expansions get.
- In the target, x48 SHARES r30 with data (path-dead inside the 0xC00
  tail) — MWCC interference is path-aware enough for this; reproducing
  the sharing is untested as a lever.

## Walls Banked (updated)

- SIMPLIFY pop-order, single-web data: data has ~92 interferers (it
  outlives every inline expansion inside the arms) vs result's ~33
  (result dies at each arm entry — does NOT interfere with the inline
  temps). Pop order is not explained by degree or nIntfr sort; do not
  reverse-engineer further — drive it empirically (permuter).
- entering_menu CP/remat: not blocked by (u8) cast; split-assignment and
  comma-expr regress (iter-1). Lever not found despite cast/order/web
  changes.
- UpdateHeader float f0/f1 binding (y wants f1, x wants f0): temp-set
  permutations exhausted (y,z temps = best 94.2; x,y / x,z / all /
  none all regress). Same dispenser family.
- UpdateHeader +14c `mr r3,r31` vs our `clrlwi`: gm_8016400C takes u8
  in repo headers; target passed int name unmasked = another implicit-
  prototype site. Unfixable without TU-local prototype change (blocked
  by -requireprotos + included header); function-pointer cast forces
  indirect call (breaks bl). PARKED.

## Permuter

- coder1: mnDiagram_InputProc listening post — DO NOT TOUCH.
- coder3: re-bootstrapped + resubmitted at the 97.5 base (d2 form);
  prior 97.1-base job stopped after yielding the d2 mechanism
  (output-800-1, best 800 from 1320 at ~30K iters).
- coder2: submissions repeatedly produced empty output files (3×);
  verify with `remote ps` before relying on it.
- Old 95.91-base jobs stopped. Old high-score candidates (4530 etc.) are
  STALE — scored against the pre-mask base; do not apply.
- #558 NULL auto-injection: NOT exercised (this base.c has no NULL
  token); verify on a base that uses NULL before dropping the manual
  step from doctrine.

## Doctrine for driver 3

1. Gate everything vs 97.1 (commits a97f93631 + 92775a644).
2. The remaining function-level walls are all dispenser/pop-order
   micro-state. The permuter is the right search engine now; full-file
   diff every candidate (stale-base risk after ANY commit).
3. Decisive untested levers:
   - x48-sharing shape (make x48 colorable into r30 alongside data)
   - PAD_STACK(40)'s real form (40-byte local/array/addressed temp) —
     may shift remat/spill costs AND the frame story at once
   - `debug mutate insert-alias` scored against force-phys 44:r28
     (suggester recipe 3, untried)
   - S3's two-load shape: break the test-load/arg-load CSE (e.g. test
     via a different lvalue spelling)
4. If single-web + correct rotation is ever observed, S1's +2 dies —
   re-check IMMEDIATELY whether delta-1 (CP only) holds.

## DOC-FEEDBACK (methodology observations, iteration 2)

1. **Precise-alignment-first should be doctrine.** Iteration-1 spent a
   session attributing +8 to "5 mr + 3 lwz from new_var" from eyeballing
   side-by-side diff hunks; a 30-line difflib alignment (normalize regs,
   list pure insertions) overturned it in one pass and directly produced
   the masks win. checkdiff's paired view interleaves offset drift with
   real inserts — never count extras from it manually.
2. **"X% improvement from change C" claims need a mechanism check.**
   new_var's +3.79% was real but the MECHANISM recorded (callee-saves)
   was wrong (it was inline-temp alternation; callee-saves came from
   data3). The wrong mechanism note sent iteration-2's first hour at the
   wrong target. COLORGRAPH-diff before/after a win, not just match%.
3. **Caller-side masking = prototype-visibility evidence.** Double-mask
   (callee masks return AND caller masks again) reads as "original TU
   had no prototype". This generalizes: grep target asm for
   clrlwi-after-bl at call sites whose repo prototypes return u8. The
   `_s` macro idiom is the repo-blessed fix. Candidate for mismatch-db.
4. **Schedule oracle scope**: only same-base adjacent/1-straddle LOAD
   pairs are forceable; everything else is explain-only and reports
   "missing" rather than classifying. Fine for ruling OUT placement —
   one command per site, cheap, decisive. Use it exactly that way.
5. **Variable identity is a dispenser lever even without web binding.**
   u8 new_val/var_r28/int new_val moved the mask web r31/r29/regression
   at identical match% — cheap 3-way A/B worth standardizing when a
   register-only residual is one dispenser step away.
6. **Background `permute remote submit` may produce an empty output file
   and no session** (coder2, twice). Re-submit synchronously and verify
   with `remote ps`. Tool issue to file if it recurs.
