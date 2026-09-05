import pytest

from src.search.statement_move import (
    escaped_locals,
    extract_movable_units,
    generate_statement_hoist_sink_variants,
    legal_destinations,
    local_names,
    toplevel_siblings,
)

TARGET = "target"
SOURCE = """\
typedef struct Vec3 {
    float x;
    float z;
} Vec3;

void escape_translate(Vec3* value);
void opaque_barrier(void);

void target(void)
{
    Vec3 translate;
    Vec3 pos;
    escape_translate(&translate);
    pos.x = translate.x;
    opaque_barrier();
    pos.z = translate.z;
    if (pos.x != 0.0f) {
        opaque_barrier();
    }
}
"""


def _units_and_ctx():
    siblings = toplevel_siblings(SOURCE, TARGET)
    if siblings is None:
        pytest.skip("tree-sitter unavailable")
    locals_ = local_names(SOURCE, TARGET)
    escaped = escaped_locals(SOURCE, TARGET)
    units = extract_movable_units(siblings, locals_)
    return siblings, locals_, escaped, units


def _unit_statement_text(unit) -> str:
    start, end = unit.byte_range
    return SOURCE.encode("utf-8")[start:end].decode("utf-8").strip()


def test_d15c_extracts_pos_x_and_pos_z_but_they_cannot_move():
    siblings, locals_, escaped, units = _units_and_ctx()
    units_by_text = {_unit_statement_text(unit): unit for unit in units}
    pos_x = units_by_text["pos.x = translate.x;"]
    pos_z = units_by_text["pos.z = translate.z;"]

    assert pos_x.write_base == "pos"
    assert pos_z.write_base == "pos"
    assert "translate" in escaped
    assert legal_destinations(siblings, pos_x, escaped, locals_) == []
    assert legal_destinations(siblings, pos_z, escaped, locals_) == []


def test_d15c_generates_no_unsafe_move():
    if toplevel_siblings(SOURCE, TARGET) is None:
        pytest.skip("tree-sitter unavailable")

    variants = generate_statement_hoist_sink_variants(
        SOURCE,
        TARGET,
        max_candidates=24,
    )

    assert variants == []
