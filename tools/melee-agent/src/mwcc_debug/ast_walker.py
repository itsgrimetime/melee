"""Tree-sitter façade for the symbol bridge.

Parses C source via tree-sitter + tree-sitter-c, exposes a function-scoped
walk that yields LocalDecl records with scope_path and byte ranges.

This module is the only place in the mwcc_debug package that imports
tree-sitter. If the binary wheels are missing, AstUnavailableError is
raised at first call and the bridge falls back to its slim regex walker
(see symbol_bridge fallback path).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


try:
    import tree_sitter
    import tree_sitter_c
    _LANGUAGE = tree_sitter.Language(tree_sitter_c.language())
    _PARSER = tree_sitter.Parser(_LANGUAGE)
    _TS_AVAILABLE = True
except ImportError:
    _TS_AVAILABLE = False
    _LANGUAGE = None
    _PARSER = None


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


# Cache lives here; Task 4 implements lookup logic.
_CACHE: dict[object, object] = {}
_AST_CACHE_MAX = 64


def clear_cache() -> None:
    """Drop all cached parses. Called by the autouse pytest fixture."""
    _CACHE.clear()


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


def _node_text(source_bytes: bytes, node) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _find_function_definition(root, source_bytes: bytes, fn_name: str):
    """Search the tree for a function_definition whose declarator name
    matches `fn_name`. Returns the function_definition node or None.
    """
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "function_definition":
            # Find the declarator → function_declarator → identifier
            decl = node.child_by_field_name("declarator")
            while decl is not None and decl.type != "identifier":
                # Could be pointer_declarator wrapping function_declarator
                inner = decl.child_by_field_name("declarator")
                if inner is None:
                    break
                decl = inner
            if decl is not None and decl.type == "identifier":
                if _node_text(source_bytes, decl) == fn_name:
                    return node
        for child in node.children:
            stack.append(child)
    return None


def _build_type_str(source_bytes: bytes, decl_node, declarator_node) -> str:
    """Return the type slice for a `declaration` node, *without* the
    declarator name. Handles pointers, arrays, qualifiers.

    Strategy: take the declaration's source slice up to the declarator
    start; if the declarator wraps a pointer or array, fold those tokens
    into the type.
    """
    type_parts: list[str] = []
    for child in decl_node.children:
        if child == declarator_node:
            break
        text = _node_text(source_bytes, child).strip()
        if text:
            type_parts.append(text)

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

    base = " ".join(type_parts)
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
    """Walk one C function's body, return its locals."""
    _check_ts()
    source_bytes = source.encode("utf-8")
    tree = _PARSER.parse(source_bytes)
    fn_node = _find_function_definition(tree.root_node, source_bytes, fn_name)
    if fn_node is None:
        return []

    body = fn_node.child_by_field_name("body")
    if body is None:
        return []

    counter = [0]
    out: list[LocalDecl] = []
    scope_path: tuple[str, ...] = (fn_name,)
    scope_byte_range = (body.start_byte, body.end_byte)

    # Phase 1, Task 3: top-level walk only. Iterate direct children of
    # the function body's compound_statement.
    for child in body.children:
        if child.type == "declaration":
            out.extend(_extract_decls_from_declaration(
                child, source_bytes, scope_path, scope_byte_range, counter,
            ))

    return out
