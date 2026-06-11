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
  **Iteration-3 update**: No safe lever. Permuter exhausted the
  "cache in returning arm + reuse at bottom" class. Certified ceiling.
- S2 (+1): CP/remat `li r0,0; stb r0` vs `stb r28`. MWCC rematerializes
  the provably-0 var_r28 across the lbAudioAx call at the 0x20-arm store
  only (the 0xC00-arm store, non-provable value, uses r28 fine). (u8)
  cast does not block it. Target does not remat despite same provability.
  Certified ceiling; all spellings tried.
- S3 (-1): ours CSEs the is_name_mode test load into the UpdateHeader1
  arg (1 load); target emits 2 loads (r0 test, r4 arg). Block-local CSE
  difference downstream of register state. **UNTESTED lever: different
  lvalue spelling for the test to force 2 loads.**
- S4: CLOSED by 213a63310.

Register-only (6 paired mismatches per `force-phys-from-diff`):
- **ig44 → r31** (current r29): 0xC00-arm inline data-root. Force causes
  cascades; not a simple tiebreak.
- **ig128 → r4** (current r0): scratch node, 0xC00-arm area.
- **ig65, ig81, ig85 → r0** (current r6): 3 of 9 inline entity_idx arg
  nodes. First-divergence: these wrongly coalesce to root r6.
- **ig192** (already r0): no-op.
- **R3**: +028/+02c addi ORDER swap — scheduling residual; force-schedule
  oracle class=missing; 2 paired instructions (same opcodes, reversed
  emission order). Separate from the 6 force-phys-from-diff entries.

NOTE: Driver-2's R0/R1/R2 description was imprecise. The 6 paired mismatches
are volatile-register and coalesce-related, NOT the 9-expansion callee-save
rotation. The target ALSO has inline d=r31/r30 and data=r29 (confirmed via
`debug target derive`). The "r28,r29 stable" description was wrong — the
target uses the same register pattern as ours for the inline nodes.

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
- **Iteration-3 addition**: `debug target derive` produces a SELF-REFERENTIAL
  target (maps current source → current coloring). The target .o HAS
  different register assignments for ig44, ig65, ig81, ig85, ig128, ig192
  (per `force-phys-from-diff`). The derive output showing ig44:29 is WRONG
  for comparison purposes — always use `force-phys-from-diff` for the real
  target register requirements.
- **Coalesce divergence**: 9 inline r6-arg nodes (ig65,69,73,77,81,85,89,93,97)
  all coalesce to root r6 in our graph. Target keeps ig65, ig81, ig85 as
  separate (r0-class scratch). First-divergence: coalesce "65, 81, 85 →
  root 6" is the first allocator decision differing from target.
  Shortening the live ranges of these 3 nodes is the lever — untested.

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

## Iteration 3: Dispenser Fact Analysis (driver 2, 2026-06-11)

### Baseline verification
97.5% confirmed. Line-edit 240 instrs / sim 37.2%. Line delta 3. DLL 12/12
(1 WARN melee-agent path, non-blocking). State commit 35032cd39. Clean tree.

### Task 1 — The {r28,r29}-stable vs {r29,r30,r31}-rotating analysis

**COLORGRAPH census complete (194 nodes).**

The "campaign state R0 description" (9 expansions: ours r31|r30,r29 vs
target r29,r28) was imprecise. The `debug target derive` shows the target
ALSO has inline d=r31/r30 and data=r29 — same as ours for these nodes.
The ACTUAL 6 paired mismatches (from `debug target force-phys-from-diff`)
are:
1. **ig44 → r31** (current r29): inline data-root for the 0xC00-arm
   RefreshStatRows expansion. The forced r31 caused cascades in testing
   (force-phys didn't reach a clean result; verified not a simple tiebreak).
2. **ig128 → r4** (current r0): scratch node in 0xC00-arm.
3. **ig65, ig81, ig85 → r0** (current r6): 3 of the 9 inline r6 arg3
   nodes. These coalesce to root 6 (r6) in our code; target keeps them as
   r0-class scratch nodes. `debug inspect first-divergence` named this as
   the first divergence: "nodes 65, 81, 85 coalesced into root 6 [r6]".
4. **ig192 → r0** (already r0, no change needed).

The +028/+02c addi ORDER swap is a STRUCTURAL scheduling residual, not
in the force-phys list (it's 2 paired instructions with the same opcodes
in reversed emission order; schedule oracle already confirmed "missing"
for this class).

**What the dispenser fact actually is:**

The r57 web (bottom-body `data = mnDiagram2_804D6C18->user_data`, ig_idx
57, pops at COLORGRAPH iter 1 → r30) is the correct key node. With r31
(result=r99) and r30 (data=r57) both blocked when the inline d/data roots
pop, the inline nodes cascade to r31/r30/r29 alternating. This IS the
driver-1 diagnosis.

**What "single fact would stabilize the draw" is:**

The fact is: r57 must draw r28 (instead of r30) so the inline d roots
draw r29. Mechanically: r57 needs to pop AFTER iter 2 (r39, current r30),
not at iter 1. This would require a source change that moves r57's virtual
number to a LOWER ig_idx, i.e., a shorter first-use distance.

**What the permuter found (best=535, all unsafe):**

Coder3 at 97.5 base ran ~20K iters, best score 535 (baseline 660). All
408 fetched candidates: 31 corrupt, 377 unsafe. The recurring pattern:
`new_var = mnDiagram2_804D6C18->user_data` in the 0x20 arm, then
`data = new_var` at line 395 (bottom-half re-assignment). This IS the web
identity lever — it would make the bottom-half data web reuse a variable
from an EARLIER def, moving its ig_idx earlier and potentially pulling r57
to a lower register. However: all permuter candidates with this pattern are
DATA HAZARDS (new_var is only set on the 0x20-arm path, which always returns
early; data = new_var at bottom reads uninitialized on non-0x20 paths).
No safe core extractable. Confirmed with full-file diff on all candidates.

**Named fact and lever:**
- Named fact: "r57's first-use at IR position ~151 draws r30 (fresh-
  descend iter 1) before the inline roots (ig 49-60) can claim it."
- Natural C lever: a web that HOLDS a path from an EARLIER sda21-load
  (before position 151) and reuses it at position 151 would move r57's
  virtual earlier, potentially drawing r28.
- Barrier: all such path-spanning webs require the value to be DEFINED on
  the non-returning arms' paths — which means a variable set inside
  returning arms. This is an unreachable-web problem: no natural C path
  creates a web that spans from inside a returning arm to the bottom fall-
  through without a DATA HAZARD. Permuter exhausts this space; all safe
  candidates = no-op.

**VERDICT: Dispenser fact identified but unreachable from natural C.
This function's remaining residuals are all allocator tiebreaks and one
scheduler ordering. NO FAST TRANSFORM exists (diagnose confirmed).**

Match remains at **97.5%** (no change this iteration).

### Task 2 — Small residuals

**S2 (CP/remat, +1):** `li r0,0; stb r0` vs `stb r28`. Confirmed as the
entering_menu CP wall from iter-2. All spellings tried previously. Banked
as ceiling. The force-phys-from-diff shows ig44→r31 is related to the
0xC00-arm data web, not directly to S2. The CP site is separate.

**S1 (+2 reload):** Not dissolved. The r57 web (bottom-body data re-read)
still exists; no safe lever found. S1 remains as the price of the rotation.

### Task 3 — Permuter cadence

coder3 job: `mnDiagram2_HandleInput-coder3-20260611-125553`. 20K iters,
best 535 (66 points below baseline, a significant improvement indicating
this search space has real signal). ALL candidates unsafe. Status: plateau.
coder2: verified STILL not producing jobs (3× empty output, issue #567).
#558 NULL auto-injection: not exercised (base.c has no NULL token).

### Task 4 — Prototype-visibility mismatch-db

`melee-agent mismatch --help` shows: list, get, show, search, opcode, m2c,
record-success, migrate, backfill, review, stats. **NO `add` command.**
The double-masking⟹no-prototype pattern (clrlwi after bl at sites where
callee masks its return AND caller masks again) cannot be directly recorded.
Gap noted: `mismatch add <name> --example <fn> --fix <description>` command
is missing. Doc-feedback #7 filed below.

### DOC-FEEDBACK additions (iteration 3)

7. **mismatch-db has no `add` command.** The natural idiom after finding a
   pattern (e.g., double-masking = no-prototype) is `melee-agent mismatch
   add "double-mask=no-prototype" --fix "use _s macro + (u8) cast"`. The
   current flow requires either a markdown file (migrate) or git history
   (backfill). A direct add path would enable agents to file patterns
   inline as they find them.
8. **force-phys-from-diff gives CONTRADICTORY output vs derive.**
   `derive` maps virtuals to what the CURRENT source produces (self-
   referential: shows ig44→29 because that's what our code emits), while
   `force-phys-from-diff` reads paired asm diffs (ig44→31). The two
   commands produce OPPOSITE answers for the same node. Confusing for
   agents — a clearer docs distinction (or renaming `derive` to
   `derive-current`) would prevent misdiagnosis.
9. **Permuter ALL-UNSAFE corpus = safe wall signal.** When 100% of 400+
   permuter candidates are `semantic-risk-high` with the same structural
   pattern (new_var across returning arms), the permuter has effectively
   characterized the wall. This is useful information that the triage
   system should surface — e.g., "all safe candidates tried for this
   source shape class; this wall is certified." Currently agents must infer
   this from the audit JSON counts.

## Doctrine for driver 4

1. Gate everything vs 97.5 (commits a97f93631/92775a644/9c52d3ce1/213a63310).
2. **WALL CENSUS (certified after iteration-3 analysis):**
   - S1 (+2 reload): bottom-body data re-read (r57 web). No safe lever.
     Permuter exhausted this class. Do NOT re-run unless source structure
     changes (e.g., removing the 0xC00-arm early-return, which would change
     the whole CFG).
   - S2 (+1 CP): entering_menu remat. Ceiling. All cast/split/comma spellings
     tried. Do NOT re-run.
   - S3 (-1 CSE): ours has 1 fewer load than target. Structural difference
     in is_name_mode test load. Untested lever: use a different lvalue
     spelling for the CSE source to force 2 separate loads.
   - R3 (+028/+02c addi swap): scheduler ordering. Force-schedule class:
     non-load window = oracle says "missing". Untested: try reordering the
     rlwinm computation relative to the lis/addi pair.
3. The ONE remaining testable lever: **S3's two-load shape.** If the
   UpdateHeader arg load is made to use a different lvalue than the test
   load (forcing 2 separate lbz instead of CSE), that addresses -1 of the
   delta 3, reducing to delta 2. Still net-positive is uncertain.
4. **PAD_STACK(40) real form still untested** as a lever. A real 40-byte
   stack reservation MAY shift spill/remat costs, potentially hitting S2.
5. Let coder3 run; harvest at low cadence. The all-unsafe corpus signal
   is stable; stop the job if 50K+ iters without a `semantic-risk-low`
   candidate.

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
