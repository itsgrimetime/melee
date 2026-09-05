# Issue 988: Inline-Boundary Continuation Handoff

## Problem

`debug measure inline-leverage` can now prove that
`mnDiagram_SortNamesByKOs -> mnDiagram_SumNameKOs` is a strict lever: the
normal source scores better than the scalar-assignment de-inlined variant.
The retained-frontier queue did not consume that evidence, so after the Sort
post-ceiling source-model proof closed its known source families, triage could
still report `all-known-frontiers-exhausted` with no next route.

The missing layer is bounded helper-boundary continuation around the real
inline rather than a broad transform-corpus search. The required dimensions are:

- `signature`
- `local_declarations`
- `loop_init`
- `call_argument`
- `return_local_materialization`
- `scalar_assignment_splice_boundary`

## Design

Add a narrow inline-leverage boundary module that accepts strict
`scalar_assignment_splice` leverage records and generates candidate source
probes around the exact inline definition and call assignment. The module is
pure source-to-source: it writes no files unless the CLI asks it to, returns
blocked diagnostics for ambiguous source shapes, and ranks existing
`debug target score-source --json` payloads by target/expression progress.

Add `melee-agent debug suggest inline-boundary-continuation` to:

1. load an inline-leverage report,
2. select a unique strict row,
3. generate bounded probes,
4. optionally write probe `.c` files and a target spec,
5. rank supplied score JSONs, and
6. emit a normalized terminal frontier when every generated probe is scored and
   none improves the requested target registers.

Teach retained-frontier triage to recognize strict inline-leverage records as an
actionable `inline-leverage-helper-boundary-continuation` frontier. A terminal
proof from the new command uses the same frontier id, so the existing frontier
merge path closes the actionable route without another bespoke suppression
system.

## Acceptance

Given the Sort inline-leverage report, retained-frontiers must hand off to the
new inline-boundary command instead of silently exhausting. Given a terminal
proof from that command, retained-frontiers must return to exhausted while naming
all six searched dimensions.
