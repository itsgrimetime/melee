# Statement Hoist/Sink Operator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `statement-hoist-sink` operator to the existing `statement-order` structure-search axis that relocates conservatively-safe movable units (simple no-call local assignments, and local-aggregate field-write clusters like `pos.x/y/z`) among a function's top-level compound-block siblings, def-use- and escaped-call-safe, scored with shape-aware ranking.

**Architecture:** A new pure module `src/search/statement_move.py` builds a top-level-sibling model on the shared tree-sitter parser (`src.common.tree_sitter_c`), classifies movable units, computes legal destinations with opaque/escaped-call barriers, selects targeted positions (expandable to exhaustive), and rewrites source by byte-line move. It plugs into `generate_statement_order_variants()` via the existing `add_variant` closure and is ranked by an extended shape-aware sort. Spec: `docs/superpowers/specs/2026-06-07-statement-hoist-sink-axis-design.md`.

**Tech Stack:** Python 3, tree-sitter-c (`src/common/tree_sitter_c.py`), pytest (`tools/melee-agent/tests/search/`).

**Conventions:**
- Paths relative to repo root unless absolute. Package root: `tools/melee-agent/`. Run tests from there: `python -m pytest tests/<f> -v`.
- Package imports: `from ..common import tree_sitter_c`, `from .structure import ...`; tests use `from src.search.statement_move import ...`.
- **v1 scope:** only the function's **top-level** compound block's direct sibling statements. Control/nested-block/declaration statements are **opaque, immovable, hard barriers** (never crossed, never recursed into). Nested-block movement is a documented future expansion.
- Commit after each task on the current worktree branch.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/search/statement_move.py` (NEW) | `SiblingStmt`, `MoveUnit`, `toplevel_siblings`, `escaped_locals`, `classify_movable`, `extract_movable_units`, `legal_destinations`, `select_positions`, `apply_move`, `generate_statement_hoist_sink_variants`. |
| `src/search/structure.py` (MODIFY) | Call the new operator from `generate_statement_order_variants` (emit first); extend shape-aware ranking to `statement-order`. |
| `tests/search/test_statement_move.py` (NEW) | Unit tests for every helper (no compiler). |
| `tests/search/test_statement_move_ranking.py` (NEW) | Shape-aware ranking covers `statement-order`. |
| `tests/search/test_statement_move_d15c.py` (NEW) | D15C safety + yield (skip-if-objects-absent / compiler-gated). |

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
    # declaration(opaque), simple a=idx, opaque if-block, simple b.x=a
    assert kinds == ["opaque", "simple", "opaque", "simple"]
    # the inner `a = a + 1;` is NOT a top-level sibling
    assert all("a + 1" not in s.text for s in sibs if s.kind == "simple")
    # siblings are in source order with byte ranges
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
blocks; control/nested/declaration statements are opaque barriers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..common import tree_sitter_c as _ts

# tree-sitter-c node types that are control/compound statements -> opaque
_OPAQUE_KINDS = {
    "if_statement", "for_statement", "while_statement", "do_statement",
    "switch_statement", "compound_statement", "labeled_statement",
    "goto_statement", "declaration",
}


@dataclass(frozen=True)
class SiblingStmt:
    text: str
    byte_range: tuple[int, int]
    line_range: tuple[int, int]
    kind: str  # "simple" (movable candidate) | "opaque" (barrier)
    node_type: str


def _function_body_node(tree, source_bytes: bytes, function: str):
    root = tree.root_node
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "function_definition":
            decl = node.child_by_field_name("declarator")
            ident = _find_identifier(decl) if decl is not None else None
            if ident is not None:
                name = source_bytes[ident.start_byte:ident.end_byte].decode("utf-8")
                if name == function:
                    return node.child_by_field_name("body")
        stack.extend(node.children)
    return None


def _find_identifier(node):
    # descend through (pointer_)?function_declarator to the leftmost identifier
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "identifier":
            return n
        stack.extend(reversed(n.children))
    return None


def toplevel_siblings(source: str, function: str) -> Optional[list[SiblingStmt]]:
    if not _ts.is_available():
        return None
    parser = _ts.get_parser()
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    body = _function_body_node(tree, source_bytes, function)
    if body is None:
        return None
    sibs: list[SiblingStmt] = []
    for child in body.named_children:
        # skip comments
        if child.type == "comment":
            continue
        text = source_bytes[child.start_byte:child.end_byte].decode("utf-8")
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
Expected: PASS (or skip if tree-sitter unavailable). If `expression_statement` is not the node type for `a = idx;`, print `[s.node_type for s in sibs]` and adjust `_OPAQUE_KINDS` / kind logic — only assignment `expression_statement`s should be `"simple"`.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/search/statement_move.py tools/melee-agent/tests/search/test_statement_move.py
git commit -m "feat(search): top-level compound-sibling model for statement moves"
```

---

## Task 2: Movable-unit classification + `escaped_locals`

**Files:** Modify `src/search/statement_move.py`; Test `tests/search/test_statement_move.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/search/test_statement_move.py
from src.search.statement_move import classify_movable, escaped_locals

def _mk(text, kind="simple"):
    from src.search.statement_move import SiblingStmt
    return SiblingStmt(text=text, byte_range=(0, len(text)), line_range=(1, 1),
                       kind=kind, node_type="expression_statement")

def test_classify_movable_accepts_simple_local_and_aggregate_field():
    scalar = classify_movable(_mk("a = idx;"), locals_={"a", "idx"})
    assert scalar is not None and scalar.write_base == "a" and scalar.reads == {"idx"}
    field = classify_movable(_mk("pos.x = translate.x;"), locals_={"pos", "translate"})
    assert field is not None and field.write_base == "pos" and field.is_field is True
    assert field.reads == {"translate"}

def test_classify_movable_rejects_calls_pointers_arrays_and_side_effects():
    locs = {"a", "p", "arr", "i"}
    assert classify_movable(_mk("a = f(idx);"), locals_=locs) is None      # call
    assert classify_movable(_mk("*p = a;"), locals_=locs) is None          # ptr store
    assert classify_movable(_mk("a = p->x;"), locals_=locs) is None        # ->
    assert classify_movable(_mk("arr[i] = a;"), locals_=locs) is None      # array
    assert classify_movable(_mk("a += idx;"), locals_=locs) is None        # compound assign
    assert classify_movable(_mk("a = idx++;"), locals_=locs) is None       # ++
    assert classify_movable(_mk("a = b ? c : d;"), locals_=locs) is None   # ?:
    assert classify_movable(_mk("g = a;"), locals_={"a"}) is None          # g not local (global)
    assert classify_movable(_mk("if (a) {}", kind="opaque"), locals_=locs) is None

def test_escaped_locals_finds_address_taken():
    src = "void f(){ Vec3 t; g(x, &t); h(& u); k(&(w)); }"
    esc = escaped_locals(src, "f")
    assert {"t", "u", "w"} <= esc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k "classify or escaped" -v`
Expected: FAIL — `ImportError: classify_movable`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/search/statement_move.py
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_ADDR_RE = re.compile(r"&\s*\(?\s*([A-Za-z_]\w*)")
# RHS side-effect / unsafe-memory markers (reject if present)
_UNSAFE_RHS_RE = re.compile(r"\+\+|--|->|\[|\*|&|\?|,|\b[A-Za-z_]\w*\s*\(")
_C_KEYWORDS = {"sizeof", "return", "if", "for", "while", "do", "switch"}


@dataclass(frozen=True)
class MovableInfo:
    write_base: str       # the local being written (aggregate base or scalar)
    is_field: bool        # True if `base.field = ...`
    reads: set[str]       # local identifiers read on the RHS
    writes: set[str]      # {write_base}


def _mask(text: str) -> str:
    # reuse the axis's comment/literal masker
    from ..mwcc_debug.source_patch import _mask_c_comments_and_literals
    return _mask_c_comments_and_literals(text)


def escaped_locals(source: str, function: str) -> set[str]:
    sibs = toplevel_siblings(source, function)
    scope_text = source if sibs is None else source  # &x anywhere in the TU body is conservative
    masked = _mask(scope_text)
    return set(_ADDR_RE.findall(masked))


def classify_movable(stmt: "SiblingStmt", locals_: set[str]) -> Optional[MovableInfo]:
    if stmt.kind != "simple":
        return None
    text = _mask(stmt.text).strip()
    if not text.endswith(";"):
        return None
    text = text[:-1]
    # split on the single top-level '='; reject compound assigns (handled by _UNSAFE on RHS too)
    if "=" not in text:
        return None
    lhs, _, rhs = text.partition("=")
    if lhs.rstrip().endswith(("+", "-", "*", "/", "|", "&", "^", "%", "<", ">", "!")):
        return None  # compound/`==`/`<=` etc.
    if rhs.startswith("="):
        return None  # `==`
    lhs = lhs.strip()
    rhs = rhs.strip()
    # LHS must be `base` or `base.field` with base a local
    m = re.fullmatch(r"([A-Za-z_]\w*)(?:\.([A-Za-z_]\w*))?", lhs)
    if m is None:
        return None
    base, fld = m.group(1), m.group(2)
    if base not in locals_:
        return None
    # RHS must be side-effect-free, no unsafe memory ops, identifiers all local/literal
    if _UNSAFE_RHS_RE.search(rhs):
        return None
    reads = {
        ident for ident in _IDENT_RE.findall(rhs)
        if ident not in _C_KEYWORDS and not ident[0].isdigit()
    }
    # every read identifier must be a known local (no globals) -- conservative
    if not reads <= locals_:
        return None
    return MovableInfo(write_base=base, is_field=fld is not None,
                       reads=reads, writes={base})
```

Note: `locals_` (the set of local + param names) is computed once per function in Task 3 from the declarations; pass it in. The `escaped_locals` scan over the whole function body is a conservative superset (fine per spec/review).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k "classify or escaped" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/search/statement_move.py tools/melee-agent/tests/search/test_statement_move.py
git commit -m "feat(search): classify movable units + escaped-local scan"
```

---

## Task 3: Group formation (`extract_movable_units`)

**Files:** Modify `src/search/statement_move.py`; Test `tests/search/test_statement_move.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/search/test_statement_move.py
from src.search.statement_move import extract_movable_units, local_names

POS_SRC = '''\
void f(int idx, float spacing)
{
    Vec3 translate;
    Vec3 pos;
    HSD_Text* text;
    pos.x = translate.x;
    pos.y = spacing;
    pos.z = translate.z;
    text->pos_x = pos.x;
    text->pos_y = pos.y;
}
'''

def test_extract_units_clusters_aggregate_fields_and_skips_pointer_members():
    sibs = toplevel_siblings(POS_SRC, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(POS_SRC, "f")
    units = extract_movable_units(sibs, locs)
    # the three pos.* writes form ONE cluster unit
    pos_units = [u for u in units if u.write_base == "pos"]
    assert len(pos_units) == 1
    assert pos_units[0].index_range[1] - pos_units[0].index_range[0] == 2  # 3 statements, inclusive
    assert pos_units[0].is_cluster is True
    # text->pos_x / pos_y are pointer members -> NOT movable, no unit
    assert all(u.write_base != "text" for u in units)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k extract -v`
Expected: FAIL — `ImportError: extract_movable_units`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/search/statement_move.py

@dataclass(frozen=True)
class MoveUnit:
    write_base: str
    is_cluster: bool
    reads: set[str]
    writes: set[str]
    index_range: tuple[int, int]   # inclusive sibling indices [i, j]
    byte_range: tuple[int, int]    # spanning byte range


def local_names(source: str, function: str) -> set[str]:
    """Param + local declaration names of the function (conservative)."""
    from ..mwcc_debug.ast_walker import walk_function, AstUnavailableError, AstWalkError
    names: set[str] = set()
    try:
        for decl in walk_function(source, function):
            names.add(decl.name)
    except (AstUnavailableError, AstWalkError):
        pass
    # also params via a light regex on the signature
    from ..mwcc_debug.source_patch import find_function
    span = find_function(source, function)
    if span is not None:
        sig = source[span.sig_start:span.body_open]
        paren = sig[sig.find("(") + 1:sig.rfind(")")]
        for part in paren.split(","):
            ids = _IDENT_RE.findall(_mask(part))
            if ids:
                names.add(ids[-1])  # last identifier = param name
    return names


def extract_movable_units(sibs: list[SiblingStmt], locals_: set[str]) -> list[MoveUnit]:
    infos = [classify_movable(s, locals_) for s in sibs]
    units: list[MoveUnit] = []
    i = 0
    n = len(sibs)
    while i < n:
        info = infos[i]
        if info is None:
            i += 1
            continue
        # try to extend an aggregate-field cluster: same base, is_field, contiguous
        j = i
        if info.is_field:
            while (j + 1 < n and infos[j + 1] is not None
                   and infos[j + 1].is_field
                   and infos[j + 1].write_base == info.write_base):
                j += 1
        reads: set[str] = set()
        writes: set[str] = set()
        for k in range(i, j + 1):
            reads |= infos[k].reads
            writes |= infos[k].writes
        units.append(MoveUnit(
            write_base=info.write_base,
            is_cluster=(j > i),
            reads=reads - writes,   # intra-unit writes aren't external reads
            writes=writes,
            index_range=(i, j),
            byte_range=(sibs[i].byte_range[0], sibs[j].byte_range[1]),
        ))
        i = j + 1
    return units
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k extract -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A tools/melee-agent/src/search/statement_move.py tools/melee-agent/tests/search/test_statement_move.py
git commit -m "feat(search): aggregate-field clustering + movable-unit extraction"
```

---

## Task 4: `legal_destinations` (def-use + opaque/escaped-call barriers)

**Files:** Modify `src/search/statement_move.py`; Test `tests/search/test_statement_move.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/search/test_statement_move.py
from src.search.statement_move import legal_destinations

def test_legal_destinations_blocks_crossing_opaque_when_reading_escaped():
    sibs = toplevel_siblings(POS_SRC, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(POS_SRC, "f")
    units = extract_movable_units(sibs, locs)
    pos_unit = next(u for u in units if u.write_base == "pos")
    # 'translate' is read by pos and (pretend) escaped -> cannot cross an opaque barrier
    legal = legal_destinations(sibs, pos_unit, escaped={"translate"})
    # POS_SRC has no opaque between pos cluster and the text-> uses (those are simple-but-immovable);
    # the immovable text-> statements are barriers too -> pos cannot sink past them
    assert pos_unit.index_range[1] + 1 not in legal or True  # see assertion below

def test_legal_destinations_simple_cases():
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
    a_unit = next(u for u in units if u.write_base == "a")  # `a = idx;`
    legal = legal_destinations(sibs, a_unit, escaped=set())
    # `a = idx` can move down past `b = idx` (no dep) but NOT past `c = a` (RAW on a)
    a_idx = a_unit.index_range[0]
    assert (a_idx + 1) in legal          # past b=idx ok
    c_idx = next(i for i, s in enumerate(sibs) if "c = a" in s.text)
    assert c_idx not in legal            # cannot land at/after c=a (reads a)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k legal -v`
Expected: FAIL — `ImportError: legal_destinations`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/search/statement_move.py

def _sibling_rw(stmt: SiblingStmt, locals_: set[str]) -> tuple[set[str], set[str], bool]:
    """Return (reads, writes, is_hard_barrier) for an arbitrary sibling.
    Opaque (control/decl/call/pointer/array/global) -> hard barrier."""
    info = classify_movable(stmt, locals_)
    if info is not None:
        return info.reads, info.writes, False
    return set(), set(), True  # immovable -> conservative hard barrier


def legal_destinations(sibs: list[SiblingStmt], unit: "MoveUnit",
                       escaped: set[str], locals_: set[str] | None = None) -> list[int]:
    if locals_ is None:
        locals_ = unit.reads | unit.writes
    lo, hi = unit.index_range
    touches_escaped_or_nonlocal = bool((unit.reads | unit.writes) & escaped)
    legal: list[int] = []

    def crosses_ok(t: SiblingStmt) -> bool:
        t_reads, t_writes, hard = _sibling_rw(t, locals_)
        if hard:
            # opaque barrier: blocked unconditionally for escaped/nonlocal units;
            # for purely-local units, still blocked (v1 conservative: any opaque
            # statement may have un-analyzed effects)
            return False
        # data dependence
        if t_writes & (unit.reads | unit.writes):
            return False
        if t_reads & unit.writes:
            return False
        return True

    # sink (move down): destination slot d means "after sibling d-1, before d";
    # legal d in (hi, n] while each crossed sibling is ok
    d = hi + 1
    while d <= len(sibs):
        legal.append(d)
        if d == len(sibs):
            break
        if not crosses_ok(sibs[d]):
            break
        d += 1
    # hoist (move up): legal d in [0, lo)
    d = lo - 1
    while d >= 0:
        if not crosses_ok(sibs[d]):
            break
        legal.append(d)
        d -= 1
    # identity window [lo, hi+1] is not a move
    legal = sorted(set(x for x in legal if x < lo or x > hi + 1))
    return legal
```

Note: `touches_escaped_or_nonlocal` is computed but the v1 rule treats *any* opaque sibling as a hard barrier regardless (Codex clarification A — opaque statements are unconditional barriers). Keep the variable for the future nested-block expansion where escaped-awareness refines it; if lint flags it unused, drop it. Adjust the first test's loose assertion to a concrete one once you observe the indices.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k legal -v`
Expected: PASS. Tighten `test_legal_destinations_blocks_crossing_opaque_when_reading_escaped` to assert the pos unit cannot reach the slot after the `text->` barriers.

- [ ] **Step 5: Commit**

```bash
git add -A tools/melee-agent/src/search/statement_move.py tools/melee-agent/tests/search/test_statement_move.py
git commit -m "feat(search): legal-destination computation with opaque/dep barriers"
```

---

## Task 5: `select_positions` (targeted + exhaustive seam)

**Files:** Modify `src/search/statement_move.py`; Test `tests/search/test_statement_move.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/search/test_statement_move.py
from src.search.statement_move import select_positions

def test_select_positions_targeted_and_exhaustive():
    sibs = toplevel_siblings(POS_SRC, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(POS_SRC, "f")
    units = extract_movable_units(sibs, locs)
    pos_unit = next(u for u in units if u.write_base == "pos")
    legal = legal_destinations(sibs, pos_unit, escaped=set(), locals_=locs)
    targeted = select_positions(sibs, pos_unit, legal, "targeted")
    exhaustive = select_positions(sibs, pos_unit, legal, "exhaustive")
    assert set(targeted) <= set(legal)
    assert set(exhaustive) == set(legal)
    assert len(targeted) <= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k select -v`
Expected: FAIL — `ImportError: select_positions`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/search/statement_move.py

def select_positions(sibs: list[SiblingStmt], unit: "MoveUnit",
                     legal: list[int], strategy: str) -> list[int]:
    if strategy == "exhaustive":
        return list(legal)
    # targeted: sink-to-first-use of unit.writes; hoist-to-after-last-def of unit.reads
    legal_set = set(legal)
    picks: list[int] = []
    lo, hi = unit.index_range
    # sink: first sibling AFTER the unit that reads any of unit.writes
    for i in range(hi + 1, len(sibs)):
        r, _, _ = _sibling_rw(sibs[i], unit.reads | unit.writes)
        if r & unit.writes and i in legal_set:
            picks.append(i)
            break
    # hoist: just after the last sibling BEFORE the unit that writes any of unit.reads
    for i in range(lo - 1, -1, -1):
        _, w, _ = _sibling_rw(sibs[i], unit.reads | unit.writes)
        if w & unit.reads:
            if (i + 1) in legal_set and (i + 1) < lo:
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

## Task 6: `apply_move` (UTF-8 byte-line relocation)

**Files:** Modify `src/search/statement_move.py`; Test `tests/search/test_statement_move.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/search/test_statement_move.py
from src.search.statement_move import apply_move

def test_apply_move_identity_and_real_move_preserve_indentation():
    sibs = toplevel_siblings(POS_SRC, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(POS_SRC, "f")
    units = extract_movable_units(sibs, locs)
    pos_unit = next(u for u in units if u.write_base == "pos")
    # identity: dest within [lo, hi+1] returns source unchanged
    assert apply_move(POS_SRC, sibs, pos_unit, pos_unit.index_range[0]) == POS_SRC
    # a real downward move keeps "    pos.x" indentation and stays compilable-shaped
    moved = apply_move(POS_SRC, sibs, pos_unit, len(sibs))
    assert "    pos.x = translate.x;" in moved
    assert moved.count("pos.x = translate.x;") == 1   # moved, not duplicated
    assert moved != POS_SRC

def test_apply_move_non_ascii_is_byte_correct():
    src = "void f(){\n    int a;\n    a = 1; // café\n    g();\n}\n"
    sibs = toplevel_siblings(src, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(src, "f")
    units = extract_movable_units(sibs, locs)
    assert units  # `a = 1;` is movable
    moved = apply_move(src, sibs, units[0], len(sibs))
    assert "café" in moved and moved.count("a = 1;") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k apply_move -v`
Expected: FAIL — `ImportError: apply_move`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/search/statement_move.py

def _line_bounds(source_bytes: bytes, start: int, end: int) -> tuple[int, int]:
    """Expand [start,end) to full-line byte bounds (line start .. after trailing \\n)."""
    ls = source_bytes.rfind(b"\n", 0, start) + 1           # 0 if not found
    le = source_bytes.find(b"\n", end)
    le = len(source_bytes) if le == -1 else le + 1          # include the newline
    return ls, le


def apply_move(source: str, sibs: list[SiblingStmt], unit: "MoveUnit", dest: int) -> str:
    lo, hi = unit.index_range
    if lo <= dest <= hi + 1:
        return source  # identity window
    b = source.encode("utf-8")
    mv_start, mv_end = _line_bounds(b, unit.byte_range[0], unit.byte_range[1])
    block = b[mv_start:mv_end]
    if not block.endswith(b"\n"):
        block = block + b"\n"
    # destination byte offset = full-line start of sibling `dest` (or EOF if dest==len)
    if dest >= len(sibs):
        ins_anchor = len(b)
    else:
        ins_anchor, _ = _line_bounds(b, sibs[dest].byte_range[0], sibs[dest].byte_range[1])
    # remove the moved block first
    removed = b[:mv_start] + b[mv_end:]
    # adjust insertion anchor if it was after the removed region
    if ins_anchor >= mv_end:
        ins_anchor -= (mv_end - mv_start)
    elif ins_anchor > mv_start:
        ins_anchor = mv_start  # shouldn't happen (dest outside unit), defensive
    out = removed[:ins_anchor] + block + removed[ins_anchor:]
    return out.decode("utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k apply_move -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A tools/melee-agent/src/search/statement_move.py tools/melee-agent/tests/search/test_statement_move.py
git commit -m "feat(search): byte-line apply_move with downward dest adjustment"
```

---

## Task 7: Operator entry + integration into the axis

**Files:** Modify `src/search/statement_move.py` and `src/search/structure.py`; Test `tests/search/test_statement_move.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/search/test_statement_move.py
import tempfile
from pathlib import Path
from src.search.statement_move import generate_statement_hoist_sink_variants

def test_operator_emits_compilable_shaped_candidates(tmp_path):
    sibs = toplevel_siblings(POS_SRC, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    variants = generate_statement_hoist_sink_variants(
        POS_SRC, "f", tmp_path, baseline_percent=50.0, max_candidates=12)
    # produces >=1 candidate, each written to a .c, operator label set, no duplicates of source
    assert variants, "expected at least one hoist-sink candidate"
    for v in variants:
        assert v["operator"] == "statement-order-hoist-sink"
        assert Path(v["path"]).read_text() != POS_SRC
        assert "base" in v["metadata"] and "dest" in v["metadata"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k operator -v`
Expected: FAIL — `ImportError: generate_statement_hoist_sink_variants`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/search/statement_move.py

def generate_statement_hoist_sink_variants(
    source: str, function: str, output_dir: Path,
    baseline_percent: float | None, max_candidates: int = 12,
    strategy: str = "targeted",
) -> list[dict[str, Any]]:
    """Standalone generator returning plain dicts (the structure.py host adapts
    these to StructureVariant via add_variant). Returns [] on ast-unavailable."""
    sibs = toplevel_siblings(source, function)
    if sibs is None:
        return []
    locs = local_names(source, function)
    escaped = escaped_locals(source, function)
    units = extract_movable_units(sibs, locs)
    output_dir.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    seen = {source}
    for unit in units:
        legal = legal_destinations(sibs, unit, escaped, locs)
        for dest in select_positions(sibs, unit, legal, strategy):
            if len(out) >= max_candidates:
                return out
            candidate = apply_move(source, sibs, unit, dest)
            if candidate in seen:
                continue
            seen.add(candidate)
            label = f"hoist-sink-{len(out)}"
            path = output_dir / f"{label}.c"
            path.write_text(candidate, encoding="utf-8")
            direction = "sink" if dest > unit.index_range[1] else "hoist"
            out.append({
                "operator": "statement-order-hoist-sink",
                "label": label,
                "path": str(path),
                "byte_range": unit.byte_range,
                "metadata": {"base": unit.write_base, "dest": dest,
                             "direction": direction, "is_cluster": unit.is_cluster},
            })
    return out
```

Then wire it into `src/search/structure.py` `generate_statement_order_variants` — **before** the existing `_generate_split_shift_or_statement_variants(...)` call (emit first so the cap doesn't starve it):

```python
# in generate_statement_order_variants, right after `seen_sources: set[str] = {source}`
# and the add_variant definition, BEFORE the existing _generate_* calls:
    from .statement_move import generate_statement_hoist_sink_variants
    for cand in generate_statement_hoist_sink_variants(
        source, function, output_dir, baseline_percent, max_candidates):
        candidate_source = Path(cand["path"]).read_text(encoding="utf-8")
        br = cand["byte_range"]
        add_variant(
            operator=cand["operator"],
            start=br[0],
            end=br[1],
            candidate_source=candidate_source,
            metadata=cand["metadata"],
        )
```

(`add_variant` re-dedupes and re-writes the `.c` under its own label scheme; the operator's own temp `.c` files in `output_dir` are harmless. If double-write is undesirable, pass `candidate_source` strings out of the generator instead of paths — optional cleanup.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py -k operator -v`
Then integration smoke: `cd tools/melee-agent && python -m src.cli debug search structure -f mnEvent_8024D5B0 --axis statement-order --no-score --max-candidates 6` (a matched fn; must not crash, may emit 0+ candidates).
Expected: unit PASS; CLI runs without traceback.

- [ ] **Step 5: Commit**

```bash
git add -A tools/melee-agent/src/search/statement_move.py tools/melee-agent/src/search/structure.py tools/melee-agent/tests/search/test_statement_move.py
git commit -m "feat(search): wire statement-hoist-sink operator into statement-order axis"
```

---

## Task 8: Shape-aware ranking for `statement-order`

**Files:** Modify `src/search/structure.py`; Test `tools/melee-agent/tests/search/test_statement_move_ranking.py`

- [ ] **Step 1: Write the failing test**

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
    # same %, but one preserves opcode shape and one doesn't -> shape-preserved ranks first
    variants = [_v("breaks", 84.0, False, -6), _v("clean", 84.0, True, 0)]
    ranked = rank_structure_variants(variants)
    assert ranked[0].label == "clean"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move_ranking.py -v`
Expected: FAIL — either `ImportError: rank_structure_variants` (if not exported) or AssertionError (statement-order not shape-ranked yet).

- [ ] **Step 3: Write minimal implementation**

In `src/search/structure.py`: generalize the `source-lifetime` shape-rank to cover `statement-order`. Rename `_source_lifetime_shape_rank` usage by adding a shared set and applying it in `_rank_source_lifetime_slots` (rename to `_rank_shape_aware_slots`):

```python
# near the top of the ranking section
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

def _shape_aware_in_axis_sort_key(variant: StructureVariant):
    return (_exact_match_bucket(variant), _shape_rank(variant),
            *_structure_variant_common_sort_key(variant))

def _rank_shape_aware_slots(variants):
    ranked_iter = {
        axis: iter(sorted((v for v in variants if v.axis == axis),
                          key=_shape_aware_in_axis_sort_key))
        for axis in _SHAPE_AWARE_AXES
    }
    out = []
    for v in variants:
        out.append(next(ranked_iter[v.axis]) if v.axis in _SHAPE_AWARE_AXES else v)
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

Change the single call `_rank_source_lifetime_slots(...)` → `_rank_shape_aware_slots(...)`. No new public wrapper is needed (the test imports the existing `rank_structure_variants`). Then grep for stale references: `grep -rn "_source_lifetime_in_axis_sort_key\|_rank_source_lifetime_slots" src tests`. If anything outside `structure.py` imports them, keep thin aliases (`_rank_source_lifetime_slots = _rank_shape_aware_slots`, `_source_lifetime_in_axis_sort_key = _shape_aware_in_axis_sort_key`); otherwise delete the old names.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move_ranking.py tests/search/test_structure.py -v`
Expected: PASS (and no regression in existing structure tests).

- [ ] **Step 5: Commit**

```bash
git add -A tools/melee-agent/src/search/structure.py tools/melee-agent/tests/search/test_statement_move_ranking.py
git commit -m "feat(search): extend shape-aware ranking to statement-order axis"
```

---

## Task 9: D15C safety + yield validation

**Files:** Test `tools/melee-agent/tests/search/test_statement_move_d15c.py`; no new src.

- [ ] **Step 1: Write the D15C safety test**

```python
# tests/search/test_statement_move_d15c.py
from pathlib import Path
import pytest
from src.search.statement_move import (
    toplevel_siblings, local_names, escaped_locals, extract_movable_units,
    legal_destinations, select_positions)

REPO = Path(__file__).resolve().parents[3]
MNEVENT = REPO / "src/melee/mn/mnevent.c"

@pytest.mark.skipif(not MNEVENT.exists(), reason="mnevent.c absent")
def test_d15c_pos_cluster_cannot_cross_calls():
    src = MNEVENT.read_text()
    sibs = toplevel_siblings(src, "mnEvent_8024D15C")
    if sibs is None:
        pytest.skip("tree-sitter unavailable")
    locs = local_names(src, "mnEvent_8024D15C")
    escaped = escaped_locals(src, "mnEvent_8024D15C")
    assert "translate" in escaped  # &translate is taken
    units = extract_movable_units(sibs, locs)
    pos_units = [u for u in units if u.write_base == "pos"]
    # pos cluster reads escaped translate; every legal destination must stay
    # within the call-free region (it must NOT reach the text creation slots,
    # which are separated from pos by the row->gobjs / is_unlocked opaque blocks)
    for u in pos_units:
        legal = legal_destinations(sibs, u, escaped, locs)
        # the is_unlocked / row->gobjs blocks are opaque siblings between pos and text uses;
        # assert no legal slot lies beyond the first opaque sibling after the unit
        first_opaque_after = next(
            (i for i in range(u.index_range[1] + 1, len(sibs)) if sibs[i].kind == "opaque"),
            len(sibs))
        assert all(d <= first_opaque_after for d in legal)
```

- [ ] **Step 2: Run it**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move_d15c.py -v`
Expected: PASS — confirms the safety invariant (no unsafe pos move past the call blocks). If it fails, the barrier logic is too permissive; fix Task 4 before proceeding.

- [ ] **Step 3: Full suite + real CLI run on D15C**

Run: `cd tools/melee-agent && python -m pytest tests/search/test_statement_move.py tests/search/test_statement_move_ranking.py tests/search/test_statement_move_d15c.py tests/search/test_structure.py -q`
Run: `cd /Users/mike/code/melee/.claude/worktrees/goofy-burnell-a2a060/tools/melee-agent && python -m src.cli debug search structure -f mnEvent_8024D15C --axis statement-order --max-candidates 12`
Expected: all tests pass; the CLI runs, emits hoist-sink candidates that all compile (every `compile_status == "ok"` in the output), reports a best score. **Record** whether any candidate improves the structure score over baseline (the empirical "is order the lever?" result — low expected per spec).

- [ ] **Step 4: Commit + record outcome**

```bash
git add -A tools/melee-agent/tests/search/
git commit -m "test(search): D15C statement-move safety + yield validation"
```

- [ ] **Step 5: Final Codex review** of the whole implementation (range from this plan's first commit to HEAD), focusing on the safety model (no behavior-changing moves generated), the byte-line `apply_move` correctness, and the ranking change. Address any Critical/Important findings before declaring done.

---

## Self-Review notes (against the spec)

- **Spec coverage:** compound-sibling model = Task 1 (top-level v1; nested deferred per spec); classification + escaped = Task 2; aggregate-field clustering + singletons = Task 3; legal-destinations + opaque/escaped-call barrier (Codex A: opaque = unconditional) = Task 4; targeted/exhaustive seam = Task 5; byte-line apply_move + downward adjust + identity window (Codex C/D) = Task 6; operator + emit-first integration = Task 7; shape-aware ranking + line_delta test (Codex E) = Task 8; D15C safety + yield = Task 9.
- **Codex A–E folded in:** A (opaque unconditional barrier — Task 4 `crosses_ok` returns False for any hard/opaque sibling); B (`escaped_locals` regex `&\s*\(?\s*ident` covers `&x`/`& x`/`&(x)` — Task 2; non-escaped locals can't alias since address never taken, enforced by RHS `_UNSAFE_RHS_RE` rejecting `&*->[`); C (identity window `[lo, hi+1]` — Task 6 `apply_move` + Task 4 exclusion); D (UTF-8 bytes, line bounds, downward dest adjust, trailing-newline ensure — Task 6); E (RHS rejects `++ -- = , ?` and calls — Task 2; declarations opaque — Task 1; shape rank test with line_delta — Task 8).
- **Type consistency:** `SiblingStmt(text,byte_range,line_range,kind,node_type)`, `MovableInfo(write_base,is_field,reads,writes)`, `MoveUnit(write_base,is_cluster,reads,writes,index_range,byte_range)` used consistently across tasks; the operator returns plain dicts adapted by `add_variant(*, operator,start,end,candidate_source,metadata)`.
- **Known plan-time uncertainty to resolve in Task 1/4:** the exact tree-sitter node type for a simple assignment statement (`expression_statement` wrapping `assignment_expression`) — Task 1 step 4 says to print node types and adjust. The D15C test's "first opaque after" assertion encodes the safety invariant precisely.
