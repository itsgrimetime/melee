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
    elif mutation == "mwcc_padding_encodings":
        data[0x261:0x270] = bytes.fromhex(
            "89 c0 8d 40 00 8d 44 20 00 8d 80 00 00 00 00"
        )
    elif mutation == "closed_unreachable_island":
        data[0x261:0x270] = bytes.fromhex(
            "89 c0 eb 0b 90 90 90 90 90 90 90 90 90 90 90"
        )
    elif mutation == "closed_unreferenced_aligned_function":
        data[0x22B:0x230] = b"\0" * 5
        data[0x230:0x239] = bytes.fromhex(
            "55 8b ec 75 03 c3 90 90 c3"
        )
    elif mutation == "closed_aligned_function_owned_merge":
        data[0x22B:0x230] = b"\0" * 5
        data[0x230:0x240] = bytes.fromhex(
            "55 8b ec 85 c0 74 09 8d 84 20 00 00 00 00 89 c0"
        )
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
    elif mutation == "interior_e8_crosses_owned_instructions":
        struct.pack_into("<I", data, 0x430, 0x1070)
        data[0x270:0x277] = bytes.fromhex("01 e8 00 00 00 00 c3")
    elif mutation == "interior_e8_crosses_zero_function_alignment":
        # Move the FLD operand out of .text and make its call prove the
        # independently aligned function at 0x401080.  The raw E8 at 0x401071
        # begins inside JLE, spans RET, and ends in the zero alignment gap.
        data[0x240:0x246] = bytes.fromhex("dd 05 98 20 40 00")
        data[0x24B:0x250] = bytes.fromhex("e8 30 00 00 00")
        struct.pack_into("<I", data, 0x226, 0x00401080)
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 8, 0x180)
        data[0x270:0x280] = bytes.fromhex(
            "7e e8 c3 00 00 00 00 00 00 00 00 00 00 00 00 00"
        )
        data[0x280:0x288] = bytes.fromhex("90 90 90 90 90 90 90 c3")
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
    elif mutation == "exec_relocation_aligned_prologue":
        data[0x22B:0x230] = b"\0" * 5
        data[0x230:0x23A] = bytes.fromhex(
            "53 56 55 8b 1d 80 20 40 00 c3"
        )
        struct.pack_into("<IIHH", data, 0x800, 0x1000, 12, 0x3035, 0)
    elif mutation == "exec_relocation_branched_prologue":
        data[0x22B:0x230] = b"\0" * 5
        data[0x230:0x23A] = bytes.fromhex(
            "53 c3 90 90 a1 80 20 40 00 c3"
        )
        struct.pack_into("<IIHH", data, 0x800, 0x1000, 12, 0x3035, 0)
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


def synthetic_dispatch_pe_bytes(
    *,
    entry_count: int = 2,
    mode: str = "absolute-jump",
) -> bytes:
    """Return a strict PE with one finite guarded indirect transfer."""
    if not 1 <= entry_count <= 468:
        raise ValueError("entry_count must be between 1 and 468")

    original = synthetic_pe_bytes()
    data = bytearray(0x1600)
    data[:0x400] = original[:0x400]
    data[0x400:0x800] = original[0x400:0x800]
    data[0x1400:0x1600] = original[0x800:0xA00]

    # Keep a compact executable section, grow .rdata for the 468-entry table,
    # and move .reloc after it without changing either section RVA.
    struct.pack_into("<II", data, SECTION_TABLE_OFFSET + 8, 0x100, 0x1000)
    struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x61)
    struct.pack_into("<II", data, SECTION_TABLE_OFFSET + 40 + 8, 0x1000, 0x2000)
    struct.pack_into("<II", data, SECTION_TABLE_OFFSET + 40 + 16, 0x1000, 0x400)
    struct.pack_into("<II", data, SECTION_TABLE_OFFSET + 80 + 16, 0x200, 0x1400)

    text = bytearray(b"\xCC" * 0x100)
    table_va = 0x00402200
    bound = entry_count - 1
    if mode == "base-index-jump":
        dispatch = (
            b"\xBB" + struct.pack("<I", table_va)
            + b"\x3D" + struct.pack("<I", bound)
            + b"\x0F\x87\x09\x00\x00\x00"
            + b"\xFF\x24\x83"
        )
    elif mode == "callback-table":
        dispatch = (
            b"\x3D" + struct.pack("<I", bound)
            + b"\x0F\x87\x08\x00\x00\x00"
            + b"\xFF\x14\x85" + struct.pack("<I", table_va)
            + b"\xC3"
        )
    elif mode == "missing-guard":
        dispatch = b"\xFF\x24\x85" + struct.pack("<I", table_va)
    elif mode == "conflicting-width":
        dispatch = (
            b"\x3D" + struct.pack("<I", bound)
            + b"\x0F\x87\x08\x00\x00\x00"
            + b"\xFF\x24\xC5" + struct.pack("<I", table_va)
        )
    else:
        selected_base = 0x004031FC if mode == "unmapped-entry" else table_va
        dispatch = (
            b"\x3D" + struct.pack("<I", bound)
            + b"\x0F\x87\x08\x00\x00\x00"
            + b"\xFF\x24\x85" + struct.pack("<I", selected_base)
        )
    text[: len(dispatch)] = dispatch
    text[0x20] = 0xC3
    text[0x60] = 0xC3
    if mode in {
        "unowned-relocated-dispatch",
        "unowned-called-function-dispatch",
        "unowned-terminal-jump-dispatch",
        "two-unowned-relocations",
    }:
        if mode == "two-unowned-relocations":
            struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0xBA)
        text[:] = b"\xCC" * len(text)
        text[:6] = bytes.fromhex("e8 29 00 00 00 c3")
        text[0x20] = 0xC3
        text[0x2E:0x30] = bytes.fromhex("c3 00")
        if mode == "unowned-terminal-jump-dispatch":
            text[:6] = bytes.fromhex("e8 26 00 00 00 c3")
            text[0x2B:0x30] = bytes.fromhex("e9 d0 ff ff ff")
        text[0x30:0x42] = (
            b"\x3D" + struct.pack("<I", bound)
            + b"\x0F\x87\x15\x00\x00\x00"
            + b"\xFF\x24\x85" + struct.pack("<I", table_va)
        )
        if mode == "unowned-called-function-dispatch":
            text[0x30:0x47] = (
                bytes.fromhex("e8 eb ff ff ff")
                + b"\x3D" + struct.pack("<I", bound)
                + b"\x0F\x87\x0A\x00\x00\x00"
                + b"\xFF\x24\x85" + struct.pack("<I", table_va)
            )
        text[0x50] = 0xC3
        text[0x60] = 0xC3
        if mode == "two-unowned-relocations":
            text[:6] = bytes.fromhex("e8 a9 00 00 00 c3")
            text[0x2B:0x30] = b"\0" * 5
            text[0x60] = 0xCC
            text[0xAE:0xB0] = bytes.fromhex("c3 00")
            text[0xB0:0xBA] = bytes.fromhex(
                "53 56 55 8b 1d 80 20 40 00 c3"
            )
    elif mode == "unowned-branched-function-dispatch":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0xA1)
        text[:] = b"\xCC" * len(text)
        text[0] = 0xC3
        text[0x20] = 0xC3
        text[0x37:0x40] = b"\0" * 9
        text[0x40:0x4E] = bytes.fromhex(
            "53 e8 da ff ff ff 85 c0 75 26 31 c0 5b c3"
        )
        text[0x70:0x88] = (
            bytes.fromhex("0f b6 c0 83 e8 00")
            + b"\x3D" + struct.pack("<I", bound)
            + b"\x0F\x87\x0F\x00\x00\x00"
            + b"\xFF\x24\x85" + struct.pack("<I", table_va)
        )
        text[0x90:0x92] = bytes.fromhex("5b c3")
        text[0xA0] = 0xC3
    elif mode == "unowned-long-guard-branch-dispatch":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0xA1)
        text[:] = b"\xCC" * len(text)
        text[0] = 0xC3
        text[0x20] = 0xC3
        text[0x2B:0x30] = b"\0" * 5
        text[0x30:0x35] = bytes.fromhex("85 c0 75 0c c3")
        text[0x35:0x65] = b"\x90" * 0x30
        text[0x40:0x44] = bytes.fromhex("85 c0 74 0c")
        text[0x49:0x50] = bytes.fromhex("c3 8d 80 00 00 00 00")
        text[0x65:0x77] = (
            b"\x3D" + struct.pack("<I", bound)
            + b"\x0F\x87\x20\x00\x00\x00"
            + b"\xFF\x24\x85" + struct.pack("<I", table_va)
        )
        text[0x90] = 0xC3
        text[0xA0] = 0xC3
    elif mode == "aligned-branched-relocation":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0xC3)
        text[:] = b"\xCC" * len(text)
        text[0] = 0xC3
        text[0x20] = 0xC3
        text[0xAB:0xB0] = b"\0" * 5
        text[0xB0:0xC3] = bytes.fromhex(
            "53 e8 6a ff ff ff 85 c0 75 02 90 90 "
            "a1 80 20 40 00 5b c3"
        )
    elif mode == "relocation-inline-data":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x56)
        text[:] = b"\xCC" * len(text)
        text[:6] = bytes.fromhex("e8 29 00 00 00 c3")
        text[0x20] = 0xC3
        text[0x2E:0x33] = bytes.fromhex("e9 cd ff ff ff")
        text[0x33:0x50] = b"Hacked by Ninji 2023-07-15 $\x08"
        text[0x50:0x56] = bytes.fromhex("e8 cb ff ff ff c3")
    elif mode == "self-lea-zero-suffix":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x56)
        text[:] = b"\xCC" * len(text)
        text[0] = 0xC3
        text[0x20] = 0xC3
        text[0x2B:0x30] = b"\0" * 5
        text[0x30:0x56] = bytes.fromhex(
            "a1 80 20 40 00 53 85 c0 74 14 8d 80 00 00 00 00 "
            "81 60 02 fd ff ff ff 8b 40 2a 85 c0 75 f2 "
            "8b 1d 80 20 40 00 5b c3"
        )
    elif mode == "self-lea-padding-dispatch":
        text[:] = b"\xCC" * len(text)
        text[:6] = bytes.fromhex("e8 24 00 00 00 c3")
        text[0x20] = 0xC3
        text[0x29] = 0xC3
        text[0x2A:0x30] = bytes.fromhex("8d 80 00 00 00 00")
        text[0x30:0x42] = (
            b"\x3D" + struct.pack("<I", bound)
            + b"\x0F\x87\x15\x00\x00\x00"
            + b"\xFF\x24\x85" + struct.pack("<I", table_va)
        )
        text[0x50] = 0xC3
        text[0x60] = 0xC3
    elif mode == "owned-dispatch-interior":
        text[:] = b"\xCC" * len(text)
        text[0] = 0xC3
        text[0x20] = 0xC3
        text[0x2B:0x30] = b"\0" * 5
        text[0x30:0x48] = (
            bytes.fromhex("53 e8 ea ff ff ff")
            + b"\x3D" + struct.pack("<I", bound)
            + b"\x0F\x87\x0F\x00\x00\x00"
            + b"\xFF\x24\x85" + struct.pack("<I", table_va)
        )
        text[0x50] = 0xC3
        text[0x60] = 0xC3
    elif mode == "owned-relocation-interior":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x3C)
        text[:] = b"\xCC" * len(text)
        text[0] = 0xC3
        text[0x2B:0x30] = b"\0" * 5
        text[0x30:0x3C] = bytes.fromhex(
            "31 c0 31 c9 80 b9 80 20 40 00 00 c3"
        )
    data[0x200:0x300] = text

    # Export a real target and retain the relocation-proven second target.
    export_rva = {
        "owned-dispatch-interior": 0x1041,
        "owned-relocation-interior": 0x1034,
    }.get(mode, 0x1020)
    struct.pack_into("<I", data, 0x430, export_rva)
    struct.pack_into("<I", data, 0x480, 0x00401060)
    if mode in {
        "unowned-relocated-dispatch",
        "unowned-terminal-jump-dispatch",
    }:
        struct.pack_into("<IIHH", data, 0x1400, 0x1000, 12, 0x303E, 0)
    elif mode == "unowned-called-function-dispatch":
        struct.pack_into("<IIHH", data, 0x1400, 0x1000, 12, 0x3043, 0)
    elif mode == "two-unowned-relocations":
        struct.pack_into(
            "<IIHH", data, 0x1400, 0x1000, 12, 0x303E, 0x30B5
        )
    elif mode == "unowned-branched-function-dispatch":
        struct.pack_into("<IIHH", data, 0x1400, 0x1000, 12, 0x3084, 0)
    elif mode == "unowned-long-guard-branch-dispatch":
        struct.pack_into("<IIHH", data, 0x1400, 0x1000, 12, 0x3073, 0)
    elif mode == "aligned-branched-relocation":
        struct.pack_into("<IIHH", data, 0x1400, 0x1000, 12, 0x30BD, 0)
    elif mode == "relocation-inline-data":
        struct.pack_into("<IIHH", data, 0x1400, 0x1000, 12, 0x3040, 0)
    elif mode == "self-lea-zero-suffix":
        struct.pack_into(
            "<IIHH", data, 0x1400, 0x1000, 12, 0x3031, 0x3050
        )
    elif mode == "self-lea-padding-dispatch":
        struct.pack_into("<IIHH", data, 0x1400, 0x1000, 12, 0x303E, 0)
    elif mode == "owned-dispatch-interior":
        struct.pack_into("<IIHH", data, 0x1400, 0x1000, 12, 0x3044, 0)
    elif mode == "owned-relocation-interior":
        struct.pack_into("<IIHH", data, 0x1400, 0x1000, 12, 0x3036, 0)
    else:
        struct.pack_into("<IIHH", data, 0x1400, 0x2000, 12, 0x3080, 0)
    second_target = (
        0x004010A0
        if mode
        in {
            "unowned-branched-function-dispatch",
            "unowned-long-guard-branch-dispatch",
        }
        else (
            0x004010AE
            if mode == "two-unowned-relocations"
            else 0x00401060
        )
    )
    targets = tuple(
        0x00401020 if index % 2 == 0 else second_target
        for index in range(entry_count)
    )
    if mode == "target-outside-text":
        targets = (0x00402000, *targets[1:])
    table_offset = 0x15FC if mode == "unmapped-entry" else 0x600
    for index, target in enumerate(targets):
        section_end = 0x1600 if mode == "unmapped-entry" else 0x1400
        if table_offset + index * 4 + 4 <= section_end:
            struct.pack_into("<I", data, table_offset + index * 4, target)

    return bytes(data)


def write_synthetic_dispatch_pe(
    tmp_path: Path,
    *,
    entry_count: int = 2,
    mode: str = "absolute-jump",
) -> Path:
    path = tmp_path / f"synthetic-dispatch-{mode}-{entry_count}.exe"
    path.write_bytes(
        synthetic_dispatch_pe_bytes(entry_count=entry_count, mode=mode)
    )
    return path
