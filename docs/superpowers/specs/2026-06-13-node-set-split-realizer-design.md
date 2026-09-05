# Node Set Split Realizer Design

## Goal

Fix `debug solve node-set-split` so generated source candidates compile through
the existing repo-local `debug dump local` path, then broaden the candidate
generator enough to cover the loop live-range reshaping reports in issues #659
and #660.

## Scope

This design keeps the existing CLI surface. It changes only the internals of
`debug solve node-set-split` and its candidate generator. It does not add a new
parser, relax `dump local` path validation, or attempt a broad source-rewrite
framework.

## Temp Source Handling

Candidate `.c` files must be written under the active Melee checkout so
`debug dump local` accepts them. The command will create a unique temporary
directory under:

`build/mwcc_debug_cache/probes/node_set_split/`

The command will create the parent directory if needed, write each generated
candidate there, pass that path to `_node_set_split_compile_signature`, and
remove the per-run directory after evaluation. This preserves the existing
repo-path contract and avoids leaking candidate files across runs.

## Candidate Families

The generator keeps the existing alias-before-use and lifetime-preservation
families.

It adds declaration-order candidates by reusing the existing scoped declaration
helpers: `build_decl_order_candidates_for_scope`, `explain_decl_reorder_skip`,
and `reorder_decls_in_function_scope`. The node-set generator will focus this
family on the requested variable and bounded group/pair candidates that include
the requested variable. Unsafe initializer reorderings are skipped by the
existing dependency blocker.

It adds a conservative per-loop rename family. This family only emits a
candidate when the requested local has independent lifetimes in simple top-level
loops. Each selected loop must assign the variable before reading it, must not
take its address, must not use it in loop headers or updates, must not carry the
value into another loop, and must not read it after the renamed loop range. Loops
with nested blocks or nested loops that mention the variable are skipped. The
candidate adds one same-type declaration per renamed loop near the original
declaration and rewrites only that loop body to the new loop-local name.

It adds a narrow integer reassociation family for direct assignments to the
requested local. Only `var = a + b;` and `var = b + a;` shapes are considered,
where both operands are simple identifiers or integer constants. Calls, casts,
field/member accesses, array accesses, pointer expressions, unary operators,
increments, compound assignments, and multi-term expressions are rejected.

## Evaluation

All families flow through the existing evaluation gate. A candidate is
checkdiff-scored only after its pcdump moves the target IG to the requested
physical register and introduces no new spills. Wrong-register and spill
candidates remain reported but unscored.

## Tests

Tests cover the repo-local temp directory behavior, retention of existing
alias/lifetime candidates, new declaration-order candidates, positive and
negative per-loop rename cases, positive and negative integer reassociation
cases, and the existing gate that prevents wrong-register candidates from
running checkdiff scoring.
