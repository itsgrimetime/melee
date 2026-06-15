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
    find_all_virtuals_for_var,
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


def test_nested_decl_no_longer_emits_red_flag() -> None:
    """Phase 1: nested-block decls are now seen by the AST walker, so
    the 'nested-decl' red flag is no longer emitted. Locals that are
    observed as destinations remain best-guess."""
    source = textwrap.dedent("""\
        void f(void) {
            int a;
            if (1) {
                int nested;
            }
            int b;
        }
    """)
    pre = _make_pre_pass([32, 33, 34])
    bindings, basis = list_bindings_with_basis(source, "f", pre)
    assert basis is not None
    assert "nested-decl" not in basis.red_flags
    locals_ = [b for b in bindings if b.kind == "local"]
    by_name = {b.var_name: b for b in locals_}
    # Top-level locals stay best-guess when observed; nested-block local is
    # demoted to ambiguous-nested by the Phase-1 demotion pass (Task 7).
    assert by_name["a"].confidence == "best-guess"
    assert by_name["b"].confidence == "best-guess"
    assert by_name["nested"].confidence == "ambiguous-nested"


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


def test_red_flag_unrecognized_decl_detected_in_fallback() -> None:
    """The regex fallback flags function-pointer decls as unrecognized-decl.
    The AST (tree-sitter) primary path handles them correctly, so this
    test exercises the walker directly (not via list_bindings_with_basis
    which now uses the AST path)."""
    body = "{ int a; void (*cb)(int); int b; }"
    unrecognized: list[str] = []
    decls = walk_local_decls(body, on_unrecognized=unrecognized.append)
    # Regex walker sees two parseable decls and one unrecognized
    assert [d.name for d in decls] == ["a", "b"]
    assert len(unrecognized) == 1
    assert "void" in unrecognized[0] or "(*cb)" in unrecognized[0]


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


def test_find_var_for_virtual_rejects_ambiguous_nested_candidate() -> None:
    """virtual-to-var should not present unvalidated nested locals as facts."""
    source = (
        "void f(void) {\n"
        "    int top_a;\n"
        "    if (top_a) {\n"
        "        int nested;\n"
        "    }\n"
        "    int top_b;\n"
        "}\n"
    )
    pre = _make_pre_pass([32, 33, 34])

    assert find_var_for_virtual(source, "f", 34, pre) is None


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
    not (CALIBRATION_FIXTURES / "fn_80247510_pcdump.txt").exists(),
    reason="fn_80247510 fixture not present",
)
def test_calibration_fn_80247510_binds_rumble_and_panel_without_nested_decl_flag() -> None:
    """Feedback regression: fn_80247510 must expose the rumble/panel locals
    without the stale nested-decl red flag that used to make bridge output
    look ambiguous for the wrong reason."""
    pcdump_text = (
        CALIBRATION_FIXTURES / "fn_80247510_pcdump.txt"
    ).read_text()
    source_path = pathlib.Path(__file__).resolve().parents[3] / (
        "src/melee/mn/mnvibration.c"
    )
    source = source_path.read_text()

    fns = parse_pcdump(pcdump_text)
    fn = next((f for f in fns if f.name == "fn_80247510"), None)
    assert fn is not None
    pre = fn.last_precolor_pass()
    assert pre is not None

    bindings, basis = list_bindings_with_basis(source, "fn_80247510", pre)
    assert basis is not None
    assert "nested-decl" not in basis.red_flags
    assert "extra-virtuals" in basis.red_flags

    by_name = {b.var_name: b for b in bindings}
    assert by_name["rumble_setting"].kind == "local"
    assert by_name["rumble_setting"].type_str == "u8"
    assert by_name["rumble_setting"].scope_path == ("fn_80247510",)
    assert by_name["rumble_setting"].confidence != "low-confidence"

    assert by_name["panel_jobj"].kind == "local"
    assert by_name["panel_jobj"].type_str == "HSD_JObj*"
    assert by_name["panel_jobj"].scope_path == ("fn_80247510",)


@pytest.mark.skipif(
    not (CALIBRATION_FIXTURES / "fn_80247510_pcdump.txt").exists(),
    reason="fn_80247510 fixture not present",
)
def test_calibration_fn_80247510_nested_panel_jobj_source_experiment_is_visible() -> None:
    """Feedback regression: if the A-button out-param is tested as
    branch-local source, the bridge must return those nested `panel_jobj`
    bindings instead of reporting the variable as not found."""
    pcdump_text = (
        CALIBRATION_FIXTURES / "fn_80247510_pcdump.txt"
    ).read_text()
    source_path = pathlib.Path(__file__).resolve().parents[3] / (
        "src/melee/mn/mnvibration.c"
    )
    source = source_path.read_text()
    source = source.replace("    HSD_JObj* panel_jobj;\n", "")
    source = source.replace(
        "                    lb_80011E24(jobj, &panel_jobj, 2, -1,\n",
        "                    HSD_JObj* panel_jobj;\n"
        "                    lb_80011E24(jobj, &panel_jobj, 2, -1,\n",
        2,
    )

    fns = parse_pcdump(pcdump_text)
    fn = next((f for f in fns if f.name == "fn_80247510"), None)
    assert fn is not None
    pre = fn.last_precolor_pass()
    assert pre is not None

    bindings, basis = list_bindings_with_basis(source, "fn_80247510", pre)
    assert basis is not None
    assert "nested-decl" not in basis.red_flags

    panel_matches = find_all_virtuals_for_var(bindings, "panel_jobj")
    assert len(panel_matches) == 2
    assert all(b.kind == "local" for b in panel_matches)
    assert all(b.type_str == "HSD_JObj*" for b in panel_matches)
    assert all(len(b.scope_path) > 1 for b in panel_matches)
    assert all(b.confidence == "ambiguous-nested" for b in panel_matches)
    assert [b.decl_line for b in panel_matches] == sorted(
        b.decl_line for b in panel_matches
    )


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


def test_list_bindings_with_basis_surfaces_nested_decls() -> None:
    """A function with a nested block returns LocalDecls in both
    top-level and nested scope_paths via decls_by_scope."""
    from src.mwcc_debug.symbol_bridge import list_bindings_with_basis
    from src.mwcc_debug.parser import Pass, Block, Instruction

    source = (
        "void f(int arg0) {\n"
        "    int outer;\n"
        "    if (arg0) {\n"
        "        int inner;\n"
        "    }\n"
        "}\n"
    )
    # Synthetic pre-pass with destinations: r32 (outer), r33 (inner).
    pp = Pass(name="AFTER PEEPHOLE FORWARD")
    pp.blocks.append(Block(index=0, succ=[], pred=[], labels=[]))
    pp.blocks[0].instructions = [
        Instruction(opcode="li", operands="r32,0", annotations=[], regs=[("r", 32)]),
        Instruction(opcode="li", operands="r33,0", annotations=[], regs=[("r", 33)]),
    ]
    bindings, basis = list_bindings_with_basis(source, "f", pp)

    # Scope grouping was populated by the AST walker.
    scope_groups = list(basis.decls_by_scope.values())
    all_names = {d.name for group in scope_groups for d in group}
    assert "outer" in all_names
    assert "inner" in all_names


def test_bindings_claim_function_top_scope_before_nested_scope() -> None:
    """The cursor model claims all function-top locals before nested locals.

    This pins the Phase-1 bridge contract from the spec: parsed_locals remains
    lexical/source-order, but virtual assignment is partitioned by scope so a
    later function-top declaration is not displaced by an earlier nested decl.
    """
    source = (
        "void f(void) {\n"
        "    int top_a;\n"
        "    if (1) {\n"
        "        int nested;\n"
        "    }\n"
        "    int top_b;\n"
        "}\n"
    )
    pre = _make_pre_pass([32, 33, 34])
    bindings, basis = list_bindings_with_basis(source, "f", pre)
    assert basis is not None

    assert [d.name for d in basis.parsed_locals] == [
        "top_a", "nested", "top_b",
    ]
    assert [d.name for d in basis.decls_by_scope[("f",)]] == [
        "top_a", "top_b",
    ]

    by_name = {b.var_name: b for b in bindings}
    assert by_name["top_a"].virtual == 32
    assert by_name["top_b"].virtual == 33
    assert by_name["nested"].virtual == 34
    assert by_name["nested"].confidence == "ambiguous-nested"
    assert len(by_name["nested"].scope_path) == 2


def test_list_bindings_no_longer_emits_nested_decl_red_flag() -> None:
    """Removing the nested-decl red flag: bindings on a function with
    nested blocks are no longer demoted to low-confidence."""
    from src.mwcc_debug.symbol_bridge import list_bindings_with_basis
    from src.mwcc_debug.parser import Pass, Block, Instruction

    source = (
        "void f(int arg0) {\n"
        "    int outer;\n"
        "    if (arg0) { int inner; }\n"
        "}\n"
    )
    pp = Pass(name="AFTER PEEPHOLE FORWARD")
    pp.blocks.append(Block(index=0, succ=[], pred=[], labels=[]))
    pp.blocks[0].instructions = [
        Instruction(opcode="li", operands="r32,0", annotations=[], regs=[("r", 32)]),
        Instruction(opcode="li", operands="r33,0", annotations=[], regs=[("r", 33)]),
    ]
    _, basis = list_bindings_with_basis(source, "f", pp)
    assert "nested-decl" not in basis.red_flags


def test_nested_block_bindings_default_to_ambiguous_nested() -> None:
    """Bindings whose decl has a non-trivial scope_path get
    confidence='ambiguous-nested' pending validation."""
    from src.mwcc_debug.symbol_bridge import list_bindings_with_basis
    from src.mwcc_debug.parser import Pass, Block, Instruction

    source = (
        "void f(int arg0) {\n"
        "    int outer;\n"
        "    if (arg0) { int inner; }\n"
        "}\n"
    )
    pp = Pass(name="AFTER PEEPHOLE FORWARD")
    pp.blocks.append(Block(index=0, succ=[], pred=[], labels=[]))
    pp.blocks[0].instructions = [
        Instruction(opcode="li", operands="r32,0", annotations=[], regs=[("r", 32)]),
        Instruction(opcode="li", operands="r33,0", annotations=[], regs=[("r", 33)]),
    ]
    bindings, _ = list_bindings_with_basis(source, "f", pp)
    by_name = {b.var_name: b for b in bindings}
    assert by_name["outer"].confidence in {"best-guess", "verified"}
    assert by_name["inner"].confidence == "ambiguous-nested"


def test_extract_function_text_still_importable() -> None:
    """mutators.py imports _extract_function_text. Phase 1 keeps it.
    Signature: returns Optional[tuple[str, str, int]] =
    (params_text, body_text, start_line)."""
    from src.mwcc_debug.symbol_bridge import _extract_function_text
    extracted = _extract_function_text("void f(int x) { int y; }", "f")
    assert extracted is not None
    params, body, start_line = extracted
    assert "int y" in body
    assert params == "int x"
    assert start_line == 1


def test_strip_strings_and_comments_still_importable() -> None:
    """mutators.py uses _strip_strings_and_comments. Phase 1 keeps it."""
    from src.mwcc_debug.symbol_bridge import _strip_strings_and_comments
    out = _strip_strings_and_comments('a = "hello"; /* c */ b = 1;')
    assert '"hello"' not in out
    assert "/* c */" not in out
    assert "b = 1" in out


def test_walk_local_decls_still_importable() -> None:
    """mutators.py uses walk_local_decls. Phase 1 keeps top-level walk."""
    from src.mwcc_debug.symbol_bridge import walk_local_decls
    out = walk_local_decls("{ int x; HSD_JObj* y; }")
    names = {d.name for d in out}
    assert "x" in names
    assert "y" in names


def test_mutators_module_imports_cleanly() -> None:
    """Smoke test: mutators imports the helpers it expects."""
    from src.mwcc_debug import mutators
    # If symbol_bridge stopped exporting required helpers, the import
    # above would have raised. Confirm the module's expected entry
    # points are still callable:
    assert callable(mutators.mutate_type_change)
    assert callable(mutators.mutate_insert_alias_before_use)


def test_function_with_nested_block_is_no_longer_low_confidence() -> None:
    """A function that previously triggered nested-decl red flag and
    got demoted to low-confidence is now best-guess (top-level decls)
    or ambiguous-nested (nested-block decls)."""
    from src.mwcc_debug.symbol_bridge import list_bindings_with_basis
    from src.mwcc_debug.parser import Pass, Block, Instruction

    source = (
        "void f(int arg0) {\n"
        "    int top1;\n"
        "    int top2;\n"
        "    if (arg0) {\n"
        "        int nested1;\n"
        "    }\n"
        "}\n"
    )
    pp = Pass(name="AFTER PEEPHOLE FORWARD")
    pp.blocks.append(Block(index=0, succ=[], pred=[], labels=[]))
    pp.blocks[0].instructions = [
        Instruction(opcode="li", operands="r32,0", annotations=[], regs=[("r", 32)]),
        Instruction(opcode="li", operands="r33,0", annotations=[], regs=[("r", 33)]),
        Instruction(opcode="li", operands="r34,0", annotations=[], regs=[("r", 34)]),
    ]
    bindings, basis = list_bindings_with_basis(source, "f", pp)
    by_name = {b.var_name: b for b in bindings}

    # Top-level decls are no longer demoted.
    assert by_name["top1"].confidence in {"best-guess", "verified"}
    assert by_name["top2"].confidence in {"best-guess", "verified"}
    # Nested decls get the new ambiguous-nested label.
    assert by_name["nested1"].confidence == "ambiguous-nested"
    # Red flag is gone.
    assert "nested-decl" not in basis.red_flags


def test_cli_var_to_virtual_help_shows_scope_and_all_flags() -> None:
    """CLI --help mentions the new flags."""
    import subprocess
    import pathlib
    cwd = pathlib.Path(__file__).parent.parent  # tools/melee-agent
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "inspect", "var-to-virtual", "--help"],
        cwd=cwd, capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0
    assert "--all" in proc.stdout
    assert "--scope" in proc.stdout


def test_cli_virtual_to_var_help_mentions_scope() -> None:
    """CLI --help mentions scope in output description."""
    import subprocess
    import pathlib
    cwd = pathlib.Path(__file__).parent.parent
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "inspect", "virtual-to-var", "--help"],
        cwd=cwd, capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0
    # Verify help text was updated to mention scope (covers user's expectation)
    assert "scope" in proc.stdout.lower()
