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
    kind: str  # "simple" (non-barrier; movability refined by classify_movable) | "opaque" (barrier)
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
    body = fn.child_by_field_name("body")
    if body is not None and body.type != "compound_statement":
        return None, source_bytes
    return body, source_bytes


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
        # An opaque statement is a barrier: v1 never recurses into or moves its
        # contents, so represent multi-line constructs (if/for/while/...) by
        # their header line only. This keeps nested block bodies out of the
        # sibling model — they are NOT top-level movable units.
        if kind == "opaque":
            text = text.splitlines()[0] if text else text
        sibs.append(SiblingStmt(
            text=text,
            byte_range=(child.start_byte, child.end_byte),
            line_range=(child.start_point[0] + 1, child.end_point[0] + 1),
            kind=kind,
            node_type=child.type,
        ))
    return sibs


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
