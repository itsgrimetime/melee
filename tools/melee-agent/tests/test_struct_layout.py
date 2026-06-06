# tests/test_struct_layout.py
import os
import pytest
from pathlib import Path

from src.common import struct_layout

REPO = Path(__file__).resolve().parents[3]

_LIVE_GUARD = pytest.mark.skipif(
    not os.environ.get("LIVE_9ACC_TESTS"),
    reason="Set LIVE_9ACC_TESTS=1 to run live compiler tests",
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
