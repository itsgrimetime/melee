# Issue 916 Protected Structural Repair Lane Design

## Problem

Issue #916 reports a select-order search frontier for
`mnDiagram_SortNamesByKOs` where a retained source candidate already satisfies
the protected force-phys target `IG34->r27, IG44->r25`, but the structural guard
rejects it as `control-flow-source-shape`. The existing guard-repair lane can
expand structural-guard-rejected force-phys hits, but only after those hits are
produced by the current invocation through normal candidate or beam search. A
matcher who already has an exact-register retained source must rerun unrelated
searches or hand-drive structural probes.

## Goals

- Allow a user to provide a retained exact-register source as a protected
  guard-repair frontier.
- Preserve existing ranking and guard-repair semantics: a seed is still a
  scored source candidate, must have at least one protected force-phys hit, and
  must be rejected by the structural guard before it seeds repair.
- Auto-enable a bounded guard-repair pass when explicit repair seeds are passed
  with a force-phys map, even without beam mode.
- Emit ledger evidence that identifies explicit seeds, their protected hits, and
  the repair stop condition.
- Keep implementation scoped to `debug select-order-search`; do not add a new
  command or a new structural search engine.

## Non-Goals

- Do not bypass or weaken the structural guard.
- Do not claim semantic equivalence beyond the existing compile, force-phys, and
  structural-guard checks.
- Do not special-case `mnDiagram_SortNamesByKOs`; the lane should be reusable
  for any retained source candidate.

## Considered Approaches

1. Add a standalone `debug structural-repair-from-exact` command. This would be
   discoverable but would duplicate scoring, ledger, and guard-repair behavior.
2. Reuse `--candidate` and document the current workaround. This does not solve
   the operational problem because guard repair remains tied to beam/default
   depth behavior and the seed is not clearly protected in the ledger.
3. Add explicit `--guard-repair-seed` inputs to `debug select-order-search`.
   This is the selected approach because it reuses the existing scoring,
   ranking, crossover, subtractive hunk, transform, and ledger machinery while
   making the exact-register frontier a first-class input.

## CLI Behavior

`debug select-order-search` gains a repeatable option:

```text
--guard-repair-seed OPERATOR=path
--guard-repair-seed LABEL:OPERATOR=path
```

The format matches `--candidate`, but the path must point at a `.c` retained
source. The option requires `--force-phys` or `--transform-force-phys` because
the protected lane is defined by the force-phys map.

Each explicit seed is scored through the same source candidate path as
`--candidate`. Successful seed variants are tagged with
`guard_repair_explicit_seed=true` and normal candidate metadata. When
`--guard-repair-depth` is omitted, explicit seeds with a force-phys map imply
depth 1. `--guard-repair-depth 0` remains an explicit opt-out.

The guard-repair seed set is selected from explicit seeds first, then existing
ranked variants fill any remaining `--guard-repair-width` slots. A tagged seed
still must pass the existing seed eligibility checks: successful compile,
structural guard rejected, retained `.c` source, and at least one protected
force-phys hit.

## Output and Ledger

The JSON payload includes:

- `guard_repair_seed_specs`: the parsed explicit seed labels, operators, and
  paths.
- `guard_repair_ledger`: unchanged path semantics.

The guard-repair ledger includes:

- `explicit_seed_specs`: parsed explicit seed inputs.
- `seed_source`: `explicit` or `ranked-variant` for each seed entry.
- `stop_condition`: existing values such as `depth-exhausted`,
  `frontier-empty`, `no-repair-probes`, or `timeout`.

This gives matchers a source-actionable handoff: retained seed source, ranked
repair candidates, preserved protected hits, and bounded failure evidence if no
repair improves structural shape.

## Tests

- Add a CLI regression test where `--guard-repair-seed` is passed with
  `--no-compile-probes` and no `--beam-depth`. The test verifies the explicit
  seed is scored, guard repair auto-enables at depth 1, the ledger marks the
  seed as explicit, and a generated repair candidate preserves the protected
  force-phys hits.
- Add validation tests that explicit seeds require a force-phys map and require
  a `.c` source path.
- Run the existing guard-repair tests plus the new tests.
- Smoke `melee-agent debug select-order-search --help` and verify the installed
  `melee-agent` entrypoint exposes the new option after refresh.

## Rollout

This is backward compatible. Existing `--candidate`, beam, and guard-repair
flows keep their behavior. Users who already have exact-register retained source
can now pass it directly as a protected structural repair frontier.
