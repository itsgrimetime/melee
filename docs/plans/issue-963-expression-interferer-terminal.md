# Issue #963 Plan: Close Expression-Interferer Generated-Family Loops

## Goal

Resolve issue #963 by making `expression-interferer-repair` recognize that the
current concrete row/product generated families have already exhausted the
existing post-bridge support-order route. The fixed command should emit a hard
`post_bridge_terminal_summary` and blocked `source_generation` instead of
regenerating the same probes.

## Files

- `tools/melee-agent/src/mwcc_debug/expression_interferer_repair.py`
- `tools/melee-agent/tests/test_expression_interferer_repair.py`
- `docs/superpowers/specs/2026-06-23-issue-963-expression-interferer-terminal-design.md`
- `docs/plans/issue-963-expression-interferer-terminal.md`

## Steps

1. Add private concrete coverage tuples in
   `expression_interferer_repair.py`.
2. Add `_attempted_routes_for_post_bridge()` that calls `_attempted_route_set()`
   and adds the logical `non_satisfied_select_order` route only when full
   concrete coverage is present.
3. Keep `row_fsubs_owner_repair` independently required by the existing
   `_POST_BRIDGE_EXHAUSTED_ROUTES` check.
4. Add a direct regression for live-style attempted families:
   `build_terminal_summary()` emits `post_bridge_terminal_summary`, and
   `generate_source_repair_candidates()` blocks with no candidates.
5. Add negative regressions for missing `row_fsubs_owner_repair`, missing
   `retained_fpr_case_c_target_live_range_repair`, missing one support family,
   and retained-only coverage.
6. Run targeted tests:
   `PYTHONPATH=tools/melee-agent pytest --no-cov tools/melee-agent/tests/test_expression_interferer_repair.py -q`.
7. Run the allocator-ceiling expression terminal tests:
   `PYTHONPATH=tools/melee-agent pytest --no-cov tools/melee-agent/tests/test_allocator_ceiling.py::test_expression_interferer_terminal_is_practical_ceiling tools/melee-agent/tests/test_allocator_ceiling.py::test_expression_interferer_terminal_missing_route_is_incomplete_with_precise_gap -q`.
8. Replay the live Draw command using the scored `*.score.json` artifacts and
   live-style attempted families. Verify JSON contains
   `post_bridge_terminal_summary`, `source_generation.status == "blocked"`, and
   no generated candidates.

## Risks

The main risk is premature terminal closure if partial concrete-family coverage
is normalized too broadly. The fix avoids that by requiring full concrete
support-family coverage and by leaving the existing scored-no-progress and C2
bridge evidence gates unchanged.
