from pathlib import Path
import pytest
from src.search.statement_move import (
    toplevel_siblings, local_names, escaped_locals, extract_movable_units,
    legal_destinations, generate_statement_hoist_sink_variants)

REPO = Path(__file__).resolve().parents[4]
MNEVENT = REPO / "src/melee/mn/mnevent.c"
FN = "mnEvent_8024D15C"

def _units_and_ctx():
    src = MNEVENT.read_text()
    sibs = toplevel_siblings(src, FN)
    if sibs is None:
        pytest.skip("tree-sitter unavailable")
    locs = local_names(src, FN)
    esc = escaped_locals(src, FN)
    return src, sibs, locs, esc, extract_movable_units(sibs, locs)

@pytest.mark.skipif(not MNEVENT.exists(), reason="mnevent.c absent")
def test_d15c_extracts_pos_x_and_pos_z_but_they_cannot_move():
    src, sibs, locs, esc, units = _units_and_ctx()
    def _unit_on_line(ln):
        return next((u for u in units
                     if sibs[u.index_range[0]].line_range[0] <= ln <= sibs[u.index_range[1]].line_range[1]), None)
    pos_x = _unit_on_line(150)
    pos_z = _unit_on_line(152)
    # non-vacuous: the model DOES identify pos.x and pos.z as movable singletons
    assert pos_x is not None and pos_x.write_base == "pos"
    assert pos_z is not None and pos_z.write_base == "pos"
    assert "translate" in esc                              # &translate is taken
    # ...but both are bracketed by immovable siblings -> ZERO legal destinations
    assert legal_destinations(sibs, pos_x, esc, locs) == []
    assert legal_destinations(sibs, pos_z, esc, locs) == []

@pytest.mark.skipif(not MNEVENT.exists(), reason="mnevent.c absent")
def test_d15c_generates_no_unsafe_move():
    src = MNEVENT.read_text()
    if toplevel_siblings(src, FN) is None:
        pytest.skip("tree-sitter unavailable")
    variants = generate_statement_hoist_sink_variants(src, FN, max_candidates=24)
    # every candidate (if any) MUST keep pos.x before the row->gobjs call block and
    # before the second translate reload at line 166 -> i.e. pos is never relocated.
    for v in variants:
        cs = v["candidate_source"]
        assert cs.index("pos.x = translate.x;") < cs.index("if (row->gobjs[0]")
        assert cs.index("pos.z = translate.z;") < cs.index("if (row->gobjs[0]")
