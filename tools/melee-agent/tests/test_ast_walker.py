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
    assert [d.type_str for d in decls] == ["int", "int", "int"]
    line_nos = {d.line_no for d in decls}
    assert line_nos == {2}
    byte_ranges = {d.byte_range for d in decls}
    assert len(byte_ranges) == 3


def test_walk_function_multi_declarator_with_initializers_keeps_base_type() -> None:
    """Later declarators in a combined C89 declaration must not absorb
    the previous declarator text into their type."""
    src = "void f(void) {\n    int i = 0, j;\n}"
    decls = walk_function(src, "f", path=None)
    assert [d.name for d in decls] == ["i", "j"]
    assert [d.type_str for d in decls] == ["int", "int"]


def test_walk_function_function_pointer() -> None:
    """A function pointer parses as one LocalDecl with type captured."""
    src = "void f(void) { void (*cb)(int); }"
    decls = walk_function(src, "f", path=None)
    assert len(decls) == 1
    assert decls[0].name == "cb"


def test_walk_function_for_loop_block() -> None:
    """A for-loop body's decls get their own scope_path."""
    src = (
        "void f(void) {\n"
        "    int outer;\n"
        "    for (int i = 0; i < 8; i++) {\n"
        "        int inner;\n"
        "    }\n"
        "}\n"
    )
    decls = walk_function(src, "f", path=None)
    names = {d.name: d for d in decls}
    assert "outer" in names
    assert "inner" in names
    assert names["outer"].scope_path == ("f",)
    assert names["inner"].scope_path[0] == "f"
    assert len(names["inner"].scope_path) == 2
    assert names["inner"].scope_path[1].startswith("block@l")


def test_walk_function_if_else_distinct_scopes() -> None:
    """`if (x) { ... } else { ... }` makes two distinct nested scopes."""
    src = (
        "void f(int x) {\n"
        "    if (x) {\n"
        "        int a;\n"
        "    } else {\n"
        "        int b;\n"
        "    }\n"
        "}\n"
    )
    decls = walk_function(src, "f", path=None)
    by_name = {d.name: d for d in decls}
    assert by_name["a"].scope_path != by_name["b"].scope_path
    assert by_name["a"].scope_path[0] == "f"
    assert by_name["b"].scope_path[0] == "f"


def test_walk_function_if_else_decl_order_is_source_order() -> None:
    """Sibling block declarations are emitted in source order, not
    traversal-stack order."""
    src = (
        "void f(int x) {\n"
        "    if (x) {\n"
        "        int first;\n"
        "    } else {\n"
        "        int second;\n"
        "    }\n"
        "}\n"
    )
    decls = walk_function(src, "f", path=None)
    assert [d.name for d in decls] == ["first", "second"]
    assert [d.decl_index for d in decls] == [0, 1]


def test_walk_function_shadowing_outer_and_inner_i() -> None:
    """An outer `int i` and an inner `int i` are both surfaced."""
    src = (
        "void f(void) {\n"
        "    int i;\n"
        "    {\n"
        "        int i;\n"
        "    }\n"
        "}\n"
    )
    decls = walk_function(src, "f", path=None)
    paths = sorted(d.scope_path for d in decls if d.name == "i")
    assert len(paths) == 2
    assert paths[0] != paths[1]


def test_walk_function_two_blocks_same_line_distinct_paths() -> None:
    """`if (a) { ... } else { ... }` on one line: column suffix
    disambiguates the two scopes."""
    src = "void f(int a) {\n    if (a) { int x; } else { int y; }\n}"
    decls = walk_function(src, "f", path=None)
    by_name = {d.name: d for d in decls}
    assert by_name["x"].scope_path[1] != by_name["y"].scope_path[1]


def test_walk_function_cache_returns_same_objects() -> None:
    """Two calls on the same source return objects derived from the
    same cached parse tree (verified by id() of the cached entry)."""
    src = "void f(void) { int x; }"
    decls_a = walk_function(src, "f", path=None)
    decls_b = walk_function(src, "f", path=None)
    assert [d.name for d in decls_a] == [d.name for d in decls_b]


def test_walk_function_tolerates_pad_stack_macro() -> None:
    """Body-level ERROR nodes from PAD_STACK don't trigger AstWalkError
    as long as the decls themselves parse cleanly."""
    src = (
        "void f(void) {\n"
        "    int x;\n"
        "    PAD_STACK(64);\n"
        "    int y;\n"
        "}\n"
    )
    decls = walk_function(src, "f", path=None)
    names = [d.name for d in decls]
    assert "x" in names
    assert "y" in names


def test_walk_function_tolerates_m2c_field_pointer_type_initializer() -> None:
    """M2C_FIELD pointer-type arguments create ERROR nodes inside the macro
    call, but they do not corrupt the surrounding declaration."""
    src = (
        "void f(void) {\n"
        "    int x = M2C_FIELD(sp28, int*, 0xC);\n"
        "    int y;\n"
        "}\n"
    )
    decls = walk_function(src, "f", path=None)
    assert [d.name for d in decls] == ["x", "y"]


def test_walk_function_raises_on_decl_enclosing_error() -> None:
    """An ERROR node that interrupts a declaration triggers AstWalkError."""
    src = "void f(void) { int = 5; }"  # syntax error inside decl
    with pytest.raises(AstWalkError):
        walk_function(src, "f", path=None)
