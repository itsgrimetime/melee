"""Tests for the Tier 3 source mutator library."""

from __future__ import annotations

import textwrap

import pytest

from src.mwcc_debug.mutators import (
    MutationUnsupported,
    mutate_type_change,
)
from src.mwcc_debug.mutators import mutate_insert_alias_before_use


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


def test_mutate_insert_alias_before_first_use() -> None:
    """Insert `data_alias = data;` before the first use of `data`."""
    source = textwrap.dedent("""\
        void f(MnEventData* data) {
            data->x = 0;
            data->y = 1;
        }
    """)
    result = mutate_insert_alias_before_use(
        source, "f", "data", at_stmt_index=0,
    )
    # Alias decl is inserted before the first use
    assert "MnEventData* data_alias = data;" in result
    # First use is rewritten to data_alias
    assert "data_alias->x = 0;" in result
    # Second use is unchanged
    assert "data->y = 1;" in result


def test_mutate_insert_alias_before_second_use() -> None:
    source = textwrap.dedent("""\
        void f(MnEventData* data) {
            data->x = 0;
            data->y = 1;
            data->z = 2;
        }
    """)
    result = mutate_insert_alias_before_use(
        source, "f", "data", at_stmt_index=1,
    )
    # First use unchanged
    assert "data->x = 0;" in result
    # Second use rewritten
    assert "data_alias->y = 1;" in result
    # Third use unchanged
    assert "data->z = 2;" in result


def test_mutate_insert_alias_custom_name() -> None:
    source = "void f(int* p) { *p = 0; }"
    result = mutate_insert_alias_before_use(
        source, "f", "p", at_stmt_index=0, new_name="alt",
    )
    assert "int* alt = p;" in result
    assert "*alt = 0;" in result


def test_mutate_insert_alias_unknown_var_raises() -> None:
    source = "void f(int* p) { *p = 0; }"
    with pytest.raises(MutationUnsupported):
        mutate_insert_alias_before_use(
            source, "f", "missing", at_stmt_index=0,
        )


def test_mutate_insert_alias_index_out_of_range_raises() -> None:
    """If at_stmt_index >= number of reading statements, raise."""
    source = "void f(int* p) { *p = 0; }"
    with pytest.raises(MutationUnsupported):
        mutate_insert_alias_before_use(
            source, "f", "p", at_stmt_index=5,
        )


def test_mutate_insert_alias_skips_lhs_of_assignment() -> None:
    """`p = ...;` is a WRITE, not a read — alias-split skips it."""
    source = textwrap.dedent("""\
        void f(void) {
            int* p;
            p = 0;
            p[0] = 1;
        }
    """)
    result = mutate_insert_alias_before_use(
        source, "f", "p", at_stmt_index=0,
    )
    # First read (after the write) is `p[0] = 1;`
    assert "p[0] = 1;" not in result.split("p_alias = p;")[0]
    assert "p_alias[0] = 1;" in result
