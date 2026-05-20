# Nested-block-local awareness — design spec

**Feature:** Make the mwcc-debug symbol bridge aware of locals declared inside
nested `{...}` blocks (not just function top), so var-to-virtual /
virtual-to-var / future scope-aware mutations can target the variables the
allocator actually colored.

**Status:** Phase 1 of two.

**Phase 1 (this spec):** Tree-sitter rewrite of the bridge core, plus
scope-aware lookups. Public dataclasses gain a `scope_path` field.

**Phase 2 (separate spec, follow-up):** scope-aware mutations
(`mutate insert-alias`) and enumeration (`enumerate-decl-orders`). Defers
until Phase 1 lands and the AST surface is stable.

## Motivation

The heartbeat agent's `fn_80248A78` matching is blocked at 99.6% by a
register-allocation swap involving `cursor_row` — a local declared inside
the cursor-setup nested block. Today:

- `var-to-virtual cursor_row` returns "variable not found".
- `virtual-to-var 34` returns the low-confidence top-level `frame` guess.
- `mutate insert-alias --var cursor_row` fails the same way.
- `enumerate-decl-orders` only considers top-level locals — the actual
  interesting swap candidates (`cursor_jobj`, `row_0_jobj`, etc.) are
  unreachable.

The current regex parser in `symbol_bridge.py` explicitly says at
`_top_level_statements`: "Nested-block contents are returned as a single
statement-sized chunk (we DON'T descend into them in v1)." This spec
removes that limitation.

## Architecture

Three new modules + one rewrite, all in
`tools/melee-agent/src/mwcc_debug/`:

- **`ast_walker.py`** (new, ~250 lines) — tree-sitter façade. Parses C
  source via `tree-sitter` + `tree-sitter-c` (already project deps).
  Exposes `walk_function(source, fn_name) -> list[LocalDeclNode]`.
  One file, one purpose. No regex.
- **`symbol_bridge.py`** (rewrite) — keeps the same public API. Drops
  `_top_level_statements`, `_strip_strings_and_comments`,
  `walk_local_decls`, `_looks_like_decl`, the `_skip_initializer` /
  `_skip_array_brackets` helpers, and most regex constants. Shrinks from
  ~713 lines to ~250. Calls `ast_walker.walk_function` to get decls.
- **`scope_path.py`** (new, ~80 lines) — utilities: `is_nested_within`,
  `nearest_common_ancestor`, `format_for_display`. Shared between
  bridge and (in Phase 2) the mutator.
- **No changes to `parser.py`, `colorgraph_parser.py`,
  `coalesce_ir_facts.py`** — they consume `Binding` through the same
  interface. The new `scope_path` field is additive.

## Data model

### `LocalDeclNode` (in `ast_walker.py`, new)

```python
@dataclass
class LocalDeclNode:
    name: str                          # "cursor_row"
    type_text: str                     # "HSD_JObj*"
    decl_text: str                     # source slice (single declarator)
    line_no: int                       # 1-indexed source line of the decl
    byte_range: tuple[int, int]        # [start, end) byte offsets
    scope_path: tuple[str, ...]        # ("fn_80248A78", "block@l234")
    scope_byte_range: tuple[int, int]  # enclosing block body span
    has_initializer: bool
    initializer_line_no: Optional[int] # same line as decl if init in-place
```

`scope_path` element format:
- Top-level scope (function body): the function name
  (`"fn_80248A78"`). Always the first element.
- Nested scope: `"block@l{line_no}"` where `line_no` is the 1-indexed
  source line of the opening `{` token. Stable across reformats as long
  as the block-opening line doesn't move; if it does, the path changes
  — that's intentional, callers re-derive after structural edits.

CLI display uses `/` as separator (e.g. `fn_80248A78/block@l234`).
The `--scope <prefix>` filter on lookups takes the same `/`-separated
form and matches by prefix (so `--scope fn_80248A78` matches all
scopes including nested ones; `--scope fn_80248A78/block@l234` matches
only that specific nested block).

### `Binding` (in `symbol_bridge.py`, existing — extended)

```python
@dataclass
class Binding:
    var_name: str
    virtual: int
    decl_line: int
    confidence: str        # "verified" | "best-guess" | "low-confidence"
    var_type: str          # NEW: AST-known type text
    scope_path: tuple[str, ...]  # NEW: same shape as LocalDeclNode
```

`var_type` and `scope_path` are new. Existing readers of `var_name` /
`virtual` / `decl_line` / `confidence` continue to work unchanged.

When the AST regex-fallback path fires (see "Tree-sitter parse failure"
below), returned Bindings still carry both fields: `var_type` is `""`
(empty string — type not recovered) and `scope_path` is `(fn_name,)`
(top-level only, since fallback doesn't descend into nested blocks).

### `BindingBasis` (in `symbol_bridge.py`, existing — extended)

Adds:

```python
decls_by_scope: dict[tuple[str, ...], list[LocalDeclNode]]
```

Surfaces all decls grouped by scope_path. Phase 2 (mutate + enumerate)
will use this; Phase 1 just populates it.

### `FirstDef` (unchanged)

Pcdump-only concept. No source-position fields needed.

## Lookup behavior

### `var-to-virtual <name>`

Input: variable name (e.g. `cursor_row`). Optional: `--scope <prefix>`.

1. Walk AST → all `LocalDeclNode`s with `name == "cursor_row"` (may be
   multiple due to shadowing or unrelated reuse).
2. For each matching decl, look up the corresponding `Binding` via
   ordinal-within-scope matching (see "Per-scope ordinal matching"
   below).
3. Return ALL matches, sorted: highest confidence first; within same
   confidence, by `scope_path` (top-level before nested).
4. If `--scope <prefix>` is given, filter to bindings whose `scope_path`
   starts with that prefix.

Output (text):
```
cursor_row -> r34  (best-guess, type=HSD_JObj*, scope=fn_80248A78/block@l234, line 235)
cursor_row -> r78  (best-guess, type=HSD_JObj*, scope=fn_80248A78/block@l312, line 313)
```

JSON includes `scope_path` as an array per binding.

If zero matches: print the existing "variable not found" error. The
agent's complaint specifically was that `cursor_row` produced this error
because the nested-block decl was invisible — Phase 1 fixes that.

### `virtual-to-var <virt>`

Input: virtual reg number (e.g. `34`).

1. Existing logic: find first-def, get its block_idx, match against
   basis bindings.
2. NEW: include `scope_path` in the reported best-guess binding.
3. NEW: if multiple bindings tie at best-guess (e.g. shadowed `i` in two
   scopes), print all candidates, sorted by a scope tiebreaker.

Scope tiebreaker (tiebreaker only — never overrides confidence): a
virtual whose first-def is in pcdump block 0 most likely corresponds to
a top-level local; first-def in a later block more likely corresponds to
a nested-block local. We don't have line numbers from MWCC, so this is
heuristic, not exact.

Output (text):
```
r34 -> cursor_row  (best-guess, scope=fn_80248A78/block@l234)
  alternates:
    cursor_row at scope=fn_80248A78/block@l312 (less likely — first-def in block 0)
```

### Per-scope ordinal matching (the key heuristic)

The bridge today matches decls to virtuals by source-order ordinal
within the function. The Phase 1 change: do the same ordinal walk, but
**partitioned by scope**.

For each scope in the AST (function-top first, then each nested block
in source order), iterate its decls in source order. Track which
virtuals have been claimed by earlier scopes' walks. Within a scope,
match its decls to the next un-claimed virtuals seen in pcdump order.

Why this works for the heartbeat case: `cursor_row` is in a nested
scope. Today's walker doesn't see it at all. Phase 1 walks into the
nested scope and assigns virtual 34 (or wherever) to it, which is
strictly better than the current "not found" or wrong "frame".

The matching stays best-guess (we don't have line numbers from MWCC).
The improvement is *visibility*, not *precision*.

## Error handling

### Tree-sitter parse failure

If tree-sitter fails (preprocessor macros that aren't expanded, broken
headers), `ast_walker.walk_function` raises `AstWalkError` with the
parse-error location. The bridge catches, logs a clear warning to
stderr:

```
[symbol_bridge] AST parse failed at line N, falling back to regex walker
```

…and falls back to a slim ~80-line regex walker that finds **top-level
decls only** (no nested-block awareness). This preserves pre-Phase-1
behavior as a safety net for the rare unparseable file. Existing
matched functions don't break.

### Function not found in source

`ast_walker.walk_function(source, "fn_X")` returns `[]`. Bridge raises
`FunctionNotFoundError` to the CLI, which prints the existing
"function not found" message.

### Multi-declarator decls

`int x, y, z;` produces three `LocalDeclNode`s with the same
`scope_path` and the same overall declaration `line_no`, but each one
has its own `byte_range` covering exactly that declarator's tokens
(tree-sitter exposes them as separate `init_declarator` children under
the parent `declaration` node). `decl_text` likewise covers only the
single-declarator slice (so e.g. `"x"` not `"int x, y, z"`); callers
that want the full declaration line can reconstruct it from the parent
`scope_byte_range`.

### Block scopes without braces

`if (x) int y;` — rare, deprecated, legal C. Tree-sitter exposes these
as compound_statements implicitly. Treated the same as braced blocks;
they get a `block@lN` element in `scope_path`.

### Shadowing

Two locals with the same name in different scopes (outer `i` + inner
`i`) are both surfaced. The user disambiguates via `--scope`. The
bridge does NOT resolve shadowing the way a C semantic analyzer would;
it's purely lexical.

### Function pointers and complex decls

Tree-sitter handles these natively. The `_looks_like_decl` heuristic
for "unrecognized shapes" in the old parser is no longer needed.

### Caching

`ast_walker.walk_function` is called many times per CLI invocation. The
walker caches parsed ASTs in a module-level dict keyed on
`(source_path, source_sha256)`. `ast_walker.clear_cache()` for tests.

## Testing strategy

### Unit tests for `ast_walker.py` (`tests/test_ast_walker.py`, new)

~15 tests:
- Top-level decl walk on a simple function.
- Nested-block: locals in `if` / `for` / `while` / braced compound
  blocks all surfaced with correct `scope_path`.
- Shadowing: outer `int i` + inner `int i` → both returned, distinct
  `scope_path`s.
- Multi-declarator: `int x, y, z;` → 3 decls, same scope, distinct
  `byte_range`s.
- Function pointer: `void (*cb)(int);` → one decl, type captured.
- Array decl: `int arr[10];` → one decl, type captured.
- Parse failure: malformed input → raises `AstWalkError` with line.
- Function not found: returns `[]`.
- Initializers: `int x = 5;` → `has_initializer=True`,
  `initializer_line_no` set.
- Cache hit/miss: two calls on same source return identical objects
  when cache is warm.

### Unit tests for `scope_path.py` (`tests/test_scope_path.py`, new)

~6 tests:
- `is_nested_within`: child starting with ancestor → True; sibling →
  False; same → True.
- `nearest_common_ancestor`: identical → same; cousin → common prefix;
  no common → `()`.
- `format_for_display`: round-trip with a parser.

### Bridge tests (`test_mwcc_debug_symbol_bridge.py`, existing)

- All existing tests continue to pass (`Binding` shape backward-
  compatible with new optional-by-position fields; the two new fields
  get defaults).
- New: `list_bindings` on a function with a nested `for` loop surfaces
  both the outer counter and an inner-block decl with distinct
  `scope_path`s.
- New: `find_var_for_virtual` includes `scope_path` in its returned
  Binding.
- New: `find_virtual_for_var("cursor_row")` on a synthetic source with
  a nested-block `cursor_row` returns the nested-block Binding (today
  this returns `None`).

### Integration test on `fn_80248A78` (slow, `@pytest.mark.integration`)

- Load `src/melee/mn/mnvibration.c` + cached pcdump (skip if missing).
- Assert: `find_virtual_for_var("cursor_row")` returns a non-`None`
  Binding (today returns `None`/"not found").
- Assert: `find_var_for_virtual(34)` returns `cursor_row` with the
  nested-block scope_path (today returns low-confidence top-level
  `frame`).

### Calibration regression

Re-run `coalesce_calibration.yaml` cases. They should keep passing —
bridge upgrade is additive at the data level.

### Full-suite gate

Run `pytest tools/melee-agent/tests/`. Target: 731 → ~755 (existing +
~24 new). No regressions.

## Limitations

- Per-scope ordinal matching is still best-guess. We don't have
  MWCC-emitted line numbers, so virtual→scope correlation is heuristic.
  The improvement over today is *visibility* (nested decls exist in the
  binding list at all) rather than *precision* (knowing which virtual
  exactly maps to which decl).
- Macro-heavy source may trip tree-sitter. The regex fallback preserves
  pre-Phase-1 behavior for those files.
- Phase 1 does not change `mutate insert-alias` or
  `enumerate-decl-orders`. Their existing behavior is unchanged. Phase
  2 will pick those up using the same `scope_path` model.

## Out of scope (Phase 2 candidates)

- `mutate insert-alias` scope-aware insertion (place alias decl at
  nearest enclosing block, not function top).
- `enumerate-decl-orders` nested-scope walk and within-scope swap
  restriction.
- `tier3-search` seeding from compiler-temp facts (depends on this
  spec's `Binding` upgrade landing first).
- A C semantic analyzer (type inference, shadowing resolution) — we
  deliberately stay lexical.

## File structure summary

| File | Action | LOC delta |
|------|--------|-----------|
| `tools/melee-agent/src/mwcc_debug/ast_walker.py` | Create | +~250 |
| `tools/melee-agent/src/mwcc_debug/symbol_bridge.py` | Rewrite | -713 → +~250 (net -463) |
| `tools/melee-agent/src/mwcc_debug/scope_path.py` | Create | +~80 |
| `tools/melee-agent/tests/test_ast_walker.py` | Create | +~300 |
| `tools/melee-agent/tests/test_scope_path.py` | Create | +~120 |
| `tools/melee-agent/tests/test_mwcc_debug_symbol_bridge.py` | Extend | +~200 |
