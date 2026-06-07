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
