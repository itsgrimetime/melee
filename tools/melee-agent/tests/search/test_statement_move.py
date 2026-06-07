import pytest
from src.search.statement_move import toplevel_siblings, SiblingStmt

SRC = '''\
void f(int idx)
{
    int a;
    a = idx;
    if (a != 0) {
        a = a + 1;
    }
    b.x = a;
}
'''

def test_toplevel_siblings_does_not_flatten_nested_blocks():
    sibs = toplevel_siblings(SRC, "f")
    if sibs is None:
        pytest.skip("tree-sitter unavailable")
    kinds = [s.kind for s in sibs]
    # declaration(opaque), simple `a = idx`, opaque if-block, simple `b.x = a`
    assert kinds == ["opaque", "simple", "opaque", "simple"]
    # the inner `a = a + 1;` is NOT a top-level sibling
    assert all("a + 1" not in s.text for s in sibs)
    assert all(s.byte_range[0] < s.byte_range[1] for s in sibs)
    assert [s.byte_range for s in sibs] == sorted(s.byte_range for s in sibs)


from src.search.statement_move import classify_movable, escaped_locals, _mask

def _mk(text, kind="simple"):
    from src.search.statement_move import SiblingStmt
    return SiblingStmt(text=text, byte_range=(0, len(text)), line_range=(1, 1),
                       kind=kind, node_type="expression_statement")

def test_mask_blanks_comments_and_literals_preserving_length():
    m = _mask('a = "x=y&z"; // &q\n')
    assert len(m) == len('a = "x=y&z"; // &q\n')
    assert "&" not in m and "x=y" not in m  # literal + comment content blanked

def test_classify_movable_accepts_simple_local_and_aggregate_field():
    scalar = classify_movable(_mk("a = idx;"), locals_={"a", "idx"})
    assert scalar is not None and scalar.write_base == "a" and scalar.reads == {"idx"}
    field = classify_movable(_mk("pos.x = translate.x;"), locals_={"pos", "translate"})
    assert field is not None and field.write_base == "pos" and field.is_field is True
    assert field.reads == {"translate"}            # field member `x` is NOT a read
    lit = classify_movable(_mk("a = 0.035f;"), locals_={"a"})
    assert lit is not None and lit.reads == set()   # numeric literal is not a read

def test_classify_movable_rejects_calls_pointers_arrays_and_side_effects():
    locs = {"a", "b", "c", "p", "arr", "i", "idx"}
    for bad in ("a = f(idx);", "*p = a;", "a = p->x;", "arr[i] = a;",
                "a += idx;", "a = idx++;", "a = b ? c : a;", "a = b, c;",
                "a = b = c;", "a = (b = c);", "a = b += c;", "a = b == c;",
                "a = b & c;", "a = &b;", "a = *p;"):
        assert classify_movable(_mk(bad), locals_=locs) is None, bad
    assert classify_movable(_mk("g = a;"), locals_={"a"}) is None      # g not local (global)
    assert classify_movable(_mk("if (a) {}", kind="opaque"), locals_=locs) is None

def test_escaped_locals_finds_address_taken():
    src = "void f(){ Vec3 t; g(x, &t); h(& u); k(&(w)); }"
    esc = escaped_locals(src, "f")
    assert {"t", "u", "w"} <= esc
