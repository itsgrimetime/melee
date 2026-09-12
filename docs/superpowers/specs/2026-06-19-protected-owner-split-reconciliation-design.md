# Protected Owner-Split Reconciliation Design

## Context

Issues #849 and #850 share one allocator-tooling gap: select-order search can
collect protected-hit and complement-hit evidence, but the report still centers
one primary orientation. When the opposite protected orientation is the
source-actionable one, the matcher has to dig through nested groups to find it.
For Draw FPRs, select-order also emits materialized owner-split node-set deltas
that node-set-split cannot turn into probes when the synthetic owner expression
is only used as a safe call argument.

## Goals

- Surface every protected/complement orientation at the top of the
  `protected_complement_repair` summary, including which orientations are
  source-actionable and where their materialized node-set deltas live.
- Allow node-set-split to introduce typed bindings for safe expression
  statement call arguments such as `col_offset` in
  `HSD_JObjSetTranslateX(... + col_offset)`.
- Keep the heavy compile/scoring path inside node-set-split. Select-order
  should report and materialize source-actionable deltas, not compile all of
  them inline.
- Preserve existing JSON fields and behavior for existing consumers.

## Non-Goals

- Generic expression lifting across arbitrary statements.
- Binding expressions from statements with assignments, increments,
  short-circuit operators, ternaries, or other side effects.
- Changing matcher source files or decompilation code.

## Design

### Orientation Reconciliation Lanes

`_select_order_protected_complement_summary` will continue to choose a primary
orientation for backward-compatible fields. It will also emit compact
`orientation_reconciliation_lanes` records, one per protected-hit seed group.
Each record includes:

- group index and seed label
- status/reason
- protected registers and complement targets
- terminal blockers
- causal lane status, actionable target IDs, scored/materialized candidate
  counts, and materialized candidate labels
- whether the orientation is source-actionable
- mixed source repair status and materialized node-set target IDs when present

`source_actionable_orientations` will contain the subset of orientation lanes
that have a causal materialized candidate or a ready mixed-source repair plan.
This makes split root causes like Sort #849 visible without changing the nested
`groups` payload that carries full source hunks and detailed diagnostics.

### Safe Call-Argument Binding

`_binding_context_for_span` will add a third binding mode for expression
statements that are not simple assignments. The existing patch builder already
supports non-declaration modes by declaring a binding at block top, assigning it
immediately before the statement, and rewriting the selected occurrence.

The new mode is accepted only when:

- the statement starts on a plain line
- the source expression is safe to bind
- the expression appears in the statement
- the statement contains no side-effect markers or control-flow-sensitive
  operators
- the fallback source type normalizes to a safe binding type

This is intentionally conservative. It covers Draw's function-call owner split
while rejecting statements such as `use(col_offset, col_offset = other);`.

## Validation

- Regression tests for call-argument binding generation and side-effect
  rejection in `test_node_set_split.py`.
- Regression tests for source-actionable orientation lane reporting in
  `test_select_order_search.py`.
- Focused CLI smoke: replay the Draw IG38/IG46 materialized node-set delta with
  zero compile budget and verify node-set-split generates candidates instead of
  returning `no-coupled-probes`.
