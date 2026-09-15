# Issue 994/995 Source-Family Continuation Plan

## Scope

Issues #994 and #995 both start after `debug search source-model-synthesis`.
The generator has already found useful one-hit source facts, but the existing
retained-frontiers path cannot consume the follow-up evidence:

- Sort: GPR source-family probes move either `IG34->r27` or `IG44->r25`, but
  structural repair and pairwise recombination do not preserve both targets.
- Draw: the `col-mul-assign` source preserves a renumbered pcode-only fsubs
  expression hit, but later reconcile/interferer probes either revert that hit
  or introduce frame drift.

The reusable feature is a read-only continuation artifact builder. It consumes
classified source-model output plus follow-up artifacts and emits a normalized
`post-ceiling-source-model-proof` frontier.

## CLI Contract

```
melee-agent debug search source-family-continuation \
  --source-model-json classified.json \
  --artifact combine-or-reconcile.json \
  --score-json optional-score-source.json \
  --out continuation.json \
  --json
```

`--artifact` and `--score-json` are repeatable. The command does not create new
source probes; it ranks and terminalizes evidence produced by existing tools.

## Acceptance Rules

For Sort, a continuation candidate is accepted only if it preserves all forced
GPR targets with an accepted structural guard and no frame drift.

For Draw, the source-model one-hit result becomes the baseline. A continuation
candidate is accepted only if it improves beyond that expression-hit baseline
while preserving structural guard/frame safety. Renumbered pcode-only fsubs
anchors remain valid evidence only when the expression signature matches.

If no candidate satisfies those rules and supplied artifacts prove the bounded
continuation lanes were attempted, the command emits a terminal proof naming
the exhausted dimensions and blockers.

## Retained-Frontiers Shape

The output is a normalized frontier with:

- `family_id: post-ceiling-source-model-proof`
- `kind: post-meta-source-family-continuation-proof`
- `terminal`, `attempted_targets`, `protected_targets`, `final_force_phys`
- ranked candidates, score summaries, source hunks, and blocker evidence
- embedded `source_model_proof.source_family_synthesis`

This lets `retained-frontiers` close the same governance family instead of
leaving the older unsupported source-model note dominant.
