import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from tools.mwcc_retro import port_table as pt  # noqa: E402

EXE_11 = REPO / "build/compilers/GC/1.1/mwcceppc.exe"
EXE_125N = REPO / "build/compilers/GC/1.2.5n/mwcceppc.exe"
pytestmark = pytest.mark.skipif(
    not EXE_125N.exists(), reason="compiler binaries not present"
)

NINJA_RANGES = [(0x4ABD9A, 0x4ABDB4), (0x506510, 0x50653E)]


def test_anchor_unique_dumping_function():
    a = pt.string_anchor(EXE_11, EXE_125N, b"Dumping function %s after %s ")
    assert a.confidence == "unique"
    assert a.dst_site - a.src_site == 0x10


def test_anchor_drift_starting_function():
    a = pt.string_anchor(EXE_11, EXE_125N, b"Starting function %s")
    assert a.confidence == "unique"
    assert a.dst_site - a.src_site == 0x10


def test_no_table_entry_overlaps_ninja_patch():
    for site_va in [0x506510 + 4, 0x4ABD9A + 2]:
        assert pt.overlaps_ninja(site_va, NINJA_RANGES)
    assert not pt.overlaps_ninja(0x42CD86, NINJA_RANGES)
