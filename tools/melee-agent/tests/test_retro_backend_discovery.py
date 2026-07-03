import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_discovery  # noqa: E402


def test_scan_abs32_operands_finds_data_reference():
    blob = b"\x8b\x0d\x88\x30\x58\x00" + b"\x90" * 8
    refs = backend_discovery.scan_abs32_operands(
        blob, base_va=0x400000, lo=0x580000, hi=0x590000
    )
    assert refs == [{"site_va": 0x400002, "target_va": 0x583088}]


def test_rank_candidate_rejects_ambiguous_refs():
    candidates = [
        {"site_va": 0x1, "target_va": 0x583088},
        {"site_va": 0x2, "target_va": 0x583088},
    ]
    result = backend_discovery.unique_operand_target(candidates, 0x583088)
    assert result is None


def test_rank_candidate_accepts_unique_ref():
    candidates = [{"site_va": 0x1, "target_va": 0x583088}]
    result = backend_discovery.unique_operand_target(candidates, 0x583088)
    assert result == {"site_va": 0x1, "target_va": 0x583088}
