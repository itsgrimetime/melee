# Statement Hoist/Sink Operator — Design / Spec

Status: design, revised per Codex review 2026-06-07 (no-go → safety model rebuilt).

## Problem

Last-mile register/stack walls (e.g. `mnEvent_8024D15C`) are sensitive to the
**order of statements** in the C source: where a value is computed relative to
its uses changes MWCC's live ranges, hence register/stack allocation. The
structure-search substrate (`melee-agent debug search structure`) has the right
structure-aware scorer but its `statement-order` axis only does narrow rewrites
(`split/fuse-shift-or`, `adjacent-swap`) — it cannot relocate a statement/group
to a **non-adjacent** position, the move class that reorders live ranges. The
pcdump-guided `directed` layer is gated behind the experimental role preflight.

So the substrate is missing the one operator that reaches this wall class.

## Goal / Non-goals

- GOAL: add a `statement-hoist-sink` operator to the existing `statement-order`
  axis that relocates a **conservative** movable unit (a simple no-call local
  assignment, or a local-aggregate field-write cluster) to other legal positions
  **among its compound-block siblings**, def-use- and side-effect-safe; scored by
  the existing structure scorer with **shape-aware ranking extended to this axis**.
- GOAL: **targeted + group-merge** move generation, with the position-selection
  strategy factored so an **exhaustive** strategy is a one-branch add later.
- GOAL: a generalizable substrate capability validated for *safety* on
  `mnEvent_8024D15C` (it must NOT generate unsafe moves) and for *yield* on a
  function where a single safe move is plausibly the lever.
- NON-GOAL (explicit, per review): this is **not** expected to crack D15C — a
  sound barrier correctly blocks the `pos`-past-calls move (escaped `translate`),
  and D15C's real lever appears to be a *combination* (decouple `translate` +
  rematerialize/spill `pos`) beyond any single operator. Also out of scope: the
  role-gated `directed` layer; exhaustive enumeration now (only the seam); a
  `rematerialize` operator (the complementary lever, a documented follow-on).

## Why existing span infra is insufficient (key correction)

`source_spans.py:list_statement_spans()` **recursively flattens nested compound
statements** (`_direct_statement_nodes`, src/mwcc_debug/source_spans.py:75) and
derives `scope_path` from local declarations, not the parent compound/control
block (`_scope_for_node`, :102). So a statement inside `if (is_unlocked)` reports
the same scope as an outer statement → "same scope" is **not** a safe relocation
domain. And `_read_write_sets` (:127) is shallow (identifiers; first LHS for `=`)
— it does NOT model call side effects, `+=`/`++`, initializers, pointer/array/
`->` stores, volatile, or aliasing.

Therefore v1 builds a small **compound-sibling model** on the existing tree-sitter
parser (reuse `ast_walker.py`'s parser access), and restricts movable units to a
conservatively-analyzable subset. `list_statement_spans`/`_read_write_sets` are
reused only to read identifier reads/writes **of an already-classified simple
statement**, never for scope/sibling structure.

## Components (small, independently testable)

1. **Compound-sibling model (NEW, `src/search/statement_move.py`)**
   - `parse_compound_tree(source, function) -> CompoundBlock` (tree-sitter):
     each `CompoundBlock` holds its **direct child statements in source order**;
     a child is either a `SimpleStmt` (expression/assignment, no nested block) or
     an `OpaqueStmt` (anything containing a nested block or control flow:
     `if/for/while/switch/do`, labeled, `goto`, declarations-with-side-effects).
     Opaque statements are **never moved and act as hard sibling barriers**; the
     model does NOT recurse into them for move purposes (v1).
   - Each `SimpleStmt` carries byte range (tree-sitter `start_byte`/`end_byte`),
     line range, and a **classification** (see 2).

2. **Movable-unit classification + safety (NEW)**
   - A `SimpleStmt` is **movable** only if it is a simple assignment whose LHS is
     a local scalar (`x = …`) or a local-aggregate dot-field (`base.field = …`,
     `base` a local), whose RHS is call-free and has no `&`/`*`/`->`/`[]`/volatile
     and references only locals/params/literals. Everything else (calls, pointer/
     array/`->` stores, globals, volatile, declarations) is **immovable + a
     barrier**.
   - `reads(unit)` / `writes(unit)`: from the RHS/LHS identifiers (may reuse
     `_read_write_sets` on the classified-simple text). For an aggregate-field
     write, `writes = {base}` (whole aggregate, conservative).
   - `escaped_locals(source, function) -> set[str]`: locals with `&name` taken
     anywhere (mask comments/literals first). Conservative superset is fine.

3. **Group formation (NEW)** — `extract_movable_units(block) -> list[MoveUnit]`:
   emit (a) **aggregate-field-write clusters**: maximal runs of consecutive
   movable `SimpleStmt` siblings writing distinct fields of the **same local
   aggregate base** (`pos.x; pos.y; pos.z`), and (b) **singletons** for movable
   simple statements not in a cluster. A `MoveUnit` carries union reads/writes,
   the contiguous sibling index range, and byte range. (Singletons are also
   emitted for cluster members? No — clusters move whole; members not separately,
   to avoid partial-group breakage.)

4. **Legal-position + barrier model (NEW)** —
   `legal_destinations(siblings, unit, escaped) -> list[int]`: scanning outward
   among **the same compound block's siblings**, stop at the first sibling `T`
   that is a barrier:
   - data dep: `T.writes ∩ (unit.reads ∪ unit.writes) ≠ ∅` or
     `T.reads ∩ unit.writes ≠ ∅`;
   - **opaque/call barrier:** `T` is opaque (control/call/unknown-memory) AND
     (`unit.reads ∪ unit.writes` ∩ `escaped` ≠ ∅, OR `unit` touches any
     non-local) → hard stop. (A call may clobber address-escaped/global state
     that `StatementSpan.writes` cannot show.) In D15C this blocks moving the
     `pos` cluster across the `row->gobjs`/`is_unlocked` blocks at mnevent.c:154
     and :160 because `pos` reads escaped `translate`.
   - Returns the legal sibling-slot indices (a contiguous window around the
     origin), complete (so exhaustive can consume it directly).

5. **Position-selection strategy (PLUGGABLE seam)** —
   `select_positions(unit, legal, strategy) -> list[int]`:
   - `"targeted"` (default): the slot just before the first sibling reading any of
     `unit.writes` (sink-to-first-use) and just after the last sibling writing any
     of `unit.reads` (hoist-to-last-def), ∩ `legal`.
   - `"exhaustive"` (future): return all of `legal`. One-branch add; legality and
     generation are unchanged.

6. **Variant generation (NEW)** — `apply_move(source_bytes, unit, dest) -> bytes`:
   operate on **bytes** (tree-sitter offsets are byte offsets; encode source to
   UTF-8/Latin-1 once, slice, decode once). Move the unit's **full source lines**
   (leading indentation through trailing newline), reinsert at `dest`'s line
   boundary, and **adjust `dest` for the removal when moving downward**. Same-
   compound moves preserve indentation (hard invariant; assert it). Identity move
   (dest == origin) returns input unchanged.

7. **Operator entry + integration (NEW)** —
   `generate_statement_hoist_sink_variants(source, function, output_dir,
   baseline_percent, max_candidates, strategy="targeted")` mirrors the existing
   operator functions and registers variants via the host `add_variant` closure
   with label `statement-order-hoist-sink`, metadata `{base, dest, direction}`.
   Called from `generate_statement_order_variants()`; **emit hoist-sink variants
   first** so the per-axis `max_candidates` cap (structure.py:863) doesn't starve
   them behind the narrow legacy operators.

8. **Shape-aware ranking (MODIFY `src/search/structure.py`)** — extend the
   `source-lifetime`-only shape-aware rank branch (structure.py:143) to also cover
   `statement-order`, so candidates are ranked by `opcode_shape_preserved` +
   `line_delta` then match%, not match% alone. (Or, if that proves entangled,
   soften the spec's scorer claim — but the extension is preferred and small.)

## Data flow

`source.c` → `parse_compound_tree` (+ `escaped_locals`) → per block:
`extract_movable_units` → `legal_destinations` → `select_positions(targeted)` →
`apply_move` → `add_variant` (write `.c`) → `score_structure_variants` (existing)
→ shape-aware rank.

## Safety / correctness model

- Movement is confined to **siblings of one real compound block**; control/calls
  are opaque barriers; movable units are a conservatively-analyzable subset. This
  makes generated moves content-preserving and, for the modeled cases, behavior-
  preserving.
- The structure scorer is **triage ranking, not a semantic oracle**: exact-asm
  match is the decomp oracle; a non-exact candidate that improves shape is a lead
  to inspect, and a behavior-changing candidate *can* score high (so v1 stays
  conservative on what it generates rather than relying on the scorer to reject).
- Tree-sitter unavailable / parse error → `AxisSummary(status="blocked",
  reason="ast-unavailable")`, never crash (mirror existing axes).

## Testing

- Unit (`tests/search/test_statement_move.py`, no compiler):
  - compound model: statements inside `if(){…}` are NOT siblings of outer
    statements; the `if` is one opaque barrier unit.
  - classification: `pos.x = translate.x;` movable; `lb_80011E24(…);`,
    `text->pos_x = …;`, `*p = …;`, `arr[i] = …;`, a declaration → immovable/barrier.
  - grouping: `pos.x; pos.y; pos.z` → one cluster (base `pos`); `text->font_size.x;
    .y;` → NOT clustered (pointer member); a lone assignment → singleton.
  - `escaped_locals` finds `translate` from `&translate`.
  - legality: a unit reading escaped `translate` cannot cross an opaque/call
    barrier; a pure-register-local unit can cross a non-aliasing simple sibling.
  - `select_positions`: targeted returns first-use/last-def; `exhaustive` returns
    full legal set (proves the seam).
  - `apply_move`: identity is a no-op; a real move preserves indentation and is
    byte-correct on a non-ASCII fixture; downward-move destination adjustment.
- Integration (`tests/search/test_statement_move_d15c.py`, skip-if-objects-absent):
  run on `mnEvent_8024D15C` and assert: (a) **no unsafe move is generated** — no
  candidate relocates the `pos` cluster across the `is_unlocked`/`row->gobjs`
  blocks (assert by inspecting emitted candidate sources / metadata); (b) every
  emitted candidate **compiles**; (c) the run reports a best score without
  crashing. (Expected yield on D15C: low — see Non-goals.)
- Yield smoke: run on one function with an obvious in-block movable simple
  assignment and confirm ≥1 compiling candidate is produced and ranked.

## Expandability (designed in)

- `select_positions` strategy: `targeted` → `exhaustive` is one branch;
  `legal_destinations` already returns the complete legal window.
- The compound-sibling model + barrier logic is independent of a future
  `rematerialize` operator (replace a held value with its recomputation at use) —
  the complementary lever the D15C 85.9% hand-experiment pointed at, and the
  natural next operator on this seam once hoist-sink lands.
