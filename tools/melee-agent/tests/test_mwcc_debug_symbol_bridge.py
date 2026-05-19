"""Tests for the source variable ↔ virtual register bridge."""

from __future__ import annotations

import textwrap

from src.mwcc_debug.symbol_bridge import (
    LocalDecl,
    walk_local_decls,
)


def test_walk_local_decls_simple() -> None:
    """One local decl gets recognized."""
    body = textwrap.dedent("""\
        {
            int x;
            return x;
        }
    """)
    decls = walk_local_decls(body)
    assert len(decls) == 1
    assert decls[0].name == "x"
    assert decls[0].type_str == "int"


def test_walk_local_decls_multiple_in_order() -> None:
    """Decls returned in source order."""
    body = textwrap.dedent("""\
        {
            int a;
            HSD_JObj* b;
            u32 c;
        }
    """)
    names = [d.name for d in walk_local_decls(body)]
    assert names == ["a", "b", "c"]


def test_walk_local_decls_skips_non_decl_statements() -> None:
    """Plain expression statements aren't decls."""
    body = textwrap.dedent("""\
        {
            int x;
            x = 5;
            foo(x);
            return x;
        }
    """)
    decls = walk_local_decls(body)
    assert [d.name for d in decls] == ["x"]


def test_walk_local_decls_handles_initializers() -> None:
    """`int x = 5;` is one decl, not a statement."""
    body = textwrap.dedent("""\
        {
            int x = 5;
            HSD_JObj* j = gobj->hsd_obj;
        }
    """)
    decls = walk_local_decls(body)
    assert [d.name for d in decls] == ["x", "j"]


def test_walk_local_decls_handles_macro_initializers() -> None:
    """Decls with MACRO(...) initializers (common in Melee) work."""
    body = textwrap.dedent("""\
        {
            MnEventData* data = GET_EVENTDATA(gobj);
        }
    """)
    decls = walk_local_decls(body)
    assert [d.name for d in decls] == ["data"]
    assert decls[0].type_str == "MnEventData*"


def test_walk_local_decls_ignores_decls_inside_nested_blocks() -> None:
    """v1 only sees top-level body decls. Nested block decls are
    skipped (less common in mwcc-targeted code; future work)."""
    body = textwrap.dedent("""\
        {
            int x;
            if (x) {
                int y;
            }
            int z;
        }
    """)
    names = [d.name for d in walk_local_decls(body)]
    assert names == ["x", "z"]


def test_walk_local_decls_skips_string_literal_lookalike() -> None:
    """A `;` inside a string literal doesn't terminate a statement."""
    body = textwrap.dedent('''\
        {
            const char* s = "int fake;";
            int real;
        }
    ''')
    names = [d.name for d in walk_local_decls(body)]
    assert names == ["s", "real"]
