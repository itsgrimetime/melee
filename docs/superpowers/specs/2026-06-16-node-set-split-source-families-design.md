# Node-Set Split Source-Family Expansion Design

## Goal

Issue #732 reports that `debug solve node-set-split` exhausts its current
candidate set while every compiled candidate remains `wrong-register`, but
manual source edits in four untried families move register assignment. Extend
the node-set-split generator so it can mechanically try those source shapes and
bounded combinations of them.

The new families are:

- prologue-reorder: swap adjacent independent assignments;
- assignment-chain: replace a recomputed subexpression with an already assigned
  temporary of the same safe scalar type;
- operand-alias: bind one simple RHS operand to a fresh local and use that alias
  in one statement;
- block-scope: wrap adjacent assignment statements in braces as an MWCC
  source-shape probe.

The feature is complete when the solver emits these families, does not starve
them under default candidate caps, and either finds a new-family realization for
`mnDiagram_80241E78` or `8023FC28`, or records that all four new families and
their bounded combinations were triaged without improvement.

## Scope

Keep the implementation in `tools/melee-agent/src/mwcc_debug/node_set_split.py`
and tests in `tools/melee-agent/tests/test_node_set_split.py`. Do not add a new
CLI option or output schema. Existing `debug solve node-set-split` JSON already
includes candidate IDs and objective rows, which is enough to prove family
emission and realization.

This change must not depend on or overwrite unrelated dirty edits currently in
`tools/melee-agent/src/cli/debug/__init__.py`,
`tools/melee-agent/src/search/solver/solve.py`, or
`tools/melee-agent/tests/search/solver/test_solve.py`.

## Candidate Ordering

The solver evaluates candidates in list order and defaults to
`--max-candidates 16`. Appending high-volume families after existing aliases and
declaration-order probes would make the new families invisible in normal runs.

Add family classification and balanced ordering:

- `_node_set_candidate_family(candidate_id)` maps candidate IDs to families.
- `_order_node_set_patches_for_search(...)` interleaves candidates by family
  after all base and composite candidates are generated.
- New priority families are `combo`, `prologue-reorder`,
  `assignment-chain`, `operand-alias`, and `block-scope`.
- Single-request generation returns priority-balanced patches, so default CLI
  scoring sees at least one available new family before older high-volume
  families.
- Coupled generation applies the same ordering before taking `max_per_ig`
  candidates for a request. Raise the internal coupled default from 6 to 12 so
  the five priority families plus existing families can survive the per-request
  frontier cap; the user-facing CLI cap remains unchanged.

Candidate IDs and summaries must preserve family identity, including composite
constituent families, so JSON rows can be used for stop-condition evidence.

## Bounded Combinations

Issue #732 specifically calls out combined edits such as reorder + chain +
alias. A one-edit-per-request design is not sufficient.

Split generation into:

- a base pass that emits existing families plus the four new families;
- a bounded same-request composite pass that uses only the four new families.

The composite pass runs a bounded breadth-first search over one request:

- maximum depth 3;
- no repeated family in one composite chain;
- at most 2 candidate expansions per family per layer;
- at most 24 composite candidates total.

Each composite step re-runs the relevant family helper on the already patched
source, so the normal safety checks are reapplied to edited text. Composite
candidate IDs start with `node-split-combo-`, include the family chain, and add
a sequence or digest fragment to avoid collisions.

Coupled mode continues to compose one candidate per request per frontier layer,
but those per-request candidates may now be composites such as
`prologue-reorder+assignment-chain+operand-alias`.

## Shared Safety Model

Use conservative line-level source scanning based on the existing
`statement_order` transform-corpus guards:

- blank comments and literals before scanning;
- assign block IDs from immediate brace nesting;
- recognize direct simple assignment records and unique visible scalar bindings;
- require same immediate compound through matching block IDs and contiguous line
  offsets where adjacency matters.

Candidate regions abstain when they contain preprocessor directives, labels,
`case` or `default`, control-flow keywords, comments or order notes, calls,
member access, arrays, dereference, address-of, compound assignment,
increment/decrement, comma, ternary, logical operators, volatile declarations,
address-taken names, or unknown identifiers.

All rewrites use parsed byte or line offsets. Do not use raw global string
replacement.

## Family Rules

### Prologue Reorder

Swap two adjacent independent assignment records in the same immediate block
when the requested source variable appears in either statement. Require
distinct LHS names, no RHS dependency on the other statement's LHS, and only
safe scalar locals or parameters in both RHS expressions.

### Assignment Chain

Find an earlier assignment `tmp = expr;` and a later assignment whose RHS
recomputes the same `expr` as a subexpression, then rewrite only that occurrence
to `tmp`.

The earlier assignment must dominate the later one by source order in the same
immediate block. There must be no intervening writes to `tmp` or to any
identifier used by `expr`. `tmp` must have a unique safe scalar type. For FPR
requests, all identifier operands in `expr` must be the same floating scalar
type class as `tmp` (`f32`/`float` or `f64`/`double`). For GPR requests, operands
must stay within one compatible integer-ish type class without signed/unsigned
mixing. Ambiguous precision or conversion cases abstain.

The current master source for `mnDiagram_80241E78` already contains
`row_offset_adj = row_offset - 0.4f`, so assignment-chain tests must include a
separate recomputed-RHS fixture.

### Operand Alias

Choose one simple identifier operand in a safe assignment RHS. Insert a fresh
same-type alias declaration at the legal declaration site for that immediate
block, insert `alias = operand;` immediately before the target statement, and
replace only that operand occurrence in the target statement.

The operand must have a unique safe scalar binding. If the target statement
occurs before the block's legal declaration section ends, abstain instead of
creating mixed declaration/statement code.

### Block Scope

Wrap 1 to 3 adjacent safe assignment statements in the same immediate block:

```c
{
    a = b;
    c = d;
}
```

This is an MWCC source-shape probe only; it must not claim semantic C lifetime
changes. Do not move declarations into the new block. Reject regions containing
declarations, labels, control flow, preprocessor directives, comments/order
notes, or unsafe expressions.

## Tests

Add regression tests before implementation for:

- positive candidate emission for all four families;
- negative cases for dependency/order, intervening writes, calls, members,
  arrays, nested/control/preprocessor regions, mixed declarations, ambiguous
  precision, and signedness;
- same-request composite generation for reorder + chain + alias;
- family-balanced ordering under default single-request and coupled caps;
- unique candidate IDs when multiple occurrences exist in one statement or
  statement pair;
- rollback behavior when a helper raises after appending partial candidates;
- an `mnDiagram_80241E78`-like fixture for prologue-reorder, operand-alias, and
  block-scope, plus a recomputed-RHS fixture for assignment-chain.

Existing node-set-split tests must continue to pass.

## Verification

Run:

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_node_set_split.py -q
python -m compileall -q tools/melee-agent/src/cli tools/melee-agent/src/mwcc_debug
python -m src.cli debug solve node-set-split --help
```

For live smoke, run a bounded `debug solve node-set-split` probe on
`mnDiagram_80241E78`. If it does not produce a new-family or composite
realization, run the same bounded probe on `8023FC28`. Inspect JSON candidate
IDs and objective rows. Resolve #732 only when at least one new-family or
composite candidate realizes the target register, or when all four new families
plus bounded composites have been generated and triaged across both functions
with no improvement.
