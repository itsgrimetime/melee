"""Shared tree-sitter-c parser bootstrap and AST helpers.

Single import site for the tree_sitter / tree_sitter_c wheels so multiple
callers (mwcc_debug.ast_walker, cli.fingerprint, ...) don't each maintain
their own try/except + module-level objects.

Also exposes function-locator helpers (`find_function_definition`,
`node_text`) that were previously private to ast_walker.py.
"""
from __future__ import annotations

from typing import Optional


class TreeSitterUnavailableError(ImportError):
    """Raised when callers ask for a parser but tree-sitter is missing."""


try:
    import tree_sitter
    import tree_sitter_c
    _LANGUAGE = tree_sitter.Language(tree_sitter_c.language())
    _PARSER = tree_sitter.Parser(_LANGUAGE)
    _AVAILABLE = True
except Exception:  # noqa: BLE001 — ImportError or ABI mismatch on bad wheel
    _LANGUAGE = None
    _PARSER = None
    _AVAILABLE = False


def is_available() -> bool:
    """True if tree-sitter and tree-sitter-c are importable."""
    return _AVAILABLE


def get_parser():
    """Return the shared tree-sitter parser; raise if unavailable."""
    if not _AVAILABLE:
        raise TreeSitterUnavailableError(
            "tree-sitter or tree-sitter-c is not installed"
        )
    return _PARSER


def get_language():
    """Return the tree-sitter-c language object; raise if unavailable."""
    if not _AVAILABLE:
        raise TreeSitterUnavailableError(
            "tree-sitter or tree-sitter-c is not installed"
        )
    return _LANGUAGE


def node_text(source_bytes: bytes, node) -> str:
    """Return the source slice for a tree-sitter node, UTF-8 decoded."""
    return source_bytes[node.start_byte:node.end_byte].decode(
        "utf-8", errors="replace"
    )


def _unwrap_declarator(decl):
    """Descend from a declarator node toward the innermost identifier.

    Follows the `declarator` field when present (function_declarator,
    pointer_declarator, array_declarator, init_declarator) and descends
    through `parenthesized_declarator` children to handle function-pointer
    return types like `int (*fn(void))(int)`.
    """
    while decl is not None and decl.type != "identifier":
        inner = decl.child_by_field_name("declarator")
        if inner is None and decl.type == "parenthesized_declarator":
            # parenthesized_declarator has no `declarator` field; pick the
            # first non-punctuation child.
            for child in decl.children:
                if child.type not in ("(", ")"):
                    inner = child
                    break
        if inner is None:
            break
        decl = inner
    return decl


def find_function_definition(root, source_bytes: bytes, fn_name: str):
    """Search the tree for a function_definition whose declarator name
    matches `fn_name`. Returns the function_definition node or None.

    Handles function-pointer return types and pointer_declarator wrappers
    by unwrapping the declarator chain until an identifier is reached.
    """
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "function_definition":
            decl = _unwrap_declarator(node.child_by_field_name("declarator"))
            if decl is not None and decl.type == "identifier":
                if node_text(source_bytes, decl) == fn_name:
                    return node
        for child in node.children:
            stack.append(child)
    return None
