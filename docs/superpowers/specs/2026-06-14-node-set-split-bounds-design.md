# Node-Set Split Bounded Probe Design

## Goal

Make `melee-agent debug solve node-set-split` safe to run as the stop-condition
probe requested by issue #672. The existing solver already generates
source-shape candidates for allocator node-set splits, but a real function can
produce enough candidates that a probe with a small per-child `--timeout` still
runs for minutes.

## Scope

This design extends the existing command. It does not add a new allocator hook,
does not force an artificial split in MWCC, and does not claim that a target-side
copy exists unless a trace command proves it. The command remains a source-shape
realizer: it either finds an improving source candidate or reports that the
bounded search did not find one.

## CLI Contract

`debug solve node-set-split` gains:

- `--max-candidates N`, defaulting to `16`. This is the maximum number of
  generated source candidates evaluated by the pcdump/checkdiff loop. `0` means
  unlimited for explicit exhaustive runs.
- `--budget SECONDS`, optional. This is a global wall-clock budget for compile
  and score probes. Each child compile or checkdiff call receives a timeout
  clamped to the remaining budget, so one child cannot consume the full original
  per-candidate timeout after the global budget is nearly exhausted.

The command keeps the primary outcome stable:

- `status: "improved"` means at least one evaluated candidate realized the
  requested node-set objective and improved real-tree checkdiff by the requested
  threshold.
- `status: "exhausted"` means no evaluated candidate improved the result.
- `status: "blocked"` means the command could not form a bindable request or
  generate candidates.

Bounded termination is separate from the primary outcome. JSON includes
`stop_condition` when the run stops early, with `kind` equal to
`candidate-limit` or `budget-exhausted`. An improved candidate remains
`status: "improved"` even if later candidates were omitted.

## Summary Fields

The JSON summary keeps existing fields for compatibility and adds clearer
counts:

- `generated_count`: all generated source candidates.
- `evaluated_count`: candidate rows that entered the pcdump objective loop.
- `checkdiff_scored_count`: evaluated candidates that reached real-tree
  checkdiff scoring.
- `realized_count`: evaluated candidates whose pcdump moved the target IG to the
  requested physical register without new spills.
- `omitted_count`: generated candidates not evaluated because of a stop
  condition.
- `exhaustive`: true only when no stop condition ended a non-blocked run.

## Guidance

When a run stops early or exhausts without a win, the summary suggests
`debug inspect trace-copy` as a separate diagnostic for suspected target-only
allocator splits. This is guidance, not proof: the command only says
`copy-not-found` when the user actually runs `trace-copy` and observes that
result.

For issue #672 specifically, `debug inspect trace-copy -f mnDiagram_80242C0C
--from r76 --to r47 --json` returns `copy-not-found`, so the old coalesce/block
copy path is not the right layer for that current build. The bounded
`node-set-split` run is the appropriate source-shape probe.

## Tests

Regression coverage must prove:

- Summary output separates primary `status` from `stop_condition`.
- `--budget 0` skips candidate compile work and reports omitted candidates.
- `--max-candidates 1` evaluates one candidate and reports the rest omitted.
- `status: "improved"` wins when the first candidate improves before a candidate
  cap stops the search.
- Existing node-set-split tests still pass.
