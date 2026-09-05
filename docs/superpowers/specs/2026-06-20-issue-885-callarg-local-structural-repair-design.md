# Issue 885: Callarg-Local Structural Repair Design

## Problem

`mnDiagram_DrawCellNumber` has two useful but incompatible retained frontiers:

- `reconcile-h001-h002`: preserves all six protected expression anchors but
  stays structurally high at `normalized_diff_lines=32`.
- `reconcile-h004`: improves structure to `normalized_diff_lines=18` and
  `opcode_similarity=0.862669`, but both protected `fsubs` expression anchors
  become `missing-expression`.

The lost anchors are not a scoring bug. The artifacts show that the direct
call-argument shape:

```c
HSD_JObjReqAnimAll(jobj, (f32) digit);
```

is structurally downhill, but dematerializes the source-visible digit frame
local that keeps the protected pcode-only FPR `fsubs` anchors alive. The current
tooling can either preserve the digit callarg local and accept 30+ lines of
inline-boundary drift, or choose the direct callarg and lose two protected
anchors.

## Evidence Read

Artifacts inspected:

- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_885_protected_expression_reconcile_scored.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_885_reconcile_h004_plan_fpr.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_885_h004_expression_interferer_repair.json`

Relevant source inspected:

- `src/melee/mn/mndiagram.c`
- `tools/melee-agent/src/mwcc_debug/protected_expression_reconciliation.py`
- `tools/melee-agent/src/mwcc_debug/expression_interferer_repair.py`
- `tools/melee-agent/src/search/directed/transform_corpus/orchestrator.py`
- `tools/melee-agent/src/search/directed/transform_corpus/registry.py`
- `tools/melee-agent/src/search/directed/mutators.py`
- `tools/melee-agent/src/mwcc_debug/pressure_explorer/__init__.py`
- Existing tests under `tools/melee-agent/tests/search/directed/transform_corpus/`
  and `tools/melee-agent/tests/test_*expression*`.

Capability audit:

```bash
melee-agent capabilities search "callarg local preserving structural repair protected expression anchors issue 885"
```

The relevant existing commands are:

- `debug suggest protected-expression-reconcile`
- `debug suggest expression-interferer-repair`
- `debug mutate lifetime-layout`
- `debug search plan-transforms`

No new top-level CLI is needed.

## Root Cause

The missing capability is a third source-shape lane, not another scorer:

1. `protected_expression_reconciliation.py` recombines concrete line hunks
   between two retained frontiers. It cannot synthesize a hybrid hunk that keeps
   the source-visible callarg local while also adopting the structurally better
   h004 product/count and inline-boundary shape. Its `direct-callarg` hunk is
   all-or-nothing: applying h004 gives the better structure and drops the two
   `fsubs` anchors.

2. `pcode_only_fpr_callarg_temp_repair` is too local. It rewrites a single
   `HSD_JObjReqAnimAll` call site, but does not carry enough surrounding
   context to coordinate:
   - product versus `digit_count` order,
   - the existing `rowf = (f32) digit` assignment,
   - reuse versus fresh local ownership,
   - and the protected `row_offset`/`row_offset_adj_owner_fpr` pressure span.

3. `expression_interferer_repair.py` explores row/product owner shapes, but its
   generation families do not model a protected callarg-local-preserving
   structural shape. The best near miss, `row-scaled-adj-direct-owner`, remains
   direct-callarg, preserves only four of six anchors, and duplicates row
   scaling incoherently.

4. Generic `call-argument-tempization` in `pressure_explorer` only hoists
   compound arithmetic call arguments. It intentionally does not act on
   `HSD_JObjReqAnimAll(jobj, rowf)` or direct `(f32) digit` in a way that
   preserves protected expression anchors.

The reusable class is:

> A structurally downhill direct-callarg source loses pcode-only protected FPR
> expression anchors because the local expression that keeps ownership visible
> to MWCC is dematerialized. The repair needs a composite source transform that
> preserves or reintroduces a call-argument local while varying adjacent
> structural order and lifetime.

## Proposed Design

Add a targeted transform family:

```text
callarg_local_structural_repair
```

Initial mutator key:

```text
steer_callarg_local_preserving_structural_repair
```

This should live in the transform-corpus path, not as a standalone CLI. The
family should be invokable through:

- `debug search plan-transforms --transform-family callarg_local_structural_repair`
- `debug mutate lifetime-layout --include-transform-corpus --transform-family callarg_local_structural_repair`
- directed consumers that already append transform-corpus probes.

### Source Matcher

Add the exact source matcher in
`tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`,
next to the existing pcode-only, mixed lifetime, and coupled FPR/callarg
matchers. `orchestrator.py` should only import the iterator, add a small
diagnostic summary, apply the exact-span mutator, and wrap body-relative spans
back into whole-file probes.

The matcher should recognize the `mnDiagram_DrawCellNumber`-style region:

- a digit count statement: `digit_count = mn_GetDigitCount(...)`;
- a product/handoff pair: `col_offset_product_fpr = y_spacing * ...;`
  and `col_offset = col_offset_product_fpr;`;
- row scaling and adjusted row owner statements;
- loop-local digit extraction;
- optional source-visible digit frame assignment, for example
  `rowf = (f32) digit;`;
- `HSD_JObjReqAnimAll(jobj, <arg>)`.

The matcher should reject unsafe regions:

- preprocessor directives inside the candidate span;
- address-taken or externally used callarg local;
- multiple matching calls in the same span unless the call is uniquely
  identified;
- non-`f32`/`float` callarg locals;
- intervening statements with unknown side effects between digit conversion and
  `HSD_JObjReqAnimAll`.

### Candidate Families

Generate bounded candidates, with provenance describing the strategy. The first
batch should be deliberately small and scoreable:

- `retain-existing-rowf-callarg-h004-order`: keep or restore
  `rowf = (f32) digit; HSD_JObjReqAnimAll(jobj, rowf);` while using the h004
  product/count order.
- `fresh-loop-callarg-local`: introduce a loop-local `f32 digit_frame_fpr;`,
  assign it from `digit`, and call with that local.
- `block-scoped-callarg-local`: wrap only the request call in a block with
  `f32 digit_frame_fpr = (f32) digit;`.
- `dead-local-reuse-callarg`: reuse an existing same-type temporary only when
  the matcher proves it is dead before the call and not used after.
- `product-count-callarg-recombine`: combine one callarg-local strategy with the
  product-before-count and product-after-count order variants already observed
  in the reconciliation artifacts.

Avoid generating incoherent row scaling like:

```c
row_offset_adj = row_offset * rowf - 0.4f;
```

after `row_offset` has already been scaled.

### Scoring And Ranking

Do not create a new scorer. Transform-corpus probes should be written through
the existing `debug search plan-transforms --write-probes` path, which emits a
`candidate_path` for each probe. Agents can score those paths manually or by
passing a `--validate-command` template:

```bash
melee-agent debug target score-source <probe.c> \
  -f mnDiagram_DrawCellNumber \
  --cflags-from src/melee/mn/mndiagram.c \
  --target <target.json> \
  --expression-baseline <baseline.pcdump.txt> \
  --expression-source <baseline-source.c> \
  --expression-reg-class fpr \
  --checkdiff-guard \
  --json
```

Ranking should continue to prioritize:

1. `expression_score.matched == expression_score.targeted == 6`;
2. lower `structural_guard.normalized_diff_lines`;
3. higher `opcode_similarity`;
4. smaller hunk count and lower line delta;
5. source coherence.

Add a terminal blocker summary when the family is exhausted:

```text
exhausted-callarg-local-structural-repair
```

For `plan-transforms --validate-command`, this belongs in
`tools/melee-agent/src/search/cli/__init__.py` inside
`_summarize_transform_validations`. For reconciliation reruns over scored
candidate JSON, any richer protected-expression terminal blocker belongs in
`tools/melee-agent/src/mwcc_debug/protected_expression_reconciliation.py`.

The summary should report the best `expression_score=6/6` structural line
count, the best structural candidate's expression count, and whether every
local-preserving shape remains at or above the 30-line structural ceiling.

## Integration Points

Likely production files:

- `tools/melee-agent/src/search/directed/transform_corpus/registry.py`
  - Add family metadata and mutator key.
- `tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`
  - Add the case model, exact matcher, diagnostics payloads, and candidate
    replacement strings.
- `tools/melee-agent/src/search/directed/transform_corpus/orchestrator.py`
  - Add iterator import, force-class support, diagnostics summary, and family
    dispatch.
- `tools/melee-agent/src/search/directed/mutators.py`
  - Add `steer_callarg_local_preserving_structural_repair` as exact-span
    replacement using existing `_replace_validated_span`.
- `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
  - Add catalog metadata and notes only.
- `tools/melee-agent/src/search/cli/__init__.py`
  - Add validation-summary terminal blocker logic for
    `exhausted-callarg-local-structural-repair` when validation results prove
    the local-preserving family is exhausted.
- `tools/melee-agent/src/mwcc_debug/protected_expression_reconciliation.py`
  - Optionally add a protected-expression terminal blocker for scored
    reconciliation reruns if the generated candidate JSON needs richer
    protected-anchor classification.
- `tools/melee-agent/src/mwcc_debug/expression_interferer_repair.py`
  - Optionally add the same candidate source generation strategies if the
    source-generation-only path should emit them without `plan-transforms`.
    Prefer transform-corpus first; only mirror here if the real #885 smoke shows
    `expression-interferer-repair` remains the primary caller.
- `tools/melee-agent/src/cli/debug/__init__.py`
  - Usually no command change. Only touch if existing output summaries need to
    preserve the new diagnostics in JSON.

## Non-Goals

- Do not add a new top-level `melee-agent` command.
- Do not change `debug target score-source` scoring semantics.
- Do not broaden generic `call-argument-tempization` unless the targeted family
  cannot reuse existing helpers safely.
- Do not implement broad C AST rewriting for all call arguments. Use exact-span
  guarded matching for this issue class.
- Do not edit `src/melee/mn/mndiagram.c` as part of the tooling fix.

## Acceptance Criteria

The implementation is successful when the tooling can emit retained `.c` probes
for `mnDiagram_DrawCellNumber` that:

- preserve or reintroduce a source-visible digit callarg local used by
  `HSD_JObjReqAnimAll`;
- vary product/count order and callarg local lifetime/scope in bounded,
  coherent ways;
- include `candidate_path` values usable by existing score-source validation
  commands when emitted through transform-corpus;
- report expression and structural guard evidence after scoring;
- either find a candidate with `expression_score=6/6` below the current
  `ndiff=32` local-preserving ceiling, or produce a terminal summary explaining
  that callarg-local preservation necessarily keeps the 30+ line
  inline-boundary drift.

## Open Questions

- The current best h004 source still contains an unused `rowf = (f32) digit;`.
  The compiler likely DCEs it. The first implementation should confirm whether
  using that local in the call, using a fresh loop-local, or block-scoping it
  changes the `fsubs` anchor status.
- If all local-preserving shapes stay at `ndiff >= 30`, the terminal summary
  must distinguish "generation missing" from "compiler structural coupling."
- The existing `expression-interferer-repair` source-generation path may need a
  mirror of the transform-corpus family for convenience, but the reusable
  production source should be transform-corpus first.
