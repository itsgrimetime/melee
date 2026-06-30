"""Regression tests for de-inline parameter substitution correctness.

Both cases below are wrong-but-compilable expansions that the bare
`re.sub(\\bname\\b, arg)` substitution produced, silently corrupting the
de-inlined source and thus the lever measurement (a false `lever`).
"""
from src.inline_leverage.deinline import build_deinline_patch
from src.inline_leverage.detect import find_call_sites, parse_inline_defs


PAREN_SOURCE = """
static inline int dbl(int a0) {
    return a0 * 2;
}

void target(int x) {
    int y = dbl(x + 1);
}
"""


def test_value_expr_parenthesizes_compound_arg() -> None:
    defs = {item.name: item for item in parse_inline_defs(PAREN_SOURCE, "u.c")}
    calls = find_call_sites(PAREN_SOURCE, "target", "dbl")
    result = build_deinline_patch(PAREN_SOURCE, "target", defs["dbl"], calls)
    assert result.ok
    # Faithful expansion is (x + 1) * 2 — NOT x + 1 * 2 (== x + 2).
    assert "(x + 1) * 2" in (result.new_source or "")


FIELD_SOURCE = """
static inline int get(Foo* obj, int x) {
    return obj->x + x;
}

void target(Foo* p, int n) {
    int y = get(p, n);
}
"""


def test_value_expr_preserves_field_named_like_param() -> None:
    defs = {item.name: item for item in parse_inline_defs(FIELD_SOURCE, "u.c")}
    calls = find_call_sites(FIELD_SOURCE, "target", "get")
    result = build_deinline_patch(FIELD_SOURCE, "target", defs["get"], calls)
    assert result.ok
    # The field access obj->x must stay obj->x (renamed via the obj param to
    # p->x); only the bare param `x` becomes `n`. Never p->n.
    assert "p->x + n" in (result.new_source or "")
    assert "p->n" not in (result.new_source or "")
