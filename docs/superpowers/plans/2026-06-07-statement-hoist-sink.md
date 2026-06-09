# Statement Hoist/Sink Operator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `statement-hoist-sink` operator to the existing `statement-order` structure-search axis that relocates conservatively-safe movable units (simple side-effect-free local scalar assignments, and local-aggregate field-write clusters like `pos.x/y/z`) among a function's top-level compound-block siblings, def-use- and barrier-safe, scored with shape-aware ranking.

**Architecture:** A new pure module `src/search/statement_move.py` builds a top-level-sibling model on the shared tree-sitter parser (`src.common.tree_sitter_c`, reusing `find_function_definition`/`node_text`), classifies movable units conservatively, computes legal destinations with **unconditional opaque/immovable barriers** plus def-use barriers, selects targeted positions (expandable to exhaustive via one branch), and rewrites source by full-line byte move on UTF-8. It plugs into `generate_statement_order_variants()` via the existing `add_variant` closure (emitted first) and is ranked by an extended shape-aware sort. Spec: `docs/superpowers/specs/2026-06-07-statement-hoist-sink-axis-design.md`.

**Tech Stack:** Python 3, tree-sitter-c (`src/common/tree_sitter_c.py`), pytest (`tools/melee-agent/tests/search/`).

**Conventions:**
- Paths relative to repo root unless absolute. Package root: `tools/melee-agent/`. Run tests from there: `python -m pytest tests/<f> -v`.
- Package imports: `from ..common import tree_sitter_c as _ts`; tests use `from src.search.statement_move import ...`.
- **v1 scope:** only the function's **top-level** compound block's direct sibling statements. Control/nested-block/declaration statements and any non-classifiable statement are **opaque, immovable, unconditional hard barriers** (never crossed, never recursed into). Nested-block movement is a documented future expansion.
- **Safety invariant:** a movable unit may cross *only* other pure-local movable siblings, and only when no read/write dependency conflicts. Because movable RHS/LHS forbid `* & -> [] = call()`, a movable sibling can never write through a pointer to clobber another local — so crossing movable siblings is behavior-preserving. Crossing anything immovable is forbidden outright. (`escaped_locals` is therefore *subsumed* by the immovable-barrier rule in v1; it is still computed, tested, surfaced in metadata, and used as a defense-in-depth check, and becomes decisive when v2 relaxes nested-block barriers.)
- Commit after each task on the current worktree branch.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/search/statement_move.py` (NEW) | `_mask`, `_body_node`, `toplevel_siblings`, `local_names`, `escaped_locals`, `classify_movable`, `extract_movable_units`, `legal_destinations`, `select_positions`, `apply_move`, `generate_statement_hoist_sink_variants`, and helpers (`_leftmost_identifier`, `_declared_names`, `_sibling_rw`, `_line_bounds`, `_unit_owns_its_lines`). |
| `src/search/structure.py` (MODIFY) | Call the new operator from `generate_statement_order_variants` (emit first); extend shape-aware ranking to `statement-order` (incl. `line_delta`). |
| `tests/search/test_statement_move.py` (NEW) | Unit tests for every helper (no compiler). |
| `tests/search/test_statement_move_ranking.py` (NEW) | Shape-aware ranking covers `statement-order` (incl. `line_delta`) + a fake-scored `run_structure_search` integration proof + no source-lifetime regression. |
| `tests/search/test_statement_move_d15c.py` (NEW) | D15C safety (non-vacuous): pos.x/pos.z extracted but have zero legal destinations; no unsafe candidate emitted. |

**Shared fixture** (used by Tasks 3, 5, 6, 7) — define once at the top of `test_statement_move.py`:

```python
POS_SRC = '''\
void f(int idx, float spacing)
{
    Vec3 translate;
    Vec3 pos;
    Vec3 result;
    int pad;
    pos.x = translate.x;
    pos.y = spacing;
    pos.z = translate.z;
    pad = idx;
    result.x = pos.x;
}
'''
```

This fixture is constructed so the `pos` cluster (3 movable field writes, base `pos`) has a real targeted move: it can sink past the non-conflicting `pad = idx;` to land just before its first use `result.x = pos.x;`. `Vec3` need not be a real type — tree-sitter parses it structurally.

---

## Task 1: Top-level sibling model (`toplevel_siblings`)

**Files:** Create `tools/melee-agent/src/search/statement_move.py`; Test `tools/melee-agent/tests/search/test_statement_move.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/search/test_statement_move.py
import pytest
from src.search.statement_move import toplevel_siblings, SiblingStmt

SRC = '''\
void f(int idx)
{
    int a;
    a = idx;
    if (a != 0) {
        a = a + 1;
    }
    b.x = a;
}
'''

def test_toplevel_siblings_does_not_flatten_nested_blocks():
    sibs = toplevel_siblings(SRC, "f")
    if sibs is None:
        pytest.skip("tree-sitter unavailable")
    kinds = [s.kind for s in sibs]
    # declaration(opaque), simple `a = idx`, opaque if-block, simple `b.x = a`
    assert kinds == ["opaque", "simple", "opaque", "simple"]
    # the inner `a = a + 1;` is NOT a top-level sibling
    assert all("a + 1" not in s.text for s in sibs)
    assert all(s.byte_range[0] < s.byte_range[1] for s in sibs)
    assert [s.byte_range for s in sibs] == sorted(s.byte_range for s in sibs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py::test_toplevel_siblings_does_not_flatten_nested_blocks -v`
Expected: FAIL — `ModuleNotFoundError: src.search.statement_move`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/search/statement_move.py
"""Statement hoist/sink: relocate conservatively-safe movable units among a
function's top-level compound-block siblings. v1 does NOT recurse into nested
blocks; control/nested/declaration/non-classifiable statements are opaque,
immovable, unconditional barriers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from ..common import tree_sitter_c as _ts

# tree-sitter-c node types that are control/compound/declaration -> opaque barriers
_OPAQUE_KINDS = {
    "if_statement", "for_statement", "while_statement", "do_statement",
    "switch_statement", "compound_statement", "labeled_statement",
    "goto_statement", "declaration", "return_statement", "break_statement",
    "continue_statement",
}


@dataclass(frozen=True)
class SiblingStmt:
    text: str
    byte_range: tuple[int, int]
    line_range: tuple[int, int]
    kind: str  # "simple" (assignment-shaped candidate) | "opaque" (barrier)
    node_type: str


def _body_node(source: str, function: str):
    """Return (body_node, source_bytes) for the function's top-level compound
    block, or (None, source_bytes/None) if unavailable."""
    if not _ts.is_available():
        return None, None
    parser = _ts.get_parser()
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    fn = _ts.find_function_definition(tree.root_node, source_bytes, function)
    if fn is None:
        return None, source_bytes
    return fn.child_by_field_name("body"), source_bytes


def toplevel_siblings(source: str, function: str) -> Optional[list[SiblingStmt]]:
    body, source_bytes = _body_node(source, function)
    if body is None:
        return None
    sibs: list[SiblingStmt] = []
    for child in body.named_children:
        if child.type == "comment":
            continue
        text = _ts.node_text(source_bytes, child)
        kind = "opaque" if child.type in _OPAQUE_KINDS else "simple"
        sibs.append(SiblingStmt(
            text=text,
            byte_range=(child.start_byte, child.end_byte),
            line_range=(child.start_point[0] + 1, child.end_point[0] + 1),
            kind=kind,
            node_type=child.type,
        ))
    return sibs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -v`
Expected: PASS (or skip if tree-sitter unavailable). If a bare assignment is not `expression_statement`, print `[(s.node_type, s.kind) for s in sibs]` and adjust — only assignment-shaped `expression_statement`s should be `"simple"`; `declaration` must be `"opaque"`.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/search/statement_move.py tools/melee-agent/tests/search/test_statement_move.py
git commit -m "feat(search): top-level compound-sibling model for statement moves"
```

---

## Task 2: Comment/literal masker + movable classification + `escaped_locals`

**Files:** Modify `src/search/statement_move.py`; Test `tests/search/test_statement_move.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/search/test_statement_move.py
from src.search.statement_move import classify_movable, escaped_locals, _mask

def _mk(text, kind="simple"):
    from src.search.statement_move import SiblingStmt
    return SiblingStmt(text=text, byte_range=(0, len(text)), line_range=(1, 1),
                       kind=kind, node_type="expression_statement")

def test_mask_blanks_comments_and_literals_preserving_length():
    m = _mask('a = "x=y&z"; // &q\n')
    assert len(m) == len('a = "x=y&z"; // &q\n')
    assert "&" not in m and "x=y" not in m  # literal + comment content blanked

def test_classify_movable_accepts_simple_local_and_aggregate_field():
    scalar = classify_movable(_mk("a = idx;"), locals_={"a", "idx"})
    assert scalar is not None and scalar.write_base == "a" and scalar.reads == {"idx"}
    field = classify_movable(_mk("pos.x = translate.x;"), locals_={"pos", "translate"})
    assert field is not None and field.write_base == "pos" and field.is_field is True
    assert field.reads == {"translate"}            # field member `x` is NOT a read
    lit = classify_movable(_mk("a = 0.035f;"), locals_={"a"})
    assert lit is not None and lit.reads == set()   # numeric literal is not a read

def test_classify_movable_rejects_calls_pointers_arrays_and_side_effects():
    locs = {"a", "b", "c", "p", "arr", "i", "idx"}
    for bad in ("a = f(idx);", "*p = a;", "a = p->x;", "arr[i] = a;",
                "a += idx;", "a = idx++;", "a = b ? c : a;", "a = b, c;",
                "a = b = c;", "a = (b = c);", "a = b += c;", "a = b == c;",
                "a = b & c;", "a = &b;", "a = *p;"):
        assert classify_movable(_mk(bad), locals_=locs) is None, bad
    assert classify_movable(_mk("g = a;"), locals_={"a"}) is None      # g not local (global)
    assert classify_movable(_mk("if (a) {}", kind="opaque"), locals_=locs) is None

def test_escaped_locals_finds_address_taken():
    src = "void f(){ Vec3 t; g(x, &t); h(& u); k(&(w)); }"
    esc = escaped_locals(src, "f")
    assert {"t", "u", "w"} <= esc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k "mask or classify or escaped" -v`
Expected: FAIL — `ImportError: classify_movable`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/search/statement_move.py
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_ADDR_RE = re.compile(r"&\s*\(?\s*([A-Za-z_]\w*)")
# RHS markers that forbid movement: ptr/array/member-deref, addr-of, call, ternary, comma,
# increment/decrement.  Multiply/bitwise-and use the same chars (`*`,`&`) and are also
# rejected (conservative: we cannot cheaply distinguish them from deref/addr-of).
_UNSAFE_RHS_RE = re.compile(r"\+\+|--|->|\[|\]|\*|&|\?|,|\b[A-Za-z_]\w*\s*\(")
_ASSIGN_PREV_FORBID = set("+-*/%&|^<>=!~")   # char before '=' that means it isn't plain assignment
_C_KEYWORDS = {"sizeof", "return", "if", "for", "while", "do", "switch", "else", "case"}


@dataclass(frozen=True)
class MovableInfo:
    write_base: str       # the local being written (aggregate base or scalar)
    is_field: bool        # True if `base.field = ...`
    reads: frozenset      # local identifiers read on the RHS
    writes: frozenset     # {write_base}


def _mask(text: str) -> str:
    """Blank out comment and string/char-literal CONTENT with spaces, preserving
    length and offsets, so `&`/`=`/identifiers inside them are not misread."""
    out = list(text)
    i, n, state = 0, len(text), None
    while i < n:
        c = text[i]
        if state is None:
            if c == "/" and i + 1 < n and text[i + 1] == "/":
                out[i] = out[i + 1] = " "; state = "line"; i += 2; continue
            if c == "/" and i + 1 < n and text[i + 1] == "*":
                out[i] = out[i + 1] = " "; state = "block"; i += 2; continue
            if c == '"': state = "str"; i += 1; continue
            if c == "'": state = "char"; i += 1; continue
            i += 1; continue
        if state == "line":
            if c == "\n": state = None
            else: out[i] = " "
            i += 1; continue
        if state == "block":
            if c == "*" and i + 1 < n and text[i + 1] == "/":
                out[i] = out[i + 1] = " "; state = None; i += 2; continue
            if c != "\n": out[i] = " "
            i += 1; continue
        # str/char
        q = '"' if state == "str" else "'"
        if c == "\\" and i + 1 < n:
            out[i] = out[i + 1] = " "; i += 2; continue
        if c == q: state = None; i += 1; continue
        out[i] = " "; i += 1; continue
    return "".join(out)


def escaped_locals(source: str, function: str) -> set[str]:
    """Locals whose address is taken anywhere in the function body (conservative
    superset). v1 does not use this for legality (immovable barriers subsume it),
    but it is surfaced in unit metadata and reserved for v2 nested-block relaxation."""
    return set(_ADDR_RE.findall(_mask(source)))


def classify_movable(stmt: SiblingStmt, locals_: set[str]) -> Optional[MovableInfo]:
    if stmt.kind != "simple":
        return None
    text = _mask(stmt.text).strip()
    if not text.endswith(";"):
        return None
    text = text[:-1]
    # locate the single plain-assignment '='; reject compound/comparison
    eq = -1
    for i, ch in enumerate(text):
        if ch == "=":
            prev = text[i - 1] if i > 0 else ""
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if prev in _ASSIGN_PREV_FORBID or nxt == "=":
                return None     # +=, ==, <=, >=, != ... not a plain assignment
            eq = i
            break
    if eq == -1:
        return None
    lhs, rhs = text[:eq].strip(), text[eq + 1:].strip()
    # LHS must be `base` or `base.field`, base a local
    m = re.fullmatch(r"([A-Za-z_]\w*)(?:\.([A-Za-z_]\w*))?", lhs)
    if m is None:
        return None
    base, fld = m.group(1), m.group(2)
    if base not in locals_:
        return None
    # RHS: no nested assignment/comparison ('=' of any kind), no unsafe memory/call ops
    if "=" in rhs:
        return None
    if _UNSAFE_RHS_RE.search(rhs):
        return None
    # extract reads: drop `.member` accesses and numeric literals first
    rhs_clean = re.sub(r"\.\s*[A-Za-z_]\w*", "", rhs)
    rhs_clean = re.sub(r"\b\d[\w.]*", "", rhs_clean)
    reads = {tok for tok in _IDENT_RE.findall(rhs_clean) if tok not in _C_KEYWORDS}
    if not reads <= locals_:        # any non-local read (global / type-cast name) -> reject
        return None
    return MovableInfo(write_base=base, is_field=fld is not None,
                       reads=frozenset(reads), writes=frozenset({base}))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k "mask or classify or escaped" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A tools/melee-agent/src/search/statement_move.py tools/melee-agent/tests/search/test_statement_move.py
git commit -m "feat(search): masker + conservative movable-unit classification + escaped scan"
```

---

## Task 3: Top-level local names + group formation (`extract_movable_units`)

**Files:** Modify `src/search/statement_move.py`; Test `tests/search/test_statement_move.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/search/test_statement_move.py
from src.search.statement_move import extract_movable_units, local_names

def test_local_names_excludes_nested_block_decls():
    src = '''\
void f(int idx)
{
    int top;
    top = idx;
    if (idx != 0) {
        int inner;
        inner = idx;
    }
}
'''
    if toplevel_siblings(src, "f") is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    names = local_names(src, "f")
    assert "top" in names and "idx" in names
    assert "inner" not in names          # nested-block local is NOT a top-level local

def test_extract_units_clusters_aggregate_fields_and_keeps_singletons():
    sibs = toplevel_siblings(POS_SRC, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(POS_SRC, "f")
    units = extract_movable_units(sibs, locs)
    pos_units = [u for u in units if u.write_base == "pos"]
    assert len(pos_units) == 1
    assert pos_units[0].is_cluster is True
    assert pos_units[0].index_range[1] - pos_units[0].index_range[0] == 2  # 3 stmts inclusive
    bases = {u.write_base for u in units}
    assert {"pos", "pad", "result"} <= bases       # pad and result are separate singletons
    # cluster self-reads are NOT subtracted away
    assert pos_units[0].reads == frozenset({"translate", "spacing"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k "local_names or extract" -v`
Expected: FAIL — `ImportError: extract_movable_units`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/search/statement_move.py

@dataclass(frozen=True)
class MoveUnit:
    write_base: str
    is_cluster: bool
    reads: frozenset
    writes: frozenset
    index_range: tuple[int, int]   # inclusive sibling indices [i, j]
    byte_range: tuple[int, int]    # spanning byte range


def _leftmost_identifier(node):
    if node is None:
        return None
    if node.type == "identifier":
        return node
    d = node.child_by_field_name("declarator")
    if d is not None:
        r = _leftmost_identifier(d)
        if r is not None:
            return r
    for c in node.named_children:
        r = _leftmost_identifier(c)
        if r is not None:
            return r
    return None


def _declared_names(decl_node, source_bytes) -> set[str]:
    names: set[str] = set()
    type_node = decl_node.child_by_field_name("type")
    type_id = type_node.id if type_node is not None else None
    for child in decl_node.named_children:
        if type_id is not None and child.id == type_id:
            continue
        if child.type == "comment":
            continue
        ident = _leftmost_identifier(child)
        if ident is not None:
            names.add(_ts.node_text(source_bytes, ident))
    return names


def local_names(source: str, function: str) -> set[str]:
    """Param names + the function's TOP-LEVEL local declarations (NOT nested-block
    locals — a nested-only name is out of scope for a top-level statement)."""
    body, source_bytes = _body_node(source, function)
    names: set[str] = set()
    if body is None:
        return names
    for child in body.named_children:
        if child.type == "declaration":
            names |= _declared_names(child, source_bytes)
    fn = body.parent  # function_definition
    stack = [fn] if fn is not None else []
    param_list = None
    while stack:
        n = stack.pop()
        if n.type == "parameter_list":
            param_list = n
            break
        stack.extend(n.children)
    if param_list is not None:
        for p in param_list.named_children:
            if p.type == "parameter_declaration":
                ident = _leftmost_identifier(p)
                if ident is not None:
                    names.add(_ts.node_text(source_bytes, ident))
    return names


def extract_movable_units(sibs: list[SiblingStmt], locals_: set[str]) -> list[MoveUnit]:
    infos = [classify_movable(s, locals_) for s in sibs]
    units: list[MoveUnit] = []
    i, n = 0, len(sibs)
    while i < n:
        info = infos[i]
        if info is None:
            i += 1
            continue
        j = i
        if info.is_field:
            while (j + 1 < n and infos[j + 1] is not None
                   and infos[j + 1].is_field
                   and infos[j + 1].write_base == info.write_base):
                j += 1
        reads: set[str] = set()
        writes: set[str] = set()
        for k in range(i, j + 1):
            reads |= set(infos[k].reads)
            writes |= set(infos[k].writes)
        units.append(MoveUnit(
            write_base=info.write_base,
            is_cluster=(j > i),
            reads=frozenset(reads),     # NOTE: do NOT subtract writes (keeps aggregate self-reads)
            writes=frozenset(writes),
            index_range=(i, j),
            byte_range=(sibs[i].byte_range[0], sibs[j].byte_range[1]),
        ))
        i = j + 1
    return units
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k "local_names or extract" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A tools/melee-agent/src/search/statement_move.py tools/melee-agent/tests/search/test_statement_move.py
git commit -m "feat(search): top-level local names + aggregate-field clustering"
```

---

## Task 4: `legal_destinations` (def-use + unconditional opaque barriers)

**Files:** Modify `src/search/statement_move.py`; Test `tests/search/test_statement_move.py`

Destination-slot semantics (used by both `legal_destinations` and `apply_move`): **slot `d` means "insert before sibling `d`"**; `d == len(sibs)` means "at the end of the block, before `}`". The unit occupies `[lo, hi]`; slots `[lo, hi+1]` are identity/no-move and are excluded.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/search/test_statement_move.py
from src.search.statement_move import legal_destinations

def _idx_of(sibs, needle):
    return next(i for i, s in enumerate(sibs) if needle in s.text)

def test_legal_destinations_raw_dependency_blocks_moving_past_use():
    src = '''\
void f(int idx)
{
    int a;
    int b;
    int c;
    a = idx;
    b = idx;
    c = a;
}
'''
    sibs = toplevel_siblings(src, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(src, "f")
    units = extract_movable_units(sibs, locs)
    a_unit = next(u for u in units if u.write_base == "a")
    legal = legal_destinations(sibs, a_unit, escaped=set(), locals_=locs)
    ci = _idx_of(sibs, "c = a")
    assert ci in legal              # may move down to just BEFORE c (a still precedes its use)
    assert (ci + 1) not in legal    # may NOT move past c (would break c's read of a)
    bi = _idx_of(sibs, "b = idx")
    assert any(d > bi for d in legal)   # proves it crossed the independent `b = idx`

def test_legal_destinations_call_is_unconditional_hard_barrier():
    src = '''\
void f(int a, int b)
{
    int x;
    int y;
    x = a;
    y = b;
    g(b);
}
'''
    sibs = toplevel_siblings(src, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(src, "f")
    units = extract_movable_units(sibs, locs)
    x_unit = next(u for u in units if u.write_base == "x")
    legal = legal_destinations(sibs, x_unit, escaped=set(), locals_=locs)
    gi = _idx_of(sibs, "g(b)")
    assert gi in legal              # may move to just before the call (after y = b)
    assert (gi + 1) not in legal    # may NOT cross the call (unconditional barrier)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k legal -v`
Expected: FAIL — `ImportError: legal_destinations`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/search/statement_move.py

def _sibling_rw(stmt: SiblingStmt, locals_: set[str]) -> tuple[frozenset, frozenset, bool]:
    """(reads, writes, is_hard_barrier). A statement we cannot classify as a
    pure-local movable assignment is an unconditional hard barrier."""
    info = classify_movable(stmt, locals_)
    if info is not None:
        return info.reads, info.writes, False
    return frozenset(), frozenset(), True


def legal_destinations(sibs: list[SiblingStmt], unit: MoveUnit,
                       escaped: set[str], locals_: set[str]) -> list[int]:
    lo, hi = unit.index_range
    unit_escape_sensitive = bool((set(unit.reads) | set(unit.writes)) & escaped)

    def crosses_ok(t: SiblingStmt) -> bool:
        t_reads, t_writes, hard = _sibling_rw(t, locals_)
        if hard:
            return False    # clarification A: opaque/immovable = unconditional barrier
        if t_writes & (unit.reads | unit.writes):   # WAR / WAW
            return False
        if t_reads & unit.writes:                    # RAW (t reads what unit writes)
            return False
        # defense-in-depth (currently always satisfied since movable siblings are pure-local):
        if unit_escape_sensitive and (t_writes & escaped):
            return False
        return True

    legal: list[int] = []
    d = hi + 1                          # sink (down)
    while d <= len(sibs):
        legal.append(d)
        if d == len(sibs) or not crosses_ok(sibs[d]):
            break
        d += 1
    d = lo - 1                          # hoist (up)
    while d >= 0:
        if not crosses_ok(sibs[d]):
            break
        legal.append(d)
        d -= 1
    return sorted(x for x in set(legal) if x < lo or x > hi + 1)   # exclude identity window
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k legal -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A tools/melee-agent/src/search/statement_move.py tools/melee-agent/tests/search/test_statement_move.py
git commit -m "feat(search): legal-destination scan with unconditional opaque barriers"
```

---

## Task 5: `select_positions` (targeted + exhaustive seam)

**Files:** Modify `src/search/statement_move.py`; Test `tests/search/test_statement_move.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/search/test_statement_move.py
from src.search.statement_move import select_positions

def test_select_positions_targeted_sinks_to_first_use_and_exhaustive_is_full():
    sibs = toplevel_siblings(POS_SRC, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(POS_SRC, "f")
    units = extract_movable_units(sibs, locs)
    pos_unit = next(u for u in units if u.write_base == "pos")
    legal = legal_destinations(sibs, pos_unit, escaped=set(), locals_=locs)
    ri = _idx_of(sibs, "result.x = pos.x")
    assert legal == [ri]                       # only legal move: sink past `pad = idx;`
    targeted = select_positions(sibs, pos_unit, legal, "targeted", locs)
    exhaustive = select_positions(sibs, pos_unit, legal, "exhaustive", locs)
    assert targeted == [ri]                    # sink-to-first-use of `pos`
    assert set(exhaustive) == set(legal)       # seam: exhaustive consumes full legal set
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k select -v`
Expected: FAIL — `ImportError: select_positions`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/search/statement_move.py

def select_positions(sibs: list[SiblingStmt], unit: MoveUnit,
                     legal: list[int], strategy: str, locals_: set[str]) -> list[int]:
    if strategy == "exhaustive":
        return list(legal)
    legal_set = set(legal)
    picks: list[int] = []
    lo, hi = unit.index_range
    # sink: the legal slot at the first sibling AFTER the unit that reads unit.writes
    for i in range(hi + 1, len(sibs)):
        r, _, _ = _sibling_rw(sibs[i], locals_)
        if r & unit.writes:
            if i in legal_set:
                picks.append(i)
            break
    # hoist: just after the last sibling BEFORE the unit that writes any of unit.reads
    for i in range(lo - 1, -1, -1):
        _, w, _ = _sibling_rw(sibs[i], locals_)
        if w & unit.reads:
            if (i + 1) in legal_set:
                picks.append(i + 1)
            break
    return sorted(set(picks))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k select -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A tools/melee-agent/src/search/statement_move.py tools/melee-agent/tests/search/test_statement_move.py
git commit -m "feat(search): targeted/exhaustive position selection seam"
```

---

## Task 6: `apply_move` (UTF-8 full-line relocation, end-of-block safe)

**Files:** Modify `src/search/statement_move.py`; Test `tests/search/test_statement_move.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/search/test_statement_move.py
from src.search.statement_move import apply_move, _unit_owns_its_lines

def test_apply_move_identity_window_is_noop():
    sibs = toplevel_siblings(POS_SRC, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(POS_SRC, "f")
    pos_unit = next(u for u in extract_movable_units(sibs, locs) if u.write_base == "pos")
    lo, hi = pos_unit.index_range
    for dest in range(lo, hi + 2):
        assert apply_move(POS_SRC, sibs, pos_unit, dest) == POS_SRC

def test_apply_move_real_sink_preserves_lines_and_order():
    sibs = toplevel_siblings(POS_SRC, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(POS_SRC, "f")
    pos_unit = next(u for u in extract_movable_units(sibs, locs) if u.write_base == "pos")
    ri = _idx_of(sibs, "result.x = pos.x")
    moved = apply_move(POS_SRC, sibs, pos_unit, ri)
    assert moved.count("pos.x = translate.x;") == 1            # moved, not duplicated
    assert "    pos.x = translate.x;" in moved                 # indentation preserved
    assert moved.index("pad = idx;") < moved.index("pos.x = translate.x;")  # sank past pad
    assert moved.index("pos.z = translate.z;") < moved.index("result.x = pos.x;")
    assert moved.rstrip().endswith("}")                        # nothing escaped past `}`

def test_apply_move_to_end_of_block_stays_before_close_brace():
    src = '''\
void f(int idx)
{
    int a;
    int b;
    a = idx;
    b = idx;
}
'''
    sibs = toplevel_siblings(src, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(src, "f")
    a_unit = next(u for u in extract_movable_units(sibs, locs) if u.write_base == "a")
    moved = apply_move(src, sibs, a_unit, len(sibs))   # to end of block
    assert moved.count("a = idx;") == 1
    assert moved.index("b = idx;") < moved.index("a = idx;")
    assert moved.rstrip().endswith("}")
    assert moved.rstrip().splitlines()[-1].strip() == "}"   # `a = idx;` is BEFORE the close brace

def test_apply_move_non_ascii_is_byte_correct():
    src = "void f(){\n    int a;\n    int b;\n    a = 1; // café\n    b = 2;\n}\n"
    sibs = toplevel_siblings(src, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(src, "f")
    a_unit = next(u for u in extract_movable_units(sibs, locs) if u.write_base == "a")
    moved = apply_move(src, sibs, a_unit, _idx_of(sibs, "b = 2"))
    assert "café" in moved and moved.count("a = 1;") == 1

def test_unit_owns_its_lines_rejects_shared_line():
    src = "void f(int idx){\n    int a; int b;\n    a = idx; b = idx;\n}\n"
    sibs = toplevel_siblings(src, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(src, "f")
    units = extract_movable_units(sibs, locs)
    sb = src.encode("utf-8")
    # the `a = idx;` and `b = idx;` share one physical line -> not movable by line
    assert any(not _unit_owns_its_lines(u, sb) for u in units)

def test_unit_owns_its_lines_rejects_brace_sharing_line():
    # the close brace shares the last statement's physical line; a line move would drag `}`
    src = "void f(int idx){\n    int a;\n    a = idx; }\n"
    sibs = toplevel_siblings(src, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(src, "f")
    sb = src.encode("utf-8")
    a_unit = next(u for u in extract_movable_units(sibs, locs) if u.write_base == "a")
    assert not _unit_owns_its_lines(a_unit, sb)

def test_unit_owns_its_lines_allows_trailing_comment():
    src = "void f(int idx){\n    int a;\n    int b;\n    a = idx; // note\n    b = idx;\n}\n"
    sibs = toplevel_siblings(src, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(src, "f")
    sb = src.encode("utf-8")
    a_unit = next(u for u in extract_movable_units(sibs, locs) if u.write_base == "a")
    assert _unit_owns_its_lines(a_unit, sb)   # trailing comment masks to whitespace -> allowed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k "apply_move or owns_its_lines" -v`
Expected: FAIL — `ImportError: apply_move`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/search/statement_move.py

def _line_bounds(source_bytes: bytes, start: int, end: int) -> tuple[int, int]:
    """Expand [start,end) to full-line byte bounds: line start .. just past the
    trailing newline (or EOF)."""
    ls = source_bytes.rfind(b"\n", 0, start) + 1          # 0 if no preceding newline
    le = source_bytes.find(b"\n", end)
    le = len(source_bytes) if le == -1 else le + 1        # include the newline
    return ls, le


def _unit_owns_its_lines(unit: MoveUnit, source_bytes: bytes) -> bool:
    """True iff the bytes OUTSIDE the unit on its first/last physical lines are
    only whitespace/comments. Rejects multiple statements sharing a line
    (`a; b;`) AND a statement sharing its line with a brace (`b = idx; }`) —
    both corrupt a full-line move. A trailing comment IS allowed (it masks to
    whitespace and travels with the moved line)."""
    u0, u1 = unit.byte_range
    ls, le = _line_bounds(source_bytes, u0, u1)
    prefix = source_bytes[ls:u0].decode("utf-8", "replace")   # before unit on first line
    suffix = source_bytes[u1:le].decode("utf-8", "replace")   # after unit on last line
    return _mask(prefix).strip() == "" and _mask(suffix).strip() == ""


def apply_move(source: str, sibs: list[SiblingStmt], unit: MoveUnit, dest: int) -> str:
    lo, hi = unit.index_range
    if lo <= dest <= hi + 1:
        return source                # identity window
    b = source.encode("utf-8")
    mv_start, mv_end = _line_bounds(b, unit.byte_range[0], unit.byte_range[1])
    block = b[mv_start:mv_end]
    if not block.endswith(b"\n"):
        block = block + b"\n"
    if dest >= len(sibs):
        # end of block == just past the LAST sibling's line (before the closing brace),
        # never EOF.  (dest>=len with the unit already last is an identity, handled above.)
        _, ins_anchor = _line_bounds(b, sibs[-1].byte_range[0], sibs[-1].byte_range[1])
    else:
        ins_anchor, _ = _line_bounds(b, sibs[dest].byte_range[0], sibs[dest].byte_range[1])
    removed = b[:mv_start] + b[mv_end:]
    if ins_anchor >= mv_end:
        ins_anchor -= (mv_end - mv_start)        # downward move: account for removal
    out = removed[:ins_anchor] + block + removed[ins_anchor:]
    return out.decode("utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k "apply_move or owns_its_lines" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A tools/melee-agent/src/search/statement_move.py tools/melee-agent/tests/search/test_statement_move.py
git commit -m "feat(search): byte-line apply_move (end-of-block safe) + line-ownership guard"
```

---

## Task 7: Operator entry + integration into the axis

**Files:** Modify `src/search/statement_move.py` and `src/search/structure.py`; Test `tests/search/test_statement_move.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/search/test_statement_move.py
from src.search.statement_move import generate_statement_hoist_sink_variants

def test_operator_emits_distinct_candidates_with_metadata():
    if toplevel_siblings(POS_SRC, "f") is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    variants = generate_statement_hoist_sink_variants(POS_SRC, "f", max_candidates=12)
    assert variants, "expected at least one hoist-sink candidate"
    seen = set()
    for v in variants:
        assert v["operator"] == "statement-order-hoist-sink"
        assert v["candidate_source"] != POS_SRC
        assert v["candidate_source"] not in seen
        seen.add(v["candidate_source"])
        assert set(v["metadata"]) >= {"base", "dest", "direction", "is_cluster",
                                      "escape_sensitive"}
        assert len(v["byte_range"]) == 2

def test_operator_skips_units_not_owning_their_lines():
    src = "void f(int idx){\n    int a; int b;\n    a = idx; b = idx;\n}\n"
    if toplevel_siblings(src, "f") is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    variants = generate_statement_hoist_sink_variants(src, "f", max_candidates=12)
    # shared-line statements must never be emitted as line moves
    assert all("a = idx; b = idx;" not in v["candidate_source"] or
               v["candidate_source"] == src for v in variants)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k operator -v`
Expected: FAIL — `ImportError: generate_statement_hoist_sink_variants`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/search/statement_move.py

def generate_statement_hoist_sink_variants(
    source: str, function: str, max_candidates: int = 12, strategy: str = "targeted",
) -> list[dict[str, Any]]:
    """Return candidate dicts {operator, candidate_source, byte_range, metadata}.
    Does NOT write files (the host add_variant closure persists them). [] on
    ast-unavailable."""
    sibs = toplevel_siblings(source, function)
    if sibs is None:
        return []
    source_bytes = source.encode("utf-8")
    locs = local_names(source, function)
    escaped = escaped_locals(source, function)
    out: list[dict[str, Any]] = []
    seen = {source}
    for unit in extract_movable_units(sibs, locs):
        if not _unit_owns_its_lines(unit, source_bytes):
            continue
        legal = legal_destinations(sibs, unit, escaped, locs)
        for dest in select_positions(sibs, unit, legal, strategy, locs):
            # hoist-sink owns NON-adjacent relocations. A singleton crossing exactly
            # one sibling is a plain adjacent swap, already produced by the
            # adjacent-swap operator — skip it so that operator keeps its labeled
            # candidate. Clusters are exempt (a multi-statement cluster move is never
            # an adjacent swap). (Refinement found during Task 7 build: without this,
            # emit-first hoist-sink dedup-steals adjacent-swap's labeled output and
            # regresses test_statement_order_generates_only_safe_local_scalar_swaps.)
            lo, hi = unit.index_range
            crossed = (dest - hi - 1) if dest > hi + 1 else (lo - dest)
            if not unit.is_cluster and crossed == 1:
                continue
            if len(out) >= max_candidates:
                return out
            candidate = apply_move(source, sibs, unit, dest)
            if candidate in seen:
                continue
            seen.add(candidate)
            out.append({
                "operator": "statement-order-hoist-sink",
                "candidate_source": candidate,
                "byte_range": unit.byte_range,
                "metadata": {
                    "base": unit.write_base,
                    "dest": dest,
                    "direction": "sink" if dest > unit.index_range[1] else "hoist",
                    "is_cluster": unit.is_cluster,
                    "escape_sensitive": bool((set(unit.reads) | set(unit.writes)) & escaped),
                },
            })
    return out
```

Then wire it into `src/search/structure.py` `generate_statement_order_variants`. Add the import at the top of the module with the other `from .` imports, and insert the loop **immediately after** the `add_variant` closure definition and **before** the first existing `_generate_split_shift_or_statement_variants(...)` call (emit-first so the per-axis cap can't starve it):

```python
# inside generate_statement_order_variants, right after `def add_variant(...): ...`
    from .statement_move import generate_statement_hoist_sink_variants
    for cand in generate_statement_hoist_sink_variants(
        source, function, max_candidates=max_candidates):
        br = cand["byte_range"]
        add_variant(
            operator=cand["operator"],
            start=br[0],
            end=br[1],
            candidate_source=cand["candidate_source"],
            metadata=cand["metadata"],
        )
```

(`add_variant` writes the `.c` under `output_dir` and dedupes against `seen_sources`, so the operator itself writes nothing.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k operator -v`
Then integration smoke (must not crash; 0+ candidates allowed): `cd tools/melee-agent && python -m src.cli debug search structure -f mnEvent_8024D5B0 --axis statement-order --no-score --max-candidates 6`
Expected: unit PASS; CLI runs without traceback.

- [ ] **Step 5: Commit**

```bash
git add -A tools/melee-agent/src/search/statement_move.py tools/melee-agent/src/search/structure.py tools/melee-agent/tests/search/test_statement_move.py
git commit -m "feat(search): wire statement-hoist-sink operator into statement-order axis"
```

---

## Task 8: Shape-aware ranking for `statement-order` (incl. `line_delta`)

**Files:** Modify `src/search/structure.py`; Test `tools/melee-agent/tests/search/test_statement_move_ranking.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/search/test_statement_move_ranking.py
from src.search.structure import StructureVariant, rank_structure_variants

def _v(label, pct, shape, line_delta, axis="statement-order"):
    return StructureVariant(
        axis=axis, operator="statement-order-hoist-sink", label=label,
        status="ok", match_percent=pct, final_match_percent=pct, delta=0.0,
        metadata={"structural": {"opcode_shape_preserved": shape,
                                 "line_delta": line_delta}})

def test_statement_order_ranks_shape_preserved_first():
    ranked = rank_structure_variants([_v("breaks", 84.0, False, 0),
                                      _v("clean", 84.0, True, 0)])
    assert ranked[0].label == "clean"

def test_statement_order_breaks_ties_by_smaller_line_delta():
    # same %, both shape-preserved -> smaller |line_delta| ranks first
    ranked = rank_structure_variants([_v("far", 84.0, True, -6),
                                      _v("near", 84.0, True, 0)])
    assert ranked[0].label == "near"

def test_source_lifetime_ranking_unaffected_by_line_delta():
    # line_delta participates ONLY for statement-order. Construct the DISTINGUISHING
    # case: the higher-% variant has the LARGER line_delta. If line_delta were wrongly
    # applied to source-lifetime it would rank before match% and put `b` (line_delta 0)
    # first; correct behavior ignores line_delta here, so higher-% `a` wins.
    a = _v("a", 90.0, True, 9, axis="source-lifetime")   # higher %, LARGER line_delta
    b = _v("b", 84.0, True, 0, axis="source-lifetime")   # lower %, smaller line_delta
    ranked = rank_structure_variants([b, a])             # input order must not matter
    assert [v.label for v in ranked] == ["a", "b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move_ranking.py -v`
Expected: FAIL — `test_statement_order_ranks_shape_preserved_first` and `test_statement_order_breaks_ties_by_smaller_line_delta` fail (statement-order not shape-ranked yet).

- [ ] **Step 3: Write minimal implementation**

In `src/search/structure.py`, generalize the source-lifetime shape rank to a shared shape-aware rank covering both axes, and add a statement-order-only `line_delta` tiebreak. Add near the existing `_source_lifetime_shape_rank`:

```python
_SHAPE_AWARE_AXES = {"source-lifetime", "statement-order"}

def _shape_rank(variant: StructureVariant) -> int:
    if variant.axis not in _SHAPE_AWARE_AXES:
        return 0
    if variant.status != "ok":
        return 4
    if variant.unscored_reason == SCORE_CAP_UNSCORED_REASON:
        return 4
    if variant.unscored_reason or variant.compile_status not in (None, "ok"):
        return 3
    structural = variant.metadata.get("structural")
    if not isinstance(structural, dict):
        return 3
    if structural.get("opcode_shape_preserved") is True:
        return 0
    if structural.get("opcode_shape_preserved") is False:
        return 2
    return 3

def _line_delta_rank(variant: StructureVariant) -> int:
    # participate ONLY for statement-order (preserves existing source-lifetime order)
    if variant.axis != "statement-order":
        return 0
    structural = variant.metadata.get("structural")
    if isinstance(structural, dict) and "line_delta" in structural:
        try:
            return abs(int(structural["line_delta"]))
        except (TypeError, ValueError):
            return 9999
    return 9999

def _shape_aware_in_axis_sort_key(variant: StructureVariant) -> tuple[Any, ...]:
    return (
        _exact_match_bucket(variant),
        _shape_rank(variant),
        _line_delta_rank(variant),
        *_structure_variant_common_sort_key(variant),
    )

def _rank_shape_aware_slots(variants: list[StructureVariant]) -> list[StructureVariant]:
    ranked_iters = {
        axis: iter(sorted((v for v in variants if v.axis == axis),
                          key=_shape_aware_in_axis_sort_key))
        for axis in _SHAPE_AWARE_AXES
    }
    out: list[StructureVariant] = []
    for v in variants:
        out.append(next(ranked_iters[v.axis]) if v.axis in _SHAPE_AWARE_AXES else v)
    return out
```

The public entry point already exists — `rank_structure_variants(variants)` at `structure.py:110`:

```python
def rank_structure_variants(variants: list[StructureVariant]) -> list[StructureVariant]:
    ranked = _rank_source_lifetime_slots(sorted(
        variants,
        key=_structure_variant_base_sort_key,
    ))
    # ... (existing rank-number assignment below; leave intact)
```

Change the single call `_rank_source_lifetime_slots(...)` → `_rank_shape_aware_slots(...)`. No new public wrapper is needed. Then grep for stale references: `grep -rn "_source_lifetime_in_axis_sort_key\|_rank_source_lifetime_slots\|_source_lifetime_shape_rank" src tests`. If anything outside `structure.py` imports them, keep thin aliases (`_rank_source_lifetime_slots = _rank_shape_aware_slots`, `_source_lifetime_in_axis_sort_key = _shape_aware_in_axis_sort_key`); otherwise delete the old names. Note for the implementer: `_shape_rank` returns the SAME values for `source-lifetime` as the old `_source_lifetime_shape_rank`, and `_line_delta_rank` returns a constant `0` for `source-lifetime`, so source-lifetime ordering is unchanged (the third test pins this).

- [ ] **Step 4: Run tests to verify they pass + no regression**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move_ranking.py tests/search/test_structure.py -v`
Expected: PASS (including all pre-existing `test_structure.py` ranking tests).

- [ ] **Step 5: Add a fake-scored integration ranking test (production path)**

```python
# append to tests/search/test_statement_move_ranking.py
import tempfile
from pathlib import Path
from src.search.structure import run_structure_search, StructureScoreResult

RANK_SRC = '''\
void f(int idx, float spacing)
{
    Vec3 translate;
    Vec3 pos;
    Vec3 result;
    int pad;
    pos.x = translate.x;
    pos.y = spacing;
    pos.z = translate.z;
    pad = idx;
    result.x = pos.x;
}
'''

def test_run_structure_search_ranks_statement_order_by_shape(tmp_path):
    src = tmp_path / "f.c"
    src.write_text(RANK_SRC)

    def fake_score(variants):
        # mark the FIRST generated candidate as shape-breaking, the rest preserved,
        # all same %, so shape ranking (not generation order) must decide the top slot.
        results = []
        for i, v in enumerate(variants):
            preserved = (i != 0)
            results.append(StructureScoreResult(
                label=v.label, baseline_percent=80.0, candidate_percent=80.0,
                compile_status="ok", checkdiff_status="ok",
                structural={"opcode_shape_preserved": preserved, "line_delta": 0}))
        return results

    payload = run_structure_search(
        function="f", source_path=str(src), output_dir=str(tmp_path / "out"),
        axes=["statement-order"], baseline_percent=80.0,
        score_runner=fake_score, score_variants=True)
    variants = payload["variants"]
    if len(variants) < 2:
        import pytest; pytest.skip("need >=2 generated candidates to prove ranking")
    top = variants[0]
    assert top["metadata"]["structural"]["opcode_shape_preserved"] is True
```

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move_ranking.py -v`
Expected: PASS (or skip only if <2 candidates generated). This proves statement-order structural metadata reaches and affects the real `rank_structure_variants` path, not just the hand-built unit test.

- [ ] **Step 6: Commit**

```bash
git add -A tools/melee-agent/src/search/structure.py tools/melee-agent/tests/search/test_statement_move_ranking.py
git commit -m "feat(search): shape-aware ranking (+line_delta) for statement-order axis"
```

---

## Task 9: D15C safety validation (non-vacuous)

**Files:** Test `tools/melee-agent/tests/search/test_statement_move_d15c.py`; no new src.

Grounding: in `mnEvent_8024D15C`, `pos.x = translate.x;` (line 150) and `pos.z = translate.z;` (line 152) ARE classified movable (singletons), but `pos.y` (line 151, has `*` and a cast) is immovable and the statements above (`data_offset = idx * 4;`, the `row` cast) are immovable — so pos.x and pos.z are **bracketed by immovable siblings on both sides** → zero legal destinations → the operator correctly emits **no** move for them. This is the safety property: the analysis engages (extracts pos.x/pos.z) yet generates nothing unsafe.

- [ ] **Step 1: Write the D15C safety test**

```python
# tests/search/test_statement_move_d15c.py
from pathlib import Path
import pytest
from src.search.statement_move import (
    toplevel_siblings, local_names, escaped_locals, extract_movable_units,
    legal_destinations, generate_statement_hoist_sink_variants)

REPO = Path(__file__).resolve().parents[4]  # tools/melee-agent/tests/search/<file> -> repo root
MNEVENT = REPO / "src/melee/mn/mnevent.c"
FN = "mnEvent_8024D15C"

def _units_and_ctx():
    src = MNEVENT.read_text()
    sibs = toplevel_siblings(src, FN)
    if sibs is None:
        pytest.skip("tree-sitter unavailable")
    locs = local_names(src, FN)
    esc = escaped_locals(src, FN)
    return src, sibs, locs, esc, extract_movable_units(sibs, locs)

@pytest.mark.skipif(not MNEVENT.exists(), reason="mnevent.c absent")
def test_d15c_extracts_pos_x_and_pos_z_but_they_cannot_move():
    src, sibs, locs, esc, units = _units_and_ctx()
    def _unit_on_line(ln):
        return next((u for u in units
                     if sibs[u.index_range[0]].line_range[0] <= ln <= sibs[u.index_range[1]].line_range[1]), None)
    pos_x = _unit_on_line(150)
    pos_z = _unit_on_line(152)
    # non-vacuous: the model DOES identify pos.x and pos.z as movable singletons
    assert pos_x is not None and pos_x.write_base == "pos"
    assert pos_z is not None and pos_z.write_base == "pos"
    assert "translate" in esc                              # &translate is taken
    # ...but both are bracketed by immovable siblings -> ZERO legal destinations
    assert legal_destinations(sibs, pos_x, esc, locs) == []
    assert legal_destinations(sibs, pos_z, esc, locs) == []

@pytest.mark.skipif(not MNEVENT.exists(), reason="mnevent.c absent")
def test_d15c_generates_no_unsafe_move():
    src = MNEVENT.read_text()
    if toplevel_siblings(src, FN) is None:
        pytest.skip("tree-sitter unavailable")
    variants = generate_statement_hoist_sink_variants(src, FN, max_candidates=24)
    # every candidate (if any) MUST keep pos.x before the row->gobjs call block and
    # before the second translate reload at line 166 -> i.e. pos is never relocated.
    for v in variants:
        cs = v["candidate_source"]
        assert cs.index("pos.x = translate.x;") < cs.index("if (row->gobjs[0]")
        assert cs.index("pos.z = translate.z;") < cs.index("if (row->gobjs[0]")
```

- [ ] **Step 2: Run the safety test**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move_d15c.py -v`
Expected: PASS. If `test_d15c_extracts_pos_x_and_pos_z_but_they_cannot_move` fails on the `== []` assertions, the barrier logic is too permissive — fix Task 4 before continuing. If pos.x/pos.z are NOT extracted, classification regressed — fix Task 2.

- [ ] **Step 3: Full suite + real CLI run on D15C**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py tests/search/test_statement_move_ranking.py tests/search/test_statement_move_d15c.py tests/search/test_structure.py tests/search/test_structure_scoring.py -q`
Run (real, from this worktree): `cd /Users/mike/code/melee/.claude/worktrees/goofy-burnell-a2a060/tools/melee-agent && python -m src.cli debug search structure -f mnEvent_8024D15C --axis statement-order --max-candidates 12`
Expected: all tests pass; the CLI runs and reports a result without crashing. **Record** the candidate count and whether any improves the structure score (expected: few/zero candidates for D15C, per the bracketing — this is the honest empirical "is statement order the lever here?" answer, and validates that the substrate is safe).

- [ ] **Step 4: Commit + record outcome**

```bash
git add -A tools/melee-agent/tests/search/test_statement_move_d15c.py
git commit -m "test(search): D15C statement-move safety validation (non-vacuous)"
```

- [ ] **Step 5: Final Codex review** of the whole implementation (diff from this plan's first commit to HEAD), focusing on: the classifier rejecting all side-effecting RHS (no false-accept), `apply_move` byte correctness (no corruption / end-of-block), the unconditional-barrier safety model, and the ranking change (no source-lifetime regression). Address any Critical/Important findings before declaring done.

---

## Self-Review notes (against the spec + Codex plan-review findings)

- **Spec components 1–8 → tasks:** (1) compound-sibling model = Task 1 (top-level v1; nested deferred); (2) classification + escaped = Task 2; (3) clustering + singletons = Task 3; (4) legal-destinations + barrier model = Task 4; (5) targeted/exhaustive seam = Task 5; (6) `apply_move` = Task 6; (7) operator + emit-first integration = Task 7; (8) shape-aware ranking = Task 8; validation = Task 9.
- **Codex plan-review findings, all addressed:**
  - Masking import (was `source_patch._mask_c_comments_and_literals`, nonexistent) → **local `_mask`** in Task 2.
  - `pos.x = translate.x;` falsely rejected → Task 2 **strips `.member` and numeric literals** before read extraction; test pins acceptance.
  - RHS nested-assignment false-accept (`a=b=c`, `a=(b=c)`, `a=b+=c`) → Task 2 **rejects any `=` in RHS**; comparisons (`==` etc.) likewise; tests pin all.
  - `local_names` included nested-block locals → Task 3 derives names **only from top-level declarations + params** (no `walk_function` recursion); test pins exclusion.
  - cluster `reads - writes` erased self-reads → Task 3 **keeps reads unsubtracted**; test pins `{translate, spacing}`.
  - Task 4 slot off-by-one + `or True` → rewritten with **concrete slot semantics** (`ci in legal`, `ci+1 not in legal`) and **no escape hatch**.
  - `select_positions` used unit-set not full locals → Task 5 **threads `locals_`** into `_sibling_rw`.
  - `apply_move(dest==len)` inserted at EOF past `}` → Task 6 uses the **last sibling's line end**; test asserts text stays before `}`.
  - Ranking ignored `line_delta` → Task 8 adds **`_line_delta_rank`** (statement-order only) + a tie-break test.
  - Task 8 inert-in-production risk → verified axis-agnostic (`structure_scoring.py:230/345`, `structure.py:548`) + a **fake-scored `run_structure_search` integration test**.
  - D15C test vacuity → Task 9 asserts pos.x/pos.z **are extracted** AND have **zero legal destinations** (non-vacuous safety).
- **Beyond Codex:** dropped the dead `touches_escaped_or_nonlocal`; documented that `escaped` is **subsumed** by the unconditional-opaque-barrier rule in v1 (kept as tested telemetry + defense-in-depth + v2 hook); added a **line-ownership guard** (`_unit_owns_its_lines`) that requires whitespace/comments-only outside the unit on its physical lines, so neither multi-statement lines (`a; b;`) nor brace-sharing lines (`b = idx; }`) are ever line-moved (byte-corruption hazard), while trailing comments remain allowed.
- **Type consistency:** `SiblingStmt(text, byte_range, line_range, kind, node_type)`, `MovableInfo(write_base, is_field, reads, writes)` (frozensets), `MoveUnit(write_base, is_cluster, reads, writes, index_range, byte_range)`; `legal_destinations(sibs, unit, escaped, locals_)`, `select_positions(sibs, unit, legal, strategy, locals_)`, `apply_move(source, sibs, unit, dest)`, `generate_statement_hoist_sink_variants(source, function, max_candidates=12, strategy="targeted") -> list[dict]` used consistently; host adapts dicts via `add_variant(*, operator, start, end, candidate_source, metadata)`.

## Final-review safety fixes (Task 9 Step 5 — Codex merge gate, fixed in `fdb6decea`)

The final whole-implementation Codex review found two safety blockers the per-task code missed; both fixed:
- **Destination-side line ownership.** `_unit_owns_its_lines` validated only the *moved* unit, but `apply_move` inserts at the *destination* sibling's line start. A destination sibling sharing its physical line with another sibling (`c = idx; d = idx;`) let the splice cross an unchecked sibling (reading `c` before its def). Fix: `_dest_line_boundary_clean(sibs, dest, source_bytes)` — for `dest<len` the destination sibling must own its line START; for `dest==len` the last sibling must own its line END — gated in the operator before `apply_move`. Test `test_operator_skips_dest_sharing_a_line`.
- **Volatile locals.** `local_names` dropped qualifiers, so a `volatile` local was movable (reordering volatile stores). Fix: `local_names` excludes `volatile`-qualified declarations and params (`\bvolatile\b` on masked text); since `classify_movable` rejects any statement whose LHS base / RHS reads aren't in `locals_`, every volatile-touching statement becomes a hard barrier. Test `test_volatile_locals_are_immovable`. (The spec already listed volatile as immovable — this aligned the implementation with it.)
