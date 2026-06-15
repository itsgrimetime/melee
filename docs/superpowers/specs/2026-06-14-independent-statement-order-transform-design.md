# Independent Statement-Order Transform Design

## Goal

Make `independent_statement_order` executable for a conservative class of adjacent statement swaps where a local read/write dependency proof shows the source order is semantically irrelevant.

## Scope

Add one concrete mutator, `swap_independent_adjacent_statements`, that swaps two adjacent non-declaration statements in the same compound block. This is the first executable step for the previously record-only family; it does not attempt arbitrary block scheduling or cross-window movement.

The analyzer only emits candidates for simple assignment statements:

- `local = expression;`
- compound assignments are rejected,
- the left-hand side must be a known source-local scalar variable declared earlier in the same compound block,
- the right-hand side may read only known same-block local variables and constants,
- unknown RHS identifiers are rejected instead of ignored,
- member, pointer, array, global, volatile, and macro-shaped writes are rejected.

Two statements are independent only when their write sets are disjoint, neither statement reads the other statement's writes, and neither statement has unknown memory or call effects.

## Safety Rules

The target body is rejected if it contains preprocessor directives, labels, `case`, `default`, or control-flow keywords. Candidate blocks are rejected before and after comment or intentional-order notes such as `fallthrough` and `preserve order`. Candidate lines are rejected if they contain comments, declarations, function calls, increment/decrement, pointer/member/array access on the left-hand side, `asm`, `volatile`, or words that commonly document intentional ordering.

The analyzer assigns compound-block ids from a comments-and-literals-blanked copy of the target function body and only pairs adjacent statement lines in the same concrete block. It trusts only prior unqualified, non-volatile scalar declarations in that same compound block. It does not move statements across declarations, braces, labels, blank/comment separators, control-flow constructs, or sibling block boundaries.

All emitted anchors contain exact `span_text` and `replacement_text` for the two-line region. The mutator validates the span before replacing it and returns `None` for stale spans.

## Integration

`independent_statement_order` is no longer record-only. It appears in generic `plan-transforms` output with `swap_independent_adjacent_statements` as a concrete mutator key. The generic fallback cluster includes it now that it can produce guarded probes.

The directed scorer treats `transform-corpus:independent_statement_order:*` provenance as an order-changing edit, matching the existing classification behavior for declaration reordering.

The family remains medium risk because statement order can affect codegen substantially, but the initial analyzer is intentionally narrow and abstains on unknowns.

## Tests

Regression coverage must prove:

- family metadata exposes `swap_independent_adjacent_statements` and no longer says record-only,
- the mutator swaps an exact validated two-line span and rejects stale spans,
- positive fixtures generate a swap for adjacent independent local assignments,
- dependency fixtures reject write/read, read/write, write/write, self-dependency pairs, unknown RHS identifiers, and RHS pointer/member/array reads,
- unsafe fixtures reject declarations, calls, global/member/pointer/array writes, control flow, labels/case/default, comments/fallthrough notes, preprocessor bodies, different-depth statements, and locals leaked from sibling blocks,
- scorer tests classify `transform-corpus:independent_statement_order:*` as an order-change edit,
- generated probes preserve statement spans, read/write sets, movement direction, family id, mutator key, and probe id in provenance,
- command-level unfiltered `plan-transforms --write-probes --json` can materialize a candidate file through the generic cluster.
