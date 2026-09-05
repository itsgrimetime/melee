# Draw Aggregate Frontier Handoff Design (#961)

## Problem

The Draw FPR frontier spans three related targets in
`mnDiagram_DrawCellNumber`:

- IG32 `col_offset` wants `f28`;
- IG37 `row_offset` wants `f26`;
- IG46 pcode-only `fsubs` wants `f26`.

Single-IG node-set resume now works, but the aggregate workflow still cannot
handoff terminal evidence cleanly:

1. coupled node-set generation can exceed `--budget` before producing JSON;
2. solve-coloring force-vector probes are not serialized into abstain JSON;
3. allocator-ceiling does not combine completed node-set, force-vector, and
   select-order terminal evidence into a concrete source-actionable or terminal
   classification.

## Design Goals

- Preserve existing commands; do not add a new command.
- Make coupled node-set budget exhaustion observable and resumable.
- Serialize force-vector evidence in a form allocator-ceiling can consume.
- Keep generic allocator-ceiling safety intact; only recognize Draw-like
  terminal evidence when the source and target coverage match.
- Prefer concrete next-step commands over generic missing-evidence text.

## Coupled Node-Set Contract

Coupled source generation needs a first-class result instead of a bare patch
list:

```python
NodeSetGenerationResult(
    patches=list[CandidatePatch],
    stop_reason=None | "budget-exhausted" | "candidate-limit",
    elapsed_seconds=float,
    budget_seconds=float | None,
    candidate_limit=int | None,
    generation_complete=bool,
)
```

`generate_coupled_node_set_split_patches()` should stop expanding a request as
soon as `next_frontier` reaches `max_candidates`. It should not expand all
parents and slice afterward. If a deadline expires after complete candidates
exist, return those candidates plus `stop_reason="budget-exhausted"` rather
than discarding the frontier.

`solve_node_set_split_cmd` should wrap generation with a hard budget watchdog.
When generation times out before any compile, emit a normal node-set summary:

- `status="exhausted"`;
- `stop_condition.kind="budget-exhausted"`;
- `exhaustive=false`;
- `coupled_requests` and `shared_source_var` when applicable;
- `generated_candidate_manifest` and `pending_candidates` when candidates were
  produced;
- a `resume_command` if a manifest exists.

This makes the no-compiler, CPU-bound failure mode visible to both users and
allocator-ceiling.

## Force-Vector JSON Contract

Solve-coloring should carry an optional diagnostics payload through
`Preconditions` and `SolveResult`:

```json
{
  "force_phys": {"32": 28, "37": 26, "46": 26},
  "force_phys_csv": "1:32:28,1:37:26,1:46:26",
  "force_vector": "class1:ig32:phys=f28,class1:ig37:phys=f26,class1:ig46:phys=f26",
  "natural_pcdump": ".../live_current.pcdump.txt",
  "force_vector_verify": {
    "ran": true,
    "union": {
      "status": "match",
      "pcdump": ".../retained-union.pcdump.txt"
    },
    "probes": []
  }
}
```

The `force_vector` string describes the desired physical target map. The actual
probe entries inside `force_vector_verify.union.entries` may be iter-first or
other override forms; allocator-ceiling uses the physical map as the target and
the retained union pcdump as proof that the target can be forced.

`_run_force_vector_auto_verify()` should retain pcdumps only when requested.
Default cleanup remains unchanged for lightweight callers, but solve-coloring
JSON intended for allocator-ceiling must keep the matching union pcdump. A
payload that names a deleted pcdump is not valid evidence.

## Allocator-Ceiling Frontier Model

Allocator-ceiling should build a per-target frontier summary from:

- `node_set_delta.missing_virtuals`;
- single/coupled node-set summaries;
- solve-coloring force-vector diagnostics;
- select-order terminal exhaustion summaries;
- target-only backprojection evidence.

For Draw:

- IG32 and IG37 are source-bindable and covered when their node-set summaries
  are exhaustive with only `wrong-register` or `missing-target` outcomes.
- IG46 is pcode-only and covered by select-order
  `degree-zero-fpr-case-c-source-exhaustion` when the terminal summary's
  `force_phys_targets` include the same target map.
- Coupled node-set evidence is still required when two or more bindable targets
  remain and no coupled summary exists. If it is missing, allocator-ceiling
  should return a concrete `debug solve node-set-split --coupled ...` command.
- Force-vector union evidence is required before target-only backprojection. If
  it is missing, allocator-ceiling should return a concrete
  `debug solve coloring --force-vector-probes ...` command.

Once coupled node-set, force-vector, and select-order terminal evidence are all
present, allocator-ceiling can run target-only backprojection. If source levers
are found, the result is `actionable`. If no source-visible lever remains and
all source-shape families are terminal, the result is a named
`practical-ceiling`, not generic missing evidence.

## Test Matrix

- Coupled generation budget expiry emits JSON before compile.
- Coupled generation hard timeout is summarized by the parent CLI.
- Coupled frontier expansion stops at the candidate cap.
- Solve-coloring abstain JSON includes the force-vector diagnostics payload.
- Retained union pcdumps exist when force-vector retention is requested.
- Allocator-ceiling consumes force-vector diagnostics with retained natural and
  forced pcdumps.
- Draw-shaped evidence with no force vector returns the exact force-vector
  command.
- Draw-shaped evidence with no coupled summary returns the exact coupled
  node-set command.
- Draw-shaped evidence with a bounded coupled summary returns `bounded` and its
  resume command.
- Draw-shaped complete evidence reaches target-only backprojection or a named
  practical ceiling.

## Non-Goals

- No changes to `src/melee/mn/mndiagram.c`.
- No new allocator solver.
- No blanket rule that any select-order failure equals transform-corpus
exhaustion. The terminal select-order summary must be the Draw-style
`degree-zero-fpr-case-c-source-exhaustion` and cover the same force-phys
targets.
