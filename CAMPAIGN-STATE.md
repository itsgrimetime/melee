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

## Iteration-35: three levers executed — 97.55 → 97.68; census 90 → 74
Baseline verified at 8ee83c19c. 3 builds (2 committed, 1 byte-identical re-test).

### Lever meter table
| lever | edit | result | verdict |
|---|---|---|---|
| 1. steps→row2 | merge nav steps into row2 (band 1128, the ptr2..found window; dump-verified found(351-359)-before-steps(364-366) pop order first) | fighter found_merged r25→r28 ✓TARGET (retail; debug predicted differently — known ±divergence), fighter steps r28→r25 (1 step closer, want r24), name 2-cycle DID NOT flip. 97.55→97.58, census 90→86 | COMMITTED |
| 2. FindPrevFighter p-decl-first | align Prev's decl order with Next's (found/find-p colors swap with helper decl order; iter-34's Next-flip regression = flipping AWAY from the working order) | up_f/lf_f found/find-p 2-cycle FULLY RESOLVED — both find-only fighter arm windows EMPTY in census. 97.58→97.68, census 86→74 | COMMITTED |
| 3. fc/fr soup | analysis only | decomposes into two wall shadows (below); no independent lever exists | NO BUILD |

### Name found/steps 2-cycle: BANKED (new wall characterization)
ig114/ig122 = the dn_n/rt_n found-merge webs (+7c4/+5fc clrlwi + cmpw + rlwimi
+ addic-feed) are STATEMENT-TEMP-banded — they pop ~iter 305, BEFORE the r23
dispense (330) and before every variable band, where r24 is the only takeable
callee-save (r23 undispensed, r25-r31 front-held). Target's equivalent webs =
r27 ⟹ they pop in the FOUND variable band (after steps/walker/anchor). No
variable can outrank a statement temp, so the fix requires the found-merge web
to become variable-banded — a helper-return identity question; the s32-return
+ caller-cast refactors measured WORSE (iterations 25-26). ~10 sites.

### Soup family: two wall shadows (~17 sites)
- fr-side (~11: +18c/+1cc/+1d0/+1d8/+1e0/+1e8/+1f0/+200/+210/+230/+234):
  LHZU-coupled. Target reads hovered via 0(r29) (the lhzu-advanced base);
  ours burns a r24 &hovered temp whose occupancy displaces fr-i to r28 and
  cascades the whole fr ring. Walled with +168 lhzu (the Δ3 member).
- nc-side (~7-9: +094 hovered-temp r28-vs-r27, +0a4-+0ec idx family,
  +0f4/+0fc/+104 lhz+srawi ring): first divergence is the +094 temp pick,
  which chains to B-col r26-vs-r27 = the original CLOSED front-order family.

### TASK 2 — wall re-test on the post-lever graph: HOLDS
Fresh li still emitted (+048 li r25,0; Δ3 unchanged). New-on-this-graph
spelling roll `s32 count2 = count` (count = the zero-rider's variable now):
BYTE-IDENTICAL (const-prop) — reverted, recorded. The decl-init door stays
closed; the wall's target form (count2 home-init IS the buttons-hi zero)
remains unreachable from C on graph #4.

### TASK 3 — micro-sites: +0f4 (nr lhz r0-vs-r3) and +0bc feed the nc-side
srawi ring → B-col shadow; no independent evidence, no builds.

### State after iteration-35: match 97.68, opcode 98.4, delta 3, hunks 16,
74 register-mismatched aligned sites. Commits: 30859c945 (row2 merge), 14451eeec (prev flip).
### Walled families (the maximal-reachable accounting):
1. Fusion-debt (~28: zero pair +03c/+044, B-arm +25x-28x cascade, ternary
   +398/+39c, 0xC00 walker shifts, count-loop walker +858-870) + 2-line Δ.
2. LHZU/fr-soup (~11) + 1-line Δ (+168).
3. B-col front-order shadow: nc-side soup (~8) incl +094/+0f4 micro-sites.
4. Name found/steps statement-temp cycle (~10).
Σ walled ≈ 57 of 74 ⟹ non-walled residue ≈ 17 sites (fighter steps↔ptr2
r25↔r24 2-cycle in dn_f/rt_f ~6, scattered B-arm/0xC00 leftovers ~11).
Maximal reachable without cracking a wall ≈ 97.9-98.0.
### Iteration-36 entry points
1. Fighter steps↔ptr2 2-cycle (dn_f/rt_f, ~6 sites): steps(row2-band) pops
   AFTER ptr2(1101-band) — target wants steps=r24 BEFORE ptr2=r25. Needs a
   steps home between ptr(1092) and ptr2(1101) — no existing variable there;
   OR move ptr2's nav webs to a later band (split nav-ptr2 from soup-ptr2 —
   but the soup share is what feeds the name walkers... check whether a
   fighter-only ptr3 alias for the nav ptr2 role lands in the right window).
2. The walls stand unless a new mechanism class appears (rider-move was the
   last one). Re-test set on next graph change: decl-init door, lhzu site,
   B-col order.

## Iteration-36: copy-coalesce door closed with mechanism; dead-anchor tool found — 97.68 → 97.74
Baseline verified at 39b9acf72. 3 builds: 1 reverted (byte-identical), 2 committed as one logical change.

### TASK 1 — THE COPY-COALESCE DOOR: CLOSED (the wall's last untested class)
Evidence first: target +848 `mr r24,r25` = the count-loop walker init copy ours
lacks (a Δ3 member). The multi-def hypothesis (ternary makes count2's web a
{0,1} phi → no const-prop → copy survives) is CORRECT about target's web — the
ternary windows show BOTH builds already share the ternary 0-arm with the live
zero (multi-def web exists in both; +388-tgt/+398-ours li 1 only, 0-arm falls
through). The difference is purely WHICH web owns the cluster: temp r23 (ours)
vs count2-home r25 (target).
- Build (ternary routed through count2 + store from it): BYTE-IDENTICAL — the
  IRO DCEs the dead count2 write (the path-disjointness that makes it safe
  makes it removable). count2's web never becomes multi-def.
- The live-use variant (`if (count2 != 0)` after the store) would delete the
  field re-load BOTH builds emit (+390-tgt/+3a0-ours lbz) — body change ✗.
- ROOT MECHANISM (final): ours emits TWO overlapping zero materializations
  (+3c temp li, +48 count2-home li) whose linear ranges overlap → same-value
  coalesce refused → split forever. Target emitted ONE li because the
  original's count2 init IS the buttons-hi IR node — only spellable via u64
  arithmetic ((s32)(input64>>32)) which this compiler lowers through __shr2u
  (door 2's measured death). WALL CLOSED: every mechanism class now has a
  measured dead door (const-prop, DCE, class-refusal, range-overlap, library
  call). The fusion family (~28 sites + 2-line Δ) is the wall's full extent.

### TASK 2 — the free sites: fighter steps ring CRACKED (97.68 → 97.74)
- Build A (ptr3 = dn_f/rt_f inner walker, own variable): cycle ROTATED —
  steps r25→r24 ✓TARGET, but merged r28→r25 ✗ regressed, walker r28 ✗.
  97.70, census 72.
- Build B (+ DEAD BAND ANCHOR `ptr3 = sorted;` in the 0xC00-fighter branch):
  THE NEW MECHANISM — a dead init anchors a variable's band position
  (precedent: count's dead decl-init at 1050 anchored count's band, proven by
  D-NEW-1). The anchor is DCE'd (Δ3 held) but places ptr3's band in the
  row2(1128)..found(1253) window → walker pops before found_merged.
  dn_f ring FULLY TARGET: merged=r28 ✓, steps=r24 ✓, walker=r25 ✓, anchor=r27 ✓.
  97.74, census 67. COMMITTED (one commit, ptr3+anchor).
- rt_f ring did NOT flip (merged=r25/walker=r28 still swapped, ~5 sites):
  per-arm divergence — dn_f's merged popped variable-band-late, rt_f's
  popped before its walker; the merged webs' band classification differs per
  arm (statement-temp vs variable boundary). OPEN — needs a dump read of the
  rt_f merged web's ig and pop slot.

### DEAD-ANCHOR BAND PLACEMENT (new general tool — record for reuse)
`var = <any-live-value>;` on a path-disjoint, provably-dead branch is DCE'd
(zero instructions) but anchors the variable's FIRST-USE position for the
promotion's band ordering. This makes band placement a free knob anywhere
EARLIER than the variable's first real use. Combined with the band model
(earlier first-use = higher band = pops earlier; within-band latest region
pops first) this gives nearly arbitrary pop-order control for variable webs.
LIMIT: statement-temp webs (e.g. the name found-merge ig114/122) have no
variable identity — anchors cannot reach them.

### TASK 3 — substrate re-tests on the new graph: both walls HOLD
- lhzu/fr root: +168 addi+lhz unchanged (Δ3 member), fr ring intact in census.
- Name statement-temp cycle: dn_n/rt_n buckets unchanged (5+5 incl the
  count-loop fusion sites). No new door; recorded.

### State after iteration-36: match 97.74, opcode 98.4, delta 3, hunks 16,
census 67. Region: soup+nc 17, B-arm 13, 0xC00-fighter 10, dn_n+countloop 8,
rt_f 7, rt_n 5, head 3, 0xC00-name 2, dn_f 2.
### Walled (final accounting): fusion ~28+Δ2, lhzu/fr ~11+Δ1, B-col shadow ~6,
name statement-temp cycle ~10 ⟹ Σ ≈ 55. Non-walled: rt_f ring 5, init-pair
order swaps 4 (+99c/+9a0, +b80/+b84 — positional, the decl-flip regressed),
scattered ~3.
### Iteration-37 entry points
1. rt_f merged/walker swap: dump-read the rt_f merged web (ig + pop slot) —
   if it's variable-band, a second dead anchor or member shift may flip it
   like dn_f's. ~5 sites.
2. The init-pair order (+99c/+b80, 4 sites): FindNextFighter emission order —
   the iter-34 flip regressed at 97.55; RE-TEST at 97.74 (substrate rule —
   the graph has changed 4 times since).
3. Walls stand. Maximal non-wall ceiling ≈ 97.9.

## Iteration-37: field-shape theory ALIVE (iteration-38 headline); rt_f + init-pair refuted
Baseline 97.74 at 90aae6e50. 2 builds, both reverted with mechanism. No source commits.

### THE DEAD-ANCHOR TOOL (named tool — prominent record, as standing equipment)
**Dead-anchor band placement**: `var = <any-live-value>;` on a path-disjoint,
provably-dead branch is DCE'd (zero instructions emitted, Δ unchanged) but
anchors the variable's FIRST-USE position for the promotion's band ordering.
Band model: earlier first-use = higher band = pops earlier; within-band,
later region pops first (with exceptions — see rt_f anomaly below). Proven
uses: count's dead decl-init (D-NEW-1, iteration-34), ptr3's 0xC00-branch
anchor (iteration-36, dn_f ring full target match).
LIMITS: (1) statement-temp webs (no variable identity) are unreachable —
e.g. the name found-merge webs ig114/122; (2) within-variable web ordering
is not always contiguous (rt_f walker landed ig55 while dn_f's landed ig67
from the same ptr3 variable — mechanism of the split UNKNOWN); (3) bands are
no guarantee of the PICK — the at-pop blocked set still decides.

### TASK 1 — BUTTONS FIELD-SHAPE EVIDENCE (theory ALIVE; no builds per orders)
(a) Declaration: `/* 0x0008 */ u64 buttons;` in src/melee/mn/mnmain.h
(MenuFlow). InputProc's +38/+44 store pair comes from the SHARED inline
`Menu_GetAllInputs()` (src/melee/mn/inlines.h:38:
`return mn_804A04F0.buttons = mn_80229624(4);`).
(b) NO matched function constrains the layout: every writer emits the
{stw lo, stw hi} pair and every reader (`buttons & mask`) reads only the lo
word — u64-vs-2×u32 is codegen-indistinguishable across all 8 TUs touching
the field (mnruleplus 87.98, mnitemsw 98.43, mnname 94.98, mnnamenew 93.05,
mndiagram2 91.13, mnmainrule, mnsoundtest, mnmain). Theory ALIVE.
(c) THE IN-TREE IDIOM (three sibling TUs already bypass the inline):
mnmainrule.c:121, mnnamenew.c:712, and the SISTER FUNCTION
mnDiagram2_HandleInput (mndiagram2.c:294, TU 91.13/fn 89.34 — unverified
but convergent):
    result = mn_80229624(4);
    ((s32*) &mn_804A04F0.buttons)[1] = result;
    ((s32*) &mn_804A04F0.buttons)[0] = (var_r28 = 0);
    ... mn_804A04F0.entering_menu = var_r28;   // zero-local reused!
PREDICTED InputProc spelling (iteration-38 build 1 — NO header change):
    u32 input = mn_80229624(4);
    ((u32*) &mn_804A04F0.buttons)[1] = input;
    ((u32*) &mn_804A04F0.buttons)[0] = (count2 = 0);
(+ `s32 count2;` decl uninitialized). Predicted codegen: ONE li (count2's
init IS the +3c li r25), stw count2,8(r29) — the +48 li disappears (Δ3→Δ2),
the range-overlap refusal dissolves (one li = no second range), count2's
home web absorbs {+3c, +44} and via the ternary 0-arm same-value reuse the
{+390 ternary, +25x entering_menu} cluster ⟹ THE MEGAWEB FORMS ⟹ fusion
family (~28 sites) + possibly the front re-order (B-col shadow ~6, IF the
fused web's degree shift reorders the finishing sweep). RISK: IRO may still
const-prop the store operand and split (door-5's death mode) — the
assignment-expression def-form and the sibling convergence are the evidence
it may not. BLAST RADIUS: one statement in InputProc; bypasses the shared
inline exactly as the three siblings do; zero header edits.

### TASK 2 — rt_f ring: ptr4 split REGRESSED (97.70), reverted
At-pop mechanism (dump): dn_f merged (ig66, pop 360) is blocked from r25 by
its walker (ig67, pop 359) → r28 ✓. rt_f merged (ig64, pop 362) is NOT —
its walker is ig55 popping 371 (AFTER) → r25 free → merged r25 ✗. The ptr3
variable's two webs landed NON-CONTIGUOUS igs (67 vs 55) — anomaly vs the
band model; mechanism unknown. ptr4+anchor for rt_f: 97.74→97.70 ✗ reverted.
rt_f ring (~5 sites) stays open pending the numbering anomaly's mechanism.

### TASK 3 — init-pair order re-test: REGRESSES AGAIN (97.74→97.68), reverted.
FindNextFighter found-first costs more elsewhere than the 4 positional sites
(+99c/+9a0, +b80/+b84) it would fix. Second graph re-test, same result.

### State after iteration-37: match 97.74, opcode 98.4, delta 3, hunks 16,
census 67. Tree clean at the iteration-36 stack.
### FOR DRIVER 4 (rotation brief)
- Worktree: this one; branch claude/mndiagram-802427B4-investigation.
- Baseline: 97.74 / opcode 98.4 / Δ3 / hunks 16 / census 67 (skeleton-aligned
  register-mismatch count; script inline in iteration-33+ sections).
- Gates: neutral-or-better vs ALL of the above. Commit gate-passers
  individually. Diagnostic forces (r14-r17 only). #550: verify force lists
  applied via fingerprint sites appearing.
- ITERATION-38 PROGRAM: (1) the field-shape build above (the wall's best
  remaining shot; if the megaweb forms, re-run the front-order probe and the
  whole-census — expect up to ~97.9-98.3); (2) if it fires, substrate-rule
  re-tests: lhzu site, name statement-temp cycle, rt_f ring, init-pair order
  — all four walls/opens get one cheap roll on the new graph; (3) if it
  dies, read WHY from the dump (the store-operand IR shape) and bank the
  wall closed-for-good with all six+1 mechanism classes enumerated.
- Tools: dumps via `melee-agent debug dump local src/melee/mn/mndiagram.c
  --output X --no-cache-sync`; InputProc = 26th class-0 COLORGRAPH
  (n_nodes=396); fingerprints `--force-phys "IG:14,IG2:15" --force-phys-fn
  mnDiagram_InputProc --diff`; census script in iteration-33; at-pop blocked
  set = interferers with EARLIER pop iter only.
- Walls (full statements in iterations 34-36): fusion ~28+Δ2 (field-shape =
  the live door), lhzu/fr ~11+Δ1, B-col shadow ~6, name statement-temp ~10.
- Non-walled opens: rt_f ring 5 (numbering anomaly), init-pair 4 (flip
  regresses), scatter ~3.

## Iteration-38 (driver 4): FIELD-SHAPE FIRES — fusion door OPEN; landing = substrate
migration (no commit; tree restored to baseline 5a42093cd, re-verified 97.74/Δ3)

### TASK 1 — THE FIELD-SHAPE BUILD: the fusion MECHANISM WORKS (door-5 refuted)
Build (mirrors mnDiagram2_HandleInput:294 exactly; PAD_STACK(64) kept; both the
decl-init form `u32 input = mn_80229624(4);` and separate-assign form measured —
codegen-identical 96.70/96.69):
    u32 input = mn_80229624(4);            // bypasses Menu_GetAllInputs inline
    ... s32 count2;                        // decl uninitialized
    ((s32 *) &mn_804A04F0.buttons)[1] = input;
    ((s32 *) &mn_804A04F0.buttons)[0] = (count2 = 0);
METER:
- ONE li ✓✓: exactly one `li r25,0` at +03c (target-identical position AND
  register, naturally — no force). The +048 fresh-li is GONE. Δ2 fusion debt PAID.
- MEGAWEB FORMS (r14-verified, ig35 = count2's HOME web, 11 sites): {+03c li,
  +044 buttons-hi stw, +874 count2++, all 8 count compares +8a8/+8cc/+970/+994/
  +a8c/+ab0/+b54/+b78}. count2's home-init IS the buttons-hi zero = the exact
  target form the wall demanded. The {ternary, entering_menu} cluster did NOT
  join on this graph (smaller than target's 16-site web).
- FRONT POP r25 ✓: ig35 pops front iter8 → r25 naturally (count2-home keeps its
  D-NEW-1-era band; order+fusion NO LONGER mutually exclusive — the iteration-24
  "mutually exclusive through every door" verdict is SUPERSEDED by this door).
- DEATH MODE (the gate-fail): match 96.70 < 97.74. NOT door-5 const-prop (the
  def-form `(count2 = 0)` store survives IRO; the sibling-idiom prediction was
  CORRECT). Two new mechanisms:
  M1 ENTRY-BAND PERMUTATION: bypassing the inline makes `input` an explicit
  home web; the three entry webs renumber by CREATION ORDER (statement position):
  ig176=sorted < ig178=input < ig180=base → same-sweep descending pop → base=r30,
  input=r29, sorted=r28 = cyclic permutation of target's sorted=r30, base=r29,
  input=r28. Baseline graph achieves target order via SORTED'S SWEEP DEFERRAL
  (deg 27 vs field-shape 25 — the inline's u64 temps were ~2 deferral-margin
  edges; sorted skips the ascending sweep, pops right after data).
  M2 DOWNSTREAM RENUMBER RE-ROLL (iteration-28 blocker class): the inline bypass
  shifts every downstream @-temp; the nav/pool coloring tuned in iterations 33-36
  re-rolls. STRUCTURAL fallout, not just renames — Δ multiset vs target:
  {li +3, mr +3, clrlwi −2, b +1} + the standing lhzu member = Δ6 (901 vs 895).
  fc-head +178 addi/+17c mr pressure copies are back.

### THE FORCE PROOF (diagnostic; debug DLL; force verified applied per #550)
--force-iter-first "53,176,180,178" --force-iter-first-fn mnDiagram_InputProc:
front pops 53→r31, 176(sorted)→r30 ✓, 180(base)→r29 ✓, 178(input)→r28 ✓.
Same-offset operand census (forced-debug vs target): 62 → 50 reg-mismatch
operands; the THREE entry families ((r30,r28)×4, (r29,r30)×4, (r28,r29)×5)
vanish exactly; downstream families ((r28,r27)×6, (r24,r3)×8...) UNTOUCHED —
M1 and M2 are independent. Head residue after force: only the +030/+034
EMISSION-ORDER swap (both registers correct; ours emits base-addi before
input-addi, target the reverse — scheduler order, untested lever).

### THE C-LEVER HUNT for M1 (sorted-first-pop): blocked both ways, spellings tried
- Option B (sorted decl bare + `sorted = mnDiagram_804A0750.sorted_fighters;`
  AFTER the stores): creation-order control PROVEN IN VIVO — base→r29 ✓ and
  input→r28 ✓ snapped (two of three) — but sorted's lis/addi EMITS AFTER THE
  CALL (MWCC does not move defs across calls; target needs +004/+018 pre-call)
  → prologue shifts → 96.14. REVERTED. The coupling: created-last (color) and
  defined-pre-call (schedule) are mutually exclusive for sorted through plain
  statement order — C89 blocks decls after statements; nested-block and
  comma-expr forms all put the def textually post-call.
- Deferral route (+2 edges on sorted, body-neutral): no spelling found. DCE'd
  defs add NO edges (but DO consume ig slots, see below). u64-pair pressure
  reintroduction = the baseline (loses fusion) or __shr2u libcall (door 2).
- NOT claiming source-impossibility: untested directions = the +030/+034
  emission-order lever, store-order swap (zero-store textually first; scheduler
  may normalize), data/sorted decl swap (shifts creation indices), and any
  spelling that re-adds ~2 final-sweep interference edges to sorted.

### THE WALL RESTATED (supersedes "fusion family ~28+Δ2 walled")
The fusion door is OPEN: the field-shape build produces target's count2-home
megaweb fusion + front r25 pop + Δ2 paid, from natural sibling-precedent C.
The cost is the substrate: −1.04pp (96.70) from M1 (~13+ same-offset sites +
head) and M2 (the 33-36 nav tuning invalidated + Δ+5 structural). LANDING IT =
the iteration-29 pattern: commit-below-gate (orchestrator decision required;
gates forbid it for a driver) then re-tune the nav levers on the new graph
(rider-move/anchors/decl-order were all graph-relative). Expected path:
96.70 → ~97.2 (front lever or accepted-as-is) → re-climb past 97.74 with the
fusion family + Δ2 as permanent gains. The 33-36 lever recipes are recorded
and re-executable; the re-tune is multi-iteration work.

### TASK 3 pivot — rt_f numbering anomaly READ (mechanism found, no build)
Baseline dump, ig54-68 pop window: igs 58-63 AND 65 are DEG-0 EMPTY WEBS
(DCE'd defs still consume ig indices = empty placeholder slots, pop to r0).
The window is REGION-MAJOR: dn_f cluster {68,67=ptr3-walker,66=merged} >
[empties] > rt_f cluster {64=merged, 57,56,55=walker family}. ptr3's two webs
(67 vs 55) are split by the empty slots + rt_f's own cluster — this is the
iteration-37 "non-contiguous anomaly" mechanism. rt_f merged (ig64, pop 362)
still pops BEFORE its walker (ig55, pop 371) → r25 ✗. A lever must lift the
rt_f walker web above ig64 — note the slot-consumers (which dead defs create
58-63?) are unidentified; candidates: the ptr3 dead anchor itself, i=count2,
count's dead decl-init. Iteration-37's ptr4 split regressed because it
re-rolled this whole window.

### Substrate sweep: NOT RUN (contingent on a committed graph change; none).
### Standing observation (verify before relying): a build with PAD_STACK(64)
removed from InputProc scored 97.74 with the same source-fingerprint as
baseline — PAD_STACK(64) may be codegen-neutral on the current graph.
### State: tree CLEAN at 5a42093cd, match 97.74, opcode 98.4, Δ3, census 67.
### Driver-5 entry points (priority order)
1. ORCHESTRATOR DECISION: land the field-shape substrate (commit 96.70 +
   re-tune campaign) — the only known path to the fusion family's ~28 sites
   + Δ2. The build recipe, force proof, and M1/M2 decomposition are above.
2. If landing: first probe the M1 levers (emission-order +030/+034, store-order
   swap, deferral-edge spellings), then re-run the iteration-33-36 lever set
   on the new graph (cur→i merge bands, rider-move, ptr3 anchor, prev-flip).
3. If not landing: rt_f window lever (lift walker above ig64; identify the
   empty-slot creators first — one r14 fingerprint per candidate dead def).
4. Micro-opens unchanged: init-pair 4 (two graphs, flip regresses), nr +0f4 /
   soup +0bc (B-col shadow members).

## Iteration-39 (driver 4, orchestrator-directed): SUBSTRATE COMMITTED — new line 96.70 → 96.87
ORCHESTRATOR DECISION (recorded): commit the field-shape below the old gate,
iteration-29 pattern. NEW GATES: neutral-or-better vs the committed line
(96.87 after this iteration). Old-gate report trigger 97.74 stands.

### Commit stack this iteration (tree clean at ee5d2793d)
1. 5c3ee06c3 field-shape buttons stores (96.70; full rationale in message)
2. ec4b3d62a count2-web read spellings B-arm + ternary (byte-identical;
   original's web membership per target +250 stb r25 / +38c fall-through)
3. ee5d2793d dedicated `cur` walker for nav arms (96.70→96.87)

### TASK 0 meter at commit: ONE li r25,0 at +03c ✓, megaweb 11 sites ✓
(r14-verified), Δ6, opcode 98.2, hunks 18, census 234 (skeleton aligner,
/tmp/census.py method inline in this repo's iteration-33 notes).

### FREE WIN CONFIRMED AT COMMIT: B-col/B-row LANDED (the iteration-13-era
closed front-order wall): target +184 lbzx r27 ↔ ours r27 ✓, +1a4 li r27,25 ✓,
+1e8 lbzx r26 ✓, +208 li r26,25 ✓. The B-col shadow family came free with the
fusion. (Residual operands on those lines = M1 sorted/base + walker families.)

### TASK 2 WIN: the cur un-merge (ee5d2793d) — substrate relativity pays again
Iteration-33's cur→i merge REVERSED on this graph: walker band (i, first-use
1086) popped before its arm-mates (pops 336-345 vs mates 346-375) with almost
nothing colored (fc-walker ig81 at-pop blocked set = {r24 by ig96, r31 data}
ONLY) → ascending-reuse r25. Dedicated cur (first-use in nav arms) pops late:
census 234→207, nav-name 74→53, match 96.70→96.87. Walkers now r29 (one
register from target r23).

### THE WALKER→M1 CHAIN (measured, force probe on this graph, applied=4 ✓)
force-iter-first "54,176,180,178" (new-graph front ids; data=54 now):
entry snaps (sorted r30/base r29/input r28) AND the walker/found pair rotates
r29→r24/r23. Mechanism: ours' input(r29) is DEAD inside arm bodies (no later
mask test on the taken path) → r29 free for walkers; target's r29=base is
LIVE in the name arms (hovered reads via r29) → blocked → target walkers
reach fresh r23. M1's fix moves walkers to (r24,r23) — ONE transposition
from target (walker r23, found r24). M1 is therefore worth ~50 entry sites
PLUS most of the walker families (~30+) = the dominant remaining lever.

### The walker/found pair (the last transposition; ~19 sites, (r23,r24)+(r24,r23))
Target pops found BEFORE walker (found r24 colored, walker fresh r23). Ours
pops walker first (cur first-use 1252 < found 1253 → cur band higher).
DEAD-ANCHOR ATTEMPT (found = count; in the path-disjoint 0xC00-name block):
moved the walker r29→r24 but did NOT flip the pair (found stayed r23) and
nav-fighter worsened 32→36 → net 96.84 < 96.87 REVERTED. The anchor moves
bands but the pair's relative order resisted — mechanism of the resistance
unread (the anchor may have moved found's band ABOVE other mates, reshaping
several arms at once). Candidates for driver 5: per-pair anchor positions
(between 1086 and 1252 instead of ~1205), or fix M1 first and re-measure
(the force showed the pair lands (r24,r23) under M1 — possibly found-anchor
+ M1 composes to (r23,r24)... note force+anchor composition was NOT tested).

### TASK 1 (M1 spellings) — no new C-lever found on this graph; oracle re-proven
Banked analysis stands: creation order is call-position-forced (sorted's def
must precede the call for the +018 schedule; created-last is schedule-dead);
the deferral margin's historical source WAS the zero-temp web that the fusion
absorbs by design (the wall ate its own ladder). Untried-but-weak: store-order
swap (body risk, no mechanism), data/sorted decl swap (no relative effect).
The force vector "<data>,176,180,178" remains the goal-oracle (verify ids per
graph: data=54, sorted=176, input=178, base=180 on the current one).

### TASK 3: megaweb completion CONST-PROP-WALLED on the read side
entering_menu=count2 and ternary-0-arm=count2 both IRO-const-prop to literal
zeros (byte-identical) — count2's single-def literal web is IRO-visible-as-0;
the def-form protects only the def site. Target's 16-site membership needs
count2's def to be non-literal (the u64-hi extraction the original had =
__shr2u libcall from C, door 2). The 11-site fused web is the C-reachable
form. Spellings kept in source (ec4b3d62a) — they fire if a future graph
breaks the propagation.

### TASK 4 sweep results (committed graph)
- B-col order family: LANDED free (above).
- lhzu/fr root: HOLDS — +168 addi+lhz persists (Δ multiset lhzu −1), fc-head
  +178/+17c copies persist under force too.
- Name statement-temp cycle: superseded on this graph by the walker/found
  pair form (~19 sites, above).
- init-pair (+99c/+b80): flip REGRESSES third graph in a row (96.87→96.79,
  reverted). Stop re-testing without new evidence; spelling is settled.
- rt_f ring: not re-read on this graph (the old-graph empty-slot window read
  stands as the mechanism guide; slots have shifted — re-read before any
  ptr4-style build).

### State: match 96.87, opcode 98.2, Δ6, census 207. Tree clean ee5d2793d.
### Trajectory note (orchestrator): expect multi-iteration recovery like
29→36 (97.16→97.74 took 7 iterations). Prize map from here: M1 ~50 sites +
walker chain ~30 (force-proven reachable TOGETHER) + pair transposition ~19
+ fc/fr soup 46 (partly lhzu-walled) + scatter. M1 alone ≈ 97.5-97.8
territory; M1+pair+walkers ≈ 98.5+ if the chain composes as the force probe
indicates.
### Driver-5 entry points (priority)
1. M1 C-lever: the entry-band deferral. New angle wanted; everything
   statement-order is exhausted. Consider: what besides degree defers a node
   past its ascending-sweep slot (the dump's sweep mechanics around pops
   10-30 = the last main-phase pushes; the deferral threshold question from
   iteration-38/39 readings is UNRESOLVED — baseline deferred at listed
   deg 27, field-shape catches at 25, k=29 explains neither).
2. The walker/found pair: anchor-position sweep (the 0xC00-name anchor
   half-worked); or read WHY the pair resisted (one dump: found's web igs +
   pop slots under the anchor).
3. rt_f window re-read on current graph, then the lift lever.
4. fc/fr soup (46 sites): unexamined on this graph beyond the persisting
   +178/+17c copies; the lhzu sub-wall is inside it.

## Iteration-40 (driver 5): M1 + walker/found pair attempts — walls confirmed; rt_f + fc/fr characterized
Baseline verified: ee5d2793d, 96.87%, opcode 98.2, Δ6, census 207. Tree clean throughout.
Gates: neutral-or-better vs 96.87%. No gate-passing edits found. 5 builds attempted, all
reverted. 2 builds were neutral-confirmed byte-identical (not counted in mismatch count).

### TASK 1 (M1 corrected eligibility rule — RESOLVED)
MWCC SIMPLIFY uses ascending ig-idx order within each sweep. Eligibility = scan-time class-0
degree < k=29. For sorted (lowest ig of the front webs = first scanned in ascending sweep):
scan-time degree = push-time degree (no neighbors pushed before it).
- BASELINE graph (dump_baseline): sorted ig177 push-time=27; input(ig179)/base(ig182) have
  ig > sorted → when sorted is scanned, they are not yet pushed → scan-time = 27+2 = 29 = k
  → deferred (not strictly less than k). ✓ Explains deferral.
- CURRENT graph (dump40): sorted ig176 push-time=25; same input+base edges = scan-time 25+2=27 < 29
  → NOT deferred (field-shape removed 2 class-0 edges from sorted by eliminating the u64 temp webs).
Gap = +2 class-0 edges needed on sorted (with ig > sorted's ig) to restore deferral.

### TASK 2 (M1 C-lever) — NO LEVER FOUND; store-order RULED OUT
Store-order swap tested (zero-first order: `[0]=(count2=0)` before `[1]=input`): 96.721% < 96.87%.
REVERTED. Mechanism: swap hurts register allocation elsewhere.
All statement-order directions exhausted per campaign. The deferral gap (+2 edges needed) has no
C-reachable source: DCE'd defs add no class-0 edges; introducing new live GPR webs with first-use
between sorted's and input/base's positions while interfering with sorted = no natural candidate.
UNTESTED: emission-order of the +030/+034 addi pair (base-addi before input-addi, target reverses).

### TASK 3 (walker/found pair transposition) — 3 anchor builds, all FAILED GATE
Three dead-anchor positions tested for `found` (to push found's first-use earlier than cur's):
1. 0x10-arm is_name_mode block (line ~1086): `found = col_result;` before return → 96.793% ✗ REVERTED
   Mechanism: too early — introduces cross-arm interference that cascades negatively.
2. 0xC00 arm GetNameCount()==0 early-return (line ~1195): `found = count2;` before lbAudioAx call
   → 96.844% ✗ REVERTED. Mechanism: anchor moves found's band but pair relative order resisted.
3. 0xC00 arm GetNameCount()==0 early-return (same location), this is build 3 in TASK 3 budget.
   Wait — above #2 is the 0xC00 GetNameCount==0 anchor. All 3 positions tried. Each sub-gate.

PAIR TRANSPOSITION WALL: cur first-use 1252 < found first-use 1253 → cur band higher → cur pops
first (iter ~345-360 in dump) → cur takes r29, found takes r23. Target wants found-first (found r24,
cur r23). Three anchor positions between 1086 and 1252 all failed to flip the pair while holding gate.
The B-col free-win (from iter-39) means the FORCE CHAIN STILL HOLDS: M1 → (r24,r23) pair.
Pair transposition is gated on M1.

### TASK 4 (rt_f ring + fc/fr soup evidence)
**rt_f ring (dump-only read):**
Current graph rt_f arm webs (identified via ig38's interference set): {ig87(r27), ig79(r24),
ig75(r25), ig74(r29), ig67(r30)}. Pop order: ig87→338, ig79→346, ig75→350, ig74→351, ig67→358.
dn_f arm webs (via ig40's interference): {ig86(r27), ig78(r24), ig65(r25), ig72(r29), ig56(r30)}.
BOTH arms have the same register set {r27,r24,r25,r29,r30} on the current graph.
The old-graph "dn_f fully target" verdict was measured at 97.74% pre-field-shape. After the substrate
migration, the old lever commits (steps→row2, ptr3+anchor, FindPrevFighter flip) are in source but
their effect on COLORS is unmeasured on this graph. Cannot assess rt_f ring mismatch vs target
without a force-phys fingerprint of the rt_f merged (row_result4) and walker (ptr3-rt_f region) webs.
RECOMMENDATION: r14-fingerprint ig67 and ig74 (the two unclassified rt_f webs) before any ptr-style build.

**fc/fr soup (evidence summary):**
Two wall shadows characterize the ~46-site soup family (unchanged from iter-35):
- fr-side (~11 sites: +18c/+1cc..+234): LHZU-coupled. Target reads hovered via 0(r29) (lhzu-advanced
  base); ours burns r24 &hovered temp → fr-i displaced → ring cascades. Wall = lhzu Δ (structural,
  delta already Δ6, no room to absorb another structural divergence in lhzu direction).
- nc-side (~7-9 sites: +094, +0a4..+0ec, +0f4/+0fc/+104): first divergence at +094 hovered-temp
  pick chains to B-col (M1 front-order family). Walled with M1.
The fc-head +178/+17c addi/mr copies persist on this graph (verified in iter-38 force probe).
These are pressure artifacts from the nc/nr inline + fc soup shape mismatch; they disappear only
if the fc arm's r29 timing aligns (the lhzu path). The fc/fr soup wall is not independent of M1 + lhzu.

### State after iteration-40
Match: 96.87%, opcode 98.2, Δ6, census 207. Tree clean at ee5d2793d. No source changes committed.

### Wall inventory (updated for current graph):
1. M1 entry-band deferral: sorted needs +2 scan-time edges (push-time 25+2=27 < k=29). Store-order
   swap ruled out. Untested: +030/+034 emission-order swap, data/sorted decl swap.
2. Walker/found pair transposition (~19 sites): gated on M1 (force-chain proven). Three anchor
   positions tested and failed gate. CLOSED until M1 resolves.
3. lhzu/fr soup (~11+Δ1): structural. Cannot absorb lhzu without widening delta.
4. nc-side soup (~7-9 sites): B-col/M1 shadow.
5. Fusion mega-debt (~28 sites + Δ2): the field-shape commit paid Δ2; the 11-site megaweb forms ✓;
   the remaining 5 sites ({ternary, entering_menu} cluster) are const-prop-walled.
6. rt_f ring (~5 sites): unread on current graph. Old iter-36 verdict (statement-temp merged)
   may no longer apply (ptr3 source structure changed through iter-36 commit). Re-read before building.

### Pair-transposition mechanism (at-pop level, from dump40 analysis)
cur (nav walker) and found both have first-use near lines 1252/1253 → cur band slightly higher
→ cur pops before found. At cur's pop: r29 is DEAD (input web ig178 used r29 in the entry band and
is now free as a dispensed callee-save reuse) → cur takes r29. At found's pop: r29 blocked by cur
→ found takes r23. Result: (cur=r29, found=r23) = ours.
Target (cur=r23, found=r24): base=ig180 takes r29 AND IS LIVE in the name arms (hovered reads via
r29) → at cur's pop r29 is BLOCKED → cur goes to fresh r23 dispense → found takes r24.
CONCLUSION: pair transposition is MECHANISTICALLY GATED ON M1. No anchor position can fix it
without first making base=r29 live in the name arms. The three anchor failures are explained:
- any found-anchor earlier than cur's first-use makes found take the r29 dead register FIRST
  → cur takes r23 → pair swaps to (found=r29, cur=r23) — wrong but different wrong.
- the 0xC00-name anchor result (iter-39): cur moved r29→r24 not r23 (found stayed r23)
  = the anchor put found in an EVEN EARLIER band, making the reuse schedule different.
CLOSED: walker/found pair transposition without M1 is NOT achievable via dead anchors.

### Driver-6 entry points (priority)
1. M1 C-lever: untested direction = +030/+034 addi emission-order swap (base-addi before input-addi
   in ours; target emits the reverse — noted in iter-38's force proof head residue). May be sensitive
   to the declaration ORDER of `u32 input` vs `Diagram *data = ...` (creation-order-controlled).
   Cheap probe: swap `u32 input = mn_80229624(4);` and `Diagram *data = ...` in the source
   (both are at-decl inits; their order controls which gets created first in the entry band).
2. rt_f ring re-read: force-phys ig67:14 and ig74:15 to fingerprint those webs, then assess lever.
   Both dn_f and rt_f have {r27,r24,r25,r29,r30} color sets on current graph — possibly both match
   target (or possibly rt_f merged/walker are swapped vs dn_f). Cannot assess without fingerprint.
3. After M1 resolves: re-run walker/found pair (it's mechanistically free once base=r29 live).

## Iteration-41 (driver 5): M1 SOLVED FROM C — u64 store mints the supplier temps; 96.87 → 97.37
Baseline verified 96.87006 at 0b73e8ea6. Committed b7044e54e (97.36688). NEW GATES:
neutral-or-better vs 97.37. Old-line report trigger 97.74 NOT yet crossed.

### THE COMPLETED ALLOCATOR MODEL (definitive statement, supersedes iteration-40's +2 arithmetic)
SIMPLIFY runs repeated ascending-ig sweeps; a node pushes when its CURRENT degree < k=29 at its
scan; pops reverse pushes. The recorded degree column = degree at push. Within the finishing
sweeps, earlier-pushed cohort mates decrement later members' scan degrees (dynamic). The MAIN-sweep
pushes do NOT explain cohort degree differences across graphs — the cohort's listed degrees carry
edges from entry-region webs REGARDLESS of those webs' own sweep fate:
- BASELINE suppliers identified (dump_baseline): ig184 (r0, deg 2, nIntfr 12) + ig181 (r4, deg 2,
  nIntfr 10) — tiny VOLATILE-colored webs popping mid-pack (iters 256-259), both interfering with
  sorted(177) + the whole cohort. They are the u64 conversion temps of the Menu_GetAllInputs inline
  (`buttons = (u64)(u32 call result)` — the pair-half value webs). The hi-zero half coalesced into
  the old zero web (ig180→98 alias).
- Baseline vs field-shape: EVERY cohort member's listed degree = exactly +2 in baseline (uniform).
  Suppliers do NOT need cohort survival, do NOT need ig > sorted — they need to be class-0 webs
  live in the ENTRY WINDOW (where the whole cohort is simultaneously live).
- Deferral: sorted defers when its sweep-2 scan degree (= listed) reaches 27-with-suppliers
  (empirically: listed 27 ⟹ deferred past input/base; listed 25 ⟹ eligible).

### TASK 1 — the creation-point probe: BOTH DIRECTIONS DEAD (prediction held)
- Prediction (written pre-build): creation-order swap cannot change sorted's accounting (suppliers
  stay 2; sorted scans first regardless). Only relabeling possible.
- data/input statement swap: predicted-regression WITHOUT build (data's lwz pair sits pre-call in
  BOTH builds at +020/+024; loads cannot hoist across calls ⟹ moving the call above data's decl
  breaks the head). Not built.
- bp-pointer pre-call spelling (`s32 *bp = (s32*)&mn_804A04F0.buttons;` + stores via bp): NOT
  propagated (unlike the fc/fr hovered-pointer case — entry pointer decls SURVIVE IRO) — the base
  materialization moved pre-call → head schedule broken → 83.06 ✗ REVERTED.
- VERDICT: creation order and schedule position are mutually locked for the entry trio from BOTH
  sides (Option B proved sorted's side iteration-38; bp proves base's side). The +030/+034 emission
  order is M1-COUPLED and auto-resolved under V2 (see below) — never was an independent lever.

### TASK 2 — THE M1 LEVER FOUND AND COMMITTED (the session headline)
Ladder (all retail-metered):
- D1 `if (((u64)input) & 0x10)`: deferral FIRES in dump (front 54,176,180,178; sorted deg 27;
  n_class_regs 467→475) but the u64 test lowers as a real pair test (li hi-zero + li r3,16 ...)
  AND the hi-zero web joins the front (pop 4, steals r27, shifts B-pair/megaweb/gobj down one).
  Retail 95.13 ✗ reverted.
- V1 `count2 = (s32)((mn_804A04F0.buttons = input) >> 32)`: the assignment-expression-pair >>32
  does NOT fold — __shr2u libcall inline at +040..+058 (+5 instrs) — door 2's death mode applies
  to pair-temps too. BUT the M1 head went byte-identical (sorted r30 ✓ base r29 ✓ input r28 ✓)
  and 96.55 total — M1's gains absorbed nearly the whole libcall. ✗ reverted.
- V2 `mn_804A04F0.buttons = input;  count2 = 0;` — COMMITTED b7044e54e, 96.87 → 97.37:
  - The plain u64 field store zero-extends u32→u64, minting the SAME pair temps the old inline had
    (the baseline ig184/181 profile — volatile-class, zero extra instructions).
  - Sorted defers naturally: front = 54(data,r31), 175(sorted,r30), 180(base,r29), 177(input,r28)
    — target colors, byte-identical head through +044, +030/+034 emission order auto-resolved.
  - Front tail CLEAN (B-pair r27/r26/r26/r26, megaweb r25, gobj r24 — no D1-style pollution).
  - FREE FIX: the ternary/entering_menu zero-cluster sites now read the live r23 zero-temp web
    (the hi-zero absorbed i + serves the cluster, old-baseline-style) — the +25c li, +39c b, +3a0
    li inserts are GONE. Line delta 6 → 3.
  - V2b (count2=0 first): byte-identical. V3 (u64 store + def-form [0] re-store): 97.23 ✗ reverted.
- NEW FORCE-ORACLE IDS (V2 graph): data=54, sorted=175, base=180, input=177.
- Orchestrator sub-answers: (a) the cluster zeros were per-site fresh r0 li's pre-V2 (no web to
  extend); V2 dissolved the question — they now ride the zero-temp web. (b) web-multiplicity
  splits in nav regions cannot supply entry-window edges (wrong region — supplier profile).
  (c) no existing web's last-use can move INTO the entry window. Both closed by the profile.

### THE NEW WALL MAP (census 207 → 158 after V2)
Top families: r27→r23 ×32 (steps-walk walkers), r23→r25 ×19 (zero-cluster reads),
r23→r24 ×13 (0xC00-fighter/up_n window incl. count-loop), r25→r26 ×12, r23→r27 ×8 (anchors),
r24→r25 ×7, r27→r28 ×6, r28→r25 ×5 (steps-walk p's), r28→r24 ×5, r29→r24 ×4.
THE SINGLE DOMINANT WALL = THE COUNT2/ZERO FUSION, which now gates almost everything:
- Ours: hi-zero TEMP web = r23 (+03c..+870, absorbed i, serves ternary/entering_menu) + count2
  HOME = r25 (own li at +048). Target: ONE r25 web (count2's home IS the hi-zero).
- The r23-occupancy blocks the walkers' target color ⟹ the 32-site walker family + the 4-cycles
  + the 19-site cluster ≈ ~70 sites are ALL fusion-coupled.
- The walker/found pair transposition (iteration-39/40 wall) was CONSUMED by this wall: the
  found-anchor re-test on the V2 graph (the never-tested M1+anchor composition) = 97.32 ✗
  reverted — anchoring cannot free r23 from the zero web.
- Doors measured dead ON THIS GRAPH: V1 (>>32 pair-temp = __shr2u), V3 (def-form re-store of hi),
  plus the historical set (read-back lwz, comma shield, halves stores, count2-read spellings
  const-prop). The merge itself is class-refused (temp-only same-value zero coalescing) with
  overlapping ranges (+048 li vs +03c..+870 temp). No C door found; per policy: not found with
  spellings tried, mechanism = class-refusal + range-overlap + const-prop triangle.

### TASK 3 — rt_f re-read on the V2 graph (fingerprints unnecessary — interferer-set read)
- rt_f family (via ig38's list): ig87=r23[ROOT], ig79=r24, ig75=r25, ig74=r27, ig67=r28.
  dn_f family (via ig40's list): ig86=r23[ROOT], ig78=r24, ig65=r25, ig72=r27, ig56=r28.
- The up_f/lf_f FIND arms are now FULLY TARGET-COLORED (windows byte-equal mod the lf-wrap instr:
  cur=r23, found=r24, p=r25, sorted=r30).
- The rt_f STEPS ring (asm windows +9b8..+a18 T / +9c4..+a24 C) = clean 4-CYCLE:
  ours (merged=r25, walker=r27, p=r28, anchor=r23) vs target (merged=r28, walker=r23, p=r25,
  anchor=r27). Pivot = walker wants r23 (zero-web-occupied) ⟹ FUSION-COUPLED, not independently
  fixable. The iteration-36/37 rt_f mechanism (band/empty-slot window) is OBSOLETE on this graph.

### TASK 4 — Δ census: 6 → 3 via V2; remaining structurals
Closed by V2: +25c li, +39c b, +3a0 li (ternary/entering_menu cluster — target shape exact).
Remaining Δ3 multiset: {+048 li r25 (count2's own init — THE fusion debt), lhzu pair (+168
addi+lhz vs lhzu — banked wall), fc-head +17c/+180 copies (lhzu-coupled)} and ours-MISSING
T+848 mr r24,r25 (i=count2 init — ours' i absorbed into the zero web, one FEWER instr).
Positional (non-Δ): +448-vs-+498 arg-copy (volatile-pick, no lever in 3 sessions), +68c-vs-+698
addi (lf_n region one-slot).
- lf-wraps (+6dc/+abc clrlwi-vs-mr, 2 replace-sites): THIRD-graph re-roll of the helper-wide
  `return (u8) cur;` = 97.34 ✗ reverted. Mechanism sharpened: target truncates ONLY the srawi-
  derived (lf) wraps; up's clrlwi-derived cur does NOT fold the redundant helper-cast across the
  inline boundary (no IRO cast-CSE through inline copies). A per-arm differentiator from C remains
  unfound (helper split = source duplication, untested).

### State after iteration-41: match 97.37, Δ3, census 158. Tree clean at b7044e54e.
### Wall inventory:
1. COUNT2/ZERO FUSION (the dominant wall, ~70 coupled sites + Δ1): count2's home-init must BE the
   u64 hi-zero; all known C doors measured dead (V1/V3 this graph + historical). The walker family,
   steps 4-cycles, zero-cluster, pair transposition, and T+848 mr all hang off it.
2. lhzu/fr (+168 + fc-head copies, Δ2-equivalent): unchanged, banked.
3. lf-wraps (2 sites): 3 graphs, 3 negative rolls of the cast variant; needs a new mechanism class.
4. Volatile-pick positionals (+448/+498, +68c/+698): characterized, no lever.
### Driver-6 entry points:
1. The fusion wall is THE prize (~+2pp if it cracks → ≈99+). Untested directions: (i) helper-split
   the lf/up Prev callers so lf's wrap truncation comes from a DEDICATED inline (also closes the
   lf-wraps) — does NOT touch the fusion but is the only non-fusion family left; (ii) for the
   fusion itself: hunt a spelling where count2's def reads the STORED buttons-hi through a path
   IRO folds to a register (e.g. struct-copy forms, union typing of the buttons pair) — untested;
   (iii) micro: move count2's decl-init `= 0` to the nav-fighter block head (kills +048 li,
   plants one at +84c-ish where target has mr — net Δ0 but merges 2 diff regions into 1 replace).
2. Verify count2's compares stayed r25-target after any fusion attempt (they are currently ✓).
3. The +84c window: ours has NO i-init instr (absorbed); target mr r24,r25. Any count2-def change
   re-rolls this site — meter it together with (iii).

### Iteration-41 addendum: lf-wraps CLOSED via helper split — 97.37 → 97.49 (b12009fd0)
The per-arm differentiator was found immediately after the state write: dedicated
FindPrevNameWrap / FindPrevFighterWrap inlines (wrap arm `return (u8) cur;`) for the lf callers
only. Inlines expand per call site, so the split changes nothing at the up sites. Both
+6dc/+abc clrlwi-vs-mr sites closed; Δ3 held; census family list otherwise unchanged.
FINAL STATE: match 97.49, Δ3, tree clean at b12009fd0. Gates for driver-6: ≥ 97.49.
Wall inventory item 3 (lf-wraps) is RESOLVED; items 1 (fusion ~70 sites), 2 (lhzu/fr),
4 (volatile-pick positionals) stand as written.

## Iteration-42 (driver 6): combined-form hunt — seesaw diagnosed as MUTUALLY EXCLUSIVE; no commit
Baseline verified: 97.49% at b12009fd0 (b7044e54e V2 u64-store + b12009fd0 lf-wraps). Δ3, census 158. Tree clean throughout. No gate-passing edits found. 4 builds measured (all reverted).

### TASK 1 — EVIDENCE PASS (the complete seesaw diagnosis)

#### Sibling (mnDiagram2_HandleInput) full store idiom
Lines 293-295 of mndiagram2.c:
  `((s32*) &mn_804A04F0.buttons)[1] = result;`   // lo-word of u64 (offset +0c)
  `((s32*) &mn_804A04F0.buttons)[0] = (var_r28 = 0);`  // hi-word (offset +08) via var_r28
Sibling target asm at +030/+034/+03c: stw r31,12 / li r28,0 / stw r28,8 — ZERO conversion temps.
The sibling has NO M1 requirement (uses r30 for data/user_data, not sorted); its half-store works
because it doesn't need the deferral suppliers.

#### Target window +038..+04c (decoded)
```
+038: stw r28,12(r29)   # [1] = input (same as half-store and V2)
+03c: li  r25,0          # ONE li — count2 (r25 home web, front pop)
+044: stw r25,8(r29)    # [0] = count2 (hi-word)
+048: beq ...            # test from +040 rlwinm. r0,r3,0,27,27
```
Target has 3 instructions for the store pair (no extra li). count2=r25 IS the zero stored to
buttons-hi. sorted=r30 (M1 achieved). The target had BOTH simultaneously.

#### IR the target must have had
The count2-home-init IS the u64-hi-zero (the zero-extension of u32 input's hi-half). The
original's count2 def traced through the buttons store path, making it opaque to const-prop
(hence `mr r24,r25` at +848 for i=count2 survives). The u64 store created two class-0
pair-half virtuals (ig181/ig184 analogs) live in the entry window, giving sorted +2 scan-time
edges to defer (scan-time deg 27+2=29=k). Simultaneously, the pair-half zero virtual and
count2's home were THE SAME IR node — possible only if count2's assignment was the u64
zero-extension result itself (not a separate literal 0).

#### THE DEFERRAL MECHANISM (from dump analysis; definitive)
V2 baseline SIMPLIFY: sorted=ig175, push-time deg=27, n_class_regs=469.
Half-store form: sorted=ig176, push-time deg=25, n_class_regs=469 (same total webs).
V2 has ig181 (deg=2) and ig184 (deg=0) in the entry window; half-store has ig181 (deg=0),
ig184 (deg=0). The +2 deg difference = ig181's 2 edges. ig181 is the u64 zero-extension
pair-half virtual (fingerprinted: the rlwinm. r0,r3 scratch at +040 is one of its uses).
Without these 2 extra edges, sorted's scan-time deg = 27 < 29 → NOT deferred → sorted
pushes before base in the ascending sweep → pop order (base=r30, input=r29, sorted=r28).

#### COLORGRAPH comparison (measured from dumps)
V2 front:       data(ig54)→r31, sorted(ig175)→r30, base(ig180)→r29, input(ig177)→r28
Half-store:     data(ig54)→r31, base(ig180)→r30, input(ig178)→r29, sorted(ig176)→r28
Entry trio is a cyclic rotation in the half-store form. count2(ig35)→r25 in BOTH forms.

#### SEESAW MECHANISM (final statement, supersedes iteration-41 wall description)
The u64 store (`mn_804A04F0.buttons = input;`):
  → Creates 2 pair-half virtuals (ig181/ig184 class) live in entry window
  → Gives sorted +2 scan-time edges (deg 25+2=27 in baseline → with pair temps: 27+2=29=k)
  → sorted DEFERS → sorted pops before base/input → sorted=r30 (M1 ✓)
  BUT: the u64-lo zero virtual (pair-half) is a TEMP-class web → same-value coalescing refuses
  to merge it with count2-HOME (range-overlap + class-refusal) → TWO lis (+03c temp, +048 home).

The half-store form (`((s32*)&buttons)[1]=input; ((s32*)&buttons)[0]=(count2=0);`):
  → NO pair-half virtuals → sorted NOT deferred → sorted=r28 (M1 broken ✗)
  BUT: count2's home IS the zero stored to buttons-hi → ONE li r25,0 (fusion ✓)
  count2=r25 ✓, megaweb forms ✓ → 97.01 (-0.48pp from M1 loss)

### TASK 2 — LADDER: 4 builds measured (none gate-passing)
| form | edit | +038..+04c | sorted | count2 fused? | score | gate |
|------|------|-----------|--------|--------------|-------|------|
| V3: u64 + half-store [0] overwrite | `buttons=input; ((s32*)&buttons)[0]=(count2=0);` | TWO lis + TWO lo stores (4 instrs; MWCC emits both, no DCE) + rlwinm reads r28 not r3 | r30 ✓ (M1 fires; conversion temps still present) | NO (+048 li r25 still separate; count2 not fused) | 97.35 | FAIL |
| Half-store: [1]=input, [0]=(count2=0) | sibling idiom verbatim | ONE li r25,0, ONE lo store | r28 ✗ (M1 broken; no conversion temps) | YES (count2=r25, megaweb) | 97.01 | FAIL |
| Reversed half-store: [0] first, [1] second | store hi-zero FIRST | worse allocation | r30 ✗ | — | 96.86 | FAIL |
| V3 re-test (post lf-wrap) | same as V3 but on current b12009fd0 | same as V3 above | r30 ✓ | NO | 97.35 | FAIL |

#### V3 mechanism (why it fails): MWCC does NOT dead-store-eliminate the half-store's stw when
the u64 store already wrote 0 to the same location. Both stores are emitted → +1 extra stw + the
known fresh li → Δ3→Δ5-equivalent; rlwinm mask test shifts from r3 to r28 (scheduling change
from the extra store). Not a viable path.

#### Half-store mechanism (why 97.01 < 97.49): sorted=r28 instead of r30. The entry trio is a
cyclic rotation (base=r30, input=r29, sorted=r28). This costs ~31+ sites vs V2 (entry cascade).

### THE COMBINED FORM: NOT FOUND in the 8 spelling classes tried (each with a measured mechanism)
[CORRECTED FRAMING per standing rule — the original source IS the existence proof that a C form
produces both sides; the reconstruction below is the SEARCH TARGET, not an impossibility claim.]
Spelling classes tried, with measured death mechanisms:
- V3 (u64 + half-store overwrite): emits both stores; MWCC's dead-store elimination does not
  fire across the alias (97.35).
- Half-store alone (sibling idiom): no pair-half virtuals → sorted scan-time deg 27 < k → no
  deferral → entry trio rotated (97.01).
- Reversed half-store ([0] first): worse allocation (96.86).
- Union typing of buttons pair: predicted stack lwz/stw additions (not built; analytic).
- Read-back from stored location: adds lwz (not built; analytic).
- Dead-cast (`(u64)input` in dead block): IRO DCEs dead code entirely, no temps (prior iters).
- Dead arithmetic (`u64 dummy = (u64)input + 0`): IRO DCEs unused result (prior iters).
- u64-shift for count2 (V1 path): __shr2u library call +5 instrs (measured iteration-41).

THE SEARCH TARGET (what any winning spelling must produce, from the IR reconstruction):
1. Two class-0 pair-half virtuals (ig181/ig184 profile) live in the entry window with
   ig > sorted's ig — sorted's scan-time degree 27+2 = 29 = k → deferral → entry trio
   sorted=r30/base=r29/input=r28.
2. count2's home-init = THE SAME IR node as the u64-hi-zero — ONE li r25,0 at +03c,
   stw r25,8(r29), no +048 li; count2's value opaque to const-prop (T+848 mr r24,r25
   = i=count2 SURVIVES).
3. Three-instruction store window (stw input / li 0 / stw 0), rlwinm mask test reads r3.
The deduction channel found no spelling that mints the pair virtuals while making count2's
def be the hi-zero node; the search must continue through channels that do not require
conceiving the form first (permuter = iteration-43).

### TASK 3 — substrate re-tests (no new graph change; walls hold from iter-41)
- lhzu/fr: +168 still addi+lhz vs lhzu; V2's base=r29 correct, but the lhzu requires r29 to
  advance INTO &hovered (r29 = mn_804A04F0 + 2) for the fr arm. In V2, r29 IS the base and
  the lhzu COULD form — but the +168 window's exact condition (r29 dead on the path after +168,
  enabling update-form) remains architecture-visible; the structural Δ1 lhzu member is banked.
- B-col/nc-soup: the half-store form measured and found entry trio rotated → confirms the B-col
  shadow family IS still walled with M1 (the nc-side soup ~6 sites chain to sorted=r28 in the
  half-store form; they didn't improve).
- Fusion re-test: all new spellings confirm the wall; no new mechanism found.

### WALL INVENTORY (iteration-42, framing corrected)
1. COUNT2/ZERO FUSION ↔ M1 ENTRY DEFERRAL: not found in 8 spelling classes tried (mechanisms
   measured above). The SEARCH TARGET spec stands; ~70 coupled sites + Δ1. Next channel:
   breadth-first spelling search (permuter), not further deduction.
2. lhzu/fr (+168 + fc-head copies, Δ2-equivalent): unchanged, banked. No C lever found
   with spellings tried.
3. Volatile-pick positionals (+448/+498, +68c/+698): characterized, no lever found.
4. (lf-wraps: RESOLVED in iteration-41 addendum.)

### State: match 97.49, Δ3, census 158. Tree clean at b12009fd0. NO change from baseline.

### Driver-7 entry points (priority)
The two dominant walls (fusion ↔ M1 exclusivity + lhzu) together account for ~81 of 158 census
sites plus Δ2. The non-walled residual ≈ 77 sites (volatile-pick + scattered unknowns). A deep
census re-read on the current graph is the most useful next step:
1. **RE-CENSUS the 158**: which of the 77 non-walled sites are truly free? Use the reconstructor +
   skeleton aligner on the current graph to produce a fresh web-level extent table. The iter-33..36
   nav/walker lever set (cur→i, rider-move, anchors, prev-flip) is all committed and on this graph;
   the residual families from that era may have shifted. A census pass may reveal NEW lever families.
2. **The +84c window** (T: mr r24,r25 = i=count2; ours: no instruction = i absorbed into zero-temp):
   This site is part of the fusion debt. It moves only when the fusion search target is hit.
   Do NOT invest deduction build budget here.
3. **Micro-sites unchanged**: +448/+498 (volatile pick), +68c/+698 (lf_n one-slot). No lever found
   in 3 sessions; only build if new evidence appears.
4. **Permuter**: a focused remote-permuter run on the current baseline may crack structural-shape
   residuals in the non-walled 77 that manual analysis has missed. The search substrate infrastructure
   (tools/melee-agent/src/search/) is available. Worth commissioning a targeted run.
5. **Header cleanup**: PAD_STACK(64) is still present (not shippable). The natural frame reservation
   question remains open. Lower priority until match improves further.

## Iteration-43 (driver 6): framing corrected; census split; PERMUTER DEPLOYED (4 channels live)
Baseline verified 97.49 at aa797be33 (tree clean; no source commits this iteration; zero gated
builds spent — no free family justified one).

### TASK 0 — wall framing corrected (orchestrator rule enforcement)
Iteration-42's "NOT reachable from C / PERMANENTLY MUTUALLY EXCLUSIVE" violated the standing
rule — the original source IS the existence proof that a C form produces both seesaw sides.
Rewritten in place (see corrected iteration-42 sections): "not found in the 8 spelling classes
tried, each with a measured mechanism," and the IR reconstruction now stands as THE SEARCH
TARGET (pair-half virtuals live in entry window + count2 home-init == the hi-zero node + ONE li).

### TASK 1 — fresh census (skeleton aligner, /tmp/census43.py): 145 CS-only operand sites
Method: checkdiff --format json → skeleton align (mnemonic + CS-regs wildcarded) → per-position
CS↔CS reg pairs → families + region buckets.
Families (tgt→ours): r23→r27 ×32 (walkers) | r25→r23 ×19 (zero cluster) | r24→r23 ×13 (0xC00
window+countloop) | r26→r25 ×12 (name anchors) | r27→r23 ×8 (fighter rings) | r25→r24 ×7 |
r26→r23 ×6 (B-arm d-ptr) | r27→r24 ×6 (name found-merge) | r24→r26 ×6 | r28→r24 ×5 |
r25→r28 ×5 | r24→r28 ×5 | r28→r27 ×4 | r24→r29 ×4 (fr &hovered) | r23→r25 ×4 (lf_n) |
r28→r25 ×3 | r23→r24 ×2 | r24→r25 ×2 | r27→r28 ×1 | r29→r24 ×1.
Regions: dn_n 23, rt_n 23, rt_f 19, B-arm 15, fc/fr 14, 0xC00-head 13, dn_f 13, nc/nr 8,
lf_n 6, up_n 5, countloop+up_f 4, head 2.

**CENSUS CORRECTION (supersedes iteration-42's "~77 free")**: the fusion-coupled footprint is
~115 of 145 — the name-arm cascades (dn_n+rt_n 46) are walker-family + same-arm mates, all
chained to the r23/r25 occupancy. lhzu/fr ≈ 13. TRUE free set ≈ 10-15:
- nc 2-cycle (5 sites): fingerprinted ig168 = nc walk-idx (pop 264, ours r27, tgt r28) vs
  ig140 = &hovered CSE temp (pop 289, ours r28, tgt r27). BOTH temp-class, no C-variable
  identity: walker = inline-expansion @-temp (decl order does not survive IRO renaming,
  iter-28); &hovered = address CSE (pointer-form propagated, iter-28). Dead-anchor cannot
  reach temp-class webs (tool LIMIT). No lever found with spellings tried; permuter's random
  temp-insertion is the reachable channel for this class.
- nr volatile r0/r3 swap + srawi pair (+0f8/+0fc): volatile-pick, characterized, no lever
  (3 sessions).
- head 2 = aligner skew at the +090 emission-order boundary, not renames.
VERDICT: no free family justified a gated build; deduction yield this round = the census
correction itself. The fusion search target gates ~115 sites ≈ +1.8pp if hit.

### TASK 2 — PERMUTER DEPLOYED (the breadth-first channel; first deployment in 43 iterations)
Setup repairs (all reported/resolved in issue queue):
- Re-bootstrap from CURRENT worktree source (old base.c was Jun-9 pre-V2 — stale-base trap):
  `melee-agent debug permute bootstrap -f mnDiagram_InputProc --melee-root <this worktree>
  --force`. base.c now has V2 u64-store + lf-wrap helpers; randomize_funcs includes all 7
  helper inlines (avoids #424 bl-vs-inline trap).
- `#pragma _permuter define NULL 0` added to base.c (known reduced-context death).
- dtk-objdump import bug in INSTALLED package fixed (#555 RESOLVED: ..mwcc_debug → ...mwcc_debug
  at lines 3300/6399 of main-checkout tools/melee-agent/src/cli/debug/__init__.py).
- Filed: #554 (permute run --target auto-derive: NameError _FRAME_RE — mwcc-blend path broken;
  stock permuter.py works), #556 (remote ps AttributeError), #557 (remote list AttributeError;
  tail/submit/targets work).
- Base score = 1975 (= the 97.49 source, byte-diff scorer).

ENTRY-WINDOW MACRO ENUMERATION (finite, complete): 13 PERM_GENERAL forms over the
buttons/count2 statements — V2, half-store, V3, reversed, + 8 NEW identity-arithmetic forms
tying count2's def INSIDE the u64 expression ((u64)input + (count2=0), |, ^, -, <<32-or,
operand orders). RESULT: {1975×7 = byte-identical fold-backs, 2075, 2640, 3400, 3895, 4055×2}
— IRO const-prop erases every identity-arithmetic count2 connection (the fold-back mechanism,
now measured across the whole family); no form beat base. The conceived-form space is exhausted;
the random channel is what remains.

LIVE JOBS (running past this session; ~50 threads total):
- coder2 `mnDiagram_InputProc-coder2-20260611-032140`: whole-function random, 16t.
- coder3 `mnDiagram_InputProc-coder3-20260611-032157`: whole-function random, 16t.
- coder1 `mnDiagram_InputProc_entryrand-coder1-20260611-032713`: PERM_RANDOMIZE focused on the
  entry window (dir nonmatchings/mnDiagram_InputProc_entryrand) — 0 compile errors (scoped
  mutations), highest-density channel for the seesaw.
- local PID 51907, log /tmp/permuter_local_43.log, 6t whole-function (nohup; reap when checking).
No candidate below 1975 as of session end (coder2/3 ~5k iters, coder1 ~250, local ~2k).

### TASK 3 — micro-sites: no new evidence; no builds (+448/+498, +68c/+698 unchanged).

### State: match 97.49, Δ3, census 145 CS-sites (method change from 158: CS↔CS pairs only).
Tree clean. No source commits.

### Driver-7 entry points (priority)
1. PERMUTER HARVEST (first action): `melee-agent debug permute remote fetch <job>` for all 3
   jobs + check local log/outputs. Triage rules (memory-enforced): scorer optimizes match% NOT
   behavior — mentally execute every candidate; reject volatile hacks/no-op masks/semantic
   breaks; a score-0 may be stale-base rediscovery (base = aa797be33-era source = current
   committed, so score-0 here IS news unless tree moved). Any plausible candidate gets the
   full meter: ONE li? conversion temps (sorted deferral → entry trio r30/r29/r28)? count2
   compares r25? walker family? Δ? match%? Gate ≥97.49.
2. If a seesaw candidate appears: land it, then re-run the iteration-33-36 lever set on the
   new graph (substrate relativity — all nav tuning re-rolls).
3. If jobs plateau (>100k iters no win): stop+reap remotes (`remote stop`, `remote reap`),
   record the negative with iteration counts, and bank the search-target spec for a future
   mechanism (e.g. retro IRO comparison of the pair-half virtual creation on a matched sibling).
4. The nc 2-cycle (5 sites) + nr volatile swap: temp-class; only the permuter channel reaches
   them — included in the running jobs' mutation space.
5. PAD_STACK(64) natural-reservation question: still open, lower priority.

## Iteration-44 (driver 6): ORACLE REFUTES the fusion coupling map; permuter harvest LANDS the walker family — 97.49 → 97.93
Baseline verified 97.49 at a9669fb93. One source commit: e1adac8aa (97.93). OLD-LINE 97.74
REPORT TRIGGER CROSSED this iteration.

### TASK 1 — the fusion oracle (the decisive instrument move)
- force-coalesce r178=r35 (hi-zero virtual into count2-home; virtuals read from the final IR
  snapshot, entry block B4: li r178,0/stw r178,8(r180) = zero temp → ig98; li r35,0 = count2
  home → ig35): **hook safety gate REFUSED** — "virtuals interfere directly per colorgraph
  data; coalesce is invalid" + no copy/identity edge. The gate independently CONFIRMS the
  iteration-36 range-overlap mechanism from the allocator's own data. (Tooling gap noted: no
  unsafe-override flag exists; the gate is correct to refuse — a forced interfering merge
  could hang the allocator.)
- Occupancy composition instead: **force-phys IG98:14** (zero web off-pool entirely; ig98
  fingerprint-verified = {+03c li, +044 stw, +260 stb, +398/+39c ternary, +858-870 i}; force
  application verified via r25→r14×5 + r24→r14×4 relabels in the scored diff).
- SCORING (same-compiler: dtk-objdump on kept debug objects, skeleton-aligned vs target;
  /tmp/oracle44.py): unforced 135 CS-mismatch sites → forced 135. **DELTA = 0 real sites.**
  Per family: walker r23→r27 ×32 UNMOVED; fighter rings ×8 UNMOVED; name anchors ×12 UNMOVED;
  B-arm ×6 UNMOVED; zero-cluster 19→14 (−5 = pure r14 relabels); 0xC00 11→7 (−4 = i-absorption
  relabels).
- **VERDICT: the iteration-41/43 "~70-115 fusion-coupled" map is REFUTED. The fusion wall's
  true footprint = the ~11-site zero-cluster + Δ1 (+048 li) + the i-absorption structurals
  ≈ +0.2pp, NOT +1.8pp.** The walkers do not want for r23's availability.
- THE REAL GATE NAMED (blocked-set read at the dn_n walker ig68's pop, iter 356): r23 held by
  **ig84 = the dn_n steps-walk pointer** (FindNextName p; +614 mr/+620 ++/+634 lbz, pop 340),
  r26 by **ig76 = the steps counter** (li 10/addic., pop 348), r25 by ig81, r24 by statement
  temps ig122/ig158 → walker takes r27. The ~120-site residual mass = WITHIN-ARM POP ORDER
  ({walker, p, steps, anchor, found} permutation per arm) — the iteration-33-39 lever class.

### TASK 2 — harvest: coder2 found the within-arm order lever (same mechanism, same session)
- Channels at harvest: coder2 28k iters, coder3 31k, coder1-entryrand 22k, local 11k.
- coder2 produced 60+ candidates; best **output-1635-1 (score 1635 vs base 1975)**:
  `cur = col;` before the nc GetVisibleNameFrom call (arg passed as (u8)cur). Mechanism = a
  LIVE band-lift: cur's first-use moves from ~line 1252 into the 0x10 arm → cur's band rises
  → nav walkers pop before their arm-mates → the ig84/ig76 steal chain breaks. Semantics
  verified (cur re-initialized in every nav arm before any read; col's value passes through).
- RETAIL METER: **97.49 → 97.93, Δ 3→2 (one fc-head copy closed), hunks 18→8, census 145→101.
  The 32-site walker family landed in full**; dn_n 23→6, rt_n 23→6, rt_f 19→10, dn_f 13→4.
  Cost: fc/fr-soup 14→25 (fr-ring re-roll, lhzu-coupled region). COMMITTED e1adac8aa.
- Sibling triage (verify-semantics rules): 1680 = same lever, head placement, worse — skip;
  1695 = `if (cur && cur) {}` no-op hack — REJECT; 1760 = DELETES the hovered clamp blocks —
  semantic break, REJECT; 1720/1810 = dominated micro-variants — skip. coder3/coder1/local:
  nothing below base.
- STALE-BASE DOCTRINE EXECUTED: all 4 channels stopped; re-bootstrapped from the committed
  source (base = 1635-equivalent, verified `cur = col;` present + NULL pragma); resubmitted:
  coder2 `mnDiagram_InputProc-coder2-20260611-034539`, coder3 `...-coder3-20260611-034549`,
  coder1 `mnDiagram_InputProc_entryrand-coder1-20260611-034558` (entryrand rebuilt on new
  base). Local NOT restarted (remotes dominate; restart recipe: cd decomp-permuter &&
  nohup ./permuter.py nonmatchings/mnDiagram_InputProc -j6 --better-only > /tmp/log &).

### Substrate re-tests on the new graph (committed change)
- Fusion doors: +048 li r25 persists; zero-cluster = 11 true sites (the dn_n +604/+610/+624
  members were walker-cascade mislabels, now gone). Wall stands at its re-priced size.
- lhzu: +168 addi+lhz persists; fr-ring re-rolled around it (the +11 fc/fr cost) — wall holds.
- nc 2-cycle: now r28→r27 ×6 (+098..+0e8) — standing, temp-class.

### New census (101 CS-sites, /tmp/census43.py): r24→r23 ×17 (0xC00-head + fr mixed),
r25→r23 ×11 (zero cluster), r25→r28 ×9 (fr-ring), r23→r25 ×8 (fr + lf_n), r25→r24 ×7,
r28→r27 ×6 (nc 2-cycle), r26→r23 ×6 (B-arm), r27→r24 ×6, r24→r27 ×6, r24→r28 ×5 ...
Regions: fc/fr 25, B-arm 15, 0xC00-head 13, rt_f 10, nc/nr 9, dn_n 6, rt_n 6, lf_n 4,
countloop+up_f 4, dn_f 4, up_n 3, head 2.

### WALL INVENTORY (re-priced by the oracle)
1. Fusion/zero-cluster: ~11 sites + Δ1. Search-target spec unchanged (iteration-42 corrected
   section); permuter value re-priced DOWN to ~+0.2pp.
2. lhzu/fr: Δ1 + fr-ring (~15-20 sites post-re-roll). Walled as before.
3. Within-arm pop order (THE REAL MASS, was mislabeled fusion): ~50-60 remaining sites
   (B-arm, 0xC00-head, rt_f, nc/nr, scattered arms). The 1635 lever class (live band-lifts /
   value-pass-through copies) WORKS here — found by random search, mechanism understood.
4. nc 2-cycle (6) + volatile-pick positionals: temp-class, permuter-only channel.

### DRIVER-7 POSTURE (the wait-state protocol)
- CADENCE: fetch+triage all three remote jobs once per session start and roughly every 2-3
  hours of wall time (`remote fetch <job>` ×3 → diff.diff triage best-first → verify-semantics
  → retail meter → commit gate ≥97.93). After ANY commit: stop all jobs, re-bootstrap, resubmit
  (stale-base doctrine — this iteration's procedure above is the template).
- SEARCH-EXHAUSTED THRESHOLD (per memory's dead-vs-finite guidance): whole-function random
  channels plateau at >150k iterations with zero sub-base candidates; entryrand at >50k.
  On plateau: stop+reap, record counts, bank the negative.
- WHILE WAITING (deduction work that composes): (a) the 1635 lever class generalizes — try
  hand-built value-pass-through copies for OTHER arm variables (found/steps/p) at earlier
  call sites, gated builds, best-first by census bucket size (B-arm 15, 0xC00-head 13);
  (b) one blocked-set read each for the B-arm d-pointer (r26→r23 ×6) and 0xC00-head webs to
  name their gates before building; (c) do NOT re-derive the fusion/lhzu walls.
- Report triggers: next at 98 (old-line 97.74 crossed this iteration).

## Iteration-45 (driver 7): comparison-form flip — 97.93 → 98.18; REPORT TRIGGER CROSSED
Baseline verified: 97b22051b, 97.93%, Δ2, hunks 8, census 101. One source commit: 2b8fc4127 (98.18%).

### BASELINE CORRECTION
Earlier campaign notes said Δ3; the TRUE BASELINE was Δ2 all along. The confusion came
from comparing "Line delta" values without re-verifying on the stashed tree. Confirmed
by `git stash` rebuild: Δ2/hunks 8/97.93.

### TASK 2 — HARVEST: comparison-form flip discovered, metered, committed
Channels at session start: coder2 had candidates down to score 1445; coder3 down to 1445;
coder1-entryrand had 3 below base. All 3 channels re-bootstrapped and stopped per
stale-base doctrine executed at end of iteration-44.

TRIAGE PASS (ordered by score):
- coder3 1445-1: THREE semantic changes: `col=(cur=hovered)` combined assignment +
  `new_var3=count` (0xC00 arm) + `new_var2=col+1` (B-arm). Combined retail: **97.55** (-0.38pp) ✗ REVERTED.
- coder3 1445-2: REJECT — `inline_fn()` no-op wrapper hack.
- coder2 1560-1: `row = hovered; row = row >> 8;` (row band-lift in 0x10-arm). Retail **98.04%** but:
  count2 color shifted r25→r23 (M1 front arrangement broken), frame -120 vs -128 (wrong),
  hunks jumped 8→16. NOT a clean gate-passer — structural integrity failed. REVERTED.
  Mechanism: row's band-lift added an early-used temp displacing count2's sweep-1 position.
  RULE DERIVED: band-lifts in the 0x10-arm / entry region are UNSAFE (they compete with
  count2's sweep-1 front pick). Only band-lifts AFTER the nav loop entry (main phase) are safe.
- coder2 1575-1: `if ((0 < row3) && ...)` operand-flip in up-arm clamp. Retail **98.18%**,
  Δ2 held, hunks 8 held, frame -128 ✓, opcode sim 99.0% (+0.3pp). COMMITTED 2b8fc4127.
  Mechanism: comparison operand-order changes MWCC's cmpwi emission form in the rt_n arm
  (branch shape changes); downstream @-temp renumbering fixes register sites in rt_n/dn_n.
  count2 stays r25 ✓ (the flip is in the main nav body, post-front).
- coder2 1585: REJECT — inline_fn() wrapper hack.
- coder2 1615 (ptr2/i decl swap): retail 97.95% but count2 shifted r23, block shape divergence
  at +0ac (extra b instruction), many misaligned instructions. REVERTED. Mechanism: decl-order
  changes @-temp indices in the 0x10-arm region (same unsafe zone as the row split).
- coder3/coder1 remaining: nothing below 1575 (dominated by the operand flip's siblings).
- Rejected (no-op/hack): 1445-2 (inline_fn), 1585 (inline_fn), 1630 (col=1 assignment to call arg).

### TASK 1 — band-lift generalization: tested, mechanisms recorded
(a) 0xC00-head bucket: `new_var3 = count` (s32, declared between ptr3 and new_var) + usage
  in clamping block. Retail **97.88%** (-0.05pp). REVERTED.
  Mechanism: new_var3's first-use is in the main nav body (safe zone), count2 stays r25 ✓.
  But the new variable's band competes with the at-pop blocked sets in the 0xC00 arm,
  shifting the clamp-block webs in a direction that costs slightly more than it gains.
  The 0xC00-head bucket (~13 sites) is NOT free — its blocked sets are coupled to the
  zero-web/count2 front arrangement (the B-arm d-ptr + 0xC00 scatter are all in the r23→r25
  family, consistent with the fusion-coupled wall). BANKED as walled.
(b) B-arm bucket: no direct band-lift attempt (blocked-set reads show B-arm d-ptr at r26→r23
  = fusion-coupled; other B-arm sites need dump reads). The 1575 operand-flip was discovered
  to address the rt_n arm (misidentified as "B-arm" bucket in driver-7's program — the 
  "B-arm 15" census bucket is: B-arm d-ptr ~6 fusion-coupled + ~9 other sites from the
  name-up arm's row3 comparison chain).

### Substrate re-tests on the 2b8fc4127 graph
- Fusion wall: TWO lis still (+03c li r23 = zero-temp, +048 li r25 = count2). count2=r25 ✓.
  Wall holds at ~11 sites + Δ1. Zero-temp is now at r23 (was r27 in some earlier iterations?
  — the count2/zero positions have shifted with each graph change).
- lhzu wall: +168 lhzu-vs-addi+lhz persists. Wall holds.
- nc 2-cycle: 6 sites (r28→r27 per the iteration-44 census family). Temp-class, permuter-only.

### New permuter channels (stale-base doctrine executed)
Stopped all 3 jobs. Re-bootstrapped on 2b8fc4127 source. Resubmitted:
- coder2: mnDiagram_InputProc-coder2-20260611-040227 (16t, stock)
- coder3: mnDiagram_InputProc-coder3-20260611-040238 (16t, stock)
- coder1: mnDiagram_InputProc-coder1-20260611-040256 (8t, stock)

### State: match 98.18, Δ2, hunks 8, opcode 99.0. Tree clean at 2b8fc4127.
### Wall inventory (revised):
1. Fusion/zero-cluster: ~11 sites + Δ1. count2 at r25 ✓; zero-temp at r23. Wall stands.
2. lhzu/fr: Δ1 + fr-ring. Wall stands.
3. Within-arm pop order: ~50-60 remaining sites (B-arm ~9 non-fusion, 0xC00-head ~13 all
   walled, rt_f ~10, nc/nr ~9, scattered). The operand-flip class (1575/1635 family) works
   here. Permuter is the primary search vehicle.
4. nc 2-cycle (6) + volatile-pick positionals: temp-class/volatile-pick, permuter-only.
5. SAFE-ZONE RULE (new): band-lifts in the 0x10-arm/entry region are UNSAFE (displace
   count2's sweep-1 front position); only band-lifts in the main nav body (post-front) are safe.

### Driver-8 entry points
1. PERMUTER HARVEST: fetch coder2/coder3/coder1 (new jobs started 2026-06-11 ~04:02 UTC).
   Triage rules unchanged. Gate ≥98.18.
2. OPERAND-FLIP FAMILY (the 1575 lever class): systematically check other comparison sites in
   the census buckets (B-arm ~9, rt_f ~10, nc/nr ~9) for `(x > 0)` or `(x > N)` forms that
   could be rewritten `(0 < x)` / `(N < x)`. Each is a cheap 1-character change. Build on
   evidence only (check the census site offsets vs source lines).
3. NEW RULE: before any band-lift, classify the first-use position as safe (main nav body,
   post-front) or unsafe (entry/0x10-arm region). Only safe-zone lifts should be built.
4. After any commit: stop/re-bootstrap/resubmit the permuter channels (stale-base doctrine).
5. REPORT TRIGGER: next at 98.5 (98 crossed this iteration).

## Iteration-46 (driver 7): operand-flip family CLOSED by evidence; harvest lands the 0xC00-fighter
band-lift — 98.18 → 98.45
Baseline verified: ab1ca7e12, 98.18, Δ2, hunks 8, opcode 99.0. One source commit: 5bf6600e5 (98.45).

### TASK 1 — OPERAND-FLIP GENERALIZATION: family closed at ONE site (evidence, zero builds)
Extraction: all 85 compare+branch pairs from both sides (cmpwi/cmpw/cmplwi/clrlwi./srawi./rlwinm.
+ branch), pairwise aligned, register-wildcarded. **85/85 FORMS MATCH.** The 1575 commit closed
the only form-divergent site. THE MECHANISM, precise: `row3 > 0` (literal-RHS gt) emitted
`srawi + cmpwi + ble` (no record-form fold); `0 < row3` (const-LHS lt) folds to `srawi. + ble`
(record form, one fewer instruction). The sibling arms never diverged because: fighter arms
compare `> new_var` (const-propped 0) which folds naturally; the (u8)-truncation arms fold via
`clrlwi.`; the `< 9`/`< 6` arms emit cmpwi+bge both sides. CLASS WRITEUP: the operand-flip lever
applies ONLY where ours emits compare-against-0 as a separate cmpwi after a foldable defining op
(shift/truncation) while target shows the record form — grep signature: `srawi rX` or `clrlwi rX`
immediately followed by `cmpwi rX,0` in ours, record-form in target. No remaining sites in this
function. The +0.25pp of iteration-45 was STRUCTURAL (instruction elimination + form alignment),
not register cascade — the register census was flat at 101 before/after.

### TASK 1b — dn_n/rt_n found↔row2 cycle: fingerprinted, 3 builds, all neutral-reverted
Fingerprint map (r14-r17 probes, 6 dumps): **ig124 = dn_n found-merge** ({+5f8 clrlwi, +5fc cmpw,
+66c or}, pop 303, ours r24, tgt r27); **ig69 = dn_n row2** (li 10/addic., pop 355, ours r27,
tgt r24); ig70 = rt_n row2 (+7d0); ig72 = rt_f row2 (+bb4); ig71 = dn_f row2 (inferred);
ig129 = up_n found (+510); ig145 = rt_f found (+b80); ig140 = fc/fr &hovered (+16c);
ig74 = dn_n anchor (r26 ✓ matches); ig79 = dn_f anchor; ig82 = 0xC00 count-loop walker;
ig73 = fr walker-ptr; ig68 = rt_f steps-ptr; ig76 = fr-soup ptr.
THE TRANSPOSITION MECHANISM: found-merge pops 52 iters BEFORE row2 (303 vs 355) → takes r24
(ascending reuse; r23 blocked by the zero web +03c..+870) → row2 finds r24 taken → r27. Target
pops row2-equivalent first (r24) → found takes r27. Builds, all byte-neutral, reverted:
1. `row2 = cur;` same-path anchor (lf_n, before found's first use): erased (dead-store elim).
2. `row2 = count;` path-disjoint anchor (0xC00-name branch, ptr3-precedent form): ALSO inert —
   the dead-anchor band tool does NOT work for row2 on this graph; row2's per-arm steps webs
   are TEMP-BANDED (igs 69-72), not home-banded — their numbers don't follow row2's first-use.
3. `found2 = FindNextName(cur); found = found2;` intermediate (coder2-1605 shape): copy-propagated,
   byte-identical.
NUMBERING CONTRADICTION RECORDED: found(first-use 1285) promoted before row2(1310) should give
found LOWER igs (pop later) — observed ig124 > ig69 (pops first). The first-use→band model does
NOT predict these temp igs. Not found with spellings tried; mechanism = temp-band pop-order
transposition, numbering not source-predictable. Banked as permuter-territory (~12 sites dn_n+rt_n).

### TASK 2 — HARVEST: dead channels fixed, then the 1365 win (98.18 → 98.45)
- ALL THREE iteration-45 channels were DEAD since submission (~24h, zero candidates): the
  re-bootstrap had dropped `#pragma _permuter define NULL 0` → "Unable to compile base.c".
  **Issue #558 filed** (second occurrence of this death mode). PERMANENT WORKAROUND IN THE
  DOCTRINE: after EVERY bootstrap, re-add the NULL pragma to base.c line 2 and verify
  `./permuter.py <dir> --best-only -j1` prints a base score before submitting.
- Channels fixed + resubmitted (~45 min run): coder2 best 1350, coder3 best 1365, coder1 1465.
- **COMMITTED 5bf6600e5: coder3 output-1365-1** — `new_var2 = count` band-lift in the
  0xC00-FIGHTER clamp block (all uses substituted; decl between row2/row3). 98.18 → 98.45,
  opcode 99.1, Δ2 held, hunks 9 (alignment split), count2/front guards intact ✓. SIDE WIN: the
  +448 arg-copy (volatile-pick, "no lever in 3 sessions") closed structurally — ours now hoists
  the UpdateScrollArrowVisibility arg to target's early-addi shape. NOTE: iteration-45's failed
  `new_var3 = count` was the 0xC00-NAME block; the winner is the FIGHTER block — different webs.
- Triage rejections this pass: coder3-1365-2 (relocates fc_inner: label into the 0xC0 arm —
  SEMANTIC BREAK), coder3-1475 + coder2-1585-class (inline_fn no-op wrappers), coder2-1475
  (`(double) 0` loop-init junk), coder1-1465 (unreachable-code anchor, dominated).
- Metered-neutral on the new base: coder2-1350's `new_var3 = sorted` rt_n lift (copy-propagated,
  byte-identical standalone); 1350's remaining delta vs 1365 (~15 pts) = its partial-substitution
  count form + combined assignment — UNTESTED as a trio, low value, left for channels to re-find.
- STALE-BASE DOCTRINE EXECUTED: all stopped; re-bootstrapped from 5bf6600e5 (+NULL pragma,
  base verified 1365); resubmitted coder2 `mnDiagram_InputProc-coder2-20260611-043921`,
  coder3 `...-coder3-20260611-043931`, coder1 `...-coder1-20260611-043941`; coder3 verified
  iterating on base 1365.

### Census after 5bf6600e5 (102 CS-sites — flat; the wins are STRUCTURAL)
Structural pairs: T-only 13→8, C-only 15→10 (the +440-+494 0xC00 clamp cluster closed).
Remaining structural: nr-head order (+0f0-0fc, known open), lhzu cluster (+164-174, walled),
fusion Δ members (+048 li / T+848 mr, walled).
Families: r24→r23 ×18, r25→r23 ×11, r25→r28 ×9, r23→r25 ×8, r25→r24 ×7, r28→r27 ×6,
r26→r23 ×6, r27→r24 ×6, r24→r27 ×6 ...
Regions: fc/fr 25, 0xC00 16, dn_f 10, nc 7, B-arm 7, 0xC0 6, dn_n 6, rt_n 6, lf_n 4,
cntloop 4, rt_f 4, up_n 3, head 2, nr 2.
WALLS (updated): (1) fusion/zero ~11+cascades (B-arm/0xC0 d-ptr r25/r26→r23 = ascending-reuse
of ours' early r23 zero dispense — confirmed pop-order cascade, not independently fixable) + Δ1;
(2) lhzu/fr Δ1 + fc/fr 25; (3) temp-band pop-order cycles (dn_n/rt_n/dn_f/nc/up_n/lf_n/rt_f
~40) — the ig124-class, permuter-territory; (4) nr-head order 2.

### Driver-8 entry points
1. HARVEST (primary lever source — 2 wins in 2 live harvests): fetch the 0438xx jobs at session
   start. Gate ≥98.45. After commit: doctrine + **NULL-pragma re-add + local compile verify**.
2. The temp-band cycles are the permuter's domain — do NOT build anchors/intermediates for them
   (3 neutral builds this iteration; mechanisms recorded above).
3. The fingerprint map above is current for graph 5bf6600e5 (shifts with any commit).
4. 1350's partial-substitution count form: optional cheap meter if channels stall.
5. REPORT TRIGGER: 98.5 (98.45 now — one small win away).

## Iteration-47 (driver 8): full harvest pass — zero gate-passers; all channels ACTIVE
Baseline verified: 5bf6600e5, 98.45%, Δ2, hunks 9, opcode 99.1%. Channels coder1/2/3 on
base 1365 (jobs 20260611-0439xx), ALIVE at 7.3h wall time. Two fetches executed this iteration.

### Channel status (post-fetch 2):
- coder2: best 1155 @iter8649, latest 5555 @iter38940 — ACTIVE, descending
- coder3: best 1290 @iter864, latest 2165 @iter44242 — ACTIVE, descending
- coder1: best 1250 @iter11588, latest 1560 @iter32056 — ACTIVE, descending

### HARVEST TRIAGE TABLE (all candidates below base 1365, both fetches):

| Candidate | Score | Change | Zone | Verdict | Reason |
|-----------|-------|--------|------|---------|--------|
| coder2-1155-1 | 1155 | `fc_inner:` label relocated into gmMainLib calls region | UNSAFE | REJECT | Goto retargeting — semantic break |
| coder2-1225-1 | 1225 | `u16 *new_var3 = &hovered_selection` pointer alias | UNSAFE | REJECT | Entry-band addition + first-use in 0x10 arm |
| coder2-1265-1 | 1265 | row-split (0x10 arm) + `(col-(0,1))` comma hack | UNSAFE | REJECT | 0x10 arm unsafe zone + no-op comma |
| coder3-1290-1 | 1290 | row-split only: `row=hovered; row=row>>8` (0x10 arm) | UNSAFE | REJECT | Already tested iter-45 (1560): broke M1, count2 r25→r23 |
| coder1-1250-1 | 1250 | Drop `s32 i` from decl list | UNSAFE | REJECT | Entry-band change |
| coder1-1250-2 | 1250 | Add `Diagram *new_var3` between row4/row5 | UNSAFE | REJECT | Entry-band addition |
| coder1-1265-1 | 1265 | Same as coder1-1250-2 | UNSAFE | REJECT | Entry-band addition |
| coder*-1295-x | 1295 | `s32 i` → `char`/`short`/`unsigned char i` | UNSAFE | REJECT | Entry-band type change on i |
| coder1-1295-1 / coder3-1295-2 | 1295 | `inline_fn` replacing row expr | UNSAFE | REJECT | No-op wrapper hack |
| coder2-1335-1 / coder3-1335-1 | 1335 | `inline_fn(->user_data)` wrapper | SAFE | REJECT | No-op wrapper hack |
| coder2-1340-1 | 1340 | `(hovered_selection*)` type cast + partial sub | SAFE | REJECT | Broken cast semantics |
| coder2-1340-2 | 1340 | `cur += (...)` arithmetic + ptr2 changes | SAFE | REJECT | Arithmetic manipulation hack |
| coder2-1345-1 / coder3-1345-1 | 1345 | ptr2/ptr3 decl reorder | UNSAFE | REJECT | Entry-band reorder |
| coder2-1345-5 / coder3-1345-4 | 1345 | `col_result3 +=` or `row_result3 +=` extra assign | SAFE | REJECT | Spurious extra assignment hack |
| coder2-1355-3 / coder1-1355-1 | 1355 | `cur=data->name_cursor_pos; cur=cur>>8` split | SAFE | BYTE-IDENTICAL | Already tested iter-47/prior: metered 98.46% |
| coder2-1360-x | 1360 | `cur += (...)` arithmetic manipulation family | SAFE | REJECT | Arithmetic manipulation hack |
| coder2-1365-1 | 1365 | `s32 count` → `int count` | UNSAFE | REJECT | Entry-band; already tested prior session |
| coder3-1310-1 | 1310 | `short i` + multiple `inline_fn` replacements | UNSAFE | REJECT | Entry-band + mass inline wrapper |
| coder1-1325-1 | 1325 | `inline_fn` + new `u8 *new_var3` + dead goto hack | SAFE | REJECT | Wrapper + dead-goto semantic hack |
| coder1-1330-1 | 1330 | Multiple: ptr2/row2 decl reorders + `cur += (...)` | UNSAFE | REJECT | Entry-band reorders + arithmetic hack |
| coder1-1335-1 | 1335 | Dead `do {} while(0)` + extra if | SAFE | REJECT | Dead-code insertion hack |
| coder1-1335-2 | 1335 | Extra if blocks + `row6 = hovered_selection` add | SAFE | REJECT | Dead-branch injection |
| coder3-1330-1 | 1330 | `inline_fn(->user_data)` wrappers + `new_var3 = sorted+cur` | SAFE | REJECT | Wrapper + indirect sorted access |
| coder3-1345-2 | 1345 | ptr2 decl position change | UNSAFE | REJECT | Entry-band reorder |
| coder3-1345-3 | 1345 | `u16 new_var3` cast pointer to hovered | SAFE | REJECT | Type-pun pointer hack |
| coder3-1350-1 / coder1-1350-1 | 1350 | `cur += (...)` arithmetic | SAFE | REJECT | Arithmetic hack family |
| coder3-1355-1 | 1355 | `cur += (...)` + `found |= found` | SAFE | REJECT | Arithmetic + no-op OR |
| coder2-1350-2/3 | 1350 | `u16 new_var3` + unsafe 0x10 row split or similar | UNSAFE | REJECT | Entry-band + unsafe zone |

**RESULT: Zero gate-passers in iteration-47. All 30+ candidates rejected.**

### Reject family analysis (new rejection patterns catalogued):

1. **`cur += (...)` arithmetic family** (~8 candidates): Permuter constructs `cur += (expr)`
   followed by removal of the original `cur -= col` or similar subtraction. The combined effect
   is semantically equivalent (net +/- arithmetic preserved) but uses a temporary accumulate
   pattern. All were at token ~187 in the function body. Rejected as arithmetic manipulation.

2. **`inline_fn()` wrapper / `->user_data` wrapper** (~5 candidates): Wrapping `data =
   mnDiagram_804D6C10->user_data` or field accesses in `inline_fn()`. No-op wrapper hack class.

3. **`s32 i` type-change family** (~8 candidates): `char`/`short`/`unsigned char`/`int` for
   the `i` loop variable — all change the entry band. All rejected per M1 guard.

4. **0x10-arm row-split** (re-confirmed): `row = mn_804A04F0.hovered_selection >> 8` →
   `row = hovered; row = row >> 8` in the `is_name_mode != 0` block. This was already
   tested in iteration-45 (score 1560-1) and caused count2 to shift r25→r23 (M1 broken).
   The coder3-1290-1 / coder2-1265-1 candidates are the same change. DO NOT RETEST.

5. **Entry-band decl additions/reorders** (~8 candidates): Various ptr2/ptr3 swaps, new
   `Diagram *new_var3`, `u16 *new_var3` etc. All touch the entry band. All rejected.

6. **goto label relocation** (coder2-1155-1, the "best" score): Repositions `fc_inner:`
   label to a different region of the function — complete semantic break. The very low
   permuter score (1155 vs 1365 base) reflects structural divergence, not proximity to
   the target — a larger byte-diff can be "better" in the permuter's scoring if the two
   sides align differently on the random scoring positions.

### Safe-zone census update (confirmed closed levers):
- Operand-flip class: ONE site (1575 commit), ALL others identical. Closed.
- Dead-anchor band-lift: 0xC00-FIGHTER (1365 commit). The 0xC00-NAME form is banked as walled.
  Safe-zone (post-front/main-nav) band-lifts: ONLY if they don't compete with the front sweep.
- `cur` two-statement split: BYTE-IDENTICAL. Confirmed dead in safe zone.

### Channels remain ACTIVE — no stale-base doctrine (no commit this iteration).

### Driver-9 entry points
1. HARVEST (primary): keep fetching coder1/2/3 (base 1365, jobs 20260611-0439xx). Gate ≥98.45.
   Session-start checklist: `remote status` all 3 jobs → if any stopped/plateaued, re-bootstrap
   from committed source + NULL pragma + verify compile + resubmit. Channel-health check is
   MANDATORY at session start (#558 class: channels die silently from missing NULL pragma or
   stale base).
2. The temp-band pop-order cycles (~40 sites in fc/fr + nc/dn_n/rt_n families) are the
   permuter's ONLY remaining lever. Do NOT build manual interventions for them.
3. Fingerprint map current for 5bf6600e5 (unchanged this iteration).
4. REPORT TRIGGER: 98.5% (unchanged; 98.45 now).

## Iteration-48 (driver 8): targeted macro enumeration built + harvest lands the zero-arg web
lift — 98.45 → 98.62 (REPORT TRIGGER 98.5 CROSSED)
Baseline verified: 5bf6600e5, 98.45, Δ2, hunks 9, opcode 99.1. One source commit:
bcdd2265c (98.62). Docs commit for iter-47: 2ee6c889b.

### TASK 3 — PLATEAU DECISION (executed first; freed the host for TASK 1)
coder1 entryrand: best 1250 @iter11588, latest @iter36218+ = ~24.6k iterations stale,
approaching the 50k threshold with nothing since ~12k. RETIRED (stopped) in favor of the
targeted macro job. coder2/coder3 were healthy (descending) at retirement time.

### TASK 1 — TARGETED MACRO JOB on the found↔row2 temp-band cycle region
First-ever finite enumeration (entry-window style) on this region. Axes derived from the
iteration-46 mechanism map (ig124 found-merge pop 303 vs ig69 row2 pop 355; ig70/71/72
sibling row2s; ig129/145 founds), NOT blind:
- dn_n (7 options): baseline; row2-hoist-before-found; row2-between-found-and-if;
  row2-after-ptr2; row2-interleaved-in-ptr2-derivation; fused `ptr2 = sorted + cur + 0x1C`;
  arg re-read `FindNextName((u8) data->name_cursor_pos)`.
- rt_n (7): same shapes with row2=7 / `>> 8` arg re-read.
- up_n (3): baseline; arg-inline at call; found-before-cur order swap.
- dn_f (7): all 6 orders of the independent head {ptr=sorted+cur; found=FindNextFighter;
  row2=N} + arg re-read variant.
- rt_f (7): same.
Space = 7×7×3×7×7 = 7,203. All variants semantically valid by construction (helpers
read-only; row2 dead outside regions; head statements independent). PERM facts established
(read from src/perm/parse.py + perm.py): comma-split tracks ONLY parens → options may span
`if (...) {` with unbalanced braces; `(,)` escapes commas; seed-0 = first option of every
PERM_GENERAL + identity LINESWAP order → make first options baseline text and the printed
base score IS the doctrine verification. PERM_LINESWAP is blind to dependencies — used
explicit PERM_GENERAL options instead so no invalid orders enter the space.
Job dir: decomp-permuter/nonmatchings/mnDiagram_InputProc_macro/ (sibling dir, own
target.o/compile.sh/settings.toml; settings func_name stays mnDiagram_InputProc).

RESULT ON 5bf6600e5 GRAPH (job ...macro-coder1-20260611-052018, COMPLETED all 7,203):
**best = 1365 @iter1 (the baseline itself); zero candidates below base.** The found↔row2
pop-order cycle is INVARIANT under all 7,203 arrangement/arg-shape/derivation spellings of
its five regions. Wall confirmation far stronger than iteration-46's 3 hand builds. Many
variants byte-identical to base (score exactly 1365) — the cycle igs are insensitive to
these axes. The cycle stays banked as permuter-random-territory; do NOT re-run this exact
space on an unchanged graph.
RE-RUN ON NEW GRAPH (bcdd2265c, base 1235): resubmitted as ...macro-coder1-20260611-053017
(substrate relativity + stale-base doctrine). Result pending at session close — DRIVER-9
MUST CHECK (finite job: it will look stopped when complete; fetch + read best).

### TASK 2 — HARVEST: the zero-arg web lift (coder2 output-1235-1) — COMMITTED bcdd2265c
Pre-commit triage of 6 new old-base candidates: c2-1270-2/c3-1270-2 (family-5 new_var3 +
unsafe row region), c2-1270-3 (families 2+3 multi-hack), c3-1265-1 (family-4 row-split +
comma/dead-code hacks), c3-1270-1 (variable-alias + `- -1` hack) — all tallied REJECT.
**c2-1235-1 = genuinely new shape** (zero-materialization, touches the fusion/zero wall —
not a pre-classified family): in the 0x10 arm,
  `i = 0; proc = HSD_GObj_SetupProc(gobj, ..., i);`  (was `..., 0`)
i is reassigned before any read on every path (verified by mental execution). METERED:
98.62 / opcode 99.4 / Δ1 / hunks 6 — ALL FOUR GATES IMPROVED (Δ 2→1, hunks 9→6).
M1 INTACT: count2 r25 (+048), entry trio r30/r29/r28, frame -128. COMMITTED bcdd2265c.
MECHANISM (new lever class — ZERO-ARG WEB LIFT): MWCC copy-propagates i=0 back into
`li r5,0` at the call (no separate web materializes at the site!) but i's band-lift into
the 0x10-arm head renumbers the fc/fr temp igs downstream: the nc anchor transposition
partially resolved and the old T+848 mr Δ-member CLOSED (Δ2→1; remaining Δ1 = the fusion
+048 extra li). NOTE vs the safe-zone rule: this is an ENTRY-REGION lift that did NOT
displace count2 — the rule's empirical basis (row/cur lifts breaking M1) does not cover
zero-value lifts that copy-prop away at the use site. Refine the rule: entry-region lifts
whose value is copy-propagated into an immediate (no live range across the front sweep)
can be SAFE; lifts that hold a live value across the front remain UNSAFE.

### TASK 2b — post-commit harvest on the new base (channels found below-base fast)
Fresh channels (coder2-052732, coder3-052741, 16t stock each) found 18 below-1235
candidates within ~25 min. Tally: 16 pre-classified family rejects (inline_fn ×4,
type-change ×4, `cur += (...)` ×5, row-split ×2, broken `(hovered*)` cast, entry-decl
new_var3, alias-block `{ptr3=ptr;...}`), 2 known byte-identical (`cur = cur >> 8` split).
**c3-1140-1 (best, -95) = genuinely new**: `row = (u8)(hovered_selection >> 8)` in the
0x10 arm (NOT the iter-47 (u16) test — different width, different graph). METERED:
98.70 / opcode 99.6 / **Δ2 ↑ / hunks 8 ↑ — GATE FAIL** (match+opcode up, structure
regressed; the extra instruction returned). REVERTED. Consistent with the unsafe-zone
trade pattern: 0x10-arm row perturbations buy site wins with front structure. The (u8)
cast variant is now METERED-CLOSED on this graph; do not re-meter.

### Stale-base doctrine executed (after bcdd2265c)
Stopped coder2/coder3 (+ macro had completed). Re-bootstrapped base.c from new source —
**#558 THIRD OCCURRENCE: bootstrap dropped the NULL pragma again**; re-added to line 2,
local verify: base compiles, **new base score = 1235** (exactly the committed candidate's
score — commit landed its codegen byte-for-byte). Resubmitted:
- coder2 random: mnDiagram_InputProc-coder2-20260611-052732 (16t stock)
- coder3 random: mnDiagram_InputProc-coder3-20260611-052741 (16t stock)
- macro re-run: mnDiagram_InputProc_macro-coder1-20260611-053017 (16t, finite 7,203,
  seed-0 verified 1235 locally before submit)
All three verified ACTIVE with correct base scores.

### Wall inventory after bcdd2265c (match 98.62, Δ1, hunks 6, opcode 99.4)
1. Fusion/zero: Δ1 = the +048 extra `li r25,0` (count2 home; target fuses with the
   u64-hi-zero `li` at +03c). count2 r25 ✓. Wall STANDS (unchanged through the commit).
2. lhzu/fr: +168 lhzu-vs-lhz class persists. Wall STANDS.
3. found↔row2 temp-band cycle: **7,203-variant enumeration NULL on old graph** — strongest
   wall evidence in the campaign. Re-run on new graph pending (driver-9 reads it).
4. nc anchor transposition (r27↔r28) + nr-head load-order swap (+0f4): partially shifted
   by the commit; remaining sites are the standing register-only residual (~21 paired
   register-only lines per checkdiff).
5. T+848 mr Δ-member: CLOSED by bcdd2265c.

### Driver-9 entry points
1. READ THE MACRO RE-RUN RESULT FIRST (...macro-coder1-20260611-053017; finite — looks
   stopped when complete; `remote fetch` then read best/candidates). If a below-1235
   candidate exists: triage per rules (M1 guard at meter). If null again: the cycle wall
   is confirmed graph-independent for these axes; retire the macro dir until the NEXT
   graph change, then one cheap re-run.
2. HARVEST coder2-052732/coder3-052741 at cadence. Gate ≥98.62 (Δ1, hunks 6, opcode 99.4
   — the gate tightened with the commit). Six families + (u8)-row-cast are pre-classified;
   tally, don't re-derive.
3. NEW LEVER CLASS to generalize (zero-arg web lift): any harvest candidate inserting
   `var = <imm>; call(..., var)` with var dead-before-read is this class, not a hack.
   Within InputProc the 0x10-arm site was the only literal-0 call arg; likely exhausted
   in-function, but keep the class in triage.
4. coder1 hosts the macro job; when it completes, either re-seed a random job there
   (weight_overrides/randomize_funcs tuning per memory) or leave idle until next commit.
5. Channel-health check (#558) MANDATORY at session start; bootstrap ALWAYS drops the
   NULL pragma (3/3 occurrences) — re-add + local verify before every submit.
6. REPORT TRIGGER: next at 99.0 (98.5 crossed this iteration at 98.62).

### Iteration-48 close-out (results that landed after the section above was drafted)
- MACRO RE-RUN ON NEW GRAPH: COMPLETE, all 7,203 — **best = 1235 @iter6 (base-identical),
  zero candidates**. The found↔row2 cycle is invariant under these axes on BOTH graphs
  (5bf6600e5 and bcdd2265c). Wall = graph-independent for arrangement/arg-shape/derivation
  spellings; 14,406 total variants, two graphs, zero wins. Macro dir RETIRED (keep
  nonmatchings/mnDiagram_InputProc_macro/ for one cheap re-run after the NEXT graph change
  — regenerate its base.c from the new base first via the PERM script pattern in this
  section's git history).
- CODER1 RE-SEEDED (TASK 3 alternative executed): pattern-tuned random channel
  `mnDiagram_InputProc_tuned-coder1-20260611-053754`, weights perm_cast_simple=30 /
  perm_expand_expr=15 / perm_randomize_internal_type=10 (pattern widen-u8-to-u32 via
  spill suggestion; detection used a stale pre-commit pcdump — weights are a search bias,
  not a correctness input). Separate dir nonmatchings/mnDiagram_InputProc_tuned/ so the
  main dir stays STOCK — `permute config` writes into the shared settings.toml and a
  doctrine re-bootstrap would silently keep it (existing-settings-kept behavior); stock
  settings.toml restored in the main dir. Tuned base verified 1235 locally pre-submit.
- FINAL POSTURE: coder1 = tuned random (1235), coder2 = stock random (1235),
  coder3 = stock random (1235). All NULL-pragma-verified.

## Iteration-49 (driver 8): immediate-lift class generalized — head-window live, tail-window
DCE'd; 98.62 → 98.63
Baseline verified: bcdd2265c/ebe72fec6, 98.62, Δ1, hunks 6, opcode 99.4. One source commit:
4e514c1f1 (98.63).

### TASK 1 — COPY-PROPAGATED IMMEDIATE LIFT: generalization table (3 builds, gated)
| Build | Site | Lift | Result | Verdict |
|-------|------|------|--------|---------|
| A | 0x10-arm head, audio(1) | `cur = 1; lbAudioAx_80024030(cur);` | 98.63/99.4/Δ1/6 — match +0.01, rest held, M1 ✓ (count2 r25, li r3,1 copy-propped at +050) | **COMMITTED 4e514c1f1** |
| B | dn_n result block, audio(2) | `row3 = 2; lbAudioAx_80024030(row3);` | byte-neutral (98.63 =) | INERT — reverted |
| C | dn_f result block, audio(2) | `row5 = 2; lbAudioAx_80024030(row5);` | byte-neutral (98.63 =) | INERT — reverted |

CLASS LAW (4 data points): **head-window lifts survive** (i=0 SetupProc committed iter-48;
cur=1 audio +0.01 iter-49) — the lifted band lands before the IRO promotion scan of the
0x10-arm bodies and renumbers downstream temps. **Nav-arm-tail lifts are dead-store
eliminated** (row3 dn_n, row5 dn_f — both byte-neutral): in arm-tail positions the
assignment is copy-propped at the call and the store fully DCE'd before it can mint a band.
Same finding shape as iteration-46's erased same-path anchors. ⟹ The class's usable window
is the ENTRY/HEAD region only (pre-front statements with downstream temp regions); the
0x10-arm head is now occupied by TWO lifts (i, cur). Remaining head-window literal sites:
none (audio(1) and SetupProc-0 were the only literals in the window). CLASS EXHAUSTED
in-function unless a new head literal appears from future restructuring.

### TASK 2 — HARVEST (tuned channel first results + stock finals)
Tuned coder1 (cast/expand/type weights): 16 candidates. The weights bias produced exactly
the predicted family mix — 4 spellings of the SAME 0x10-arm row-site fix, all 1140-1160:
use-site `(u8) row` cast (1140-1), `row = 8; row = hovered >> row` shift-split (1140-2),
`new_var = row` short-alias (1140-3), row-split (1160-1). All score-equal to the
metered-closed (u8) assignment cast (iter-48 gate-fail Δ2/hunks8) — the permuter scorer
rewards the site fix; retail meter shows the structure trade. NOT re-metered (same-site
same-codegen family). Remaining 12: family rejects (entry-decl new_var3 ×4, type-change
×2, cur+=() ×2, ptr alias-block, no-op &&-chain, multi-hacks). NOTE for census: two
candidates MOVED/REMOVED PAD_STACK(64) and scored 1210-1225 (below base!) — the permuter
considers the pad's stack-home shift profitable; retail gates would need the frame intact.
Do NOT chase (diagnostic pad is long-standing baseline; natural-frame-reservation guidance
stands).
Stock coder2 final: 1140-1 (multi-hack alias+no-op), 1165-1/2 (type+alias families) — all
tallied rejects. Stock coder3: best unchanged (the metered (u8) cast).

### TASK 3 — substrate sweep on the 4e514c1f1 graph
- Fusion/zero: +03c li r23 (zero-temp) / +048 extra li r25 (count2 home) — Δ1 unchanged.
  count2 r25 ✓. WALL STANDS.
- nc anchor transposition: +094 addi r28-vs-r27 — STANDS (the +0.01 was elsewhere).
- lhzu/fr: STANDS.
- Macro enumeration RE-RUN on this graph: job mnDiagram_InputProc_macro-coder1-20260611-055405
  (7,203, seed-0 verified 1220 locally). Result pending at write time — see close-out below.

### Stale-base doctrine executed (after 4e514c1f1)
- **#558 FOURTH occurrence**: bootstrap dropped the NULL pragma again (4/4 — fully
  deterministic). Re-added; new base verified compiling, **base score = 1220**.
  Note: the tuned channel's first hit was EXACTLY 1220 — it had independently found the
  cur=1 lift form (or codegen-equivalent) before the deduction landed it. Channel + class
  converged on the same change.
- base.c propagated to _tuned dir; _macro dir rebuilt via the PERM script (asserts passed
  — the new head edit didn't drift the five nav-arm site texts).
- Submitted: macro→coder1 (...-055405), stock→coder2 (...-055415), stock→coder3 (...-055424).
- Tuned coder1 resubmission queued AFTER the macro completes (finite, ~25 min).

### Iteration-49 continued — second commit: the intermediate-copy class (harvest)
**COMMITTED 7a17d3dc5: coder3-055424 output-1190-1** — dn_f found via row5 intermediate-copy:
  `row5 = mnDiagram_FindNextFighter(sorted, cur); found = row5;`
98.63 → **98.67**, opcode 99.4 / Δ1 / hunks 6 all held, M1 ✓. Decoded from full-FILE token
diff (main-body diff missed it: 1095/1125 siblings carried a `volatile unsigned short/char`
HELPER-param hack — REJECT family; 1190-1 was the copy alone. TRIAGE NOTE: always run the
full-file diff — helper/preamble changes hide from main-body-only diffs; the permuter's
`static inline`→`inline static` + dropped-pragma hunks are normalization artifacts, ignore).
CLASS MECHANICS (now 3 variants distinguished):
- fresh-temp copy (`found2 = call; found = found2;`): copy-propagated, byte-identical (iter-46).
- dead-STORE lift (`row3 = 2; audio(row3)` tail positions): DCE'd, byte-identical (iter-49 B/C).
- existing-var copy whose value is CONSUMED (`row5 = call; found = row5;`): PERSISTS and
  renumbers (this win). The variable must have its own web elsewhere (row5/up_f).
GENERALIZATION (3 sibling builds, all byte-neutral → reverted; class is SITE-SPECIFIC):
- rt_f via row6: inert. rt_f via row5: inert. dn_n via row3: inert.
- 1/4 sites live. The dn_f graph position (after the committed head lifts) is what made it
  fire; the sibling sites' bands were already in their stable arrangement.
ALSO METERED THIS PASS: coder2-055415 1125-2 `(short)` cast on the 0x10-arm row site —
98.76 (best match% ever seen) but Δ2/hunks8, M1 INTACT (unlike iter-45's row lifts).
GATE FAIL → reverted. ROW-SITE FAMILY VERDICT (6 spellings metered/scored): every spelling
buys +0.08-0.13pp at +1 instruction/+2 hunks; the missing spelling must fix the site
registers with NO added instruction. Pre-classified; only meter a row-site candidate if
its diff shows NO net instruction insertion.

### Macro enumeration: third graph (98.63/4e514c1f1) re-run — NULL again
Job ...macro-coder1-20260611-055405: all 7,203, best = 1220 @iter28 (base-identical), zero
candidates. THREE consecutive graph-independent nulls (21,609 variants total). The
found↔row2 cycle does not move under arrangement/arg-shape/derivation spellings, period.

### Stale-base doctrine after 7a17d3dc5
- **#558 FIFTH occurrence** (5/5 deterministic; noted on the issue with suggested fix).
- New base verified: **1190** (row5 copy present in base.c).
- Submitted: stock coder2 ...-060955, stock coder3 ...-061005, macro 4th run ...-061014
  (dn_f PERM options REBASED around the committed copy unit {row5=call; found=row5} —
  the graph change is INSIDE the macro's own dn_f region this time, making run 4 the most
  interesting re-test yet; seed-0 verified 1190). Tuned coder1 auto-resubmits when macro4
  completes (background chain).

### Driver-10 entry points
1. Read macro4 result (...061014; finite). Then verify the tuned auto-resubmission landed
   (job id in this session's background output). If macro4 null: FOUR graphs — stop
   re-running the arrangement space entirely; only rebuild it if a commit restructures one
   of the five enumerated regions' control flow (not just bands).
2. HARVEST coder2-060955 / coder3-061005 / tuned-(new) at cadence. Gate ≥98.67
   (Δ1, hunks 6, opcode 99.4). Pre-classified: six families + row-site 6-spelling family
   (meter only no-net-instruction diffs) + volatile-helper-param hacks (full-file diff!).
3. Immediate-lift class: head-window EXHAUSTED (both literals lifted); intermediate-copy
   class: site-specific, dn_f committed, siblings inert. New class instances only via
   harvest.
4. Walls: fusion Δ1 (+048), lhzu, nc transposition (+094), nr-head order — all standing on
   the 98.67 graph. Census drop: 868 differing lines (was inflated by +4-shift artifact),
   match 98.67 / Δ1 / hunks 6 / opcode 99.4.
5. #558: expect the pragma drop EVERY bootstrap (5/5); the doctrine handles it.
6. REPORT TRIGGER: 99.0.

## Iteration-50 (driver 9): macro-4 null confirmed; full harvest pass; ENDGAME ASSESSMENT
Baseline verified: source `7a17d3dc5`, docs `38dda871c`, match 98.67, Δ1, hunks 6, opcode 99.4.
Clean tree. Background chain: macro-4 completed (stopped, 7,203 iters, best = 1190 = base-identical,
zero sub-base candidates). Tuned auto-resubmit did NOT fire (no new coder1 job visible after
macro stop). coder2-060955 / coder3-061005 active, descending.

### TASK 1 — BACKGROUND-CHAIN COLLECTION

#### Macro run 4 (mnDiagram_InputProc_macro-coder1-20260611-061014): NULL (4TH CONSECUTIVE)
Completed all 7,203 variants on the bcdd2265c→7a17d3dc5 graph (the dn_f intermediate-copy
commit was INSIDE the macro's dn_f enumeration region). Best = 1190 @iter4 = base-identical.
Zero sub-base candidates.
WALL CONFIRMATION (definitive): the found↔row2 temp-band cycle is invariant under ALL of:
  - arrangement/arg-shape/derivation spellings for all five nav regions (dn_n, rt_n, up_n,
    dn_f, rt_f)
  - four consecutive graph changes (28,812 total variants across graphs 5bf6600e5, bcdd2265c,
    4e514c1f1, 7a17d3dc5)
  - the committed structural change (dn_f copy) was INSIDE the macro's own region → the
    strongest possible null: graph changes within the enumerated space do not help.
DOCTRINE: do NOT re-run this macro until a commit changes the CONTROL FLOW of one of the
five regions (not just bands/substitution spellings). The arrangement space is exhausted.

#### Harvest triage — coder2-060955 / coder3-061005 (combined pass)
coder2: best 1090 @iter2577; coder3: best 1090 @iter2009. All 30+ candidates triaged.
Full results per reject family:

| Score | Channel | Change | Family | Verdict |
|-------|---------|--------|--------|---------|
| 1090 | c2 | row-split + volatile long pad + audio(col_result3*0) | F4+hack | REJECT |
| 1090 | c3 | row-split + entry new_var3 + indirect hov assign | F4+F5 | REJECT |
| 1115 | c2 | row-split + audio(col_result3*0) | F4+hack | REJECT |
| 1115-2 | c3 | entry-decl mass + row-split | F4+F5 | REJECT |
| 1120 | c2 | row-split + `short row` type change | F4+F3 | REJECT |
| 1155 | c3 | inline_fn(user_data) wrappers | F2 | REJECT |
| 1160 | c3 | dead if-chain + row-split | F4+dead | REJECT |
| 1165 | c3 | `!= (hov*0)` no-op multiply | hack | REJECT |
| 1170-1 | c2 | entry new_var3 + (input&0x10)!=0 + `(0,input&8)` comma | F5+comma | REJECT |
| 1170-2 | c2 | entry new_var3 + gmMain indirect | F5 | REJECT |
| 1170-3 | c2 | dead triple-&&-check | hack | REJECT |
| 1170 | c3 | ptr2/ptr3 decl reorder | F5 | REJECT |
| 1180-1 | c2 | nav cur-split + dead if(data&&data) | hack | REJECT |
| 1180-2 | c2 | dead if(data&&data) + row6-split | hack+F4 | REJECT |
| 1180 | c3 | is_name_mode form + dead if(cur) + cur-split | hack | REJECT |
| 1185 | c2 | new_var=0 arg + dead if(!cur&&!cur) | hack | REJECT |
| 1190-1 | c3 | entry new_var + row6 split | F5+F4 | REJECT |
| 1190-2 | c3 | int new_var2 type change + row4 split | F3+F5 | REJECT |
| 1190-3 | c3 | dead triple-&&-check on row2 | hack | REJECT |
| 1190-4 | c3 | inline_fn + new_var3 + col_result4=7 intermediate | F2+F5 | REJECT |
| 1190-1/2 | c2 | row-split family variants | F4 | REJECT |

**RESULT: ZERO gate-passers. All 30+ candidates rejected per pre-classified families.**
Six families validated again: F2=inline_fn wrapper, F3=type change, F4=row-split-unsafe-zone,
F5=entry-band additions, hack=arithmetic/dead-code/comma hacks. No genuinely new class
appeared in this pass.
NOTE: the found↔row2 INTERMEDIATE-COPY family (iter-49's intermediate-copy class, dn_f
won via existing-var-copy) did NOT appear in this harvest — the sibling sites (rt_f, dn_n
via row3) were already proven inert by generalization builds in iter-49. The class is
site-specific and exhausted at the current graph position.

Tuned auto-resubmit: NOT triggered (no new coder1 job). The macro's completion did not
fire the background chain. Tuned channel needs manual re-seed after any future commit.

### TASK 2 — ENDGAME PORTFOLIO ASSESSMENT

See the ENDGAME section written into CAMPAIGN-STATE below.

### TASK 3 — DEDUCTION ASSIST

No harvest winner this iteration → no generalization builds. Class-exhaustion confirmed
for both immediate-lift (head-window) and intermediate-copy (site-specific, siblings inert).
Zero builds spent.

---

## ENDGAME ASSESSMENT — mnDiagram_InputProc (as of iteration-50, 2026-06-11)
### Status: 98.67%, Δ1, hunks 6, opcode 99.4%

#### (a) Sites remaining by family — wall status and evidence grade

| Family | Sites (CS-only census) | Wall status | Evidence grade |
|--------|----------------------|-------------|----------------|
| Fusion/zero-cluster | ~11 CS + Δ1 (li) | WALLED: class-refusal + range-overlap + const-prop triangle; 8+ spelling classes measured dead on 4+ graphs | DEFINITIVE (closed-mechanism) |
| lhzu/fr-ring | ~15-20 CS + Δ1 (structural) | WALLED: structural — any lhzu spelling adds net instruction, widens Δ1→Δ2 | DEFINITIVE (Δ arithmetic) |
| found↔row2 temp-band cycle | ~12 CS (dn_n+rt_n+dn_f/rt_f) | WALLED: 28,812 variants / 4 graphs / 0 wins; within-arm pop order insensitive to all arrangement/arg/derivation spellings | DEFINITIVE (exhaustive enumeration) |
| nc anchor transposition (+094) | ~6 CS | WALLED: temp-class web (no variable identity), dead-anchor tool cannot reach; permuter-random only | STRONG (tool-limit) |
| nr-head load-order (+0f4) | ~2 CS | WALLED: volatile-pick positional; 3 sessions no lever | STRONG (characterized) |
| Row-site family (+093-0a4 region) | ~6 CS | CONDITIONALLY WALLED: every spelling (6 metered) adds Δ1; only a no-net-instruction form would pass gate | STRONG (6 spellings measured) |
| Scattered B-arm/0xC0-arm/fc-fr remainder | ~40-50 CS | PREDOMINANTLY WALLED: most are cascades of the fusion/lhzu/nc families; ~5-10 genuinely unknown | MODERATE (some unread) |
| PAD_STACK(64) natural reservation | Δ? | OPEN — structural question; 64-byte frame gap not yet explained by natural C | OPEN |

**Total walled sites: ~95-100 of ~101 CS-only census sites.**
**Genuinely free (unknown mechanism, not pre-walled): 5-10 sites.**

#### (b) Realistic harvest-reachable estimate

Non-walled (not behind definitive/strong wall evidence):
- ~5-10 scattered sites in B-arm/0xC0/fc-fr whose blocked-set reads have NOT been done
  on the current graph (these are the 40-50 "scattered" sites minus the cascade fraction)
- The permuter-random channel can reach these only through the random mutation path; no
  manual lever has been found for any of them in sessions 47-50

**Harvest-reachable estimate: +0.05 to +0.15pp** if the random channels find a new class
instance (similar to iter-44's cur=col band-lift, iter-45's operand-flip, iter-46's
0xC00 band-lift, iter-48's zero-arg lift, iter-49's intermediate copy — each +0.01-0.48pp).
The wins are getting smaller because fewer free sites remain.

**Ceiling without cracking a wall: ~98.7-98.8pp** (the ~5-10 free sites represent at most
~0.15pp).

#### (c) What the 99.0 trigger requires

99.0% needs approximately +0.33pp from 98.67% baseline.
At the function's ~895 instruction count: +0.33pp = ~3 additional matched instructions.

**Required families that must move:**
Either (A) crack the fusion/zero-cluster wall (~11 CS + Δ1 = ~+0.2pp), which requires a
C spelling that produces both the u64-conversion-temp pair-half virtuals (for M1 deferral)
AND count2's home-init == the hi-zero node (for fusion) simultaneously — 8 spelling classes
measured dead; OR (B) crack the lhzu/fr wall (~15-20 CS + Δ1 = ~+0.3-0.4pp), which
requires a spelling that produces lhzu at +168 without adding a net instruction — no C
form found through pointer-walk, field-type, or IRO analysis.

**For 99.0: at least ONE wall must crack.** The random permuter has ~100k+ total iterations
against the fusion/zero cluster region without hitting the search target. The probability
of a random hit is low but non-zero.

#### (d) Wall re-prices and what would re-roll them

| Wall | Re-price on graph change | Substrate re-test trigger |
|------|--------------------------|--------------------------|
| Fusion/zero | Would re-price ONLY if a new mechanism class is found (not a spelling variant); all 8 spelling classes have measured death modes | After ANY structural commit that changes the entry window or IRO temp structure |
| lhzu/fr | Would re-price if a commit reduces Δ1 to Δ0 (eliminating the current extra-li debt); with Δ0, a lhzu spelling might be absorb-able | Δ1→Δ0 transition (requires cracking the fusion wall first) |
| found↔row2 | 28,812-variant exhaustive enumeration; only re-runs after a CONTROL-FLOW change to one of the five nav regions, NOT a band/substitution change | After a commit that changes conditional structure of dn_n/rt_n/up_n/dn_f/rt_f arms |
| nc transposition | Re-price if a commit changes the 0x10-arm's temp-region structure (re-numbers the @-temps before the nc walk) | After any 0x10-arm structural change |
| Row-site | The 6-spelling constraint (no net instruction) is architectural; a future commit that reduces overall Δ to -1 (ours shorter) would flip the sign and make the row-site spelling free | Δ1→Δ0→Δ(-1) transition |

**Summary statement for the orchestrator:**
The function is at 98.67% with two definitive walls accounting for ~31 CS sites + 2 structural
lines (~+0.5pp if both crack), plus a fully-enumerated temp-cycle wall (~12 CS, +0.2pp), and
~5-10 genuinely free sites reachable only by random search (~0.1pp).
**The realistic ceiling without a new mechanism class is ~98.7-98.8pp.**
**99.0 requires cracking the fusion wall or the lhzu wall — both have exhausted their
currently-conceived mechanism classes.** The harvest engine should continue running (yield
~+0.01-0.04pp per win at current cadence) but the probability of crossing 99.0 via random
search alone is low. The rational decision point for banking the result is when:
  (1) the random channels have run 150k+ iterations without a win (approaching the
      search-exhausted threshold), OR
  (2) a new mechanism class is proposed (e.g., retro IRO comparison of the pair-half
      virtual creation vs a matched sibling, or a union-type strategy for the fusion).

### TASK 4 — Campaign state updated with harvest log and endgame section (this iteration).

### Driver-10 entry points (REVISED)
1. **Macro-4 is NULL (4 graphs, 28,812 variants)**: retire the macro dir entirely until
   a commit changes one of the five nav regions' CONTROL FLOW. Macro re-runs on band/
   substitution changes are provably wasted.
2. **Tuned coder1 NOT auto-resubmitted**: manually re-seed the tuned channel after any
   future commit (the background chain did not fire). Template: bootstrap from committed
   source → add NULL pragma → local verify → submit with perm_cast_simple=30 weights.
3. **Harvest coder2-060955 / coder3-061005** at cadence. Gate ≥98.67 (Δ1, hunks 6,
   opcode 99.4). Pre-classified families: F1=row-split-0x10-arm, F2=inline_fn,
   F3=type-change, F4=row-split-unsafe, F5=entry-band, F6=arithmetic/dead/comma hacks.
   Meter ONLY candidates with no pre-classified family token AND no net instruction change.
4. **Portfolio decision**: as documented in the ENDGAME section — 99.0 requires a wall
   crack; the harvest engine is valid but expected yield is +0.01-0.04pp per win.
   Run until 150k+ iterations without win, then bank and report.
