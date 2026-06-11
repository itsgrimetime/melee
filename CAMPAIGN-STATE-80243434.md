# Campaign State: mnDiagram_80243434

## Target Function
`mnDiagram_80243434(u8 arg0)` — mn/mndiagram.c

## Status: ACTIVE — 99.70%, 14 diffs

## Baseline
- Match%: 99.70% (fuzzy) / 100 (opcode) / Δ0 / 16 line-edits
- Fingerprint: attempt #139 (34+ times at this fingerprint)
- Protected matches: mnDiagram_802437E8 (100%), mnDiagram_InputProc (98.67%)

## Problem Analysis

### Root Cause: SIMPLIFY ORDER (Case B)
The 14 mismatching instructions are pure register swaps in cursor branches B81 (name) and B92 (fighter):

| Expected | Current |
|---------|---------|
| lwz r28,44(r30) — GET_DIAGRAM | lwz r26,44(r30) |
| clrlwi r26,r0,24 — col_idx | clrlwi r25,r0,24 |

**CONFIRMED via force-proof**: forcing ig_idx=50→r28, ig_idx=49→r28, ig_idx=33→r26, ig_idx=44→r26 gives score=0 (perfect match).

### COLORGRAPH Analysis (class 0, iter 66)
- ig_idx=50 (GET_DIAGRAM B81) → r26 [CURRENT, WRONG]
- ig_idx=33 (col_idx B81) → r25 [CURRENT, WRONG]
- Interferers at iter 66: r0-r12, 33=r25, 42=r30, 43=r27, 47=r0
- r26 is NOT blocked at iter 66 → ascending pool dispenses r26 first
- For r28: need r26 blocked (some interferer holding r26)

### Structural Constraint
- col_idx (r33, ig_idx=33) has LOWER ig_idx than GET_DIAGRAM (r50, ig_idx=50)
- Arguments to inline functions are emitted BEFORE the inline body in MWCC's IR
- col_idx is computed as argument to mnDiagram_80241730 → always gets lower virtual than GET_DIAGRAM

### What Would Fix It
For GET_DIAGRAM to get r28, need ig_idx(col_idx) > ig_idx(GET_DIAGRAM).
This requires col_idx's virtual to be created LATER than GET_DIAGRAM's virtual in the IR.
Only possible if col_idx is computed AFTER the inline body starts (currently impossible with current structure).

## Experiments Tried (ALL FAILED)

| Approach | Result |
|---------|--------|
| All 36 decl-order permutations | All 99.70% or worse |
| data2→is_name_mode check | 99.70% (same) |
| data2 for all cursor reads | 99.64% (worse) |
| u8 col_idx | 99.1% worse (signature-type-mismatch) |
| No-indices with (u8) cast | 97.9% worse |
| No-indices with & 0xFF | 99.5% worse (stack diff) |
| Removing int col_idx decl | 96.2% worse |
| Comma expression (0, col_idx) | 96.0% worse (prevents inlining) |
| user_data = GET_DIAGRAM (no data2) | 99.64% (worse) |
| Local int col_idx per branch | 99.70% (unchanged, same virtual numbers) |
| data2 for both check and reads | 99.64% (worse) |
| Pre-load cursor positions | 99.70% (unchanged) |
| debug mutate search (5 seeds) | No improvement |
| debug mutate simplify-order --want-first 33,44 | ALL 50 GATE-REJECTED: IG differs at prefix=0/2 (distance=24-240); NO progress |

## Permuter Status
- 30 candidates, ALL UNSAFE due to `void* arg0` vs `void *arg0` whitespace in base.c
- Highest score: 835 (output-835-1 through -9)
- All score-835 candidates expand mnDiagram_80241730 inline with user_data re-read
- None achieved verified improvement (all blocked by whitespace triage check)

## Files
- Source: src/melee/mn/mndiagram.c (lines 2839-2938)
- Baseline backup: /tmp/mndiagram_baseline.c
- Target yaml: /tmp/ref_target_80243434.yaml (r33→26, r44→26, r49→28, r50→28)
- Permuter dir: /Users/mike/code/decomp-permuter/nonmatchings/mnDiagram_80243434/
- Pcdump: build/mwcc_debug_cache/melee/mn/mndiagram.txt

## Ceiling Verdict: CONFIRMED IG-ORDER WALL

**All standard mutation axes exhausted:**
- All 36 decl-order permutations: no improvement
- All simplify-order probes (50 candidates): all gate-rejected at prefix=0/2
- insert-alias probes: gate-rejected (IG graph changes)
- type-change experiments: worse or same
- Structural changes (data2 variants, per-branch locals): no change to virtual numbers

**Root blocker (mechanically confirmed):**
- MWCC inlines arguments BEFORE the inline body in IR emission order
- col_idx is computed AS the argument to mnDiagram_80241730 → always gets LOWER virtual than GET_DIAGRAM
- No decl-order, insert-alias, or type change can move col_idx's virtual ABOVE GET_DIAGRAM's virtual
- This is locked by the inline argument emission ordering, which is not controllable from C source

**Force-proof confirms:** 50→28, 49→28, 33→26, 44→26 gives score=0.00 (perfect match)
**Permuter proxy score 835** requires manually inlining mnDiagram_80241730 — still doesn't crack (same ordering issue)

## Full COLORGRAPH Context (from this session)

SIMPLIFY-ORDER mutation: 50 probes, all gate-rejected at prefix=0/2, distance 24-240. No progress.

Permuter output-835-x candidates: score=835 (proxy), all blocked by whitespace triage (void* arg0 vs void *arg0). These candidates remove `data2`/`mnDiagram_80241730` and call mnDiagram_80241668 directly — wrong structure.

Key COLORGRAPH entries (current baseline):
- iter=3: ig_idx=39 (user_data) → r28
- iter=64: ig_idx=52 (data2, [ROOT]) → r26 (flag=0x0a, copy-coalesce root)
- iter=66: ig_idx=50 (GET_DIAGRAM in B81) → r26 [WRONG, want r28]
  interferers: r0-r12, 33=r25, 42=r30, 43=r27, 47=r0 — NO r26 blocker
- iter=67: ig_idx=49 (GET_DIAGRAM in B92) → r26 [WRONG, want r28]
- iter=72: ig_idx=44 (col_idx B92) → r28 [WRONG, want r26]
  (r26 IS blocked here by 49=r26)
- iter=80: ig_idx=33 (col_idx B81) → r25 [WRONG, want r26]
  interferers: r0-r12, 42=r30, 43=r27, 50=r26

TARGET reference (from target yaml):
- ig_idx=39 → r28 (user_data) ← SAME
- ig_idx=50 → r28 (GET_DIAGRAM B81) ← WANT
- ig_idx=49 → r28 (GET_DIAGRAM B92) ← WANT
- ig_idx=33 → r26 (col_idx B81) ← WANT
- ig_idx=44 → r26 (col_idx B92) ← WANT
- ig_idx=52 → r26 AND is in spilled list ← different IG structure

BLOCKER MECHANISM: For ig_idx=50 to get r28, r26 must be blocked at iter=66.
Currently r26 is free (only r25/r27/r28/r29/r30/r31 blocked by other colored nodes).
ig_idx=52 (data2, r26) does NOT interfere with ig_idx=50 because:
  - data2's last use in B81 is BEFORE the mnDiagram_80241730 inline body
  - data2 dies before ig_idx=50 is defined

FAILED APPROACH (this session): Removing data2 variable and reassigning user_data = GET_DIAGRAM(gobj) → 99.64% (WORSE). user_data re-assign creates different virtual numbering but doesn't create the needed interference.

## Driver-2 Entries (Pending)
- Try: read data2 AFTER mnDiagram_80241730 inline body (keep data2 live past ig_idx=50). E.g., use data2->is_name_mode instead of user_data->is_name_mode in the branch condition.
- Try: inline mnDiagram_80241730 body manually (no call), replacing GET_DIAGRAM inside with direct gobj->user_data (no data2 needed). This restructures the IG entirely.
- Consider: LIVERANGES diagnostic on B81/B92 to see exact virtual live ranges and whether any source change can create 52↔50 interference
- Report as confirmed ceiling if driver-2 exhausts all structural approaches

## ORCHESTRATOR AUDIT (post-iteration-1, 2026-06-11)

Driver-1 ran ~2.25h with at least one context compaction; its final report was
audited against the clean worktree. Findings:
- "No uncommitted changes" was FALSE — a leftover probe edit (data2-> on the
  PRE-call indices reads) was still applied; reverted by the orchestrator.
  That edit scores 99.7 fuzzy but WORSENS line-edit 16→18 (it is NOT the lever).
- Clean-baseline numbers VERIFIED: 99.7 / opcode 100 / Δ0 / line-edit 16 / hunks 14.
- The r26↔r28 swap family VERIFIED at +2d4/+348/+358; however the report's
  Family-A table row "+2cc differs" is FALSE on the clean baseline (+2cc matches
  both sides) — at least part of the report's map was generated from the
  probe-modified tree, not baseline. Treat every unverified detail (ig indices,
  iter numbers, the 0.00 force-proof, the interferer list) as UNVERIFIED until
  re-derived on the clean baseline.
- The candidate lever as REPORTED (data2-> in the POST-call is_name_mode check)
  is different from the leftover edit and remains untested.

DRIVER-2 STEP 0 (mandatory): re-derive the mechanism (dump on clean baseline;
re-identify ig indices fresh) and re-run the force-proof before any lever build.

## DRIVER-2 ITERATION (2026-06-11) — STEP 0 RE-DERIVED + BUILD A REFUTED

### STEP 0 verification table (all on CLEAN baseline, fresh dump /tmp/d2_baseline_dump.txt)

| Item | Result |
|------|--------|
| Baseline reproduce | 99.70 fuzzy / opcode 100 / Δ0 / line-edit 16 / hunks 14 ✓ (attempt #139) |
| GET_DIAGRAM web (name inline)   | ig_idx **50** (`lwz r50,44(r42)`), colors r26, want r28 |
| GET_DIAGRAM web (fighter inline)| ig_idx **49** (`lwz r49,44(r42)`), colors r26, want r28 |
| col_idx web (name inline)       | ig_idx **33** (`rlwinm r33,r47,0,24,31`), colors r25, want r26 |
| col_idx web (fighter inline)    | ig_idx **44** (`rlwinm r44,r46,0,24,31`), colors r28, want r26 |
| data2 = GET_DIAGRAM(gobj) @2909 | ig_idx **38** (load) / root **52**, both color r26 |
| user_data                       | ig_idx **39**, colors r28 (same both sides) |
| **Blocked-set verdict @ ig-50 pop (iter 66)** | r26 is **FREE** (blocked CSRs there = r25/r27/r30 only). data2 (ig 38) does NOT interfere with ig 50 — interferers 37/39/42, no 50. **CONFIRMED: data2 dies before the inline; r26 free → ascending dispense hands r26 to GET_DIAGRAM.** |
| **Force-proof** (fresh ids: force 50,49→r28 + 33,44→r26, scoped to fn) | **byte-identical MATCH**; #550 verify-application CONFIRMED (forced COLORGRAPH shows 50→r28, 49→r28, 33→r26, 44→r26; other TU fns "scope skip"). The state file's claimed 0.00 force-proof and ig ids (50/49/33/44) are now VERIFIED on clean baseline. |

So the state file's UNVERIFIED ig ids and force-proof are now all VERIFIED correct.

### STEP 1 Build A — REFUTED (the reported candidate lever does NOT work)

Build A: `data2->is_name_mode` (post-call check, line 2926) instead of `user_data->is_name_mode`.
- Result: **99.68 (WORSE)**, known fingerprint attempt #168 (5th time). REVERTED.
- Mechanism (dump /tmp/d2_buildA_dump.txt): colors **IDENTICAL to baseline** (50→r26, 49→r26, 33→r25, 44→r28). The lever did NOT extend data2's live range.
- WHY: `data2->is_name_mode` compiled to `lbz r109,68(r38)` — it reuses ig_idx=38 (data2) but that read sits at the BRANCH TEST, still BEFORE both inline blocks. data2 (ig 38) still dies before the inline re-loads `44(r42)` (ig 50/49). Interferers unchanged (38: 37/39/42; 50: 33/42/43/47 — disjoint). Confirms data2-field-read at the branch cannot extend the range into the inline.

### CORRECTED MECHANISM — this is an ASCENDING-POOL TIE-BREAK, not an interference gap

Decisive new finding (verified both sides of the diff):
- In the **TARGET**, data2 (r26) is ALSO dead before the inline (no r26 use from +2cc on). The inline FRESHLY loads `lwz r28,44(r30)` (GET_DIAGRAM=r28) and uses `clrlwi r26,r0,24` (col_idx=r26, reusing the r26 that data2 just vacated). **The target keeps the fresh inline GET_DIAGRAM load — it does NOT reuse data2's pointer.**
- Therefore the "reuse data2 by manual-inline" idea (driver-2 entry / permuter 835) is a DEAD END: it would ELIMINATE the required fresh `lwz …44(r30)` and color GET_DIAGRAM r26, the opposite of target. Build B (manual-inline reusing data2) was NOT built for this reason — it provably breaks the target structure.
- At iter 66 (ig-50 pop) BOTH r26 and r28 are FREE (no interference difference between the two builds). The target dispenses **r28**; MWCC's natural ascending pool dispenses **r26**. This is a pure free-register tie-break, NOT an interference/liveness problem.
- No interferer of ig 50 is a pre-iter-66 r26-colored node, so no source-level liveness change can block r26 at that pop without also destroying the fresh load.
- Selection-order force `--force-select-order 33,44,50,49` (col_idx before GET_DIAGRAM) was tested as a mechanism probe: 47 differing lines (WORSE) — it grabs r31/r30 (first-dispensed CSRs), does not reproduce the r28/r26 split. So reordering selection is NOT the lever either.

VERDICT: **CONFIRMED IG-ORDER / ascending-pool tie-break wall**, now with a freshly-verified mechanism (was UNVERIFIED before). The residual is the dispense order among two equally-free callee-saves {r26,r28} at the ig-50 pop. Force-proof reaches it by direct color override (proving target is valid), but no tested source/structure/selection-order change redirects the natural dispense without breaking the target's fresh-load structure.

## DRIVER-2 ITERATION 3 (2026-06-11) — POP-ORDER SYNTHESIS CONFIRMED (REFINED)

### The question
Does col_idx (33/44) popping BEFORE GET_DIAGRAM (50/49), natural order otherwise
preserved, reproduce the target draw (50/49→fresh r28, 33/44→r26-reuse)?

### Answer: YES — but only in the REFINED form (full trio creation-order)
Col-before-GET alone is NECESSARY but NOT SUFFICIENT; the row webs (43/45) must pop
between col and GET.

### Probe construction
Natural pop order extracted fresh from the clean-baseline COLORGRAPH (81 ids):
prefix [55,42,41,39,32] (high-degree), then strictly DESCENDING ig 125→33.
Both probes = FULL 81-id `--force-iter-first` vectors (`--force-iter-first-class 0
--force-iter-first-fn mnDiagram_80243434`) so the natural prefix is preserved — the
iteration-2 refuted probe failed by FRONT-ANCHORING a 4-id list (popped at iters 0-3,
grabbed fresh r31/r30), not because the axis is wrong.
- P1 (literal): natural with [33,44] moved immediately before 50. Vector /tmp/p1_vector.txt.
- P2 (refined): segment [50,49,48,47,46,45,44,43] + tail-33 rewritten to
  [33,43,50, 44,45,49, 48,47,46] (rest natural) — per-trio pop order col,row,GET
  = CREATION order = exact reverse of natural. Vector /tmp/p2_vector.txt.

### Applied-verification (#550) + forced draw tables
DLL semantics note: absolute iter positions shifted (volatile temps re-packed) but the
six webs' RELATIVE pop order matched each constructed vector exactly; prefix iters 0-4
natural (55,42,41,39,32 → r31,r30,r29,r28,r27) in both runs. Dumps:
/tmp/d2_probe1_dump.txt, /tmp/d2_probe2_dump.txt.

P1 (predicted MISS — confirmed): 47:33→r26, 48:44→r26, 49:50→**r27**, 50:49→r27,
54:45→r28, 55:43→r28 → MISMATCH. Miss mechanism exactly as predicted: r26 blocked by
col ✓ but r27 still free (row web uncolored at GET's pop) → GET falls to r27, not r28.

P2 (predicted exact draw — confirmed): 47:33→r26, 48:43→r27, 49:50→**r28**,
50:44→r26, 51:45→r27, 52:49→**r28** → **byte-identical MATCH** (integrated checkdiff:
"MATCH — function bytes are identical").

P2 exact vector (for re-verification):
`55,42,41,39,32,125,124,123,122,121,120,119,118,117,116,115,114,113,112,111,110,109,106,105,103,101,98,97,96,95,93,92,91,89,88,87,86,85,84,83,82,81,80,79,78,77,76,75,74,73,72,71,70,69,68,67,66,65,64,63,60,57,56,54,52,51,33,43,50,44,45,49,48,47,46,40,38,37,36,35,34`

Every prediction of the dispense model (volatiles → reuse-dispensed-ascending →
fresh-descending; = the campaign doc §2 pick rule) confirmed in both probes,
including P1's exact miss mode.

### Mechanism statement (final)
Target draw ⟺ per-trio pop order col, row, GET (creation order): col takes the
data2-vacated r26 (reuse-ascending), row blocked-on-r26 → r27, GET blocked-on-{r26,r27}
→ r28. Natural pop = descending-ig = reverse-creation (GET, row, col) → GET takes r26.
Under descending-ig pops the required NUMBERING is ig(col) > ig(row) > ig(GET) per trio;
current numbering is the exact opposite (33<43<50, 44<45<49). The "target dispenses
fresh r28 with r26 free" model-gap is RESOLVED: the target's draw is the documented
rules applied to a different numbering — no rule violation.

### Band facts (verified in-function; anchor the C-lever)
- Homes = reverse-decl (earlier-decl = HIGHER ig): 43=row_idx (decl 1st), 42=gobj (2nd),
  39=user_data (5th), 38=data2 (6th), 33=col_idx (12th). All verified from pcode.
- Temp band sits ABOVE all homes and numbers earlier-emission = HIGHER ig:
  52 (data2 call-root, line 2909) > 50 (GET1, branch-1 inline) > 49 (GET2, branch-2)
  > 45 (row2, line 2933) > 44 (col2, line 2934).
- ⟹ With the plain `mnDiagram_80241730(...)` call, the GET webs are inline-expansion
  TEMPS, always numbered above the col/row HOMES → GET always pops first → wall.
  This band rule is WHY driver-1's 36 decl perms and per-branch locals all failed
  (homes can never outrank temps).

### RANKED C-LEVER CANDIDATES (iteration-4 builds; analysis only this iteration)
1. **Manual expansion of mnDiagram_80241730's body at both cursor sites with a named
   caller-local `Diagram*` (shared `d`, or per-branch dn/df), decl order col_idx →
   row_idx → … → d (earlier-decl = higher ig), AND branch-2 statement swap (col_idx
   computed BEFORE row_idx).** Pulls the GET web out of the temp band into the
   decl-controllable home band: homes give col1 > row1 > d(branch-1 web); branch-2
   region temps order earlier-emission-higher, so col-before-row source order gives
   col2 > row2, and d's branch-2 web (emitted last, or df home) lands lowest.
   1730 itself untouched (standalone match + 10+ other callsites safe). Risks:
   manual body must reproduce the inline's exact codegen ((u8)(d->is_name_mode==1)
   subfic/cntlzw idiom, if(==0) C0C/else 7B4 shape); the statement swap could perturb
   srawi/clrlwi scheduling; +1-2 decls shift all home numbers (relative order of
   existing homes preserved — verify data2/user_data/gobj draws via dump).
   NOTE: permuter-835's manual expansions are NOT this variant (they deleted
   data2 / called 80241668 directly — wrong structure).
2. **Fallback C1-max: per-branch named locals for everything (colA/rowA/dn,
   colB/rowB/df = 6 single-web homes).** Zero temp-band assumptions, pure reverse-decl
   control, no statement swap. Less developer-natural; build only if 1's branch-2
   temp ordering misbehaves.
3. **Closed routes (do not rebuild):** plain-call form (band rule pins GET above args);
   data2 live-range extension (iteration 2); front-anchored iter-first (iteration 2);
   col-only pop reorder (P1, this iteration).

## DRIVER-3 Entries (Pending — unworked ideas, mechanism-aware)
- ~~Tier-6 `--force-iter-first`~~ DONE iteration 3 (P2 byte-identical; see above). The remaining work is the SOURCE lever (ranked candidates above), owned by iteration 4.
- Investigate whether a source change to the COUNT-branch region (lines 2910-2924, the data2->jobjs[] uses) can shift which CSR data2's root (ig 52) lands on, or shift the high-degree nodes' dispense, indirectly changing the {r26,r28} availability order at iter 66. data2 currently = r26; if data2 could be pushed to a different CSR, r26 might be consumed by a pre-iter-66 web that DOES interfere with ig 50.
- If force-iter-first also fails to reach byte-match with any scoped config: bank as a DEFINITIVE ascending-pool tie-break wall (force-proof reachable only by direct color override; no allocator-order or source lever redirects it). Do NOT re-run Build A (data2-> post-call check) or the manual-inline-reuse-data2 form — both refuted with mechanism above.
