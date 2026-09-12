import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_discovery  # noqa: E402
from tools.mwcc_retro import struct_map  # noqa: E402


GC125N_EXE = REPO / "build/compilers/GC/1.2.5n/mwcceppc.exe"


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


def test_gc125n_backend_candidate_report_records_static_text_evidence():
    if not GC125N_EXE.exists():
        import pytest

        pytest.skip(f"{GC125N_EXE} not present")

    report = backend_discovery.build_gc125n_backend_candidate_report(GC125N_EXE)

    assert report["compiler"] == "1.2.5n"
    colorgraph = report["entries"]["colorgraph"]
    assert colorgraph["va"] == 0x4CE2D0
    assert colorgraph["section"] == ".text"
    assert len(colorgraph["first_bytes_hex"]) >= 16
    assert colorgraph["confidence"] == "static-pe-present"
    assert colorgraph["needs_live_invariant"] is True
    assert colorgraph["provenance"]


def test_gc125n_backend_candidate_report_records_static_bss_globals():
    if not GC125N_EXE.exists():
        import pytest

        pytest.skip(f"{GC125N_EXE} not present")

    report = backend_discovery.build_gc125n_backend_candidate_report(GC125N_EXE)

    for key in ("pcbasicblocks", "interference_matrix", "coalesce_alias"):
        entry = report["entries"][key]
        assert entry["section"] == ".bss"
        assert entry["confidence"] == "static-section-present"
        assert entry["needs_live_invariant"] is True
        assert "first_bytes_hex" not in entry


def test_gc125n_backend_candidate_report_keeps_unknowns_unknown():
    if not GC125N_EXE.exists():
        import pytest

        pytest.skip(f"{GC125N_EXE} not present")

    report = backend_discovery.build_gc125n_backend_candidate_report(GC125N_EXE)

    assert report["entries"]["backend_block_list"]["confidence"] == "unknown"
    assert report["entries"]["backend_block_list"]["needs_live_invariant"] is True
    assert report["summary"]["missing"] == 1


def test_gc125n_backend_candidate_report_records_used_vreg_candidates():
    if not GC125N_EXE.exists():
        import pytest

        pytest.skip(f"{GC125N_EXE} not present")

    report = backend_discovery.build_gc125n_backend_candidate_report(GC125N_EXE)

    assert report["entries"]["used_vreg_gpr"] == {
        "va": 0x58846E,
        "provenance": "live probe candidate: rclass 0 n_virtuals counter",
        "section": ".bss",
        "confidence": "static-section-present",
        "needs_live_invariant": True,
    }
    assert report["entries"]["used_vreg_fpr"] == {
        "va": 0x58846C,
        "provenance": "live probe candidate: rclass 1 n_virtuals counter",
        "section": ".bss",
        "confidence": "static-section-present",
        "needs_live_invariant": True,
    }


def test_gc125n_backend_candidate_report_records_frame_and_final_candidates():
    if not GC125N_EXE.exists():
        import pytest

        pytest.skip(f"{GC125N_EXE} not present")

    report = backend_discovery.build_gc125n_backend_candidate_report(GC125N_EXE)

    assert report["entries"]["frame_locals"] == {
        "va": 0x587FB8,
        "provenance": "cadmic GC/1.1 locals list port candidate; live frame sample required",
        "section": ".bss",
        "confidence": "static-section-present",
        "needs_live_invariant": True,
    }
    final_scheduler = report["entries"]["final_scheduler"]
    assert final_scheduler["va"] == 0x435D75
    assert final_scheduler["section"] == ".text"
    assert final_scheduler["confidence"] == "static-pe-present"
    assert final_scheduler["needs_live_invariant"] is True


def test_gc125n_backend_candidate_report_includes_required_keys_and_doc_structs():
    if not GC125N_EXE.exists():
        import pytest

        pytest.skip(f"{GC125N_EXE} not present")

    report = backend_discovery.build_gc125n_backend_candidate_report(GC125N_EXE)

    assert set(struct_map.REQUIRED_GC125N_BACKEND_KEYS) <= set(report["entries"])
    for name, fields in struct_map.REQUIRED_STRUCT_FIELDS.items():
        assert report["structs"][name] == {
            "fields": fields,
            "provenance": "mwcc-debug-docs",
            "confidence": "docs-only",
            "needs_live_invariant": True,
        }


def test_gc125n_backend_candidate_report_does_not_satisfy_live_gate():
    if not GC125N_EXE.exists():
        import pytest

        pytest.skip(f"{GC125N_EXE} not present")

    report = backend_discovery.build_gc125n_backend_candidate_report(GC125N_EXE)

    accepted = struct_map.ACCEPTED_REQUIRED_CONFIDENCE
    for entry in report["entries"].values():
        assert entry["confidence"] not in accepted
    for struct in report["structs"].values():
        assert struct["confidence"] not in accepted
    assert struct_map.validate_required_backend_map(report)
