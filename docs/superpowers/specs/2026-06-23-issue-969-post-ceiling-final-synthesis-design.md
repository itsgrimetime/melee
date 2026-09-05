# Issue 969: Post-Ceiling Final Synthesis

## Problem

Post-ceiling baseline escape can now generate broad Draw and Sort baseline
probes, score them, and derive second-generation continuation routes. The issue
queue shows one remaining gap: after retained-frontiers triage has already
consumed the baseline-escape and continuation route outputs, the baseline-escape
classifier can still loop.

Two concrete failures drive this design:

- `mnDiagram_DrawCellNumber` has an `all-known-frontiers-exhausted`
  retained-frontiers aggregate with a terminal
  `post-ceiling-baseline-escape-continuation` frontier, but baseline escape
  still re-emits the same select-order continuation routes.
- `mnDiagram_SortNamesByKOs` reaches a stable terminal, but the terminal
  continuation summary loses the logical force map. The score rows still carry
  `target_score.virtuals` for IG34 to r27 and IG44 to r25, but
  `final_force_phys` becomes `{}` and the blockers degrade to
  `candidate-force-map-empty`.

## Goals

- Consume retained-frontiers aggregate closure evidence inside the
  baseline-escape classification flow.
- Do not re-emit post-ceiling continuation routes once the retained-frontiers
  aggregate says that continuation family is exhausted for the function.
- Preserve logical force maps from the strongest available source:
  normalized evidence, scored `target_score.virtuals`, scored
  `expression_score.virtuals`, or a continuation summary that already carried
  them.
- Report a stable terminal synthesis with residual blocker targets when every
  known frontier and continuation lane has been exhausted.
- Keep the change reusable for Draw and Sort without adding a new CLI command.

## Non-Goals

- Do not invent new source transformations for Draw or Sort.
- Do not change retained-frontiers ranking semantics.
- Do not make `debug solve allocator-ceiling` consume retained-frontiers
  aggregates in this patch. This fix belongs in the baseline-escape final
  classifier because it has the generated candidate IDs and score rows needed
  to decide whether route closure is stale or final.

## Approaches Considered

### A. Add a separate final-synthesis CLI command

This would make the workflow explicit, but it would require matcher agents to
learn and invoke another command after baseline escape. It also duplicates
classification data already present in `baseline-escape`.

### B. Teach allocator-ceiling solve to read retained-frontiers aggregates

This fixes one reported papercut, but allocator-ceiling does not know the
baseline-escape candidate IDs, scored route outputs, or continuation family
state. It would either under-report route closure or need to import too much of
the baseline-escape classifier.

### C. Integrate final synthesis into baseline-escape classification

Baseline escape already normalizes allocator, retained-frontiers, supplemental,
and score evidence. Extending that flow lets the tool suppress only the
continuation families that the aggregate already closed, while preserving normal
source-actionable output for fresh score progress.

Chosen approach: C.

## Design

`_normalize_evidence` will retain more than the top-level
retained-frontiers status. For the requested function it will summarize:

- whether `next_frontier` is absent;
- terminal frontier rows by `family_id`, `kind`, `status`, and
  `terminal_reason`;
- closed post-ceiling continuation families; and
- non-terminal residual frontier rows that explain why the final terminal still
  has residual blockers.

`generate_baseline_escape_candidates` will continue to classify score rows
first. If every generated baseline probe was scored and no progress was found,
it will build a terminal summary as today. It then handles three terminal lanes
before exposing more work:

- conflicting score-derived force targets produce
  `post-ceiling-force-map-conflict/ambiguous-score-force-targets`;
- already-terminal continuation summaries without route signatures, such as the
  Sort `post-ceiling-continuation-exhausted` case, produce final synthesis; and
- source-actionable continuation routes are only suppressed when the current
  route signatures exactly match retained closure signatures or route terminal
  blockers.

When a continuation is closed, it will emit a `post_ceiling_final_summary` with:

- `kind: post-ceiling-all-frontiers-exhausted`;
- `terminal_reason:
  post-ceiling-all-frontiers-exhausted/current-source-shape-ceiling`;
- preserved `final_force_phys`;
- `residual_blocker_targets` from still-unmatched force-map targets; and
- `closed_families` and `retained_frontiers` context for auditability.

When the continuation family is not closed, the existing
`analyze_baseline_escape_continuations` path remains active. This preserves the
current behavior that can emit a fresh `source-actionable` continuation after
new scores or a route shape not covered by retained closure evidence.

Force-map preservation is handled by a small helper that scans classified score
rows for `target_score.virtuals` or `expression_score.virtuals` entries with
`expected` registers. Evidence force maps stay authoritative when present, but
empty evidence no longer erases score-derived targets. The continuation
analyzer uses the same helper before deriving candidate force maps, so Sort can
analyze or terminalize with IG34 to r27 and IG44 to r25 instead of reporting
`candidate-force-map-empty`. If score rows disagree on expected registers for a
logical IG, the classifier reports a conflict terminal and does not derive a
route from an arbitrary first-seen value.

## Error Handling

Malformed retained-frontiers entries are ignored rather than failing the
diagnostic command. The existing missing-evidence checks still decide whether
the command is ready. A closure summary only suppresses continuation routing
when it is scoped to the requested function and the top-level retained-frontiers
status is `all-known-frontiers-exhausted`.

## Tests

- Draw regression: when scored baseline probes are terminal and retained
  frontiers include matching closed post-ceiling continuation route signatures,
  baseline escape returns terminal final synthesis and does not re-emit the
  closed continuation routes.
- Draw stale-closure regression: a retained continuation family closure with a
  mismatched route signature does not suppress a fresh source-actionable route.
- Sort regression: when normalized evidence lacks `final_force_phys`, terminal
  summaries preserve IG34 to r27 and IG44 to r25 from scored
  `target_score.virtuals`.
- Force conflict regression: disagreeing score-derived expected registers emit
  `post-ceiling-force-map-conflict` instead of route generation.
- Existing continuation test: when no retained-frontiers closure exists, Sort
  terminal scores can still emit a select-order continuation route.
- CLI smoke: rerun baseline-escape against the issue artifacts and confirm Draw
  is terminal final synthesis while Sort preserves the force map.

## Review Notes

This spec intentionally replaces the brainstorming skill's human approval gates
with independent Codex subagent review because the issue-resolver automation
forbids waiting for human feedback on feature-request issues.
