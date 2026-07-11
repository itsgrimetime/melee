import pytest

from src.search.delta_minimize import DeltaMinimizeError, delta
from src.search.delta_minimize.bindings import (
    BindingIndex,
    CallBinding,
    FunctionBinding,
    build_binding_index,
    couple_semantic_atoms,
)
from src.search.delta_minimize.delta import (
    DeltaAtom,
    DeltaPatch,
    enumerate_legal_masks,
    materialize_mask,
)

PARAM_LEFT = """\
static int helper(int a, int b) { return a - b; }
int draw(int x, int y) { return helper(x, y); }
"""
PARAM_RIGHT = """\
static int helper(int b, int a) { return a - b; }
int draw(int x, int y) { return helper(y, x); }
"""

DECLARATION_LEFT = """\
static int helper(int a, int b);
static int helper(int a, int b) { return a - b; }
int draw(int x, int y) { return helper(x, y); }
"""
DECLARATION_RIGHT = """\
static int helper(int b, int a);
static int helper(int b, int a) { return a - b; }
int draw(int x, int y) { return helper(y, x); }
"""

POINTER_RETURN_LEFT = """\
static int *helper(int a, int b);
static int *helper(int a, int b) { static int result; result = a - b; return &result; }
int draw(int x, int y) { return *helper(x, y) + 1; }
"""
POINTER_RETURN_RIGHT = """\
static int *helper(int b, int a);
static int *helper(int b, int a) { static int result; result = a - b; return &result; }
int draw(int x, int y) { return *helper(y, x) + 2; }
"""

UNIQUE_RENAME_LEFT = """\
static int helper(int value);
static int helper(int value) { return value + 1; }
int draw(int value) { return helper(value); }
"""
UNIQUE_RENAME_RIGHT = """\
static int assist(int value);
static int assist(int value) { return value + 1; }
int draw(int value) { return assist(value); }
"""

AMBIGUOUS_RENAME_LEFT = """\
static int first(int value) { return value + 1; }
static int second(int value) { return value + 2; }
int draw(int value) { return first(value) + second(value); }
"""
AMBIGUOUS_RENAME_RIGHT = """\
static int third(int value) { return value + 1; }
static int fourth(int value) { return value + 2; }
int draw(int value) { return third(value) + fourth(value); }
"""

MACRO_CALL_LEFT = """\
#define HELPER(a, b) ((a) - (b))
int draw(int x, int y) { return HELPER(x, y); }
"""
MACRO_CALL_RIGHT = """\
#define HELPER(a, b) ((a) - (b))
int draw(int x, int y) { return HELPER(y, x); }
"""

INDIRECT_CALL_LEFT = """\
int sub(int a, int b) { return a - b; }
int draw(int x, int y) { int (*helper)(int, int) = sub; return helper(x, y); }
"""
INDIRECT_CALL_RIGHT = """\
int sub(int a, int b) { return a - b; }
int draw(int x, int y) { int (*helper)(int, int) = sub; return helper(y, x); }
"""

SHADOWED_CALL_LEFT = """\
int helper(int a, int b) { return a - b; }
int other(int a, int b) { return a + b; }
int draw(int x, int y) { int (*helper)(int, int) = other; return helper(x, y); }
"""
SHADOWED_CALL_RIGHT = """\
int helper(int a, int b) { return a - b; }
int other(int a, int b) { return a + b; }
int draw(int x, int y) { int (*helper)(int, int) = other; return helper(y, x); }
"""

DECLARATION_SHADOW_LEFT = """\
int helper(int a, int b) { return a - b; }
int draw(int x, int y) { int local = 1; return helper(x, y) + local; }
"""
DECLARATION_SHADOW_RIGHT = """\
int helper(int a, int b) { return a - b; }
int draw(int x, int y) { int helper = 1; return helper(x, y) + helper; }
"""

FUNCTION_POINTER_OBJECT_LEFT = """\
int sub(int a, int b) { return a - b; }
int other(int a, int b) { return a + b; }
static int (*factory(void))(int, int);
static int (*helper)(int, int) = sub;
int draw(int x, int y) { return helper(x, y); }
"""
FUNCTION_POINTER_OBJECT_RIGHT = """\
int sub(int a, int b) { return a - b; }
int other(int a, int b) { return a + b; }
static int (*factory(void))(int, int);
static int (*helper)(int, int) = other;
int draw(int x, int y) { return helper(x, y); }
"""

CONDITIONAL_LEFT = """\
int helper(int a, int b) { return a - b; }
int draw(int x, int y) {
#if ENABLE_HELPER
    return helper(x, y);
#else
    return x;
#endif
}
"""
CONDITIONAL_RIGHT = """\
int helper(int a, int b) { return a - b; }
int draw(int x, int y) {
#if ENABLE_HELPER
    return helper(y, x);
#else
    return x;
#endif
}
"""


def test_parameter_and_call_reorder_become_one_atom():
    manifest = delta.extract_delta_manifest(PARAM_LEFT, PARAM_RIGHT, function="draw")

    atom = next(a for a in manifest.atoms if "helper parameter reorder" in a.summary)
    assert {patch.anchor_kind for patch in atom.patches} == {
        "parameter_list",
        "argument_list",
    }
    assert materialize_mask(PARAM_LEFT, manifest, 0) == PARAM_LEFT
    assert materialize_mask(PARAM_LEFT, manifest, (1 << len(manifest.atoms)) - 1) == PARAM_RIGHT


def test_declaration_definition_and_calls_reorder_as_one_atom():
    manifest = delta.extract_delta_manifest(DECLARATION_LEFT, DECLARATION_RIGHT, function="draw")

    assert len(manifest.atoms) == 1
    assert {patch.anchor_kind for patch in manifest.atoms[0].patches} == {
        "parameter_list",
        "argument_list",
    }


def test_pointer_return_declaration_definition_and_calls_stay_coupled_for_every_legal_mask():
    manifest = delta.extract_delta_manifest(
        POINTER_RETURN_LEFT,
        POINTER_RETURN_RIGHT,
        function="draw",
    )

    coupled = next(atom for atom in manifest.atoms if "helper parameter reorder" in atom.summary)
    assert [patch.anchor_kind for patch in coupled.patches].count("parameter_list") == 4
    assert [patch.anchor_kind for patch in coupled.patches].count("argument_list") == 2
    assert len(manifest.atoms) == 2

    masks = enumerate_legal_masks(manifest, max_candidates=4)
    assert masks == (0b00, 0b01, 0b10, 0b11)
    assert {materialize_mask(POINTER_RETURN_LEFT, manifest, mask) for mask in masks} >= {
        POINTER_RETURN_LEFT,
        POINTER_RETURN_RIGHT,
    }
    for mask in masks:
        candidate = materialize_mask(POINTER_RETURN_LEFT, manifest, mask)
        helper = build_binding_index(candidate).functions["helper"]
        assert (helper.parameter_names, helper.direct_calls[0].argument_texts) in {
            (("a", "b"), ("x", "y")),
            (("b", "a"), ("y", "x")),
        }


def test_function_pointer_object_is_not_indexed_as_a_function_declaration():
    index = build_binding_index(FUNCTION_POINTER_OBJECT_LEFT)

    assert "helper" not in index.functions
    assert not any(
        blocker.symbol == "factory" and blocker.reason == "function-pointer-object-declaration"
        for blocker in index.blockers
    )


def test_changed_function_pointer_object_with_unchanged_call_fails_closed():
    with pytest.raises(DeltaMinimizeError, match="unsupported-semantic-binding") as exc:
        delta.extract_delta_manifest(
            FUNCTION_POINTER_OBJECT_LEFT,
            FUNCTION_POINTER_OBJECT_RIGHT,
            function="draw",
        )
    blocker = next(
        item for item in exc.value.details["blockers"] if item["reason"] == "function-pointer-object-declaration"
    )
    changed_offset = FUNCTION_POINTER_OBJECT_LEFT.index("sub;", FUNCTION_POINTER_OBJECT_LEFT.index("(*helper)"))
    assert blocker["span"][0] <= changed_offset < blocker["span"][1]


def test_changed_local_declaration_shadowing_unchanged_call_fails_closed():
    with pytest.raises(DeltaMinimizeError, match="unsupported-semantic-binding") as exc:
        delta.extract_delta_manifest(
            DECLARATION_SHADOW_LEFT,
            DECLARATION_SHADOW_RIGHT,
            function="draw",
        )
    blocker = next(item for item in exc.value.details["blockers"] if item["reason"] == "shadowing-declaration")
    changed_offset = DECLARATION_SHADOW_RIGHT.index("helper = 1")
    assert blocker["span"][0] <= changed_offset < blocker["span"][1]


def test_unique_rename_couples_declaration_definition_and_call():
    manifest = delta.extract_delta_manifest(
        UNIQUE_RENAME_LEFT,
        UNIQUE_RENAME_RIGHT,
        function="draw",
    )

    assert len(manifest.atoms) == 1
    assert "helper to assist rename" in manifest.atoms[0].summary
    assert enumerate_legal_masks(manifest, max_candidates=2) == (0, 1)


def test_ambiguous_rename_fails_closed():
    with pytest.raises(DeltaMinimizeError, match="ambiguous-delta-coupling"):
        delta.extract_delta_manifest(
            AMBIGUOUS_RENAME_LEFT,
            AMBIGUOUS_RENAME_RIGHT,
            function="draw",
        )


def test_semantic_union_recomputes_dependency_scc_deterministically():
    left_function = FunctionBinding(
        name="helper",
        definition_span=(0, 5),
        parameter_names=("a", "b"),
        parameter_span=(0, 1),
        direct_calls=(CallBinding("helper", (9, 12), (10, 11), ("x", "y")),),
    )
    right_function = FunctionBinding(
        name="helper",
        definition_span=(0, 5),
        parameter_names=("b", "a"),
        parameter_span=(0, 1),
        direct_calls=(CallBinding("helper", (9, 12), (10, 11), ("y", "x")),),
    )
    left_index = BindingIndex({"helper": left_function}, ())
    right_index = BindingIndex({"helper": right_function}, ())
    atoms = (
        DeltaAtom("parameter", "expression", (DeltaPatch(0, 1, "a", 0, 1, "b", "expression", "p"),), ("bridge",)),
        DeltaAtom("argument", "expression", (DeltaPatch(10, 11, "x", 10, 11, "y", "expression", "a"),)),
        DeltaAtom("bridge", "expression", (DeltaPatch(20, 21, "1", 20, 21, "2", "expression", "b"),), ("argument",)),
    )

    forward = couple_semantic_atoms(left_index, right_index, atoms)
    reverse = couple_semantic_atoms(left_index, right_index, tuple(reversed(atoms)))

    assert forward == reverse
    assert len(forward) == 1
    assert forward[0].requires == ()
    manifest = delta.DeltaManifest("delta-manifest.v1", "draw", "left", "right", forward)
    assert enumerate_legal_masks(manifest, max_candidates=2) == (0, 1)


@pytest.mark.parametrize(
    ("left_directive", "right_directive"),
    [
        ('#include "left.h"', '#include "right.h"'),
        ("#undef LEFT", "#undef RIGHT"),
        ("#pragma pack(4)", "#pragma pack(8)"),
    ],
    ids=("include", "undef", "pragma"),
)
def test_changed_generic_preprocessor_directive_fails_closed(left_directive, right_directive):
    left = f"{left_directive}\nint draw(void) {{ return 1; }}\n"
    right = f"{right_directive}\nint draw(void) {{ return 1; }}\n"

    with pytest.raises(DeltaMinimizeError, match="unsupported-semantic-binding"):
        delta.extract_delta_manifest(left, right, function="draw")


def test_unchanged_generic_preprocessor_directives_do_not_block_coupling():
    directives = '#include "common.h"\n#undef LEGACY\n#pragma pack(4)\n'

    manifest = delta.extract_delta_manifest(
        directives + PARAM_LEFT,
        directives + PARAM_RIGHT,
        function="draw",
    )

    assert any("helper parameter reorder" in atom.summary for atom in manifest.atoms)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (MACRO_CALL_LEFT, MACRO_CALL_RIGHT),
        (INDIRECT_CALL_LEFT, INDIRECT_CALL_RIGHT),
        (SHADOWED_CALL_LEFT, SHADOWED_CALL_RIGHT),
        (CONDITIONAL_LEFT, CONDITIONAL_RIGHT),
    ],
    ids=("macro-like", "indirect", "shadowed", "conditional"),
)
def test_unsupported_changed_binding_fails_closed(left, right):
    with pytest.raises(DeltaMinimizeError, match="unsupported-semantic-binding"):
        delta.extract_delta_manifest(left, right, function="draw")
