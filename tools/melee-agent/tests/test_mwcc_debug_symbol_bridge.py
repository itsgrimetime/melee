"""Tests for the source variable ↔ virtual register bridge."""

from __future__ import annotations

import textwrap

from src.mwcc_debug.parser import (
    Block,
    Function,
    Instruction,
    Pass,
)
from src.mwcc_debug.symbol_bridge import (
    Binding,
    LocalDecl,
    list_bindings,
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


def test_walk_local_decls_multi_declarator() -> None:
    """`int x, y, z;` emits three entries in order."""
    body = "{ int x, y, z; }"
    decls = walk_local_decls(body)
    assert [d.name for d in decls] == ["x", "y", "z"]
    assert [d.decl_index for d in decls] == [0, 1, 2]
    assert all(d.type_str == "int" for d in decls)


def test_walk_local_decls_multi_declarator_with_initializers() -> None:
    """`int x = 1, y = 2;` emits two entries."""
    body = "{ int x = 1, y = 2; }"
    decls = walk_local_decls(body)
    assert [d.name for d in decls] == ["x", "y"]
    assert all(d.type_str == "int" for d in decls)


def test_walk_local_decls_array() -> None:
    """`int arr[10];` is recognized as a single decl."""
    body = "{ int arr[10]; }"
    decls = walk_local_decls(body)
    assert [d.name for d in decls] == ["arr"]
    assert decls[0].type_str == "int"


def test_walk_local_decls_array_with_decl_index_preserves_order() -> None:
    """`int x; int arr[5]; int z;` returns all three in order."""
    body = "{ int x; int arr[5]; int z; }"
    decls = walk_local_decls(body)
    assert [d.name for d in decls] == ["x", "arr", "z"]
    assert [d.decl_index for d in decls] == [0, 1, 2]


def test_walk_local_decls_warns_on_unrecognized_decl_shape() -> None:
    """Function-pointer decls aren't yet supported. The walker
    should record them via the warning hook so callers can detect
    silent failures."""
    body = "{ int x; void (*cb)(int); int z; }"
    unrecognized: list[str] = []
    decls = walk_local_decls(body, on_unrecognized=unrecognized.append)
    # The two parseable decls still come through
    assert [d.name for d in decls] == ["x", "z"]
    # The function-pointer line was flagged
    assert len(unrecognized) == 1
    assert "void" in unrecognized[0] or "(*cb)" in unrecognized[0]


def _make_ist(
    opcode: str, operands: str, regs: list[tuple[str, int]]
) -> Instruction:
    return Instruction(
        opcode=opcode, operands=operands, annotations=[], regs=regs
    )


def _make_pre_pass(virtuals_in_order: list[int]) -> Pass:
    """Construct a single-block pre-coloring pass that hits the
    given virtuals in order as destination operands."""
    pre = Pass(name="AFTER PEEPHOLE FORWARD")
    block = Block(index=0, succ=[], pred=[], labels=["L0"])
    for v in virtuals_in_order:
        block.instructions.append(
            _make_ist("li", f"r{v}, 0", [("r", v)])
        )
    pre.blocks.append(block)
    return pre


def test_list_bindings_locals_only_assigns_in_order() -> None:
    """Two locals get the first two distinct virtuals (≥32) seen."""
    source = textwrap.dedent("""\
        void f(void) {
            int a;
            int b;
        }
    """)
    pre = _make_pre_pass([32, 33, 34])
    bindings = list_bindings(source, "f", pre)
    locals_only = [b for b in bindings if b.kind == "local"]
    assert [b.var_name for b in locals_only] == ["a", "b"]
    assert locals_only[0].virtual == 32
    assert locals_only[1].virtual == 33
    assert all(b.confidence == "best-guess" for b in locals_only)


def test_list_bindings_function_not_found_returns_empty() -> None:
    source = "void other(void) { int x; }"
    pre = _make_pre_pass([32])
    assert list_bindings(source, "missing", pre) == []


def test_list_bindings_includes_params_when_observed() -> None:
    """Parameters appear in the binding list with kind='param'."""
    source = textwrap.dedent("""\
        void f(HSD_GObj* gobj, int n) {
            int local;
        }
    """)
    # Simulate: param virtuals 32, 33 then local virtual 34
    pre = _make_pre_pass([32, 33, 34])
    bindings = list_bindings(source, "f", pre)
    params = [b for b in bindings if b.kind == "param"]
    assert [b.var_name for b in params] == ["gobj", "n"]
    assert all(b.confidence == "best-guess" for b in params)


def test_list_bindings_unobserved_param_is_ambiguous() -> None:
    """If a parameter's expected virtual doesn't appear in pre-pass,
    confidence is 'ambiguous'."""
    source = "void f(HSD_GObj* gobj, int n) { int local; }"
    # Only two virtuals present — n's expected slot is missing
    pre = _make_pre_pass([32, 34])
    bindings = list_bindings(source, "f", pre)
    params = {b.var_name: b for b in bindings if b.kind == "param"}
    # gobj is observed (first virtual present), n is not
    assert params["gobj"].confidence == "best-guess"
    assert params["n"].confidence == "ambiguous"
