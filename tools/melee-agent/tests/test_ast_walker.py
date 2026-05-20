"""Tests for ast_walker — tree-sitter façade for symbol_bridge."""
from __future__ import annotations

import pytest

from src.mwcc_debug.ast_walker import (
    AstUnavailableError,
    AstWalkError,
    LocalDecl,
    clear_cache,
    walk_function,
)


def test_local_decl_has_new_fields_with_defaults() -> None:
    """LocalDecl has the new ast-walker fields with safe defaults."""
    d = LocalDecl(name="x", type_str="int", decl_index=0)
    assert d.line_no == 0
    assert d.byte_range == (0, 0)
    assert d.scope_path == ()
    assert d.scope_byte_range == (0, 0)
    assert d.has_initializer is False
    assert d.initializer_line_no is None


def test_walk_function_not_found_returns_empty() -> None:
    """Asking for a function that doesn't exist returns []."""
    src = "void other(void) { int x; }"
    assert walk_function(src, "missing", path=None) == []


def test_walk_function_unavailable_raises_subclass() -> None:
    """AstUnavailableError and AstWalkError are both exceptions."""
    assert issubclass(AstUnavailableError, Exception)
    assert issubclass(AstWalkError, Exception)


def test_clear_cache_exists_and_returns_none() -> None:
    """clear_cache() is callable for test isolation."""
    assert clear_cache() is None
