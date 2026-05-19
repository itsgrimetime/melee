"""Tests for the Tier 3 source mutator library."""

from __future__ import annotations

import textwrap

import pytest

from src.mwcc_debug.mutators import (
    MutationUnsupported,
    mutate_type_change,
)


def test_mutate_type_change_simple() -> None:
    """Change `int x` to `u32 x`."""
    source = textwrap.dedent("""\
        void f(void) {
            int x;
            x = 5;
        }
    """)
    result = mutate_type_change(source, "f", "x", "u32")
    assert "u32 x;" in result
    assert "int x;" not in result


def test_mutate_type_change_with_pointer_type() -> None:
    source = textwrap.dedent("""\
        void f(HSD_GObj* gobj) {
            HSD_JObj* j;
            j = gobj->hsd_obj;
        }
    """)
    result = mutate_type_change(source, "f", "j", "void*")
    assert "void* j;" in result
    assert "HSD_JObj* j;" not in result


def test_mutate_type_change_preserves_initializer() -> None:
    """`int x = 5;` → `u32 x = 5;`."""
    source = "void f(void) { int x = 5; }"
    result = mutate_type_change(source, "f", "x", "u32")
    assert "u32 x = 5;" in result


def test_mutate_type_change_unknown_var_raises() -> None:
    source = "void f(void) { int x; }"
    with pytest.raises(MutationUnsupported):
        mutate_type_change(source, "f", "missing", "u32")


def test_mutate_type_change_unknown_function_raises() -> None:
    source = "void other(void) { int x; }"
    with pytest.raises(MutationUnsupported):
        mutate_type_change(source, "missing", "x", "u32")


def test_mutate_type_change_only_touches_target_decl() -> None:
    """Other decls (and uses) of similarly-named variables aren't
    touched."""
    source = textwrap.dedent("""\
        void f(void) {
            int x;
            int y;
            x = y;
        }
    """)
    result = mutate_type_change(source, "f", "x", "u32")
    assert "u32 x;" in result
    assert "int y;" in result
    # The use `x = y;` is unchanged in body
    assert "x = y;" in result
