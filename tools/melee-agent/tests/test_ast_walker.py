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


def test_walk_function_simple_top_level() -> None:
    """A function with three top-level decls produces three LocalDecls
    with correct scope_path (function-name only)."""
    src = (
        "void f(void) {\n"
        "    int a;\n"
        "    HSD_JObj* b;\n"
        "    char c[8];\n"
        "}\n"
    )
    decls = walk_function(src, "f", path=None)
    assert len(decls) == 3
    assert [d.name for d in decls] == ["a", "b", "c"]
    assert [d.type_str for d in decls] == ["int", "HSD_JObj*", "char[8]"]
    assert all(d.scope_path == ("f",) for d in decls)
    assert all(d.line_no > 0 for d in decls)


def test_walk_function_with_initializer() -> None:
    """A decl with an initializer sets has_initializer + initializer_line_no."""
    src = "void f(void) { int x = 5; }"
    decls = walk_function(src, "f", path=None)
    assert len(decls) == 1
    assert decls[0].name == "x"
    assert decls[0].has_initializer is True
    assert decls[0].initializer_line_no == 1


def test_walk_function_multi_declarator_splits_each() -> None:
    """`int x, y, z;` produces three LocalDecls with the same line_no
    and the same scope_path but distinct byte_ranges."""
    src = "void f(void) {\n    int x, y, z;\n}"
    decls = walk_function(src, "f", path=None)
    assert [d.name for d in decls] == ["x", "y", "z"]
    line_nos = {d.line_no for d in decls}
    assert line_nos == {2}
    byte_ranges = {d.byte_range for d in decls}
    assert len(byte_ranges) == 3


def test_walk_function_function_pointer() -> None:
    """A function pointer parses as one LocalDecl with type captured."""
    src = "void f(void) { void (*cb)(int); }"
    decls = walk_function(src, "f", path=None)
    assert len(decls) == 1
    assert decls[0].name == "cb"
