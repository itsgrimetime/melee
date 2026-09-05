# Directed Allocator-Ceiling Evidence Design

## Goal

Issue #726 follows #715's closure matrix: the source-transform corpus has been
exhausted, but agents still need a durable backend-level routing verdict for the
remaining functions. This slice extends the existing read-only
`debug solve allocator-ceiling` command so it can consume `debug search directed`
JSON directly and classify directed-search exhaustion as practical backend
ceiling evidence.

## Scope

This is not a new source-transform family and not a new allocator override. The
feature only interprets structured directed-search telemetry that already exists:
gate verdict, candidate byte outcomes, proof assignment buckets, and accounting
metadata. The command remains read-only.

The first supported backend-ceiling evidence shape is a single-register-class
directed run where:

- the payload is scoped to the requested function,
- at least one candidate compiled and produced directed telemetry,
- at least one source-transform candidate ran,
- no telemetry row reached `checkdiff_gate == "byte_match"`,
- byte outcomes are known for valid telemetry rows, either through
  `checkdiff_gate == "byte_mismatch"` or a nonzero `byte_score`,
- all applicable rows are byte mismatches or non-winning diagnostic candidates,
- the directed gate ended with `passed == false` and `reason ==
  "no_smooth_gradient"`,
- directed source-shape generation reports `source_shape_drained == true`,
- the run is not explicitly bounded by candidate limit, budget exhaustion, or
  producer failure, and
- proof assignment buckets include blocked allocator decisions.

When those conditions hold, `allocator-ceiling` should return
`status=practical-ceiling`, `terminal_reason=directed-source-exhausted`, and a
`backend_blockers` list describing the blocked desired physical assignments.

## Alternatives Considered

1. Add a new backend-control command now. This is too broad for #726's first
   stop condition and duplicates existing `force-phys`, `force-coalesce`, and
   `allocator-ceiling` affordances.
2. Work #725 first. Mixed-class directed proof is useful, but #726 has
   single-class evidence today, especially `mnDiagram_80241E78`.
3. Extend `allocator-ceiling` with directed telemetry evidence. This is the
   selected path because it is small, testable, and turns #715-style closure data
   into a reusable backend routing verdict.

## Data Model

`debug search directed` results should include `function` and `unit` at the top
level. Existing evidence scope validation should accept these fields without
weakening nested mismatch checks.

`allocator-ceiling` should detect directed evidence from:

- top-level `directed_telemetry` list,
- top-level `gate` mapping,
- top-level `accounting` mapping,
- optional top-level `function` and `unit`.

Each telemetry row may contain:

- `applied_mutator`
- `checkdiff_gate`
- `proof_assignments.satisfied`
- `proof_assignments.blocked`
- `proof_assignments.abstained`
- `valid`
- `non_actionable`

The classifier should aggregate blocked assignments from all valid telemetry
rows, de-duplicate them by `(original_ig, new_ig, desired_phys, assigned_phys)`,
and expose them as `backend_blockers`. For source-transform rows, include the
mutator key that observed the blocker when available.

## Verdict Rules

Positive proof still wins. Any `byte_match`, retained-source improvement,
`status == "improved"`, or positive `best_checkdiff_delta` remains actionable.

Bounded evidence is not a ceiling. Directed runs should be `bounded` when the
accounting or gate explicitly shows candidate-limit, budget-exhausted, producer
failure, or similar incomplete search limits. A short `--max-iters` smoke can
verify plumbing, but it must not be used as closure evidence unless the payload
also proves the directed corpus drained without budget or producer limits.
Individual compile failures from generated probes are not automatically
bounded when the same run has byte-scored mismatch telemetry; they are expected
for some rejected source-shape candidates and do not by themselves leave the
backend proof unscored. Score failures and invalid directed telemetry are
bounded because they leave candidate outcomes unknown.

Directed gate progress is not a ceiling. A payload with `gate.passed == true`
or any non-byte positive progress remains `actionable`, because it means the
directed mechanism found a source-level lever to inspect rather than a backend
allocator ceiling.

Directed evidence can independently prove a practical ceiling when all selected
scope conditions pass. It should not require the older four-part
solve-coloring/node-set/force-vector/transform-corpus bundle, because a directed
run already combines force-phys objective setup, source-transform execution, and
byte scoring in one artifact.

If a directed payload has no byte match but lacks blocked assignments or source
transform rows, it should be `incomplete` with missing evidence that tells the
agent what to collect next.

## CLI Behavior

No new CLI surface is required. Existing usage remains:

```bash
melee-agent debug solve allocator-ceiling \
  --function mnDiagram_80241E78 \
  --evidence directed.json \
  --json
```

Text output should include a backend-blockers section for practical ceilings
derived from directed evidence.

Exit codes remain unchanged:

- `0`: actionable positive proof found
- `2`: malformed, unreadable, or wrong-function evidence
- `3`: practical ceiling or incomplete evidence
- `4`: bounded evidence that should be rerun with larger limits

## Testing

Regression tests should be written before production code:

- directed telemetry with blocked assignments and all byte mismatches becomes
  `practical-ceiling`,
- directed telemetry with `checkdiff_gate == "byte_match"` becomes
  `actionable`,
- directed telemetry without blocked assignments is `incomplete`,
- directed telemetry without `source_shape_drained` is `incomplete`,
- directed telemetry with unknown byte outcomes is `incomplete`,
- directed telemetry with candidate-limit/budget/producers blocked is
  `bounded`,
- directed telemetry with score failures or invalid telemetry rows is `bounded`,
- mixed-function directed evidence is rejected,
- CLI text includes backend blockers, and
- `debug search directed` output includes `function`, `unit`, and source-shape
  accounting.

## Stop Condition

#726 can be resolved when `allocator-ceiling` accepts a current directed result
for `mnDiagram_80241E78` and emits a reproducible `practical-ceiling` verdict
with exact blocked allocator assignments, while all new regression tests pass.
