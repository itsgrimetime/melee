"""Small deterministic PE32/i386 fixture for strict parser tests."""

from __future__ import annotations

import struct
from pathlib import Path

PE_OFFSET = 0x80
OPTIONAL_OFFSET = PE_OFFSET + 24
OPTIONAL_SIZE = 0xE0
SECTION_TABLE_OFFSET = OPTIONAL_OFFSET + OPTIONAL_SIZE


def synthetic_pe_bytes(*, mutation: str | None = None) -> bytes:
    data = bytearray(0xA00)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, PE_OFFSET)
    data[PE_OFFSET : PE_OFFSET + 4] = b"PE\0\0"
    struct.pack_into(
        "<HHIIIHH",
        data,
        PE_OFFSET + 4,
        0x14C,
        3,
        0,
        0,
        0,
        OPTIONAL_SIZE,
        0x0102,
    )

    struct.pack_into("<H", data, OPTIONAL_OFFSET, 0x10B)
    struct.pack_into("<I", data, OPTIONAL_OFFSET + 16, 0x1000)
    struct.pack_into("<I", data, OPTIONAL_OFFSET + 20, 0x1000)
    struct.pack_into("<I", data, OPTIONAL_OFFSET + 24, 0x2000)
    struct.pack_into("<I", data, OPTIONAL_OFFSET + 28, 0x00400000)
    struct.pack_into("<I", data, OPTIONAL_OFFSET + 32, 0x1000)
    struct.pack_into("<I", data, OPTIONAL_OFFSET + 36, 0x200)
    struct.pack_into("<I", data, OPTIONAL_OFFSET + 56, 0x4000)
    struct.pack_into("<I", data, OPTIONAL_OFFSET + 60, 0x200)
    struct.pack_into("<I", data, OPTIONAL_OFFSET + 92, 16)

    directories = {
        0: (0x2000, 0x70),
        1: (0x2100, 0x28),
        5: (0x3000, 0x0C),
        12: (0x2160, 0x08),
    }
    for index, (rva, size) in directories.items():
        struct.pack_into("<II", data, OPTIONAL_OFFSET + 96 + index * 8, rva, size)

    sections = (
        (b".text", 0x180, 0x1000, 0x200, 0x200, 0x60000020),
        (b".rdata", 0x400, 0x2000, 0x400, 0x400, 0x40000040),
        (b".reloc", 0x200, 0x3000, 0x200, 0x800, 0x42000040),
    )
    for index, (name, vsize, rva, raw_size, raw_offset, flags) in enumerate(
        sections
    ):
        offset = SECTION_TABLE_OFFSET + index * 40
        data[offset : offset + 8] = name.ljust(8, b"\0")
        struct.pack_into(
            "<IIIIIIHHI",
            data,
            offset + 8,
            vsize,
            rva,
            raw_size,
            raw_offset,
            0,
            0,
            0,
            0,
            flags,
        )

    data[0x210] = 0xC3

    struct.pack_into(
        "<IIHHIIIIIII",
        data,
        0x400,
        0,
        0,
        0,
        0,
        0x2050,
        1,
        1,
        1,
        0x2030,
        0x2034,
        0x2038,
    )
    struct.pack_into("<I", data, 0x430, 0x1010)
    struct.pack_into("<I", data, 0x434, 0x2060)
    struct.pack_into("<H", data, 0x438, 0)
    data[0x450 : 0x45C] = b"fixture.dll\0"
    data[0x460 : 0x46F] = b"fixture_export\0"

    struct.pack_into("<IIIII", data, 0x500, 0x2140, 0, 0, 0x2180, 0x2160)
    struct.pack_into("<II", data, 0x540, 0x21A0, 0)
    struct.pack_into("<II", data, 0x560, 0x21A0, 0)
    data[0x580 : 0x58D] = b"KERNEL32.dll\0"
    struct.pack_into("<H", data, 0x5A0, 0)
    data[0x5A2 : 0x5AE] = b"ExitProcess\0"

    struct.pack_into("<IIHH", data, 0x800, 0x1000, 12, 0x3010, 0)

    if mutation == "wrong_machine":
        struct.pack_into("<H", data, PE_OFFSET + 4, 0x8664)
    elif mutation == "wrong_magic":
        struct.pack_into("<H", data, OPTIONAL_OFFSET, 0x20B)
    elif mutation == "overlap_raw":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 40 + 20, 0x200)
    elif mutation == "overlap_virtual":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 40 + 12, 0x1100)
    elif mutation == "overlap_headers":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 12, 0x100)
    elif mutation == "truncated_directory":
        struct.pack_into("<I", data, OPTIONAL_OFFSET + 92, 17)
    elif mutation == "invalid_directory":
        struct.pack_into("<II", data, OPTIONAL_OFFSET + 96, 0x5000, 0x20)
    elif mutation == "empty_exports":
        struct.pack_into("<IIIII", data, 0x414, 0, 0, 0, 0, 0)
    elif mutation == "forwarder_outside_directory":
        struct.pack_into("<I", data, 0x430, 0x206F)
        data[0x46F] = ord("K")
    elif mutation == "unterminated_iat":
        struct.pack_into("<I", data, 0x510, 0x23FC)
        struct.pack_into(
            "<II", data, OPTIONAL_OFFSET + 96 + 12 * 8, 0x23FC, 4
        )
        struct.pack_into("<I", data, 0x7FC, 0x21A0)
    elif mutation == "mismatched_import_tables":
        struct.pack_into("<II", data, 0x544, 0x21A0, 0)
    elif mutation == "unknown_relocation_type":
        struct.pack_into("<H", data, 0x808, 0x5010)
    elif mutation == "missing_highadj_companion":
        struct.pack_into(
            "<II", data, OPTIONAL_OFFSET + 96 + 5 * 8, 0x3000, 10
        )
        struct.pack_into("<IH", data, 0x804, 10, 0x4010)
    elif mutation == "valid_highadj":
        struct.pack_into("<HH", data, 0x808, 0x4010, 0x5000)
    elif mutation == "highlow_at_last_byte":
        struct.pack_into("<H", data, 0x808, 0x31FF)
    elif mutation == "duplicate_records":
        struct.pack_into("<I", data, OPTIONAL_OFFSET + 96 + 8 + 4, 0x3C)
        data[0x514 : 0x528] = data[0x500 : 0x514]
        data[0x528 : 0x53C] = b"\0" * 20
        struct.pack_into("<I", data, 0x418, 2)
        struct.pack_into("<I", data, 0x424, 0x203C)
        struct.pack_into("<I", data, 0x438, 0x2060)
        struct.pack_into("<HH", data, 0x43C, 0, 0)
        struct.pack_into("<H", data, 0x80A, 0x3010)
    elif mutation == "import_dll_case_tie":
        struct.pack_into("<I", data, OPTIONAL_OFFSET + 96 + 8 + 4, 0x3C)
        struct.pack_into("<I", data, OPTIONAL_OFFSET + 96 + 12 * 8 + 4, 0x18)
        struct.pack_into("<IIIII", data, 0x500, 0x2140, 0, 0, 0x2190, 0x2160)
        struct.pack_into("<IIIII", data, 0x514, 0x2140, 0, 0, 0x2180, 0x2170)
        data[0x528 : 0x53C] = b"\0" * 20
        struct.pack_into("<II", data, 0x570, 0x21A0, 0)
        data[0x590 : 0x59D] = b"kernel32.dll\0"
    elif mutation == "invalid_relocation":
        struct.pack_into("<I", data, 0x800, 0x7000)
    elif mutation == "truncated_section_table":
        return bytes(data[: SECTION_TABLE_OFFSET + 90])
    elif mutation is not None:
        raise ValueError(f"unknown synthetic PE mutation: {mutation}")

    return bytes(data)


def synthetic_cfg_pe_bytes(*, mutation: str | None = None) -> bytes:
    """Return a fully owned direct-CFG fixture derived from the strict PE."""
    data = bytearray(synthetic_pe_bytes())

    text_size = 0x88
    struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 8, text_size)
    struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, text_size)

    text = bytearray(b"\x90" * text_size)
    text[0x00:0x0A] = bytes.fromhex("55 8b ec e8 38 00 00 00 75 16")
    text[0x0A:0x19] = bytes.fromhex(
        "b8 50 10 40 00 89 c1 89 0d 90 20 40 00 eb 07"
    )
    text[0x20:0x2B] = bytes.fromhex(
        "c7 05 94 20 40 00 7d 10 40 00 c3"
    )
    text[0x40:0x51] = bytes.fromhex(
        "dd 05 80 10 40 00 83 f8 00 74 05 e8 10 00 00 00 c3"
    )
    text[0x60] = 0xC3
    text[0x70] = 0xC3
    text[0x7D:0x80] = bytes.fromhex("ff d0 c3")
    # A valid raw E8 candidate wholly contained in the eight-byte FLD data.
    text[0x80:0x88] = bytes.fromhex("e8 db ff ff ff 11 22 33")
    data[0x200 : 0x200 + text_size] = text

    # Export fixture_export from 0x401040.
    struct.pack_into("<I", data, 0x430, 0x1040)

    # A HIGHLOW relocation over a non-executable pointer slot proving 0x401060.
    struct.pack_into("<I", data, 0x480, 0x00401060)
    struct.pack_into("<IIHH", data, 0x800, 0x2000, 12, 0x3080, 0)

    if mutation in {
        "partial_initializer_store",
        "xchg_initializer_store",
        "push_initializer_value",
        "stos_initializer_value",
        "full_load_clobbers_initializer_value",
        "zeroing_clobbers_initializer_value",
        "partial_clobber_retains_initializer_taint",
        "call_clobbers_caller_saved_initializer_value",
        "call_preserves_callee_saved_initializer_taint",
        "cross_register_lea_initializer",
        "register_xchg_initializer",
        "partial_register_copy_initializer",
        "cmov_initializer",
        "arithmetic_cross_register_initializer",
        "vector_register_initializer",
    }:
        data[0x20A:0x220] = b"\x90" * 0x16

    if mutation == "unexplained_zero_gap":
        data[0x230] = 0
    elif mutation == "partial_e8_data_reference":
        data[0x240:0x246] = bytes.fromhex("a1 80 10 40 00 90")
    elif mutation == "unsupported_cross_block_initializer":
        data[0x20A:0x219] = bytes.fromhex(
            "b8 90 20 40 00 eb 00 c7 00 78 10 40 00 eb 07"
        )
        data[0x278] = 0xC3
    elif mutation == "unsupported_indexed_initializer":
        data[0x20A:0x220] = bytes.fromhex(
            "c7 04 8d 90 20 40 00 78 10 40 00 eb 09"
            "90 90 90 90 90 90 90 90 90"
        )
        data[0x278] = 0xC3
    elif mutation == "relocation_to_instruction_interior":
        struct.pack_into("<I", data, 0x480, 0x00401004)
    elif mutation == "late_backward_target":
        data[0x270:0x275] = bytes.fromhex("e9 8c ff ff ff")
    elif mutation == "late_target_inside_owned_block":
        data[0x270:0x275] = bytes.fromhex("e9 d1 ff ff ff")
    elif mutation == "lea_is_not_data":
        data[0x270:0x277] = bytes.fromhex("8d 05 68 10 40 00 c3")
    elif mutation == "write_is_not_data":
        data[0x270:0x276] = bytes.fromhex("a3 68 10 40 00 c3")
    elif mutation == "control_operand_is_not_data":
        data[0x270:0x277] = bytes.fromhex("ff 15 a0 20 40 00 c3")
    elif mutation == "data_overlaps_instruction":
        data[0x270:0x276] = bytes.fromhex("a1 60 10 40 00 c3")
    elif mutation == "partial_relocation_pointer":
        struct.pack_into("<H", data, 0x808, 0x1080)
    elif mutation == "exec_relocation_immediate":
        struct.pack_into("<IIHH", data, 0x800, 0x1000, 12, 0x300B, 0)
    elif mutation == "exec_relocation_partial_field":
        struct.pack_into("<IIHH", data, 0x800, 0x1000, 12, 0x300C, 0)
    elif mutation == "exec_relocation_data_slot":
        struct.pack_into("<I", data, 0x280, 0x00401060)
        struct.pack_into("<IIHH", data, 0x800, 0x1000, 12, 0x3080, 0)
    elif mutation == "exec_relocation_data_slot_consistent_refs":
        struct.pack_into("<I", data, 0x280, 0x00401060)
        struct.pack_into("<IIHH", data, 0x800, 0x1000, 12, 0x3080, 0)
        data[0x270:0x277] = bytes.fromhex("dd 05 80 10 40 00 c3")
    elif mutation == "exec_relocation_data_slot_conflicting_refs":
        struct.pack_into("<I", data, 0x280, 0x00401060)
        struct.pack_into("<IIHH", data, 0x800, 0x1000, 12, 0x3080, 0)
        data[0x270:0x276] = bytes.fromhex("a1 80 10 40 00 c3")
    elif mutation == "transformed_initializer":
        data[0x20A:0x219] = bytes.fromhex(
            "b8 50 10 40 00 83 c0 00 a3 90 20 40 00 eb 07"
        )
    elif mutation == "cross_block_initializer_value":
        data[0x20A:0x219] = bytes.fromhex(
            "b8 50 10 40 00 eb 00 a3 90 20 40 00 90 90 90"
        )
    elif mutation == "partial_initializer_store":
        data[0x20A:0x217] = bytes.fromhex(
            "b8 50 10 40 00 66 a3 90 20 40 00 eb 09"
        )
    elif mutation == "xchg_initializer_store":
        data[0x20A:0x217] = bytes.fromhex(
            "b8 50 10 40 00 87 05 90 20 40 00 eb 09"
        )
    elif mutation == "push_initializer_value":
        data[0x20A:0x213] = bytes.fromhex(
            "b8 50 10 40 00 50 58 eb 0d"
        )
    elif mutation == "stos_initializer_value":
        data[0x20A:0x212] = bytes.fromhex(
            "b8 50 10 40 00 ab eb 0e"
        )
    elif mutation == "full_load_clobbers_initializer_value":
        data[0x20A:0x21C] = bytes.fromhex(
            "b8 50 10 40 00 8b 05 80 20 40 00 "
            "a3 90 20 40 00 eb 04"
        )
    elif mutation == "zeroing_clobbers_initializer_value":
        data[0x20A:0x218] = bytes.fromhex(
            "b8 50 10 40 00 31 c0 a3 90 20 40 00 eb 08"
        )
    elif mutation == "partial_clobber_retains_initializer_taint":
        data[0x20A:0x219] = bytes.fromhex(
            "b8 50 10 40 00 66 31 c0 a3 90 20 40 00 eb 07"
        )
    elif mutation == "call_clobbers_caller_saved_initializer_value":
        data[0x20A:0x21B] = bytes.fromhex(
            "b8 50 10 40 00 e8 2c 00 00 00 "
            "a3 90 20 40 00 eb 05"
        )
    elif mutation == "call_preserves_callee_saved_initializer_taint":
        data[0x20A:0x21C] = bytes.fromhex(
            "bb 50 10 40 00 e8 2c 00 00 00 "
            "89 1d 90 20 40 00 eb 04"
        )
    elif mutation == "cross_register_lea_initializer":
        data[0x20A:0x218] = bytes.fromhex(
            "bb 50 10 40 00 8d 03 a3 90 20 40 00 eb 08"
        )
    elif mutation == "register_xchg_initializer":
        data[0x20A:0x218] = bytes.fromhex(
            "bb 50 10 40 00 87 d8 a3 90 20 40 00 eb 08"
        )
    elif mutation == "partial_register_copy_initializer":
        data[0x20A:0x219] = bytes.fromhex(
            "bb 50 10 40 00 66 89 d8 a3 90 20 40 00 eb 07"
        )
    elif mutation == "cmov_initializer":
        data[0x20A:0x21D] = bytes.fromhex(
            "bb 50 10 40 00 31 c0 85 c9 0f 45 c3 "
            "a3 90 20 40 00 eb 03"
        )
    elif mutation == "arithmetic_cross_register_initializer":
        data[0x20A:0x21A] = bytes.fromhex(
            "bb 50 10 40 00 31 c0 01 d8 a3 90 20 40 00 eb 06"
        )
    elif mutation == "vector_register_initializer":
        data[0x20A:0x21D] = bytes.fromhex(
            "bb 50 10 40 00 66 0f 6e c3 "
            "66 0f 7e 05 90 20 40 00 eb 03"
        )
    elif mutation == "far_call":
        data[0x270:0x278] = bytes.fromhex(
            "9a 60 10 40 00 1b 00 c3"
        )
    elif mutation == "far_jump":
        data[0x270:0x277] = bytes.fromhex("ea 60 10 40 00 1b 00")
    elif mutation == "padding_partitioned_by_data":
        data[0x270:0x276] = bytes.fromhex("a1 68 10 40 00 c3")
    elif mutation is not None:
        raise ValueError(f"unknown synthetic CFG mutation: {mutation}")

    return bytes(data)


def write_synthetic_pe(
    tmp_path: Path, *, mutation: str | None = None
) -> Path:
    path = tmp_path / f"synthetic-{mutation or 'valid'}.exe"
    path.write_bytes(synthetic_pe_bytes(mutation=mutation))
    return path


def write_synthetic_cfg_pe(
    tmp_path: Path, *, mutation: str | None = None
) -> Path:
    path = tmp_path / f"synthetic-cfg-{mutation or 'valid'}.exe"
    path.write_bytes(synthetic_cfg_pe_bytes(mutation=mutation))
    return path
