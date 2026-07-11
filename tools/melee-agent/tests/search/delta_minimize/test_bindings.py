import pytest

from src.search.delta_minimize import DeltaMinimizeError, delta
from src.search.delta_minimize.delta import materialize_mask

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
