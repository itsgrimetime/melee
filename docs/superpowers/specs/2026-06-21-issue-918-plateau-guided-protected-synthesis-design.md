# Issue 918 Plateau-Guided Protected Structural Synthesis

## Problem

Issue 917 made `debug select-order-search` report a protected structural plateau:
the Sort exact-register frontier preserves `IG34->r27` and `IG44->r25`, but
bounded guard repair cannot reduce `normalized_diff_lines` below 53. The next
matcher tried the obvious follow-ups:

- a wider protected guard-repair rerun;
- inline-boundary structure search;
- `debug search combine` over the lower-drift and preserving retained sources.

The combine run produced scored candidates, but it did not summarize the
protected structural outcome: lower-drift candidates lost the protected
assignments, and preserving candidates stayed at ndiff 53. The matcher still had
to inspect score JSON manually.

## Goal

Extend the existing pairwise `debug search combine` lane so a plateau-guided
run can answer the protected synthesis question directly:

- accept required protected assignments and a structural ndiff target;
- rank recombined retained sources by protected preservation and structural
  drift;
- report candidate-found when a recombine preserves all requested assignments
  and beats the ndiff target;
- otherwise emit a terminal component-subset summary explaining which candidate
  families preserved protected hits, which lower-drift candidates lost them, and
  which overlapping hunks still need manual subhunk ranges.

Also fix the `select-order` coverage metadata so `truncated_by_max_probes` is
only true when the generated guard-repair entries actually reach the probe cap.
Depth exhaustion with fewer generated probes is bounded exhaustion, not max-probe
truncation.

## Design

Add optional `debug search combine` inputs:

- `--protect-assignment IG:PHYS` repeatable, reusing the existing assignment
  parser used by `debug search minimize`;
- `--max-normalized-diff-lines N` for the structural target, where issue 918
  uses `52` to mean "below the ndiff 53 plateau";
- `--source-component NAME` repeatable for carrying plateau component names into
  the synthesis summary.

When these options are supplied and a score command returns JSON, build
`protected_structural_synthesis`:

1. Parse each ok combination's `score_result.parsed_json`.
2. Determine protected preservation from either `proof_assignments.satisfied` or
   `target_score.virtuals`.
3. Read `structural_guard.normalized_diff_lines`.
4. Treat an ok combination as evaluable only when the score command succeeds
   and emits JSON with `structural_guard.normalized_diff_lines`.
5. Sort candidates by full preservation, lower ndiff, missing protected count,
   lower target score total, and stable candidate id.
6. If any candidate preserves all protected assignments and has ndiff less than
   or equal to the requested maximum, report `status="candidate-found"`.
7. If no candidate is found but any ok combination lacks score coverage, report
   `status="incomplete-score-coverage"` with the unevaluable candidate ids.
8. Otherwise report `status="terminal-component-subset-exhausted"` for the
   attempted pairwise component subset with: preserving plateau candidates,
   lower-drift candidates that lost protected assignments, skipped
   overlap/invalid pairs, source components, blocker labels, and next actions.

The summary lives alongside the existing `terminal_summary`. It does not replace
the overlap-only terminal summary because a combine run can have both scored
combinations and skipped overlap pairs.

## Tests

Add focused tests before the production changes:

- `debug search combine` emits terminal protected synthesis when the only
  lower-ndiff candidate loses protected assignments and the preserving candidate
  plateaus;
- `debug search combine` emits candidate-found when a preserving recombine meets
  the ndiff target;
- `debug search combine` reports incomplete score coverage instead of terminal
  exhaustion when protected synthesis is requested without usable score JSON;
- target-score virtuals are accepted as protected-assignment evidence when
  proof assignment entries are absent;
- select-order composition coverage reports `truncated_by_max_probes=false` when
  entries are below `max_probes`, and still reports true when entries reach the
  cap.
