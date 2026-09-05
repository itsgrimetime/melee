# Issue 886: Fresh Callarg-Local Continuation Design

## Problem

`callarg_local_structural_repair` solved the issue #885 direct-callarg case,
but it does not continue from the better issue #886 retained frontier for
`mnDiagram_DrawCellNumber`.

The retained #886 source already has a separate digit animation-frame local:

```c
digitf = (f32) digit;
HSD_JObjReqAnimAll(jobj, digitf);
```

That source scores as the best expression-preserving frontier observed so far:

- artifact:
  `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_manual_rowf_matrix/scores/m04_digitf_local_callarg.json`
- `expression_score.matched=6/6`;
- `false_positive_virtual_id_hit_count=0`;
- raw `target_score.matched=5/6`, with only baseline virtual 33 wrong;
- normalized structure is still high enough to need continuation.

Running `callarg_local_structural_repair` on that retained source emits no
probes:

- artifact:
  `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_callarg_local_structural_repair_m04_digitf.json`
- `source_resolution.status=resolved`;
- `materialized_count=0`;
- `no_probe_reason=source-pattern-not-found`;
- `matcher_diagnostics.hsd_jobj_req_anim_all_calls=1`.

Running the family on the older rowf/direct-callarg frontier does emit probes,
but they are false progress under expression identity:

- artifacts:
  - `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_callarg_local_structural_repair/scores/callarg_local_structural_repair@0.json`
  - `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_callarg_local_structural_repair/scores/callarg_local_structural_repair@1.json`
  - `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_callarg_local_structural_repair_h001h002/scores/callarg_local_structural_repair@0.json`
  - `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_callarg_local_structural_repair_h001h002/scores/callarg_local_structural_repair@1.json`
- all keep raw `target_score.matched=5/6`;
- all regress to `expression_score.matched=4/6`;
- all report one `false_positive_virtual_id_hit_count`.

## Root Cause

This is a matcher-state bug plus a scoring-reporting gap, not a missing compile
or target-score primitive.

The current matcher in
`tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`
models only the issue #885 shape:

```c
rowf = (f32) row;
row_offset *= rowf;
...
rowf = (f32) digit;
HSD_JObjReqAnimAll(jobj, (f32) digit);
```

It then creates rowf-preserving or `digit_frame_fpr` variants. Two assumptions
are too narrow for #886:

1. `_iter_callarg_local_structural_cases` requires `rowf_local == callarg_local`.
   That means a source with separate `rowf` and `digitf` locals is rejected even
   when the callarg local is exactly the expression-preserving state the search
   needs to continue from.

2. The generator treats a fresh local as something it must introduce, with a
   hard-coded `digit_frame_fpr` name. It does not have a continuation mode for
   an already materialized fresh callarg local, and diagnostics collapse that
   case into generic `source-pattern-not-found`.

The scorer artifacts also show why raw virtual-id target score is unsafe here.
The generated `digit_frame_fpr` probes appear to keep a raw `5/6` target score,
but expression scoring shows that baseline virtual 33 is only a raw-id hit: the
source expression is renumbered and lands in the wrong physical register.

## Approaches

### Approach 1: Extend Existing Family With Fresh-Local Continuation

Teach `callarg_local_structural_repair` to accept separate row-scale and
callarg locals, preserve the discovered callarg local by default, and generate
bounded continuation probes around product/count order, declaration/lifetime,
and callarg-local scope.

Pros:

- tightest change; keeps the repair in the existing family and CLI paths;
- directly fixes `m04_digitf_local_callarg.c`;
- reuses exact-span replacement and existing scoring flow;
- avoids a new top-level command or duplicate catalog entry.

Cons:

- the existing family becomes slightly broader and needs better diagnostics to
  distinguish "needs direct-callarg repair" from "continuing from fresh local".

### Approach 2: Add A New Subfamily

Add `fresh_callarg_local_continuation` as a separate transform family with its
own registry/catalog metadata and terminal blocker.

Pros:

- more discoverable in diagnostics;
- easier to filter independently from the issue #885 direct-callarg repair.

Cons:

- duplicates most of the same matcher;
- adds registry/catalog/test overhead for a state transition that is still part
  of the same source region;
- risks splitting scoring history across two family ids.

### Approach 3: Make The Search Orchestrator Expression-Stateful

After validation, automatically pick the best `expression_score=6/6` source and
re-enter transform planning with that source as the next frontier.

Pros:

- generalizes beyond this one local;
- eventually useful for multi-step expression-aware searches.

Cons:

- much larger workflow change;
- needs persistent candidate state and policy decisions;
- higher risk while the immediate failure is a single exact matcher assumption.

## Selected Design

Use Approach 1.

Extend `callarg_local_structural_repair` with an explicit "fresh-local
continuation" mode. The family should detect both source states:

- direct or rowf-reused callarg source that needs a local introduced;
- already materialized fresh callarg local source such as `digitf`.

The matcher should no longer require `rowf_local == callarg_local`. Instead, it
should model the two locals separately:

- `rowf_local`: the local used for `row_offset *= rowf`;
- `callarg_local`: the local assigned from `(f32) digit` and passed to
  `HSD_JObjReqAnimAll`;
- `callarg_local_kind`: `rowf-reuse`, `fresh-existing`, or `inline-cast`;
- `callarg_assignment_line`: the assignment that dominates the call, when one
  exists.

For an existing fresh callarg local, candidate generation should preserve that
local unless a strategy explicitly probes a scoped alternative. Initial bounded
strategies:

- `continue-existing-fresh-callarg-local`: preserve the current assignment and
  callarg local while applying only safe structural reorderings available in the
  matched span.
- `fresh-local-product-count-order-swap`: move the digit-count statement across
  the column product/handoff pair when dependence checks prove it safe.
- `fresh-local-decl-demote-to-loop`: move a top-level fresh callarg declaration
  into the loop immediately before its assignment when the local is not used
  outside the loop.
- `fresh-local-block-scope-equivalent`: create a block-scoped equivalent only as
  a separate probe, not as the default continuation.

The existing issue #885 strategies can remain, but they should be generated only
when the source has an inline callarg cast or rowf-reused digit callarg. They
should not rewrite an already expression-good `digitf` local back to a hard-coded
`digit_frame_fpr` unless that is deliberately emitted as an exploratory variant.

## Diagnostics

Update orchestrator diagnostics for this family to expose the rejected state:

- `rowf_local`;
- `call_arg_local`;
- `call_arg_local_kind`;
- `has_existing_fresh_callarg_local`;
- `generated_strategies`;
- `rejection_reasons`.

Add specific rejection reasons instead of generic `source-pattern-not-found`:

- `separate-callarg-local-not-supported` before the fix, covered by a failing
  regression test;
- `fresh-callarg-local-continuation-unavailable` if a future source has an
  existing local but no safe structural continuation;
- `ambiguous-callarg-assignment`;
- `callarg-local-address-taken`;
- `callarg-local-used-after-loop`.

## Validation Summary

Keep the existing `debug target score-source` scoring semantics. The summary
layer should make false progress visible when transform validation is used:

- rank guarded partials by `expression_score` before raw `target_score`;
- preserve `false_positive_virtual_id_hit_count` in evidence;
- add a terminal note when every `callarg_local_structural_repair` candidate
  with raw target progress has expression-score regressions.

This belongs in `tools/melee-agent/src/search/cli/__init__.py`, inside or near
`_summarize_transform_validations`. The change is reporting-only.

## Integration Points

Primary production files:

- `tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`
  - extend the callarg structural case model and matcher;
  - add fresh-local continuation candidate generation;
  - remove the hard global `digit_frame_fpr` continuation rejection;
  - avoid hard-coded fresh-local names when an existing local is available.
- `tools/melee-agent/src/search/directed/transform_corpus/orchestrator.py`
  - add richer family diagnostics for separate rowf/callarg-local state.
- `tools/melee-agent/src/search/cli/__init__.py`
  - improve validation summary for expression-score false progress.

Conditional production files:

- `tools/melee-agent/src/search/directed/transform_corpus/registry.py`
  - update generated-probe wording only if the existing family description no
    longer covers fresh-local continuation.
- `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
  - update catalog wording only if registry text changes or a subfamily is
    created.
- `tools/melee-agent/src/search/directed/mutators.py`
  - no new mutator should be necessary if exact-span replacement remains enough.
    Touch only if a separate mutator key is chosen after review.

## Regression Tests

Add failing tests before production changes:

- `tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py`
  - a fixture based on `m04_digitf_local_callarg.c` where `rowf` scales
    `row_offset`, `digitf` is assigned from `(f32) digit`, and
    `HSD_JObjReqAnimAll(jobj, digitf)` is called;
  - assert the family emits at least one continuation probe;
  - assert generated probes preserve `digitf` for the default continuation;
  - assert no candidate rewrites the default fresh-local continuation to
    `digit_frame_fpr`;
  - assert unsafe cases reject address-taken `digitf`, use-after-loop `digitf`,
    and ambiguous callarg assignments.
- `tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py`
  - assert family diagnostics report `has_existing_fresh_callarg_local=true` and
    expose `rowf_local=rowf`, `call_arg_local=digitf`.
- `tools/melee-agent/tests/search/test_cli_smoke.py`
  - assert `plan-transforms --transform-family callarg_local_structural_repair`
    writes candidate paths for the fresh-local fixture.
- `tools/melee-agent/tests/test_source_transform_catalog.py`
  - assert validation summary preserves/ranks expression-score false positives
    for callarg-local structural validation.

## Non-Goals

- Do not add a new top-level `melee-agent` command.
- Do not change `debug target score-source` expression scoring.
- Do not auto-apply generated candidates to production source.
- Do not broaden the matcher to arbitrary call arguments; keep the exact
  `mnDiagram_DrawCellNumber`-style structural region.
- Do not touch issue state, staging, commits, installs, or
  `/Users/mike/.config/decomp-me` while implementing this issue.
