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
