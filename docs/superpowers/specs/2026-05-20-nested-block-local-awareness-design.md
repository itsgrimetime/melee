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
  Exposes `walk_function(source, fn_name) -> list[LocalDecl]`.
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

### `LocalDecl` (existing in `symbol_bridge.py`, extended)

Current shape (in symbol_bridge.py:21):

```python
@dataclass
class LocalDecl:
    name: str          # variable name
    type_str: str      # canonical type as written in source ("HSD_JObj*")
    decl_index: int    # 0-indexed position in source order
```

Phase 1 extends this in-place (no new parallel type — reviewer
feedback C1 / consistency with the existing API):

```python
@dataclass
class LocalDecl:
    name: str
    type_str: str
    decl_index: int                      # kept for backward compat
    # NEW fields below (all default-valued so existing constructors
    # in tests / mutators / tier3_search keep working):
    line_no: int = 0                     # 1-indexed source line of the decl
    byte_range: tuple[int, int] = (0, 0) # [start, end) byte offsets in source
    scope_path: tuple[str, ...] = ()     # ("fn_80248A78", "block@l234c12")
    scope_byte_range: tuple[int, int] = (0, 0)  # enclosing block body span
    has_initializer: bool = False
    initializer_line_no: Optional[int] = None
```

The fallback path (regex walker on tree-sitter failure) sets the new
fields to their defaults so callers that don't care about scope still
work.

`scope_path` element format:
- Top-level scope (function body): the function name
  (`"fn_80248A78"`). Always the first element.
- Nested scope: `"block@l{line}c{col}"` where `line` is the 1-indexed
  source line and `col` is the 0-indexed byte column of the opening
  `{` token. The column suffix disambiguates two blocks that open on
  the same line (common when macros expand to `if (x) { ... } else
  { ... }` on a single line — reviewer feedback I3).
- Stable across reformats as long as the block-opening token doesn't
  move; if it does, the path changes — that's intentional, callers
  re-derive after structural edits.

CLI display uses `/` as separator (e.g.
`fn_80248A78/block@l234c12`). The `--scope <value>` filter on lookups:
- `--scope fn_80248A78` → exact match on function-top scope (excludes
  nested blocks).
- `--scope fn_80248A78/` → prefix match (function-top AND any nested
  scope inside it). The trailing slash means "and everything inside".
- `--scope fn_80248A78/block@l234c12` → exact match on that specific
  nested block.
- `--scope fn_80248A78/block@l234c12/` → that block AND any blocks
  nested deeper inside it.

(Reviewer feedback I2: trailing-slash convention picked explicitly.)

### `Binding` (existing in `symbol_bridge.py:348`, extended)

Current shape:

```python
@dataclass
class Binding:
    var_name: str
    virtual: int           # -1 if unmapped
    decl_line: int         # 1-indexed line in original source
    kind: str              # "local" | "param"
    type_str: str
    confidence: str        # "verified" | "best-guess" | "low-confidence"
                           # | "rejected" | "ambiguous" | "unsupported"
```

Phase 1 adds **one** field — `scope_path` — and changes nothing else.
`type_str` already carries the type (reviewer feedback C1 corrected
my earlier draft that proposed a duplicate `var_type`). `kind` stays
as-is and continues to drive existing consumers (`tier3_search`,
`mutators`).

```python
@dataclass
class Binding:
    var_name: str
    virtual: int
    decl_line: int
    kind: str
    type_str: str
    confidence: str
    scope_path: tuple[str, ...] = ()     # NEW, defaults empty for legacy paths
```

When the regex-fallback path fires (tree-sitter ImportError or parse
failure — see "Tree-sitter availability and parse failure" below),
returned Bindings carry `scope_path=(fn_name,)` (top-level only —
fallback doesn't descend into nested blocks).

### `BindingBasis` (existing in `symbol_bridge.py:365`, extended)

Current shape:

```python
@dataclass
class BindingBasis:
    parsed_params: list[LocalDecl]
    parsed_locals: list[LocalDecl]
    observed_virtuals: list[int]
    unrecognized_decls: list[str]
    red_flags: list[str]
```

Phase 1 keeps all five existing fields. `parsed_locals` continues to be
the flat source-order list (preserves the `--basis` CLI mode wired up
in task #113). One new field:

```python
decls_by_scope: dict[tuple[str, ...], list[LocalDecl]] = field(default_factory=dict)
```

Surfaces all decls grouped by `scope_path`. Phase 2 (mutate +
enumerate) will use this; Phase 1 ships it empty-but-correct so Phase
2 lands without touching `BindingBasis` again (reviewer feedback S4).

(Reviewer feedback C2: `parsed_locals` is preserved, `decls_by_scope`
is additive.)

### `FirstDef` (unchanged)

Pcdump-only concept. No source-position fields needed.

## Lookup behavior

### `var-to-virtual <name>`

Input: variable name (e.g. `cursor_row`). Optional: `--scope <value>`
(format documented under `scope_path` above — exact match by default,
trailing `/` for prefix).

1. Walk AST → all `LocalDecl`s with `name == "cursor_row"` (may be
   multiple due to shadowing or unrelated reuse).
2. For each matching decl, look up the corresponding `Binding` via
   ordinal-within-scope matching (see "Per-scope ordinal matching"
   below).
3. Return ALL matches, sorted: highest confidence first; within same
   confidence, by `scope_path` (top-level before nested).
4. If `--scope <value>` is given, filter to bindings using exact/prefix
   semantics from `scope_path` section.

Output (text, with the project's `rN` prefix convention from task
#115):
```
cursor_row -> r34  (best-guess, type=HSD_JObj*, scope=fn_80248A78/block@l234c12, line 235)
cursor_row -> r78  (best-guess, type=HSD_JObj*, scope=fn_80248A78/block@l312c12, line 313)
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
within the function (the "cursor model" in `_collect_basis`). The Phase
1 change: do the same ordinal walk, but **partitioned by scope** and
consuming from the pre-pass's observed-virtuals list in declaration
order.

Algorithm:
1. Compute `observed_virtuals: list[int]` = pre-pass destinations
   ≥ 32, in first-def order (existing
   `_collect_virtual_destinations`).
2. Walk scopes in source order: function-top first, then each nested
   block in declaration order.
3. Within each scope, iterate decls in source order. Pop the next
   un-claimed virtual off `observed_virtuals` and assign it to the
   current decl.
4. If `observed_virtuals` runs out, remaining decls get `virtual=-1`
   with `confidence="ambiguous"`.

**Worked example (reviewer feedback I1):** Suppose `fn_80248A78` has
this shape:

```c
void fn_80248A78(HSD_GObj* gobj) {
    MnVibrationData* data;       // top-level decl 0
    s32 i;                       // top-level decl 1
    HSD_JObj* frame;             // top-level decl 2
    // ... 3 instructions defining r32, r33, r34 ...
    for (i = 0; i < 8; i++) {    // opens nested scope at line 234
        HSD_JObj* cursor_row;    // nested decl 0
        HSD_JObj* row_0_jobj;    // nested decl 1
        // ... 2 more instructions defining r35, r36 ...
    }
}
```

Suppose `observed_virtuals = [32, 33, 34, 35, 36]`.

Per-scope walk:
- Scope `fn_80248A78`: decls = [data, i, frame].
  - `data` ← 32, `i` ← 33, `frame` ← 34. (3 claimed.)
- Scope `fn_80248A78/block@l234c4`: decls = [cursor_row, row_0_jobj].
  - `cursor_row` ← 35, `row_0_jobj` ← 36. (5 claimed total.)

Today's bridge:
- `cursor_row` doesn't appear in any scope (regex walker skipped the
  nested block).
- `virtual-to-var 35` returns the wrong low-confidence top-level
  `frame` (since the cursor model overshoots its 3 top-level decls).

Phase 1 bridge:
- `cursor_row` returns a `best-guess` binding `r35`.
- `virtual-to-var 35` returns `cursor_row` with
  `scope=fn_80248A78/block@l234c4`.

The matching stays best-guess (we still don't have MWCC line numbers).
The improvement is *visibility*: nested-block decls now exist in the
binding list at all.

## Error handling

### Tree-sitter availability and parse failure

Two failure modes share one fallback:
1. **Import failure**: `tree-sitter` or `tree-sitter-c` not importable
   (e.g. binary wheel missing for the current platform). `ast_walker`
   wraps its imports in try/except (mirroring the existing pattern at
   `tools/melee-agent/src/hooks/c_analyzer.py:17` and
   `tools/melee-agent/src/cli/extract.py:24`).
2. **Parse failure**: tree-sitter parses but `walk_function` finds
   the requested function's body contains error nodes (preprocessor
   macros that aren't expanded, broken includes). Raises
   `AstWalkError` with the error-node line.

Both trigger the same bridge fallback: a slim ~80-line regex walker
that finds **top-level decls only** (no nested-block awareness). This
preserves pre-Phase-1 behavior as a safety net. Existing matched
functions don't break. The bridge logs:

```
[symbol_bridge] tree-sitter unavailable / parse failed, falling back to regex walker
```

The fallback walker is a thin subset of today's `walk_local_decls` —
just enough to keep top-level lookups working. It does NOT carry
forward `_top_level_statements`, `_strip_strings_and_comments`, or
`_looks_like_decl` in full — those are deleted with the main rewrite.

(Reviewer feedback I5: ImportError handled at module-load time in
addition to AstWalkError at call time.)

### Removed: `red_flags=["nested-decl"]`

The existing bridge sets `red_flags=["nested-decl"]` whenever the body
contains `)\s*{` (any nested compound statement) and demotes
confidence to `"low-confidence"`. The intent was to warn callers that
the cursor model might be wrong because the walker doesn't see nested
decls.

Phase 1 walks nested decls, so this red flag is no longer correct. It
gets removed from `_collect_basis`. The calibration regression tests
(see Testing) MUST include at least one function that previously
triggered this red flag, to confirm:
- The function's bindings are now `"best-guess"` (or higher), not
  `"low-confidence"`.
- The new scope-aware Bindings for the nested-block decls are present.

(Reviewer feedback C3.)

### Removed: `_FN_HEADER_RE` regex

The existing `_extract_function_text` (line 451) uses a regex
`_FN_HEADER_RE` to find the function in the source string. Tree-sitter
locates function definitions natively. `ast_walker.walk_function`
replaces both `_extract_function_text` and the regex header match —
the AST gives us the function's body span directly.

(Reviewer feedback S1.)

### Function not found in source

`ast_walker.walk_function(source, "fn_X")` returns `[]`. Bridge raises
`FunctionNotFoundError` to the CLI, which prints the existing
"function not found" message.

### Multi-declarator decls

`int x, y, z;` produces three `LocalDecl`s with the same
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

`ast_walker.walk_function` is called many times per CLI invocation
(every CLI command path that needs bindings). The walker caches
parsed `tree_sitter.Tree` objects in a module-level dict keyed on
`source_sha256(source: str)`. The path argument (when provided by
callers) is informational only — it never participates in the cache
key. This handles in-memory sources (mutate, permuter staging) the
same as on-disk files (reviewer feedback I4).

`ast_walker.clear_cache()` is exposed for tests. A pytest autouse
fixture in `tools/melee-agent/tests/conftest.py` calls it between
tests to prevent cross-test cache leaks:

```python
@pytest.fixture(autouse=True)
def _clear_ast_walker_cache():
    yield
    from src.mwcc_debug import ast_walker
    ast_walker.clear_cache()
```

## Testing strategy

### Unit tests for `ast_walker.py` (`tests/test_ast_walker.py`, new)

~15 tests:
- Top-level decl walk on a simple function.
- Nested-block: locals in `if` / `for` / `while` / braced compound
  blocks all surfaced with correct `scope_path`.
- Shadowing: outer `int i` + inner `int i` → both returned, distinct
  `scope_path`s.
- Multi-declarator: `int x, y, z;` → 3 decls, same scope and same
  `line_no`, distinct `byte_range`s (each covering only one
  declarator).
- Function pointer: `void (*cb)(int);` → one decl, type captured.
- Array decl: `int arr[10];` → one decl, type captured.
- Two blocks on one line: `if (a) { ... } else { ... }` → distinct
  `scope_path`s via column suffix (`block@l5c8` vs `block@l5c20`).
- Parse failure: malformed input → raises `AstWalkError` with line.
- Tree-sitter ImportError simulation: monkeypatch import to raise →
  `walk_function` raises `AstUnavailableError` (distinct from
  `AstWalkError` so bridge can log the right reason).
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

- All existing tests continue to pass. `Binding` is backward-compatible
  (the new `scope_path` field has a default of `()`).
- New: `list_bindings` on a function with a nested `for` loop surfaces
  both the outer counter and an inner-block decl with distinct
  `scope_path`s.
- New: `find_var_for_virtual` includes `scope_path` in its returned
  Binding.
- New: `find_virtual_for_var("cursor_row")` on a synthetic source with
  a nested-block `cursor_row` returns the nested-block Binding (today
  this returns `None`).
- **Calibration regression for removed `nested-decl` red flag**: a
  test loads a known function whose body contains `)\s*{` (i.e.
  previously triggered the `nested-decl` red flag and demoted
  confidence to `"low-confidence"`). Phase 1 asserts: bindings are
  now `"best-guess"`, AND the nested-block decls show up with
  scope_path populated.

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

Also explicitly run `pytest test_coalesce_ir_facts.py` since
`coalesce_ir_facts` imports `Binding`, `BindingBasis`, `find_first_def`
and others from `symbol_bridge`. Verify no regression (reviewer
feedback S2).

### Full-suite gate

Run `pytest tools/melee-agent/tests/`. Target: 731 → ~758 (existing +
~27 new tests across ast_walker, scope_path, bridge extensions, and
the calibration regression). No regressions.

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
| `tools/melee-agent/src/mwcc_debug/symbol_bridge.py` | Rewrite (extend `LocalDecl`, `Binding`, `BindingBasis`; replace regex walker with tree-sitter call; keep slim regex fallback) | -713 → +~280 (net -433) |
| `tools/melee-agent/src/mwcc_debug/scope_path.py` | Create | +~80 |
| `tools/melee-agent/tests/test_ast_walker.py` | Create | +~320 |
| `tools/melee-agent/tests/test_scope_path.py` | Create | +~120 |
| `tools/melee-agent/tests/test_mwcc_debug_symbol_bridge.py` | Extend (existing tests stay, add nested-block + scope cases + nested-decl red-flag removal regression) | +~220 |
| `tools/melee-agent/tests/conftest.py` | Add autouse fixture for `ast_walker.clear_cache()` (create file if absent) | +~10 |

The existing `LocalDecl`, `Binding`, `BindingBasis` are **extended in
place**; no parallel types are introduced. Existing readers continue
to work unchanged (new fields all carry safe defaults).
