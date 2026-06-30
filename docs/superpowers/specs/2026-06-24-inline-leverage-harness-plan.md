# Inline-Leverage Measurement Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Companion spec (read first, do not duplicate):** `docs/superpowers/specs/2026-06-24-inline-leverage-harness-design.md`

**Goal:** Build `melee-agent debug measure inline-leverage`, a harness that de-inlines real `(static) inline` calls in already-matched functions, recompiles, and measures whether the match regresses structurally — quantifying how often an inline is a true codegen lever vs readability, bucketed by inline shape.

**Architecture:** A new `src/inline_leverage/` package: a tree-sitter detector (finds inline defs in the TU + included headers, resolves bodies, finds call sites, shape-tags), a de-inliner (two forms: `value_expr` and `statement_splice`), a scorer (compile + checkdiff on both the fuzzy and structural axes), a SQLite ledger table, and an orchestrator. A thin Typer command wires it into the existing `debug` CLI. Scoring reuses the existing checkdiff path; classification requires a *structural* regression for a strict "lever".

**Tech Stack:** Python 3.11, Typer (CLI), tree-sitter + tree-sitter-c (via existing `src/mwcc_debug/ast_walker.py`), SQLite (via existing `src/source_transform_mining.py` ledger), `tools/checkdiff.py` (scoring), pytest.

## Global Constraints

- **Run location:** implement and run in an **isolated git worktree off `master`**, never the shared main checkout (it carries other sessions' uncommitted WIP and racing builds corrupt results). Derive all paths from the worktree root.
- **Corpus:** functions with `fuzzy_match_percent == 100`; **recompute baseline fresh** in the run — never trust cached `report.json` values.
- **Scoring axes:** record `delta_fuzzy` (Δ `fuzzy_match_percent`) **and** `delta_struct` (Δ `normalized_diff_lines`). A strict `lever` requires `delta_struct > 0`. A fuzzy-only regression is `fuzzy_only` (a backend coloring tie-break), never counted as an inline-shape lever.
- **Never use `--no-build`** for a variant checkdiff (yields `match_percent=unknown`).
- **Default scope is `--module`**; repo-wide requires `--all` and is a cached batch.
- **`deinline_failed`** (non-compiling) is excluded from rate denominators; **`unsupported`** is counted and reported **per shape bucket**.
- **CLI package root:** `tools/melee-agent` (all `src/...` / `tests/...` paths below are relative to it). Run pytest from there.
- Estimand is an explicit **proxy**: `P(lever | inline present in a matched fn)`, not the blocked-function quantity.

---

## File Structure

- `src/inline_leverage/__init__.py` — package marker, exports public types.
- `src/inline_leverage/types.py` — dataclasses + the `Verdict` literal shared across modules.
- `src/inline_leverage/store.py` — `inline_leverage` SQLite table + `InlineLeverageStore`.
- `src/inline_leverage/detect.py` — tree-sitter detection: inline defs (TU + headers), call sites, shape tagging.
- `src/inline_leverage/deinline.py` — the substitution engine (`value_expr` + `statement_splice`).
- `src/inline_leverage/score.py` — checkdiff JSON parse (fuzzy + structural) and `classify()`.
- `src/inline_leverage/run.py` — orchestrator: corpus select, per-(fn,inline) pipeline, cache, aggregate, report.
- `src/cli/debug/__init__.py` — **modify**: add `measure_app` + the `inline-leverage` command.
- `tests/inline_leverage/` — unit tests + `fixtures/` (synthetic neutral & lever TUs).

Each module has one responsibility; `types.py` holds the shared contracts so tasks can be implemented out of order.

---

### Task 1: Shared types

**Files:**
- Create: `src/inline_leverage/types.py`
- Create: `src/inline_leverage/__init__.py`
- Test: `tests/inline_leverage/test_types.py`

**Interfaces:**
- Produces: `InlineDef`, `CallSite`, `DeinlineResult`, `ScoreResult`, `LeverageRecord`, and `Verdict` — consumed by every later task.

- [ ] **Step 1: Write the failing test**

```python
# tests/inline_leverage/test_types.py
from src.inline_leverage.types import (
    InlineDef, CallSite, DeinlineResult, ScoreResult, LeverageRecord, VERDICTS,
)

def test_inline_def_shape_fields():
    d = InlineDef(
        name="GetWarn", def_location="header", def_file="mn/mndatadel.h:160",
        is_static=True, return_class="pointer", body_kind="single_return_expr",
        params=[("HSD_JObj*", "arg0")], body_text="return f(arg0);", n_statements=1,
    )
    assert d.return_class == "pointer"
    assert d.params[0] == ("HSD_JObj*", "arg0")

def test_deinline_result_unsupported_carries_reason():
    r = DeinlineResult(ok=False, expansion_form=None, new_source=None,
                       unsupported_reason="multiple returns")
    assert not r.ok and r.unsupported_reason == "multiple returns"

def test_verdicts_closed_set():
    assert VERDICTS == ("lever", "fuzzy_only", "neutral", "unsupported", "deinline_failed")

def test_leverage_record_roundtrips_to_dict():
    rec = LeverageRecord(
        run_id="r1", function="fn_8024ECCC", unit="mn/mndatadel.c",
        inline_name="GetWarn", def_location="header", def_file="mn/mndatadel.h:160",
        is_static=True, n_call_sites=1, baseline_pct=100.0, deinlined_pct=99.0,
        delta_fuzzy=1.0, baseline_ndl=0, deinlined_ndl=2, delta_struct=2,
        verdict="lever", expansion_form="value_expr", shape_return="pointer",
        shape_body="single_return_expr", shape_args=["plain_id"], n_statements=1,
        error=None,
    )
    d = rec.to_row()
    assert d["verdict"] == "lever" and d["delta_struct"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.inline_leverage'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/inline_leverage/__init__.py
"""Inline-leverage measurement harness."""
```

```python
# src/inline_leverage/types.py
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

Verdict = Literal["lever", "fuzzy_only", "neutral", "unsupported", "deinline_failed"]
VERDICTS = ("lever", "fuzzy_only", "neutral", "unsupported", "deinline_failed")

ReturnClass = Literal["void", "scalar", "pointer", "struct"]
BodyKind = Literal["single_return_expr", "multi_statement"]
ExpansionForm = Literal["value_expr", "statement_splice"]

@dataclass
class InlineDef:
    name: str
    def_location: Literal["tu", "header"]
    def_file: str                      # "path:line"
    is_static: bool
    return_class: ReturnClass
    body_kind: BodyKind
    params: list[tuple[str, str]]      # (type, name)
    body_text: str                     # inner body, no braces
    n_statements: int

@dataclass
class CallSite:
    function: str
    byte_start: int
    byte_end: int
    args: list[str]                    # source text of each argument

@dataclass
class DeinlineResult:
    ok: bool
    expansion_form: Optional[ExpansionForm]
    new_source: Optional[str]
    unsupported_reason: Optional[str] = None

@dataclass
class ScoreResult:
    compiled: bool
    baseline_pct: Optional[float]
    deinlined_pct: Optional[float]
    delta_fuzzy: Optional[float]
    baseline_ndl: Optional[int]
    deinlined_ndl: Optional[int]
    delta_struct: Optional[int]

@dataclass
class LeverageRecord:
    run_id: str
    function: str
    unit: str
    inline_name: str
    def_location: str
    def_file: str
    is_static: bool
    n_call_sites: int
    baseline_pct: Optional[float]
    deinlined_pct: Optional[float]
    delta_fuzzy: Optional[float]
    baseline_ndl: Optional[int]
    deinlined_ndl: Optional[int]
    delta_struct: Optional[int]
    verdict: Verdict
    expansion_form: Optional[str]
    shape_return: str
    shape_body: str
    shape_args: list[str]
    n_statements: int
    error: Optional[str]

    def to_row(self) -> dict:
        import json
        d = asdict(self)
        d["is_static"] = 1 if self.is_static else 0
        d["shape_args"] = json.dumps(self.shape_args)
        return d
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_types.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inline_leverage/__init__.py src/inline_leverage/types.py tests/inline_leverage/test_types.py
git commit -m "feat(inline-leverage): shared types"
```

---

### Task 2: Ledger table + store

**Files:**
- Create: `src/inline_leverage/store.py`
- Test: `tests/inline_leverage/test_store.py`

**Interfaces:**
- Consumes: `LeverageRecord` (Task 1).
- Produces: `InlineLeverageStore(db_path)` with `.ensure_schema()`, `.insert(rec)`, `.seen(tu_hash, function, inline_name) -> bool`, `.mark_seen(tu_hash, function, inline_name)`, `.records(run_id) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/inline_leverage/test_store.py
from src.inline_leverage.store import InlineLeverageStore
from src.inline_leverage.types import LeverageRecord

def _rec(**kw):
    base = dict(
        run_id="r1", function="fnA", unit="u.c", inline_name="inl",
        def_location="tu", def_file="u.c:10", is_static=True, n_call_sites=1,
        baseline_pct=100.0, deinlined_pct=99.0, delta_fuzzy=1.0,
        baseline_ndl=0, deinlined_ndl=3, delta_struct=3, verdict="lever",
        expansion_form="value_expr", shape_return="scalar",
        shape_body="single_return_expr", shape_args=["plain_id"],
        n_statements=1, error=None,
    )
    base.update(kw)
    return LeverageRecord(**base)

def test_insert_and_read_back(tmp_path):
    s = InlineLeverageStore(tmp_path / "led.db"); s.ensure_schema()
    s.insert(_rec())
    rows = s.records("r1")
    assert len(rows) == 1 and rows[0]["verdict"] == "lever"
    assert rows[0]["shape_args"] == '["plain_id"]'  # stored as JSON text

def test_seen_cache(tmp_path):
    s = InlineLeverageStore(tmp_path / "led.db"); s.ensure_schema()
    assert not s.seen("hashA", "fnA", "inl")
    s.mark_seen("hashA", "fnA", "inl")
    assert s.seen("hashA", "fnA", "inl")
    assert not s.seen("hashB", "fnA", "inl")  # different TU content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.inline_leverage.store'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/inline_leverage/store.py
from __future__ import annotations
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from .types import LeverageRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS inline_leverage (
  id INTEGER PRIMARY KEY,
  run_id TEXT, function TEXT, unit TEXT, inline_name TEXT,
  def_location TEXT, def_file TEXT, is_static INTEGER, n_call_sites INTEGER,
  baseline_pct REAL, deinlined_pct REAL, delta_fuzzy REAL,
  baseline_ndl INTEGER, deinlined_ndl INTEGER, delta_struct INTEGER,
  verdict TEXT, expansion_form TEXT, shape_return TEXT, shape_body TEXT,
  shape_args TEXT, n_statements INTEGER, error TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS inline_leverage_seen (
  tu_hash TEXT, function TEXT, inline_name TEXT,
  PRIMARY KEY (tu_hash, function, inline_name)
);
"""

class InlineLeverageStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row

    def ensure_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def insert(self, rec: LeverageRecord) -> None:
        row = rec.to_row()
        row["created_at"] = datetime.now(timezone.utc).isoformat()
        cols = ", ".join(row.keys())
        ph = ", ".join("?" for _ in row)
        self._conn.execute(f"INSERT INTO inline_leverage ({cols}) VALUES ({ph})",
                           list(row.values()))
        self._conn.commit()

    def seen(self, tu_hash: str, function: str, inline_name: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM inline_leverage_seen WHERE tu_hash=? AND function=? AND inline_name=?",
            (tu_hash, function, inline_name))
        return cur.fetchone() is not None

    def mark_seen(self, tu_hash: str, function: str, inline_name: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO inline_leverage_seen VALUES (?,?,?)",
            (tu_hash, function, inline_name))
        self._conn.commit()

    def records(self, run_id: str) -> list[dict]:
        cur = self._conn.execute("SELECT * FROM inline_leverage WHERE run_id=?", (run_id,))
        return [dict(r) for r in cur.fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_store.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inline_leverage/store.py tests/inline_leverage/test_store.py
git commit -m "feat(inline-leverage): SQLite ledger table + store with seen-cache"
```

---

### Task 3: Detector — inline defs + shape tagging (single TU)

**Files:**
- Create: `src/inline_leverage/detect.py`
- Test: `tests/inline_leverage/test_detect_defs.py`

**Interfaces:**
- Consumes: `InlineDef` (Task 1); `src/mwcc_debug/ast_walker.py` tree-sitter parse idiom.
- Produces: `parse_inline_defs(source: str, path: str) -> list[InlineDef]` — finds `inline`/`static inline` function definitions in one source string, classifying return class, body kind, params, and `unsupported` markers (control flow / multiple returns are tagged `body_kind="multi_statement"` and surfaced; the de-inliner decides support).

Notes for the implementer: follow the tree-sitter usage in `ast_walker.py` — use its parser (`from tree_sitter import Parser`; tree-sitter-c grammar), walk `function_definition` nodes, and slice `source.encode()` by node `start_byte`/`end_byte`. Classify `return_class`: a `pointer_declarator` on the function declarator ⇒ `pointer`; `primitive_type`/`sized_type_specifier` whose text is in the scalar set ⇒ `scalar`; `struct`/typedef'd struct ⇒ `struct`; `void` ⇒ `void`. `body_kind`: a single `return_statement` ⇒ `single_return_expr`, else `multi_statement`.

- [ ] **Step 1: Write the failing test**

```python
# tests/inline_leverage/test_detect_defs.py
from src.inline_leverage.detect import parse_inline_defs

SRC = """
static inline struct WarnCmnData* GetWarn(void) {
    return g_root->user_data;
}
static inline f32 framef(HSD_JObj* arg0) {
    return mn_frame(arg0);
}
static inline void setpos(Foo* p, s32 x) {
    p->a = x;
    p->b = x + 1;
}
void regular(void) { return; }
"""

def test_finds_three_inlines_not_regular():
    defs = {d.name: d for d in parse_inline_defs(SRC, "u.c")}
    assert set(defs) == {"GetWarn", "framef", "setpos"}

def test_return_classes():
    defs = {d.name: d for d in parse_inline_defs(SRC, "u.c")}
    assert defs["GetWarn"].return_class == "pointer"
    assert defs["framef"].return_class == "scalar"
    assert defs["setpos"].return_class == "void"

def test_body_kind_and_params():
    defs = {d.name: d for d in parse_inline_defs(SRC, "u.c")}
    assert defs["framef"].body_kind == "single_return_expr"
    assert defs["framef"].params == [("HSD_JObj*", "arg0")]
    assert defs["setpos"].body_kind == "multi_statement"
    assert defs["setpos"].n_statements == 2
    assert defs["setpos"].params == [("Foo*", "p"), ("s32", "x")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_detect_defs.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_inline_defs'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/inline_leverage/detect.py
from __future__ import annotations
from .types import InlineDef
from tree_sitter import Parser
import tree_sitter_c

_LANG = tree_sitter_c.language()
_SCALARS = {"bool","BOOL","s8","s16","s32","s64","u8","u16","u32","u64",
            "int","short","long","f32","f64","float","double","char","enum_t"}

def _parser() -> Parser:
    from tree_sitter import Language
    p = Parser()
    p.language = Language(_LANG)
    return p

def _txt(src: bytes, node) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")

def _find(node, type_name):
    for c in node.children:
        if c.type == type_name:
            return c
    return None

def _declarator_chain(decl):
    """Return (innermost function_declarator, is_pointer)."""
    is_ptr = False
    cur = decl
    while cur is not None and cur.type in ("pointer_declarator", "function_declarator"):
        if cur.type == "pointer_declarator":
            is_ptr = True
            cur = _find(cur, "function_declarator") or _find(cur, "pointer_declarator")
        else:
            return cur, is_ptr
    return None, is_ptr

def _params(src, fdecl):
    out = []
    plist = _find(fdecl, "parameter_list")
    if plist is None:
        return out
    for pd in plist.children:
        if pd.type != "parameter_declaration":
            continue
        text = _txt(src, pd).strip()
        if text == "void" or not text:
            continue
        # split trailing identifier as the name; rest (incl '*') is the type
        decl = pd.children[-1]
        name_node = decl
        while name_node.type != "identifier" and name_node.child_count:
            name_node = name_node.children[-1]
        name = _txt(src, name_node)
        typ = text[: text.rfind(name)].strip() if name in text else text
        typ = typ.replace(" *", "*")
        out.append((typ, name))
    return out

def parse_inline_defs(source: str, path: str) -> list[InlineDef]:
    src = source.encode("utf-8")
    tree = _parser().parse(src)
    out: list[InlineDef] = []
    for node in tree.root_node.children:
        if node.type != "function_definition":
            continue
        spec_text = " ".join(
            _txt(src, c) for c in node.children
            if c.type in ("storage_class_specifier", "type_qualifier"))
        if "inline" not in _txt(src, node).split("{")[0]:
            continue
        is_static = "static" in spec_text or "static" in _txt(src, node).split("inline")[0]
        decl = _find(node, "function_declarator") or _find(node, "pointer_declarator")
        fdecl, is_ptr = _declarator_chain(decl)
        if fdecl is None:
            continue
        name_node = _find(fdecl, "identifier")
        if name_node is None:
            continue
        name = _txt(src, name_node)
        # return class
        type_node = _find(node, "primitive_type") or _find(node, "type_identifier") \
            or _find(node, "sized_type_specifier") or _find(node, "struct_specifier")
        ret_text = _txt(src, type_node) if type_node else ""
        if is_ptr:
            return_class = "pointer"
        elif ret_text == "void":
            return_class = "void"
        elif type_node is not None and type_node.type == "struct_specifier":
            return_class = "struct"
        elif ret_text in _SCALARS:
            return_class = "scalar"
        else:
            return_class = "scalar"  # typedef scalar fallback
        body = _find(node, "compound_statement")
        stmts = [c for c in body.children if c.is_named] if body else []
        n_stmts = len(stmts)
        single_return = (n_stmts == 1 and stmts[0].type == "return_statement")
        body_inner = _txt(src, body)[1:-1].strip() if body else ""
        line = node.start_point[0] + 1
        out.append(InlineDef(
            name=name,
            def_location="tu",      # caller overrides for headers (Task 4)
            def_file=f"{path}:{line}",
            is_static=is_static,
            return_class=return_class,
            body_kind="single_return_expr" if single_return else "multi_statement",
            params=_params(src, fdecl),
            body_text=body_inner,
            n_statements=n_stmts,
        ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_detect_defs.py -v`
Expected: PASS (3 passed). If a param-type split assertion fails, fix `_params` until `[("HSD_JObj*","arg0")]` and `[("Foo*","p"),("s32","x")]` match exactly.

- [ ] **Step 5: Commit**

```bash
git add src/inline_leverage/detect.py tests/inline_leverage/test_detect_defs.py
git commit -m "feat(inline-leverage): tree-sitter inline-def detection + shape tagging"
```

---

### Task 4: Detector — header resolution + call sites in a function

**Files:**
- Modify: `src/inline_leverage/detect.py`
- Test: `tests/inline_leverage/test_detect_calls.py`

**Interfaces:**
- Consumes: `parse_inline_defs` (Task 3), `CallSite` (Task 1).
- Produces:
  - `resolve_inline_defs(tu_path: str, include_dirs: list[str]) -> dict[str, InlineDef]` — inline defs visible to a TU: those in the TU (`def_location="tu"`) plus those in transitively-`#include`d project headers (`def_location="header"`). Header names from `#include "..."` resolved against `include_dirs`; system `<...>` includes ignored. One level of header→header includes is followed (sufficient for this codebase; deeper nesting logged and skipped).
  - `find_call_sites(source: str, function: str, inline_name: str) -> list[CallSite]` — call expressions to `inline_name` inside `function`'s body, with argument source text split at top level.

- [ ] **Step 1: Write the failing test**

```python
# tests/inline_leverage/test_detect_calls.py
from src.inline_leverage.detect import resolve_inline_defs, find_call_sites

def test_resolves_header_inline(tmp_path):
    (tmp_path / "h.h").write_text("static inline int acc(int x){ return x + 1; }\n")
    (tmp_path / "u.c").write_text('#include "h.h"\nint f(void){ return acc(3); }\n')
    defs = resolve_inline_defs(str(tmp_path / "u.c"), [str(tmp_path)])
    assert "acc" in defs and defs["acc"].def_location == "header"

def test_find_call_sites_within_function():
    src = ("int f(void){ int a = acc(x); return acc(y); }\n"
           "int g(void){ return acc(z); }\n")
    sites = find_call_sites(src, "f", "acc")
    assert len(sites) == 2
    assert [s.args for s in sites] == [["x"], ["y"]]
    # g's call must NOT be included
    assert all(s.function == "f" for s in sites)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_detect_calls.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_inline_defs'`

- [ ] **Step 3: Write minimal implementation** (append to `detect.py`)

```python
import os, re

_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)

def _resolve_include(name: str, include_dirs: list[str]) -> str | None:
    for d in include_dirs:
        cand = os.path.join(d, name)
        if os.path.isfile(cand):
            return cand
    return None

def resolve_inline_defs(tu_path: str, include_dirs: list[str]) -> dict[str, InlineDef]:
    out: dict[str, InlineDef] = {}
    tu_src = open(tu_path, encoding="utf-8", errors="replace").read()
    for d in parse_inline_defs(tu_src, os.path.relpath(tu_path)):
        out[d.name] = d
    seen_headers: set[str] = set()
    frontier = list(_INCLUDE_RE.findall(tu_src))
    depth = 0
    while frontier and depth < 2:
        nxt: list[str] = []
        for inc in frontier:
            path = _resolve_include(inc, include_dirs)
            if not path or path in seen_headers:
                continue
            seen_headers.add(path)
            htext = open(path, encoding="utf-8", errors="replace").read()
            for d in parse_inline_defs(htext, os.path.relpath(path)):
                d.def_location = "header"
                out.setdefault(d.name, d)
            nxt.extend(_INCLUDE_RE.findall(htext))
        frontier = nxt
        depth += 1
    return out

def _enclosing_function_body(tree_root, src, function):
    for node in tree_root.children:
        if node.type != "function_definition":
            continue
        fdecl = _find(node, "function_declarator") or _find(node, "pointer_declarator")
        fd, _ = _declarator_chain(fdecl) if fdecl else (None, False)
        nm = _find(fd, "identifier") if fd else None
        if nm is not None and _txt(src, nm) == function:
            return _find(node, "compound_statement")
    return None

def _split_args(src, arglist_node):
    out = []
    for c in arglist_node.children:
        if c.is_named:
            out.append(_txt(src, c).strip())
    return out

def find_call_sites(source: str, function: str, inline_name: str):
    from .types import CallSite
    src = source.encode("utf-8")
    tree = _parser().parse(src)
    body = _enclosing_function_body(tree.root_node, src, function)
    sites = []
    if body is None:
        return sites
    def walk(n):
        if n.type == "call_expression":
            fn = n.children[0]
            if fn.type == "identifier" and _txt(src, fn) == inline_name:
                al = _find(n, "argument_list")
                sites.append(CallSite(function=function,
                                      byte_start=n.start_byte, byte_end=n.end_byte,
                                      args=_split_args(src, al) if al else []))
        for c in n.children:
            walk(c)
    walk(body)
    return sites
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_detect_calls.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inline_leverage/detect.py tests/inline_leverage/test_detect_calls.py
git commit -m "feat(inline-leverage): header-aware def resolution + per-function call sites"
```

---

### Task 5: De-inliner — `value_expr` form

**Files:**
- Create: `src/inline_leverage/deinline.py`
- Test: `tests/inline_leverage/test_deinline_value.py`

**Interfaces:**
- Consumes: `InlineDef`, `CallSite`, `DeinlineResult` (Task 1); `find_call_sites` (Task 4).
- Produces: `deinline(source, function, inline_def, call_sites) -> DeinlineResult`. For `single_return_expr` non-`void` inlines it produces the `value_expr` expansion; other shapes return `ok=False` with a reason (handled fully in Task 6). Multiply-used side-effecting/non-trivial args ⇒ `unsupported`.

- [ ] **Step 1: Write the failing test**

```python
# tests/inline_leverage/test_deinline_value.py
from src.inline_leverage.deinline import deinline
from src.inline_leverage.detect import parse_inline_defs, find_call_sites

def _one(src, defsrc, fn, name):
    d = {x.name: x for x in parse_inline_defs(defsrc, "u.c")}[name]
    sites = find_call_sites(src, fn, name)
    return deinline(src, fn, d, sites)

def test_value_expr_no_params():
    defsrc = "static inline int gw(void){ return g->u; }\n"
    src = "int f(void){ int a; a = gw(); return a; }\n"
    r = _one(src, defsrc, "f", "gw")
    assert r.ok and r.expansion_form == "value_expr"
    assert "a = (g->u);" in r.new_source
    assert "gw()" not in r.new_source

def test_value_expr_param_substitution():
    defsrc = "static inline int fr(HSD_JObj* a0){ return frame(a0); }\n"
    src = "int f(void){ int t = fr(sp18); return t; }\n"
    r = _one(src, defsrc, "f", "fr")
    assert r.ok and "fr(sp18)" not in r.new_source
    assert "(frame(sp18))" in r.new_source

def test_multi_use_side_effecting_arg_unsupported():
    defsrc = "static inline int sq(int a0){ return a0 * a0; }\n"  # a0 used twice
    src = "int f(void){ return sq(g()); }\n"                       # arg is a call
    r = _one(src, defsrc, "f", "sq")
    assert not r.ok and "multiply-used" in (r.unsupported_reason or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_deinline_value.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.inline_leverage.deinline'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/inline_leverage/deinline.py
from __future__ import annotations
import re
from .types import DeinlineResult, InlineDef, CallSite

_IDENT = re.compile(r"[A-Za-z_]\w*")
_TRIVIAL_ARG = re.compile(r"^[A-Za-z_]\w*$|^-?\d+$|^0x[0-9A-Fa-f]+$")

def _subst_params(expr: str, params, args, body_uses) -> tuple[str, str | None]:
    """Replace each param identifier token in expr with its arg text.
    Returns (new_expr, unsupported_reason)."""
    for (_typ, pname), arg in zip(params, args):
        uses = body_uses.get(pname, 0)
        if uses > 1 and not _TRIVIAL_ARG.match(arg.strip()):
            return expr, f"multiply-used non-trivial arg for param {pname}"
    def repl(m):
        tok = m.group(0)
        for (_t, pname), arg in zip(params, args):
            if tok == pname:
                return arg
        return tok
    return _IDENT.sub(repl, expr), None

def _return_expr(body_text: str) -> str | None:
    m = re.match(r"^\s*return\s+(?P<e>.+?);\s*$", body_text.strip(), re.DOTALL)
    return m.group("e").strip() if m else None

def _body_param_uses(body_text: str, params) -> dict[str, int]:
    toks = _IDENT.findall(body_text)
    return {pname: toks.count(pname) for _t, pname in params}

def deinline(source: str, function: str, d: InlineDef,
             call_sites: list[CallSite]) -> DeinlineResult:
    if not call_sites:
        return DeinlineResult(False, None, None, "no call sites")
    if d.body_kind == "single_return_expr" and d.return_class != "void":
        expr = _return_expr(d.body_text)
        if expr is None:
            return DeinlineResult(False, None, None, "could not parse return expr")
        uses = _body_param_uses(d.body_text, d.params)
        # apply right-to-left so byte spans stay valid
        new = source
        for site in sorted(call_sites, key=lambda s: s.byte_start, reverse=True):
            if len(site.args) != len(d.params):
                return DeinlineResult(False, None, None, "arg/param arity mismatch")
            sub, reason = _subst_params(expr, d.params, site.args, uses)
            if reason:
                return DeinlineResult(False, None, None, reason)
            new = new[:site.byte_start] + f"({sub})" + new[site.byte_end:]
        return DeinlineResult(True, "value_expr", new, None)
    # statement_splice handled in Task 6; other shapes unsupported here
    return DeinlineResult(False, None, None, "not a value_expr shape (see Task 6)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_deinline_value.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inline_leverage/deinline.py tests/inline_leverage/test_deinline_value.py
git commit -m "feat(inline-leverage): value_expr de-inliner with arg-hygiene routing"
```

---

### Task 6: De-inliner — `statement_splice` form + unsupported routing

**Files:**
- Modify: `src/inline_leverage/deinline.py`
- Test: `tests/inline_leverage/test_deinline_stmt.py`

**Interfaces:**
- Produces: extends `deinline()` to handle `void`/`multi_statement` inlines called as statements — splice the body inside a fresh `{ }` scope with params substituted; mark `expansion_form="statement_splice"`. Inlines with control flow / multiple returns / used as a value ⇒ `ok=False, unsupported_reason=...`.

- [ ] **Step 1: Write the failing test**

```python
# tests/inline_leverage/test_deinline_stmt.py
from src.inline_leverage.deinline import deinline
from src.inline_leverage.detect import parse_inline_defs, find_call_sites

def _one(src, defsrc, fn, name):
    d = {x.name: x for x in parse_inline_defs(defsrc, "u.c")}[name]
    return deinline(src, fn, d, find_call_sites(src, fn, name))

def test_statement_splice_void():
    defsrc = "static inline void sp(Foo* p, int x){ p->a = x; p->b = x + 1; }\n"
    src = "void f(void){ sp(obj, 5); }\n"
    r = _one(src, defsrc, "f", "sp")
    assert r.ok and r.expansion_form == "statement_splice"
    assert "sp(obj, 5);" not in r.new_source
    assert "{ obj->a = 5; obj->b = 5 + 1; }" in r.new_source.replace("\n", " ")

def test_control_flow_unsupported():
    defsrc = "static inline void c(int x){ if (x) g(); }\n"
    src = "void f(void){ c(1); }\n"
    r = _one(src, defsrc, "c", "c") if False else _one(src, defsrc, "f", "c")
    assert not r.ok and "control flow" in (r.unsupported_reason or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_deinline_stmt.py -v`
Expected: FAIL — assertion error (current `deinline` returns "not a value_expr shape")

- [ ] **Step 3: Write minimal implementation** (edit `deinline.py`)

Add control-flow detection and the splice branch. Replace the final `return DeinlineResult(False, None, None, "not a value_expr shape (see Task 6)")` with:

```python
    # statement_splice: void or multi-statement body called as a statement
    if re.search(r"\b(if|for|while|do|switch|goto|case|default)\b", d.body_text):
        return DeinlineResult(False, None, None, "body has control flow")
    if d.body_text.count("return") > 0 and d.return_class != "void":
        return DeinlineResult(False, None, None, "value used in non-void multi-stmt")
    uses = _body_param_uses(d.body_text, d.params)
    new = source
    for site in sorted(call_sites, key=lambda s: s.byte_start, reverse=True):
        if len(site.args) != len(d.params):
            return DeinlineResult(False, None, None, "arg/param arity mismatch")
        body, reason = _subst_params(d.body_text, d.params, site.args, uses)
        if reason:
            return DeinlineResult(False, None, None, reason)
        # the call appears as `name(args);` — replace through the trailing semicolon
        end = site.byte_end
        tail = source[end:end+1]
        consume = end + 1 if tail == ";" else end
        new = new[:site.byte_start] + "{ " + body.strip() + " }" + new[consume:]
    return DeinlineResult(True, "statement_splice", new, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_deinline_stmt.py tests/inline_leverage/test_deinline_value.py -v`
Expected: PASS (5 passed total — value_expr tests still green)

- [ ] **Step 5: Commit**

```bash
git add src/inline_leverage/deinline.py tests/inline_leverage/test_deinline_stmt.py
git commit -m "feat(inline-leverage): statement_splice de-inliner + unsupported routing"
```

---

### Task 7: Scorer — checkdiff parse (fuzzy + structural) and classify

**Files:**
- Create: `src/inline_leverage/score.py`
- Test: `tests/inline_leverage/test_score.py`

**Interfaces:**
- Consumes: `ScoreResult`, `Verdict` (Task 1).
- Produces:
  - `parse_checkdiff(text: str) -> tuple[float|None, int|None]` — returns `(fuzzy_match_percent, normalized_diff_lines)` from a checkdiff `--json` blob (the existing `candidate_verify.parse_checkdiff_json` ignores `normalized_diff_lines`, so we parse our own).
  - `classify(score: ScoreResult, epsilon: float) -> Verdict` — strict lever requires `delta_struct > 0`; fuzzy-only requires `delta_fuzzy > epsilon and delta_struct == 0`; else neutral. `compiled=False ⇒ deinline_failed`.

- [ ] **Step 1: Write the failing test**

```python
# tests/inline_leverage/test_score.py
from src.inline_leverage.score import parse_checkdiff, classify
from src.inline_leverage.types import ScoreResult

def test_parse_pulls_both_axes():
    blob = '{"fuzzy_match_percent": 99.6, "normalized_diff_lines": 0, "x": 1}'
    assert parse_checkdiff(blob) == (99.6, 0)

def _s(**kw):
    base = dict(compiled=True, baseline_pct=100.0, deinlined_pct=100.0,
                delta_fuzzy=0.0, baseline_ndl=0, deinlined_ndl=0, delta_struct=0)
    base.update(kw); return ScoreResult(**base)

def test_strict_lever_requires_structural_change():
    assert classify(_s(delta_fuzzy=2.0, deinlined_ndl=4, delta_struct=4), 0.05) == "lever"

def test_fuzzy_only_is_not_a_lever():
    assert classify(_s(delta_fuzzy=2.0, delta_struct=0), 0.05) == "fuzzy_only"

def test_neutral():
    assert classify(_s(delta_fuzzy=0.0, delta_struct=0), 0.05) == "neutral"

def test_failed_compile():
    assert classify(_s(compiled=False, baseline_pct=None, delta_fuzzy=None,
                       delta_struct=None), 0.05) == "deinline_failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_score.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.inline_leverage.score'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/inline_leverage/score.py
from __future__ import annotations
import json
from .types import ScoreResult, Verdict

def parse_checkdiff(text: str) -> tuple[float | None, int | None]:
    payload = json.loads(text)
    fuzzy = payload.get("fuzzy_match_percent")
    if fuzzy is None:
        fuzzy = payload.get("match_pct")
    ndl = payload.get("normalized_diff_lines")
    return fuzzy, ndl

def classify(score: ScoreResult, epsilon: float) -> Verdict:
    if not score.compiled:
        return "deinline_failed"
    if score.delta_struct is not None and score.delta_struct > 0:
        return "lever"
    if score.delta_fuzzy is not None and score.delta_fuzzy > epsilon:
        return "fuzzy_only"
    return "neutral"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_score.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inline_leverage/score.py tests/inline_leverage/test_score.py
git commit -m "feat(inline-leverage): dual-axis checkdiff parse + structural-first classify"
```

---

### Task 8: Orchestrator + report

**Files:**
- Create: `src/inline_leverage/run.py`
- Test: `tests/inline_leverage/test_run.py`

**Interfaces:**
- Consumes: all prior modules. Compilation/checkdiff are injected as callables so the orchestrator is unit-testable without a build.
- Produces:
  - `measure_function(source, function, unit, defs, *, compile_checkdiff, baseline, epsilon, run_id) -> list[LeverageRecord]` — for each inline `function` calls, de-inline, score via the injected `compile_checkdiff(new_source) -> (compiled, fuzzy, ndl)`, classify, build a `LeverageRecord`. `unsupported`/`deinline_failed` produce records too (with the reason in `error`).
  - `aggregate(records) -> dict` — headline counts + per-shape `(shape_return, shape_body, expansion_form)` buckets with `lever`/`fuzzy_only`/`neutral`/`unsupported`/`deinline_failed` tallies and the strict & permissive rates.

- [ ] **Step 1: Write the failing test**

```python
# tests/inline_leverage/test_run.py
from src.inline_leverage.run import measure_function, aggregate
from src.inline_leverage.detect import parse_inline_defs

DEFS = parse_inline_defs(
    "static inline int neu(void){ return g->u; }\n"
    "static inline void lev(Foo* p,int x){ p->a=x; p->b=x; }\n", "u.c")
DEFMAP = {d.name: d for d in DEFS}

SRC = ("int caller(void){ int a = neu(); lev(o, 2); return a; }\n")

def test_measure_records_lever_and_neutral():
    def fake_cc(new_source):
        # neutral expansion keeps ndl 0; the splice introduces a structural diff
        if "{ o->a = 2; o->b = 2; }" in new_source.replace("\n"," "):
            return (True, 99.0, 5)     # compiled, fuzzy, ndl
        return (True, 100.0, 0)
    recs = measure_function(SRC, "caller", "u.c", DEFMAP,
                            compile_checkdiff=fake_cc, baseline=(100.0, 0),
                            epsilon=0.05, run_id="r1")
    by = {r.inline_name: r for r in recs}
    assert by["neu"].verdict == "neutral"
    assert by["lev"].verdict == "lever" and by["lev"].expansion_form == "statement_splice"

def test_aggregate_rates():
    recs = measure_function(SRC, "caller", "u.c", DEFMAP,
        compile_checkdiff=lambda s: (True, 99.0, 5) if "o->a" in s.replace("\n"," ")
                                     else (True, 100.0, 0),
        baseline=(100.0, 0), epsilon=0.05, run_id="r1")
    agg = aggregate(recs)
    assert agg["counts"]["lever"] == 1
    assert agg["counts"]["neutral"] == 1
    assert 0.0 <= agg["strict_lever_rate"] <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.inline_leverage.run'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/inline_leverage/run.py
from __future__ import annotations
from collections import defaultdict
from typing import Callable
from .detect import find_call_sites
from .deinline import deinline
from .score import classify
from .types import InlineDef, LeverageRecord, ScoreResult

CompileCheckdiff = Callable[[str], tuple[bool, float | None, int | None]]

def _arg_kind(arg: str) -> str:
    a = arg.strip()
    if a.replace("-", "").isdigit() or a.startswith("0x"):
        return "literal"
    if "->" in a or "." in a or "[" in a:
        return "field_access"
    if a.startswith("&") or a.startswith("*"):
        return "pointer"
    return "plain_id"

def measure_function(source, function, unit, defs: dict[str, InlineDef], *,
                     compile_checkdiff: CompileCheckdiff,
                     baseline: tuple[float | None, int | None],
                     epsilon: float, run_id: str) -> list[LeverageRecord]:
    base_pct, base_ndl = baseline
    out: list[LeverageRecord] = []
    for name, d in defs.items():
        sites = find_call_sites(source, function, name)
        if not sites:
            continue
        r = deinline(source, function, d, sites)
        shape_args = [_arg_kind(a) for a in sites[0].args]
        common = dict(
            run_id=run_id, function=function, unit=unit, inline_name=name,
            def_location=d.def_location, def_file=d.def_file, is_static=d.is_static,
            n_call_sites=len(sites), shape_return=d.return_class,
            shape_body=d.body_kind, shape_args=shape_args, n_statements=d.n_statements)
        if not r.ok:
            out.append(LeverageRecord(
                **common, baseline_pct=base_pct, deinlined_pct=None,
                delta_fuzzy=None, baseline_ndl=base_ndl, deinlined_ndl=None,
                delta_struct=None, verdict="unsupported",
                expansion_form=None, error=r.unsupported_reason))
            continue
        compiled, pct, ndl = compile_checkdiff(r.new_source)
        score = ScoreResult(
            compiled=compiled, baseline_pct=base_pct, deinlined_pct=pct,
            delta_fuzzy=(base_pct - pct) if (compiled and pct is not None and base_pct is not None) else None,
            baseline_ndl=base_ndl, deinlined_ndl=ndl,
            delta_struct=(ndl - base_ndl) if (compiled and ndl is not None and base_ndl is not None) else None)
        verdict = classify(score, epsilon)
        out.append(LeverageRecord(
            **common, baseline_pct=score.baseline_pct, deinlined_pct=score.deinlined_pct,
            delta_fuzzy=score.delta_fuzzy, baseline_ndl=score.baseline_ndl,
            deinlined_ndl=score.deinlined_ndl, delta_struct=score.delta_struct,
            verdict=verdict, expansion_form=r.expansion_form,
            error=None if compiled else "did not compile"))
    return out

def aggregate(records: list[LeverageRecord]) -> dict:
    counts = defaultdict(int)
    buckets: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
    for r in records:
        counts[r.verdict] += 1
        key = (r.shape_return, r.shape_body, r.expansion_form)
        buckets[key][r.verdict] += 1
    scored = counts["lever"] + counts["fuzzy_only"] + counts["neutral"]
    strict = counts["lever"] / scored if scored else 0.0
    perm = (counts["lever"] + counts["fuzzy_only"]) / scored if scored else 0.0
    return {
        "counts": dict(counts),
        "strict_lever_rate": strict,
        "permissive_lever_rate": perm,
        "buckets": {f"{k[0]}/{k[1]}/{k[2]}": dict(v) for k, v in buckets.items()},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_run.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/inline_leverage/run.py tests/inline_leverage/test_run.py
git commit -m "feat(inline-leverage): orchestrator + per-shape aggregate (strict/permissive)"
```

---

### Task 9: CLI command + real build/checkdiff wiring

**Files:**
- Modify: `src/cli/debug/__init__.py`
- Create: `src/inline_leverage/build_checkdiff.py`
- Test: `tests/inline_leverage/test_cli_smoke.py`

**Interfaces:**
- Consumes: `measure_function`, `aggregate`, `resolve_inline_defs`, `InlineLeverageStore`.
- Produces:
  - `build_checkdiff.make_compile_checkdiff(melee_root, unit) -> CompileCheckdiff` — writes the variant into the TU, runs `ninja` then `python tools/checkdiff.py <fn> --json`, parses both axes via `score.parse_checkdiff`, restores the TU. Mirrors `candidate_verify`'s write-build-restore but reads `normalized_diff_lines` too.
  - `debug measure inline-leverage` Typer command (a new `measure_app` registered with `debug_app.add_typer(measure_app, name="measure")`), flags per the spec (`--module/--file/--function/--all/--epsilon/--json/--report/--run-id`), corpus from `report.json` (`fuzzy_match_percent == 100`), **baseline recomputed fresh**, `seen`-cache via the store keyed on TU content hash.

- [ ] **Step 1: Write the failing test** (smoke: command exists and reports on an injected store/fake build)

```python
# tests/inline_leverage/test_cli_smoke.py
from typer.testing import CliRunner
from src.cli.debug import debug_app

def test_inline_leverage_command_registered():
    res = CliRunner().invoke(debug_app, ["measure", "inline-leverage", "--help"])
    assert res.exit_code == 0
    assert "inline-leverage" in res.output or "lever" in res.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_cli_smoke.py -v`
Expected: FAIL — no such command `measure`

- [ ] **Step 3: Write minimal implementation**

Create `src/inline_leverage/build_checkdiff.py`:

```python
# src/inline_leverage/build_checkdiff.py
from __future__ import annotations
import subprocess
from pathlib import Path
from .score import parse_checkdiff

def make_compile_checkdiff(melee_root: str, unit: str, function: str):
    tu = Path(melee_root) / unit
    def run(new_source: str):
        original = tu.read_text(encoding="utf-8")
        try:
            tu.write_text(new_source, encoding="utf-8")
            b = subprocess.run(["ninja"], cwd=melee_root, capture_output=True, text=True)
            if b.returncode != 0:
                return (False, None, None)
            c = subprocess.run(
                ["python", "tools/checkdiff.py", function, "--json"],
                cwd=melee_root, capture_output=True, text=True)
            if c.returncode != 0 or not c.stdout.strip():
                return (False, None, None)
            fuzzy, ndl = parse_checkdiff(c.stdout)
            return (True, fuzzy, ndl)
        finally:
            tu.write_text(original, encoding="utf-8")
    return run
```

In `src/cli/debug/__init__.py`: near the other `*_app = typer.Typer(...)` declarations (~line 2283) add `measure_app = typer.Typer(no_args_is_help=True, help="Measurement harnesses.")`, and near the other `add_typer` calls (~line 2314) add `debug_app.add_typer(measure_app, name="measure")`. Then add the command:

```python
@measure_app.command("inline-leverage")
def measure_inline_leverage(
    module: str = typer.Option(None, "--module"),
    file: str = typer.Option(None, "--file"),
    function: str = typer.Option(None, "--function"),
    all_: bool = typer.Option(False, "--all"),
    epsilon: float = typer.Option(0.05, "--epsilon"),
    json_out: bool = typer.Option(False, "--json"),
    report: bool = typer.Option(True, "--report/--no-report"),
    run_id: str = typer.Option("default", "--run-id"),
):
    """De-inline real inlines in matched functions and measure structural regression."""
    import json as _json, hashlib
    from pathlib import Path
    from src.inline_leverage.detect import resolve_inline_defs, find_call_sites
    from src.inline_leverage.run import measure_function, aggregate
    from src.inline_leverage.store import InlineLeverageStore
    from src.inline_leverage.build_checkdiff import make_compile_checkdiff

    melee_root = _find_melee_root()  # existing helper in this module
    report_json = _json.loads((Path(melee_root) / "build/GALE01/report.json").read_text())
    include_dirs = [str(Path(melee_root) / d) for d in ("src", "include", "src/melee")]
    store = InlineLeverageStore(Path(melee_root) / "build/inline_leverage.db")
    store.ensure_schema()

    targets = _select_corpus(report_json, module, file, function, all_)  # (fn, unit) pairs
    all_records = []
    for fn, unit in targets:
        src_path = Path(melee_root) / unit
        source = src_path.read_text(encoding="utf-8")
        tu_hash = hashlib.sha256(source.encode()).hexdigest()
        defs = resolve_inline_defs(str(src_path), include_dirs)
        called = {n: d for n, d in defs.items() if find_call_sites(source, fn, n)}
        called = {n: d for n, d in called.items()
                  if not store.seen(tu_hash, fn, n)}
        if not called:
            continue
        baseline = _fresh_baseline(melee_root, fn)  # recompute, do NOT trust report.json
        cc = make_compile_checkdiff(melee_root, unit, fn)
        recs = measure_function(source, fn, unit, called, compile_checkdiff=cc,
                                baseline=baseline, epsilon=epsilon, run_id=run_id)
        for r in recs:
            store.insert(r); store.mark_seen(tu_hash, fn, r.inline_name)
        all_records.extend(recs)

    agg = aggregate(all_records)
    if json_out:
        typer.echo(_json.dumps(agg, indent=2))
    elif report:
        _print_report(agg)  # headline + per-bucket table per spec §11
```

Implement the small helpers in the same module: `_select_corpus` (filter `report.json` units/functions by `fuzzy_match_percent == 100`, honoring `--module/--file/--function/--all`; `--function` bypasses the 100% filter), `_fresh_baseline` (run `python tools/checkdiff.py <fn> --json` once on the unmodified tree, parse both axes), `_print_report` (render the §11 headline + per-shape table). Reuse the module's existing melee-root resolver (`_find_melee_root` or equivalent — grep the file for how other `debug` commands locate the repo root and use the same one).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_cli_smoke.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cli/debug/__init__.py src/inline_leverage/build_checkdiff.py tests/inline_leverage/test_cli_smoke.py
git commit -m "feat(inline-leverage): debug measure inline-leverage CLI + real build/checkdiff"
```

---

### Task 10: Validation fixtures + end-to-end calibration test

**Files:**
- Create: `tests/inline_leverage/fixtures/neutral_inline.c`, `tests/inline_leverage/fixtures/lever_inline.c` (hand-authored, committed)
- Create: `tests/inline_leverage/test_validation.py`

**Interfaces:**
- Consumes: the whole pipeline with a **fake** `compile_checkdiff` that models the spec's two calibration anchors, proving the harness classifies a known-neutral inline `neutral` and a known-lever inline `lever` — with no repo build dependency (Blocker #4 fix).

- [ ] **Step 1: Write the failing test**

```python
# tests/inline_leverage/test_validation.py
from pathlib import Path
from src.inline_leverage.detect import parse_inline_defs, find_call_sites
from src.inline_leverage.run import measure_function

FX = Path(__file__).parent / "fixtures"

def test_known_neutral_classifies_neutral():
    src = (FX / "neutral_inline.c").read_text()
    defs = {d.name: d for d in parse_inline_defs(src, "neutral_inline.c")}
    # neutral fixture: de-inlining the accessor must not change structure
    recs = measure_function(src, "use_neutral", "neutral_inline.c",
        {"acc": defs["acc"]},
        compile_checkdiff=lambda s: (True, 100.0, 0),  # no structural change
        baseline=(100.0, 0), epsilon=0.05, run_id="v")
    assert recs[0].verdict == "neutral"

def test_known_lever_classifies_lever():
    src = (FX / "lever_inline.c").read_text()
    defs = {d.name: d for d in parse_inline_defs(src, "lever_inline.c")}
    recs = measure_function(src, "use_lever", "lever_inline.c",
        {"setp": defs["setp"]},
        compile_checkdiff=lambda s: (True, 96.0, 6),   # structural regression
        baseline=(100.0, 0), epsilon=0.05, run_id="v")
    assert recs[0].verdict == "lever"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_validation.py -v`
Expected: FAIL — fixtures don't exist

- [ ] **Step 3: Write minimal implementation** (the fixtures)

```c
/* tests/inline_leverage/fixtures/neutral_inline.c */
struct S { int u; };
extern struct S* g;
static inline int acc(void) { return g->u; }
int use_neutral(void) { int a = acc(); return a; }
```

```c
/* tests/inline_leverage/fixtures/lever_inline.c */
struct Foo { int a; int b; };
static inline void setp(struct Foo* p, int x) { p->a = x; p->b = x + 1; }
void use_lever(struct Foo* o) { setp(o, 5); }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/test_validation.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite + commit**

Run: `cd tools/melee-agent && python -m pytest tests/inline_leverage/ -v`
Expected: PASS (all tasks' tests green)

```bash
git add tests/inline_leverage/fixtures tests/inline_leverage/test_validation.py
git commit -m "test(inline-leverage): committed neutral/lever calibration fixtures"
```

---

### Task 11: First real run + README

**Files:**
- Create: `src/inline_leverage/README.md`

**Interfaces:** none (operational task).

- [ ] **Step 1: Run on the `mn` module** (real build/checkdiff; in the isolated worktree)

Run: `cd tools/melee-agent && melee-agent debug measure inline-leverage --module mn --run-id mn-first --report`
Expected: a headline table (lever/fuzzy_only/neutral/unsupported/deinline_failed) + per-shape buckets. **If the upstream `mndatadel.c` is present**, the optional `GetWarnData` anchor (`--function fn_8024ECCC`) should classify `neutral`.

- [ ] **Step 2: Sanity-check against a known case**

Run: `cd tools/melee-agent && melee-agent debug measure inline-leverage --function fn_8024ECCC --json`
Expected (only if upstream `mndatadel.c` is in the tree): `GetWarnData` → `verdict: neutral`, `delta_struct: 0`. If the file is absent, the run reports 0 targets — documented, not an error.

- [ ] **Step 3: Write the README** (runtime budget, scope, estimand caveat — point to the spec, don't duplicate it)

```markdown
# inline-leverage

Measures how often a real (static) inline is a true *structural* codegen lever vs
readability, by de-inlining it in matched functions and re-scoring.

Full design: `docs/superpowers/specs/2026-06-24-inline-leverage-harness-design.md`.

Run in an isolated worktree (never shared main). Default `--module`; `--all` is a
long, ledger-cached batch (each variant is a full TU recompile + checkdiff, serial).
Results land in `build/inline_leverage.db`. The lever-rate is a PROXY for the
blocked-function quantity — see the spec's §2.
```

- [ ] **Step 4: Commit**

```bash
git add src/inline_leverage/README.md
git commit -m "docs(inline-leverage): README + first mn-module run notes"
```

---

## Self-Review

**1. Spec coverage:**
- Dual-axis scoring + structural-first lever → Task 7 + Global Constraints. ✓
- Header-aware detection + `def_location` → Task 4. ✓
- De-inliner `value_expr` + `statement_splice`, unsupported routing, arg hygiene → Tasks 5, 6. ✓
- Leave-def-in-place → de-inliner only rewrites call sites, never the def (Tasks 5/6). ✓
- Ledger table + content-hash `seen` cache → Tasks 2, 9. ✓
- Corpus = `fuzzy==100`, fresh baseline, `--module` default, `--all` opt-in → Task 9 + Global Constraints. ✓
- Per-shape reporting incl. `unsupported`/`deinline_failed` → Task 8 `aggregate` + Task 9 report. ✓
- Validation via committed synthetic fixtures (not absent `GetWarnData`) → Task 10; optional `GetWarnData` anchor → Task 11. ✓
- Estimand-as-proxy + isolated-worktree → Global Constraints + README (Task 11). ✓
- Transfer check (historical blocked-then-cracked): **deferred** — noted here as not covered by a task; it requires curated historical cases and is a follow-up measurement, not harness code. Flagged so it isn't silently dropped.

**2. Placeholder scan:** No "TBD/TODO". Task 9 references three module-local helpers (`_select_corpus`, `_fresh_baseline`, `_print_report`) with their behavior fully specified and the existing melee-root resolver to reuse; these are concrete enough to implement without guesswork.

**3. Type consistency:** `compile_checkdiff` returns `(compiled, fuzzy, ndl)` everywhere (Tasks 8, 9, 10). `parse_checkdiff` returns `(fuzzy, ndl)` (Tasks 7, 9). `DeinlineResult.expansion_form` values `value_expr`/`statement_splice` match across Tasks 5, 6, 8. `LeverageRecord` field names match Task 1 ↔ store columns (Task 2) ↔ `aggregate` keys (Task 8). ✓

---

## Execution notes

- **Worktree:** create a clean worktree off `master` for execution (`superpowers:using-git-worktrees`); do not implement in the shared main checkout.
- Tasks 1–8, 10 are pure-Python TDD with no build dependency (fast). Tasks 9 (real build wiring) and 11 (real run) require a built tree and are slow.
