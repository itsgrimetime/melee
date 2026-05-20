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


# Cache lives here; Task 3 implements lookup logic.
_CACHE: dict[object, object] = {}
_AST_CACHE_MAX = 64


def clear_cache() -> None:
    """Drop all cached parses. Called by the autouse pytest fixture."""
    _CACHE.clear()


def walk_function(
    source: str,
    fn_name: str,
    path: Optional[str] = None,
) -> list[LocalDecl]:
    """Walk one C function's body, return its locals.

    Scaffold-only: returns [] for missing function. Real parsing arrives
    in Tasks 3 and 4.
    """
    # Stub: scaffold-task return for "function not found" case.
    if fn_name not in source:
        return []
    raise NotImplementedError(
        "walk_function: parsing not yet implemented (see Task 3)"
    )
