# Fix Plan: Issue #960 Sort Implicit-Temp Frontier

## Issue

`mwcc-debug` allocator-ceiling aggregation kept reporting missing evidence for
`mnDiagram_SortNamesByKOs` even after the retained frontier had been exhausted.
The live evidence stack was:

- solve-coloring emitted `node_set_delta` for pcode-only implicit temps IG34 and IG44;
- node-set-split reported `no-coupled-probes` because there were zero bindable
  source variables;
- select-order exhausted materialized implicit-temp source probes;
- copy-survived repair for IG34 -> IG41 reached a terminal pointer-reset blocker.

The classifier still required force-vector verification, all-wrong-register
node-set evidence, and transform-corpus negative validation. Those requirements
are not applicable to this source shape because the missing virtuals are not
source-bindable and the solve-coloring fallback does not generate a force-vector
block.

## Root Cause

`allocator_ceiling.py` only recognized older residual Case-C completion routes:
blocked source spans plus simplify exhaustion, post-source-owner exhaustion,
common-subexpr coalesce exhaustion, and target-live-range exhaustion. It did not
parse terminal `copy_survived_repair` evidence and did not treat zero-bindable
implicit-temp node-set results as a separate "not source-splittable" condition.

`retained_frontier_triage.py` also ignored `copy_survived_repair`, so stale
retained lanes could remain visible after the final copy-survived pointer-reset
route had closed.

## Implementation Plan

1. Add narrow allocator-ceiling parsing for terminal `copy_survived_repair`
   payloads. Require `status == "terminal-blocker"` and a non-empty
   `terminal_blocker` so ordinary trace-copy evidence is not terminal.
2. Add zero-bindable implicit-temp detection that requires all missing
   node-set-delta virtuals to be pcode-only `implicit-temp` or
   `copy/coalesce-product` sources and a node-set-split payload with
   `stop_reason == "no-coupled-probes"` plus zero coupled requests.
3. Treat the residual Case-C path as complete only when all live-stack evidence
   is present: terminal select-order exhaustion, materialized implicit-temp
   actions, zero-bindable node-set split, and terminal copy-survived repair.
4. Keep generic missing force-vector and all-wrong-register behavior intact for
   other evidence shapes.
5. Add retained-frontier extraction for terminal `copy_survived_repair` and
   suppress matching-function retained/source-repair frontiers only when the
   terminal copy source IG intersects the old frontier targets.
6. Add regression tests for the positive stack, missing copy-survived evidence,
   zero-bindable node-set not being all-wrong-register exhaustion, and retained
   suppression scoping.

## Validation

Run:

```bash
cd /Users/mike/code/melee/tools/melee-agent
pytest --no-cov tests/test_allocator_ceiling.py tests/test_retained_frontier_triage.py tests/search/solver/test_cli_solve.py -q
python -m py_compile src/mwcc_debug/allocator_ceiling.py src/mwcc_debug/retained_frontier_triage.py
```

Smoke the live Sort evidence:

```bash
cd /Users/mike/code/melee
/opt/homebrew/bin/melee-agent debug solve allocator-ceiling \
  -f mnDiagram_SortNamesByKOs \
  -e /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_958_rerun/sort_solve_coloring_live.json \
  -e /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_958_rerun/sort_live_indexed_byte/select_order.json \
  -e /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_958_rerun/sort_live_node_set/node_set_split.json \
  -e /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_958_rerun/sort_coalesce_r34_r41_live.json \
  --json
```

Expected result: `status == "practical-ceiling"`,
`source_shape_exhausted == true`, `missing_evidence == []`, and
`residual_case_c_source_repair.terminal_stack ==
"live-implicit-temp-copy-survived"`.
