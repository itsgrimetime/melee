# Source-Lifetime Helper-Inline Transform Harness Design

## Problem

Issue #444 reports a reusable mismatch class: functions with stable or
near-stable opcode shape but wrong register ladders for helper-call results,
struct-field reloads, and short-lived temporaries. Allocator force verification
has already produced `no_improvement`, so the next useful tool must generate and
score source-level levers instead of another force knob.

The seed set is:

- `fn_803AC6B8`
- `fn_803AC7DC`
- `fn_803ACD58`
- `it_802A7384`

The required output is ranked retained source candidates. Each compiled
candidate must report baseline percent, candidate percent, delta, compile
status, checkdiff status, structural movement, and whether opcode shape was
preserved when checkdiff metrics are available.

## Chosen Approach

Add a new `debug search structure` axis named `source-lifetime`. This reuses the
structure-search scorer, which already handles real-TU compile scoring,
baseline/candidate/delta, checkdiff structural metrics, retained candidate
source, build locking, and restoration. The axis is optional rather than part of
the default axis set, because it can produce many expensive source candidates
and is meant for this specific allocator/source-lifetime class.

The implementation will also extend `debug mutate lifetime-layout` probe
generation so existing mwcc-debug users can list or compile the same source
levers directly. The structure-search axis is the issue-resolution harness; the
lifetime-layout command remains the lower-level pressure explorer.

## Alternatives Considered

1. Extend only `debug mutate lifetime-layout`.

   This command already has pressure signatures, pcdump compilation, retained
   sources, and final match percent. It does not naturally report fresh baseline
   percent, candidate delta, or checkdiff structural metrics in the same payload
   shape that matching agents now consume.

2. Add a new standalone helper-inline command.

   A standalone command would duplicate output schema, scoring, locks, source
   retention, and stop-condition behavior. That would make issue #444 harder to
   compose with the recently-added structure-search scorer.

3. Add a `source-lifetime` structure-search axis.

   This keeps one ranked source-transform harness and lets the new feature
   focus on candidate generation. This is the selected design.

## Candidate Families

The `source-lifetime` axis will gather candidates from two sources.

First, it will wrap existing `pressure_explorer.generate_lifetime_layout_probes`
families that are already source-actionable for this class:

- `declaration-order`
- `loop-counter-hoist`
- `loop-counter-type`
- `temp-introduction`
- `temp-removal`
- `declaration-use-distance`
- `block-scope`
- `call-argument-tempization`
- `expression-shape`

Second, it will add targeted source-lifetime probes:

- `for-condition-field-reload`: detects a `for` condition whose first
  expression reloads a field into a local via comma expression, such as
  `for (i = 0; size = state->x8, i < ...; i++)`. It emits C89-compatible
  variants that move the reload into the `for` init/increment clauses or
  precompute a loop-bound local, preserving a concrete retained source file for
  each shape.
- `repeated-helper-result-reuse`: detects repeated identical helper calls within
  one statement region or switch arm, such as repeated `fn_803AC634(state, i)`,
  and emits a variant that materializes the call result into a local and reuses
  it for later occurrences.
- `helper-result-dematerialize`: detects a local that is assigned from a helper
  call and used once or twice soon afterward, then emits a variant that repeats
  the helper call at the use site. This is the inverse lever for cases where the
  current code overextends a helper result lifetime.
- `simple-helper-inline-body`: detects a same-TU helper with a small single-exit
  expression body, such as a helper that returns a struct field calculation, and
  emits a variant that replaces one target-function call with the helper body
  expression using call arguments substituted for simple parameters. This is
  bounded to helpers already defined in the same source file and to bodies that
  can be rendered as one expression or one assignment plus expression; it does
  not synthesize new helper definitions.

The generator will use conservative textual rewrites only where the local
patterns are simple, balanced, and free of obvious side effects such as `++`,
`--`, assignment in arguments, preprocessor directives in the touched region, or
address-taken locals. It will not introduce helper function definitions outside
the target function. Helper call-count rewrites must also pass a callee safety
gate: the helper is either a whitelisted read-only helper for the seed class
(`fn_803AC634`) or a same-TU simple-helper body accepted by the inline-body
scanner. Candidates that do not pass this gate are emitted only as blocked
family summaries, not as compiled candidates.

Targeted families run before generic lifetime-layout families. The axis reserves
at least half of `max_candidates` for targeted source-lifetime families before
filling the remainder with generic lifetime-layout probes. If no targeted family
can generate a safe candidate, the axis summary reports per-family blockers such
as `callee-not-read-only`, `helper-body-too-complex`, or
`no-for-condition-field-reload`.

## Payload And Ranking

The new axis emits ordinary `StructureVariant` rows:

- `axis`: `source-lifetime`
- `operator`: one of the operator names above
- `label`: stable and filesystem-safe candidate label
- `source_retained` and `path`: retained generated `.c` source
- `metadata`: original probe provenance plus source line spans when available
- `command`: a rerun command using `melee-agent debug search structure -f <fn>
  --axis source-lifetime --max-candidates <n>`

Scoring remains delegated to `score_structure_variants`. The scorer will add
`metadata["structural"]["opcode_shape_preserved"]` when checkdiff reports
`opcode_similarity`; it is true when opcode similarity is at least `1.0`.
Candidates that compile and produce match percent but fail structural checkdiff
still preserve percent/delta and are marked unscored with `checkdiff_status:
"failed"`.

Ranking for source-lifetime variants puts shape-preserving scored candidates
ahead of shape-breaking scored candidates before applying match percent and
delta ordering. Shape-breaking improvements stay visible but do not satisfy the
issue-specific success criterion.

## Stop Condition

The existing structure-search stop condition is used for generic payload
compatibility:

- `improved` when any scored candidate improves over baseline or reaches 100%.
- `candidates-generated` when retained candidates exist but were not all fully
  scored.
- `no-improvement` when all bounded candidates were scored and none improved.
- `blocked` axis summaries when no safe source lever can be generated.

For issue #444 resolution, the seed smoke must run the new axis on all four seed
functions with bounded candidates. The issue can be resolved when the run either
produces at least one retained source improvement whose opcode shape is
preserved, or produces compiled/scored candidate rows plus concrete
no-source-lever/no-improvement reasons for every seed. Shape-breaking
improvements are reported as candidates for human inspection but are not enough
to resolve the issue by themselves.

## CLI

New usage:

```bash
melee-agent debug search structure -f fn_803AC7DC --axis source-lifetime --json
```

The existing lower-level explorer also gets a focus bundle:

```bash
melee-agent debug mutate lifetime-layout -f fn_803AC7DC --focus helper-inline-lifetime --json
```

The focus bundle selects the existing and new source-lifetime operator families.

## Tests

Focused tests cover:

- Source-lifetime axis emits retained `StructureVariant` rows and honors
  `max_candidates`.
- `for-condition-field-reload` generates a candidate for the `fn_803ACD58`
  style comma reload loop.
- `repeated-helper-result-reuse` generates a candidate for the `fn_803AC7DC`
  style repeated helper calls.
- `helper-result-dematerialize` generates the inverse repeated-call lever for a
  simple helper-result local.
- `simple-helper-inline-body` expands a same-TU expression helper and rejects
  helpers with multi-statement or side-effecting bodies.
- The `helper-inline-lifetime` focus filters lifetime-layout probes to the new
  and reused operator families.
- Scoring structural metadata includes `opcode_shape_preserved` when opcode
  similarity is available.
- Source-lifetime ranking puts shape-preserving candidates before shape-breaking
  candidates.
- Targeted families are not crowded out by generic lifetime-layout probes under
  a small `max_candidates`.
- CLI help and JSON smoke checks still work.

## Out Of Scope

- No allocator force-vector changes.
- No decomp source edits to the seed functions.
- No broad inline-body synthesis for arbitrary helper definitions. The harness
  only expands same-TU simple expression helpers inside the target function;
  existing `debug suggest inlines` remains the tool for broader inline-boundary
  evidence.
