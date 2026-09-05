import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from tools.mwcc_retro import pe  # noqa: E402

EXE_11 = REPO / "build/compilers/GC/1.1/mwcceppc.exe"
EXE_125N = REPO / "build/compilers/GC/1.2.5n/mwcceppc.exe"
pytestmark = pytest.mark.skipif(
    not EXE_125N.exists(), reason="compiler binaries not present"
)


def test_image_base_and_sections():
    img = pe.load(EXE_125N)
    assert img.image_base == 0x400000
    names = [s.name for s in img.sections]
    assert ".text" in names and ".data" in names


def test_va_offset_roundtrip():
    img = pe.load(EXE_125N)
    off = img.va_to_offset(0x540BBC)
    assert off is not None
    assert img.offset_to_va(off) == 0x540BBC


def test_find_string_va_banner():
    img = pe.load(EXE_125N)
    vas = img.find_string_vas(b"Metrowerks C/C++ Compiler for Embedded PowerPC")
    assert 0x540BBC in vas


def test_push_imm32_sites_unique_for_iro_anchor():
    img = pe.load(EXE_125N)
    svas = img.find_string_vas(b"Dumping function %s after %s ")
    assert len(svas) == 1
    sites = img.push_imm32_sites(svas[0])
    assert len(sites) == 1


def test_data_drift_text_drift_between_versions():
    a = pe.load(EXE_11)
    b = pe.load(EXE_125N)
    sa = a.find_string_vas(b"Dumping function %s after %s ")[0]
    sb = b.find_string_vas(b"Dumping function %s after %s ")[0]
    assert sb - sa == -0x1000
    pa = a.push_imm32_sites(sa)[0]
    pb = b.push_imm32_sites(sb)[0]
    assert pb - pa == 0x10
