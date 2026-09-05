# Issue 1014: Sort Lower-Drift Init-Lifetime

## Problem

The corrected `mnDiagram_SortNamesByKOs` protected-loss terminal identified a
new next source lever: preserve the IG44 predicate/local-copy block while
changing only the IG34 initialization name-byte/KO-total materialization. The
source-model synthesis path did not recognize that terminal text, so it
regenerated the older Sort candidate families and gave no explicit blocker when
the required IG44-preserving seed was unavailable.

Retained-frontier triage also ranked some stale route-only or estimated
continuation metadata ahead of the concrete protected-loss terminal, which
could send matcher agents back toward already-exhausted recombination lanes.

## Plan

1. Add a dedicated `sort-protected-loss-init-lifetime` source-model dimension
   that is narrowly gated on the lower-drift terminal language.
2. Seed that dimension from concrete IG44-preserving terminal candidate source,
   then generate bounded init-lifetime variants that preserve IG44 and attempt
   to recover IG34.
3. Emit a clear zero-candidate blocker when the terminal asks for this lever but
   no usable IG44-preserving source seed is materialized.
4. Require scored rows for this dimension to jointly preserve IG44/r25 and
   recover IG34/r27 before they are actionable.
5. Give concrete protected-loss terminal evidence priority over stale or
   estimated continuation metadata in retained-frontier suppression and next
   source-model ranking.

## Verification

Regression coverage exercises lower-drift generation, missing-seed blockers,
joint-assignment classification, and retained-frontier suppression/ranking for
concrete protected-loss terminals over stale estimated continuations.
