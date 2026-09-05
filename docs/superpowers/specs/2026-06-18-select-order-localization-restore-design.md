# Select-Order Localization and Restore Hardening Design

## Context

Issues #791, #792, and #793 are follow-ons to the select-order guard repair and
source bridge work in `f1b26a3ab`.

- #791: `mnDiagram_DrawCellNumber` guard repair now finds allocator-useful FPR
  candidates, but all repair children remain rejected as
  `inline-boundary-toolchain-artifact`. The output reports the class and counts
  but does not localize the drift or route the agent to targeted inline-boundary
  source transforms.
- #792: `mnDiagram_SortNamesByKOs` source bridge now reports GPR window-order
  leads and source attributions, but it does not explain why each attributed lead
  failed to produce a safe source probe, and it treats actionability as a global
  probe count instead of a per-lead fact.
- #793: interrupted real-tree source scoring can leave generated candidate edits
  in the live source checkout. Existing cleanup is per-candidate and has signal
  restore support, but select-order needs command-wide byte restore coverage for
  the whole probe generation/scoring path.

The user delegated issue decisions. This design proceeds without a human review
gate and uses subagent review instead.

## Approach

Keep select-order safety rules strict and make blocked decisions explicit. Do
not invent unsafe source moves for implicit temporaries. Do not run a full
structure search automatically inside select-order; instead surface targeted
commands and existing inline-boundary transform families when the guard class is
inline-boundary drift.

The implementation has three units:

1. Window-order source probe planning
   - Add an opt-in diagnostic planner in
     `src/search/directed/window_order_source.py`.
   - Existing `generate_window_order_source_probes()` remains compatible and
     still returns only `list[LifetimeLayoutProbe]`.
   - New diagnostics report one entry per fallback lead, with the source
     attribution, terminal blocker, generated probe labels, source lines, and a
     compact source diff for materialized probes.
   - Supported blocker classes include `missing-source-attribution`,
     `unsupported-source-attribution-kind`, `missing-local-source-name`,
     `no-movable-local-write`,
     `ambiguous-movable-local-write`, `no-legal-destination`,
     `probe-limit-reached`, and `implicit-temp-no-safe-source-move`.

2. Select-order bridge and inline-boundary localization
   - Call the new planner from `debug select-order-search`.
   - Store per-lead diagnostics in `window_order_probe_diagnostics` and
     `source_bridge_summary`.
   - Mark a lead source-actionable only when a probe generated from that lead is
     listed or scored.
   - Add an inline-boundary drift localizer for guard-rejected allocator hits.
     It uses retained checkdiff guard data, candidate source hunks, and candidate
     retained source hunks to identify the smallest available source region.
   - Inline-boundary drift actions should recommend the existing
     `debug search structure --axis inline-boundary` workflow and expose ranked
     repair routes instead of generic coloring repair.

3. Real-tree source restore hardening
   - Register a command-wide active restore snapshot before select-order source
     generation, candidate compilation, scoring, beam expansion, and summary
     generation.
   - Store active restore snapshots as a per-path stack. The signal handler
     restores the earliest snapshot, while nested scorers unregister only their
     own top layer, leaving the command snapshot active underneath.
   - Restore and unregister the command snapshot on normal and known early exits.
     A best-effort destructor provides a fallback for unexpected exceptions.
   - Preserve the current SIGINT/SIGTERM/SIGHUP behavior. SIGKILL cannot be
     caught; recovery remains through retained backups and git diff.
   - If byte restore fails, preserve a backup path and raise a loud restore error
     so the command cannot silently continue with contaminated source.

## Data Flow

`debug select-order-search` resolves the source file and records its byte
snapshot. It derives fallback window-order leads and source attributions. The
window-order planner receives the source text, fallback leads, and attribution
map, then returns probes plus per-lead diagnostics. Select-order scores the
materialized probes as before, refreshes scored probe counts from variant
provenance, and emits `source_bridge_summary` with per-lead actionability and
blocker classes.

For guard-repair candidates, select-order keeps structural guard fields and adds
an `inline_boundary_drift` object when the guard class is
`inline-boundary-toolchain-artifact`. The object includes retained source path,
source hunk, source call lines, opcode drift facts, normalized diff line count,
opcode similarity, line delta, frame delta, and ranked repair routes. The first
route is also exposed as `next_probe` for compatibility with existing consumers.

Every live-source mutation path runs under the command byte snapshot. Per-score
guards may still restore intermediate states, but the command snapshot is the
final authority and restores the original source before the command returns or
exits.

## Error Handling

- Missing retained source detail produces `inline_boundary_drift.status =
  "coarse"` with the guard facts still present.
- Missing or unsupported source attribution produces a terminal per-lead blocker,
  not a generic "inspect" action.
- Ambiguous local writes and no legal statement destinations are terminal for
  `window_order_source` and should point to declaration/lifetime or
  transform-corpus families.
- Restore failures raise an error after preserving a backup. The final source
  state must never be reported as clean if restore verification fails.

## Testing

Focused regression tests should cover:

- Window-order planner emits a probe and marks only the matching lead actionable.
- Window-order planner reports terminal blockers for ambiguous local writes, no
  legal destinations, unsupported implicit-temp attributions, and exhausted
  probe budgets.
- `source_bridge_summary` consumes per-lead diagnostics instead of global probe
  counts.
- Guard-repair summary includes inline-boundary drift localization and targeted
  inline-boundary repair routes for rejected allocator-hit candidates.
- Select-order source scoring restores the live source when a score call raises
  `KeyboardInterrupt` or `SystemExit`.
- Command-wide restore restores the original byte snapshot when probe generation
  or scoring mutates the live source before exiting.

## Non-Goals

- Do not automatically run full structure search from select-order.
- Do not relax `window_order_source` statement-move safety checks.
- Do not claim implicit compiler temporaries are source-movable locals.
- Do not solve backend allocator ceilings for these functions.
