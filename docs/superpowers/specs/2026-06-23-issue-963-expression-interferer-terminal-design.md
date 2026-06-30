# Issue #963 Design: Expression-Interferer Post-Bridge Terminal Closure

## Context

`debug suggest expression-interferer-repair` already has a terminal handoff for
post-bridge expression repair exhaustion. When scored candidates show no
expression progress and attempted routes include both
`row_fsubs_owner_repair` and `non_satisfied_select_order`, it emits
`post_bridge_terminal_summary.kind ==
no-expression-progress-after-row-fsubs-and-support-orders`. Source generation
then blocks instead of re-emitting candidates, and allocator-ceiling consumes the
same terminal shape as `expression-scored-fpr-allocator-ceiling`.

Issue #963 is a naming/coverage gap in that existing path. The live Draw
workflow records concrete generated families in `attempted_families`:

- `retained_fpr_case_c_target_live_range_repair`
- `protected_expression_row_product_generation`
- `row_fsubs_owner_repair`
- `product_operand_ownership`
- `row_offset_first_scaled_ownership`
- `product_sink_ownership`
- `row_offset_sink_branch_ownership`
- `digit_guarded_statement_motion`

Those names represent the same exhausted post-bridge source-generation route,
but `_attempted_route_set()` only recognizes the older logical route name
`non_satisfied_select_order`. The repair summary therefore remains `blocked`
without `post_bridge_terminal_summary`, and `source_generation` emits the same
families again.

This is route-level evidence, not per-candidate proof. It means the workflow has
driven each named source-generation family through scoring as a family. The
existing candidate assessments still provide the no-expression-progress proof.

## Options Considered

### Recommended: Normalize Concrete Families Into Existing Routes

Keep the current terminal kind and allocator-ceiling contract. Add an internal
coverage set for concrete expression source-generation families. When the
retained target-live-range family and all required support families are present
in `attempted_families`, synthesize the logical
`non_satisfied_select_order` route for the post-bridge terminal check. Keep
`row_fsubs_owner_repair` as a separate required route.

This is the lowest-risk fix because it only teaches the existing terminal path
about the names produced by the current generator. It does not create a second
terminal schema or change allocator-ceiling evidence parsing.

### Alternative: Add a New Terminal Summary Kind

Emit a new terminal kind specifically for generated row/product family
exhaustion. This would be more explicit, but it would require allocator-ceiling
support, retained-frontier triage support if needed later, and duplicate
evidence rules already represented by the current post-bridge terminal.

### Alternative: Generate a New Fallback Family

After concrete family exhaustion, produce another ranked source family. The
issue evidence says the known target-live-range and row/product source families
were exhausted with zero expression hits and no accepted protected expression
candidate. Adding an unproven family would prolong the loop instead of closing
it.

## Design

Add a private tuple in
`tools/melee-agent/src/mwcc_debug/expression_interferer_repair.py` for the
concrete family coverage that collectively closes the post-bridge support-order
route:

- `retained_fpr_case_c_target_live_range_repair`
- `protected_expression_row_product_generation`
- `product_operand_ownership`
- `row_offset_first_scaled_ownership`
- `product_sink_ownership`
- `row_offset_sink_branch_ownership`
- `digit_guarded_statement_motion`

Add a new private helper for the post-bridge terminal check:

```python
def _attempted_routes_for_post_bridge(attempted_families: Sequence[str]) -> set[str]:
    ...
```

It calls `_attempted_route_set()` to preserve the current raw normalization
behavior, then adds `non_satisfied_select_order` only when the full concrete
coverage set above is present. Existing old-style callers that pass
`non-satisfied-select-order` continue to work.

Do not add the synthetic route in `_attempted_route_set()` itself. Other
callers should keep seeing only raw normalized family names.

Do not require `paired_row_product_recombine` for this terminal. That family is
an optional recombine route derived from the row/product primitives and is
tracked separately through `recombine_status`. The terminal remains gated by
the required concrete family coverage, no expression progress in scored
candidates, and ready C2 bridge evidence.

`_post_bridge_expression_exhaustion()` remains responsible for the actual stop
condition:

- both required logical routes are covered,
- no candidate is a primary success,
- no candidate has expression progress, and
- the remaining blocker has ready Case C2 sticky-pool bridge evidence.

When those conditions hold, the existing `post_bridge_terminal_summary` is
emitted. `generate_source_repair_candidates()` then sees that terminal summary
and returns `source_generation.status == "blocked"` with no candidates and the
existing suppressed-family list.

## Tests

Update `tools/melee-agent/tests/test_expression_interferer_repair.py`.

Add a regression where live-style `attempted_families` with full concrete
coverage emits `post_bridge_terminal_summary` and blocks source generation.

Add negative regressions for missing coverage:

- missing `row_fsubs_owner_repair`;
- missing `retained_fpr_case_c_target_live_range_repair`;
- missing one support family; and
- retained-only coverage.

Each case must not emit `post_bridge_terminal_summary`; source generation stays
available for incomplete coverage.

Keep the existing old logical route tests unchanged.

## Out of Scope

This does not add a new source-generation family. It does not change the JSON
schema consumed by allocator-ceiling. It does not reinterpret individual score
summary rows; the existing candidate assessment still decides whether scored
probes made expression progress.
