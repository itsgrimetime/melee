"""Tree-sitter façade for the symbol bridge.

Parses C source via tree-sitter + tree-sitter-c, exposes a function-scoped
walk that yields LocalDecl records with scope_path and byte ranges.

This module is the only place in the mwcc_debug package that imports
tree-sitter. If the binary wheels are missing, AstUnavailableError is
raised at first call and the bridge falls back to its slim regex walker
(see symbol_bridge fallback path).
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Optional


from src.common import tree_sitter_c as _ts_module
from src.common.tree_sitter_c import (
    node_text as _node_text,
    find_function_definition as _find_function_definition,
)

_TS_AVAILABLE = _ts_module.is_available()
_LANGUAGE = _ts_module.get_language() if _TS_AVAILABLE else None
_PARSER = _ts_module.get_parser() if _TS_AVAILABLE else None


@dataclass
class LocalDecl:
    """One local variable declaration extracted from a function body.

    Backward-compatible with the existing symbol_bridge.LocalDecl shape
    (same three first fields) plus six new fields all defaulted so test
    fixtures and legacy constructors keep working.
    """
    name: str
    type_str: str
    decl_index: int
    line_no: int = 0
    byte_range: tuple[int, int] = (0, 0)
    scope_path: tuple[str, ...] = ()
    scope_byte_range: tuple[int, int] = (0, 0)
    has_initializer: bool = False
    initializer_line_no: Optional[int] = None


class AstUnavailableError(Exception):
    """Tree-sitter or tree-sitter-c is not importable on this platform."""


class AstWalkError(Exception):
    """Tree-sitter parsed the source but the requested function's body
    contained ERROR nodes that enclose or interrupt a decl. Bridge
    should fall back to the regex walker.
    """
    def __init__(self, message: str, line_no: int = 0):
        super().__init__(message)
        self.line_no = line_no


# Cache: maps cache_key -> tree_sitter.Tree
# cache_key is either (path, mtime_ns) for on-disk callers or
# ("mem", id(source)) for in-memory callers (see spec § Caching).
_CACHE: "collections.OrderedDict[object, object]" = collections.OrderedDict()
_AST_CACHE_MAX = 64


def clear_cache() -> None:
    """Drop all cached parses. Called by the autouse pytest fixture."""
    _CACHE.clear()


def _cache_key(source: str, path: Optional[str]) -> object:
    if path is not None:
        import os
        try:
            mtime = os.stat(path).st_mtime_ns
            return (path, mtime)
        except FileNotFoundError:
            pass
    return ("mem", id(source))


def _parse_cached(source: str, path: Optional[str]):
    key = _cache_key(source, path)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    tree = _PARSER.parse(source.encode("utf-8"))
    _CACHE[key] = tree
    while len(_CACHE) > _AST_CACHE_MAX:
        _CACHE.popitem(last=False)
    return tree


def _has_decl_enclosing_error(node) -> bool:
    """Return True if any ``declaration`` node within *node* has
    ``has_error=True`` (meaning the declarator is syntactically broken).

    Body-level standalone ERROR nodes that don't wrap a declaration fragment
    (e.g. a bare macro invocation that tree-sitter can't parse) are tolerated.
    """
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "declaration" and n.has_error:
            return True
        for child in n.children:
            stack.append(child)
    return False


def _iter_compound_statements(node):
    """Yield direct compound_statement descendants of node, stopping at
    any function_definition (don't descend into nested functions)."""
    found = []
    stack = list(node.children)
    while stack:
        n = stack.pop()
        if n.type == "compound_statement":
            found.append(n)
            continue  # the recursive _walk_body call handles descent
        if n.type == "function_definition":
            continue
        for c in n.children:
            stack.append(c)
    yield from sorted(found, key=lambda n: n.start_byte)


def _walk_body(
    body_node,
    source_bytes: bytes,
    scope_path: tuple[str, ...],
    counter: list[int],
) -> list[LocalDecl]:
    """Recursive walk of a compound_statement body. Each nested
    compound_statement (``{ ... }``) gets its own scope_path element of
    the form ``block@l{line}c{col}`` from the opening brace position.
    """
    scope_byte_range = (body_node.start_byte, body_node.end_byte)
    out: list[LocalDecl] = []
    for child in body_node.children:
        if child.type == "declaration":
            out.extend(_extract_decls_from_declaration(
                child, source_bytes, scope_path, scope_byte_range, counter,
            ))
        elif child.type == "compound_statement":
            line, col = _byte_offset_to_line_col(source_bytes, child.start_byte)
            new_path = scope_path + (f"block@l{line}c{col}",)
            out.extend(_walk_body(child, source_bytes, new_path, counter))
        else:
            # Other statement types may contain nested compound statements
            # (if_statement, for_statement, while_statement, do_statement,
            # switch_statement). Walk their compound_statement children.
            for grand in _iter_compound_statements(child):
                line, col = _byte_offset_to_line_col(source_bytes, grand.start_byte)
                new_path = scope_path + (f"block@l{line}c{col}",)
                out.extend(_walk_body(grand, source_bytes, new_path, counter))
    return out


def _check_ts() -> None:
    if not _TS_AVAILABLE:
        raise AstUnavailableError(
            "tree-sitter or tree-sitter-c not importable; bridge will use "
            "regex fallback."
        )


def _byte_offset_to_line_col(source_bytes: bytes, offset: int) -> tuple[int, int]:
    """Return (1-indexed line, 0-indexed col) for a byte offset."""
    line = 1
    col = 0
    for b in source_bytes[:offset]:
        if b == 0x0A:  # '\n'
            line += 1
            col = 0
        else:
            col += 1
    return (line, col)


_DECLARATOR_NODE_TYPES = {
    "identifier",
    "init_declarator",
    "pointer_declarator",
    "array_declarator",
    "function_declarator",
    "parenthesized_declarator",
}


def _declaration_base_type(source_bytes: bytes, decl_node) -> str:
    """Return declaration specifiers shared by every declarator."""
    type_parts: list[str] = []
    for child in decl_node.children:
        if child.type in _DECLARATOR_NODE_TYPES:
            break
        text = _node_text(source_bytes, child).strip()
        if text and text not in {",", ";"}:
            type_parts.append(text)
    return " ".join(type_parts)


def _build_type_str(source_bytes: bytes, decl_node, declarator_node) -> str:
    """Return the type slice for a `declaration` node, *without* the
    declarator name. Handles pointers, arrays, qualifiers.

    Strategy: take the declaration's source slice up to the declarator
    start; if the declarator wraps a pointer or array, fold those tokens
    into the type.
    """
    # Peel pointer/array layers off the declarator.
    suffix_parts: list[str] = []
    node = declarator_node
    while node is not None and node.type != "identifier":
        if node.type == "pointer_declarator":
            suffix_parts.insert(0, "*")
            node = node.child_by_field_name("declarator")
        elif node.type == "array_declarator":
            size = node.child_by_field_name("size")
            size_text = _node_text(source_bytes, size) if size is not None else ""
            suffix_parts.append(f"[{size_text}]")
            node = node.child_by_field_name("declarator")
        elif node.type == "init_declarator":
            node = node.child_by_field_name("declarator")
        elif node.type == "function_declarator":
            params = node.child_by_field_name("parameters")
            params_text = _node_text(source_bytes, params) if params is not None else "()"
            suffix_parts.append(params_text)
            node = node.child_by_field_name("declarator")
        elif node.type == "parenthesized_declarator":
            inner = None
            for child in node.children:
                if child.type in ("identifier", "pointer_declarator", "array_declarator", "function_declarator"):
                    inner = child
                    break
            node = inner
        else:
            break

    base = _declaration_base_type(source_bytes, decl_node)
    pointer_part = ""
    array_part = ""
    fn_part = ""
    for part in suffix_parts:
        if part == "*":
            pointer_part += "*"
        elif part.startswith("["):
            array_part += part
        elif part.startswith("("):
            fn_part = part

    if fn_part:
        return f"{base} ({pointer_part}){fn_part}".strip()
    return f"{base}{pointer_part}{array_part}".strip()


def _extract_decls_from_declaration(
    decl_node, source_bytes: bytes, scope_path: tuple[str, ...],
    scope_byte_range: tuple[int, int], counter: list[int],
) -> list[LocalDecl]:
    """Given a `declaration` node, yield one LocalDecl per declarator."""
    out: list[LocalDecl] = []
    declarators = []
    for child in decl_node.children:
        if child.type in ("init_declarator",):
            declarators.append(child)
        elif child.type in (
            "identifier",
            "pointer_declarator",
            "array_declarator",
            "function_declarator",
        ):
            declarators.append(child)

    for d in declarators:
        has_init = False
        init_line = None
        if d.type == "init_declarator":
            value = d.child_by_field_name("value")
            if value is not None:
                has_init = True
                start_byte = value.start_byte
                init_line, _ = _byte_offset_to_line_col(source_bytes, start_byte)
            inner = d.child_by_field_name("declarator")
        else:
            inner = d

        # Drill to the identifier
        name_node = inner
        while name_node is not None and name_node.type != "identifier":
            if name_node.type == "pointer_declarator":
                name_node = name_node.child_by_field_name("declarator")
            elif name_node.type == "array_declarator":
                name_node = name_node.child_by_field_name("declarator")
            elif name_node.type == "function_declarator":
                name_node = name_node.child_by_field_name("declarator")
            elif name_node.type == "parenthesized_declarator":
                for child in name_node.children:
                    if child.type in (
                        "identifier",
                        "pointer_declarator",
                        "array_declarator",
                        "function_declarator",
                    ):
                        name_node = child
                        break
                else:
                    break
            else:
                break

        if name_node is None or name_node.type != "identifier":
            continue

        name = _node_text(source_bytes, name_node)
        type_str = _build_type_str(source_bytes, decl_node, d)
        line, _ = _byte_offset_to_line_col(source_bytes, d.start_byte)
        out.append(LocalDecl(
            name=name,
            type_str=type_str,
            decl_index=counter[0],
            line_no=line,
            byte_range=(d.start_byte, d.end_byte),
            scope_path=scope_path,
            scope_byte_range=scope_byte_range,
            has_initializer=has_init,
            initializer_line_no=init_line,
        ))
        counter[0] += 1

    return out


def walk_function(
    source: str,
    fn_name: str,
    path: Optional[str] = None,
) -> list[LocalDecl]:
    """Walk one C function's body (including nested blocks), return locals."""
    _check_ts()
    tree = _parse_cached(source, path)
    source_bytes = source.encode("utf-8")
    fn_node = _find_function_definition(tree.root_node, source_bytes, fn_name)
    if fn_node is None:
        return []

    body = fn_node.child_by_field_name("body")
    if body is None:
        return []

    # Macro-tolerance check: only fail on decl-enclosing ERROR nodes.
    if _has_decl_enclosing_error(body):
        line, _ = _byte_offset_to_line_col(source_bytes, body.start_byte)
        raise AstWalkError(
            f"function body for {fn_name!r} contains decl-enclosing ERROR nodes",
            line_no=line,
        )

    counter = [0]
    return _walk_body(body, source_bytes, (fn_name,), counter)
