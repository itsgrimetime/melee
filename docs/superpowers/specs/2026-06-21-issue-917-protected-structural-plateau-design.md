# Issue 917 Protected Structural Plateau Summary

## Problem

The protected guard-repair lane can now preserve protected force-phys hits across
bounded structural repair probes, but a matcher still has to inspect the ledger
manually when all preserving candidates plateau at the seed structural drift. For
`mnDiagram_SortNamesByKOs`, the post-916 seed keeps `IG34=r27` and `IG44=r25`.
The follow-up guard-repair run preserves both hits in several candidates, but no
candidate reduces `structural_guard.normalized_diff_lines` below 53.

## Goal

Expose a terminal, source-actionable plateau summary in
`debug select-order-search` guard-repair JSON:

- identify the best full-protected seed;
- rank preserving repair candidates by structural drift;
- report the bounded stop condition from the guard-repair ledger;
- name source components visible in seed and repair hunks, such as pointer-walk
  stores, condition temps, loop index declarations, max-index placement, and
  direct global destination use;
- only declare a plateau when no full-protected repair candidate improves below
  the protected seed drift.

## Non-Goals

This does not add another search family or change the existing
protected-complement lane. It summarizes evidence already present in ranked
variants and guard-repair ledgers so the next matcher can decide whether to
manually recombine source hunks or report a truly irreducible blocker.

## Design

Add a small helper next to the guard-repair summary code:

1. Normalize optional guard-repair ledgers from mappings or paths, reusing the
   same bounded stop metadata shape as composition coverage.
2. Select seeds that satisfy every requested force-phys target and have a
   numeric `normalized_diff_lines`.
3. For each seed, collect repair candidates for that seed whose protected
   preservation counts are complete, whose lost-protected map is empty, and
   whose preserved/achieved registers explicitly match every requested
   force-phys target. Missing preservation metadata is not enough.
4. If a preserving repair candidate has `normalized_diff_lines` below the seed,
   omit the terminal plateau summary for that seed.
5. Only emit terminal plateau when the guard-repair ledger proves bounded
   exhaustion (`depth-exhausted`, `frontier-empty`, or `no-repair-probes` after
   normalization). Missing ledgers, summary-only candidates, and timeout ledgers
   do not get terminal wording.
6. Otherwise emit `protected_structural_plateau` with:
   `status=terminal-plateau`, `terminal_blocker=protected-structural-plateau`,
   seed and best-preserving candidates, `required_normalized_diff_lines_below`,
   ledger coverage, attempted replacements, source components, and blockers.

`source_components` entries include a normalized component name, evidence kind,
candidate label, source path, chain, and a compact hunk/provenance excerpt.

## Tests

Add focused unit tests for `_select_order_guard_repair_summary`:

- plateau case: full protected seed at ndiff 53, bounded ledger exhausted, best
  preserving repair also at ndiff 53, and a non-preserving ndiff 52 candidate
  that must not count as progress;
- improvement case: a full-preserving repair at ndiff 52 suppresses the terminal
  plateau report.
