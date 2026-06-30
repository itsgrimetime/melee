import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from tools.mwcc_retro import versions  # noqa: E402

EXE_11 = REPO / "build/compilers/GC/1.1/mwcceppc.exe"
EXE_125N = REPO / "build/compilers/GC/1.2.5n/mwcceppc.exe"
pytestmark = pytest.mark.skipif(
    not EXE_125N.exists(), reason="compiler binaries not present"
)


def test_detect_build_date_125n():
    assert versions.detect_build_date(EXE_125N) == "Apr 23 2001"


def test_detect_build_date_11():
    assert versions.detect_build_date(EXE_11) == "Feb  7 2001"


def test_identify_125n():
    c = versions.identify(EXE_125N)
    assert c.key == "1.2.5n"
    assert c.build_date == "Apr 23 2001"


def test_125_and_125n_share_descriptor():
    c = versions.identify(EXE_125N)
    assert c.family == "GC/1.2.5"
