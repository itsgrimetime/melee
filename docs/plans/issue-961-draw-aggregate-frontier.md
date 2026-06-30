# Issue #961: Draw Aggregate Frontier Handoff

## Issue

`mnDiagram_DrawCellNumber` has three FPR force-phys targets:

- IG32 -> `f28` (`col_offset`)
- IG37 -> `f26` (`row_offset`)
- IG46 -> `f26` (pcode-only `fsubs`)

After #959/#960, single-IG node-set resume works for IG32 and IG37, but the
aggregate Draw frontier is still not actionable:

- coupled node-set-split can run CPU-bound past `--budget` without JSON output;
- solve-coloring can run force-vector probes but does not serialize the
  force-vector evidence;
- allocator-ceiling keeps reporting generic missing evidence instead of handing
  off to the remaining coupled/target-only route.

## Root Cause

The failure is at the handoff boundary between three tools, not inside one
candidate scorer.

`debug solve node-set-split --coupled` uses cooperative deadline checks inside
source generation. If generation is CPU-bound, the parent CLI cannot regain
control to write JSON. The coupled frontier also does eager expansion and slices
afterward, so transient work can exceed the final candidate cap.

`debug solve coloring --force-vector-probes` already has a
`DeriveInputs.force_vector_probe` field, but the data is dropped because
`Preconditions`, `SolveResult`, and `_solve_abstain_payload()` only carry
`node_set_delta`. The verifier also records a pcdump path and then deletes that
file, so allocator-ceiling could not consume the pcdump even if the JSON block
were added naively.

`debug solve allocator-ceiling` still gates target-only backprojection on legacy
evidence: force-vector match, node-set exhaustion, and transform-corpus
negative validation. It does not recognize Draw's completed single-IG node-set
evidence plus select-order
`degree-zero-fpr-case-c-source-exhaustion` as the terminal pcode-only FPR route,
and it does not emit the concrete coupled node-set or force-vector command when
that evidence is still missing.

## Implementation Plan

1. Make coupled node-set generation output-safe.
   Add a generation result contract with `patches`, `stop_reason`,
   `elapsed_seconds`, `budget_seconds`, and `generation_complete`. Stop coupled
   frontier expansion as soon as the next frontier reaches `max_candidates`.
   Preserve partial candidates on deadline expiry. Wrap generation with a hard
   watchdog so the CLI can emit exit-4 JSON even if generation is CPU-bound.

2. Reuse the #959 manifest/resume path for coupled generation.
   If budget expires before compile, write JSON with `stop_condition`,
   `pending_candidates`, `generated_candidate_manifest`, and a resume command.
   A run with no generated candidates should still emit a budget-exhausted JSON
   summary instead of producing no output.

3. Serialize solve-coloring force-vector evidence.
   Thread an optional diagnostics payload through `Preconditions` and
   `SolveResult`. Include `force_phys`, class-scoped physical `force_vector`,
   `force_vector_verify`, and `natural_pcdump` in abstain JSON. Add retained
   pcdump support to `_run_force_vector_auto_verify()` so a matching union probe
   leaves a valid forced pcdump for allocator-ceiling.

4. Teach allocator-ceiling the Draw frontier.
   Add parsing for select-order
   `terminal_exhaustion_summary.kind == "degree-zero-fpr-case-c-source-exhaustion"`
   and combine it with node-set-delta coverage. Treat IG32/IG37 as completed
   when their node-set summaries are exhaustive wrong-register/missing-target.
   Treat IG46's pcode-only FPR route as covered by the select-order terminal
   summary. If coupled node-set or force-vector evidence is missing, return a
   concrete next-step command. If force-vector match and retained pcdumps exist,
   run target-only backprojection and return source-actionable levers or a named
   practical ceiling.

## Regression Tests

Add tests before production changes:

- coupled node-set generation budget emits JSON and does not enter compile;
- coupled generation hard-timeout helper returns a summarizable budget result;
- coupled generation stops expansion at the candidate cap;
- solve-coloring abstain JSON includes `force_vector` and
  `force_vector_verify`;
- force-vector verifier can retain a union pcdump when requested;
- allocator-ceiling consumes a solve-coloring force-vector payload with retained
  pcdumps;
- Draw-shaped aggregate evidence reports concrete coupled/force-vector next
  steps instead of generic missing evidence;
- Draw-shaped evidence with force-vector pcdumps reaches target-only
  backprojection.

## Validation

Focused tests:

```bash
cd /Users/mike/code/melee/tools/melee-agent
pytest --no-cov \
  tests/test_node_set_split.py \
  tests/search/solver/test_solve.py \
  tests/search/solver/test_cli_solve.py \
  tests/test_match_iter_first.py \
  tests/test_allocator_ceiling.py \
  -q
python -m py_compile \
  src/mwcc_debug/node_set_split.py \
  src/search/solver/solve.py \
  src/cli/debug/__init__.py \
  src/mwcc_debug/allocator_ceiling.py
```

Live smoke should rerun coupled node-set, solve-coloring force-vector, and the
aggregate allocator-ceiling command for `mnDiagram_DrawCellNumber`. The final
aggregate must not remain a generic `missing-required-evidence` result when the
only missing item is one of the concrete handoff commands above.
