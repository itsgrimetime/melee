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

ARITY_CHANGE_LEFT = """\
static int helper(int a);
static int helper(int a) { return a; }
int draw(int x) { return helper(x) + 1; }
"""
ARITY_CHANGE_RIGHT = """\
static int helper(int a, int b);
static int helper(int a, int b) { return a; }
int draw(int x) { return helper(x, 1) + 2; }
"""

TYPE_CHANGE_LEFT = """\
static int helper(int a);
static int helper(int a) { return a; }
int draw(int x) { return helper(x); }
"""
TYPE_CHANGE_RIGHT = """\
static int helper(unsigned int a);
static int helper(unsigned int a) { return a; }
int draw(int x) { return helper((unsigned int) x); }
"""

CALL_COUNT_CHANGE_RIGHT = """\
static int helper(int a, int b);
static int helper(int a, int b) { return a; }
int draw(int x) { return helper(x, 1) + helper(x, 2); }
"""

DECLARATION_COUNT_CHANGE_RIGHT = """\
static int helper(int a, int b) { return a; }
int draw(int x) { return helper(x, 1); }
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

NESTED_SHADOW_THEN_OUTER_CALL_LEFT = """\
int helper(int a, int b) { return a - b; }
int draw(int x, int y) {
    { int helper = 0; x += helper; }
    return helper(x, y);
}
"""
NESTED_SHADOW_THEN_OUTER_CALL_RIGHT = """\
int helper(int b, int a) { return a - b; }
int draw(int x, int y) {
    { int helper = 0; x += helper; }
    return helper(y, x);
}
"""

CALL_THEN_SAME_BLOCK_SHADOW_LEFT = """\
int helper(int a, int b) { return a - b; }
int draw(int x, int y) {
    int result = helper(x, y);
    int helper = 0;
    return result + helper;
}
"""
CALL_THEN_SAME_BLOCK_SHADOW_RIGHT = """\
int helper(int b, int a) { return a - b; }
int draw(int x, int y) {
    int result = helper(y, x);
    int helper = 0;
    return result + helper;
}
"""

FOR_SHADOW_THEN_OUTER_CALL_LEFT = """\
int helper(int a, int b) { return a - b; }
int draw(int x, int y) {
    for (int helper = 0; helper < 1; helper++) { x += helper; }
    return helper(x, y);
}
"""
FOR_SHADOW_THEN_OUTER_CALL_RIGHT = """\
int helper(int b, int a) { return a - b; }
int draw(int x, int y) {
    for (int helper = 0; helper < 1; helper++) { x += helper; }
    return helper(y, x);
}
"""

NON_CALL_REFERENCE_PREFIX = """\
int helper(int value) { return value + 1; }
int other(int value) { return value + 2; }
"""

COMPLETE_SIGNATURE_LEFT = """\
static int *helper(int mode);
static int *helper(int mode) { return 0; }
int draw(int x) { return (helper(x) != 0) + 1; }
"""
COMPLETE_SIGNATURE_RIGHT = """\
extern long **helper(unsigned int mode, int flags);
extern long **helper(unsigned int mode, int flags) { return 0; }
int draw(int x) { return (helper((unsigned int) x, 0) != 0) + 2; }
"""

FUNCTION_RETURNING_POINTER_LEFT = """\
static int add(int x, int y) { return x + y; }
static int (*factory(int mode))(int, int);
static int (*factory(int mode))(int, int) { return add; }
int draw(int x) { return factory(x) != 0; }
"""
FUNCTION_RETURNING_POINTER_RIGHT = """\
static int add(int x, int y) { return x + y; }
static int (*factory(int mode, int flags))(int, int);
static int (*factory(int mode, int flags))(int, int) { return add; }
int draw(int x) { return factory(x, 0) != 0; }
"""

ARRAY_BOUND_SCOPE_LEFT = """\
int helper(int a, int b) { return a - b; }
int draw(int x, int y) {
    int helper[helper(x, y)];
    return sizeof(helper);
}
"""
ARRAY_BOUND_SCOPE_RIGHT = """\
int helper(int b, int a) { return a - b; }
int draw(int x, int y) {
    int helper[helper(y, x)];
    return sizeof(helper);
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


def test_arity_change_couples_declaration_definition_and_call_for_every_legal_mask():
    manifest = delta.extract_delta_manifest(
        ARITY_CHANGE_LEFT,
        ARITY_CHANGE_RIGHT,
        function="draw",
    )

    coupled = next(atom for atom in manifest.atoms if "helper signature change" in atom.summary)
    assert [patch.anchor_kind for patch in coupled.patches].count("parameter_list") == 2
    assert [patch.anchor_kind for patch in coupled.patches].count("argument_list") == 1
    assert len(manifest.atoms) == 2

    masks = enumerate_legal_masks(manifest, max_candidates=4)
    candidates = {materialize_mask(ARITY_CHANGE_LEFT, manifest, mask) for mask in masks}
    assert masks == (0b00, 0b01, 0b10, 0b11)
    assert candidates >= {ARITY_CHANGE_LEFT, ARITY_CHANGE_RIGHT}
    for candidate in candidates:
        helper = build_binding_index(candidate).functions["helper"]
        binding_shape = (helper.parameter_names, helper.direct_calls[0].argument_texts)
        assert binding_shape in {
            (("a",), ("x",)),
            (("a", "b"), ("x", "1")),
        }


def test_parameter_type_change_uses_general_signature_coupling():
    manifest = delta.extract_delta_manifest(
        TYPE_CHANGE_LEFT,
        TYPE_CHANGE_RIGHT,
        function="draw",
    )

    assert len(manifest.atoms) == 1
    assert "helper signature change" in manifest.atoms[0].summary
    assert {patch.anchor_kind for patch in manifest.atoms[0].patches} == {
        "parameter_list",
        "argument_list",
    }
    assert enumerate_legal_masks(manifest, max_candidates=2) == (0, 1)
    assert materialize_mask(TYPE_CHANGE_LEFT, manifest, 0) == TYPE_CHANGE_LEFT
    assert materialize_mask(TYPE_CHANGE_LEFT, manifest, 1) == TYPE_CHANGE_RIGHT


def test_complete_signature_spans_exclude_body_and_unrelated_initializer():
    source = """\
static int *helper(int mode), *sentinel = 0;
static int *helper(int mode) { return 0; }
"""

    helper = build_binding_index(source).functions["helper"]

    assert source[slice(*helper.definition_signature_span)].strip() == "static int *helper(int mode)"
    assert tuple(
        (
            source[slice(*signature.shared_prefix_span)],
            source[slice(*signature.declarator_span)],
        )
        for signature in helper.declaration_signatures
    ) == (("static int ", "*helper(int mode)"),)


def test_complete_signature_and_call_changes_couple_without_shape_separation():
    manifest = delta.extract_delta_manifest(
        COMPLETE_SIGNATURE_LEFT,
        COMPLETE_SIGNATURE_RIGHT,
        function="draw",
    )

    coupled = next(atom for atom in manifest.atoms if "helper signature change" in atom.summary)
    assert {patch.anchor_kind for patch in coupled.patches} >= {
        "function_signature",
        "parameter_list",
        "argument_list",
    }
    assert len(manifest.atoms) == 2
    masks = enumerate_legal_masks(manifest, max_candidates=4)
    assert masks == (0b00, 0b01, 0b10, 0b11)
    assert materialize_mask(COMPLETE_SIGNATURE_LEFT, manifest, 0) == COMPLETE_SIGNATURE_LEFT
    assert materialize_mask(COMPLETE_SIGNATURE_LEFT, manifest, 0b11) == COMPLETE_SIGNATURE_RIGHT
    for mask in masks:
        candidate = materialize_mask(COMPLETE_SIGNATURE_LEFT, manifest, mask)
        helper = build_binding_index(candidate).functions["helper"]
        declaration = helper.declaration_signatures[0]
        signatures = (
            (
                candidate[slice(*declaration.shared_prefix_span)] + candidate[slice(*declaration.declarator_span)]
            ).strip(),
            candidate[slice(*helper.definition_signature_span)].strip(),
            helper.direct_calls[0].argument_texts,
        )
        assert signatures in {
            (
                "static int *helper(int mode)",
                "static int *helper(int mode)",
                ("x",),
            ),
            (
                "extern long **helper(unsigned int mode, int flags)",
                "extern long **helper(unsigned int mode, int flags)",
                ("(unsigned int) x", "0"),
            ),
        }


def test_later_prototype_signature_does_not_absorb_preceding_marker():
    left = """\
int marker = 1, helper(int a);
int helper(int a) { return a; }
int draw(int x) { return helper(x); }
"""
    right = """\
int marker = 2, helper(int a, int b);
int helper(int a, int b) { return a; }
int draw(int x) { return helper(x, 0); }
"""

    manifest = delta.extract_delta_manifest(left, right, function="draw")
    masks = enumerate_legal_masks(manifest, max_candidates=4)

    assert masks == (0b00, 0b01, 0b10, 0b11)
    assert materialize_mask(left, manifest, 0) == left
    assert materialize_mask(left, manifest, 0b11) == right
    combinations = set()
    for mask in masks:
        candidate = materialize_mask(left, manifest, mask)
        helper = build_binding_index(candidate).functions["helper"]
        declaration = helper.declaration_signatures[0]
        signature_shape = (
            candidate[slice(*declaration.declarator_span)],
            candidate[slice(*helper.definition_signature_span)].strip(),
            helper.direct_calls[0].argument_texts,
        )
        assert candidate[slice(*declaration.shared_prefix_span)] == "int "
        assert signature_shape in {
            ("helper(int a)", "int helper(int a)", ("x",)),
            (
                "helper(int a, int b)",
                "int helper(int a, int b)",
                ("x", "0"),
            ),
        }
        combinations.add(("marker = 2" in candidate, len(helper.parameter_names)))
    assert combinations == {(False, 1), (False, 2), (True, 1), (True, 2)}


def test_first_prototype_signature_does_not_absorb_following_marker():
    left = """\
int helper(int a), marker = 1;
int helper(int a) { return a; }
int draw(int x) { return helper(x); }
"""
    right = """\
int helper(int a, int b), marker = 2;
int helper(int a, int b) { return a; }
int draw(int x) { return helper(x, 0); }
"""

    manifest = delta.extract_delta_manifest(left, right, function="draw")
    masks = enumerate_legal_masks(manifest, max_candidates=4)

    assert masks == (0b00, 0b01, 0b10, 0b11)
    assert materialize_mask(left, manifest, 0) == left
    assert materialize_mask(left, manifest, 0b11) == right
    combinations = set()
    for mask in masks:
        candidate = materialize_mask(left, manifest, mask)
        helper = build_binding_index(candidate).functions["helper"]
        declaration = helper.declaration_signatures[0]
        assert candidate[slice(*declaration.shared_prefix_span)] == "int "
        assert candidate[slice(*declaration.declarator_span)] in {
            "helper(int a)",
            "helper(int a, int b)",
        }
        assert (helper.parameter_names, helper.direct_calls[0].argument_texts) in {
            (("a",), ("x",)),
            (("a", "b"), ("x", "0")),
        }
        combinations.add(("marker = 2" in candidate, len(helper.parameter_names)))
    assert combinations == {(False, 1), (False, 2), (True, 1), (True, 2)}


def test_prototype_suffix_insertion_at_owned_end_stays_independent():
    left = """\
int helper(int a);
int helper(int a) { return a; }
int draw(int x) { return helper(x); }
"""
    right = """\
int helper(int a, int b), marker = 1;
int helper(int a, int b) { return a; }
int draw(int x) { return helper(x, 0); }
"""

    manifest = delta.extract_delta_manifest(left, right, function="draw")
    masks = enumerate_legal_masks(manifest, max_candidates=4)

    assert len(manifest.atoms) == 2
    assert masks == (0b00, 0b01, 0b10, 0b11)
    assert materialize_mask(left, manifest, 0) == left
    assert materialize_mask(left, manifest, 0b11) == right
    combinations = set()
    for mask in masks:
        candidate = materialize_mask(left, manifest, mask)
        helper = build_binding_index(candidate).functions["helper"]
        combinations.add(("marker = 1" in candidate, len(helper.parameter_names)))
        assert (helper.parameter_names, helper.direct_calls[0].argument_texts) in {
            (("a",), ("x",)),
            (("a", "b"), ("x", "0")),
        }
    assert combinations == {(False, 1), (False, 2), (True, 1), (True, 2)}


@pytest.mark.parametrize(
    ("left_prototype", "right_prototype"),
    [
        (
            "int keep = 0, marker = 1, helper(int a);",
            "int keep = 0, helper(int a);",
        ),
        ("int helper(int a), marker = 1;", "int helper(int a);"),
    ],
    ids=("before-owned-declarator", "after-owned-declarator"),
)
def test_prototype_sibling_removal_stays_independent(left_prototype, right_prototype):
    left = f"{left_prototype}\nint helper(int a) {{ return a; }}\nint draw(int x) {{ return helper(x); }}\n"
    right = f"{right_prototype}\nint helper(int a, int b) {{ return a; }}\nint draw(int x) {{ return helper(x, 0); }}\n"

    manifest = delta.extract_delta_manifest(left, right, function="draw")
    masks = enumerate_legal_masks(manifest, max_candidates=4)

    assert len(manifest.atoms) == 2
    assert masks == (0b00, 0b01, 0b10, 0b11)
    assert materialize_mask(left, manifest, 0) == left
    assert materialize_mask(left, manifest, 0b11) == right
    combinations = {
        (
            "marker = 1" in candidate,
            len(build_binding_index(candidate).functions["helper"].parameter_names),
        )
        for mask in masks
        for candidate in (materialize_mask(left, manifest, mask),)
    }
    assert combinations == {(False, 1), (False, 2), (True, 1), (True, 2)}


def test_owned_start_and_name_interior_insertions_stay_coupled():
    pointer_left = """\
int helper(int a);
int helper(int a) { return 0; }
int draw(int x) { return helper(x) != 0; }
"""
    pointer_right = """\
int *helper(int a);
int *helper(int a) { return 0; }
int draw(int x) { return helper(x) != 0; }
"""
    rename_left = """\
int heper(int a);
int heper(int a) { return a; }
int draw(int x) { return heper(x); }
"""
    rename_right = """\
int helper(int a);
int helper(int a) { return a; }
int draw(int x) { return helper(x); }
"""

    pointer_manifest = delta.extract_delta_manifest(pointer_left, pointer_right, function="draw")
    rename_manifest = delta.extract_delta_manifest(rename_left, rename_right, function="draw")

    pointer_declaration = build_binding_index(pointer_left).functions["helper"].declaration_signatures[0]
    rename_binding = build_binding_index(rename_left).functions["heper"]
    rename_name_spans = (
        rename_binding.definition_name_span,
        *rename_binding.declaration_name_spans,
        *(call.callee_name_span for call in rename_binding.direct_calls),
    )
    assert len(pointer_manifest.atoms) == 1
    assert "helper signature change" in pointer_manifest.atoms[0].summary
    assert any(
        patch.left_start == patch.left_end == pointer_declaration.declarator_span[0]
        for patch in pointer_manifest.atoms[0].patches
    )
    assert len(rename_manifest.atoms) == 1
    assert "heper to helper rename" in rename_manifest.atoms[0].summary
    assert {patch.left_start for patch in rename_manifest.atoms[0].patches} == {
        start + 2 for start, _ in rename_name_spans
    }
    assert all(start < start + 2 < end for start, end in rename_name_spans)
    for manifest, source, endpoint in (
        (pointer_manifest, pointer_left, pointer_right),
        (rename_manifest, rename_left, rename_right),
    ):
        assert enumerate_legal_masks(manifest, max_candidates=2) == (0, 1)
        assert materialize_mask(source, manifest, 0) == source
        assert materialize_mask(source, manifest, 1) == endpoint


def test_parameter_and_call_insertions_before_closing_delimiters_stay_coupled():
    manifest = delta.extract_delta_manifest(ARITY_CHANGE_LEFT, ARITY_CHANGE_RIGHT, function="draw")
    helper = build_binding_index(ARITY_CHANGE_LEFT).functions["helper"]
    coupled = next(atom for atom in manifest.atoms if "helper signature change" in atom.summary)
    owned_spans = (
        helper.parameter_span,
        *helper.declaration_parameter_spans,
        *(call.argument_span for call in helper.direct_calls),
    )

    assert {patch.left_start for patch in coupled.patches} == {end - 1 for _, end in owned_spans}
    assert {patch.anchor_kind for patch in coupled.patches} >= {
        "parameter_list",
        "argument_list",
    }
    assert enumerate_legal_masks(manifest, max_candidates=4) == (0b00, 0b01, 0b10, 0b11)


def test_function_returning_function_pointer_uses_declared_function_parameters():
    index = build_binding_index(FUNCTION_RETURNING_POINTER_LEFT)

    factory = index.functions["factory"]
    assert factory.parameter_names == ("mode",)
    assert factory.parameter_texts == ("int mode",)
    assert not any(blocker.symbol == "factory" for blocker in index.blockers)


def test_function_returning_function_pointer_parameter_is_visible_in_body():
    source = """\
static int add(int x, int y) { return x + y; }
static int (*factory(int add))(int, int) { return add(1, 2); }
"""

    index = build_binding_index(source)

    assert index.functions["factory"].parameter_names == ("add",)
    assert not index.functions["add"].direct_calls
    assert any(blocker.symbol == "add" and blocker.reason == "shadowed-call" for blocker in index.blockers)


def test_function_returning_function_pointer_direct_call_stays_coupled():
    manifest = delta.extract_delta_manifest(
        FUNCTION_RETURNING_POINTER_LEFT,
        FUNCTION_RETURNING_POINTER_RIGHT,
        function="draw",
    )

    assert len(manifest.atoms) == 1
    assert "factory signature change" in manifest.atoms[0].summary
    assert {patch.anchor_kind for patch in manifest.atoms[0].patches} >= {
        "parameter_list",
        "argument_list",
    }
    assert enumerate_legal_masks(manifest, max_candidates=2) == (0, 1)
    assert materialize_mask(FUNCTION_RETURNING_POINTER_LEFT, manifest, 0) == FUNCTION_RETURNING_POINTER_LEFT
    assert materialize_mask(FUNCTION_RETURNING_POINTER_LEFT, manifest, 1) == FUNCTION_RETURNING_POINTER_RIGHT


def test_array_bound_call_precedes_local_declarator_scope():
    manifest = delta.extract_delta_manifest(
        ARRAY_BOUND_SCOPE_LEFT,
        ARRAY_BOUND_SCOPE_RIGHT,
        function="draw",
    )

    assert len(manifest.atoms) == 1
    assert "helper parameter reorder" in manifest.atoms[0].summary
    assert enumerate_legal_masks(manifest, max_candidates=2) == (0, 1)
    assert materialize_mask(ARRAY_BOUND_SCOPE_LEFT, manifest, 0) == ARRAY_BOUND_SCOPE_LEFT
    assert materialize_mask(ARRAY_BOUND_SCOPE_LEFT, manifest, 1) == ARRAY_BOUND_SCOPE_RIGHT


def test_parenthesized_local_declarator_shadows_later_call():
    source = """\
int helper(int a, int b) { return a - b; }
int draw(int x, int y) {
    int (helper);
    return helper(x, y);
}
"""

    index = build_binding_index(source)

    assert not index.functions["helper"].direct_calls
    assert any(blocker.symbol == "helper" and blocker.reason == "shadowed-call" for blocker in index.blockers)


def test_parameter_array_bound_precedes_parameter_scope_but_body_call_is_shadowed():
    source = """\
int helper(int a, int b) { return a - b; }
int draw(int helper[helper(1, 2)]) {
    return helper(3, 4);
}
"""

    index = build_binding_index(source)

    assert [call.argument_texts for call in index.functions["helper"].direct_calls] == [
        ("1", "2"),
    ]
    assert any(blocker.symbol == "helper" and blocker.reason == "shadowed-call" for blocker in index.blockers)


@pytest.mark.parametrize(
    "right",
    [CALL_COUNT_CHANGE_RIGHT, DECLARATION_COUNT_CHANGE_RIGHT],
    ids=("call-count", "declaration-count"),
)
def test_signature_change_count_ambiguity_fails_closed(right):
    with pytest.raises(DeltaMinimizeError, match="ambiguous-delta-coupling"):
        delta.extract_delta_manifest(ARITY_CHANGE_LEFT, right, function="draw")


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (NESTED_SHADOW_THEN_OUTER_CALL_LEFT, NESTED_SHADOW_THEN_OUTER_CALL_RIGHT),
        (CALL_THEN_SAME_BLOCK_SHADOW_LEFT, CALL_THEN_SAME_BLOCK_SHADOW_RIGHT),
        (FOR_SHADOW_THEN_OUTER_CALL_LEFT, FOR_SHADOW_THEN_OUTER_CALL_RIGHT),
    ],
    ids=("completed-nested-block", "later-same-block-declaration", "completed-for-scope"),
)
def test_declarations_not_visible_at_call_do_not_block_coupling(left, right):
    manifest = delta.extract_delta_manifest(left, right, function="draw")

    assert len(manifest.atoms) == 1
    assert "helper parameter reorder" in manifest.atoms[0].summary
    assert enumerate_legal_masks(manifest, max_candidates=2) == (0, 1)
    assert materialize_mask(left, manifest, 0) == left
    assert materialize_mask(left, manifest, 1) == right


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
    blockers = [
        item for item in exc.value.details["blockers"] if item["reason"] == "function-pointer-object-declaration"
    ]
    changed_offset = FUNCTION_POINTER_OBJECT_LEFT.index("sub;", FUNCTION_POINTER_OBJECT_LEFT.index("(*helper)"))
    assert any(blocker["span"][0] <= changed_offset < blocker["span"][1] for blocker in blockers)


@pytest.mark.parametrize(
    "source",
    [
        "int sub(int value) { return value; }\nstatic int (*helper)(int) = sub, unrelated = 1;\n",
        "int sub(int value) { return value; }\nstatic int unrelated = 1, (*helper)(int) = sub;\n",
    ],
    ids=("first-declarator", "later-declarator"),
)
def test_function_pointer_object_blockers_partition_shared_prefix_and_declarator(source):
    index = build_binding_index(source)

    blocker_texts = [
        source[blocker.span[0] : blocker.span[1]]
        for blocker in index.blockers
        if blocker.symbol == "helper" and blocker.reason == "function-pointer-object-declaration"
    ]

    assert blocker_texts == ["static int ", "(*helper)(int) = sub"]


@pytest.mark.parametrize(
    ("left_declaration", "right_declaration"),
    [
        (
            "static int (*helper)(int) = sub, unrelated = 1;",
            "static int (*helper)(int) = sub, unrelated = 2;",
        ),
        (
            "static int unrelated = 1, (*helper)(int) = sub;",
            "static int unrelated = 2, (*helper)(int) = sub;",
        ),
    ],
    ids=("first-declarator", "later-declarator"),
)
def test_function_pointer_object_allows_sibling_declarator_change(left_declaration, right_declaration):
    prefix = "int sub(int value) { return value; }\n"
    left = prefix + left_declaration + "\nint draw(void) { return unrelated; }\n"
    right = prefix + right_declaration + "\nint draw(void) { return unrelated; }\n"

    manifest = delta.extract_delta_manifest(left, right, function="draw")

    assert len(manifest.atoms) == 1
    assert materialize_mask(left, manifest, 0) == left
    assert materialize_mask(left, manifest, 1) == right


@pytest.mark.parametrize(
    ("left_declaration", "right_declaration"),
    [
        (
            "static int (*helper)(int) = sub, unrelated = 1;",
            "static int (*helper)(int) = other, unrelated = 1;",
        ),
        (
            "static int unrelated = 1, (*helper)(int) = sub;",
            "static int unrelated = 1, (*helper)(int) = other;",
        ),
        (
            "static int (*helper)(int) = sub, unrelated = 1;",
            "static int (*helper)(long) = sub, unrelated = 1;",
        ),
        (
            "static int unrelated = 1, (*helper)(int) = sub;",
            "static int unrelated = 1, (*helper)(long) = sub;",
        ),
        (
            "static int (*helper)(int) = sub, unrelated = 1;",
            "extern int (*helper)(int) = sub, unrelated = 1;",
        ),
        (
            "static int unrelated = 1, (*helper)(int) = sub;",
            "extern int unrelated = 1, (*helper)(int) = sub;",
        ),
        (
            "static int (*helper)(int) = sub, unrelated = 1;",
            "static long (*helper)(int) = sub, unrelated = 1;",
        ),
        (
            "static int unrelated = 1, (*helper)(int) = sub;",
            "static long unrelated = 1, (*helper)(int) = sub;",
        ),
    ],
    ids=(
        "first-initializer",
        "later-initializer",
        "first-declarator",
        "later-declarator",
        "first-shared-storage",
        "later-shared-storage",
        "first-shared-type",
        "later-shared-type",
    ),
)
def test_function_pointer_object_blocks_own_declarator_and_shared_prefix_changes(
    left_declaration,
    right_declaration,
):
    prefix = "int sub(int value) { return value; }\nint other(int value) { return value + 1; }\n"
    left = prefix + left_declaration + "\nint draw(int value) { return helper(value); }\n"
    right = prefix + right_declaration + "\nint draw(int value) { return helper(value); }\n"

    with pytest.raises(DeltaMinimizeError, match="unsupported-semantic-binding"):
        delta.extract_delta_manifest(left, right, function="draw")


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


@pytest.mark.parametrize(
    ("left_expression", "right_expression"),
    [
        ("return helper != 0;", "return other != 0;"),
        ("return &helper != 0;", "return &other != 0;"),
        ("sink = helper; return 0;", "sink = other; return 0;"),
    ],
    ids=("comparison", "address", "assignment"),
)
def test_changed_non_call_tu_local_function_reference_fails_closed(left_expression, right_expression):
    left = NON_CALL_REFERENCE_PREFIX + f"int draw(void) {{ {left_expression} }}\n"
    right = NON_CALL_REFERENCE_PREFIX + f"int draw(void) {{ {right_expression} }}\n"

    with pytest.raises(DeltaMinimizeError, match="unsupported-semantic-binding") as exc:
        delta.extract_delta_manifest(left, right, function="draw")

    blockers = [
        blocker for blocker in exc.value.details["blockers"] if blocker["reason"] == "non-call-function-reference"
    ]
    assert blockers
    helper_offset = left.index("helper", left.index("int draw"))
    assert any(blocker["span"][0] <= helper_offset < blocker["span"][1] for blocker in blockers)


def test_changed_non_call_reference_expression_fails_closed():
    left = NON_CALL_REFERENCE_PREFIX + "int draw(void) { return (helper != 0) + 1; }\n"
    right = NON_CALL_REFERENCE_PREFIX + "int draw(void) { return (helper == 0) + 1; }\n"

    with pytest.raises(DeltaMinimizeError, match="unsupported-semantic-binding"):
        delta.extract_delta_manifest(left, right, function="draw")


def test_changed_nested_parenthesized_non_call_reference_expression_fails_closed():
    left = NON_CALL_REFERENCE_PREFIX + "int draw(void) { return (((helper)) != 0) + 1; }\n"
    right = NON_CALL_REFERENCE_PREFIX + "int draw(void) { return (((helper)) == 0) + 1; }\n"

    with pytest.raises(DeltaMinimizeError, match="unsupported-semantic-binding") as exc:
        delta.extract_delta_manifest(left, right, function="draw")

    blocker = next(item for item in exc.value.details["blockers"] if item["reason"] == "non-call-function-reference")
    changed_offset = left.index("!=", left.index("int draw"))
    assert blocker["span"][0] <= changed_offset < blocker["span"][1]


def test_nested_parenthesized_non_call_reference_allows_sibling_expression_change():
    left = NON_CALL_REFERENCE_PREFIX + "int draw(void) { return (((helper)) != 0) + 1; }\n"
    right = NON_CALL_REFERENCE_PREFIX + "int draw(void) { return (((helper)) != 0) + 2; }\n"

    manifest = delta.extract_delta_manifest(left, right, function="draw")

    assert len(manifest.atoms) == 1
    assert materialize_mask(left, manifest, 0) == left
    assert materialize_mask(left, manifest, 1) == right


def test_unchanged_non_call_tu_local_function_reference_is_change_local():
    left = NON_CALL_REFERENCE_PREFIX + "int draw(void) { return (helper != 0) + 1; }\n"
    right = NON_CALL_REFERENCE_PREFIX + "int draw(void) { return (helper != 0) + 2; }\n"

    manifest = delta.extract_delta_manifest(left, right, function="draw")

    assert len(manifest.atoms) == 1
    assert materialize_mask(left, manifest, 0) == left
    assert materialize_mask(left, manifest, 1) == right


def test_unchanged_non_call_reference_does_not_block_changed_function_binding():
    left = """\
int helper(int a, int b) { return a - b; }
int draw(int x, int y) { return (helper != 0) + helper(x, y); }
"""
    right = """\
int helper(int b, int a) { return a - b; }
int draw(int x, int y) { return (helper != 0) + helper(y, x); }
"""

    manifest = delta.extract_delta_manifest(left, right, function="draw")

    assert len(manifest.atoms) == 1
    assert "helper parameter reorder" in manifest.atoms[0].summary
    assert materialize_mask(left, manifest, 0) == left
    assert materialize_mask(left, manifest, 1) == right


def test_unchanged_non_call_reference_blocks_renamed_function_binding():
    left = """\
int helper(int value) { return value + 1; }
int (*fp)(int) = helper;
int draw(int value) { return helper(value); }
"""
    right = """\
int assist(int value) { return value + 1; }
int (*fp)(int) = helper;
int draw(int value) { return assist(value); }
"""

    with pytest.raises(DeltaMinimizeError, match="unsupported-semantic-binding") as exc:
        delta.extract_delta_manifest(left, right, function="draw")

    assert any(
        blocker["symbol"] == "helper" and blocker["reason"] == "non-call-function-reference"
        for blocker in exc.value.details["blockers"]
    )


def test_unique_rename_couples_declaration_definition_and_call():
    manifest = delta.extract_delta_manifest(
        UNIQUE_RENAME_LEFT,
        UNIQUE_RENAME_RIGHT,
        function="draw",
    )

    assert len(manifest.atoms) == 1
    assert "helper to assist rename" in manifest.atoms[0].summary
    assert enumerate_legal_masks(manifest, max_candidates=2) == (0, 1)


def test_later_prototype_rename_uses_exact_name_spans():
    left = """\
int marker = 1, helper(int a);
int helper(int a) { return a; }
int draw(int x) { return helper(x); }
"""
    right = """\
int marker = 2, assist(int a);
int assist(int a) { return a; }
int draw(int x) { return assist(x); }
"""

    manifest = delta.extract_delta_manifest(left, right, function="draw")
    masks = enumerate_legal_masks(manifest, max_candidates=4)

    assert masks == (0b00, 0b01, 0b10, 0b11)
    assert materialize_mask(left, manifest, 0) == left
    assert materialize_mask(left, manifest, 0b11) == right
    combinations = set()
    for mask in masks:
        candidate = materialize_mask(left, manifest, mask)
        name = "assist" if "int assist(int a) {" in candidate else "helper"
        function = build_binding_index(candidate).functions[name]
        assert candidate[slice(*function.definition_name_span)] == name
        assert tuple(candidate[slice(*span)] for span in function.declaration_name_spans) == (name,)
        assert candidate[slice(*function.direct_calls[0].callee_name_span)] == name
        combinations.add(("marker = 2" in candidate, name))
    assert combinations == {
        (False, "helper"),
        (False, "assist"),
        (True, "helper"),
        (True, "assist"),
    }


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
