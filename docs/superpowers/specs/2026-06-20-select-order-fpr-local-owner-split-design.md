# Select-Order FPR Local Owner-Split Design

Date: 2026-06-20
Issue: #869

## Context

`debug select-order-search --class 1` can now carry FPR target evidence from
node-set-split into the retained-source select-order bridge. In the current
`mnDiagram_DrawCellNumber` report, the bridge finds window-order fallback leads
and source attributions for the contested FPR locals:

- `ig37` maps to `row_offset`.
- `ig32` maps to `col_offset = y_spacing_alias_32_0 * (f32) col`.

The existing planner only materializes a normal source move when
`statement_move.extract_movable_units` accepts the local assignment. That
conservative classifier rejects product/cast RHS shapes, so a visible and
useful float local write is reported as `no-movable-local-write` and no
window-order source probes are emitted.

## Approaches

The chosen approach is to extend the existing window-order source planner with
a local FPR owner-split fallback. When a source-attributed local is a scalar
float local and its unique assignment is a simple side-effect-free expression,
split that assignment into a fresh typed synthetic local and the original local
assignment. This reuses the same probe materialization path already used for
synthetic FPR temps.

An alternative would loosen `statement_move.classify_movable` so product
expressions are movable. That is riskier because `statement_move` is shared by
general statement-order search and intentionally treats `*` and casts
conservatively.

A second alternative would add a separate select-order local-write command.
That would duplicate scoring, beam composition, source restore, and JSON
summary behavior already present in `debug select-order-search`.

## Design

`tools/melee-agent/src/search/directed/window_order_source.py` will stay the
single source planner for window-order fallback leads.

For source attributions with `kind == "local"`:

1. Keep the current direct move path first. If `source_line` is present, only a
   movable write whose line range contains that line may satisfy the direct
   move path; otherwise continue to the local owner fallback. If `source_line`
   is absent, exactly one movable write may generate the existing hoist/sink
   probes and diagnostics.
2. If no matching movable write exists, look for a visible assignment to the
   attributed local. This ownership pass must record simple local assignments
   even when their RHS is later rejected as unsupported, so diagnostics can
   distinguish visible unsafe RHS from missing ownership. A matching
   `source_line` may disambiguate one assignment among multiple writes. When
   `source_line` is absent or stale, only a single function-wide assignment is
   accepted; multiple assignments report
   `local-source-owner-no-unique-assignment`.
3. Require an assignable scalar float declaration whose normalized type is
   exactly `f32`, `float`, or `double`. `const`, `static`, pointer, array, and
   multi-declarator forms are rejected with a local-owner blocker rather than
   copied into the synthetic declaration.
4. Require a single-line assignment with a side-effect-free RHS. The accepted
   RHS grammar is one term or one binary expression using `+`, `-`, or `*`.
   A term is an identifier, dotted field read, numeric literal, float literal,
   or a cast of one of those terms such as `(f32) col`. Parenthesized compound
   expressions, unary increments, calls, assignments, comma expressions,
   ternaries, address-taking, pointer dereference, `->`, array indexing, and
   unknown non-local identifiers are rejected.
5. Materialize the owner split with the existing synthetic-owner split helper:
   introduce a fresh local of the same type, assign it the split expression,
   then assign the original local from the fresh local.
6. Attach a `synthetic_source_probe` payload with handler
   `local-fpr-owner-split`, the owner local, split expression, line range, and
   generated local name.

If the assignment is visible but cannot be split, the lead diagnostic must name
a concrete terminal blocker such as `local-source-owner-nonfloat`,
`local-source-owner-unsupported-rhs`, or `local-source-owner-no-unique-assignment`
instead of the generic `no-movable-local-write`.

The FPR synthetic-temp path should also accept casted terms in multiply and
subtract expressions by splitting the whole arithmetic RHS. The existing `lfs`
path remains the only path that may extract a cast subexpression from a larger
RHS.

The select-order JSON diagnostic note must be updated: product expressions are
no longer only covered by transform-corpus probes when they are visible
assignable float local owners.

## Data Flow

1. `debug select-order-search` builds the class-1 fallback and source
   attribution map.
2. `plan_window_order_source_probes` receives fallback leads, source text, and
   attributions.
3. The local attribution branch first attempts normal movable write probes.
4. When the normal move path has no movable unit, the local owner-split fallback
   checks the visible assignment and creates focused window-order source probes.
5. The existing select-order scorer, beam loop, JSON probe list, and
   `source_bridge_summary` consume those probes without a new CLI surface.

## Testing

Focused regression tests should cover:

- a class-1 local attribution for
  `col_offset = y_spacing_alias_32_0 * (f32) col` materializes a
  `window-order-source-steering` probe instead of reporting
  `no-movable-local-write`;
- the probe diagnostic/action payload includes `local-fpr-owner-split` metadata
  and a source diff;
- unsupported visible float assignments report a specific local-owner blocker;
- existing movable local-write behavior is unchanged;
- FPR synthetic-temp product matching accepts casted terms.

Command smoke checks should include the focused pytest tests and
`melee-agent debug select-order-search --help`. If the reported retained source
and pcdump artifacts are present locally, run the bounded reporter command and
confirm `listed_source_probes` becomes nonzero with full `target_score.virtuals`
preserved in scored variants.
