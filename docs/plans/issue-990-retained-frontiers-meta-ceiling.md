# Issue 990 Implementation Plan

## Scope

Teach retained-frontiers and allocator-ceiling tooling to consume final
`all-known-frontiers-exhausted` retained-frontiers artifacts directly. The new
layer should produce either a ranked non-duplicate source-actionable lane or a
terminal proof that the current source shape has no modeled retained-frontier
source levers left.

## Root Cause

The retained-frontiers command could already aggregate Sort and Draw terminal
lanes, but the final artifact was not a first-class allocator-ceiling evidence
shape. Passing the full JSON into `debug solve allocator-ceiling` failed function
scope validation, and passing an extracted function entry fell through to legacy
missing-evidence handling.

## Design

1. Add retained-frontiers meta-ceiling synthesis to
   `retained_frontier_triage.py`.
2. Preserve the existing retained-frontiers output contract while attaching
   `meta_ceiling` summaries to function payloads and the top-level payload.
3. For actionable retained lanes, rank only lanes that are not already terminal
   by frontier id or suppression signature.
4. For terminal retained sets, require:
   - retained status `all-known-frontiers-exhausted`
   - no `next_frontier`
   - at least one terminal frontier
5. Group terminal frontiers by root cause:
   `(family_id, terminal_reason, suppression_family)`.
6. Emit compact representative frontier rows, allocator facts, source spans,
   closed families, exhausted dimensions, and the next unsupported source-model
   label where available.
7. Teach allocator-ceiling to accept full retained-frontiers aggregates,
   extracted function entries, and direct meta-ceiling payloads.
8. Preserve allocator precedence:
   positive evidence, bounded evidence, existing explicit terminal ceilings,
   retained actionable lanes, retained terminal proof, then legacy
   missing-evidence/incomplete fallback.
9. Add capability aliases for "meta ceiling synthesis", "all known frontiers
   exhausted", and "retained frontiers terminal proof".

## Review Corrections

Independent review requested these constraints before implementation:

- Select the requested function from multi-function retained-frontiers
  aggregates before allocator validation.
- Do not let retained-frontiers terminal proof override stronger existing
  allocator-ceiling evidence.
- Keep representative JSON compact instead of duplicating full frontier rows.
- Avoid hard-coded Sort or Draw counts; derive all grouping from artifact data.
- Cover stale retained lanes and precedence with regression tests.

## Verification

- Focused retained-frontiers, allocator-ceiling, capabilities, and baseline
  escape regression tests.
- `debug solve allocator-ceiling` smoke tests against the issue #990 Sort and
  Draw retained-frontiers artifacts.
- `debug search retained-frontiers --text` smoke test against the Sort artifact.
- Capability search smoke tests for the new aliases.
- `git diff --check`.
