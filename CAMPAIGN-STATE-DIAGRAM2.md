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

Register-only (CORRECTED in iteration-3b by precise difflib alignment,
label-normalized — the authoritative census):
- **R0 (driver-1's description CONFIRMED)**: all 9 expansions, target
  uniform (d=r29, data=r28); ours (r31|r30, r29) rotating. ~80 paired rows.
- **R1 CONFIRMED**: 4× clrlwi + stb mask sites, target r28 vs ours r29.
- **R2 CONFIRMED**: 0x20-arm x48, target r30 vs ours r29 (ours clobbers
  the dying base r29; target re-uses staging r30).
- **R3**: +028/+02c addi ORDER swap (entry; target interleaves the
  result-home copy between lis/addi-LO; ours keeps lis/addi adjacent).
- S3's visible half: target lbz r0 (test) + lbz r4 (arg, +1c0,
  target-only row); ours single CSEd lbz r4.

RETRACTION (iteration-3b): iteration-3's "6 paired mismatches
(ig44→r31, ig128→r4, ig65/81/85→r0, ig192)" were ARTIFACTS of
checkdiff's offset-based pairing after the +3 instruction drift —
`force-phys-from-diff` inherits that pairing. The un-coalesce probe
(force-coalesce 65=65,81=81,85=85, #550-verified applied) produced a
byte-identical final diff, confirming the first-divergence "prevent the
coalesce of 65/81/85 into r6" lead was also pairing-derived noise. My
"driver-1 was imprecise" note was itself the error; `derive` is
self-referential AND from-diff is drift-sensitive — only difflib
alignment on label-normalized streams is authoritative here.

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
- **Iteration-3 addition (revised 3b)**: `debug target derive` is
  SELF-REFERENTIAL (maps current source → current coloring; `inspect
  guide` against it reports 127/127 matched on a nonmatching function).
  `force-phys-from-diff` reads checkdiff's offset pairing and emits
  ARTIFACTS once instruction counts drift (its ig44/65/81/85/128 entries
  here were noise — un-coalesce probe was a byte-identical no-op).
  Neither tool names the target's coloring on this function; use difflib
  alignment + the full-vector force oracle.
- **Iteration-3b ORACLE (the family proof)**: forcing the full family
  (masks 44-47:r28; data temps 63,67,71,75,79,83,87,91,95:r28; d-roots
  49-56,60:r29; x48 36:r30 — 23 entries, #550-verified applied) collapses
  the ENTIRE register residual to 5 rows: addi swap ×2 (R3), S2's
  stb r0 ×1, S3's lbz/cmplwi r4-vs-r0 ×2 — plus the S1 (+2) / S2 (+1)
  inserts and S3's one target-only load. The register family is ONE
  coherent coloring, all reachable simultaneously with zero cascades.
- **The dispenser arithmetic (measured)**: fresh callee-save dispenses in
  ours: r31@iter0 (result), r30@iter1 (bottom-data ig57), r29@iter93
  (entry temp ig101), r28@iter135 (ig34 — too late). Expansion temps pop
  iters 97-128 with pool {r29,r30,r31} → reuse-ascending hands data
  temps r29, d-roots rotate r31/r30, masks r29. The target requires r28
  in the pool between iter 93 and iter 97. One dispense event = the
  whole R0+R1(+likely R2) family.

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

[RETRACTED IN 3b — kept for the record. This section's "correction" of
driver-1 was itself wrong: derive is self-referential and
force-phys-from-diff inherits checkdiff's drift-broken pairing. Driver-1's
R0/R1/R2 stand, confirmed by difflib alignment. See iteration-3b.]

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
- Spellings tried so far: (a) delete the line-377 re-read (97.1%, web
  fusion regression); (b) the permuter's cache-in-returning-arm aliases —
  all read uninitialized on non-0x20 paths (rejected on full-file diff).
  Mechanism: the spellings tried either fuse the bottom web into r39
  (changing the early-function coloring) or require a def inside a
  returning arm. NOT FOUND with these spellings; other mechanism classes
  (e.g., a def placed in the shared entry region with the right extent,
  per-region splits of the bottom web, or shapes nobody has conceived yet)
  remain open. The original compiled to this allocation from C; the form
  exists.

**Iteration-3 partial verdict (superseded — see iteration-3b oracle round):
dispenser fact named; lever not found with spellings tried. Tool
diagnose reports NO FAST TRANSFORM (a tool-coverage statement, not a
source-impossibility statement).**

Match remains at **97.5%** (no change this iteration).

### Task 2 — Small residuals

**S2 (CP/remat, +1):** `li r0,0; stb r0` vs `stb r28`. Same family as the
iter-2 entering_menu CP wall. Lever not found with the cast/split/comma
spellings tried (iter-1 + iter-2). The force-phys-from-diff shows ig44→r31
is related to the 0xC00-arm data web, not directly to S2. The CP site is
separate. Stays in pool; untried classes: frame-shape changes (PAD_STACK
real form), substrate changes from any future commit.

**S1 (+2 reload):** Not dissolved. The r57 web (bottom-body data re-read)
still exists; lever not found with the spellings tried (delete-reload,
returning-arm cache aliases). S1 remains as the price of the rotation.

### Task 3 — Permuter cadence

coder3 job: `mnDiagram2_HandleInput-coder3-20260611-125553`. 20K iters,
best 535 (66 points below baseline, a significant improvement indicating
this search space has real signal). ALL candidates unsafe. Status: plateau.
coder2: verified STILL not producing jobs (3× empty output, issue #567).
#558 NULL auto-injection: not exercised (base.c has no NULL token).
[3b update: 92K iters, still descending, fetched best remains the 535
spanning-web family — mechanism-checked and class-rejected (displaces
result off r31); remaining harvest value = any NON-spanning-web pattern.]

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
8. **(revised 3b) BOTH target-spec tools fail differently on drifted
   functions.** `derive` is self-referential (current source → current
   coloring; `guide` against it reports all-matched on a nonmatching fn).
   `force-phys-from-diff` inherits checkdiff's offset pairing, which is
   broken after any instruction-count delta — its vectors here were pure
   artifacts (un-coalesce probe = byte-identical no-op). On a function
   with line delta ≠ 0, the only authoritative register census is a
   difflib alignment of label-normalized streams. Tool ask: a
   from-diff mode that aligns via difflib instead of offsets.
9. **(revised 3b) Permuter ALL-UNSAFE corpus = location intelligence, not
   a wall certificate.** When 400+ candidates share one structural pattern
   (new_var across returning arms), COLORGRAPH-diff ONE candidate vs the
   permuter base to NAME the mechanism (here: spanning web grabs an early
   fresh dispense and shifts the pool — which also proved the class
   cannot reach the target because it displaces result off r31). The
   audit counts alone under-read the corpus; the mechanism check is the
   harvest step. (Original #9's "wall is certified" framing violated the
   never-claim rule — corpora characterize mechanism classes, not
   source-impossibility.)
10. **Single-node force-phys cannot test dispenser-pool hypotheses.**
   Forced assignments do not register in the allocator's reuse pool, so
   a forced early r28 does not cascade to later reuse-ascending picks
   (0:95:28 probe: one site flips, the other 8 don't). Pool-shift
   hypotheses need full-vector forces (pin every family member) or a
   source change. Worth a note in the force-phys help text.
11. **force-coalesce cannot express alias-as-root (polarity flips).**
   Pre-coloring aliases (e.g. 152/160/182/190) have no colorgraph nodes;
   the preflight refuses 'mask=alias' pairs. The InputProc iter-52
   polarity lesson is therefore untestable with this instrument —
   polarity experiments are source-side only (identity spelling).
12. **Re-derive any from-diff force vector via difflib before spending
   builds on it.** This round burned an un-coalesce probe + a first-
   divergence lead on pairing artifacts that a 30-line alignment would
   have rejected immediately. Extends #1 from eyeballs to tools: the
   pairing pathology poisons downstream tooling, not just manual counts.

## Iteration 3b: Oracle Round (driver 3, 2026-06-11)

### Schedule oracle on R3 (+028/+02c addi swap)
- `explain-schedule addi:0x28>0x2c` AND the reversed rule: status=missing
  (no same-base load window). Forced run `--force-schedule addi:0x2c>0x28`:
  #550 check shows ZERO `[FORCE_SCHEDULE]` application lines for
  HandleInput (only sibling scope-skips) — the addi pair never enters the
  force hook's window matcher. `diff-schedule`/`suggest schedule` require
  an applied force; nothing to diff. **Oracle verdict: R3 is outside the
  entire force-schedule instrument family (load windows only); no C
  reshape named.** IR fact for the source search: post-coloring IR order
  is `lis; addi-LO; mr r31,r3`; the target's emitted order interleaves
  (`lis; mr; addi-LO`) — an eager-vs-lazy result-home-copy placement
  question (InputProc M1 entry-deferral territory). Lever not found;
  spelling classes untried: supplier-temp forms for result, buttons-store
  shape variants (natural u64 store risks the two-zero-node wall).

### Coalesce-attack on the "wrongful coalesce" (ig65/81/85)
- Un-coalesce force (`--force-coalesce 65=65,81=81,85=85`, applied,
  #550-verified): final code BYTE-IDENTICAL to baseline. The
  first-divergence lead was checkdiff-pairing noise (see RETRACTION).
- Polarity flip (`44=152,45=160,46=182,47=190` — mask absorbed INTO
  temp-band partner, the InputProc iter-52 direction): preflight REFUSES —
  r152/160/182/190 are pre-coloring aliases with no colorgraph nodes;
  force-coalesce cannot express alias-as-root. Polarity remains conceived
  but UNPROBEABLE with current instruments; C-side analogue = give the
  mask its identity FROM the temp side (a97f93631's 3-way identity A/B
  moved the mask r31↔r29 but never reached r28 — r28-reaching identity
  spelling not found yet).

### Full-vector force-phys oracle — THE FAMILY PROOF
23-entry vector (masks+data-temps:r28, d-roots:r29, x48:r30) collapses
the register residual to exactly 5 rows + the 3 known structural inserts.
No cascades, no spills. The family is one coloring, simultaneously
reachable. See "Key COLORGRAPH facts" for the dispenser arithmetic.

### Cascade probes (both negative, both informative)
- `--force-iter-first 34` (pop entry var_r28 web first): it
  FRESH-DISPENSES r31 (first pop always picks fresh-top) → entry trio
  rotates → 96 divergent rows. The dispense must land 4th (after
  r31/r30/r29), not 1st.
- `--force-phys 0:95:28` (first-popping data temp only): flips that one
  expansion, NO cascade to the other 8 (99 rows). Forced assignments do
  NOT register in the dispenser's reuse pool — single-node forces cannot
  test pool-shift hypotheses (tool limitation, doc-feedback #10).

### Safe-core mining on the 535 corpus (mechanism check done)
COLORGRAPH diff of output-535-1 vs permuter base (both compiled with TU
flags via --unit-source):
- Candidate's merged new_var web = r36: lives 20..410, 119 interferers,
  degree ≥ k → deferred in SIMPLIFY → **pops iter 1, takes r30**; entry
  data takes r31 (iter 0); **result (r98) is displaced to r28** —
  the candidate BREAKS the matched entry trio (target result=r31).
  Its 535 score = expansion-region gains minus entry damage.
- Mechanism class named: "function-spanning web grabs an early fresh
  dispense and shifts the pool". ANY spanning web (~100 interferers)
  pops in the first slots and displaces result off r31 — so the SAFE
  equivalent (entry-defined d0 + bottom use, no hazard) inherits the
  same entry damage. **The target has NO spanning web; its r28-early
  mechanism is something else.** Safe-core verdict: the corpus's
  mechanism is real but not the target's; no commit extracted. Remaining
  conceived candidates for the target's mechanism: (a) UNSPLIT entry
  var_r28 web surviving the lbAudioAx call (ties S2 to the dispenser —
  if the no-remat form exists, the web crosses calls and may dispense
  r28 early; S2 stops being cosmetic and becomes the family's key); (b)
  mask-web polarity (see above). Neither found in C yet.

### S3 two-load spellings (2 builds, both rejected)
- `var_r6 = data->is_name_mode; if (var_r6 != 0)`: NO-OP — front-end
  propagation folds the temp back into one load (census identical).
  Same propagation family as the entering_menu CP wall.
- `if ((0, data->is_name_mode) != 0)` comma: 97.4%, hunks 6 — REVERTED.
- Mechanism: IRO global load-merge across the if/else; not found with
  temp-identity and comma spellings; untried: arg-side respelling that
  keeps the test natural.

### PAD_STACK(40) real form (1 build)
`u8 pad[40];` bare and unused survives -O4 with a frame home —
metrics BYTE-IDENTICAL to PAD_STACK(40) (97.5/delta-3/hunks-5).
So "natural C that reserves 40 bytes" exists trivially; but PAD_STACK
has 2081 uses in committed src/melee and IS the repo-blessed form —
reverted, finding recorded. The 40-byte gap's SEMANTIC origin (which
real object the original declared) remains unidentified; it does not
gate the register family (full-vector oracle matched everything else
with PAD_STACK in place).

## Doctrine for driver 4 (never-claim compliant)

1. Gate everything vs 97.5 (commits a97f93631/92775a644/9c52d3ce1/213a63310).
2. **THE ONE SEARCH TARGET: a C shape that dispenses r28 between the
   r29 dispense (iter 93) and the first expansion-temp pop (iter 97).**
   The full-vector oracle guarantees the payoff: the entire register
   family closes at once (expect ~99+). Ruled out this round:
   spanning-web class (displaces result), pop-ig34-first (fresh-dispenses
   r31). Open: no-remat var_r28 entry web (S2 = the suspected key, not
   cosmetic), mask polarity via identity spelling, any shape adding a
   4th early callee-save-needing temp in the entry/0xC00 region.
3. S1/S2/S3/R3 wall entries: see iteration-3/3b mechanism notes — all
   "not found with spellings tried", all stay in pool. S2 outranks the
   others now (dispenser connection).
4. Probe hygiene addendum: single-node force-phys cannot test
   pool/dispenser hypotheses (#10); force-coalesce cannot make an alias
   a root (#11); re-derive any from-diff vector via difflib alignment
   before believing it (#12).
5. Let coder3 run; harvest at low cadence. Stop the job if 50K+ iters
   without a `semantic-risk-low` candidate; the all-unsafe corpus is
   location intelligence (it found the spanning-web mechanism class).

## Iteration 4: x48+CP mechanism analysis + SIMPLIFY window map (driver 4, 2026-06-11)

### Verified SIMPLIFY window map (derived from fresh dumps this driver)

From x48+new_var pcdump (`pcdump_x48_newvar_fresh.txt`), n_nodes=194, iters 90-105:
```
iter93: ig103 (x48 rlwinm)  degree=11, nIntfr=18  → r29 (callee-save 3rd)
iter94: ig102 (mn_addr)     degree=11, nIntfr=18  → r28 (callee-save 4th)
iter95: ig101               degree=2              → r4  (volatile)
iter96: ig99                degree=2              → r4  (volatile)
iter97: ig97                degree=0              → r0  (volatile)
iter98: ig96                degree=13             → r28 (expansion temp, pool-reuse)
```

From baseline pcdump (`pcdump_baseline_v2.txt`), same window:
```
iter93: ig101 (mn_addr)     degree=11, nIntfr=18  → r29 (callee-save 3rd)
iter94: ig100               degree=2              → r4  (volatile)
iter95: ig98                degree=2              → r4  (volatile)
iter96: ig96                degree=0              → r0  (volatile)
iter97: ig95                degree=13             → r29 (expansion temp, pool-reuse)
```

**SIMPLIFY ordering rule (verified empirically):** Among equal-degree nodes, HIGHER ig_idx
pops FIRST in SIMPLIFY. Evidence: ig103 (103) pops before ig102 (102) before ig101 (101),
all degree=11. And ig34 (34) is lowest, pops latest at iter135/138.

**The dispense-window arithmetic (verified):** For ig34 (var_r28, ig_idx=34) to pop
in iters 93-97, it would need ig_idx ~102 (just above ig101=101 in descending-idx order,
but below ig103=103 which already takes r29). Function-scope locals get low ig_idx (~32-40)
at IR initialization — they CANNOT be repositioned via source spelling without eliminating
the local variable entirely.

### x48+new_var form: COLORGRAPH anatomy (verified this driver)

- ig103 (x48 rlwinm) → r29 at iter93: This web exists because `x48=(u8)var_r28;
  buttons[0]=x48` creates a rlwinm→stw chain. The rlwinm's output web (ig103) lives
  across the lbAudioAx call (MODEL GAP: last visible pcode use is B4, but COLORGRAPH
  shows live=B4,B7 — cause unattributed with available instruments).
- ig102 (mn_addr) → r28 at iter94: Displaced from r29 by ig103 taking iter93.
- ig34 (var_r28) → r27 at iter138, ig32 (gobj) → r26 at iter140: 6th callee-save created.
  This is the BLOCKING PROPERTY of the x48+new_var form: adds a 6th callee-save.

### x48 peephole mechanism (VERIFIED)

B4 post-coloring: `li r29,0` (x48=var_r28=0 assigned to r29, callee-save).
B7 CP-substitution: MWCC inserts `li r_temp,0` (pcode #58 from propagation #34).
After register coloring: r_temp → r29 (because CP's new web has same constraint as ig103).
Peephole: `li r29,0` in B7 is REDUNDANT (r29 already=0, callee-save, preserved across call).
Peephole ELIMINATES the redundant li. Result: `stb r29,17(r28)` in B7 (no li prefix).

This is confirmed by the COLORGRAPH output for x48+new_var: B7 shows `stb r29,17(r28)` with
NO preceding `li`, while baseline B7 shows `li r0,0; stb r0,17(r29)`.

### S2 CP wall: all spellings tried this driver

Goal: prevent MWCC's CP of var_r28=0 at the entering_menu store, without creating a 6th
callee-save.

All forms tried vs 97.46% baseline (all reverted):

| Form | Match% | Mechanism |
|------|--------|-----------|
| `lbAudioAx_80024030(var_r28)` | 97.46% | MWCC sees arg=constant 0 → same CP |
| `var_r28 = result & 0` | 97.46% | MWCC evaluates result&0=0 at compile time |
| `var_r28 = result & ~result` | 97.46% | MWCC evaluates ~result&result=0 at compile time |
| `x48=(u8)var_r28; buttons[0]=x48` (x48 u8) | 96.71% | 2nd rlwinm for buttons[0] stw |
| `x48` declared as `int` | 97.03% | Wrong callee-save ordering |
| x48+new_var non-swap (full form) | 98.76% | 6th callee-save (gobj→r26) |

**Fundamental barrier:** On the B4→B7 path, var_r28=0 is provably constant. MWCC's CP
pass "Found propagatable assignment at: 34" / "Found propagation at 52 from 34" fires
regardless of what precedes it on that path. No single-path spelling tried disrupts CP.

**Why x48+new_var is 98.76% and not 100%:** The 6th callee-save (gobj→r26 instead of r27)
produces `stmw r26,56(r1)` vs target `stmw r27,60(r1)`, and the entire register family
shifts by one (var_r28→r27 vs target r28, gobj→r26 vs target r27). This accounts for all
remaining hunks.

### Quirk-claim audit (coordinator requirement, driver 4)

Claims made in earlier driver text that required audit per the coordinator correction
(binding doctrine: "Bug in MWCC" is a category error; unsubstantiated "known quirks"
must be cited or retracted):

1. **"MODEL GAP: ig103 live range extends B4→B7"** — RETAINED AS OBSERVATION FORM.
   Observed: ig103 (x48 rlwinm web, last visible pcode use in B4) reports live=B4,B7
   in COLORGRAPH. No instruction in B7 reads ig103 after CP substitution. Cause: unattributed
   with available instruments. This is an honest observation; no citation needed for an
   observation. Filed as unattributed behavior, not "bug".

2. **No other "bug in MWCC" or "known quirk" claims were authored this driver.** Prior
   driver docs inherited iteration-3 notes which used observation form throughout.

### Permuter status (coder3-20260611-125553, as of driver-4 harvest)

- Total outputs: 3172 candidates after ~228K+ iterations.
- Best score: 485 (x48+new_var non-swap form with `(u8) data->scroll_offset` in RefreshStatRows).
- All 3172 candidates: 2940 unsafe, 230 corrupt, 0 safe.
- Audit ABORT reason for 485: "unsigned cast in comparison" — FALSE POSITIVE. The
  `(u8) data->scroll_offset` cast already exists in base.c:287. The audit tool
  mis-categorizes argument casts as comparison casts.
- Score 525: `void *new_var` in 0x20 arm, then reuse new_var in 0xC00 arm (UNSAFE: cross-arm
  pointer aliasing with wrong lifetime).
- Conclusion: 228K iterations found the x48+new_var class (485=known form) and nothing
  structurally new. The job has exhausted its useful search budget for safe candidates.

### What is established (driver 4)

1. x48+new_var is 98.76%, confirmed both by prior session and this driver's permuter corpus.
2. The SIMPLIFY window map is VERIFIED: ig103 pops iter93→r29, ig102 pops iter94→r28,
   expansion temps start iter98 using pool {r27,r28,r29,r30,r31}.
3. The x48 mechanism is verified: peephole elimination of redundant `li r29,0` in B7.
4. ig34 (var_r28, ig_idx=34) CANNOT reach the iter93-97 window via source spelling:
   function-scope locals get low ig_idx (~34) fixed at IR initialization. All CP-prevention
   spellings tried evaluate to the same constant 0 at compile time.

### What is open (driver 4, not tried or not found)

- **Mechanism class not yet tried:** A C form where the ENTERING_MENU store uses a different
  web (not var_r28/ig34) that NATURALLY has ig_idx in the 101-103 range and degree=11. This
  would require the entering_menu value to come from an EXPRESSION TEMP created during B4
  IR construction AFTER the mn_addr lis/addi. Candidate: refactor var_r28 as a non-local
  temp (`((s32*)&mn_804A04F0.buttons)[0] = entering_menu_val = 0; ... entering_menu = entering_menu_val`)
  where `entering_menu_val` is an inner scope temp. But MWCC likely creates this during
  function entry anyway.
- **Mask-web polarity (S4):** ig44-47 (GetXIndex masks) could potentially be assigned r28
  via identity-spelling forms not yet tried (existing tries: new_val/var_r28/int-new_val
  moved r31↔r29 but not r28). One more identity spelling remains in the gap.
- **S3 arg-side respelling** (UpdateHeader is_name_mode test): natural arg-side form that
  forces 2 loads without comma operator. Not yet tried.

### What NOT to retry (driver 4, closed)

- Any form of `var_r28 = <expr>` where expr evaluates to 0 at compile time: all hit the
  same CP. MWCC's CP fires on provably-constant assignments; no constant-expr spelling prevents it.
- x48 with non-u8 types: `int x48` tried, creates callee-save ordering regression.
- The spanning-web class: ANY variable with a live range covering both entry and bottom body
  displaces result off r31 (mechanism verified in iteration-3b). Do not retry.
- Permuter job coder3-20260611-125553: fully harvested, all 3172 outputs audited.

### Baseline state for driver 5

- Source: HEAD of `claude/mndiagram-802427B4-investigation` branch, clean working tree.
- Match: 97.46% (checkdiff delta=3, hunks=5).
- Commits in this worktree: a97f93631, 92775a644, 9c52d3ce1, 213a63310, 5c5708b56.
- Best tested form NOT committed: x48+new_var non-swap (98.76%) — 6th callee-save problem.
- Next highest priority: find a form reaching iter93-97 window with 5 callee-saves.

## Iteration 5: x48 decomposition + faithfulness verdict (driver 5, 2026-06-11)

THE ONE QUESTION: is the 98.76 form's "good half" separable and target-faithful?
ANSWER: **NO — the decomposition premise is false.** x48 is NOT a separable
"good half"; x48 ITSELF is the 6th-callee-save mechanism. And the no-li store
it produces is achieved by the WRONG web — the target reaches the same shape
from an entry coloring baseline ALREADY HAS.

### Three-way meter (3 builds, all reverted, baseline restored clean)

| Form | fuzzy | Δ | hunks | line-edit | stmw | entering_menu stb | entry web |
|------|-------|---|-------|-----------|------|-------------------|-----------|
| baseline | 97.46 | 3 | 5 | 240 | r27 (5 CSR) | `li r0,0; stb r0,17(r29)` (REMAT) | result=r31, mn_addr=r29, var_r28=r28, gobj=r27 — **matches target except addi-order R3** |
| x48-alone | 98.46 | 3 | 9 | 227 | **r26 (6 CSR)** | `stb r29,17(r28)` (no-li lands, regs shifted −1) | shifted −1: mn_addr=r28, result=r31, var_r28=r29-store, +redundant `li r27,0` x48 web |
| x48+new_var* | 98.20 | 0 | 46 | 138 | **r26 (6 CSR)** | `stb r30,17(r29)` (more displaced) | spanning new_var dissolves S1 reload (Δ0!) but cascades entry web → 46 hunks |

(*my new_var re-derivation = `new_var = data = ...->user_data` at entry +
`data = new_var` at L378; HAZARD-FREE unlike permuter's 0x20-arm form. Gives
98.20 not 98.76 — driver-4's 98.76 used a different new_var spelling. The
qualitative verdict is spelling-independent: still 6 CSR, still spanning-web
cascade.)

### Decomposition verdict: x48-alone is NOT the separable good half

COLORGRAPH dumps (fresh DLL, /tmp/pc_baseline.txt, /tmp/pc_x48alone.txt;
HandleInput section both n_nodes=194):

- **baseline** callee-save tail: iter135 ig34(var_r28)→r28, iter137 ig32(gobj)→**r27** = 5 CSR, no r26.
- **x48-alone** callee-save tail: iter93 ig103(x48 web)→r29, iter94 ig102(mn_addr)→r28,
  iter137 ig34(var_r28)→**r27**, iter139 ig32(gobj)→**r26** = **6 CSR**.

x48 creates ig103, which pops iter93→r29 (HIGHER ig_idx pops first among equal
degree=11, verified), displacing mn_addr to iter94→r28, which cascades the
whole tail down one register so gobj lands on r26 = the 6th callee-save. **The
6th callee-save is an INTRINSIC consequence of x48, not of new_var.** The
prompt's "x48-alone good half / +new_var 6th-CSR bad half" split does not exist
in codegen — x48 alone already emits `stmw r26`.

### Faithfulness verdict per component (vs the target's web structure)

1. **Does the target have an ig103-analog (the B4→B7 x48 web)?** NO. Target
   entry region is exactly 5 webs (result r31, mn_addr r29, var_r28 r28, gobj
   r27). There is no extra zero-web taking r29 ahead of mn_addr. x48-alone's
   `li r27,0` (the x48 web, separate from var_r28's `li r29,0`) is a FOREIGN
   instruction the target does not emit. x48 = right behavior (no-li store) by
   the WRONG web (a redundant zero-web that displaces the CSR chain).

2. **Does the target get the 6th callee-save without a spanning web (new_var =
   right color by wrong web)?** The target has NEITHER a 6th callee-save NOR a
   spanning web. Target = 5 CSR. new_var's spanning web dissolves the S1 reload
   (Δ0, genuinely faithful for S1!) but the SAME spanning web displaces the
   matched entry trio (46 hunks) — confirming the iteration-3b class rejection.
   The "right web" for the 6th-CSR question is: there is no right web, because
   the target needs no 6th CSR.

3. **THE KEY FINDING — S2 is NOT a coloring problem.** Baseline's entry coloring
   ALREADY MATCHES the target byte-for-byte through +03c (`addi r31,r3` /
   `addi r29,r4` modulo the R3 order swap; `stw r31,12(r29)`; `li r28,0`;
   `stw r28,8(r29)`). var_r28 is ALREADY in callee-save r28, ALREADY live across
   the lbAudioAx call. The target emits `stb r28,17(r29)` reusing that r28;
   baseline emits `li r0,0; stb r0` REMATERIALIZING the constant at the same
   site. **This is a pure CP/peephole decision DOWNSTREAM of an already-correct
   coloring — not a register-allocation or web-structure difference.** x48's
   no-li is therefore NOT reproducing the target's mechanism: ~~it gives the
   peephole a redundant callee-save zero-web to eliminate~~ [RETRACTED iter-6:
   no B7 li ever exists in the x48 IR — the store reads x48's web directly;
   see iteration-6 "x48 mechanism CORRECTED"], which only works by
   pulling in the 6th CSR. The target reaches no-li by simply not
   rematerializing from the coloring baseline already has.

### Commit decision: NONE

Neither component passes BOTH gates (neutral-or-better AND web-faithful):
- x48-alone: numbers better (98.46) but web-UNFAITHFUL (foreign ig103 web + 6th
  CSR the target lacks). REJECTED on faithfulness.
- x48+new_var: numbers mixed (98.20, Δ0 good but 46 hunks), web-UNFAITHFUL
  (spanning web displaces matched entry — known class rejection). REJECTED.
- Baseline retained. Match stays **97.46%**.

### What this implies for driver 6

- **STOP treating S2 as a register/dispenser problem.** The "find a C shape that
  dispenses r28 in the iter93-97 window" search target (driver-3/4 doctrine #2)
  is MISDIRECTED for S2: baseline already colors var_r28→r28 with the target's
  exact entry layout. S2 is a CP-remat-vs-reuse decision at one store site.
- **The faithful S2 lever (if it exists) must suppress MWCC's constant
  rematerialization of var_r28=0 at the entering_menu store**, WITHOUT adding a
  web (no x48, no spanning var). Driver-4 closed all `var_r28 = <const-expr>`
  spellings (all fold to const 0 → same CP). UNTRIED classes for driver 6: (a)
  make var_r28's value non-constant on the B4→B7 path so CP cannot fire (e.g.
  the entering_menu value sourced from a runtime expression that equals 0 but
  isn't compile-time-provable — but note buttons[0] also reads it, and a
  non-zero-provable value may break buttons[0]'s `stw`); (b) the sibling
  campaign's PER-BRANCH HOME-LOCALS control surface — give the 0x20-arm a home
  local for the entering_menu value distinct from var_r28, pinned by a
  plain-store/region-temp form (sibling 80243434 §final mechanism: home locals
  invert pop/emission order where statement order can't). This is the one
  genuinely new instrument not yet pointed at S2.
- R3 (addi +028/+02c order swap) remains the other entry residual; baseline's
  coloring is correct, only emission order differs (schedule-oracle: outside the
  force-schedule family — iteration-3b).
- Permuter corpus exhausted (228K, 0 safe); do not re-run.

## Iteration 6: S2+S1 dissolution oracles (driver 6, 2026-06-11)

THE ONE QUESTION: can S2 (CP remat) and S1 (reload) be dissolved faithfully?
ANSWER: **NO with all instruments and spellings probed this round — and both
walls now have COMPLETE mechanism statements.** 1 forced run + 1 source build
used; both home-locals builds were PRE-REFUTED by their oracles (the
oracle-first structure prevented 2 wasted builds). Match stays **97.46%**.

### ORACLE (a) — S2, the CP temp force-probe (1 forced run)

Baseline IR facts (from /tmp/pc_baseline.txt, HandleInput n_nodes=194):
- The B7 store reads a CP-materialized fresh temp: pre-coloring pcode B7 =
  `li r103,0; stb r103,17(r101)`. ig103-baseline = deg 0, nIntfr 1
  (sole interferer ig101=mn_addr), pops iter91 → r0.
- ig34 (var_r28) does NOT interfere with ig103 ⟹ forcing ig103→r28 is legal.

Forced run `--force-phys 0:103:28` (applied, verified `[FORCE_PHYS] class=0
ig_idx=103: r0 -> r28` in dump):
- Result: `+04c li r28,0; +050 stb r28,17(r29)` — the stb row becomes the
  TARGET's exact bytes, but **the li survives**. Diff row count 818 = control
  818. **Score delta: ZERO.**
- VERDICT: the post-coloring peephole does NO cross-web redundant-zero
  elimination, even at identical registers with a dominating same-register
  `li r28,0` in B4. S2 is not reachable by ANY coloring instrument; the li
  must be prevented in the FRONT-END.

### x48 mechanism CORRECTED (refutes driver-4 iter-4 + my iter-5 echo)

x48-alone pre-coloring IR, B7: `stb r103,17(r102)` — **NO li in B7 ever
exists**. The store reads x48's web (v103, def `li r103,0` in B4) directly.
Driver-4's "peephole eliminates the redundant li in B7" account is REFUTED —
there was never a B7 li to kill; the iter-4 "MODEL GAP: ig103 live B4,B7
without a B7 use" is NO GAP — the B7 store IS the use. (My iteration-5
sentence "gives the peephole a redundant callee-save zero-web to eliminate"
inherits the same error — retracted.)

The actual front-end rule (CP exclusion rule, dump-verified both forms —
identical `propagation at 52/58 from 34` events):
**CP severs a provably-constant local's use and NEVER rebinds the severed
web; the materializer reuses a DIFFERENT live same-constant VARIABLE web if
one exists (x48 form), else emits a fresh block-local temp (baseline).**

### BUILD (a) — literal store (1 build, REVERTED)

`mn_804A04F0.entering_menu = 0;` (literal, no severing → materializer free to
bind var_r28's tree?): **REFUTED — byte-identical to baseline** (97.5, Δ3,
hunks 5, same `li r0,0; stb r0`). The literal-constant store path emits a
fresh block-local temp unconditionally; it does no availability search. The
x48-style reuse fires ONLY via the CP machinery binding another VARIABLE's
tree.

### S2 wall — complete mechanism statement (4 facts)

1. CP severs the provably-constant local use; never rebinds the severed web.
2. Literal stores take the fresh-temp path unconditionally (build a).
3. The fresh temp's li is unremovable downstream — no cross-web
   redundant-zero peephole, even color-matched (oracle a).
4. A second zero-holding variable web crossing the call costs the 6th
   callee-save (x48, iter-5).
⟹ The target's no-li form requires the store to read an ALREADY-NEEDED live
web — var_r28's own (r28) — which is exactly the web CP excludes. Closed
spellings: all const-expr RHS (driver-4), literal store (this driver),
coloring/peephole instruments (this driver). Open routes are all
damage-trading: CP non-firing via non-provable value (risks buttons[0] stw)
or aliasing exposure (`&var_r28` — forces memory home, wrecks +034 li r28;
NOTE the unexplained PAD_STACK(40) is consistent with SOME address-exposed
local in the original, but no natural form found). S2 home-local build
PRE-REFUTED: any new zero local is another fresh/foreign web (li survives or
6th CSR).

### ORACLE (b) — S1, the dissolution property (dump read, x48+new_var)

From /tmp/pc_x48newvar.txt (recreated form, dump-only, reverted):
- The dissolution: new_var's entry/bottom copies COALESCE into the entry data
  web → single merged web **ig40 (deg 27, nIntfr 93)** → the 2-instruction
  re-derivation disappears entirely (Δ0). Property named:
  **reload-as-coalesced-copy.**
- The cost, precisely: merged ig40 becomes the SOLE front-band node (pops
  iter0 → r31) and **result (ig100) drops OUT of the front band** to the
  descending-ig band (pops iter93 → r28) — the entry-trio displacement.
- **Band-membership arithmetic (new, measured):** result's nIntfr across
  forms: baseline 33 (IN band, pops iter0), x48-alone 34 (IN band),
  x48+new_var 32 (OUT of band). The merge costs result exactly 2 interferers
  (bottom-data pair fuses to 1: −1; the reload's short-lived sda21 temp dies:
  −1); x48 adds +1. The front-band threshold for result sits between 32 and
  33 nIntfr (or its degree-during-simplify equivalent).
- Faithfulness implication: the target (result=r31 first, spanning data=r30
  second) needs result IN the band under the merge. Target arithmetic by our
  model: 33−2=31 < 33 ⟹ either band membership is not a fixed-nIntfr
  threshold (it is degree-at-simplify-time, which we cannot read from the
  pop-time dump), or the target's graph holds ≥2 long-lived interferers we
  do not model (40-byte frame object territory). Driver-7's quantitative
  attack: compute INITIAL degrees from LIVERANGES (not pop-time degrees) for
  result in baseline vs merged; if the in/out gap is 1-2 edges, enumerate
  which natural web could add them.
- S1 home-local build PRE-REFUTED: a bottom-region `d3 = data` copy local
  coalesces into the entry web = exactly this merged class (or driver-3's
  single-web rotation 96.7, same family). Not built.

### Cross-campaign mechanism statement (InputProc transfer pricing)

InputProc's +048 fresh-li last line is the same family as S2. Priced
transfer: the fresh-li class is NOT removable by coloring, forced colors, or
peephole (oracle a). The ONLY no-li form is a store/use that reads a live
same-value VARIABLE web that exists anyway. Triage rule for InputProc: if a
live same-value callee-save exists at +048 AND the stored value is NOT a
CP-severed constant local read, the rebind class applies (find the spelling
that reads that variable); if the value is a CP-severed constant local (as
here), it is the same 4-fact wall — do not spend coloring probes on it.

### Iteration-6 ledger

- Forced runs: 1 of ≤2 (ig103→r28). Builds: 1 of ≤3 (literal `= 0`).
- Commits: doc-only (this section). Source unchanged; baseline 97.46
  (Δ3, hunks 5) verified before and after; protected fns intact.
- For driver 7: S2 = closed-spelling wall with complete mechanism (open
  routes are damage-trading only); S1 = band-membership arithmetic question
  (LIVERANGES initial-degree read is the named next instrument); R3/S3
  unchanged.

## Iteration 7: band-faithful merge — threshold pinned, supplier census failed (driver 7, 2026-06-11)

THE ONE QUESTION: can the S1 merge be made band-faithful (Δ0 merge + result
kept in the front band)? ANSWER: **NOT via the entry window — the threshold
model is now PINNED EXACTLY and the only census-compatible supplier class
fails, measured.** Stopped at the prompt gate. Match stays **97.46%**.

### HEADLINE 1 — the front-band cut is a FIXED COUNT: T=33 (model pinned)

Method: parsed both existing COLORGRAPH dumps' full adjacency (continuation
lines included; parsed counts == nIntfr column exactly for all key nodes) and
simulated candidate rules against the OBSERVED pop orders:

| Rule | baseline (138 popped) | x48+new_var (139 popped) |
|------|----------------------|--------------------------|
| incremental scan-time deg < k=29 | 6/138 FAIL | 139/139 |
| batch (sweep-start) deg < k=29 | 138/138 | 45/139 FAIL |
| **fixed cut nIntfr ≥ T=33 → front** | **138/138** | **139/139** |

Sensitivity: baseline allows T∈[28..33]; merged requires T∈[33..39];
**intersection = exactly 33**. Verdict: NOT a relative ranking, NOT dynamic
scan-time eligibility — a fixed full-count cut at nIntfr ≥ 33 (the count
INCLUDES the 11 phys volatiles; ANY overlapping web counts, even deg-1
temps — the bottom reload's sda21 base temp was a counted result-edge).
Pop order = descending ig within each side; front pops first. This sharpens
iteration-6's "between 32 and 33" to an exact constant and explains every
observation this campaign: driver-3's single-web rotation (merged web ≥33,
result 31 → out), x48+new_var's 46 hunks (result 32 → out), x48's failure to
help (+1 only). CAVEAT: T=33 = k=29 + 4, offset unexplained; pinned on two
graphs of THIS function — re-pin per function before reuse (the methodology
doc's k=29 scan phrasing for InputProc may describe its graphs equivalently;
not contradicted here). Simulator: ~60-line python over the COLORGRAPH
adjacency (parse rows + wrapped interferer lines; cut at T; reverse-pop).

### The requirement, exact

Result-neighbor diff (baseline ig99 = 22 virtuals vs merged ig100 = 21):
the merge kills exactly 2 result-edges — the data-pair fusion (39+57→40) and
the bottom reload's sda21 base temp — and x48 adds 1 (ig103). S1-only merge:
result = 31. **Band-faithful merge needs +2 result-edges**, byte-invisible,
present in the target's census.

### HEADLINE 2 — supplier survey + target-census check: FAILED, stop

Entry-window survey (M1 playbook):
- **u64 buttons store** (the field IS u64 @0x8; InputProc's committed winner
  `mn_804A04F0.buttons = input;` is the same idiom on the same global):
  the ONLY candidate class. Call-arg temps = copy-propagated to immediates,
  no live range (safe-zone law) = no edge. Dead anchors = no live range =
  no edge (skipped per doctrine). No other u16/u64 entry-window construct
  exists without new instructions.
- Target census: the target entry window is byte-identical to ours (modulo
  the R3 addi order) ⟹ NO visible extra webs. The u64-conversion class is
  the unique byte-invisible candidate.
- **Census check MEASURED — FAILED.** The fused spelling
  `mn_804A04F0.buttons = ((u64)(u32)(var_r28 = 0) << 32) | (u32)result;`
  (the only spelling preserving our target's single fused `li r28,0`):
  MWCC 1.2.5n emits a runtime **`__shl2i` CALL** for the 64-bit shift — it
  does not fold even a provably-zero shift operand (probe dump: li r3,0;
  li r4,0; li r5,32; bl __shl2i; or; stw — entry window demolished, 879 diff
  rows vs 818 control). Generalizes the methodology doc's "u64>>32 fails as
  __shr2u": ALL u64 shifts are runtime calls on this compiler. The shiftless
  plain form (`buttons = (u32)result;` + separate `var_r28 = 0;`) is
  InputProc's spelling but predicts TWO zero-li's (conversion-zero temp +
  var_r28; home-class virtuals are excluded from copy-coalescing, and
  iteration-6's literal law gives the hi-half a fresh temp) vs OUR target's
  single li r28 ⟹ census-incompatible with THIS target.
- **⟹ The +2 margin cannot come from the entry window's natural
  constructs. Stopped per the gate; the ≤2 build budget unused** (no
  target-supported candidate emerged; building known-byte-breaking forms is
  waste).

### What this prices for driver 8 (the "elsewhere")

1. **The full-count cut widens the supplier space beyond the entry window**:
   ANY byte-invisible web overlapping result's (whole-function) live range
   counts +1 — the survey was entry-scoped per the M1 playbook; the
   0xC0/0xC00/bottom windows were NOT surveyed. Named candidate class:
   WEB-SPLITS of existing variables into two result-overlapping regions at
   zero instruction cost (du-chain splits via identity spelling — x46/x47
   arm chains, var_r5's two assignment pairs, d2). Two such splits = +2.
2. The 2 missing edges EXIST in the original's graph (target result ≥33 by
   the pinned model, assuming the target front is {result, data} per its
   r31/r30 layout) — they are webs our reconstruction fuses or avoids:
   the discovery target is which two.
3. Do NOT revisit: u64 spellings on this function (shift=__shl2i call,
   plain=2-li), entry-window call-arg/dead-anchor suppliers (no live range).

### Iteration-7 ledger

- Dump/forced runs: 1 of ≤2 (merge+fused-u64 probe). Builds: 0 of ≤2.
- Commits: doc-only. Source untouched (probe reverted same-session);
  baseline 97.46 (Δ3, hunks 5) re-verified; protected fns 100/100/98.67.

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
