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


def test_section_intervals_filters_and_maps(monkeypatch):
    from src.layout.objects import section_intervals
    from src.common.elf_symbols import ObjSymbol
    from pathlib import Path

    symbols = [
        ObjSymbol(name="foo_80380000", section=".data",  shndx=1, value=0x10, size=4,  bind="STB_GLOBAL", type="STT_OBJECT"),
        ObjSymbol(name="@4",          section=".sdata2", shndx=2, value=0x00, size=4,  bind="STB_LOCAL",  type="STT_NOTYPE"),
        ObjSymbol(name="gap_07_pad",  section=".data",   shndx=1, value=0x14, size=8,  bind="STB_LOCAL",  type="STT_OBJECT"),
        ObjSymbol(name="some_fn",     section=".data",   shndx=1, value=0x1C, size=4,  bind="STB_GLOBAL", type="STT_FUNC"),
        ObjSymbol(name="text_sym",    section=".text",   shndx=3, value=0x00, size=8,  bind="STB_GLOBAL", type="STT_FUNC"),
        ObjSymbol(name="abs_sym",     section=None,      shndx=0, value=0x00, size=0,  bind="STB_GLOBAL", type="STT_NOTYPE"),
    ]

    import src.layout.objects as mod
    monkeypatch.setattr(mod, "read_object_symbols", lambda _: symbols)

    result = section_intervals(Path("fake.o"))

    assert set(result.keys()) == {".data", ".sdata2"}
    assert len(result[".data"]) == 1
    iv = result[".data"][0]
    assert iv.name == "foo_80380000"
    assert iv.offset == 0x10
    assert iv.size == 4
    assert iv.binding == "STB_GLOBAL"
    assert iv.anonymous is False

    assert len(result[".sdata2"]) == 1
    anon_iv = result[".sdata2"][0]
    assert anon_iv.name == "@4"
    assert anon_iv.anonymous is True
