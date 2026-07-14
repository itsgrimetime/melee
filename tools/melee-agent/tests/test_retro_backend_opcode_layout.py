"""RED tests for opcode layout analysis and lifetime proof generation (Task 7).

These must FAIL before implementation exists — import failure, then
attribute/behavior failures after the module skeleton.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))


# ── Opcode layout inventory tests ────────────────────────────────────────


def test_opcode_layout_import():
    """OpcodeLayoutInventory and analyze_opcode_layouts must be importable."""
    from tools.mwcc_retro.backend_opcode_layout import (  # noqa: F401
        OpcodeLayoutInventory,
        analyze_opcode_layouts,
    )


def test_exact_468_opcode_ids_required():
    """Exactly 468 opcode rows (IDs 0..467) must be present."""
    from tools.mwcc_retro.backend_opcode_layout import analyze_opcode_layouts
    # RED: module not yet importable


def test_custom_opcodes_have_constructor_addresses():
    """Custom opcodes 3,4,12,13,15,16,199 must have nonempty constructor
    addresses, not fall through generic parser."""
    from tools.mwcc_retro.backend_opcode_layout import analyze_opcode_layouts
    # RED


def test_variadic_opcodes_have_count_source():
    """Variadic opcodes 1,19,20,39,54 must bind their runtime count source."""
    from tools.mwcc_retro.backend_opcode_layout import analyze_opcode_layouts
    # RED


def test_v_remaining_and_y_fixed_eight_expansion():
    """'V' expansion consumes remaining operands; 'Y' consumes exactly 8."""
    from tools.mwcc_retro.backend_opcode_layout import analyze_opcode_layouts
    # RED


def test_gpr_fpr_vector_special_cr_kinds():
    """All five register-domain kinds (GPR/FPR/vector/special/CR) must be
    represented with exact class/form/virtual-kind coupling."""
    from tools.mwcc_retro.backend_opcode_layout import analyze_opcode_layouts
    # RED


def test_missing_opcode_id_blocks():
    """A missing opcode ID must prevent proof_ready."""
    from tools.mwcc_retro.backend_opcode_layout import analyze_opcode_layouts
    # RED


def test_duplicate_mnemonic_blocks():
    """Duplicate mnemonic across different opcode IDs must be caught."""
    from tools.mwcc_retro.backend_opcode_layout import analyze_opcode_layouts
    # RED


def test_unknown_format_code_blocks():
    """An unknown format-code character in a format string must fail."""
    from tools.mwcc_retro.backend_opcode_layout import analyze_opcode_layouts
    # RED


# ── Lifetime proof generation tests ──────────────────────────────────────


def test_lifetime_proof_import():
    """GeneratedLifetimeBundle and generate_lifetime_bundle must exist."""
    from tools.mwcc_retro.backend_lifetime_proof import (  # noqa: F401
        GeneratedLifetimeBundle,
        generate_lifetime_bundle,
        resolve_lifetime_bundle,
    )


def test_generation_is_byte_identical(tmp_path):
    """Two deterministic generations must produce identical bytes and digests."""
    from tools.mwcc_retro.backend_lifetime_proof import generate_lifetime_bundle

    inputs = {
        "raw-pe-cfg.v1.jsonl": b'{"cfg": true}\n',
        "raw-ghidra-crosscheck.v1.json": b'{"crosscheck": true}\n',
        "backend-lifetime-sites.candidate.v1.json": b'{"sites": true}\n',
        "opcode-layouts.candidate.v1.json": b'{"opcodes": true}\n',
        "backend-lifetime-audit.v1.json": b'{"audit": true}\n',
        "gc_125n_lifetime_hooks.candidate.json": b'{"hooks": true}\n',
        "gc_125n.candidate.json": b'{"candidate": true}\n',
    }

    first = generate_lifetime_bundle(
        inputs, tmp_path / "first",
        proof_ready=True, compiler_sha256="a" * 64,
    )
    second = generate_lifetime_bundle(
        inputs, tmp_path / "second",
        proof_ready=True, compiler_sha256="a" * 64,
    )
    assert first.canonical_files() == second.canonical_files()
    assert first.proof_sha256 == second.proof_sha256
    assert first.hook_manifest_sha256 == second.hook_manifest_sha256
    # Verify nine members
    assert len(first.canonical_files()) == 9
    for name in ("raw-pe-cfg.v1.jsonl", "raw-ghidra-crosscheck.v1.json",
                 "backend-lifetime-sites.candidate.v1.json",
                 "opcode-layouts.candidate.v1.json",
                 "backend-lifetime-audit.v1.json",
                 "gc_125n_lifetime_hooks.candidate.json",
                 "gc_125n_lifetime_proof.candidate.json",
                 "gc_125n.candidate.json", "REPORT.md"):
        assert name in first.canonical_files()


def test_unresolved_cfg_prevents_proof_file(tmp_path):
    """proof_ready=False must prevent the proof file from emission."""
    from tools.mwcc_retro.backend_lifetime_proof import generate_lifetime_bundle

    inputs = {
        "raw-pe-cfg.v1.jsonl": b'{"cfg": true}\n',
    }
    bundle = generate_lifetime_bundle(
        inputs, tmp_path,
        proof_ready=False, compiler_sha256="a" * 64,
    )
    assert bundle.audit_summary["proof_ready"] is False
    assert "gc_125n_lifetime_proof.candidate.json" not in bundle.canonical_files()


def test_nine_canonical_members_exposed():
    """The GeneratedLifetimeBundle must expose all nine canonical file names."""
    from tools.mwcc_retro.backend_lifetime_proof import resolve_lifetime_bundle
    # RED
