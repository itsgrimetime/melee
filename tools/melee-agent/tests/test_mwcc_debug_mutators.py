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


def test_mutate_insert_alias_c89_split_when_non_decl_precedes() -> None:
    """Fix A: when a non-declaration statement precedes the insertion
    point, emit bare decl at block-top + assignment at use site so the
    generated code is C89-compliant (declarations before executable
    statements in a block).
    """
    source = textwrap.dedent("""\
        void f(HSD_JObj* root, HSD_JObj* port_indicator)
        {
            SomeFunc(root);
            port_indicator->color = 0;
        }
    """)
    result = mutate_insert_alias_before_use(
        source, "f", "port_indicator", at_stmt_index=0,
    )
    # The bare decl must appear immediately after the opening '{'.
    # The assignment must appear immediately before the use.
    lines = result.splitlines()
    # Find the decl and assignment lines.
    decl_lines = [l for l in lines if "port_indicator_alias;" in l]
    assign_lines = [l for l in lines if "port_indicator_alias = port_indicator;" in l]
    use_lines = [l for l in lines if "port_indicator_alias->color" in l]
    assert decl_lines, "bare decl line not found"
    assert assign_lines, "assignment line not found"
    assert use_lines, "rewritten use not found"
    # Decl must come before the executable SomeFunc() call.
    decl_idx = lines.index(decl_lines[0])
    some_func_idx = next(i for i, l in enumerate(lines) if "SomeFunc" in l)
    assert decl_idx < some_func_idx, (
        "bare decl must appear before the non-decl SomeFunc() statement"
    )
    # Assignment must appear before the rewritten use.
    assign_idx = lines.index(assign_lines[0])
    use_idx = lines.index(use_lines[0])
    assert assign_idx < use_idx, "assignment must precede the use"
    # No combined initializing form should appear (that would be invalid C89).
    assert "HSD_JObj* port_indicator_alias = port_indicator;" not in result, (
        "combined initializing form must not appear when non-decl precedes"
    )


def test_mutate_insert_alias_c89_combined_at_block_top() -> None:
    """Fix A: when the insertion point is already at block top (only decls
    precede it), emit the combined initializing form — no split needed.
    """
    source = textwrap.dedent("""\
        void f(HSD_JObj* root, HSD_JObj* port_indicator)
        {
            int x;
            port_indicator->color = 0;
        }
    """)
    result = mutate_insert_alias_before_use(
        source, "f", "port_indicator", at_stmt_index=0,
    )
    # Only declarations (`int x;`) precede the use → combined form is safe.
    assert "HSD_JObj* port_indicator_alias = port_indicator;" in result
    # No bare decl-only line should appear.
    bare_decl_lines = [
        l for l in result.splitlines()
        if l.strip() == "HSD_JObj* port_indicator_alias;"
    ]
    assert not bare_decl_lines, (
        "split decl-only line should not appear when block-top is clear"
    )


def test_mutate_insert_alias_struct_field_access_raises() -> None:
    """Fix F: when 'var_name' only appears as a struct field (->var_name or
    .var_name) in the target statement, the alias replacement produces the
    invalid '->var_name_alias' pattern.  mutate_insert_alias_before_use
    must raise MutationUnsupported so the seed is safely skipped."""
    # `jobjs` is a local pointer that's used only via `data->jobjs[i]`.
    # The word-boundary regex matches `jobjs` inside `->jobjs` and replaces it,
    # yielding `data->jobjs_alias[23]`.  The fix detects this and raises.
    source = textwrap.dedent("""\
        void fn_80247510(HSD_GObj* gobj) {
            MnFooData* data;
            HSD_JObj** jobjs;
            data = gobj->user_data;
            jobjs = data->jobjs;
            HSD_JObjRemoveAll(data->jobjs[23]);
        }
    """)
    with pytest.raises(MutationUnsupported, match="struct field"):
        mutate_insert_alias_before_use(source, "fn_80247510", "jobjs", at_stmt_index=0)


def test_mutate_insert_alias_after_first_assignment() -> None:
    """Fix E: when 'local' is first assigned (plain write) BEFORE the
    target reading-use statement, the alias assignment is placed immediately
    after that first write — not at the target use site.

    Shape produced:
        {
            type local;
            type alias;       ← bare decl at block top
            ...
            local = expr;     ← first write
            alias = local;    ← alias assigned AFTER local is set (Fix E)
            ...
            use(alias);       ← rewritten target
        }
    """
    source = textwrap.dedent("""\
        void fn_test(HSD_GObj* gobj) {
            int* port_indicator;
            DoInit(gobj);
            port_indicator = (int*)gobj->user_data;
            port_indicator[0] = 1;
        }
    """)
    result = mutate_insert_alias_before_use(
        source, "fn_test", "port_indicator", at_stmt_index=0,
    )
    lines = result.splitlines()
    # The alias assignment must appear AFTER `port_indicator = ...;`
    assign_idx = next(
        (i for i, l in enumerate(lines) if "port_indicator_alias = port_indicator;" in l),
        None,
    )
    first_write_idx = next(
        (i for i, l in enumerate(lines) if "port_indicator = (int*)gobj->user_data;" in l),
        None,
    )
    assert assign_idx is not None, "alias assignment line not found"
    assert first_write_idx is not None, "first-write line not found"
    assert assign_idx > first_write_idx, (
        "alias assignment must appear AFTER local's first write, not before it"
    )
    # The rewritten use must use the alias
    assert any("port_indicator_alias[0] = 1;" in l for l in lines)


def test_regression_fn_8024e1b4_dual_pointer_shape() -> None:
    """Pin the dual-pointer mutation shape: starting from a simple
    function reading `data` once, mutate_insert_alias to produce the
    aliased version. This is the v1 mutator's reproduction target
    from MEMORY.md (`fn_8024E1B4` dual-pointer pattern).
    """
    before = textwrap.dedent("""\
        void fn_8024E1B4(HSD_GObj* gobj)
        {
            MnEventData* data = GET_EVENTDATA(gobj);
            HSD_GObjPLink_80390228(data->gobjs[0]);
        }
    """)
    result = mutate_insert_alias_before_use(
        before, "fn_8024E1B4", "data", at_stmt_index=0,
        new_name="tmp",
    )
    # The dual-pointer pattern: `tmp = data;` inserted before the use
    assert "MnEventData* tmp = data;" in result
    assert "HSD_GObjPLink_80390228(tmp->gobjs[0]);" in result
    # The decl line itself isn't touched
    assert "MnEventData* data = GET_EVENTDATA(gobj);" in result
