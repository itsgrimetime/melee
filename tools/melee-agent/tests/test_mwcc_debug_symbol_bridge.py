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


def test_list_bindings_params_are_best_guess_even_when_unobserved() -> None:
    """Params are always best-guess: MWCC always allocates a virtual
    slot for each parameter, even when the param's value lives in the
    ABI register (r3/r4/...) without being re-defined in the function
    body. The pre-coloring pass may therefore legitimately omit the
    param's virtual as a destination — but the slot is still there.

    This is the common case for `gobj` in proc callbacks. See the
    calibration test against fn_80247510."""
    source = "void f(HSD_GObj* gobj, int n) { int local; }"
    # Only two virtuals present — both param slots (r32, r33) and
    # local slot (r34) are notionally allocated, but only r32 and
    # r34 appear as destinations.
    pre = _make_pre_pass([32, 34])
    bindings = list_bindings(source, "f", pre)
    params = {b.var_name: b for b in bindings if b.kind == "param"}
    # Both params are best-guess; their virtuals are deterministic
    # based on declaration order.
    assert params["gobj"].confidence == "best-guess"
    assert params["gobj"].virtual == 32
    assert params["n"].confidence == "best-guess"
    assert params["n"].virtual == 33


from src.mwcc_debug.symbol_bridge import (
    BindingBasis,
    find_var_for_virtual,
    find_virtual_for_var,
    list_bindings_with_basis,
)


def test_list_bindings_with_basis_returns_basis_evidence() -> None:
    """list_bindings_with_basis exposes the parsed inputs + flags."""
    source = textwrap.dedent("""\
        void f(int n) {
            int a;
            int b;
        }
    """)
    pre = _make_pre_pass([32, 33, 34])
    bindings, basis = list_bindings_with_basis(source, "f", pre)
    assert basis is not None
    assert [p.name for p in basis.parsed_params] == ["n"]
    assert [ld.name for ld in basis.parsed_locals] == ["a", "b"]
    assert basis.observed_virtuals == [32, 33, 34]
    assert basis.red_flags == []
    # All locals stay best-guess when no red flags
    assert all(
        b.confidence == "best-guess"
        for b in bindings if b.kind == "local"
    )


def test_red_flag_nested_decl_demotes_to_low_confidence() -> None:
    """Functions with nested-block decls get the 'nested-decl' flag,
    which demotes locals from best-guess to low-confidence."""
    source = textwrap.dedent("""\
        void f(void) {
            int a;
            if (x) {
                int nested;
            }
            int b;
        }
    """)
    pre = _make_pre_pass([32, 33, 34])
    bindings, basis = list_bindings_with_basis(source, "f", pre)
    assert basis is not None
    assert "nested-decl" in basis.red_flags
    locals_ = [b for b in bindings if b.kind == "local"]
    # Locals observed as destinations → demoted to low-confidence
    assert all(b.confidence == "low-confidence" for b in locals_)


def test_red_flag_extra_virtuals_demotes_to_low_confidence() -> None:
    """Many more observed virtuals than parsed locals signals that
    MWCC introduced temps (CSE/IV) that shifted the cursor."""
    source = "void f(int n) { int a; }"
    # 1 param + 1 local should produce 2 virtuals. Simulate 8 (extra
    # compiler-introduced temps). Difference = 6 ≥ 3 → extra-virtuals.
    pre = _make_pre_pass([32, 33, 34, 35, 36, 37, 38, 39])
    bindings, basis = list_bindings_with_basis(source, "f", pre)
    assert basis is not None
    assert "extra-virtuals" in basis.red_flags
    local = next(b for b in bindings if b.kind == "local")
    assert local.confidence == "low-confidence"


def test_red_flag_static_local_detected() -> None:
    """Functions with 'static' locals get the static-local red flag."""
    source = textwrap.dedent("""\
        void f(void) {
            int a;
            static int s = 0;
        }
    """)
    pre = _make_pre_pass([32, 33])
    bindings, basis = list_bindings_with_basis(source, "f", pre)
    assert basis is not None
    assert "static-local" in basis.red_flags


def test_red_flag_unrecognized_decl_detected() -> None:
    """If the parser can't handle a decl shape (function pointer etc.)
    it gets surfaced as unrecognized-decl."""
    source = textwrap.dedent("""\
        void f(void) {
            int a;
            void (*cb)(int);
            int b;
        }
    """)
    pre = _make_pre_pass([32, 33, 34])
    bindings, basis = list_bindings_with_basis(source, "f", pre)
    assert basis is not None
    assert "unrecognized-decl" in basis.red_flags
    assert any("(*cb)" in s for s in basis.unrecognized_decls)


def test_function_not_found_returns_empty_and_none_basis() -> None:
    """When the function doesn't exist, return ([], None)."""
    source = "void other(void) { int x; }"
    pre = _make_pre_pass([32])
    bindings, basis = list_bindings_with_basis(source, "missing", pre)
    assert bindings == []
    assert basis is None


def test_find_virtual_for_var_existing_local() -> None:
    source = "void f(void) { int x; int y; }"
    pre = _make_pre_pass([32, 33])
    binding = find_virtual_for_var(source, "f", "y", pre)
    assert binding is not None
    assert binding.virtual == 33
    assert binding.kind == "local"


def test_find_virtual_for_var_unknown_returns_none() -> None:
    source = "void f(void) { int x; }"
    pre = _make_pre_pass([32])
    assert find_virtual_for_var(source, "f", "z", pre) is None


def test_find_var_for_virtual_inverse() -> None:
    source = "void f(void) { int a; int b; int c; }"
    pre = _make_pre_pass([32, 33, 34])
    binding = find_var_for_virtual(source, "f", 33, pre)
    assert binding is not None
    assert binding.var_name == "b"


import pathlib

import pytest

from src.mwcc_debug.parser import parse_pcdump

CALIBRATION_FIXTURES = (
    pathlib.Path(__file__).parent / "fixtures" / "mwcc_debug"
)


@pytest.mark.skipif(
    not (CALIBRATION_FIXTURES / "fn_80247510_pcdump.txt").exists(),
    reason="fn_80247510 fixture not present",
)
def test_calibration_fn_80247510_has_param_gobj() -> None:
    """Calibration gate: fn_80247510's first parameter gobj must bind
    to a virtual >=32 with kind='param'."""
    pcdump_text = (
        CALIBRATION_FIXTURES / "fn_80247510_pcdump.txt"
    ).read_text()
    source_path = pathlib.Path(
        "/Users/mike/code/melee/src/melee/mn/mnvibration.c"
    )
    if not source_path.exists():
        pytest.skip("mnvibration.c not present")
    source = source_path.read_text()

    fns = parse_pcdump(pcdump_text)
    fn = next((f for f in fns if f.name == "fn_80247510"), None)
    assert fn is not None
    pre = fn.last_precolor_pass()
    assert pre is not None

    bindings = list_bindings(source, "fn_80247510", pre)
    params = [b for b in bindings if b.kind == "param"]
    assert params, "fn_80247510 must have at least one param binding"
    # gobj is the first param
    assert params[0].var_name == "gobj"
    assert params[0].virtual >= 32
    assert params[0].confidence == "best-guess"


@pytest.mark.skipif(
    not pathlib.Path(
        "/Users/mike/code/melee/src/melee/mn/mnevent.c"
    ).exists(),
    reason="mnevent.c not present",
)
def test_calibration_fn_8024e1b4_dual_pointer_locals() -> None:
    """Calibration: fn_8024E1B4 has locals tree, tmp, data, iter, i
    (per MEMORY.md dual-pointer pattern). The bridge should find them."""
    source = pathlib.Path(
        "/Users/mike/code/melee/src/melee/mn/mnevent.c"
    ).read_text()
    # Build a synthetic pre_pass with enough virtuals (one per
    # expected entity: gobj param + 5 locals = 6 virtuals).
    pre = _make_pre_pass([32, 33, 34, 35, 36, 37])
    bindings = list_bindings(source, "fn_8024E1B4", pre)
    names = [b.var_name for b in bindings]
    # Expect: gobj (param), then tree, tmp, data, iter, i (locals)
    assert "gobj" in names
    assert "tree" in names
    assert "tmp" in names
    assert "data" in names
    assert "iter" in names
    assert "i" in names

    # Verify ordering: gobj is param, the rest are locals in source order
    param_names = [b.var_name for b in bindings if b.kind == "param"]
    local_names = [b.var_name for b in bindings if b.kind == "local"]
    assert param_names == ["gobj"]
    assert local_names == ["tree", "tmp", "data", "iter", "i"]


def test_local_decl_has_new_scope_fields_with_defaults() -> None:
    """LocalDecl carries the new scope fields with safe defaults."""
    from src.mwcc_debug.symbol_bridge import LocalDecl
    d = LocalDecl(name="x", type_str="int", decl_index=0)
    assert d.line_no == 0
    assert d.byte_range == (0, 0)
    assert d.scope_path == ()
    assert d.scope_byte_range == (0, 0)
    assert d.has_initializer is False
    assert d.initializer_line_no is None


def test_binding_has_scope_path_with_default() -> None:
    """Binding has a new scope_path field, defaults to ()."""
    from src.mwcc_debug.symbol_bridge import Binding
    b = Binding(
        var_name="x", virtual=32, decl_line=5,
        kind="local", type_str="int", confidence="best-guess",
    )
    assert b.scope_path == ()


def test_binding_basis_has_decls_by_scope_with_default() -> None:
    """BindingBasis has a new decls_by_scope dict."""
    from src.mwcc_debug.symbol_bridge import BindingBasis
    bb = BindingBasis(
        parsed_params=[], parsed_locals=[],
        observed_virtuals=[], unrecognized_decls=[], red_flags=[],
    )
    assert bb.decls_by_scope == {}
