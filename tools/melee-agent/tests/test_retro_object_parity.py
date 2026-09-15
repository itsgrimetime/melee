import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import object_parity  # noqa: E402


def test_hash_file_records_size_and_sha256(tmp_path):
    p = tmp_path / "a.o"
    p.write_bytes(b"abc")
    h = object_parity.hash_file(p)
    assert h.path == p
    assert h.size == 3
    assert len(h.sha256) == 64
    assert h.sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_compare_objects_reports_match(tmp_path):
    a = tmp_path / "a.o"
    b = tmp_path / "b.o"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    result = object_parity.compare_objects(a, b)
    assert result.matched is True
    assert result.reference.sha256 == result.retro.sha256


def test_compare_objects_reports_mismatch(tmp_path):
    a = tmp_path / "a.o"
    b = tmp_path / "b.o"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    result = object_parity.compare_objects(a, b)
    assert result.matched is False
    assert result.reference.sha256 != result.retro.sha256
