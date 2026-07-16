"""RED tests for opcode layout analysis and lifetime proof generation (Task 7).

These must FAIL before implementation exists — import failure, then
attribute/behavior failures after the module skeleton.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))


from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from tools.mwcc_retro import pe
from tools.mwcc_retro.backend_opcode_layout import (
    CUSTOM_OPCODES,
    OPCODE_METADATA_ROW_SIZE,
    OPCODE_METADATA_TABLE,
    RETAIL_GC125N_SHA256,
    VARIADIC_OPCODES,
    analyze_opcode_layouts,
)
from tools.mwcc_retro.x86_cfg import Instruction

COMPILER = REPO / "build/compilers/GC/1.2.5n/mwcceppc.exe"
pytestmark = pytest.mark.skipif(
    not COMPILER.exists(), reason="exact retail GC/1.2.5n compiler is unavailable"
)


def _exact_inputs():
    image = pe.load(
        COMPILER,
        expected_sha256=RETAIL_GC125N_SHA256,
        require_pe32_i386=True,
    )
    addresses = (
        0x004A317B,
        0x004A3213,
        0x004A319B,
        0x004A327D,
        0x004A3540,
        0x004A3538,
        0x004A3530,
        0x004A3527,
        0x0046B4C1,
        0x0046E097,
        0x0046E21A,
        0x0046E30A,
        0x004703F3,
        0x0047094D,
        0x004718DF,
    )
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    instructions = []
    for address in addresses:
        decoded = next(decoder.disasm(image.read(address, 15), address))
        payload = image.read(address, decoded.size)
        instructions.append(
            Instruction(
                address=address,
                size=decoded.size,
                bytes_hex=payload.hex(),
                mnemonic=decoded.mnemonic,
                operands=decoded.op_str,
            )
        )
    return image, SimpleNamespace(instructions=tuple(instructions))


def _inventory():
    image, cfg = _exact_inputs()
    return analyze_opcode_layouts(image, cfg)


def _mutate_va(image, address: int, payload: bytes):
    offset = image.va_to_offset(address)
    assert offset is not None
    data = bytearray(image.data)
    data[offset : offset + len(payload)] = payload
    return replace(image, data=bytes(data))


# ── Opcode layout inventory tests ────────────────────────────────────────


def test_opcode_layout_import():
    """OpcodeLayoutInventory and analyze_opcode_layouts must be importable."""
    from tools.mwcc_retro.backend_opcode_layout import (  # noqa: F401
        OpcodeLayoutInventory,
        analyze_opcode_layouts,
    )


def test_exact_468_opcode_ids_required():
    """Exactly 468 opcode rows (IDs 0..467) must be present."""
    inventory = _inventory()
    assert [row.opcode_id for row in inventory.opcode_rows] == list(range(468))
    assert inventory.opcode_rows[0].mnemonic == "B"
    assert inventory.opcode_rows[-1].mnemonic == "PEXIT"
    assert len({row.mnemonic for row in inventory.opcode_rows}) == 468
    assert len({row.format_string for row in inventory.opcode_rows}) == 103
    assert inventory.metadata_sha256 == (
        "4dfd675154dd9085db6a08dd78c2719a0bf2a1621f71d009791020f6fb76f238"
    )


def test_custom_opcodes_have_constructor_addresses():
    """Custom opcodes 3,4,12,13,15,16,199 must have nonempty constructor
    addresses, not fall through generic parser."""
    inventory = _inventory()
    custom = {row.opcode_id: row for row in inventory.custom_constructors}
    assert set(custom) == CUSTOM_OPCODES
    assert all(row.addresses for row in custom.values())
    assert all(row.instruction_bytes_hex for row in custom.values())
    assert all(
        inventory.opcode_rows[opcode_id].constructor_kind == "custom"
        for opcode_id in CUSTOM_OPCODES
    )


def test_variadic_opcodes_have_count_source():
    """Variadic opcodes 1,19,20,39,54 must bind their runtime count source."""
    inventory = _inventory()
    sources = {row.opcode_id: row for row in inventory.variadic_sources}
    assert set(sources) == VARIADIC_OPCODES
    assert all(
        row.source == "first-vararg-u32-at-generic-constructor"
        for row in sources.values()
    )
    assert sources[39].expansion == "remaining-gpr-count"
    assert sources[54].expansion == "remaining-gpr-count"


def test_v_remaining_and_y_fixed_eight_expansion():
    """'V' expansion consumes remaining operands; 'Y' consumes exactly 8."""
    inventory = _inventory()
    descriptors = [
        descriptor
        for row in inventory.opcode_rows
        for descriptor in row.operand_descriptors
    ]
    remaining = [row for row in descriptors if row.format_code == "V"]
    fixed_eight = [row for row in descriptors if row.format_code == "Y"]
    assert len(remaining) == 2
    assert all(
        row.expansion_kind == "remaining" and row.expansion_count is None
        for row in remaining
    )
    assert len(fixed_eight) == 2
    assert all(
        row.expansion_kind == "fixed" and row.expansion_count == 8
        for row in fixed_eight
    )


def test_gpr_fpr_vector_special_cr_kinds():
    """All five register-domain kinds (GPR/FPR/vector/special/CR) must be
    represented with exact class/form/virtual-kind coupling."""
    inventory = _inventory()
    forms = {
        descriptor.register_form
        for row in inventory.opcode_rows
        for descriptor in row.operand_descriptors
    }
    assert {"gpr", "fpr", "vector", "special", "cr"} <= forms


def test_missing_opcode_id_blocks():
    """A missing opcode ID must prevent proof_ready."""
    image, cfg = _exact_inputs()
    table_offset = image.va_to_offset(OPCODE_METADATA_TABLE)
    assert table_offset is not None
    truncated = replace(
        image,
        data=image.data[: table_offset + 467 * OPCODE_METADATA_ROW_SIZE],
    )
    with pytest.raises(ValueError, match="read is not wholly mapped"):
        analyze_opcode_layouts(truncated, cfg)


def test_duplicate_mnemonic_blocks():
    """Duplicate mnemonic across different opcode IDs must be caught."""
    image, cfg = _exact_inputs()
    first_pointer = image.read(OPCODE_METADATA_TABLE, 4)
    altered = _mutate_va(
        image, OPCODE_METADATA_TABLE + OPCODE_METADATA_ROW_SIZE, first_pointer
    )
    inventory = analyze_opcode_layouts(altered, cfg)
    assert any(row.startswith("duplicate-mnemonic:1:B") for row in inventory.unresolved)
    assert not inventory.proof_ready


def test_unknown_format_code_blocks():
    """An unknown format-code character in a format string must fail."""
    image, cfg = _exact_inputs()
    format_pointer = struct.unpack(
        "<I", image.read(OPCODE_METADATA_TABLE + 4, 4)
    )[0]
    altered = _mutate_va(image, format_pointer, b"q")
    inventory = analyze_opcode_layouts(altered, cfg)
    assert "opcode 0 has non-generic format code 'q'" in inventory.unresolved
    assert not inventory.proof_ready


def test_raw_pointer_row_is_dereferenced_not_decoded_as_inline_text():
    inventory = _inventory()
    row = inventory.opcode_rows[63]
    assert row.mnemonic == "ADDI"
    assert row.format_string == "=r,b,m,p"
    assert row.entry_bytes_hex.startswith(
        row.mnemonic_pointer.to_bytes(4, "little").hex()
    )


def test_metadata_alone_never_promotes_operand_rules():
    inventory = _inventory()
    assert not inventory.proof_ready
    assert "custom-opcode-layouts-unproved" in inventory.unresolved
    assert "stage-specific-register-domains-unproved" in inventory.unresolved
    assert "variadic-count-bounds-unproved" in inventory.unresolved


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
