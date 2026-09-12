# Transform Corpus Mutator Batch Design

## Context

Issues #673-#680 all have the same root cause: mining job `88baa039`
promoted repeated source-transform families into `DEFAULT_TRANSFORM_FAMILIES`,
but those families still have empty `mutator_keys`, so `debug search
plan-transforms` can only describe them as catalogue knowledge. It cannot
materialize source probes for agents to compile, validate, or record.

The initial implementation should be deliberately narrow. The directed
transform corpus is a probe generator, not a C refactoring engine. It should
only emit candidate source when local syntax and proof evidence are strong
enough to avoid broken source or semantic drift. Unsupported mined aliases stay
unmaterialized until a later proof helper exists.

Human review is intentionally skipped for this automation run per the issue
resolver instructions. Independent Codex review is used instead before and
after implementation.

## Approach

Add conservative source-shape anchors in
`tools/melee-agent/src/search/directed/anchors.py`, exact-text mutators in
`tools/melee-agent/src/search/directed/mutators.py`, and family wiring in
`tools/melee-agent/src/search/directed/transform_corpus.py`.

The generic fallback cluster may advertise the newly actionable family ids, but
materialization must remain proof-gated. Syntax-local low-risk transforms can
be emitted from body anchors. Return, assert, data-symbol, global-alias,
numeric-cast, and raw-struct rewrites require additional local proof before a
candidate is emitted.

## Supported Initial Shapes

The first pass supports one or two safe shapes per requested family:

- `comma_operator_noop_expression_shape`: wrap a simple assignment RHS as
  `(0, expr)` when the RHS is a simple expression, has no top-level comma, and
  is not already comma-wrapped.
- `empty_do_while_barrier`: insert `do { } while (0);` between adjacent simple
  expression/call/assignment statements, avoiding labels, `case/default`,
  declarations, control-flow statements, and preprocessor lines.
- `assignment_expression_temp_seed`: fold an adjacent `tmp = expr; if (tmp !=
  NULL) {` or `while` condition into `if ((tmp = expr) != NULL) {`, only when
  the seed expression is simple and there are no intervening uses.
- `numeric_cast_shape`: elide a redundant call-argument cast only when a
  source-local prototype proves the formal parameter has the same numeric type
  as the cast and the casted expression is a simple scalar expression. Mixed
  arithmetic, nested casts, signedness changes, pointer casts, aggregate casts,
  callback casts, and function-pointer casts are rejected.
- `switch_case_order_default_shape`: swap two adjacent self-contained switch
  arms when each arm is a simple `case`/`default` body ending in `break;` and
  contains no declarations, labels, nested switch, gotos, or fallthrough
  comments.
- `assert_macro_expansion_shape`: collapse exact explicit asserts of the form
  `if (x == NULL) __assert("file.c", line, msg);` into
  `HSD_ASSERTMSG(line, x, msg);` only when the asserted file basename matches
  the planned source file basename. `HSD_ASSERT` is not used because it changes
  the message to `#cond`.
- `void_to_value_return_shape`: convert a `static void` function with a final
  plain helper-call statement into a scalar-returning function that forwards
  that helper result. A source-local helper prototype/definition must prove the
  scalar return type; the target signature and final statement are both edited.
- `string_literal_data_blob_field_shape`: replace a string literal argument
  with a source-local `symbol.field` expression only when a visible initialized
  struct object has a string field initialized to exactly the same literal
  bytes and that literal is unique among candidate fields.
- `global_pointer_alias_shape`: insert a typed pointer alias for a source-local
  global object and rewrite repeated `global.field` accesses to `alias->field`
  only when the global type declaration is visible in the same source and no
  alias-name collision exists.
- `raw_pointer_offset_struct_field_shape`: rewrite a narrow byte-offset cast
  expression such as `*(Vec3*) ((u8*) gp + 0xE0)` to `gp->field` only when a
  source-local struct layout proves the field offset and field type exactly.

The final two families share issue #679, so both string-data and global-alias
proofs can live in the same small source-local proof helper area.

## Rejection Rules

Anchors must not be yielded for:

- expressions with obvious side effects that would move evaluation order, such
  as calls, `++`, `--`, assignments, or top-level comma operators, except for
  the specific call/statement shapes the family owns;
- macro-heavy or preprocessor-adjacent regions;
- labels, `case`, `default`, `goto`, fallthrough comments, or scope-changing
  declarations near statement/switch transforms;
- pointer/function casts in numeric-cast mutators;
- assert conditions with calls, dynamic messages, non-`NULL` tests, or extra
  statements;
- return forwarding when helper return type cannot be proven locally;
- string/data aliases when duplicate literal bytes or unmodeled data offsets
  make identity ambiguous;
- struct offset rewrites when layout, offset, field type, or base pointer type
  is not locally recoverable.

## Tests And Verification

Regression tests should cover each family at three levels where practical:

- metadata wiring: requested family has a concrete `mutator_keys` entry and no
  longer says `record-only`;
- mutator behavior: exact positive source text plus absent/unsafe rejection;
- planner behavior: `generate_transform_probes` materializes candidate text
  from a focused fixture and keeps edits inside the target function.

The command-level smoke check should run `debug search plan-transforms` with a
fixture source and `--write-probes`, proving the CLI exercises the same
materialization path as agents use.
