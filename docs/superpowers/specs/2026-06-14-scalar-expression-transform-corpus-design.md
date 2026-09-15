# Scalar Expression Transform Corpus Design

## Context

Issue #691 covers four related record-only transform families:
`bool_int_accumulator_shape`, `abs_macro_expression_fold`,
`zero_compare_logical_not`, and `minmax_macro_ternary_shape`.  The shared root
cause is that the transform corpus can describe these scalar expression levers
but cannot materialize source probes for directed search or
`plan-transforms`.

Human review is intentionally skipped for this automation run per the issue
resolver instructions.  Independent Codex review is used instead for the design
and implementation checkpoints.

## Approach

Use the existing directed transform-corpus architecture.  Scalar anchors live in
`tools/melee-agent/src/search/directed/anchors.py`, exact-text mutators live in
`tools/melee-agent/src/search/directed/mutators.py`, and family wiring plus
planner exposure stays in
`tools/melee-agent/src/search/directed/transform_corpus.py`.

The first implementation is intentionally narrow.  It emits source probes only
when a single line or a small local accumulator pattern can be rewritten by
exact text and when duplicated-evaluation risks are rejected.  It does not try
to infer full C types, macro definitions, cross-TU contracts, or arbitrary
expression equivalence.  The scalar families must be added to the generic
fallback transform plan so `plan-transforms` can materialize them, and the
existing transform-corpus adapter must be able to filter the generated probes
for commands that already support `--transform-family`.

## Supported Shapes

`bool_int_accumulator_shape` gets one mutator:
`rewrite_bool_accumulator_as_int`.  It finds a `bool` or `BOOL` local
declaration in the target function, requires at least one `var |= expr;`
accumulation and a `return var;`, rejects address-taken or incremented forms,
and changes the declaration to `s32`.  It also rewrites direct `var != false`
and `var == false` comparisons to `var != 0` and `var == 0`, and direct
`var != true` and `var == true` comparisons to `var != 1` and `var == 1` in the
same function body.

`zero_compare_logical_not` gets one mutator:
`rewrite_zero_compare_logical_not`.  It rewrites simple top-level `if`/`while`
conditions from `expr == 0` to `!expr` and from `expr != 0` to `expr`.  The
expression is evaluated once in both forms, so simple calls such as
`call(gobj) == 0` are allowed for this family.  Conditions with assignments,
top-level comma operators, increments, decrements, logical conjunctions, or
nested comparisons are rejected.

`abs_macro_expression_fold` gets one mutator:
`rewrite_abs_ternary_to_macro`.  It rewrites simple ternary absolute-value
spelling such as `(x < 0) ? -x : x` to `ABS(x)`.  The operand must be a simple
identifier/member chain.  Calls, assignments, increments, comma expressions,
casts, dereferences, array indexes, and any form that would duplicate an unsafe
operand are rejected.  The implementation treats `ABS` as an available project
macro only for these narrow scalar operand forms.

`minmax_macro_ternary_shape` gets one mutator:
`rewrite_minmax_macro_to_ternary`.  It rewrites simple `MIN(a, b)` and
`MAX(a, b)` calls to explicit conditional expressions.  Both operands must be
simple identifier/member-chain scalar expressions so the generated ternary does
not duplicate evaluation with semantic changes.  The implementation treats
`MIN` and `MAX` as known project macros only for these narrow scalar operand
forms and does not claim support for dereference/arithmetic examples yet.

## Rejection Rules

The implementation rejects scalar anchors when:

- the candidate expression includes `++`, `--`, assignment, top-level comma,
  logical `&&`/`||`, or nested comparison operators;
- `ABS`, `MIN`, or `MAX` operands are calls, casts, dereferences, array
  indexes, or complex arithmetic;
- a boolean accumulator variable is address-taken, modified with increments, or
  lacks either an OR-accumulation or a direct return;
- a replacement would be identical or the exact payload line is absent;
- the anchor span does not identify the cited occurrence when identical lines
  repeat in the same function;
- the requested transform family is filtered out by `--transform-family` or
  the planner's allowed family set.
- a scalar family is requested through a named transform plan that does not
  include the family and no generic transform cluster is used.

## Tests And Verification

Regression tests cover metadata, materialization, and unsafe rejection:

- the four family ids have concrete mutator keys and no longer say
  `record-only`;
- a focused fixture materializes all four families through
  `generate_transform_probes`;
- unsafe duplicated-evaluation operands for `ABS` and `MIN/MAX` produce no
  probes;
- direct mutator tests verify exact replacement and absent-payload rejection;
- a command-level smoke runs plain `debug search plan-transforms` with a
  fixture source and confirms JSON/written probes include scalar-expression
  families;
- a second command-level smoke uses a supported source-shape scoring command
  with `--transform-family` to prove the generated scalar probes can be
  requested independently through the adapter path.
