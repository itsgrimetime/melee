import hashlib
import json
import struct
import sys
from collections import Counter
from dataclasses import fields, replace
from pathlib import Path

import capstone
import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))
from retro_pe_fixture import (  # noqa: E402
    write_synthetic_cfg_pe,
    write_synthetic_dispatch_pe,
)
from tools.mwcc_retro import pe  # noqa: E402
from tools.mwcc_retro.x86_cfg import (  # noqa: E402
    AnalysisLimitError,
    AnalysisLimits,
    AuditAnchor,
    CfgRecoveryError,
    DirectCall,
    JumpTable,
    SeedRecord,
    _materialize_function_entries,
    build_seed_inventory,
    canonical_jsonl_bytes,
    parse_cw_exception_metadata,
    recover_cfg,
    write_jsonl_atomic,
)


@pytest.fixture
def synthetic_cfg_image(tmp_path):
    return load_cfg_image(tmp_path)


def load_cfg_image(tmp_path, mutation=None):
    path = write_synthetic_cfg_pe(tmp_path, mutation=mutation)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return pe.load(
        path,
        expected_sha256=digest,
        require_pe32_i386=True,
    )


def load_cfg_program(tmp_path, program_hex):
    path = write_synthetic_cfg_pe(tmp_path)
    data = bytearray(path.read_bytes())
    program = bytes.fromhex(program_hex)
    assert len(program) <= 0x16
    data[0x20A:0x220] = b"\x90" * 0x16
    data[0x20A : 0x20A + len(program)] = program
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    return pe.load(path, expected_sha256=digest, require_pe32_i386=True)


def decode_one(encoded):
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoder.detail = True
    return decoder, next(
        decoder.disasm(bytes.fromhex(encoded), 0x00401000, count=1)
    )


def audit_anchor(image, address=0x00401070):
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoded = next(decoder.disasm(image.read(address, 15), address, count=1))
    return AuditAnchor(
        name="synthetic-audit-anchor",
        address=address,
        instruction_bytes=bytes(decoded.bytes),
        evidence="synthetic-fixture",
    )


def inventory(image):
    return build_seed_inventory(image, (audit_anchor(image),))


def generous_limits(image):
    defaults = AnalysisLimits.for_image(image)
    return replace(
        defaults,
        max_instructions=512,
        max_blocks=512,
        max_edges=4096,
        max_functions=512,
        max_finite_targets=512,
        max_finite_values=512,
    )


def test_function_entry_provenance_materialization_is_single_pass():
    class SinglePassRecords:
        def __init__(self, records):
            self.records = records
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            if self.iterations != 1:
                raise AssertionError("seed provenance was rescanned")
            yield from self.records

    records = SinglePassRecords(
        (
            SeedRecord(0x20, "zeta", 0x10, "90", "z", True),
            SeedRecord(0x20, "alpha", 0x10, "90", "a", True),
            SeedRecord(0x20, "ignored", 0x10, "90", "n", False),
        )
    )
    entries = _materialize_function_entries((0x30, 0x20), records)
    assert records.iterations == 1
    assert tuple(row.address for row in entries) == (0x20, 0x30)
    assert entries[0].provenance == ("alpha", "zeta")
    assert entries[1].provenance == ("derived-function-target",)


def cw_exception_image(*, mutation=None):
    data = bytearray(0x500)
    text_va = 0x00401000
    rdata_va = 0x00402000
    exc_va = 0x00403000
    data[0x00:0x1C] = bytes.fromhex(
        "8b 44 24 04 8b 48 06 8b 44 24 08 8b 18 8b 70 04 "
        "8b 78 08 8b 68 0c db e3 90 9b ff e1"
    )
    data[0x50] = data[0x60] = data[0x70] = 0xC3

    # One packed complex function record.  Its intentionally unaligned u32
    # fields mirror the retail CodeWarrior layout.
    data[0x100] = 0
    data[0x101:0x105] = (rdata_va + 0x20).to_bytes(4, "little")
    data[0x105:0x107] = (3).to_bytes(2, "little")
    data[0x107:0x10F] = (
        (text_va + 7).to_bytes(4, "little")
        + (rdata_va + 0x20).to_bytes(4, "little")
    )
    data[0x10F:0x117] = (
        (text_va + 0x10).to_bytes(4, "little")
        + (rdata_va + 0x2A).to_bytes(4, "little")
    )
    data[0x117:0x11F] = (
        (text_va + 0x18).to_bytes(4, "little")
        + (rdata_va + 0x34).to_bytes(4, "little")
    )

    # Kinds 1 and 10 are both ten-byte records with a relocated callback at
    # +6.  The high bit terminates each action chain.
    data[0x120:0x12A] = bytes.fromhex(
        "01 80 00 00 00 00 50 10 40 00"
    )
    data[0x12A:0x134] = bytes.fromhex(
        "0a 80 00 00 00 00 60 10 40 00"
    )
    data[0x134:0x142] = bytes.fromhex(
        "10 80 00 00 00 00 70 10 40 00 00 00 00 00"
    )

    data[0x300:0x30C] = (
        text_va.to_bytes(4, "little")
        + rdata_va.to_bytes(4, "little")
        + (0xFFFF_FFFF).to_bytes(4, "little")
    )
    relocations = {
        exc_va,
        exc_va + 4,
        rdata_va + 1,
        rdata_va + 7,
        rdata_va + 11,
        rdata_va + 15,
        rdata_va + 19,
        rdata_va + 23,
        rdata_va + 27,
        rdata_va + 0x26,
        rdata_va + 0x30,
        rdata_va + 0x3A,
    }
    if mutation == "missing-sentinel":
        data[0x308:0x30C] = b"\0" * 4
    elif mutation == "unaligned-action":
        data[0x101:0x105] = (rdata_va + 0x21).to_bytes(4, "little")
    elif mutation == "missing-packed-relocation":
        relocations.remove(rdata_va + 7)
    elif mutation == "incomplete-context-restore":
        data[0x10:0x13] = b"\x90" * 3
    elif mutation is not None:
        raise ValueError(mutation)

    return pe.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe.Section(".text", text_va, 0, 0x100, 0x100, 0x60000020),
            pe.Section(".rdata", rdata_va, 0x100, 0x100, 0x100, 0x40000040),
            pe.Section(".exc", exc_va, 0x300, 0x0C, 0x0C, 0x40000040),
        ),
        imports=(),
        exports=(),
        relocations=tuple(pe.Relocation(address, 3) for address in sorted(relocations)),
        executable_ranges=((text_va, text_va + 0x100),),
    )


def cw_k17_image(
    *,
    clobbered_guard_alias=False,
    clobbered_cleanup_frame=False,
    decoy_builder=False,
    poison_generic_field=False,
    registered_cleanup_with_zero=False,
    unknown_constructor=False,
):
    text_va = 0x00401000
    rdata_va = 0x00402000
    exc_va = 0x00403000
    data = bytearray(0x700)
    text = memoryview(data)[:0x400]

    # Runtime action-kind dispatch: low byte of the packed u16 tag, minus one.
    text[0x000:0x020] = bytes.fromhex(
        "66 8b 11 0f b7 c2 89 d7 25 ff 00 00 00 2d 01 00 "
        "00 00 3d 12 00 00 00 77 07 ff 24 85 00 21 40 00"
    )
    text[0x020] = 0xC3
    text[0x030] = 0xC3
    text[0x040:0x05A] = bytes.fromhex(
        "83 78 08 00 89 c1 74 11 8b 01 85 c0 75 02 "
        "eb 09 89 c8 8b 08 ff 50 08 c3 90 c3"
    )
    if clobbered_guard_alias:
        text[0x045] = 0xD1

    # Builder copies wrapper argument 2 from context+0x1c into cleanup node+8.
    text[0x100:0x108] = bytes.fromhex("8b 58 1c 89 5a 08 c3 90")
    text[0x120:0x12E] = bytes.fromhex(
        "55 89 e5 83 ec 24 8b 45 10 89 44 24 1c 54"
    )
    struct.pack_into("<Bi", text, 0x12E, 0xE8, 0x00401100 - 0x00401133)
    text[0x133] = 0xC3

    # Closed constructor caller supplies one exact destructor.
    text[0x160:0x165] = b"\x68" + (text_va + 0x1A0).to_bytes(4, "little")
    text[0x165:0x169] = bytes.fromhex("6a 00 6a 00")
    struct.pack_into("<Bi", text, 0x169, 0xE8, 0x00401120 - 0x0040116E)
    text[0x16E:0x172] = bytes.fromhex("83 c4 0c c3")
    text[0x1A0] = 0xC3

    seed_addresses = [text_va, text_va + 0x160]
    if unknown_constructor:
        text[0x1C0:0x1C5] = bytes.fromhex("50 6a 00 6a 00")
        struct.pack_into("<Bi", text, 0x1C5, 0xE8, 0x00401120 - 0x004011CA)
        text[0x1CA:0x1CE] = bytes.fromhex("83 c4 0c c3")
        seed_addresses.append(text_va + 0x1C0)
    if decoy_builder:
        text[0x200:0x207] = bytes.fromhex("8b 40 1c 89 42 08 c3")
        seed_addresses.append(text_va + 0x200)
    if poison_generic_field:
        text[0x220:0x224] = bytes.fromhex("89 4a 08 c3")
        seed_addresses.append(text_va + 0x220)
    if registered_cleanup_with_zero:
        text[0x240:0x24C] = bytes.fromhex(
            "55 89 e5 83 ec 04 6a 00 6a 00 6a 00"
        )
        struct.pack_into("<Bi", text, 0x24C, 0xE8, 0x00401120 - 0x00401251)
        text[0x251:0x25D] = (
            bytes.fromhex("83 c4 0c 68")
            + (text_va + 0x1A0).to_bytes(4, "little")
            + bytes.fromhex("6a 00 6a 00")
        )
        struct.pack_into("<Bi", text, 0x25D, 0xE8, 0x00401120 - 0x00401262)
        text[0x262:0x273] = bytes.fromhex(
            "83 c4 0c 89 45 fc 83 7d fc 00 74 03 ff 55 fc c9 c3"
        )
        text[0x271:0x276] = bytes.fromhex("8b 65 f8 c9 c3")
        if clobbered_cleanup_frame:
            text[0x26C:0x278] = bytes.fromhex(
                "74 05 89 c5 ff 55 fc 8b 65 f8 c9 c3"
            )
        seed_addresses.append(text_va + 0x240)

    # One complex function map referring to a terminal kind-17 action.
    data[0x400] = 0
    data[0x401:0x405] = (rdata_va + 0x40).to_bytes(4, "little")
    data[0x405:0x407] = (1).to_bytes(2, "little")
    data[0x407:0x40F] = (
        (text_va + 0x20).to_bytes(4, "little")
        + (rdata_va + 0x40).to_bytes(4, "little")
    )
    data[0x440:0x446] = bytes.fromhex("11 80 e8 ff ff ff")
    for index in range(19):
        target = text_va + 0x40 if index == 16 else text_va + 0x30
        struct.pack_into("<I", data, 0x500 + index * 4, target)
    data[0x600:0x60C] = (
        text_va.to_bytes(4, "little")
        + rdata_va.to_bytes(4, "little")
        + (0xFFFF_FFFF).to_bytes(4, "little")
    )
    relocation_addresses = [
        pe.Relocation(text_va + 0x161, 3),
        pe.Relocation(rdata_va + 1, 3),
        pe.Relocation(rdata_va + 7, 3),
        pe.Relocation(rdata_va + 11, 3),
        pe.Relocation(exc_va, 3),
        pe.Relocation(exc_va + 4, 3),
    ]
    if registered_cleanup_with_zero:
        relocation_addresses.append(pe.Relocation(text_va + 0x255, 3))
    image = pe.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe.Section(".text", text_va, 0, 0x400, 0x400, 0x60000020),
            pe.Section(".rdata", rdata_va, 0x400, 0x200, 0x200, 0x40000040),
            pe.Section(".exc", exc_va, 0x600, 0x0C, 0x0C, 0x40000040),
        ),
        imports=(),
        exports=(),
        relocations=tuple(relocation_addresses),
        executable_ranges=((text_va, text_va + 0x400),),
    )
    return image, tuple(seed_addresses)


def test_strict_cw_exception_parser_accepts_packed_unaligned_fields():
    image = cw_exception_image()
    metadata = parse_cw_exception_metadata(image, generous_limits(image))
    assert metadata is not None
    assert metadata.range_table == ((0x00401000, 0x00402000),)
    assert metadata.landing_sites == (
        0x00401007,
        0x00401010,
        0x00401018,
    )
    assert metadata.action_kinds == (1, 10, 16)
    assert metadata.direct_callbacks == (0x00401050, 0x00401060)
    assert metadata.continuation_targets == ((16, 0x00401070),)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing-sentinel", "sentinel"),
        ("unaligned-action", "action.*aligned"),
        ("missing-packed-relocation", "relocation"),
    ],
)
def test_strict_cw_exception_parser_rejects_malformed_metadata(
    mutation, message
):
    image = cw_exception_image(mutation=mutation)
    with pytest.raises(CfgRecoveryError, match=message):
        parse_cw_exception_metadata(image, generous_limits(image))


@pytest.mark.parametrize(
    "limit_name",
    [
        "max_exception_entries",
        "max_exception_actions",
        "max_exception_landing_sites",
    ],
)
def test_strict_cw_exception_parser_obeys_structural_caps(limit_name):
    image = cw_exception_image()
    limits = replace(generous_limits(image), **{limit_name: 1})
    with pytest.raises(AnalysisLimitError, match=limit_name):
        parse_cw_exception_metadata(image, limits)


def test_cw_packed_continuation_jump_uses_only_registered_kind_targets():
    image = cw_exception_image()
    cfg = recover_cfg(image, (image.entrypoint,), generous_limits(image))
    assert cfg.cw_exception_metadata == parse_cw_exception_metadata(
        image, generous_limits(image)
    )
    assert b'"record_kind":"cw-exception-metadata"' in canonical_jsonl_bytes(
        cfg
    )
    edges = {
        (row.source, row.target, row.flow_kind)
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040101A
    }
    assert edges == {
        (
            0x0040101A,
            0x00401070,
            "indirect-jump-cw-exception-continuation",
        )
    }
    assert not [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x0040101A
    ]


def test_cw_continuation_without_complete_context_restore_stays_blocking():
    image = cw_exception_image(mutation="incomplete-context-restore")
    cfg = recover_cfg(image, (image.entrypoint,), generous_limits(image))
    unresolved = [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x0040101A
    ]
    assert len(unresolved) == 1
    assert "unresolved indirect jump" in unresolved[0].detail


def test_cw_k17_destructor_domain_is_derived_from_constructor_store():
    image, seeds = cw_k17_image()
    cfg = recover_cfg(image, seeds, generous_limits(image))
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401054
        and row.flow_kind == "indirect-call-cw-exception-k17"
    )
    assert edge.target == 0x004011A0
    assert "cw-k17-builder=0x401100" in edge.provenance
    assert "wrapper=0x401120" in edge.provenance


def test_cw_k17_ignores_unlinked_builder_shaped_decoy():
    image, seeds = cw_k17_image(decoy_builder=True)
    cfg = recover_cfg(image, seeds, generous_limits(image))
    edges = [
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401054
        and row.flow_kind == "indirect-call-cw-exception-k17"
    ]
    assert {row.target for row in edges} == {0x004011A0}


def test_cw_k17_clobbered_prebranch_alias_keeps_callback_blocking():
    image, seeds = cw_k17_image(
        clobbered_guard_alias=True,
        poison_generic_field=True,
    )
    cfg = recover_cfg(image, seeds, generous_limits(image))
    unresolved = [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x00401054
    ]
    assert len(unresolved) == 1


def test_cw_k17_unknown_constructor_caller_keeps_callback_blocking():
    image, seeds = cw_k17_image(unknown_constructor=True)
    cfg = recover_cfg(image, seeds, generous_limits(image))
    unresolved = [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x00401054
    ]
    assert len(unresolved) == 1
    assert "unresolved indirect call" in unresolved[0].detail


def test_cw_registered_cleanup_ignores_proven_zero_registration():
    image, seeds = cw_k17_image(registered_cleanup_with_zero=True)
    cfg = recover_cfg(image, seeds, generous_limits(image))
    edges = [
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040126E
        and row.flow_kind == "indirect-call-cw-registered-destructor"
    ]
    assert {row.target for row in edges} == {0x004011A0}


def test_cw_registered_cleanup_rejects_clobbered_frame_base():
    image, seeds = cw_k17_image(
        clobbered_cleanup_frame=True,
        registered_cleanup_with_zero=True,
    )
    cfg = recover_cfg(image, seeds, generous_limits(image))
    unresolved = [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x00401270
    ]
    assert len(unresolved) == 1


def load_dispatch_image(tmp_path, *, entry_count=2, mode="absolute-jump"):
    path = write_synthetic_dispatch_pe(
        tmp_path, entry_count=entry_count, mode=mode
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return pe.load(path, expected_sha256=digest, require_pe32_i386=True)


def dispatch_cfg(tmp_path, *, entry_count=2, mode="absolute-jump"):
    image = load_dispatch_image(
        tmp_path, entry_count=entry_count, mode=mode
    )
    return recover_cfg(
        image, build_seed_inventory(image, ()), generous_limits(image)
    )


def test_guarded_absolute_jump_table_records_complete_provenance(tmp_path):
    cfg = dispatch_cfg(tmp_path)
    table = cfg.jump_table_at(0x0040100B)
    assert isinstance(table, JumpTable)
    assert (
        table.guard_address,
        table.guard_operator,
        table.guard_bound,
        table.base,
        table.entry_width,
        table.index_min,
        table.index_max,
    ) == (0x00401000, "ja", 1, 0x00402200, 4, 0, 1)
    assert table.raw_entries == (0x00401020, 0x00401060)
    assert table.targets == (0x00401020, 0x00401060)
    assert {row.category for row in cfg.seed_inventory.records} >= {
        "jump-table-entry"
    }
    assert not [
        row
        for row in cfg.ownership_diagnostics
        if row.address == table.address and row.kind == "indirect-flow"
    ]


def test_guarded_base_plus_index_jump_table_is_recovered(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="base-index-jump")
    table = cfg.jump_table_at(0x00401010)
    assert table.base == 0x00402200
    assert table.targets == (0x00401020, 0x00401060)


def test_guard_search_skips_non_flag_non_index_register_moves(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="nonadjacent-guard")
    table = cfg.jump_table_at(0x0040100D)
    assert table.guard_address == 0x00401000
    assert (table.index_min, table.index_max) == (0, 1)


def movzx_dispatch_image():
    """Synthetic PE with ``movzx ebx, byte ptr [eax]; call [ebx*4+TABLE]``."""
    import struct
    from tools.mwcc_retro import pe as pe_mod

    TEXT_VA = 0x00401000
    RDATA_VA = 0x00402000
    # Reserve space for 256 table entries (1024 bytes) + text
    data = bytearray(0x600)

    # Entry: movzx ebx, byte ptr [eax] ; call [ebx*4 + TABLE] ; ret
    text = memoryview(data)[:0x100]
    text[0x00:0x03] = bytes.fromhex("0f b6 18")  # movzx ebx, byte ptr [eax]
    text[0x03:0x0A] = bytes.fromhex("ff 14 9d 00 20 40 00")  # call [ebx*4+0x402000]
    text[0x0A] = 0xC3  # ret

    # Fill all 256 dispatch table entries with RVA 0x1020 (type-3 relocation
    # adds image_base to make 0x401020 at load time).
    for i in range(256):
        struct.pack_into("<I", data, 0x100 + i * 4, 0x1020)
    text[0x20] = 0xC3  # target function

    # Add type-3 relocations for each table entry
    relocations = tuple(
        pe_mod.Relocation(RDATA_VA + i * 4, 3) for i in range(256)
    )

    return pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=TEXT_VA,
        directories=(),
        sections=(
            pe_mod.Section(".text", TEXT_VA, 0, 0x100, 0x100, 0x60000020),
            pe_mod.Section(".rdata", RDATA_VA, 0x100, 0x400, 0x400, 0x40000040),
        ),
        imports=(),
        exports=(),
        relocations=relocations,
        executable_ranges=((TEXT_VA, TEXT_VA + 0x100),),
    )


def test_movzx_guard_resolves_indexed_call_table():
    image = movzx_dispatch_image()
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    # Debug: check what happened
    diagnostics_at_call = [
        d for d in cfg.ownership_diagnostics if d.address == 0x00401003
    ]
    assert not diagnostics_at_call, (
        f"unexpected diagnostics at 0x401003: "
        + "; ".join(f"{d.kind}:{d.detail}" for d in diagnostics_at_call)
    )
    table = cfg.jump_table_at(0x00401003)
    assert table.guard_operator == "movzx"
    assert table.guard_bound == 0xFF
    assert (table.index_min, table.index_max) == (0, 0xFF)
    assert set(table.targets) == {0x00401020}
    assert not [
        row
        for row in cfg.ownership_diagnostics
        if row.address == 0x00401003
        and row.kind in {"computed-flow-blocker", "indirect-flow"}
    ]


def test_bounded_registrar_callers_prove_runtime_callback_table(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="registrar-table")
    table = cfg.jump_table_at(0x00401075)
    assert table.guard_operator == "registrar-capacity"
    assert table.guard_bound == 4
    assert table.index_min == table.index_max == 0
    assert table.targets == (0x00401090,)
    assert any(
        row.source == 0x00401075
        and row.target == 0x00401090
        and row.flow_kind == "indirect-call-registrar-table"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_zero_count_table_is_provisionally_unreachable(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="registrar-empty")
    assert not [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x00401075
    ]
    assert any(
        row.kind == "proven-unreachable-control"
        and row.address == 0x00401075
        and "count=0x402300" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_empty_crt_sentinel_table_is_provisionally_unreachable(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="crt-empty-sentinel")
    assert not [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x0040100C
    ]
    assert any(
        row.kind == "proven-unreachable-control"
        and row.address == 0x0040100C
        and "empty .CRT sentinel" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_byte_return_summary_bounds_callback_table(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="byte-return-table")
    table = cfg.jump_table_at(0x00401008)
    assert table.guard_operator == "byte-return-summary"
    assert table.guard_address == 0x00401030
    assert table.guard_bound == 0xFF
    assert (table.index_min, table.index_max) == (0, 0xFF)
    assert set(table.targets) == {0x00401020, 0x00401060}
    assert not [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x00401008
    ]


def test_cdecl_argument_spill_reload_closes_callback_target(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-spill-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040103C
        and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "argument=0" in edge.provenance
    assert not [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x0040103C
    ]


def test_cdecl_argument_is_recovered_from_entry_relative_esp(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-esp-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401030
        and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "logical-stack=+0x4" in edge.provenance


def test_dominating_cdecl_register_definition_crosses_basic_blocks(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-cross-block-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040103B
        and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "dominating-definition=0x401031" in edge.provenance
    assert "argument=0" in edge.provenance


def test_cross_block_register_clobber_keeps_callback_unresolved(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-cross-block-clobber")
    assert any(
        row.address == 0x0040103D and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_recursive_forwarding_does_not_widen_cdecl_callback_domain(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-recursive-callback")
    edges = {
        row.source: row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.flow_kind == "indirect-call-finite-value"
    }
    assert edges[0x00401035] == 0x00401090
    assert edges[0x00401042] == 0x00401090


def test_recursive_unknown_argument_keeps_callback_unresolved(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-recursive-unknown")
    assert any(
        row.address == 0x00401035 and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_complete_cdecl_forwarder_chain_closes_all_five_callbacks(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-forwarder-chain")
    expected_sources = {
        0x00401033,
        0x00401036,
        0x00401039,
        0x0040103C,
        0x0040103F,
    }
    observed = {
        row.source: row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.source in expected_sources
        and row.flow_kind == "indirect-call-finite-value"
    }
    assert observed == {
        source: 0x00401090 for source in expected_sources
    }
    assert not expected_sources & {
        row.address for row in cfg.control_targets.unresolved
    }


def test_cdecl_forwarder_chain_rejects_an_alternate_unknown_caller(tmp_path):
    cfg = dispatch_cfg(
        tmp_path, mode="cdecl-forwarder-chain-alternate-caller"
    )
    assert {
        0x00401033,
        0x00401036,
        0x00401039,
        0x0040103C,
        0x0040103F,
    } <= {row.address for row in cfg.control_targets.unresolved}


def test_cdecl_forwarder_chain_rejects_an_intervening_overwrite(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-forwarder-chain-overwrite")
    assert {
        0x00401036,
        0x00401039,
        0x0040103C,
        0x0040103F,
        0x00401042,
    } <= {row.address for row in cfg.control_targets.unresolved}


def test_cdecl_forwarder_chain_uses_stable_canonical_ebp_arguments(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-forwarder-chain-ebp-complex")
    expected_sources = {
        0x00401033,
        0x00401036,
        0x00401039,
        0x0040103C,
        0x0040103F,
    }
    assert {
        row.source: row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.source in expected_sources
        and row.flow_kind == "indirect-call-finite-value"
    } == {source: 0x00401090 for source in expected_sources}


def test_cdecl_forwarder_chain_rejects_clobbered_frame_pointer(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-forwarder-chain-ebp-clobber")
    assert {
        0x00401033,
        0x00401036,
        0x00401039,
        0x0040103C,
        0x0040103F,
    } <= {row.address for row in cfg.control_targets.unresolved}


def test_two_sided_signed_byte_domain_recovers_relocated_callback_table(
    tmp_path,
):
    cfg = dispatch_cfg(tmp_path, mode="signed-byte-domain-table")
    table = cfg.jump_table_at(0x00401014)
    assert (
        table.guard_address,
        table.guard_operator,
        table.guard_bound,
        table.base,
        table.entry_width,
        table.index_min,
        table.index_max,
    ) == (0x00401005, "signed-memory-range", 16, 0x00402300, 4, 0, 15)
    assert table.raw_entries == (0x00401090,) * 16
    assert table.targets == (0x00401090,) * 16
    assert not [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x00401014
    ]


def test_signed_byte_domain_accepts_exact_push_and_spill_shape(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="signed-byte-domain-exact-spill")
    table = cfg.jump_table_at(0x0040101B)
    assert (
        table.guard_address,
        table.guard_operator,
        table.guard_bound,
        table.index_min,
        table.index_max,
    ) == (0x00401005, "signed-memory-range", 16, 0, 15)
    assert table.targets == (0x00401090,) * 16


@pytest.mark.parametrize(
    "mode",
    (
        "signed-byte-domain-one-sided",
        "signed-byte-domain-admits-sixteen",
        "signed-byte-domain-bad-slot",
        "signed-byte-domain-relocations-only",
    ),
)
def test_signed_byte_table_without_a_closed_exact_domain_stays_blocking(
    tmp_path, mode
):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert any(
        row.address == 0x00401014
        and row.kind == "computed-flow-blocker"
        for row in cfg.control_targets.unresolved
    )
    with pytest.raises(KeyError):
        cfg.jump_table_at(0x00401014)


def test_zero_domain_and_nonzero_guard_prove_transfer_unreachable(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="zero-guarded-callback")
    assert not [
        row for row in cfg.control_targets.unresolved
        if row.address == 0x00401039
    ]
    assert any(
        row.address == 0x00401039
        and row.kind == "proven-unreachable-control"
        and "zero-domain contradicts nonzero guard" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_zero_domain_without_guard_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="zero-unguarded-callback")
    assert any(
        row.address == 0x00401035 and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_guarded_zero_context_preserves_nonzero_callback_context(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="mixed-zero-nonzero-guarded-callback")
    edges = {
        row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401039
        and row.flow_kind == "indirect-call-finite-value"
    }
    assert edges == {0x00401090}
    assert any(
        row.address == 0x00401039
        and row.kind == "proven-unreachable-control-context"
        and "zero context contradicts nonzero guard" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_historical_control_diagnostics_fixture_is_frozen_canonical():
    path = (
        Path(__file__).parent
        / "fixtures/retro/gc125n-historical-control-diagnostics.v1.json"
    )
    payload = path.read_bytes()
    rows = json.loads(payload)
    assert len(rows) == 705
    assert hashlib.sha256(payload).hexdigest() == (
        "391d34a85b99f16c1455e473978af7ca2234ba7aaee4787c6c24c5710d6fd3d0"
    )
    assert Counter(row["kind"] for row in rows) == {
        "computed-flow-blocker": 290,
        "indirect-flow": 415,
    }


def test_guarded_callback_table_adds_finite_function_seeds(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="callback-table")
    table = cfg.jump_table_at(0x0040100B)
    assert table.flow_kind == "call"
    assert {(edge.target, edge.kind) for edge in cfg.edges if edge.source == table.address} >= {
        (0x00401020, "indirect-call-table"),
        (0x00401060, "indirect-call-table"),
    }
    callback_seeds = [
        row
        for row in cfg.seed_inventory.records
        if row.category == "callback-table-entry"
    ]
    assert {row.address for row in callback_seeds} == {
        0x00401020,
        0x00401060,
    }


def test_zero_guard_remains_proof_across_an_unchanged_backedge(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="zero-loop-guarded-callback")
    assert not [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x00401039
    ]
    assert any(
        row.address == 0x00401039
        and row.kind == "proven-unreachable-control"
        and "zero-domain contradicts nonzero guard" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_zero_guard_backedge_clobber_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="zero-loop-clobbered-callback")
    assert any(
        row.address == 0x00401039 and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_zero_guard_accepts_a_proven_noreturn_zero_path(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="noreturn-guarded-callback")
    assert not [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x0040103E
    ]
    assert any(
        row.address == 0x0040103E
        and row.kind == "proven-unreachable-control"
        and "zero-domain contradicts nonzero guard" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_zero_guard_returning_zero_path_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="returning-guarded-callback")
    assert any(
        row.address == 0x0040103E and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_zero_guard_search_covers_a_large_bounded_function(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="zero-distant-guarded-callback")
    assert not [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x004010D0
    ]
    assert any(
        row.address == 0x004010D0
        and row.kind == "proven-unreachable-control"
        for row in cfg.ownership_diagnostics
    )


def test_distant_zero_callback_without_guard_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="zero-distant-unguarded-callback")
    assert any(
        row.address == 0x004010D0 and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_closed_constructor_field_domain_proves_vtable_callback(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="constructor-field-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040100B
        and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "dynamic-field=+0x104" in edge.provenance


def test_constructor_field_domain_ignores_stack_offset_decoy(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="constructor-field-stack-decoy")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401016
        and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "dynamic-field=+0x104" in edge.provenance


def test_constructor_field_provenance_is_stable_as_finite_writers_grow(
    tmp_path,
):
    cfg = dispatch_cfg(tmp_path, mode="constructor-field-late-finite-write")
    edges = {
        row.target: row.provenance
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040100B
        and row.flow_kind == "indirect-call-finite-value"
    }
    assert set(edges) == {0x00401090, 0x004010A0}
    assert all("dynamic-field=+0x104" in row for row in edges.values())


def test_unknown_constructor_field_write_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="constructor-field-unknown-write")
    assert any(
        row.address == 0x0040100B and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_validated_constructor_descriptor_proves_field_callback(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="validated-constructor-descriptor")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401064
        and row.flow_kind == "indirect-call-constructor-descriptor"
    )
    assert edge.target == 0x004010F0
    assert "identity-validator=0x401080" in edge.provenance
    assert "constructor=0x4010a0" in edge.provenance
    assert "descriptor-field=+0x34" in edge.provenance
    assert not [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x00401064
    ]


def test_constructor_descriptor_validator_follows_retail_guard_arms(
    tmp_path,
):
    cfg = dispatch_cfg(
        tmp_path,
        mode="validated-constructor-descriptor-retail-guard-arms",
    )
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040106C
        and row.flow_kind == "indirect-call-constructor-descriptor"
    )
    assert edge.target == 0x004010F0


def test_constructor_descriptor_follows_wrapper_and_global_object_origin(
    tmp_path,
):
    cfg = dispatch_cfg(
        tmp_path,
        mode="validated-constructor-descriptor-wrapper-global",
    )
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401066
        and row.flow_kind == "indirect-call-constructor-descriptor"
    )
    assert edge.target == 0x004010F0
    assert "constructor=0x4010a0" in edge.provenance
    assert not [
        row
        for row in cfg.control_targets.unresolved
        if row.address == 0x00401066
    ]


def test_constructor_descriptor_filters_closed_tag_disjoint_producer(
    tmp_path,
):
    cfg = dispatch_cfg(
        tmp_path, mode="validated-constructor-descriptor-multi-tag"
    )
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401074
        and row.flow_kind == "indirect-call-constructor-descriptor"
    )
    assert edge.target == 0x004010F0
    assert "rejected-tag=0x436f6d70" in edge.provenance


@pytest.mark.parametrize(
    "mode",
    (
        "validated-constructor-descriptor-multi-tag-same-tag",
        "validated-constructor-descriptor-multi-tag-unknown-tag",
    ),
)
def test_constructor_descriptor_rejects_non_disjoint_producer(
    tmp_path, mode
):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert any(
        row.address == 0x00401074
        and row.kind in {"indirect-flow", "computed-flow-blocker"}
        for row in cfg.control_targets.unresolved
    )
    assert not any(
        row.source == 0x00401074
        and row.flow_kind == "indirect-call-constructor-descriptor"
        for row in cfg.control_targets.finite_internal_edges
    )


@pytest.mark.parametrize(
    "mode",
    (
        "validated-constructor-descriptor-wrapper-global-alternate-writer",
        "validated-constructor-descriptor-wrapper-global-incomplete-domain",
    ),
)
def test_constructor_descriptor_rejects_open_global_object_origin(
    tmp_path, mode
):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert any(
        row.address == 0x00401066
        and row.kind in {"indirect-flow", "computed-flow-blocker"}
        for row in cfg.control_targets.unresolved
    )
    assert not any(
        row.source == 0x00401066
        and row.flow_kind == "indirect-call-constructor-descriptor"
        for row in cfg.control_targets.finite_internal_edges
    )


@pytest.mark.parametrize(
    "mode",
    (
        "validated-constructor-descriptor-different-writer",
        "validated-constructor-descriptor-alternate-producer",
        "validated-constructor-descriptor-changed-descriptor",
        "validated-constructor-descriptor-tag-only",
        "validated-constructor-descriptor-incomplete-initializer-domain",
    ),
)
def test_constructor_descriptor_requires_complete_object_provenance(
    tmp_path, mode
):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert any(
        row.address == 0x00401064
        and row.kind in {"indirect-flow", "computed-flow-blocker"}
        for row in cfg.control_targets.unresolved
    )
    assert not any(
        row.source == 0x00401064
        and row.flow_kind == "indirect-call-constructor-descriptor"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_registered_copied_descriptor_proves_callback(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040103E
        and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x004010F0
    assert "copied-descriptor-component=0" in edge.provenance


def test_unknown_copied_descriptor_source_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-unknown-source")
    assert any(
        row.address == 0x0040103E and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_copied_descriptor_domain_does_not_cover_unproven_objects(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-unproven-object")
    assert any(
        row.address == 0x0040103E and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_fresh_copied_descriptor_origin_survives_argument_forwarding(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-forwarded-object")
    assert any(
        row.source == 0x0040103E
        and row.target == 0x004010F0
        and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_copied_descriptor_slot_zero_hypothesis_closes_after_replay(tmp_path):
    cfg = dispatch_cfg(
        tmp_path, mode="copied-descriptor-slot-zero-hypothesis"
    )
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040103D
        and row.flow_kind
        == "indirect-call-copied-descriptor-slot-zero"
    )
    assert edge.target == 0x004010F0
    assert "fixed-nine-dword-copy" in edge.provenance


@pytest.mark.parametrize(
    "mode",
    (
        "copied-descriptor-slot-zero-hidden-caller",
        "copied-descriptor-slot-zero-unrelocated-record",
    ),
)
def test_copied_descriptor_slot_zero_hypothesis_is_fail_closed(
    tmp_path, mode
):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert any(
        row.address == 0x0040103D and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )
    assert not any(
        row.source == 0x0040103D
        and row.flow_kind
        == "indirect-call-copied-descriptor-slot-zero"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_hypothesis_replay_discovers_second_order_object_table(tmp_path):
    cfg = dispatch_cfg(
        tmp_path, mode="copied-descriptor-object-hypothesis-chain"
    )
    assert any(
        row.address == 0x00401048
        and row.category == "copied-descriptor-callback-entry"
        for row in cfg.seed_inventory.records
    )
    assert any(
        row.address == 0x004010F0
        and row.category == "object-callback-table-entry"
        for row in cfg.seed_inventory.records
    )
    assert not any(
        row.address == 0x00401058
        for row in cfg.control_targets.unresolved
    )


def test_six_movsd_decoy_without_constructor_contract_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-six-movsd-decoy")
    assert any(
        row.address == 0x0040103E and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_cross_block_callback_clobber_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-cross-block-clobber")
    assert any(
        row.address == 0x00401040 and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_bounded_affine_descriptor_array_proves_every_callback(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="bounded-descriptor-array")
    assert {
        row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401009
        and row.flow_kind == "indirect-call-finite-value"
    } == {0x00401090, 0x004010A0, 0x004010B0}


def test_unbounded_affine_descriptor_array_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="unbounded-descriptor-array")
    assert any(
        row.address == 0x00401009 and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_nested_bounded_affine_descriptor_array_uses_innermost_loop(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="nested-bounded-descriptor-array")
    assert {
        row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040100D
        and row.flow_kind == "indirect-call-finite-value"
    } == {0x00401090, 0x004010A0, 0x004010B0}


def test_nested_affine_outer_clobber_remains_blocking(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="nested-bounded-descriptor-array-with-outer-clobber",
    )
    assert any(
        row.address == 0x0040100D and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_nested_affine_ignores_clobber_on_non_backedge_exit(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="nested-bounded-descriptor-array-dead-end-clobber",
    )
    assert {
        row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040100D
        and row.flow_kind == "indirect-call-finite-value"
    } == {0x00401090, 0x004010A0, 0x004010B0}


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("missing-guard", "finite dominating guard"),
        ("conflicting-width", "entry width conflicts"),
        ("unmapped-entry", "jump-table entry is not wholly mapped"),
        ("target-outside-text", "jump-table target is not executable"),
    ],
)
def test_computed_table_failures_remain_explicit_blockers(
    tmp_path, mode, message
):
    image = load_dispatch_image(tmp_path, mode=mode)
    cfg = recover_cfg(
        image, build_seed_inventory(image, ()), generous_limits(image)
    )
    assert any(
        row.kind == "computed-flow-blocker" and message in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_guarded_468_way_dispatch_is_recovered(tmp_path):
    cfg = dispatch_cfg(tmp_path, entry_count=468)
    table = cfg.jump_table_at(0x0040100B)
    assert table.index_min == 0
    assert table.index_max == 467
    assert len(table.raw_entries) == 468
    assert len(table.targets) == 468
    assert table.base == 0x00402200


def test_structural_default_limits_derive_from_executable_raw_bytes(
    synthetic_cfg_image,
):
    limits = AnalysisLimits.for_image(synthetic_cfg_image)
    assert limits.max_instructions == 0x88
    assert limits.max_blocks == 0x88
    assert limits.max_edges == 8 * 0x88
    assert limits.max_jump_tables == 65_536
    assert limits.max_jump_table_entries == 524_288
    assert limits.max_functions == 65_536
    assert limits.max_finite_targets == 65_536
    assert limits.max_finite_values == 8_192
    assert limits.max_states_per_block == 256
    assert limits.max_contexts_per_entry == 256
    assert limits.max_scc_iterations == 65_536
    assert limits.max_summary_iterations == 65_536
    assert limits.max_fixpoint_updates == 8_000_000


@pytest.mark.parametrize(
    "cap_name",
    [field.name for field in fields(AnalysisLimits)],
)
@pytest.mark.parametrize("delta", [0, 1], ids=["equal", "over"])
def test_every_analysis_cap_fails_closed_at_equality_and_over(
    synthetic_cfg_image, cap_name, delta
):
    limits = generous_limits(synthetic_cfg_image)
    configured = getattr(limits, cap_name)
    with pytest.raises(AnalysisLimitError) as raised:
        limits.check(cap_name, configured + delta)
    assert raised.value.limit_name == cap_name
    assert raised.value.configured == configured
    assert raised.value.observed == configured + delta
    assert f"configured={configured}" in str(raised.value)
    assert f"observed={configured + delta}" in str(raised.value)


def test_seed_order_cannot_change_raw_cfg(synthetic_cfg_image):
    limits = generous_limits(synthetic_cfg_image)
    a = recover_cfg(
        synthetic_cfg_image,
        (0x00401000, 0x00401040, 0x00401070),
        limits,
    )
    b = recover_cfg(
        synthetic_cfg_image,
        (0x00401070, 0x00401040, 0x00401000),
        limits,
    )
    assert a.to_dict() == b.to_dict()


def test_direct_cfg_owns_exact_instructions_blocks_edges_and_calls(
    synthetic_cfg_image,
):
    cfg = recover_cfg(
        synthetic_cfg_image,
        inventory(synthetic_cfg_image),
        generous_limits(synthetic_cfg_image),
    )
    assert (0x00401003, 0x00401040) in {
        (call.address, call.target) for call in cfg.direct_calls
    }
    assert (0x0040104B, 0x00401060) in {
        (call.address, call.target) for call in cfg.direct_calls
    }
    assert any(
        edge.source == 0x00401008
        and edge.target == 0x00401020
        and edge.kind == "conditional-branch"
        for edge in cfg.edges
    )
    call_block = next(block for block in cfg.blocks if block.start == 0x00401000)
    assert call_block.end == 0x00401008
    assert call_block.instruction_addresses == (
        0x00401000,
        0x00401001,
        0x00401003,
    )
    assert all(
        len(bytes.fromhex(instruction.bytes_hex)) == instruction.size
        for instruction in cfg.instructions
    )
    unresolved_indirects = [
        row for row in cfg.ownership_diagnostics if row.kind == "indirect-flow"
    ]
    assert len(unresolved_indirects) == 1
    assert unresolved_indirects[0].address == 0x0040107D


def test_embedded_e8_is_explained_as_data_not_call(synthetic_cfg_image):
    cfg = recover_cfg(
        synthetic_cfg_image,
        inventory(synthetic_cfg_image),
        generous_limits(synthetic_cfg_image),
    )
    row = next(
        row for row in cfg.raw_e8_candidates if row.address == 0x00401080
    )
    assert row.target == 0x00401060
    assert row.classification == "owned-data"
    data = next(
        row
        for row in cfg.data_regions
        if row.start == 0x00401080 and row.end == 0x00401088
    )
    assert data.provenance


def test_partial_five_byte_e8_data_containment_is_unresolved(tmp_path):
    image = load_cfg_image(tmp_path, "partial_e8_data_reference")
    with pytest.raises(CfgRecoveryError, match="raw E8 candidate is unresolved"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_interior_e8_crossing_owned_instructions_is_explained(tmp_path):
    image = load_cfg_image(tmp_path, "interior_e8_crosses_owned_instructions")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    row = next(
        row for row in cfg.raw_e8_candidates if row.address == 0x00401071
    )
    assert row.target == 0x00401076
    assert row.classification == "owned-instruction-bytes"
    instructions = {row.address: row for row in cfg.instructions}
    assert instructions[0x00401070].mnemonic == "add"
    assert instructions[0x00401072].mnemonic == "add"
    assert instructions[0x00401074].mnemonic == "add"


def test_retail_mwcc_nop_encodings_are_owned_as_padding(tmp_path):
    image = load_cfg_image(tmp_path, "mwcc_padding_encodings")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert any(
        region.start == 0x00401061 and region.end == 0x00401070
        for region in cfg.padding_regions
    )


def test_pure_zero_fill_after_terminal_owns_executable_raw_tail(
    synthetic_cfg_image,
):
    text = synthetic_cfg_image.sections[0]
    data = bytearray(synthetic_cfg_image.data)
    data[text.raw_offset : text.raw_offset + 0x10] = b"\xc3" + b"\0" * 15
    tail_section = replace(text, raw_size=0x10, virt_size=0x10)
    image = replace(
        synthetic_cfg_image,
        data=bytes(data),
        entrypoint=text.va,
        sections=(tail_section, *synthetic_cfg_image.sections[1:]),
        exports=(),
        relocations=(),
        executable_ranges=((text.va, text.va + 0x10),),
    )
    cfg = recover_cfg(image, (text.va,), generous_limits(image))
    assert any(
        region.start == text.va + 1 and region.end == text.va + 0x10
        for region in cfg.padding_regions
    )


def test_unsupported_cross_block_initializer_fails_closed(tmp_path):
    image = load_cfg_image(tmp_path, "unsupported_cross_block_initializer")
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_unsupported_indexed_initializer_fails_closed(tmp_path):
    image = load_cfg_image(tmp_path, "unsupported_indexed_initializer")
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_instruction_interior_and_unmapped_seeds_fail_closed(
    synthetic_cfg_image,
):
    limits = generous_limits(synthetic_cfg_image)
    with pytest.raises(CfgRecoveryError, match="instruction interior"):
        recover_cfg(
            synthetic_cfg_image,
            (0x00401003, 0x00401004),
            limits,
        )
    with pytest.raises(CfgRecoveryError, match="not executable"):
        recover_cfg(synthetic_cfg_image, (0x00409999,), limits)


@pytest.mark.parametrize(
    ("mutation", "target", "predecessor"),
    [
        ("late_backward_target", 0x00401001, 0x00401000),
        ("late_target_inside_owned_block", 0x00401046, 0x00401040),
    ],
)
def test_late_target_split_retains_predecessor_fallthrough(
    tmp_path, mutation, target, predecessor
):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert any(block.start == target for block in cfg.blocks)
    assert any(
        edge.source == predecessor
        and edge.target == target
        and edge.kind == "fallthrough"
        for edge in cfg.edges
    )


@pytest.mark.parametrize(
    ("mutation", "forbidden_start"),
    [
        ("lea_is_not_data", 0x00401068),
        ("write_is_not_data", 0x00401068),
        ("control_operand_is_not_data", 0x004020A0),
    ],
)
def test_only_semantic_memory_reads_produce_data_evidence(
    tmp_path, mutation, forbidden_start
):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert not any(
        region.start <= forbidden_start < region.end
        for region in cfg.data_regions
    )


def test_absolute_iat_call_is_a_typed_terminal_external_edge(tmp_path):
    image = load_cfg_image(tmp_path, "control_operand_is_not_data")
    image = replace(
        image,
        imports=(
            pe.Import(
                dll="KERNEL32.dll",
                name="CloseHandle",
                ordinal=None,
                hint=28,
                iat_va=0x004020A0,
            ),
        ),
    )
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    edge = next(
        row
        for row in cfg.control_targets.terminal_external_edges
        if row.source == 0x00401070
    )
    assert (edge.flow_kind, edge.iat_va, edge.dll, edge.name) == (
        "call",
        0x004020A0,
        "KERNEL32.dll",
        "CloseHandle",
    )
    assert not any(
        row.address == 0x00401070 and row.kind == "indirect-flow"
        for row in cfg.ownership_diagnostics
    )


def test_relocated_internal_callback_escaping_to_an_import_blocks(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="external-code-pointer-escape")
    escape = next(
        row
        for row in cfg.control_targets.external_escapes
        if row.source == 0x00401005
    )
    assert escape.target_import_iat == 0x00402160
    assert escape.possible_internal_targets == (0x00401090,)
    assert any(
        row.address == 0x00401005
        and row.kind == "external-code-pointer-escape"
        for row in cfg.control_targets.unresolved
    )


def test_reachable_global_initializer_proves_finite_slot_target(tmp_path):
    image = load_cfg_image(tmp_path, "global_callback_slot")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040107A
        and row.flow_kind == "indirect-jump-global-slot"
    )
    assert edge.target == 0x00401060
    assert "slot=0x4020a0" in edge.provenance
    assert not any(
        row.address == 0x0040107A and row.kind == "indirect-flow"
        for row in cfg.ownership_diagnostics
    )


def test_zero_initialized_bss_slot_accepts_reachable_finite_writes(tmp_path):
    image = load_cfg_image(tmp_path, "bss_global_callback_slot")
    sections = tuple(
        replace(section, raw_size=0x200, virt_size=0x1000)
        if section.name == ".rdata"
        else section
        for section in image.sections
    )
    image = replace(image, sections=sections)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040107A
        and row.flow_kind == "indirect-jump-global-slot"
    )
    assert edge.target == 0x00401060
    assert "slot=0x402300;initial=0x0" in edge.provenance


def test_cdecl_argument_write_proves_global_callback_target(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="global-cdecl-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040100B
        and row.flow_kind == "indirect-call-global-slot"
    )
    assert edge.target == 0x00401090
    assert "argument=0" in edge.provenance
    assert "caller=" not in edge.provenance


def test_finite_object_field_uses_reachable_runtime_writes(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="finite-object-runtime-field-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401038
        and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "global-slot=0x402404" in edge.provenance
    assert "fault-before-transfer=0x0" in edge.provenance


def test_finite_object_field_with_unknown_runtime_write_remains_blocking(
    tmp_path,
):
    cfg = dispatch_cfg(
        tmp_path, mode="finite-object-runtime-field-unknown-write"
    )
    assert any(
        row.address == 0x00401038 and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_global_descriptor_domain_proves_field_callback_target(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="global-descriptor-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401035
        and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "global-slot=0x402300" in edge.provenance
    assert "fault-before-transfer=0x0" in edge.provenance


def test_ebp_can_hold_a_finite_descriptor_instead_of_a_frame(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="global-descriptor-ebp-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401036
        and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "field=+0x10" in edge.provenance
    assert "global-slot=0x402300" in edge.provenance


def test_guarded_global_descriptor_survives_volatile_alias_block(tmp_path):
    cfg = dispatch_cfg(
        tmp_path, mode="global-descriptor-guarded-alias-callback"
    )
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040103F
        and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "global-slot=0x402300" in edge.provenance


def test_guarded_global_descriptor_rejects_volatile_alias_clobber(tmp_path):
    cfg = dispatch_cfg(
        tmp_path, mode="global-descriptor-guarded-alias-clobber"
    )
    assert any(
        row.address == 0x00401041 and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_unknown_global_descriptor_write_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="global-descriptor-unknown-write")
    assert any(
        row.address == 0x00401035 and row.kind == "indirect-flow"
        for row in cfg.control_targets.unresolved
    )


def test_reachable_object_callback_table_seeds_every_relocated_entry(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="object-callback-table")
    records = {
        (row.address, row.provenance_address, row.category)
        for row in cfg.seed_inventory.records
    }
    assert records >= {
        (0x00401090, 0x00402300, "object-callback-table-entry"),
        (0x004010A0, 0x00402304, "object-callback-table-entry"),
    }
    assert {
        row.address
        for row in cfg.function_entries
    } >= {0x00401090, 0x004010A0}
    assert any(
        row.start <= 0x00402300 and 0x0040230C <= row.end
        for row in cfg.data_regions
    )


@pytest.mark.parametrize(
    "mode",
    (
        "object-callback-table-no-dispatch",
        "object-callback-table-unreachable-store",
        "object-callback-table-unknown-source",
        "object-callback-table-isolated",
        "object-callback-table-missing-terminator",
        "object-callback-table-relocated-terminator",
        "object-callback-table-interior-target",
        "object-callback-table-unknown-overlap",
        "object-callback-table-late-rmw",
    ),
)
def test_relocated_executable_run_without_owned_exact_object_store_is_not_code(
    tmp_path, mode
):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert not {
        row.address
        for row in cfg.seed_inventory.records
        if row.category == "object-callback-table-entry"
    }
    unproven_entry = (
        0x00401091
        if mode == "object-callback-table-interior-target"
        else 0x00401090
    )
    assert unproven_entry not in {
        row.address for row in cfg.function_entries
    }


def test_late_rmw_cannot_leave_a_stale_object_dispatch_proof(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="object-callback-table-late-rmw")
    assert any(
        row.address == 0x00401034
        and row.kind == "object-callback-table-blocker"
        for row in cfg.control_targets.unresolved
    )
    assert any(
        row.source == 0x0040106A
        and row.flow_kind == "indirect-call-finite-value"
        and row.target == 0x004010A0
        for row in cfg.control_targets.finite_internal_edges
    )
    assert 0x00401090 not in {
        row.address for row in cfg.instructions
    }
    assert not any(
        row.source == 0x00401090
        for row in cfg.control_targets.finite_internal_edges
    )


def test_data_evidence_cannot_overlap_instruction_or_padding(tmp_path):
    image = load_cfg_image(tmp_path, "data_overlaps_instruction")
    with pytest.raises(CfgRecoveryError, match="ownership overlap"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_partial_width_relocation_does_not_prove_executable_pointer(tmp_path):
    image = load_cfg_image(tmp_path, "partial_relocation_pointer")
    seeds = inventory(image)
    assert not any(
        row.category == "relocation-executable-pointer"
        for row in seeds.records
    )


def test_executable_relocation_crossing_operand_boundary_fails(tmp_path):
    image = load_cfg_image(tmp_path, "exec_relocation_partial_field")
    with pytest.raises(CfgRecoveryError, match="relocation.*boundary"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_executable_highlow_conflicting_data_boundaries_fail_closed(tmp_path):
    image = load_cfg_image(
        tmp_path, "exec_relocation_data_slot_conflicting_refs"
    )
    with pytest.raises(
        CfgRecoveryError, match="data boundary is ambiguous.*attributions=2"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_final_relocation_dispositions_distinguish_instruction_typed_and_residue(
    tmp_path,
):
    instruction_image = load_cfg_image(tmp_path, "exec_relocation_immediate")
    instruction_cfg = recover_cfg(
        instruction_image,
        inventory(instruction_image),
        generous_limits(instruction_image),
    )
    assert any(
        row.source_address == 0x0040100B
        and row.status == "owned-instruction-operand"
        and row.source_class == "instruction"
        for row in instruction_cfg.relocation_dispositions
    )

    typed_image = load_cfg_image(
        tmp_path, "exec_relocation_data_slot_consistent_refs"
    )
    typed_cfg = recover_cfg(
        typed_image, inventory(typed_image), generous_limits(typed_image)
    )
    assert any(
        row.source_address == 0x00401080
        and row.status == "unresolved-exec-pointer"
        and row.source_class == "unique-typed-data-boundary"
        for row in typed_cfg.relocation_dispositions
    )

    residue_image = load_cfg_image(
        tmp_path, "exec_relocation_aligned_prologue"
    )
    residue_cfg = recover_cfg(
        residue_image,
        inventory(residue_image),
        generous_limits(residue_image),
    )
    assert any(
        row.source_address == 0x00401035
        and row.status == "residue-nonexec-address"
        and row.source_class == "residue"
        for row in residue_cfg.relocation_dispositions
    )


@pytest.mark.parametrize(
    "mutation", ["transformed_initializer", "cross_block_initializer_value"]
)
def test_executable_initializer_taint_never_silently_disappears(
    tmp_path, mutation
):
    image = load_cfg_image(tmp_path, mutation)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "mutation",
    [
        "partial_initializer_store",
        "xchg_initializer_store",
        "push_initializer_value",
        "stos_initializer_value",
    ],
)
def test_unsupported_memory_write_of_executable_value_fails_closed(
    tmp_path, mutation
):
    image = load_cfg_image(tmp_path, mutation)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "mutation",
    [
        "full_load_clobbers_initializer_value",
        "zeroing_clobbers_initializer_value",
        "call_clobbers_caller_saved_initializer_value",
    ],
)
def test_full_independent_write_or_call_clobber_kills_initializer_taint(
    tmp_path, mutation
):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert not any(
        row.category == "function-pointer-initializer"
        and 0x0040100A <= row.provenance_address < 0x00401020
        for row in cfg.seed_inventory.records
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "partial_clobber_retains_initializer_taint",
        "call_preserves_callee_saved_initializer_taint",
    ],
)
def test_partial_write_and_callee_saved_call_retain_unsafe_taint(
    tmp_path, mutation
):
    image = load_cfg_image(tmp_path, mutation)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "mutation",
    [
        "cross_register_lea_initializer",
        "register_xchg_initializer",
        "partial_register_copy_initializer",
        "cmov_initializer",
        "arithmetic_cross_register_initializer",
        "vector_register_initializer",
    ],
)
def test_register_transform_retains_unsafe_initializer_taint(
    tmp_path, mutation
):
    image = load_cfg_image(tmp_path, mutation)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_shrd_implicit_cl_read_preserves_initializer_taint(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "bb 50 10 40 00 0f ad fb 89 1d 90 20 40 00 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_capstone_semantic_contract_is_pinned_before_recovery(
    synthetic_cfg_image, monkeypatch
):
    monkeypatch.setattr(capstone, "__version__", "5.0.7-audited-drift")
    with pytest.raises(CfgRecoveryError, match="Capstone audit contract"):
        recover_cfg(
            synthetic_cfg_image,
            inventory(synthetic_cfg_image),
            generous_limits(synthetic_cfg_image),
        )


@pytest.mark.parametrize(
    ("encoded", "instruction_id", "operand_access", "register_reads"),
    [
        ("0f f7 c1", 376, (1, 1), ("edi",)),
        ("66 0f f7 c1", 359, (1, 1), ("edi",)),
        ("c5 f9 f7 c1", 1004, (1, 1), ("edi",)),
        ("0f ae 01", 212, (2,), ()),
        ("dd 31", 204, (2,), ()),
        ("dd 19", 714, (1,), ()),
        ("0f ae 21", 1511, (2,), ("rdx", "rax")),
        ("0f 38 f6 08", 1485, (0, 0), ()),
        ("66 0f 38 f5 08", 1487, (0, 0), ()),
        ("0f 7e 00", 377, (1, 1), ()),
        ("0f 11 00", 495, (1, 1), ()),
        ("c5 fc 11 00", 1051, (1, 1), ()),
        ("c4 e2 75 2e 00", 1006, (1, 1, 1), ()),
        ("c4 e2 75 8e 00", 1230, (1, 1, 1), ()),
        ("62 f2 7d 49 a2 04 88", 1440, (1, 1, 0), ()),
        ("62 f2 7d 49 a0 04 88", 1317, (1, 1, 0), ()),
    ],
)
def test_audited_capstone_writer_metadata_contract(
    encoded, instruction_id, operand_access, register_reads
):
    decoder, decoded = decode_one(encoded)
    assert decoded.id == instruction_id
    assert tuple(operand.access for operand in decoded.operands) == operand_access
    assert tuple(decoder.reg_name(reg) for reg in decoded.regs_read) == (
        register_reads
    )


@pytest.mark.parametrize(
    (
        "encoded",
        "instruction_id",
        "mnemonic",
        "operand_registers",
        "operand_access",
        "register_reads",
        "register_writes",
    ),
    [
        ("d9 c1", 331, "fld", ("st(1)",), (1,), (), ("fpsw",)),
        (
            "d9 c9",
            1494,
            "fxch",
            ("st(0)", "st(1)"),
            (1, 0),
            (),
            ("fpsw",),
        ),
        ("dd d1", 713, "fst", ("st(1)",), (1,), (), ("fpsw",)),
        ("dd d9", 714, "fstp", ("st(1)",), (2,), (), ("fpsw",)),
        ("d8 c1", 15, "fadd", ("st(1)",), (1,), (), ()),
        ("de c1", 15, "faddp", ("st(1)",), (1,), (), ()),
    ],
)
def test_audited_capstone_hidden_x87_stack_metadata_contract(
    encoded,
    instruction_id,
    mnemonic,
    operand_registers,
    operand_access,
    register_reads,
    register_writes,
):
    decoder, decoded = decode_one(encoded)
    assert decoded.id == instruction_id
    assert decoded.mnemonic == mnemonic
    assert tuple(decoder.reg_name(op.reg) for op in decoded.operands) == (
        operand_registers
    )
    assert tuple(op.access for op in decoded.operands) == operand_access
    assert tuple(decoder.reg_name(reg) for reg in decoded.regs_read) == (
        register_reads
    )
    assert tuple(decoder.reg_name(reg) for reg in decoded.regs_write) == (
        register_writes
    )


@pytest.mark.parametrize(
    "program",
    [
        # A tainted base is an address, not the loaded payload.
        "bb 50 10 40 00 81 c3 00 10 00 00 8b 03 a3 90 20 40 00 c3",
        # A tainted store address does not taint a clean payload.
        "bb 50 10 40 00 31 c0 89 03 c3",
        # STOS consumes EAX, not its EDI destination address.
        "bf 50 10 40 00 31 c0 ab c3",
        # MOVS copies a fresh memory value; ESI is only its source address.
        "be 50 10 40 00 81 c6 00 10 00 00 a5 c3",
        # LODS loads a fresh value even when its source address is tainted.
        "be 50 10 40 00 81 c6 00 10 00 00 ad a3 90 20 40 00 c3",
        # XCHG moves the clean old EAX into EBX positionally.
        "bb 50 10 40 00 31 c0 87 d8 89 1d 90 20 40 00 c3",
        # MASKMOVQ's mask operand is not the stored payload.
        "b8 50 10 40 00 0f 6e c8 0f f7 c1 c3",
        # VMASKMOVDQU's mask operand is not the stored payload.
        "b8 50 10 40 00 66 0f 6e c8 c5 f9 f7 c1 c3",
        # Masked stores do not store their mask register.
        "b8 50 10 40 00 66 0f 6e c8 c4 e2 75 2e 01 c3",
        "b8 50 10 40 00 66 0f 6e c8 c4 e2 75 8e 01 c3",
        # Scatter index registers are addresses, not payload.
        "b8 50 10 40 00 66 0f 6e c8 62 f2 7d 49 a2 04 89 c3",
        # INS consumes DX as a port selector, not a stored payload.
        "ba 50 10 40 00 6d c3",
        # MOVDIR64B consumes EAX as a destination address.
        "b8 50 10 40 00 66 0f 38 f8 00 c3",
        # OUTS targets an I/O port and gather only reads memory.
        "be 50 10 40 00 6f c3",
        "b8 50 10 40 00 66 0f 6e c8 c4 e2 6d 90 04 89 c3",
    ],
)
def test_address_mask_and_protocol_dependencies_are_not_payloads(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # Implicit MASKMOV destinations.
        "b8 50 10 40 00 0f 6e c0 0f f7 c1 c3",
        "b8 50 10 40 00 66 0f 6e c0 66 0f f7 c1 c3",
        "b8 50 10 40 00 66 0f 6e c0 c5 f9 f7 c1 c3",
        # ENTER pushes the old EBP value.
        "bd 50 10 40 00 c8 00 00 00 c3",
        # State saves contain hidden MMX/x87/vector payloads.
        "b8 50 10 40 00 0f 6e c0 dd 31 c3",
        "b8 50 10 40 00 0f 6e c0 dd 19 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f ae 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f ae 21 c3",
        # CET stores have access=0 for both operands.
        "b9 50 10 40 00 31 c0 0f 38 f6 08 c3",
        "b9 50 10 40 00 31 c0 66 0f 38 f5 08 c3",
        # Representative legacy and VEX access-metadata defects.
        "b8 50 10 40 00 0f 6e c0 0f 7e 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f 11 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 c5 fc 11 01 c3",
        # Masked and scatter stores consume operand 2, not their masks/VSIB.
        "b8 50 10 40 00 66 0f 6e c0 c4 e2 75 2e 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 c4 e2 75 8e 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 62 f2 7d 49 a2 04 89 c3",
        "b8 50 10 40 00 66 0f 6e c0 62 f2 7d 49 a0 04 89 c3",
    ],
)
def test_semantic_memory_writers_reject_only_tainted_payload(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # Full GPR/vector loads replace every written lane.
        "b8 50 10 40 00 8b 01 a3 90 20 40 00 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f 10 01 0f 11 01 c3",
        # Vector zero idiom clears the full destination.
        "b8 50 10 40 00 66 0f 6e c0 66 0f ef c0 0f 11 01 c3",
        # A VEX XMM write also clears the upper YMM alias lanes.
        "b8 50 10 40 00 62 f2 7d 28 7c c0 c5 f8 10 01 "
        "c5 fc 11 01 c3",
        # FXSAVE stores XMM state, not the untouched upper YMM lanes.
        "b8 50 10 40 00 62 f2 7d 28 7c c0 66 0f ef c0 0f ae 01 c3",
        # Register XADD places the clean old destination in its source.
        "bb 50 10 40 00 31 c0 0f c1 d8 89 1d 90 20 40 00 c3",
        # POP replaces the full destination with a fresh stack value.
        "b8 50 10 40 00 58 a3 90 20 40 00 c3",
        # A state-save address by itself is not saved payload.
        "b9 50 10 40 00 dd 31 c3",
    ],
)
def test_full_lane_replacements_and_address_only_state_are_clean(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # Partial GPR/vector loads preserve untouched tainted lanes.
        "b8 50 10 40 00 8a 01 a3 90 20 40 00 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f 12 01 0f 11 01 c3",
        # A legacy XMM write preserves upper YMM lanes.
        "b8 50 10 40 00 62 f2 7d 28 7c c0 0f 10 01 "
        "c5 fc 11 01 c3",
        # CMOV can preserve its old destination.
        "b8 50 10 40 00 31 db 85 c9 0f 45 c3 a3 90 20 40 00 c3",
        # PUSH immediate, PUSHA, and PUSHF store their real payloads.
        "68 50 10 40 00 c3",
        "bb 50 10 40 00 60 c3",
        "b8 50 10 40 00 83 c0 00 9c c3",
        # XADD/CMPXCHG memory forms conditionally store the source value.
        "b8 50 10 40 00 0f c1 01 c3",
        "b9 50 10 40 00 0f b1 0b c3",
        # XSAVE can store upper YMM/ZMM state selected at runtime.
        "b8 50 10 40 00 62 f2 7d 28 7c c0 66 0f ef c0 0f ae 21 c3",
    ],
)
def test_partial_conditional_and_stack_payloads_remain_tainted(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_wide_cmpxchg_failure_arm_preserves_accumulator_taint(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f c7 0f a3 90 20 40 00 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize("instruction", ["87 c0", "0f c1 c0"])
def test_aliased_exchange_outputs_retain_old_accumulator_taint(
    tmp_path, instruction
):
    image = load_cfg_program(
        tmp_path,
        f"b8 50 10 40 00 {instruction} a3 90 20 40 00 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_cmpxchg_destination_aliasing_accumulator_uses_source_value(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 31 db 0f b1 d8 a3 90 20 40 00 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # Source aliases the accumulator: either architectural arm can retain it.
        "b8 50 10 40 00 31 db 0f b1 c3 a3 90 20 40 00 c3",
        # Source aliases the destination: the destination remains unchanged.
        "bb 50 10 40 00 31 c0 0f b1 db 89 1d 90 20 40 00 c3",
        # The high-byte source partially aliases the implicit AL accumulator.
        "b8 50 10 40 00 31 db 0f b0 e3 89 1d 90 20 40 00 c3",
    ],
)
def test_cmpxchg_source_destination_and_partial_aliases_join_taint(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize("fld", ["d9 c1", "66 d9 c1", "2e d9 c1"])
def test_fld_register_pushes_hidden_x87_stack_value(tmp_path, fld):
    image = load_cfg_program(
        tmp_path,
        f"b8 50 10 40 00 0f 6e c8 {fld} dd 19 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # FXCH moves the tainted ST(1) value to the memory-visible top.
        "b8 50 10 40 00 0f 6e c8 d9 c9 dd 19 c3",
        # FST copies ST(0) into ST(1) even though Capstone marks it read-only.
        "b8 50 10 40 00 0f 6e c0 dd d1 dd c0 d9 c9 dd 19 c3",
        # FLD shifts a tainted ST(1) to ST(2), then arithmetic consumes it.
        "b8 50 10 40 00 0f 6e c8 d9 e8 d8 c2 dd 19 c3",
        # FADDP writes its hidden destination before popping the x87 stack.
        "b8 50 10 40 00 0f 6e c0 d9 e8 de c1 dd 19 c3",
        # The implicit ST(0) arithmetic input is not reported as an operand.
        "b8 50 10 40 00 0f 6e c0 de c1 dd 19 c3",
    ],
)
def test_x87_swap_store_and_arithmetic_stack_forms_preserve_taint(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_clean_fstp_register_copy_and_pop_is_fully_modeled(tmp_path):
    image = load_cfg_program(tmp_path, "d9 e8 dd d9 dd 19 c3")
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # FLDENV changes control/TOP state but does not overwrite data registers.
        "b8 50 10 40 00 0f 6e c0 d9 21 0f 7e c0 a3 90 20 40 00 c3",
        # EMMS changes tags; the aliased MMX payload remains architecturally present.
        "b8 50 10 40 00 0f 6e c0 0f 77 0f 7e c0 a3 90 20 40 00 c3",
        # FFREE changes a tag; it does not erase the aliased physical payload.
        "b8 50 10 40 00 0f 6e c0 dd c0 0f 7e c0 a3 90 20 40 00 c3",
        # An x87 push into physical slot 7 cannot erase unrelated MM6.
        "b8 50 10 40 00 0f 6e f0 d9 e8 0f 7e f0 a3 90 20 40 00 c3",
    ],
)
def test_x87_stack_and_tag_updates_preserve_mmx_physical_alias_taint(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_fldenv_top_ambiguity_cannot_hide_physical_mmx_taint(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c8 d9 21 dd 19 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_tainted_x87_mutation_with_unknown_top_has_canonical_diagnostic(
    tmp_path,
):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 d9 21 d9 e8 c3",
    )
    with pytest.raises(
        CfgRecoveryError,
        match=(
            r"address=0x401014;bytes=d9e8;id=330;mnemonic=fld1;"
            r"operands=;reason=ambiguous x87 TOP with tainted physical "
            r"payload: effect=push;top-mask=0xff;valid-must=0x00;"
            r"valid-may=0xff"
        ),
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_fst_logical_destination_does_not_clear_unrelated_physical_mmx(
    tmp_path,
):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c8 0f 77 d9 e8 dd d1 "
        "0f 7e c8 89 02 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_clean_fld1_fstp_does_not_store_stale_physical_mmx_payload(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 0f 77 d9 e8 dd 19 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


def test_ffree_empty_logical_value_does_not_erase_physical_mmx_payload(
    tmp_path,
):
    clean_logical_store = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 dd c0 d9 e8 dd 19 c3",
    )
    recover_cfg(
        clean_logical_store,
        inventory(clean_logical_store),
        generous_limits(clean_logical_store),
    )

    physical_read = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 dd c0 d9 e8 dd 19 "
        "0f 7e c0 89 02 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(
            physical_read,
            inventory(physical_read),
            generous_limits(physical_read),
        )


@pytest.mark.parametrize("restore", ["dd 21", "0f ae 09"])
def test_fresh_x87_state_restore_clears_physical_payload_taint(
    tmp_path, restore
):
    image = load_cfg_program(
        tmp_path,
        f"b8 50 10 40 00 0f 6e c0 {restore} dd 19 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


def test_fxrstor_replaces_low_xmm_lanes_but_not_upper_vector_lanes(tmp_path):
    restored_xmm = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 66 0f 6e c0 0f ae 09 0f 11 02 c3",
    )
    recover_cfg(
        restored_xmm,
        inventory(restored_xmm),
        generous_limits(restored_xmm),
    )

    retained_upper_ymm = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 62 f2 7d 28 7c c0 0f ae 09 c5 fc 11 02 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(
            retained_upper_ymm,
            inventory(retained_upper_ymm),
            generous_limits(retained_upper_ymm),
        )


@pytest.mark.parametrize("restore", ["dd 21", "0f ae 29"])
def test_other_state_restores_do_not_overclear_vector_state(tmp_path, restore):
    image = load_cfg_program(
        tmp_path,
        f"b8 50 10 40 00 66 0f 6e c0 {restore} 0f 11 02 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_full_mmx_replacement_overwrites_aliased_x87_sign_exponent(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 d8 c0 0f ef c0 0f ae 01 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


def test_full_mmx_replacement_propagates_tainted_low_payload(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 d8 c0 0f 6e c0 0f ae 01 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_x87_state_save_sinks_stale_physical_payload_after_emms(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 0f 77 dd 31 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_fldenv_with_clean_physical_state_keeps_logical_stores_clean(tmp_path):
    image = load_cfg_program(tmp_path, "d9 21 d9 e8 dd 19 c3")
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # One predecessor increments TOP, so ST(0) can resolve physical MM1.
        "b8 50 10 40 00 0f 6e c8 85 c0 74 02 d9 f7 dd 19 c3",
        # One predecessor empties tags while the other keeps MM0 valid.
        "b8 50 10 40 00 0f 6e c0 85 c0 74 02 0f 77 dd 19 c3",
    ],
)
def test_cfg_join_unions_top_and_may_tags_for_relevant_taint(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_cfg_join_with_differing_clean_top_and_tags_is_not_a_pointer_blocker(
    tmp_path,
):
    image = load_cfg_program(
        tmp_path,
        "31 c0 85 c0 74 02 d9 f7 d9 e8 dd 19 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


def test_call_retains_physical_taint_and_invalidates_logical_control(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c8 e8 04 00 00 00 dd 19 c3 90 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_finit_resets_top_and_tags_but_retains_physical_payload(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 db e3 d9 e8 dd 19 "
        "0f 7e c0 89 02 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_unknown_hidden_x87_stack_form_blocks_only_relevant_taint(tmp_path):
    tainted = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c8 d9 f8 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unmodeled x87 stack effect"):
        recover_cfg(tainted, inventory(tainted), generous_limits(tainted))

    clean = load_cfg_program(tmp_path, "d9 f8 c3")
    recover_cfg(clean, inventory(clean), generous_limits(clean))


def test_entry_export_and_anchor_bind_to_complete_first_instruction(
    synthetic_cfg_image,
):
    cfg = recover_cfg(
        synthetic_cfg_image,
        inventory(synthetic_cfg_image),
        generous_limits(synthetic_cfg_image),
    )
    export = next(
        row for row in cfg.seed_inventory.records if row.category == "export"
    )
    assert export.provenance_bytes == "dd0580104000"

    prefix_anchor = AuditAnchor(
        name="prefix-anchor",
        address=0x00401001,
        instruction_bytes=synthetic_cfg_image.read(0x00401001, 1),
        evidence="synthetic-fixture",
    )
    with pytest.raises(CfgRecoveryError, match="complete instruction"):
        recover_cfg(
            synthetic_cfg_image,
            build_seed_inventory(synthetic_cfg_image, (prefix_anchor,)),
            generous_limits(synthetic_cfg_image),
        )


@pytest.mark.parametrize(
    "cap_name",
    [
        "max_instructions",
        "max_blocks",
        "max_edges",
        "max_functions",
        "max_finite_targets",
        "max_finite_values",
        "max_states_per_block",
        "max_fixpoint_updates",
        "max_summary_iterations",
    ],
)
def test_recover_cfg_enforces_every_task3_production_cap(
    synthetic_cfg_image, cap_name
):
    limits = replace(generous_limits(synthetic_cfg_image), **{cap_name: 1})
    with pytest.raises(AnalysisLimitError) as raised:
        recover_cfg(synthetic_cfg_image, inventory(synthetic_cfg_image), limits)
    assert raised.value.limit_name == cap_name
    assert raised.value.configured == 1
    assert raised.value.observed >= 1


def test_high_water_marks_cover_all_caps_and_zero_only_deferred_dimensions(
    synthetic_cfg_image,
):
    cfg = recover_cfg(
        synthetic_cfg_image,
        inventory(synthetic_cfg_image),
        generous_limits(synthetic_cfg_image),
    )
    high_water = {
        row.limit_name: row.observed for row in cfg.high_water_marks
    }
    assert set(high_water) == {
        field.name for field in fields(AnalysisLimits)
    }
    assert high_water["max_finite_values"] > 0
    assert high_water["max_states_per_block"] == 8
    assert high_water["max_fixpoint_updates"] > 0
    assert high_water["max_summary_iterations"] > 0
    for deferred in (
        "max_jump_tables",
        "max_jump_table_entries",
        "max_contexts_per_entry",
        "max_scc_iterations",
    ):
        assert high_water[deferred] == 0


@pytest.mark.parametrize(
    "cap_name",
    [
        "max_jump_tables",
        "max_jump_table_entries",
        "max_contexts_per_entry",
        "max_scc_iterations",
    ],
)
def test_recover_cfg_rejects_zero_cap_for_unobserved_dimension(
    synthetic_cfg_image, cap_name
):
    limits = replace(generous_limits(synthetic_cfg_image), **{cap_name: 0})
    with pytest.raises(AnalysisLimitError) as raised:
        recover_cfg(synthetic_cfg_image, inventory(synthetic_cfg_image), limits)
    assert raised.value.limit_name == cap_name
    assert raised.value.configured == 0
    assert raised.value.observed == 0


@pytest.mark.parametrize("mutation", ["far_call", "far_jump"])
def test_far_control_transfer_is_unresolved_not_direct(tmp_path, mutation):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert not any(call.address == 0x00401070 for call in cfg.direct_calls)
    assert not any(
        edge.source == 0x00401070
        and edge.kind in {
            "direct-call",
            "conditional-branch",
            "unconditional-branch",
        }
        for edge in cfg.edges
    )
    assert any(
        row.address == 0x00401070 and row.kind == "unsupported-far-flow"
        for row in cfg.ownership_diagnostics
    )


def test_decode_lookahead_is_bounded_by_executable_raw_tail(
    synthetic_cfg_image,
):
    text = synthetic_cfg_image.sections[0]
    tail_address = text.va + text.raw_size - 1
    raw_tail = text.raw_offset + text.raw_size - 1
    data = bytearray(synthetic_cfg_image.data)
    data[raw_tail] = 0xC3
    tail_section = replace(
        text,
        va=tail_address,
        raw_offset=raw_tail,
        raw_size=1,
        virt_size=0x10,
    )
    tail_image = replace(
        synthetic_cfg_image,
        data=bytes(data),
        entrypoint=tail_address,
        sections=(tail_section, *synthetic_cfg_image.sections[1:]),
        exports=(),
        relocations=(),
        executable_ranges=((tail_address, tail_address + 0x10),),
    )
    cfg = recover_cfg(tail_image, (tail_address,), generous_limits(tail_image))
    assert [(row.address, row.size) for row in cfg.instructions] == [
        (tail_address, 1)
    ]


def test_padding_gap_is_partitioned_around_proven_data(tmp_path):
    image = load_cfg_image(tmp_path, "padding_partitioned_by_data")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert any(
        region.start == 0x00401068 and region.end == 0x0040106C
        for region in cfg.data_regions
    )
    assert any(
        region.start == 0x00401061 and region.end == 0x00401068
        for region in cfg.padding_regions
    )
    assert any(
        region.start == 0x0040106C and region.end == 0x00401070
        for region in cfg.padding_regions
    )


def test_audit_anchor_requires_exact_instruction_byte_provenance(
    synthetic_cfg_image,
):
    anchor = AuditAnchor(
        name="bad-anchor",
        address=0x00401070,
        instruction_bytes=b"\x90",
        evidence="synthetic-fixture",
    )
    with pytest.raises(CfgRecoveryError, match="audit anchor bytes differ"):
        build_seed_inventory(synthetic_cfg_image, (anchor,))


def test_raw_relocations_never_create_authoritative_roots(
    synthetic_cfg_image,
):
    seeds = build_seed_inventory(synthetic_cfg_image, ())
    assert {row.category for row in seeds.records} <= {
        "entrypoint",
        "export",
        "loader-callback",
        "crt-callback",
        "unwind-callback",
    }
    assert not any(
        row.category == "relocation-executable-pointer"
        for row in seeds.records
    )


@pytest.mark.parametrize(
    ("mutation", "residue_address"),
    [
        ("closed_unreachable_island", 0x00401061),
        ("closed_unreferenced_aligned_function", 0x00401030),
        ("exec_relocation_aligned_prologue", 0x00401030),
    ],
)
def test_syntactically_closed_or_relocated_residue_never_becomes_code(
    tmp_path,
    mutation,
    residue_address,
):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    forbidden = {
        "relocation-aligned-entry",
        "relocation-computed-transfer",
        "relocation-inline-data-successor",
        "closed-executable-island",
        "closed-aligned-function",
    }
    assert not forbidden & {
        row.category for row in cfg.seed_inventory.records
    }
    assert all(
        "terminal-noninstruction-separator" not in row.provenance
        for row in cfg.data_regions
    )
    assert cfg.provisional_unreachable_residue.contains(residue_address)


def test_atomic_jsonl_is_canonical_and_has_final_newline(
    synthetic_cfg_image, tmp_path
):
    limits = generous_limits(synthetic_cfg_image)
    a = recover_cfg(
        synthetic_cfg_image,
        (0x00401000, 0x00401040, 0x00401070),
        limits,
    )
    b = recover_cfg(
        synthetic_cfg_image,
        (0x00401070, 0x00401040, 0x00401000),
        limits,
    )
    path = tmp_path / "cfg.jsonl"
    write_jsonl_atomic(path, a)
    first = path.read_bytes()
    write_jsonl_atomic(path, b)
    assert path.read_bytes() == first
    assert first.endswith(b"\n")
    rows = [json.loads(line) for line in first.splitlines()]
    keys = [
        (row["address"], row["record_kind"], row.get("target", -1))
        for row in rows
    ]
    assert keys == sorted(keys)
    rendered = first.decode("utf-8")
    assert "elapsed" not in rendered
    assert "timestamp" not in rendered
    assert str(tmp_path) not in rendered
