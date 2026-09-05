# Node-Set Introduce-Binding Split Realizer

## Context

Issue #707 reports a recurring failure mode in node-set split steering: the
solver can identify a `node_set_delta` target, but the source attribution is an
expression such as `entries[i].stat_value`, `data->field`, or
`&sorted_names[i]` instead of a bindable local name. Existing node-set split
families only operate on an already declared source variable. That leaves
mixed rotations with one or more unbindable nodes either blocked or exhausted
with every candidate still in the wrong register.

## Goal

Extend node-set split candidate generation with a conservative
introduce-binding realizer. For a source expression that can safely be hoisted
to a typed local, generate candidates that:

1. introduce a named local for the expression at the use site,
2. rewrite that use to read the local,
3. run the existing alias/lifetime/decl-order/per-loop/reassociation split
   families against the introduced local, and
4. evaluate the original target IG/register objective exactly as today.

The feature must work through both `debug solve node-set-split --node-set-delta`
and `debug search plan-transforms --node-set-delta`.

## Non-Goals

- Do not infer arbitrary C expression types. If neither the delta nor the
  statement context supplies a safe type, keep the node skipped/blocked.
- Do not hoist expressions with calls, assignments, comma operators, casts,
  increment/decrement, or other visible side effects.
- Do not apply candidates by default. `--apply-best` remains the only apply
  path, and it still requires objective and checkdiff verification.
- Do not change the existing bindable-local behavior for GPR or FPR deltas.

## Design

Add optional source-expression fields to `NodeSetSplitRequest` so the existing
request type can describe both an already bindable local and an unbindable but
introducible source expression. The existing `var_name` path remains unchanged.
When `var_name` is missing, request parsing records the source expression,
source kind, source type when present, and a conservative inferred binding type
when possible.

Type admission is intentionally narrow:

- A delta-provided scalar or pointer type may be used after simple syntax
  validation.
- Otherwise, infer the type from a plain destination statement in the same
  function: `lhs = expression;` uses `lhs`'s local/parameter type, and
  `Type lhs = expression;` uses the declaration type.
- If the expression appears only in a call argument, control expression, macro,
  or an unsupported statement shape, no introduce-binding request is emitted.

Patch generation walks statement spans in the target function and finds exact
source-expression occurrences. Each occurrence must be standalone, must not be
an lvalue, must be side-effect free, and must not sit inside a short-circuit,
ternary, comma, assignment, increment, or same-line control-statement context
where hoisting would change whether the expression is evaluated. For a
declaration use, the patch emits an initialized temp declaration immediately
before the original declaration and rewrites the initializer. For a normal
statement, the patch emits a bare temp declaration at the enclosing block top,
assigns the expression immediately before the target statement, and rewrites the
expression occurrence to the temp.

Every safe binding site emits a binding-only candidate first. This is necessary
for initialized declarations such as `int out = data->field;`, where rewriting
to `int tmp = data->field; int out = tmp;` introduces a source-visible virtual
but does not give the existing alias mutator a non-declaration read of `tmp`.
When the introduced temp also has a normal read statement, the introduced source
then feeds the existing split generator with a synthetic request for the temp
name. Candidate IDs and summaries are prefixed with
`node-split-introduce-binding-ig...` so downstream reports identify the new
family. Coupled generation should compose normal and introduce-binding requests
through the same per-IG frontier rather than dropping unbindable but
introducible nodes.

All final `CandidatePatch` objects must rebuild touched ranges and hunks
against the original source, not the intermediate bound source. Transform probes
slice `span_text` and `replacement_text` from those ranges.

## CLI And Transform Routing

`debug solve node-set-split` should no longer exit immediately when a request
has no `var_name` if the request carries an introducible expression. It should
generate introduce-binding candidates and score them through the existing
objective/checkdiff pipeline. When no explicit target IG is supplied, normal
bindable requests still win, followed by the first introducible request, then
the first blocked request for diagnostics. If no introduce-binding candidates
can be materialized, the command should still exit blocked with a clear reason.

`plan-transforms --node-set-delta` should include introducible requests in its
node-set probe budget. Probe payloads should preserve the raw missing virtual
entry and expose the same request payload shape as bindable requests, while
non-introducible entries remain in `skipped_missing_virtuals`.

## Testing

Unit tests should cover:

- request parsing records field-expression binding metadata without pretending
  it is a bindable local,
- safe assignment and initialized-declaration contexts generate prefixed
  introduce-binding split candidates,
- initialized declarations emit an explicit binding-only candidate even when no
  normal read of the introduced temp exists,
- address-of cursor expressions such as `&sorted_names[i]` generate pointer
  bindings when the destination type is known,
- FPR/scalar expression temps such as `x_spacing + col_offset` generate typed
  bindings when the destination type is known,
- missing types, lvalue occurrences, calls, side effects, and unsupported
  expressions generate no candidates,
- coupled generation can compose one bindable local and one introduced binding,
- transform-corpus probes materialize an unbindable field expression instead of
  only reporting it as skipped, and
- direct CLI `node-set-split --node-set-delta` routes field-expression deltas
  into candidate generation.

Command-level checks:

- focused pytest for node-set split, solve CLI, and transform CLI tests,
- `python -m compileall -q tools/melee-agent/src`,
- `git diff --check`,
- `melee-agent debug solve node-set-split --help`,
- `melee-agent debug search plan-transforms --help`.

## Acceptance Criteria

- #707 is resolved when unbindable-but-typed source expressions produce
  verified node-set split candidates in both solve and transform paths.
- Non-introducible implicit temps remain explicitly skipped/blocked.
- Existing bindable-local node-set split behavior and tests remain unchanged.
