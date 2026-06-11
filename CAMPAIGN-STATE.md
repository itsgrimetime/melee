# mnDiagram_InputProc register-allocation campaign — state brief

## Current state (2026-06-10, iteration 23)
- Worktree: `.claude/worktrees/mndiagram-802427B4-investigation`, branch `claude/mndiagram-802427B4-investigation`
- **Match: 95.4%** (95.36 precise). Commit stack (do not rebase away):
  1. `a152f6c58` init count at decl (94.53→94.6)
  2. `b3a4ecedd` split col/row_result into per-region locals (body-identical, target-like webs; A-row now r0 = target)
  3. `1e3a4a595` reorder split decls (94.6→94.7; nav webs snapped to r26/r26)
  4. `ac4884952` split steps into per-region locals (body-identical)
  5. `d1004e97a` split row into per-region locals (body-identical)
  6. `a280837d4` clang-format pass (whitespace only)
  7. `9802e44e6` restore (u8) found casts in up_n/dn_n/up_f/dn_f find loops
  8. `26271d5d1` restore (u8) compare casts in lf_f/rt_f (94.7→95.0)
  9. `ec552699b` restore (u8) found compare casts in up_n/dn_n/rt_n (95.0→95.2)
  10. `ed09c6e1f` clang-format pass (whitespace only)
  11. `999489a09` Merge branch master into worktree
  12. `0372241ee` hoist entering_menu=0 before d=user_data in B-button arm (95.2→95.4)
- Structural mnemonic diff: **1 delta** — `+168 lhzu` (target load-with-update, ours `lhz + addi`).
  All other diffs are register-renaming only.

## π (target registers per web; force-phys-fingerprint verified)
- count-web (ig114, the 0xC00 fighter-loop counter + buttons-hi zero CSE; sites +3c/+44): **r25** (ours r27)
- B-col / B-row (0x10 fighter arm, sites +188/+1ec clusters; igs 38/37): **r27 / r26** (ours r26/r25)
- nav webs (+9bc/+b98 clusters; igs 41/39): r26/r26 ✓ matched
- A-col (pool, +c4): r24 (ours r27, open); A-row (+124): r0 ✓ matched
- proc(32)=r24 ✓; identities 50/157/162/159 = r31-r28 ✓

## The allocator model (all measured, this worktree's dumps)
- SELECT order = descending ig_idx within sweeps (3 exceptions/365 = degree-phase front 44,153,158 + sweep boundary).
- Pick: volatiles low-first; reuse dispensed callee-saves ascending; fresh r31-down. Surrogate `tiebreak` validates G1 100%; what-if + order-solve scripts in iteration history.
- 12/720 tail orders reproduce π; ALL require ig(B-col) > ig(B-row) > ig(count-web).

## The numbering map (measured; the campaign's deepest result)
1. params r32+; **locals = REVERSE declaration order** (~r33-56) — decl position is a working renumbering knob (got the +0.1 nav-web fix).
2. statement temps ~r57-110 (emission order).
3. **IRO-pass temps r111+**: the IRO-exit promotion pass (between EvaluateConditionals and RebuildCondExpressions; fresh ledger /tmp/retro23) rewrites **multi-web loop-carried variables** to per-web @-temps (**@1008=nav-fighter count=ig118** — iteration-23 corrected the old @1010 claim). Spelling-immune (for/while/++/accumulator probes T1-T3 all inert).
- Numbering (iteration-23 corrected): variables in FIRST-USE order; webs within a variable in REVERSE node order (latest region = lowest @). Loop OUTPUTS (col_result*/row_result*) are never promoted.
- ⟹ ig(B-col)>ig(count) is unreachable by NUMBERING (temps outrank homes) — but the POP ORDER is reachable via the spill-candidate push channel (see iteration-23 order oracle: +31 lines).

## Open question (iteration-10 entry point)
Target emitted the identical body from DIFFERENT IRO internals (different temp counts/numbering upstream). Prime suspect: the m2c goto-soup dual-pointer walks (nc/nr/fc/fr loops, lines ~1013-1158: i/ptr/ptr2 triple-walk = 3 promoted vars per loop). An index-only original spelling would change the @-temp sequence before count's @1010, shifting select order. The required-order constraint (B-pair first) is relative to OUR interference graph — a reshaped graph changes the requirement too. Oracle stands: force-iter-first slot-6 → count r25 (real allocator).

## Tool recipes
- Meter: dump `melee-agent debug dump local src/melee/mn/mndiagram.c --output X --no-cache-sync`; find InputProc's SIMPLIFY/COLORGRAPH (class=0, biggest n_nodes); count-web = the 0xa row in the top-10.
- Web fingerprint: `--force-phys "IG:14,IG2:15" --force-phys-fn mnDiagram_InputProc --diff` → ours-side lines with r14/r15 = exact web sites.
- π extraction: checkdiff `--format json` → target_asm/current_asm → difflib align (skeleton: mnemonic + CS-regs wildcarded) → per-position reg pairs.
- Order solve: tiebreak module `predict_assignments(ig, order=...)` over tail permutations (iteration-7 script).
- Retro IRO ledger: `melee-agent debug retro dump src/melee/mn/mndiagram.c -f mnDiagram_InputProc -O /tmp/retro8` (62 phase dumps + iro-summary.txt node ledger).
- Body gate: checkdiff opcode similarity must stay ≥ 88.1 / line delta ≤ 1 / hunks ≤ 42 / match ≥ 95.4%.

## Don'ts (proven dead ends)
- force-interfere on count (edges exist), add-interferer what-ifs, decl-init renumbering of count (DCE'd), surviving-init (no sink, body breaks), input-decl reorder (body breaks), B-pair dead decl-inits (body breaks, no renumber), loop spelling probes T1-T3 (IRO-normalized).

## Iteration-10 addenda (real-allocator oracle + reshape verdicts)
- REAL-ALLOCATOR π-ORDER TEST: force-iter-first "50,157,162,159,38,37,114,41,39,32" executes the
  12/720 winning order EXACTLY (clique lands 38=r27, 37=r26, 114=r25, 41=r26, 39=r26, 32=r24) but
  fixes ONLY count's 2 sites (+3c/+44), breaks 0: 708→706 mismatch lines. ⟹ B-pair π readings
  (r27/r26) were skew artifacts — their sites mismatch under BOTH colorings; clique order is NOT
  the remaining gap. The ~706-line residual is pool/web-structure (upstream IRO).
- WALK-VAR SPLIT (i/ptr/ptr2 per region, nr/fc/fr): FAILS body gate (opcode 80.6, Δ5, hunks 35)
  — unlike col_result, the shared walk locals are body-faithful. Do NOT retry.
- Next entry point: the pool residual's per-site target regs need a clean re-extraction
  (difflib path, avoiding the skew regions) before any further restructuring; and the spill-front
  membership idea (B-pair degrees vs k=29; front members are degree 47/33/14/13) remains untested.

## Iteration-11: the global map (no source edits)
- Skew-aware alignment: 767/777 instrs aligned, ~28 skew-noise, **172 confident reg-mismatch sites**
  (the "706 lines" was diff inflation). Artifacts: /tmp/map11.pkl, /tmp/webmap11.pkl.
- HISTOGRAM (attributed 139 operand-sites; 65 sites unattributed=pcode-align gaps, 6 self-check fails):
  CONSISTENT-RENAME 45 webs/129 sites (93%) | SPLIT 2 webs/10 sites (ig94, ig95: r23-vs-r26).
- Top webs: ig114(count) r27→r25 ×7; ig91 r25→r27 ×6; ig34 r23→r25 ×6; ig33 r23→r26 ×6;
  ig107 r24→r23 ×5; ig105 r24→r28 ×5. All pool scratch temps in the nav/walk regions.
- Greedy global-order reachability (π = 45 consistent + preserve rest): 318/370 placed,
  **19 π-webs stuck** — not a proof of unreachability (greedy incomplete) but the stuck direction
  is uniform: ours-LOWER-than-target (r23→r25/26/28, r24→r25/28, r25→r27...). Signature: target's
  allocator had MORE webs holding low pool regs at those select moments ⟹ web COUNT/composition
  differs upstream ⟹ more m2c-merged variables need per-region splitting.
- WORKLIST (gated per-var, col_result-style; walk i/ptr/ptr2 already FAILED the gate):
  split candidates shared across 8+ nav regions: steps, cur, found, col, row, new_var.
  Each split: body gate must PASS; watch pool web count + the stuck-19 list shrink.

## Iteration-12: split worklist executed
- steps: PASS (4 regions) committed 94.7=. cur: FAIL gate (opcode 80.0, Δ5). found: FAIL (Δ7;
  region-8 tail at 1710 gotcha fixed but still Δ7). col: FAIL (opcode 80.7). row: PASS (6 regions)
  committed 94.7=. new_var: unsplittable (single def at 1466 feeds all reads).
- NEITHER inflection fired: count still r27/slot4 (front stayed 4 members); no cascade fixes.
- Verdict: the splittable m2c-merges are exhausted (col_result/row_result/steps/row = committed;
  cur/found/col/i/ptr/ptr2 are body-relevant merges = the ORIGINAL shared them). Pool-pressure
  hypothesis NOT yet confirmed by yield — the committed splits were match-neutral. The stuck-19
  under-pressure signature must come from something else: remaining candidates = the unattributed
  65 sites' webs, the A-col pool web (r27 vs target r24), and the front-membership/degree question.

## Iteration-13: front-membership experiment (force-interfere #549, revived)
- Front rule: not pure degree (peel sim reproduces the SET not the ORDER; G2 remains open).
- Candidates: ours recomputes &mn_804A04F0.hovered_selection SIX times (pre-color temps
  r129-r151, pool r24/r25); target colors ALL instances r27. Walk-base adds = the r26 family.
- Exp-1 (129 + 32 high-ig edges): ig129 JOINED the front region (slot 4, fresh r27) — induction WORKS.
- Exp-2 (+129=114 edge, +ig91): count denied r27 -> r26 (one register toward r25); ig91 (low ig)
  popped after count (numbering); score 708->705 (-3 sites only).
- Exp-3 (129+132 both, 67 edges): config silently didn't apply (suspect edge-count cap) — baseline.
- VERDICT: front-join + count-denial mechanisms PROVEN, but score stays ~flat: the target's
  r27-sites are six SHORT pool webs that all happen to pick r27 (not one long web) — the uniform
  ours-lower pool direction is most plausibly DOWNSTREAM of count popping later in target
  (dispensed-evolution channel: count@r25 blocks r25 for ~50 interferers -> pool reuses r26/r27/r28).
  Iteration-6's force-phys 114:25 didn't replicate it because force-phys keeps count's SLOT;
  the pool needs count's POP to come after two pool dispenses. Next vehicle: force count's POP
  later (force-iter-first with two pool igs >114 ahead of it, e.g. 129,132 prefix) and SCORE —
  if the pool follows, the entire residual is one select-position; then find count's natural
  later-pop in C (its 0xa/coalesce-root status exempts it from pure numbering — the rep/ROOT
  flag question from iteration 11 is the remaining unknown).

## Iteration-14: surrogate full-pi order search — ORDER CHANNEL EXHAUSTED
- pi rebuilt on current cast (/tmp/pi14.pkl): 45 webs/129 sites.
- count-slide alone: best +4 slots = 5/45 webs (17 sites), 3 regressions. Dispensed-evolution-via-
  count-alone REFUTED.
- Hill-climb (18 moved igs): max 26/45 webs (68/129 sites) WITH 13 regressions — no select order
  of OUR graph reproduces pi. Unreached 19 webs (/tmp/best14.pkl): NO uniform direction (10 want-
  higher, 9 want-lower), includes volatile-class wants (ig141 r4->r5 arg-reg, ig152 r0->r28) ⟹
  the TARGET'S INTERFERENCE GRAPH / WEB EXTENTS DIFFER. Composition, not order.
- Confirming build: INCONCLUSIVE — 365-element force-iter-first vector silently not applied
  (same silent-cap class as iter-13 exp-3) → issue #550 filed (apply-or-die + echo count).
- VERDICT: residual = composition divergence distributed over ~19+ pool webs (walk/nav temps,
  arg-setup temps). The original's webs have different EXTENTS (longer/shorter lives, different
  CSE) that no reordering of ours matches. Next vehicle must change the GRAPH: per-web extent
  diagnosis on the top unreached webs (ig34 r23->r25 x6, ig105 r24->r28 x5, ig107 r24->r23 x5,
  ig82/83/84/99...) — what value each is, where its live range starts/ends vs what pi implies.

## Iteration-15: TARGET WEB RECONSTRUCTOR + extent-delta table
- Tool: tools/target_web_reconstructor.py (CFG from target asm + reaching-defs + union-find webs).
  Usage: python3 tools/target_web_reconstructor.py <checkdiff.json>. Gates: 4 identity webs OK;
  target callee-save webs = 105 vs ours ~95 (target MORE populated, as pool-pressure predicted).
- HEADLINE: target count-web = ONE FUSED r25 web, 15 sites, +3c..+b60 (zero + name-arm + fighter-
  nav) where ours is split (IRO @-temp ig114 + home-anchored name web). Candidate body-identical
  edit: move `count = 0;` (line 1220) ABOVE the is_name_mode branch (dead on name path -> same
  emitted code, but the IR web fuses through the phi) — NOT yet tested.
- Extent-delta of the 19: 8 = same-extent pure renames (downstream cascade of the true deltas);
  true composition deltas concentrate in fighter-nav +98c..+bf0: ig97/ig53/ig52/ig131/ig66 = ours
  single-site scratch webs where target has 3-4-site webs spanning 0x30-0x60 more (starts earlier,
  ends later, FUSED) — original kept cursor/found-family values LIVE LONGER (cached vs re-derived).
  Medium: ig106/ig99/ig54/ig123/ig117/ig98 small end-shifts, same direction.
- RANKED HYPOTHESES: (1) count = 0 hoist (15 tgt sites + unlocks the r25 chain + likely flips the
  8 renames downstream); (2) fighter-nav caching: one local holding the re-derived cursor value per
  arm (ig97/53/52 cluster ~17 sites); (3) same pattern, name-nav (ig99/106 ~8 sites).

## Iteration-16: H1/H2 verdicts
- Reconstructor committed (tools/target_web_reconstructor.py).
- H1 (count=0 hoist above is_name_mode branch): BOTH placements FAIL body gate (opcode 79.3,
  delta 7-8/hunks) — MWCC does not cleanly DCE the hoisted dead zero; the count-web fusion the
  target shows cannot be produced by a dead hoisted store. The fusion mechanism remains unknown
  (target: ONE r25 web +3c..+b60; candidates left: different is_name_mode branch shape, or the
  fusion is an artifact of reconstructor unioning through phi paths — VERIFY with a finer-grain
  read before further edits).
- H2 recon: the ig97/53/52 fighter-nav delta region (+98c..+a0c) is a SKEW block — same instruction
  multiset, different ORDER; source lead-ins are m2c-inconsistent (up_f/lf_f found-first vs
  dn_f/rt_f ptr-first at lines 1487/1527/1601/1641) BUT the skew sits in dn_f (already ptr-first)
  ⟹ the order difference is allocation-driven scheduling, not statement order. The cached-local
  H2 design needs the per-arm value identity read (which value target holds across +98c..+9ec in
  r27 = ptr=sorted+cur held across the walk loop; ours rematerializes via mr r27,r23+adds).
  NEXT: H2 edit = keep ptr live across the dn_f walk (use ptr instead of re-deriving from cur in
  the post-loop sites); gate strictly. H3 untested.

## Iteration-17: fusion OVERSTATED + skew census = the (u8)-cast worklist
- STEP A: count mega-fusion (+3c..+b60) = reconstructor ARTIFACT — chain links li r25,1
  (is_name_mode store +388) into count compares (+8b4) with no GetNameCount def in web =
  CFG leak (false fallthrough). True target count-read web ≈ +848..+b60; zero web separate.
  Reconstructor needs CFG fix before further fusion claims (blr/return + branch-target audit).
- STEP B: dn_f `col_result4 = *ptr` FAILED (lbz vs target lbzx, opcode 72.3) — target's
  post-loop read IS sorted[cur]; reverted.
- STEP C CENSUS (the real find): skew blocks are DIFF-MULTISET, dominated by ~9 clrlwi (u8
  truncations) PRESENT IN TARGET, MISSING IN OURS (+5e8 x2, +6f4 x2, +7b0 x2, +8f0, +9c0 x2,
  +ad8, +ba8) balanced by ours-extra addi/mr (+48c,+518,+5f4,+684,+6e4,+79c,+7b4) and one
  lhzu-vs-addi+lhz at +168 (update-form load = pointer-walk spelling). Line delta 8 = target
  has ~8 MORE instructions = mostly these casts. m2c DROPPED (u8) casts the original had
  (some arms kept `found = (u8) found;` — the pattern exists in source at some sites already).
- ITERATION-18 WORKLIST: per missing-clrlwi site, identify the variable/arm (nav-loop found/cur
  truncations) and add the (u8) cast; convergence gate = clrlwi appears at the aligned offset +
  hunks/line-delta shrink + match% up. Then the +168 lhzu spelling (lhzu = `*++p`-family form).

## Iteration-18: CAST RESTORATION — 94.7 -> 95.0, opcode 81.0 -> 88.2, delta 8 -> 3
- Group 1 (committed): GetNameText((u8) found) + hit-branch `found = (u8) found;` in up_n/dn_n
  + hit-branch casts in up_f/dn_f (delta 8->5, opcode 81.8).
- Group 2 (committed): compare-site `cur != (u8) found` in lf_f/rt_f mirroring lf_n's surviving
  spelling (delta 5->3, opcode 88.2 (+6.4!), match 95.0). First match% movement since 94.53->94.7.
- REMAINING structural deltas (census on /tmp/cur18.json): ~8 clrlwi at +52c/+5e8x2/+6f4/+7b0x2/
  +9c0/+ba8 PAIRED with ours-extra addi (+524/+5e0/+5f8/+688/+6e8/+7a4/+7bc) = the up_n/dn_n WALK
  regions: ours derives via addi (ptr-arithmetic) where target truncates via clrlwi — a value-flow
  difference in the walk-adjacent derivations, not a simple dropped cast. Plus +168 lhzu (update-
  form load, untried) and +250/+25c stb position swap.
- Reconstructor CFG-fix still on worklist (false-fallthrough leak, iteration-17).

## Iteration-19: structural closure to delta=1 + re-census
- up_n/dn_n/rt_n compare casts `cur != (u8) found` (mirroring lf_n) committed: 95.0->95.2,
  line delta 3->1, opcode 88.1. The only remaining structural delta = +168 lhzu (target
  load-with-update of the mn_804A04F0 base; needs an advancing-pointer spelling; no natural
  candidate found — OPEN) and the +250/+25c stb position swap (untouched).
- RE-CENSUS: 176 confident register-mismatch sites (was 172 — restored instructions add register-
  wrong-but-structure-right sites; fuzzy match rewards the alignment: 95.2). Top renames:
  r27->r24 x21, r25->r24 x16, r27->r25 x15, r24->r23 x15, r28->r24 x13.
- NEW-CAST ORDER SEARCH: natural 0/45; hill-climb max 28/45 webs (73/130 sites) with 17
  regressions, 24 moved igs — order channel STILL insufficient post-closure. The register
  residual remains extent/composition-driven (plus the open lhzu + stb items).
- Iteration-20 decision input: remaining-extents diagnosis on the new top rename webs; the
  lhzu spelling hunt; reconstructor CFG fix for trustworthy target extents.

## Iteration-20: RECONSTRUCTOR VALIDATED — iteration-17 "artifact" verdict REVERSED
- Instrumented union events for the +3c..+b60 r25 web: the links are LEGITIMATE phi-webs:
  (a) +38c `stb r25,68(r31)` = the `is_name_mode = (==0) ? 1 : 0` ternary — its 0-arm REUSES
  the +3c zero (defs {+388 li 1, +3c li 0} feed one use = real multi-def web);
  (b) {+3c, +85c} = loop init+backedge phi (the +84x-+b60 nav count/steps chain inits from the
  SAME +3c zero — no separate li in target).
  Hand-trace with within-block kills over the same CFG confirms no false path; CFG is sound.
  ⟹ TARGET REALLY HAS the mega-fused r25 zero-web (buttons-hi + ternary-0 + nav-count chain).
  Ours has the same FUSION FAMILY (ig114 = the 0xa coalesce-ROOT absorbing zeros) but colored
  r27 (slot 4) — the fusion is real in BOTH compiles; the difference is COLOR/POP-POSITION of
  the SAME-SHAPED web after all, PLUS whatever extent differences remain in the nav chain.
- No reconstructor code change needed: acceptance criteria reinterpreted (the +388 link SHOULD
  appear). The iteration-15 finding stands: ONE r25 web +3c..+b60, 15 sites.
- IMPLICATION for the endgame: ours-ig114 vs target-r25-megaweb extents must be compared
  precisely next (does OUR 0xa web cover the +84x-+b60 chain sites the target's does? If ours
  covers fewer — the nav count reads live in OTHER our-webs — that's the true extent delta;
  if same, it's purely the slot-4-vs-later pop again, now with the +85c init-sharing as the
  C-shape clue: target's nav-loop counters INIT FROM the shared zero rather than fresh li's).
- Iteration-19 leftovers still open: +168 lhzu, +250 stb, extent table regen (STEP B not
  completed this round — context), top-rename extent classification pending.

## Iteration-21: site-coverage diff + the 6-site force proof
- STEP A table: all 15 target-megaweb sites align to ours' r27 instructions; attribution SAID
  ig118 everywhere — but the FORCE-PHYS PROBE (118:25) corrects it: fixed exactly 6 sites
  (+3c/+44 zero pair, +a74/+a98/+b3c/+b60 = input&4/&8 count reads), broke 0, unforced diff
  632 -> 626 rows. The +388 ternary and +848..+97c (input&1/&2 reads) did NOT flip ⟹
  OURS SPLITS THE TARGET MEGAWEB IN TWO: ig118 = {zero, input&4/8 chain}; a second r27-colored
  web owns {ternary, input&1/2 chain}. (The earlier two-web suspicion — name-arm vs fighter —
  was wrong in detail; the split is between the input&1/2 and input&4/8 read clusters.)
- ANSWER to STEP A: PARTIAL coverage — the binary question's answer is NO for the input&1/2
  chain, YES for input&4/8.
- The remaining C-question, precisely: what makes target's input&1/2 count-read cluster (and
  the is_name_mode ternary constant) chain into the SAME web as the zero/input&4-8 cluster,
  where ours separates them. Target evidence: +85c addi r25,r25,1 inside input&1/2 = a +1 temp
  (likely the `col4 + 1` of `count > (col4 + 1)`) sharing the web — i.e. target's bound-arithmetic
  temps chain THROUGH the count value where ours gives them fresh webs.
- ig118->r25 via slot move stays worth exactly +6 sites until the second cluster fuses.
- Probe was diagnostic (forced) — no commit. Open: +168 lhzu, +250 stb, top-rename extent
  classification, force-list cap #550.

## Iteration-22: stb/lhzu/cluster-2 investigation (95.2→95.4)

### Baseline verification
Confirmed: 13 commits on the stack (12 campaign commits + 1 master merge at #11), match
95.2% at session start. Line delta = 1 (the +168 lhzu). Only CAMPAIGN-STATE.md untracked.
Checkdiff confirmed: sole structural mnemonic difference is `lhzu` (target-only).

### TASK 3: stb/lwz position swap in B-button arm — COMMITTED (+0.2%)
Target emits `stb r0,17(r29)` (entering_menu=0) BEFORE `lwz rX,0(gobj)` (Diagram* load).
Ours had the store AFTER the load (inside the Diagram* block). Fix: moved
`mn_804A04F0.entering_menu = 0;` outside the `{Diagram *d = ...}` inner block to just before it
(C89 requires declarations first in a block; the outer placement preserves legality).
Result: 95.2→95.4%, hunks 43→42. Committed `0372241ee`.

### TASK 1: +168 lhzu — NOT VIABLE (do NOT retry)
The `lhzu` at +168 is `lhzu r3,2(r29)` — load hovered_selection with pre-increment of r29 from
&mn_804A04F0 to &mn_804A04F0.hovered_selection. In target r29 STAYS as the struct-base pointer
and advances by 2 once; in ours r29 is repurposed as the `ptr` (sorted+i walk) variable.
Any pointer-walk C spelling (e.g. `u16 *mf_sel = (u16*)&mn_804A04F0; ... *++mf_sel`) would:
- Reduce our instruction count 784→783 (the addi+lhz become lhzu, eliminating 1 instruction);
- Target has 785 instructions; this WIDENS the delta from 1→2 (WORSE);
- Additionally, C89/goto scope complications in the fc/fr arm (fc_test, fc_outer labels) block
  a clean declaration for the pointer variable.
Root cause: `addi r24,r29,2` exists because in our code r29 is clobbered by the ptr walk (ours
needs to compute `mn_804A04F0 + 2` from scratch). There is NO C source edit that produces lhzu
while also keeping instruction count ≥ 785. DEAD END — do not retry.

### TASK 2: cluster-2 fusion hunt — 3 attempts, all neutral (do NOT retry same approach)
Target has ONE r25 mega-web (15 sites) covering both cluster-1 {zero pair +3c/+44, input&4/8
count reads +a74/+a98/+b3c/+b60} and cluster-2 {ternary +388/+38c, input&1/2 reads
+848/+85c/+890/+8b4/+958/+97c}. Ours separates these as two r27-colored webs (force-phys
118:25 fixed cluster-1 in the diagnostic probe but left cluster-2 unfixed).

Three neutral attempts:
1. Ternary using count as operand: `data->is_name_mode = count ? 0 : 1` (reorder 0/1 arms to
   use the zero-web variable) — neutral, reverted.
2. Fighter count loop using count for ternary's zero: various spellings to share the zero value
   — neutral, reverted.
3. Direct zeros in for-loop to chain count's web — neutral, reverted.

Root cause: the fusion is an IRO-level optimization. Target's IRO reuses the `buttons.hi = 0`
zero (from the `u64` assignment in `Menu_GetAllInputs()` zero-extending a `u32` result) as the
shared zero for BOTH the count-web AND the ternary+input&1/2 cluster, creating one mega-web.
Our separate IRO @-temps (IRO-exit promotion pass creates distinct @1010-family temps for each
loop-carried zero) prevent this fusion. No C source re-spelling changes the @-temp structure.
The mechanism that forces them to share is UPSTREAM of the C-level declaration positions.

REMAINING STRUCTURAL DELTA SUMMARY:
- `+168 lhzu`: DEAD END (would worsen delta, see above)
- All other diffs: register allocation only (cluster-1 worth +6 sites via slot fix, cluster-2
  worth ~9 sites but requires interference-graph composition change not achievable from C)
- Order channel: exhausted (iter-14 hill-climb: max 28/45 webs with 17 regressions)

### Open items for iteration-23+
1. The second ig (cluster-2 web = {ternary, input&1/2 reads}) — what is its ig number? A
   force-phys probe with ig118:25 PLUS the cluster-2 web: (cluster2_ig):25 would confirm the
   slot-position delta (if it's merely color position, not extent — the merge is solid per
   iter-20 reconstructor reverification). If cluster-2's web is extent-fused in target vs split
   in ours for a DIFFERENT reason than the zero CSE, that's a new angle.
2. Reconstructor CFG fix (false-fallthrough audit) — iteration-17 item, still open.
3. Top-rename extent classification on the remaining 19 stuck webs (iter-14 residual): the true
   extent-delta webs in the fighter-nav +98c..+bf0 region (ig97/53/52/131/66) — cursors and
   found-family values held live longer in target than ours. Cached-local spellings in dn_f arm
   (iter-16 H2 finding: target keeps ptr live across dn_f walk, ours rematerializes from cur)
   still untested with the proper guarded C-spelling.

### Body gate for iteration-23+
opcode similarity ≥ 88.1 (current), line delta ≤ 1, hunks ≤ 42, match ≥ 95.4%.

## Iteration-23: composition CLOSED, order channel REOPENED, promotion gate decoded
Match unchanged 95.4 (95.36). No source commits (all probes/experiments reverted); the
iteration's product = three model corrections + a validated order oracle + the extent table.

### CORRECTION 1: iteration-21's two-web split was a FORCE-INTERACTION ARTIFACT
- Clean fingerprint force-phys 118:14 (r14 = unused low reg, no conflicts): ig118 =
  **ALL 16 sites** = {+3c/+44 zero pair, +254 entering_menu stb (JOINED via the iter-22
  hoist), +38c/+390 ternary, +84c mr (i=count init), +860 count++, all 8 count compares
  +894/+8b8/+95c/+980/+a74/+a98/+b3c/+b60}. Composition == target megaweb EXACTLY.
- Re-probe 118:25 reproduces the artifact: forcing to a naturally-contested register
  (r25 held by webs 121/123/127/129) BLOCKS part of the coalesce; the {zero,input&4/8}
  piece fell off the root. Iteration-21 saw the complement of my split (source state
  differed pre-stb-hoist). RULE: fingerprint with r14-r17 ONLY; never with pool registers.
- Unforced asm confirms: all 16 sites uniformly r27 in ours, r25 in target. The ENTIRE
  residual at these sites = ig118's color (pop position), not composition.

### CORRECTION 2: @-temp map redecoded (fresh /tmp/retro23 on current source)
- The promotion pass (between iro-57 EvaluateConditionals and iro-58 dump) is a
  WEB-SPLITTER for multi-web LOOP-CARRIED home variables: count (32 refs, 4 disjoint
  regions) splits into home (0xC00-name path, 6 refs) + **@1008 = nav-fighter count =
  ig118** (10 refs: init+incr+8 compares) + @1009 = nav-name count (9) + @1010 =
  0xC00-fighter count (7). The campaign's "@1010=count" was the WRONG region.
- Numbering: variables in FIRST-USE order (count first-used at decl-init line 990 =
  first promoted = lowest @s); webs WITHIN a variable in REVERSE node order (latest
  region gets lowest @). Iteration-9's "flowgraph order, earlier loops lower" is wrong.
- @1000-@1007 predate the promotion (CSE temps); promotion temps start at @1008.
  ig111+8 = 118 ✓ checks.
- GATE ANSWER (the TASK-2 question): the promotion fires on loop-CARRIED variables
  (count++, i++, col--, found--) with multiple webs. Loop OUTPUTS (col_result*/row_result*)
  are NEVER promoted — merging col_result2+col_result4 / row_result2+row_result4 was
  built+measured: B-pair sites UNCHANGED (still home webs), rt_f regressed to r25,
  95.29. REVERTED. B-pair-as-@-temps is unreachable.

### EXPERIMENT: count2 single-web home demotion (built, measured 95.04, REVERTED)
- Edit: dedicated `s32 count2` (declared last) for the nav-fighter arm + col_result2/
  row_result2 decls moved up. Result: **B-pair snapped to TARGET colors r27/r26 ✓✓**
  (pop-order mechanism works in vivo) BUT the megaweb fusion BROKE: home-count2 init
  emits fresh `li r27,0` at +84c instead of inheriting the live +3c zero; the
  {zero,entering_menu,ternary} piece split off to r24; compare second-operands cascaded.
- ⟹ the zero-CSE fusion lives ONLY in the @-temp path: the promotion-created value chain
  feeds the backend coalescer (virtuals 157/164 -> root 118). Home variables don't fuse.
  Target needs BOTH fusion AND late pop ⟹ target's count web = @-temp like ours; the
  difference is PURELY pop position within the high-pressure SELECT group.

### THE ORDER ORACLE (headline): forced SELECT order reproduces pi on the fused graph
- `--force-iter-first "58,161,166,163,38,37,41,39,118,32"` (current ig ids:
  58=data, 161/166/163=CSE identities, 38=B-col=col_result2, 37=B-row=row_result2,
  41=col_result4 dn_f, 39=row_result4 rt_f, 118=count megaweb, 32=gobj/proc):
  B-col r27 ✓, B-row r26 ✓, megaweb r25 ✓ incl. `mr r24,r25` init shape and ternary,
  results r26 ✓. Scored vs target with same-compiler baseline (dtk disasm + skeleton
  align): **unforced-debug 70.19% -> forced 74.14% (+31 net lines)**.
- Iteration-14's "order channel exhausted" verdict was measured on the PRE-FUSION graph
  (before iter-22's stb hoist changed composition). It does NOT hold on the current graph.
- Current pop order: 58,161,166,163,118,41,39,38,37,32 (SIMPLIFY trace, class 0,
  n_nodes=396). 118 pops 5th because it is pushed as a SPILL-CANDIDATE (flags 0xa +
  SPILLED in SIMPLIFY) — spill-candidate pushes pop first; among the group, descending
  ig orders the rest. Locals (33-56) can never outrank temp 118 by NUMBER.
- Pick model validated on all 6 pool decisions (reuse dispensed callee-saves ascending
  from lowest, else fresh descending): with order 38,37,41,39,118 the picks land
  r27,r26,r26,r26,r25 = exactly pi.

### Iteration-24 entry points (the C-question, sharpened)
The required order needs 118 pushed EARLIER (not spill-chosen) or 38/37 pushed LATER
(spill-chosen / degree >= k=29). Untested levers:
1. SPILL-COST of ig118: the heuristic chose it for the optimistic push. Its cost is a
   function of def/use count + loop depth. C-knobs that change its use count without
   changing the body: the ternary spelling (its 0-arm/1-arm constants are web members),
   the `i = count`-vs-`i = new_var` init spelling, the compare operand forms. Measure
   with dump (SIMPLIFY flags row for 118) per spelling.
2. Degree of B-pair (currently 18 vs k=29): +11 edges needed to make them spill-front.
   Liveness extension = body-gate risk; probably dead, but a dump-only probe is cheap.
3. The OTHER 0xa/SPILLED rows in SIMPLIFY (iters 13,22,32,41,58 of the listing,
   arraySize=2) — identify them; if any is a movable web, the spill-choice sequence
   might be reorderable from C.
4. Reminder: force-iter-first is DIAGNOSTIC-ONLY (debug DLL). Any lever must reproduce
   through the retail ninja build.

### TASK-3 extent table (web-level, reconstructor both sides, current baseline)
Method: tools/target_web_reconstructor.py build() on target_asm AND current_asm
(105 callee-save webs each side), paired greedily by extent overlap + size.
- 101 pairs; **48 register-mismatched; 40/48 = SAME-EXTENT (pure color cascade)** —
  these flip when the front order is fixed; do NOT chase individually.
- TRUE extent-deltas (7 + 3 unpaired), ALL in the nav walk arms — one family:
  1. dn_n walk web: ours r26 5-site 0x5d4-0x664 vs tgt r27 3-site 0x5ec-0x660 — ours
     materializes the walk value ~6 instr earlier w/ 2 extra sites. Same in rt_n:
     ours 5s 0x79c-0x82c vs tgt 3s 0x7b4-0x828. C-hypothesis: ours' pre-loop
     `i=cur; ptr=sorted+cur+0x1C` materialization vs original deriving later/inside.
  2. dn_f/rt_f same pattern smaller: ours r27 3s 0x9ac-0xa30 vs tgt r28 2s 0x9c4-0xa30;
     ours 3s 0xb8c-0xc10 vs tgt 2s 0xba8-0xc14 (iteration-16 H2 family).
  3. A-col nc-arm: ours r27 3s 0x94-0xe0 vs tgt r24 3s 0xa0-0xe0 — ours web starts at
     +94 (the extra `mr r23,r0` at +a0; target computes in r0 and moves once).
  Unpaired ours-only r25 webs (no target counterpart): 0x50c-0x520 (up_n), 0x6d4-0x6e8
  (lf_n), 0x20c-0x234 — ours-only materializations, same walk-arm family.
- Site histogram (236 mismatched operand-sites): r27->r24 x21, r27->r25 x16, r25->r24
  x16, r24->r23 x15, r28->r24 x13, r24->r27 x12, r25->r27 x12 — dominated by the
  cascade families above.

### Probe hygiene rules added this iteration
- Fingerprint webs ONLY with r14-r17 forces (unused regs); pool-register forces
  (118:25) perturb coalescing and produce false split readings.
- Cross-compiler match% comparisons are invalid: score forced debug-DLL objects against
  target using the SAME-compiler unforced object as baseline (dtk disasm + skeleton align;
  ninja-retail baseline reads ~5pp higher than debug baseline on this fn).

## Iteration-24: front-order rule derived; count2-home family root-caused (5 builds, all reverted)
Match unchanged 95.4 (95.36); tree clean at baseline. No gate-passing edit found this round.

### TASK 1 — the 0xa cohort + THE FRONT ORDER RULE (headline)
- 17 0xa rows in InputProc's SIMPLIFY. Every resolvable one (118, 470, 458, 446, 434,
  390, 376, 360, 348, 335, 310, 286, 273, 266, 255, 248) is a COALESCE ROOT (verified
  against the [COALESCE] map). **0x8 flag = coalesce root, NOT spill; the dump tool's
  "SPILLED" label is a mislabel. There are NO true spill pushes in this function.**
  The non-118 cohort members are degree-0/2 trivia popping at natural positions —
  the 0xa flag plays NO role in ordering.
- FRONT ORDER RULE (reverse-push reconstruction, validated against the trace):
  finishing-phase SIMPLIFY pushes run in repeated ASCENDING-INDEX sweeps over
  still-eligible nodes (eligibility: current degree < k=29); pops reverse. Front pops
  = [sweep-3: 58] [sweep-2: 161] [sweep-1 reversed: 166, 163, 118, 41, 39, 38, 37, 32].
- THE SENTENCE: ig118 pops 5th rather than 9th because sweep-1 pops in descending
  node index and 118 (an IRO @-temp, index >= 111) outranks every home local; to pop
  9th (between 37 and 32) its index must be 33-36, i.e. count's web must be a
  LAST-DECLARED HOME LOCAL — no @-temp can ever pop there, and degree/0xa/spill-cost
  play no role. This REFUTES iteration-23's "spill-candidate push" framing AND
  refutes the extent-fix->degree->order coupling premise (B-pair degree 18 vs k=29;
  extent edits of +-2 sites cannot bridge 11 edges).

### TASK 3 executed first (rule-directed): the count2-home family — MEASURED DEAD END
Goal: count2 = last-declared home local (order) + zero-web fusion (composition). Order
half SUCCEEDS in every variant; fusion half FAILS in every variant. 5 builds:
1. count2 decl-init `= 0` + B-pair decl move: 95.03. Front became 59,161,166,163,
   43,42,40,38,35(count2),32 — count2 POPPED 9th AND TOOK r25 at all 10 carry/compare
   sites (incl. all 8 compares + incr). ORDER FULLY SOLVED. But fusion broke: fresh
   `li r25,0` at +48; zero-temp (r23) kept {+3c li, +44 stw, +254 stb, +38c/+390
   ternary} AND ABSORBED i (loop +850-868, no mr) — i's absorption extends the
   zero web into the loop, blocking count2-color reuse and cascading i/col operands.
2. `count2 = (s32)(input64 >> 32)` via `u64 input64 = Menu_GetAllInputs()`: emits a
   `__shr2u` LIBRARY CALL (+4 lines, 93.53). MWCC does not fold u64>>32 here. DEAD.
3. `for (i = count2; ...)` (to force target's `mr r24,r25` i-init + break i-absorption):
   IRO copy-propagation rewrites it to `i = 0` (count2 provably 0) — IDENTICAL output.
   This is the precise mechanism behind iteration-9's "spelling-immune" verdict.
4. Init-order flip (input init moved to first statement; count2 decl-init executes
   first): scheduler hoists `li r25,0` to +1c (BEFORE the call); the inline's
   zero-extension at +40 STILL materializes its own zero with r25=0 live ⟹ the
   backend does NOT scan live registers for zero reuse.
5. (= state of 4 measured fully): 269 mismatched operand-sites vs baseline 236 —
   NET -33. Reverted.
- ROOT CAUSE (the precise gate): the baseline megaweb fusion is SAME-VALUE COALESCING
  of TEMP-CLASS virtuals (157/164 -> 118) requiring NON-INTERFERENCE. The @-temp's
  arm-init is (a) temp-class and (b) path-disjoint from the zero-temp -> merges. A
  home-count2 init is excluded: entry placement creates a +40..+4c simultaneous-live
  window with the zero-temp (interference), arm placement emits a fresh li that
  same-value coalescing refuses (home-class init virtual), and every copy-spelling
  is IRO-propagated/sunk away. No C spelling found after 4 distinct shapes; the
  home-order/temp-fusion requirements are MUTUALLY EXCLUSIVE through every door we
  have. Iteration-25+ should treat "count2-home + fusion" as closed unless a new
  mechanism (not init-spelling) appears.

### TASK 2 — nav-walk extent delta CHARACTERIZED (no build; the budget went to TASK 3)
dn_n ground truth (+5c8..+664 both sides): the extent delta is NOT the pre-loop
pointer math — it is the MERGE SHAPE of `found`:
- TARGET: both find-arms write a truncation TEMP (`clrlwi r0,r23` not-found /
  `clrlwi r0,r24` found), home materializes ONCE at the merge (`clrlwi r27,r0` at
  +5ec = web start), compare uses the truncated home directly (`cmpw r23,r27` — no
  cast at compare), store reuses it (`or r0,r0,r27`).
- OURS: arms write the home register directly (`mr r26,r23` / `clrlwi r26,r24` at
  +5d4/+5dc = web starts 6 instr earlier), truncation happens AT the compare
  (`clrlwi r0,r26; cmpw r23,r0`).
- C hypothesis for iteration-25: arms assign an UNCAST/u8-temp value, home assigned
  once after the merge (inline-helper return-value shape — the file's
  mnDiagram_GetVisible*From inlines have exactly this dataflow; m2c expanded them
  into home-writes per arm). Same family in rt_n (+7b4) and smaller in dn_f/rt_f
  (+9c4/+ba8). NOTE: per TASK 1's rule this fixes ~4-10 extent sites only; it canNOT
  move ig118's pop.

### Iteration-25 entry points
1. dn_n/rt_n temp-merge spelling (above) — extent-family fix, gated, per-arm evidence.
2. The order+fusion contradiction: the only untested door is making the TERNARY or
   entering_menu stores READ count2 (`= count2` instead of `= 0` — semantically equal
   with count2 init'd 0 at entry; m2c would print `= 0`) to extend count2's web into
   the B/0xC00 arms WITHOUT touching the zero-temp: count2 then interferes with
   B-pair (forces r25-style pick) AND the +254/+38c/+390 sites read count2's web
   (4-5 of the 5 zero-web sites fixed); the +3c/+44 pair stays unfused (1 li extra
   vs target). Risk: count2's longer range may join sweep-2/3 (pops before locals)
   — dump first, then build.
3. A-col +94 extra-mr (`mr r23,r0`): ours materializes the nc-walk base into a
   callee-save at +94 where target computes in r0 until +a0. Untested.

## Iteration-25: FIND-WALK INLINE FAMILY — 95.36 -> 97.08 (the campaign's biggest jump)

### TASK 1+2 — partner contest verdict: NOT a contest; family closed (6 doors total)
- Door 5 (explicit halves stores `*(u32*)&buttons = count2` + lo half): IRO
  constant-propagates count2 (provably 0) into the store; backend materializes its own
  r23 zero — identical to baseline. The C-visible read is erased before the backend.
- Door 6 (comma shield `= (0, count2)`): DOES survive propagation (stw r27 reads
  count2's reg!) but forces a STACK HOME for count2 (+stw r27,88(r1)) — 93.5. Dead.
- VERDICT: i won the door-1 absorption by CLASS-legality, not order: same-value zero
  merging is temp-class-only AND every C spelling that would connect count2-home to the
  zero is normalized away (constant-prop, sinking, hoisting, library-call shifts).
  count2-home order (r25, pop 9th) and zero fusion are mutually exclusive from source.
  FAMILY CLOSED — do not reopen without a fundamentally new mechanism.

### TASK 3 — THE WIN: find-walk inline helpers (m2c-reversal, 3 commits)
The nav arms' find loops are inlined helpers in the original; m2c expanded them into
per-arm home writes. Restoring the inline-call dataflow:
1. `2389c26b2` (95.36->96.60): mnDiagram_FindPrevName / mnDiagram_FindNextName
   (u8 return; `GetNameText(found & 0xFF)` arg — the file's existing call idiom at
   lines 266/285/436; `(u8) found` arg CSEs the arg truncation with the return
   truncation, which the target keeps separate — the & 0xFF spelling alone was worth
   +0.48). up_n/lf_n = FindPrev, dn_n/rt_n = FindNext. Casts at the post-find compare
   DROPPED (`if (cur != found)`) — the truncation lives in the helper returns now.
   Opcode similarity 88.1 -> 97.4.
2. `cb74cb7b1` (96.60->97.02): pointer-walk fighter variants FindPrevFighter /
   FindNextFighter(sorted, cur) with `mn_IsFighterUnlocked(*p) == 0` loops
   (new_var comparisons replaced by literal 0 — new_var is propagated anyway).
   up_f/lf_f/dn_f/rt_f. dn_f/rt_f keep `ptr = sorted + cur;` for their steps walks.
   Hunks 44 -> 21, opcode 98.3.
3. `31e4b2d0c` (97.02->97.08): FindNextFighter decl order (p before found) places the
   found=cur init at the target slot in dn_f/rt_f.
- Probed and REJECTED variants: Prev helpers returning s32 with `(u8)` only on the
  found arm (96.58, Delta3 — broke callers); `u8 cur` param (96.94). The +514/+8d8
  wrap-arm mr-vs-clrlwi (2 instr) stays open.

### State after iteration-25 (gates for iteration-26)
- Match 97.08, opcode similarity ~98.3, line delta 1 (ours 896 vs 895), hunks ~21.
- Gate: opcode >= 98.0 / line delta <= 1 / hunks <= 21 / match >= 97.08.
- Structural residual (~12 hunks): +a0 mr-vs-clrlwi (A-col nc-arm), +168 lhzu (known,
  do not retry), +448/+48c addi/mr pair (up_n region), +514/+8d8 prev-wrap
  mr-vs-clrlwi (helper-shape, 2 sites), 3 one-slot addi shifts of `found = cur` in
  the NAME next/prev arms (+5fc/+68c/+7c4 — FindNextName has no decl pair to swap;
  untested: an equivalent reorder inside the name helpers).
- Register residual ~218 operand sites: megaweb r27->r25 x16 + pool cascades
  (r24<->r25/r26/r27 families) — the closed order/fusion problem plus downstream.
- Iteration-26 candidates: (a) the 3 name-arm addi slots; (b) +a0 A-col shape;
  (c) steps-walk inlining (GetVisibleNameCursorFrom-form) — the dn_n/rt_n second
  loops are the existing inlines' bodies expanded; target uses index-form re-derivation
  at the tail per iteration-17, so ONLY attempt with per-arm asm evidence first;
  (d) re-run the order-channel surrogate on the NEW graph (the inline rewrite changed
  web composition everywhere — the iteration-14/19 exhaustion verdicts are stale again).

## Iteration-26: re-baseline on the new graph + prev-merge casts (97.08 -> 97.75)

### TASK 1 — new-graph census
- Structural hunks: the 12 survived the recount exactly, then build-1 closed 4 net
  (now 8): {+a0 A-col mr-vs-clrlwi, +168 lhzu (closed), +448/+48c addi/mr pair (up_n
  region), +68c addi pair (lf_n), +6dc/+6e0 + +abc/+ac0 lf_n/lf_f wrap mr-vs-clrlwi}.
- Megaweb: ig118 -> **ig106** post-inline (fewer @-temps before it), SAME 15-site
  composition (r14-verified: zero pair, +254, ternary, count++, 8 compares), same
  front {58,175,180,177,106,41,39,38,37,32}, same picks (106->r27, want r25).
- Register residual 208 operand sites; top families unchanged (r24->r25 x18,
  r25->r26 x17, r27->r25 x16, r28->r24 x13 ...).

### TASK 2 — order-solve verdict on the new graph
force-iter-first "58,175,180,177,38,37,41,39,106,32": unforced-debug 73.50 ->
forced 77.45 = **+31 net lines, identical to the old graph**. The front order is
worth the same; the other ~177 lines are NOT front-order-reachable (main-phase pool
+ extents). The C-lever for the front order remains the CLOSED count2-home family.
Full-permutation surrogate not re-run (scripts not rebuilt; front result sufficed).

### TASK 3 — prev-merge casts + ptr split (committed a2bf29b41, 97.08 -> 97.75)
- Iteration-25's s32-return failure was a MISSING CALLER CAST: the correct target
  dataflow is helper returns s32 {wrap: `return cur;` RAW -> mr; hit: `return (u8)
  found;` -> clrlwi} + caller merge `found = (u8) FindPrev...(...)` -> clrlwi.
  Closed +514/+8d8. The lf arms (srawi-cur) flip the other way (target truncates
  their wrap; `return (u8) cur` re-truncates the up arms and nets WORSE 97.72) —
  2 one-instr wrap hunks accepted.
- dn_n/rt_n steps-walk `ptr = sorted + cur; ptr = ptr + 0x1C;` two-statement split
  (nc-arm precedent) fixed the 3 addi association/slot shifts.
- +a0 A-col: re-read-field lever tried (`ptr = sorted + ((u8) data->name_cursor_pos)`)
  -> 97.57 WORSE, reverted. Site stays open: ours clrlwi r0 + mr-to-home vs target
  clrlwi-into-home; the home-vs-temp truncation landing again.

### State / gates for iteration-27
- Match **97.75**, opcode 99.0, line delta 1 (896 vs 895), hunks 23 (8 true).
- Gate: opcode >= 99.0 / delta <= 1 / hunks <= 23 / match >= 97.75.
- Iteration-27 candidates: (a) THE 0x10-ARM INLINING — nc/nr/fc/fr m2c soups are
  the existing mnDiagram_GetVisible*From inline bodies expanded (nc = 
  GetVisibleNameCursorFrom(sorted, i, col)-shaped; loop rotation differs: inline
  while(remaining>0) top-test vs m2c nc_test goto; the +a0/+448/+48c/+168-lhzu
  hunks ALL live in this arm — the inline may close them the way the find-walks
  did, INCLUDING possibly the lhzu via the inline's own pointer dataflow);
  (b) lf-wrap 2 hunks (need a spelling that truncates lf wraps without re-truncating
  up wraps — none found in 2 tries); (c) the register residual behind the closed
  order family.

## Iteration-27: 0x10-arm inline restoration — nc/nr recipe PROVEN, fc/fr REFUTED, net sub-gate (reverted)
Match unchanged 97.75 (all 5 builds < gate; best 97.16). The structural findings are
large; iteration-28 should re-apply the nc/nr recipe and attack the fc cascade.

### PROVEN: the nc/nr arms ARE mnDiagram_GetVisibleNameFrom calls (exact recipe)
Variant selection by TAIL FORM: GetVisibleNameFrom tail = `p = sorted; p += idx;
return p[0x1C];` = the soup's `sorted[i + 0x1C]` index re-derivation ✓ (CursorFrom's
`return *p` pointer tail is the WRONG variant here). The recipe that reaches
frame-match + closes +90/+a0/+a4:
```c
      col = mn_804A04F0.hovered_selection;                  // RAW local (not (u8))
      col_result = mnDiagram_GetVisibleNameFrom(
          sorted, (u8) data->name_cursor_pos, (u8) col);    // casts ON THE ARGS
      row = mn_804A04F0.hovered_selection >> 8;
      row_result = mnDiagram_GetVisibleNameFrom(
          sorted, data->name_cursor_pos >> 8, row);
```
with PAD_STACK(64) (fc/fr still soup). Mechanics learned:
- (u8) on the RANK arg = the target's +a0 clrlwi (m2c dropped this cast; the soup's
  raw `col` was wrong) — closes +a0.
- Pre-made `i` local forces an extra copy into the inline's idx (+a4 mr) — pass the
  EXPRESSION; the truncation lands directly in the walk register (closes +a4).
- `(u8) col` glued onto the LOCAL's load enables an unwanted lhzu fusion at +90 (see
  below); RAW local + cast-at-arg restores target's load-then-truncate (closes +90).
- PAD_STACK is configuration-dependent: 72 (all-soup baseline) / 64 (nc+nr inlined) /
  56 (nc+nr+fc+fr inlined) — each form hits stwu -128 = target frame exactly.
- Residual in this form: nr arg-load order one-add scheduling shift (+f0 block,
  hovered-vs-name order; row-local DOES order it but one add interleaves), fc-arm
  cascade (+178/+17c extra addi+mr — the fc soup re-shapes when nc/nr inline), pool
  renames -> fuzzy 97.16 < gate.

### THE LHZU IS REACHABLE (dead-end verdict dissolved, as predicted)
With `(u8) col` glued to the local load, OURS emitted `lhzu` at +90 (nc arm) — the
update-form fusion fires when the mn base r29 is dead on the path and the truncation
chains. Target's lhzu is at +168 (fc arm) instead. The fusion is compiler-reachable
from plain field reads; getting it at the RIGHT site = make the fc arm's first
hovered read the fusing one (the fc arm is reached when r29's base has no later use
on that path). Iteration-28: after re-applying nc/nr, check whether the fc soup's
hovered read (`col = (u8) hovered` at the fc head) emits lhzu once the nc arm no
longer competes (in cur27e it stayed addi+lhz with 2 extra instrs — the cascade
suggests the fc arm's shape is sensitive to the nc/nr registers).

### REFUTED: fc/fr are NOT GetVisibleFighterFrom calls
Both local-form and expression-form builds produce a 7-instruction-SHORTER shape
(888 vs 895; while-top-test rotation) than target's fc/fr windows, which have the
SOUP's per-iteration zero-check (`+17c cmpwi / +180 bne / +184 lbzx` rank-0 path
visible per iteration). The original fc/fr = the soup shape (or an unknown variant
whose rotation matches it) — KEEP THE SOUP. checkdiff's opcode_similarity metric
collapses (0.17-0.18) on these big block moves; use the skeleton aligner for truth.

### Open (unchanged): lf-wrap pair (+6dc/+abc), +448/+48c, +68c, nr one-add shift.
### Iteration-28 entry: re-apply the nc/nr recipe (97.16 floor), then hunt the fc
cascade (+178/+17c) and the nr add-shift to clear the gate; the lhzu site-flip last.

## Iteration-28: recipe re-applied + cascade DIAGNOSED — banked (blocker named, no commit)
All gates respected; recipe nets 97.16 < 97.75 in every configuration. 4 probes used.

### Cascade diagnosis (the headline)
Region-bucketed rename sites, committed-baseline vs recipe (skeleton aligner):
  nc/nr 37 -> 16 (-21 ✓ the recipe WORKS in its region), fc/fr 48 = 48,
  0x20/0xC0 15 = 15, nav-name 41 -> 60 (+19 ✗), nav-fighter 67 -> 90 (+23 ✗).
  Total 208 -> 229.
**BLOCKER: the nc/nr inline expansion changes the IRO @-temp COUNT upstream of the
nav arms; every downstream @-temp renumbers, re-rolling the nav-pool coloring that
the campaign tuned across iterations 1-19. The fix and the damage are coupled through
the temp numbering.** ⟹ The recipe can only land together with a nav re-tune on the
post-recipe numbering (iteration-29 program: apply recipe, re-run the nav-arm lever
hunt — decl-order, force-iter oracle, rename census — ON THAT GRAPH).

### Probes measured this round (all reverted)
1. Recipe re-applied exactly: 97.16 reproduced (frame -128 ✓, +90/+a0/+a4 closed ✓).
2. Explicit `u16* hov = &mn_804A04F0.hovered_selection` in fc/fr (lhzu hunt): IRO
   propagates the pointer away — BYTE-IDENTICAL output. The lhzu needs the allocator
   to place &hovered IN r29 (base dies at the load, the update feeds fr's read);
   pointer-form C is normalized before the backend ever chooses. Same wall class as
   count2-fusion doors. The fc-head +178/+17c copies and the lhzu remain
   allocation-coupled (the r29-kill timing): NOT C-visible this round.
3. Inline-local decl reorder (idx/remaining swap in GetVisibleNameFrom): ZERO effect —
   inline locals are IRO-renamed; their decl order does not survive to numbering.
4. fc-head accounting (exact): ours +3 lines = {+178 addi, +17c mr (truncation-to-home
   copies; absent in the all-soup baseline = pressure artifact), +168 addi+lhz vs
   lhzu (-1)}. Target's lhzu updates r29 INTO &hovered and fr's `row2 = hovered>>8`
   reads 0(r29) — the original shared the pointer across fc/fr in the base register.

### New front (recipe graph): 57,179,184,181,100(megaweb),41,39,38,37,32 — same
shape, megaweb=ig100, same picks; order family unchanged (the +31 stays banked).

## Iteration-29: RECIPE COMMITTED (orchestrator override) — new baseline 97.16
### TASK 0 — committed bcc84d573
Override rationale (recorded per orchestrator): the target compiled the original
source which HAD the nc/nr inlines; the post-recipe graph is the correct substrate
and the old baseline's nav coloring was luck on the wrong graph. Meter at commit:
97.16, opcode 98.5, line delta 3 (898 vs 895), frame -128 EXACT, 11 true hunks
(nc-head +90/+a0/+a4 closed). NEW GATES: neutral-or-better vs 97.16.

### TASK 1 — the map on the correct graph
(a) Nav web census (reconstructor, both sides): 46 reg-mismatched callee-save pairs,
    29 in the nav region. THE PATTERN: top-8 nav webs (the find/steps walk cur/found
    values in up_n/dn_n/lf_n/rt_n/up_f/dn_f/lf_f/rt_f, 4-8 sites each) are ALL
    ours-rXX -> **target r23**. Same-extent renames (offset skew aside).
(b) THE CHAIN: target B-col (col_result2) = r27 lives across the fc walk -> blocks
    r27 at fc-i's pop -> fc-i goes FRESH r23 -> all nav walk webs reuse r23
    (ascending). Ours: B-col=r26 leaves r27 free -> fc-i=r27 -> nav pool shifts up.
    The nav-r23 family CHAINS to the front-order family (B-col r27-vs-r26).
    BUT the forced front order alone does NOT fire the full chain: probe
    force-iter-first "57,179,184,181,38,37,41,39,100,32" = 71.59 -> 75.67 (+32,
    same as old graph); in the forced object fc-i took r25 and col r23 (the
    main-phase pops have their own order needs). Full chain needs the main-phase
    order too -> full-order surrogate on this graph = iteration-30 item.
    The front C-lever remains the CLOSED count2-home wall.
(c) +448/+494 (0xC00-fighter UpdateScrollArrowVisibility arg): target's &hovered CSE
    temp picked r5 (freeing r4 for an EARLY arg copy at +448); ours picked r4 (arg
    copy sinks to the call at +494). Volatile-pick artifact; no C lever found.
    lf-wraps (+6dc/+abc) and nr one-add shift (+f0) unchanged, no differentiator.

### Iteration-30 program
1. Full-order surrogate (hill-climb incl. main phase) on the recipe graph — the
   nav-r23 chain says the prize is ~50 sites if an order exists; check force-iter
   with an EXTENDED vector (front + the fc/fr/nav @-temp pops).
2. The fc-head +178/+17c copies + lhzu (allocation-coupled, r29-kill timing).
3. lf-wraps, nr add-shift, +448 r4/r5 — all characterized, no lever yet.

## Iteration-30: count2-home CRACKED on the correct graph — 97.16 -> 97.28 committed
### TASK 3 (executed first; the decisive result)
Door-1 re-test (count2 = 0 decl-init last + B-pair decls up + nav-fighter count2)
on the post-recipe graph: **match 97.28, rename sites 229 -> 171 (-58), +2 structural
lines (the known fusion cost: fresh `li r25,0` at +48 — the wall MECHANISM held,
the COST-BENEFIT inverted on the correct substrate).** Committed 06ba6b9 ("count2
home demotion + B-pair decl order"). Spot reads confirm the chain fired: count2
compares r25 ✓, fc-i = r23 ✓ (the nav-r23 cascade root), fc result lbzx r27.
LESSON RECORDED: walls proven on one graph are cost-benefit verdicts, not
mechanism-impossibility verdicts — re-test after substrate changes.

### TASK 1 — solve status (honest gap)
Full extended-vector surrogate NOT built this round (the ~30 main-phase pool igs
need per-web fingerprinting or the iteration-7 tiebreak module rebuilt; budget).
Substitute evidence: the chain analysis + door-1's -58 empirically bound the order
channel's value on this graph. Remaining after door-1: 171 rename sites + 13
structural hunks. The forced-front probe (+32 same-compiler) and #550 caution stand.

### TASK 2 — the knob map (for iteration-31)
@-temp numbering knobs (main-phase pop order = descending @-index):
1. Variable FIRST-USE order (promotion processes variables in first-use order) —
   moving a first use moves ALL that variable's webs' numbers.
2. Web multiplicity (single-web home vs promoted @-temps) — the count2 lever class.
3. Upstream temp-count changes (inlining/un-inlining shifts every downstream number
   — the recipe demonstrated this).
4. Home decl order (locals reverse-decl) — front + finishing-sweep positions.
Executed this round: knob 2+4 (door-1). Candidates next: the fc-arm group already
has the natural i-last ordering; the &hovered temp eating r24 (lhzu root) is the
remaining fc-head divergence — knob for it unknown (volatile/peephole-coupled).

### State: baseline 97.28, opcode 98.4, delta 3, hunks 13, 171 rename sites.
Next: re-census the 171 (families changed after door-1), lf-wraps, nr add-shift,
fc-head lhzu/copies, full-order surrogate if infrastructure gets rebuilt.

## Iteration-31: census re-prioritized to the zero-web/r23 chain; unfuse lever refuted
Baseline 97.28 held (no source commits; one clang-format pass committed 8e...-family).

### STANDING RULE (orchestrator): substrate relativity — after each committed graph
change, previously-proven walls get one cheap re-test before being believed.

### TASK 1 census (post-count2 graph, web-level): 42 mismatched pairs
- count2's web = r25 CORRECT at its 10 sites; the megaweb residue = the UNFUSED
  pieces: ours' zero web {+3c li, +44 stw, +25x, +390 ternary} + absorbed i = 8-site
  r23 web 0x3c-0x870 (vs target: zero in the r25 megaweb, i its own r24 3-site web).
- THE FRESH-LI DEBT IS REALLY r23 OCCUPANCY: the four big nav walk webs (dn_n/rt_n
  8+8, dn_f/rt_f 7+7 = 30 sites) all want r23 (target) and ours has them on
  r26/r27. Also visible: ours SPLITS the mn-base web (entry r29 web ends ~+750;
  nav arms re-materialize via lis/addi at +880 — target keeps ONE r29 base web
  to +b6c, 15-16 sites). The base split is ANOTHER family (~5+ sites).
- &hovered temp root (iteration-30) folded into this: same fc-head region, still open.

### TASK 2 levers measured (2 builds, both non-viable)
1. `i = count2` (substrate re-test of the propagation door): byte-identical AGAIN —
   IRO constant-prop wall holds on this graph too. Re-proven, recorded.
2. Dedicated home `s32 i2` for the count loop (home-class = same-value-merge exempt):
   the unfuse FIRED (i2 got its own fresh `li r23,0` at +858; the zero web shrank)
   but i2's home took r23 anyway and the nav walk webs did NOT move (97.07, +1 line,
   reverted). ⟹ The nav-r23 displacement is NOT explained by zero-web occupancy
   alone — my reconstructor-level interference model mispredicts the real blocker.
   NEXT INSTRUMENT (iteration-32): r14-fingerprint the dn_n cur-web ig and read its
   ACTUAL blocked-set from the COLORGRAPH interferer list at its pop (the dump has
   it), instead of reconstructor inference.

### FRESH-LI DEBT (explicit, per orchestrator): target lacks ours' +48 li r25
(count2 init) and ours lacks the megaweb fusion of {zero, ternary, entering_menu}
into count2 — 2-line + 5-site standing debt. The fusion/zero-partner contest gets a
re-test after EVERY future committed graph change (substrate rule).

### INFRASTRUCTURE GAP (standing): the extended-vector order solve needs the
iteration-7 tiebreak module rebuilt (host-side surrogate over the full pop order)
or ~30 per-web fingerprints. Until then, order-channel ceiling estimates come from
forced-front probes (+32 same-compiler) and chain analyses only.

### State: 97.28, opcode 98.4, delta 3, hunks 13ish, ~171 rename sites.
Iteration-32: (1) the dn_n blocked-set read -> the real nav-r23 blocker; (2) the
base-web split family (nav lis/addi re-materializations — possibly a source-shape
lever: the nav arms' mn_804A04F0 accesses vs the entry base); (3) &hovered/lhzu;
(4) lf-wraps/nr-shift on evidence only.

## Iteration-32: blocked-set reads + mn-base reconciliation (no source commits)
Baseline verified: commit 179cedfc7, match 97.28%, opcode 98.4, delta 3. Clean tree.

### TASK 1 — nav-r23 blocked-set table (the headline)
Fingerprinted the 4 nav walk cur-webs (r14 probes; all confirmed by site asm):
- ig73 = dn_n cur-web (srawi +794..+814, 8 sites), gets r26 at iter 353
- ig71 = rt_n cur-web (clrlwi +5cc..+64c, 8 sites), gets r26 at iter 355
- ig77 = dn_f cur-web (srawi +b78..+bd4, 7 sites), gets r27 at iter 349
- ig75 = rt_f cur-web (clrlwi +994..+9f0, 7 sites), gets r27 at iter 351

Blocked-set at each cur-web pop (from COLORGRAPH interferer lists):
| web  | iter | pick | r23 blocked by | r24 blocked by   | r25 blocked by |
|------|------|------|----------------|------------------|----------------|
| ig73 | 353  | r26  | ig85 (r23)     | ig116,ig158 (r24)| ig80 (r25)     |
| ig71 | 355  | r26  | ig84 (r23)     | ig124,ig162 (r24)| ig79 (r25)     |
| ig77 | 349  | r27  | ig87 (r23)     | ig82,ig147 (r24) | ig70,ig146(r25)|
| ig75 | 351  | r27  | ig86 (r23)     | ig81,ig153 (r24) | ig68,ig152(r25)|

(r26 blocked by ig38=B-col for dn_f; r27 blocked by same-arm cur-web for each ptr-web)

THE BLOCKERS IDENTIFIED (fingerprinted):
- ig87 = dn_f ptr-web (add/addi +b7c..+bdc, pops iter 339, picks r23) [ROOT]
- ig86 = rt_f ptr-web (add/addi +998..+9f8, pops iter 340, picks r23) [ROOT]
- ig85 = rt_n ptr-web (add/addi +7d0..+7ec, pops iter 341, picks r23)
- ig84 = dn_n ptr-web (add/addi +608..+624, pops iter 342, picks r23)

These are the FindNext/FindPrev helper's `p` pointer inlined into the nav arms.
They pop BEFORE the cur-webs (higher ig_idx = @-temp promoted by IRO) and pick
r23 because r24 is blocked by ig81/82/83/83 (step-ptr second-phase webs, r24),
r25/r26/r27 are blocked by other live webs at that moment.

Cross-arm interference: dn_n ptr (ig84) has r26 blocked by rt_n cur (ig71) and
vice-versa — cross-arm simultaneous live ranges from IRO @-temp layout.

THE CHAIN CONFIRMED: ptr-webs block cur-webs from r23. For cur-webs to pick r23,
ptr-webs must pick something other than r23. For ptr-webs to avoid r23:
Option A: r24 must be free → step-ptr webs (ig81/82/83) must not hold r24 at
          that moment (shorter step-ptr extents, or different coloring)
Option B: r26 must be free → B-col (ig38) at r27 (target value) → ptr-web picks
          r26 → cur-web picks r23.

OPTION B is the cascade root: B-col (ig38) → r27 is the single upstream lever
that propagates through all 30 cur-web sites. FORCE PROOF: forcing ig38:27
fires the nav-r23 cascade (nav region r23 sites jump from ~8 to 33 in debug DLL).
However, this is the SAME closed front-order family (B-col requires count2
r25 pop position 9th; count2-home and zero-fusion are mutually exclusive from C
as established in iterations 24-25).

OPTION A: untested. The step-ptr webs (ig81/82/83 = the p++/p-- continuing after
  find-helper return, 3-4 sites each in the steps-walk sub-phase) pick r24. If
  their extents were shorter (ending before ptr-web pop), r24 would be free for
  ptr-web → ptr picks r24 → cur picks r23. The C-lever: does the steps sub-phase
  need to reuse the find-phase `p` pointer, or could a fresh variable for the
  steps walk break the ig81/82/83 interference with ig84/85/86/87? This is the
  NEW UNTESTED LEVER for iteration-33.

dn_n cur-web r14 cross-check: force ig73:14 confirms exactly 8 sites at
+794/+798/+7a8/+7c8/+7d0/+7e0/+7e4/+814 — site attribution verified.

### TASK 2 — mn-base single-web family RECONCILED (dead end)
Target r29 web: 16 sites, +034..+740 (ends at +740, CONFIRMED from target asm).
Ours r29 web (ig184): 16 sites, +034..+750 (ends at +750, same-structure).
BOTH builds re-materialize the mn_804A04F0 base via lis r3 for nav arm accesses
(+874/+93c/+a58/+b1c in target; +880/+944/+a64/+b28 in ours — positional shift
from the 3-line delta). There is NO web-identity divergence for the mn-base.

ITERATION-31 CLAIM RETRACTED: "target keeps ONE r29 base web to +b6c, 15-16
sites" was a reconstructor artifact / incorrect reading. Target's r29 ends at
+740 same as ours. The lhzu story is consistent: lhzu at +168 advances r29 into
the &hovered region in target (r29 = &mn_804A04F0 + 2 after +168), but target
also re-materializes for nav arms. This is the known dead end from iteration-22
(lhzu path widens delta 1→2, WORSE). The mn-base single-web family is CLOSED.

Note: ours clobbers r29 with the lf_n ptr walk at +180 (mr r29,r0), while
target keeps r29 as the shifted base (+1c8 reads 0(r29) = hovered via lhzu).
This is a DIFFERENT variable occupying r29, not the mn-base web extending.

### TASK 3 — micro-sites (lf-wraps, nr add-shift)
No builds performed per TASK 3 rule (no new evidence). Status unchanged:
- lf-wraps (+6dc/+abc): 2 hunks, iteration-26 open, no differentiator found
- nr add-shift (+f0): 1 hunk, characterized iteration-27, no C lever found
- +448/+494 &hovered CSE temp (r4/r5): volatile-pick artifact, no lever

### TASK 4 — CAMPAIGN-STATE census/blockers update (this section)
Standing items unchanged:
- FRESH-LI DEBT: +48 li r25,0 (count2 init) + missing megaweb fusion (5 sites).
  Substrate-rule re-test deferred to next committed graph change.
- INFRASTRUCTURE GAP: extended-vector order solve needs tiebreak module rebuild.
- Issue #550: force-iter-first silent drop for long vectors (OPEN).

### State: 97.28, opcode 98.4, delta 3, hunks 18 (13 register-only), 171 rename sites.
### NEW UNTESTED LEVER (iteration-33 candidate):
Step-ptr decoupling: in FindNext/FindPrevFighter, the steps sub-phase (p++
continuing walk after the find loop) currently extends the find-phase `p` pointer
live range (creating ig81/82/83 which hold r24, blocking ig84/85/86/87 ptr-webs
from r24, forcing ptr-webs to r23, blocking cur-webs from r23). If the steps walk
uses a FRESH pointer variable instead of reusing `p`, ig81/82/83 would be separate
from ig84/85/86/87, potentially freeing r24 at ptr-web pop time → Option A fires.
REQUIRES: evidence that target's steps-walk pointer is a separate variable (check
target asm for r24 in the steps-walk region vs the find-walk region).
### Source file: /Users/mike/code/melee/.claude/worktrees/mndiagram-802427B4-investigation/src/melee/mn/mndiagram.c

## Iteration-33: cur→i merge lands the name arms — 97.28 → 97.30; p2-split REFUTED
Baseline verified at ef6051d9b (97.28/98.4/Δ3/18). 3 gated builds, 3 commits.

### TASK 1 — target-side verdict: ONE WEB (Option A's p2-split refuted)
Decoded TARGET dn_f (+b68..+bf8) and rt_f (+984..+a14) instruction-by-instruction:
- ONE ptr derivation per arm (`add r27,r30,r23` at +b70/+98c), find-walk p =
  COPY (`addi r25,r27,0` +b78/+994), steps ptr2 = COPY (`mr r25,r27` +bc0/+9dc),
  anchor++ in the steps loop (+bd0/+9ec). Ours has the IDENTICAL shape
  (one add, two copies, anchor++). There is nothing to decouple — the original
  shares the pointer exactly as ours does. Do NOT build a p2 split.
- The whole fighter-arm difference is a color permutation: target cur=r23/
  anchor=r27/found=r24/find-p=r25/ptr2=r25(reuse)/steps=r24(reuse)/merged=r28;
  ours cur=r27/anchor=r23/found=r24/find-p=r25/ptr2=r24/steps=r28/merged=r25.

### THE NUMBERING MODEL CORRECTED (supersedes iteration-23/30 directions)
Empirical, fingerprint-verified on both pre/post-merge graphs:
- Webs number in VARIABLE bands ordered by FIRST-USE: EARLIER first-use →
  HIGHER ig band → pops EARLIER (descending-ig pops).
- Within a variable: DESCENDING REGION order (latest region = highest ig in
  the band = pops first). [Iteration-32's within-variable reading was wrong.]
- Old graph bands: i-standalone 88/89 > ptr 83-87 > ptr2 78-82 > cur 71-77
  (first-uses 1090 < 1092 < 1101 < 1253 ✓ rule holds).

### TASK 2 — the executed lever: merge nav `cur` into the shared walk index `i`
Target evidence: ALL TEN walker webs in target sit on r23 (+16c/+1d4 soup,
+504/+5bc/+6cc/+784 name navs, +8c0/+988/+aa4/+b6c fighter navs) ⟹ the
original used ONE index variable for every walk. m2c split it (i for soup/
count/0xC00/name-steps, cur for nav arms; `i = cur` copies in dn_n/rt_n).
- BUILD 1 (cur→i everywhere, delete i=i copies, drop s32 cur decl): COMMITTED
  0076b1dba, 97.28→97.30. Retail: dn_n/rt_n cur-webs r26→r23 ✓✓ TARGET COLOR
  (16 sites), up_n +514 truncation pair fixed, name anchors moved r23→r25
  (target r26 — still off), name p2 r25→r26 (REGRESSION, was coincidentally
  right). Aligned census: 120→115 register-mismatched sites (-5 net).
  Fighter arms unmoved in retail.
- BUILD 2 (steps2/3/4 → steps): BYTE-IDENTICAL, committed 6436f7ea5 (simpler
  source; iteration-12's split is codegen-neutral both ways on this graph).
- BUILD 3 (fighter count loop `i = count2`): BYTE-IDENTICAL, committed
  cf2762034 — the substrate re-test of the propagation door (TASK 3 item):
  IRO const-prop wall holds on the merged-i graph. Target's megaweb +84c
  `mr r24,r25` shows the original spelling; kept since codegen unchanged.

### THE MECHANISM, now exact (new-graph fingerprints: igs 90/88/87/85/84/82/80/79)
New i-band (descending region): dn_f-i=90(r27), lf_f-i=89(r26), rt_f-i=88(r27),
up_f-i=87(r26), count-i+ZERO=86(r23 FRESH dispense), dn_n-i=85(r23✓),
lf_n-i=84(r23), rt_n-i=83(r23), up_n-i=82(r23), fc-soup-i=81(r23),
fr-soup-i=80(r23); anchors below: dn_f=79(r23 steal), rt_f=78(r23 steal),
name anchors=77/76(r25), then ptr2s.
- THE DISPENSE POINT IS REGION-LOCKED: the zero web rides the fighter-count-
  loop i web (region +848), which sits BETWEEN the name arms (+4c0-814) and
  fighter arms (+8c0-c10) in the band. Name i-webs pop after it → r23 ✓.
  Fighter i-webs pop before it → r26/r27; their anchors pop after → steal r23.
- IN TARGET the zero is FUSED into the front megaweb (no mid-band dispense)
  and the fighter walkers still get r23 ⟹ the FIGHTER-ARM RESIDUAL IS
  FUSION-COUPLED — same closed count2-fusion wall (fresh-li debt). Splitting
  the count loop out (i2-home) re-tested iteration-31: gate-fail (+1 line) and
  would also strip the name arms' r23 source. No independent fighter lever
  found through the numbering channel.

### Iteration-32 corrections (recorded)
- The blocked-set table printed FINAL colors, not at-pop state (a blocker
  only blocks if it popped earlier). Conclusion (same-arm pointer steals r23)
  survived; per-register "blocked-by" attributions partially wrong.
- ig84/ig85 labels were arm-swapped (84=rt_n region +608, 85=dn_n region +7d0).
- ig84-87 were not "the find-helper's p": name helpers have no pointer — the
  name-arm members were the caller's steps anchors.
- The TRUE pick mechanism for the r23 avalanche: ascending-reuse hands r23 to
  EVERY pop after the zero web's fresh-r23 dispense unless blocked same-arm.

### State after iteration-33: match 97.30, opcode 98.4, delta 3, hunks 18,
115 register-mismatched aligned sites. Commits: 0076b1dba, 6436f7ea5, cf2762034.
### Iteration-34 entry points
1. Name-arm anchor/p2 swap (anchors r25 vs target r26; p2 r26 vs target r25):
   a within-band order question (anchor pops before p2; target implies the
   reverse or different blocking). Cheap: read at-pop blocked sets for igs
   77/76 (name anchors) and the name-p2 igs on the new dump; check whether a
   found/result-web color change upstream reorders the leftovers.
2. Fighter arms: fusion-coupled (closed wall) — only reopen with a new
   fusion mechanism. The +0.02-equivalent prize there is ~30 sites.
3. Micro-sites unchanged (lf-wraps +6dc/+abc, nr add-shift +f0, +448 r4/r5).
4. Standing: #550 (no long vectors used this round; ≤4-entry forces verified
   via r14-r17 site appearance), tiebreak-module rebuild gap.

## Iteration-34: role swap + rider door — 97.30 → 97.55; fighter arms UNWALLED
Baseline verified at aeef7cf22. 4 builds: 2 committed, 2 reverted-with-mechanism.

### TASK 1 — name-arm anchor/p2 swap: SOLVED (97.30 → 97.43, census 115→103)
Blocked-set reads (at-pop accounting): ig77 (dn_n anchor, pop 349) took r25
with {r23=ig85(same-arm i), r24=ig114, r30, r31} blocked; ig72 (dn_n p2, pop
354) took r26 with r25 additionally blocked BY THE ANCHOR. Target has the
reverse (anchor r26, p2 r25) ⟹ target's walker pops first ⟹ walker belongs to
the EARLIER-first-use variable. Edit: swap ptr/ptr2 roles in dn_n/rt_n steps
walks (walker=ptr, anchor=ptr2; pure rename). COMMITTED 60d5ad582-family
(see log). dn_n/rt_n anchor+walker+load now ALL on target registers.

### TASK 2 — fusion wall re-exam: RIDER DOOR FOUND AND COMMITTED (97.43→97.55)
(a) TARGET megaweb = count2's HOME band web (front pop, r25): the original's
count2 home-init IS the +3c zero value (the u64-hi-half materialization of the
buttons assignment), so home+zeros = one front web; the count-loop inits read
it (mr r24,r25 = i = count2 SURVIVING — not const-propped because the value
chain runs through the buttons store, not a literal).
(b) NEW DOOR CLASS under the corrected model — move the RIDER (the zero-
coalesce root = lowest-numbered member = the fighter count-loop walker web):
- D-NEW-1: walk the fighter count loop with `count` (first-use 1050, band
  ABOVE i's; count is dead on the fighter path — semantically free). The
  dispense root moves into count's band, popping BEFORE the entire i-band:
  fighter i-webs then take r23 and their anchors stop stealing. COMMITTED:
  dn_f/rt_f cur=r23 ✓, anchor=r27 ✓, found=r24 ✓, find-p=r25 ✓, result=r26 ✓
  all TARGET. Census 103→90, hunks 18→16. THE FIGHTER ARMS ARE NOT WALLED —
  iteration-33's "fusion-coupled" banking is superseded (the wall's dispense-
  position CONSEQUENCE was movable without the fusion itself).
- D-NEW-2 (steps→col merge, the 1091-band slot): REGRESSED 97.55→97.18,
  REVERTED. Mechanism: col's band sits between i (1090) and ptr (1092) —
  steps webs popping there steal from the anchors/i-webs. The steps family
  needs the 1101-1253 band window instead (see entry points).

### THE FUSION WALL, restated under the corrected model (bounded, not closed)
Ours' count2=0 decl-init emits its own li (+48, the 2-line Δ); the literal
zeros coalesce temp-class-only into the fused zero web (extent +3c..+870,
interferes with everything → fresh r23 at its pop). Target's zero rides
count2's home to a front r25 pop. Every connecting spelling is IRO-normalized
(const-prop), class-refused (home-init same-value), or code-changing
(u64>>32 = library call). Doors dead: 4 init spellings, comma shield, halves
stores, u64-shift, i=count2 (re-proven 3 graphs). REMAINING CONSEQUENCE
(bounded by the census): ~28 sites, all r23-vs-r25 — {+03c,+044} zero pair,
{+260,+268,+26c,+280...} B-arm d-pointer cascade, {+398,+39c} ternary,
0xC00-fighter walker shifts (+420-444 ours r23/r24 vs tgt r24/r25) — plus the
2-line Δ. The fighter nav arms are NO LONGER part of this family.

### TASK 3 — micro-sites
- +b80/+b84 found/find-p init ORDER swap (current-graph evidence): flipping
  FindNextFighter decl order (found before p) regressed 97.55→97.49,
  REVERTED — positional fix cascades into the arm coloring on this graph.
- lf-wraps: GONE from the census (closed by iterations 33-34 cascades).
- nr add-shift +0f4 (lhz r0 vs r3) and soup +0bc family: still open, no new
  differentiator.

### State after iteration-34: match 97.55, opcode 98.4, delta 3, hunks 16,
90 register-mismatched aligned sites. Region census: soup 17, B-arm 13,
0xC00-fighter 10, rt_f 10, dn_f 10, dn_n 8, up_f 6, lf_f 6, rt_n 5, head 3,
0xC00-name 2.
### Iteration-35 entry points (named levers)
1. steps → row2 merge (first-use 1128 = the ptr2(1101)..found(1253) band
   window the steps family needs): predicted to fix the dn_n/rt_n found/steps
   2-cycle (r24↔r27, ~13 sites) and feed the dn_f/rt_f 3-cycle. UNTESTED.
2. up_f/lf_f found/find-p 2-cycle (r24↔r25, 12 sites): helper-local ordering
   inside FindPrevFighter inline — mechanism unknown (inline locals IRO-
   renamed; decl order does not survive — iteration-28).
3. fc/fr soup family (17 sites): walker/rank/result coloring — unexamined on
   the new graph.
4. Fusion-debt family (~28 sites + 2 lines): walled (above).
5. Maximal-reachable estimate: ~62 of 90 sites + possibly the 2-cycle families
   ⟹ ceiling ≈ 99%+ if all non-walled families crack; realistic next-session
   target = the two 2-cycles + soup ≈ 97.9-98.2.
