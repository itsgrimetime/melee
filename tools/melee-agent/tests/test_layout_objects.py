from pathlib import Path
from src.layout.objects import unit_paths, UnitPaths, _is_anonymous, _is_gap


def test_unit_paths_from_relative_c_file():
    up = unit_paths(Path("/repo"), Path("/repo/src/melee/mn/mnevent.c"))
    assert isinstance(up, UnitPaths)
    assert up.obj_path == "melee/mn/mnevent"
    assert up.ref_obj == Path("/repo/build/GALE01/obj/melee/mn/mnevent.o")
    assert up.our_obj == Path("/repo/build/GALE01/src/melee/mn/mnevent.o")


def test_anonymous_and_gap_detection():
    assert _is_gap("gap_07_803EF792_data")
    assert _is_anonymous("@123")
    assert _is_anonymous("...data.0")
    assert not _is_anonymous("mnEvent_803EF758")
    assert not _is_gap("mnEvent_803EF758")
