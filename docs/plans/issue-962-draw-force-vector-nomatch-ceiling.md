# Issue #962: Draw force-vector no_match allocator ceiling

## Reviewed code

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_allocator_ceiling.py`
- `/Users/mike/code/melee/tools/melee-agent/src/search/solver/solve.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/search/solver/test_solve.py`
- `/Users/mike/code/melee/docs/plans/issue-961-draw-aggregate-frontier.md`
- `/Users/mike/code/melee/docs/superpowers/specs/2026-06-22-issue-961-draw-aggregate-frontier-design.md`

The issue artifacts are not present under `/Users/mike/code/melee/build`, so I
also inspected the report paths in `/Users/mike/.codex/worktrees/eeff/melee`.
They confirm the aggregate already has complete Draw frontier evidence:

- force-vector probes ran with `union.status == "no_match"` and return code 0;
- single node-set exhaustions for IG32 and IG37 are complete with no pending
  candidates;
- coupled node-set exhaustion is complete, exhaustive, unbounded, 94 evaluated,
  0 pending, and 0 realized;
- select-order FPR Case-C exhaustion is complete for targets 32, 37, and 46;
- allocator-ceiling reports only
  `force-phys verification with union status match` and asks to rerun
  `debug solve coloring --force-vector-probes`.

## Root cause

`allocator_ceiling.py` uses one predicate for two different meanings.

At `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py:123`,
`legacy_missing` requires:

```python
force_vector.get("ran") is True
and force_vector.get("union_status") == "match"
```

That is correct for target-only backprojection, because the backprojection path
needs a successful forced union and retained forced pcdump evidence. It is not
correct for the required-evidence gate. A completed force-vector union with
`status == "no_match"` is negative evidence, not missing evidence. After the
Draw node-set frontier is exhausted, asking for the same force-vector probe
again is a classifier bug.

The later backprojection code already has the stricter match-only concept in
`_matching_force_vector_mappings()` and `_is_matching_force_vector_mapping()`
at `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py:1214`.
The missing piece is a separate "force-vector probe evidence is complete"
predicate for the top-level evidence gate.

## Code change plan

1. In `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`,
   add a small helper near `_force_vector_status()`:

   - `_force_vector_probe_evidence_complete(force_vector, *, node_set_frontier, select_order_fpr_case_c) -> bool`
   - Return true for `ran == true` and `union_status == "match"`.
   - Return true for `ran == true` and `union_status == "no_match"` only when
     the Draw frontier is terminal: `node_set_frontier.complete is True` and
     `select_order_fpr_case_c.complete is True`.
   - Return false for `None`, `failed`, `timeout`, `inconclusive`, or a stale
     payload with `ran != true`.

2. Replace the hard match-only check at
   `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py:123`
   with that helper. Keep the existing missing-evidence text for genuinely
   missing or inconclusive force-vector evidence.

3. Add an explicit terminal branch in `classify_allocator_ceiling()` before the
   generic `elif not legacy_missing` fallback:

   - If the force-vector evidence is a completed `no_match`, Draw node-set
     frontier coverage is complete, select-order FPR Case-C exhaustion is
     complete, and no other required evidence is missing, return
     `status == "practical-ceiling"` with a new terminal reason such as
     `force-vector-no-match-after-draw-frontier-exhaustion`.
   - Clear `missing_evidence`.
   - Keep `source_shape_exhausted == true` via the existing select-order
     completion path.

   This avoids reporting the less precise `target-only-allocator-rotation`
   reason when target-only backprojection never ran because the forced union did
   not match.

4. Do not relax `_matching_force_vector_mappings()` or
   `_is_matching_force_vector_mapping()`. Those should remain match-only so
   `no_match` evidence is never used as a forced-pcdump source for target-only
   backprojection.

5. Update `_next_steps()` only if the new terminal reason needs clearer text.
   The default practical-ceiling text is acceptable, but a better terminal
   message would say to treat the current Draw source shape as exhausted because
   force-vector probes completed negatively after exhaustive single and coupled
   node-set evidence.

## Regression tests

Add or update tests in
`/Users/mike/code/melee/tools/melee-agent/tests/test_allocator_ceiling.py`:

1. Add `test_draw_force_vector_no_match_after_coupled_exhaustion_is_practical_ceiling`.
   Use `_draw_delta()`, `_draw_node_wrong(32)`, `_draw_node_wrong(37)`,
   `_draw_coupled_node_summary()`, `_draw_select_order_terminal()`, and a Draw
   force-vector payload whose `force_vector_verify.union.status` is
   `"no_match"`. Assert:

   - `status == "practical-ceiling"`;
   - `terminal_reason == "force-vector-no-match-after-draw-frontier-exhaustion"`;
   - `missing_evidence == []`;
   - no `next_steps` entry contains `--force-vector-probes`;
   - `force_vector.ran is True` and `force_vector.union_status == "no_match"`;
   - `node_set_frontier_coverage.complete is True`.

2. Keep `test_draw_aggregate_missing_force_vector_reports_concrete_command`
   unchanged. It validates that absent force-vector evidence still produces the
   concrete `debug solve coloring --force-vector-probes` continuation.

3. Update `test_force_vector_no_match_is_incomplete` rather than deleting it.
   Rename it to make the distinction explicit, for example
   `test_generic_force_vector_no_match_without_draw_frontier_is_incomplete`.
   Keep the generic `_solve_delta()`, `_node_wrong()`, and
   `_transform_negative()` evidence. Assert it remains incomplete. This prevents
   the fix from globally converting all `no_match` probes into ceilings without
   the coupled Draw frontier evidence.

4. Keep `test_force_vector_non_match_statuses_are_incomplete` for
   `inconclusive`, `timeout`, and `failed`. Add an assertion that the missing
   evidence still includes `force-phys verification with union status match`.

5. Add a stale-payload guard test:
   `test_draw_force_vector_no_match_without_run_remains_incomplete`. Set
   `force_vector_verify.ran = False` with `union.status = "no_match"` and assert
   the classifier still requests force-vector evidence.

No solver tests are required for this specific bug because
`/Users/mike/code/melee/tools/melee-agent/src/search/solver/solve.py` already
threads `solver_diagnostics` and the eeff artifact shows
`force_vector_verify` is serialized into the solve-coloring JSON. If a future
implementation changes serialization, keep the existing
`tests/search/solver/test_solve.py` diagnostics threading tests as coverage.

## Validation

Run focused tests from `/Users/mike/code/melee/tools/melee-agent`:

```bash
pytest --no-cov tests/test_allocator_ceiling.py -q
pytest --no-cov tests/search/solver/test_solve.py -q
python -m py_compile src/mwcc_debug/allocator_ceiling.py src/search/solver/solve.py
```

Optional live smoke after tests pass:

```bash
melee-agent debug solve allocator-ceiling \
  -f mnDiagram_DrawCellNumber \
  -e /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_961_rerun/draw_force_vector/solve_coloring_force_vector.json \
  -e /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_960_rerun/draw_ig32_resume/node_set_split_resumed.json \
  -e /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_960_rerun/draw_ig37_resume/node_set_split_resumed.json \
  -e /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_961_rerun/draw_coupled_score8/node_set_split_score8.json \
  -e /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_958_rerun/draw_live_fsubs/select_order.json \
  --json
```

Expected smoke result: no repeated `--force-vector-probes` next step, no
`force-phys verification with union status match` missing evidence, and a
terminal/practical-ceiling result for the current Draw source shape.
