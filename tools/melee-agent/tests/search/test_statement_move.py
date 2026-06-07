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

POS_SRC = '''\
void f(int idx, float spacing)
{
    Vec3 translate;
    Vec3 pos;
    Vec3 result;
    int pad;
    pos.x = translate.x;
    pos.y = spacing;
    pos.z = translate.z;
    pad = idx;
    result.x = pos.x;
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


from src.search.statement_move import extract_movable_units, local_names

def test_local_names_excludes_nested_block_decls():
    src = '''\
void f(int idx)
{
    int top;
    top = idx;
    if (idx != 0) {
        int inner;
        inner = idx;
    }
}
'''
    if toplevel_siblings(src, "f") is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    names = local_names(src, "f")
    assert "top" in names and "idx" in names
    assert "inner" not in names          # nested-block local is NOT a top-level local

def test_extract_units_clusters_aggregate_fields_and_keeps_singletons():
    sibs = toplevel_siblings(POS_SRC, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(POS_SRC, "f")
    units = extract_movable_units(sibs, locs)
    pos_units = [u for u in units if u.write_base == "pos"]
    assert len(pos_units) == 1
    assert pos_units[0].is_cluster is True
    assert pos_units[0].index_range[1] - pos_units[0].index_range[0] == 2  # 3 stmts inclusive
    bases = {u.write_base for u in units}
    assert {"pos", "pad", "result"} <= bases       # pad and result are separate singletons
    # cluster self-reads are NOT subtracted away
    assert pos_units[0].reads == frozenset({"translate", "spacing"})


from src.search.statement_move import legal_destinations

def _idx_of(sibs, needle):
    return next(i for i, s in enumerate(sibs) if needle in s.text)

def test_legal_destinations_raw_dependency_blocks_moving_past_use():
    src = '''\
void f(int idx)
{
    int a;
    int b;
    int c;
    a = idx;
    b = idx;
    c = a;
}
'''
    sibs = toplevel_siblings(src, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(src, "f")
    units = extract_movable_units(sibs, locs)
    a_unit = next(u for u in units if u.write_base == "a")
    legal = legal_destinations(sibs, a_unit, escaped=set(), locals_=locs)
    ci = _idx_of(sibs, "c = a")
    assert ci in legal              # may move down to just BEFORE c (a still precedes its use)
    assert (ci + 1) not in legal    # may NOT move past c (would break c's read of a)
    bi = _idx_of(sibs, "b = idx")
    assert any(d > bi for d in legal)   # proves it crossed the independent `b = idx`

def test_legal_destinations_call_is_unconditional_hard_barrier():
    src = '''\
void f(int a, int b)
{
    int x;
    int y;
    x = a;
    y = b;
    g(b);
}
'''
    sibs = toplevel_siblings(src, "f")
    if sibs is None:
        import pytest; pytest.skip("tree-sitter unavailable")
    locs = local_names(src, "f")
    units = extract_movable_units(sibs, locs)
    x_unit = next(u for u in units if u.write_base == "x")
    legal = legal_destinations(sibs, x_unit, escaped=set(), locals_=locs)
    gi = _idx_of(sibs, "g(b)")
    assert gi in legal              # may move to just before the call (after y = b)
    assert (gi + 1) not in legal    # may NOT cross the call (unconditional barrier)
