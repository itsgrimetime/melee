# tests/test_struct_layout.py
import pytest
from pathlib import Path

from src.common import struct_layout

REPO = Path(__file__).resolve().parents[3]

# The resolver tests compile a real offsetof probe; they run by default when the
# MWCC compiler + wibo are present (as in this worktree), and skip on a bare
# checkout that has not built the compilers yet.
_COMPILER_PRESENT = (
    (REPO / "build/tools/wibo").exists()
    and (REPO / "build/compilers/GC/1.2.5/mwcceppc.exe").exists()
)
_LIVE_GUARD = pytest.mark.skipif(
    not _COMPILER_PRESENT,
    reason="MWCC not built (build/tools/wibo + build/compilers/GC/1.2.5/mwcceppc.exe)",
)


def test_parse_tu_cflags_thpdec():
    spec = struct_layout.parse_tu_cflags(REPO, "extern/dolphin/src/dolphin/thp/THPDec.c")
    assert spec.mw_version == "GC/1.2.5"
    # layout-determining flags must be present
    assert "-align" in spec.cflags and "powerpc" in spec.cflags
    assert "-enum" in spec.cflags and "int" in spec.cflags
    assert "-proc" in spec.cflags and "gekko" in spec.cflags
    assert "-i" in spec.cflags  # include paths preserved


def test_enumerate_field_paths_thpfileinfo():
    paths = struct_layout.enumerate_field_paths(REPO, "THPFileInfo")
    # top-level scalar/pointer/array fields present as offsetof-able paths
    assert "RST" in paths
    assert "nMCU" in paths
    assert "validHuffmanTabs" in paths
    # nested struct array element + sub-field
    assert "components[0].predDC" in paths
    assert "components[1].predDC" in paths
    assert "components[0].DCTableSelector" in paths


def test_parse_c_fields_pointer_detection():
    # The '*' may attach to the type, the name, or stand alone — all are pointers.
    body = """
        u8 plain;
        HSD_GObj* attached_to_type;
        HSD_GObj *attached_to_name;
        HSD_GObj * standalone_star;
        u8* ptr_array[3];
    """
    fields = {f["name"]: f for f in struct_layout._parse_c_fields(body)}
    assert fields["plain"]["is_pointer"] is False
    assert fields["attached_to_type"]["is_pointer"] is True
    assert fields["attached_to_name"]["is_pointer"] is True
    assert fields["standalone_star"]["is_pointer"] is True
    # pointer types resolve to the underlying type name (no stray '*')
    assert fields["attached_to_type"]["type"] == "HSD_GObj"
    assert fields["attached_to_name"]["type"] == "HSD_GObj"
    # pointer array is both a pointer and an array
    assert fields["ptr_array"]["is_pointer"] is True
    assert fields["ptr_array"]["is_array"] is True
    assert fields["ptr_array"]["array_size"] == 3


def test_parse_c_fields_hex_array_size():
    # Hex array sizes must be parsed, not silently dropped (m-5).
    body = "u8 data[0x10]; s32 vals[4];"
    fields = {f["name"]: f for f in struct_layout._parse_c_fields(body)}
    assert fields["data"]["array_size"] == 0x10
    assert fields["vals"]["array_size"] == 4


def test_enumerate_field_paths_pointer_to_struct_is_leaf():
    # HSD_GObj is self-referential: `HSD_GObj* next` etc. A pointer-to-struct
    # field must be emitted as a LEAF, never recursed into (I-1). Otherwise the
    # probe would deref a null pointer: &(((HSD_GObj*)0)->next.classifier).
    paths = struct_layout.enumerate_field_paths(REPO, "HSD_GObj")
    assert "next" in paths  # pointer field present as a leaf
    assert "prev" in paths
    # no path dereferences through the pointer field
    assert not any(p.startswith("next.") for p in paths)
    assert not any(p.startswith("prev.") for p in paths)


@_LIVE_GUARD
@pytest.mark.slow
def test_resolve_layout_thpfileinfo():
    layout = struct_layout.resolve_layout(REPO, "THPFileInfo",
                                          "extern/dolphin/src/dolphin/thp/THPDec.c")
    # field-path -> offset
    assert layout["RST"] == 0x900
    assert layout["nMCU"] == 0x8fc
    assert layout["components[1].predDC"] == 0x86a
    assert layout["components[0].DCTableSelector"] == 0x83c
    # reverse map available
    assert struct_layout.offset_to_field(layout, 0x900) == "RST"


@_LIVE_GUARD
@pytest.mark.slow
def test_verify_offsets():
    ok = struct_layout.verify_offsets(REPO, "THPFileInfo",
        "extern/dolphin/src/dolphin/thp/THPDec.c",
        {"RST": 0x900, "components[0].predDC": 0x83e})
    assert ok is True
    bad = struct_layout.verify_offsets(REPO, "THPFileInfo",
        "extern/dolphin/src/dolphin/thp/THPDec.c", {"RST": 0x999})
    assert bad is False


@_LIVE_GUARD
@pytest.mark.slow
def test_verify_offsets_bogus_path_raises():
    # A typo'd field path must RAISE (not silently return False as if it were
    # an offset mismatch) — otherwise a correctness tool is silent-wrong (I-2).
    with pytest.raises(ValueError):
        struct_layout.verify_offsets(REPO, "THPFileInfo",
            "extern/dolphin/src/dolphin/thp/THPDec.c", {"RSTt": 0x900})
