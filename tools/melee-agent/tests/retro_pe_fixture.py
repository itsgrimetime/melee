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
    elif mutation in {"global_callback_slot", "bss_global_callback_slot"}:
        struct.pack_into("<I", data, 0x226, 0x00401060)
        slot = 0x00402300 if mutation == "bss_global_callback_slot" else 0x004020A0
        data[0x270:0x280] = bytes.fromhex(
            "b8 60 10 40 00 a3"
        ) + struct.pack("<I", slot) + bytes.fromhex("ff 25") + struct.pack(
            "<I", slot
        )
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

    text = bytearray(b"\xCC" * 0x200)
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
    elif mode == "nonadjacent-guard":
        dispatch = (
            b"\x3D" + struct.pack("<I", bound)
            + b"\x89\xC1"
            + b"\x0F\x87\x13\x00\x00\x00"
            + b"\xFF\x24\x85" + struct.pack("<I", table_va)
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
    elif mode == "byte-return-table":
        text[:] = b"\xCC" * len(text)
        text[0x00:0x10] = bytes.fromhex(
            "e8 2b 00 00 00 0f bf d8 "
            "ff 14 9d 00 22 40 00 c3"
        )
        text[0x20] = 0xC3
        text[0x30:0x38] = bytes.fromhex(
            "0f b6 05 00 23 40 00 c3"
        )
        text[0x60] = 0xC3
    elif mode == "cdecl-spill-callback":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        text[0x00:0x10] = bytes.fromhex(
            "68 90 10 40 00 e8 26 00 00 00 59 c3 cc cc cc cc"
        )
        text[0x30:0x43] = bytes.fromhex(
            "55 89 e5 83 ec 10 8b 45 08 89 45 f0 "
            "ff 55 f0 89 ec 5d c3"
        )
        text[0x90] = 0xC3
    elif mode == "cdecl-esp-callback":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        text[0x00:0x10] = bytes.fromhex(
            "68 90 10 40 00 e8 26 00 00 00 59 c3 cc cc cc cc"
        )
        text[0x30:0x35] = bytes.fromhex("ff 54 24 04 c3")
        text[0x90] = 0xC3
        text[0xA0] = 0xC3
    elif mode in {"guarded-equal-callback", "guarded-equal-clobber"}:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        if mode == "guarded-equal-clobber":
            program = bytes.fromhex(
                "8b 5c 24 04 81 fb 90 10 40 00 75 0e 89 cb "
                "53 e8 1c 00 00 00 59 c3 cc cc cc cc 31 c0 c3"
            )
        else:
            program = bytes.fromhex(
                "8b 5c 24 04 81 fb 90 10 40 00 75 0c "
                "53 e8 1e 00 00 00 59 c3 cc cc cc cc 31 c0 c3"
            )
        text[: len(program)] = program
        text[0x30:0x35] = bytes.fromhex("ff 54 24 04 c3")
        text[0x90] = 0xC3
    elif mode in {"outparam-callback", "outparam-conditional-callback"}:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        text[0x00:0x17] = bytes.fromhex(
            "83 ec 08 8d 04 24 50 e8 24 00 00 00 59 "
            "8b 44 24 04 83 c4 08 ff d0 c3"
        )
        if mode == "outparam-conditional-callback":
            text[0x30:0x40] = bytes.fromhex(
                "8b 44 24 04 85 c9 74 07 c7 40 04 90 10 40 00 c3"
            )
        else:
            text[0x30:0x3C] = bytes.fromhex(
                "8b 44 24 04 c7 40 04 90 10 40 00 c3"
            )
        text[0x90] = 0xC3
    elif mode in {
        "cdecl-cross-block-callback",
        "cdecl-cross-block-clobber",
    }:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        text[0x00:0x10] = bytes.fromhex(
            "68 90 10 40 00 e8 26 00 00 00 59 c3 cc cc cc cc"
        )
        if mode == "cdecl-cross-block-clobber":
            text[0x30:0x41] = bytes.fromhex(
                "53 8b 5c 24 08 85 c0 74 04 89 cb 90 90 ff d3 5b c3"
            )
        else:
            text[0x30:0x3F] = bytes.fromhex(
                "53 8b 5c 24 08 85 c0 74 02 90 90 ff d3 5b c3"
            )
        text[0x90] = 0xC3
    elif mode in {
        "cdecl-recursive-callback",
        "cdecl-recursive-unknown",
    }:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        text[0x00:0x10] = bytes.fromhex(
            "68 90 10 40 00 e8 26 00 00 00 59 c3 cc cc cc cc"
        )
        recursive_push = "51" if mode == "cdecl-recursive-unknown" else "53"
        text[0x30:0x46] = bytes.fromhex(
            "53 8b 5c 24 08 ff d3 85 c0 74 09 "
            + recursive_push
            + " e8 ef ff ff ff 59 ff d3 5b c3"
        )
        text[0x90] = 0xC3
    elif mode in {
        "cdecl-forwarder-chain",
        "cdecl-forwarder-chain-alternate-caller",
        "cdecl-forwarder-chain-overwrite",
        "cdecl-forwarder-chain-ebp-complex",
        "cdecl-forwarder-chain-ebp-clobber",
    }:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        # Root: one exact relocated callback is forwarded as argument zero.
        text[0x00:0x0C] = bytes.fromhex(
            "68 90 10 40 00 e8 66 00 00 00 59 c3"
        )
        # Terminal forwarder: argument two feeds five separate callbacks.
        terminal = (
            "55 89 e5 "
            + ("89 4d 10 " if mode == "cdecl-forwarder-chain-overwrite" else "")
            + "ff 55 10 ff 55 10 ff 55 10 ff 55 10 ff 55 10 5d c3"
        )
        text[0x30 : 0x30 + len(bytes.fromhex(terminal))] = bytes.fromhex(
            terminal
        )
        # Middle wrapper forwards its unchanged argument zero as argument two.
        if mode == "cdecl-forwarder-chain-ebp-complex":
            middle = bytes.fromhex(
                "55 89 e5 85 c0 74 01 53 ff 75 08 6a 00 6a 00 "
                "e8 ac ff ff ff 83 c4 0c 89 ec 5d c3"
            )
        elif mode == "cdecl-forwarder-chain-ebp-clobber":
            middle = bytes.fromhex(
                "55 89 e5 89 cd ff 75 08 6a 00 6a 00 "
                "e8 af ff ff ff 83 c4 0c 89 ec 5d c3 cc"
            )
        else:
            middle = bytes.fromhex(
                "55 89 e5 ff 75 08 6a 00 6a 00 "
                "e8 ac ff ff ff 83 c4 0c 5d c3 cc cc cc cc cc"
            )
        text[0x70 : 0x70 + len(middle)] = middle
        text[0x90] = 0xC3
        if mode == "cdecl-forwarder-chain-alternate-caller":
            # An independently reachable caller supplies an unknown value.
            text[0xA0:0xAC] = bytes.fromhex(
                "51 e8 ca ff ff ff 59 c3 cc cc cc cc"
            )
    elif mode == "external-code-pointer-escape":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        text[0x00:0x0C] = bytes.fromhex(
            "68 90 10 40 00 ff 15 60 21 40 00 c3"
        )
        text[0x90] = 0xC3
    elif mode in {
        "signed-byte-domain-table",
        "signed-byte-domain-exact-spill",
        "signed-byte-domain-one-sided",
        "signed-byte-domain-admits-sixteen",
        "signed-byte-domain-bad-slot",
        "signed-byte-domain-relocations-only",
    }:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        lower = "80 3b 00 7c 16"
        upper = "80 3b 10 7d 11"
        if mode == "signed-byte-domain-one-sided":
            lower = "90 90 90 90 90"
        elif mode == "signed-byte-domain-admits-sixteen":
            upper = "80 3b 10 7f 11"
        elif mode == "signed-byte-domain-relocations-only":
            lower = upper = "90 90 90 90 90"
        if mode == "signed-byte-domain-exact-spill":
            signed_program = bytes.fromhex(
                "53 8b 5c 24 08 80 3b 00 7c 26 80 3b 10 7d 21 "
                "53 53 53 0f be 03 89 44 24 08 89 c3 "
                "ff 14 9d 00 23 40 00 83 c4 0c 5b c3 "
                "cc cc cc cc cc cc cc cc cc 31 c0 5b c3"
            )
            text[0 : len(signed_program)] = signed_program
        else:
            text[0x00:0x20] = bytes.fromhex(
                "53 8b 5c 24 08 "
                + lower
                + upper
                + "0f be 03 89 c3 ff 14 9d 00 23 40 00 5b c3 cc cc cc"
            )
            text[0x20:0x24] = bytes.fromhex("31 c0 5b c3")
        text[0x90] = 0xC3
    elif mode in {
        "zero-guarded-callback",
        "zero-unguarded-callback",
        "mixed-zero-nonzero-guarded-callback",
        "zero-loop-guarded-callback",
        "zero-loop-clobbered-callback",
        "noreturn-guarded-callback",
        "returning-guarded-callback",
        "zero-distant-guarded-callback",
        "zero-distant-unguarded-callback",
    }:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        text[0x00:0x09] = bytes.fromhex(
            "6a 00 e8 29 00 00 00 59 c3"
        )
        if mode == "mixed-zero-nonzero-guarded-callback":
            text[0x00:0x14] = bytes.fromhex(
                "6a 00 e8 29 00 00 00 59 "
                "68 90 10 40 00 e8 1e 00 00 00 59 c3"
            )
        if mode == "zero-guarded-callback":
            text[0x30:0x3D] = bytes.fromhex(
                "53 8b 5c 24 08 85 db 74 02 ff d3 5b c3"
            )
        elif mode == "mixed-zero-nonzero-guarded-callback":
            text[0x30:0x3D] = bytes.fromhex(
                "53 8b 5c 24 08 85 db 74 02 ff d3 5b c3"
            )
        elif mode == "zero-loop-guarded-callback":
            text[0x30:0x3D] = bytes.fromhex(
                "53 8b 5c 24 08 85 db 74 02 ff d3 eb f8"
            )
        elif mode == "zero-loop-clobbered-callback":
            text[0x30:0x44] = bytes.fromhex(
                "53 8b 5c 24 08 85 db 74 02 ff d3 "
                "bb 90 10 40 00 eb f3 cc cc"
            )
        elif mode in {
            "noreturn-guarded-callback",
            "returning-guarded-callback",
        }:
            text[0x30:0x42] = bytes.fromhex(
                "53 8b 5c 24 08 85 db 75 05 e8 32 00 00 00 "
                "ff d3 5b c3"
            )
            text[0x70:0x77] = (
                bytes.fromhex("ff 15 60 21 40 00 c3")
                if mode == "noreturn-guarded-callback"
                else bytes.fromhex("c3 cc cc cc cc cc cc")
            )
        elif mode == "zero-distant-guarded-callback":
            text[0x30:0x3D] = bytes.fromhex(
                "53 8b 5c 24 08 85 db 0f 84 95 00 00 00"
            )
            text[0x3D:0xD0] = b"\x41" * (0xD0 - 0x3D)
            text[0xD0:0xD4] = bytes.fromhex("ff d3 5b c3")
        elif mode == "zero-distant-unguarded-callback":
            text[0x30:0x35] = bytes.fromhex("53 8b 5c 24 08")
            text[0x35:0xD0] = b"\x41" * (0xD0 - 0x35)
            text[0xD0:0xD4] = bytes.fromhex("ff d3 5b c3")
        else:
            text[0x30:0x39] = bytes.fromhex(
                "53 8b 5c 24 08 ff d3 5b c3"
            )
        text[
            0xF0
            if mode in {
                "zero-distant-guarded-callback",
                "zero-distant-unguarded-callback",
            }
            else 0x90
        ] = 0xC3
    elif mode == "linear-prologue-conflicting-tail":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        text[0x00:0x12] = bytes.fromhex(
            "53 56 55 83 ec 10 8b 6c 24 20 "
            "85 c0 74 01 50 31 c0 c3"
        )
        text[0x20] = 0xC3
        text[0x60] = 0xC3
    elif mode in {
        "constructor-field-callback",
        "constructor-field-ebp-callback",
        "constructor-field-stack-decoy",
        "constructor-field-late-finite-write",
        "constructor-field-unknown-write",
    }:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        if mode == "constructor-field-stack-decoy":
            text[0x00:0x1A] = bytes.fromhex(
                "c7 84 24 04 01 00 00 20 23 40 00 "
                "e8 20 00 00 00 8b 98 04 01 00 00 ff 53 04 c3"
            )
        elif mode == "constructor-field-ebp-callback":
            text[0x00:0x11] = bytes.fromhex(
                "e8 2b 00 00 00 89 c5 8b ad 04 01 00 00 ff 55 04 c3"
            )
        else:
            text[0x00:0x0F] = bytes.fromhex(
                "e8 2b 00 00 00 8b 98 04 01 00 00 ff 53 04 c3"
            )
        text[0x30:0x3B] = bytes.fromhex(
            "c7 80 04 01 00 00 00 23 40 00 c3"
        )
        if mode == "constructor-field-late-finite-write":
            text[0x90:0x96] = bytes.fromhex("e8 3b 00 00 00 c3")
            text[0xA0] = 0xC3
            text[0xD0:0xDB] = bytes.fromhex(
                "c7 80 04 01 00 00 20 23 40 00 c3"
            )
            struct.pack_into("<I", data, 0x724, 0x004010A0)
        else:
            if mode == "constructor-field-unknown-write":
                text[0x3A:0x41] = bytes.fromhex(
                    "89 88 04 01 00 00 c3"
                )
            text[0x90] = 0xC3
        struct.pack_into("<I", data, 0x704, 0x00401090)
    elif mode in {
        "validated-constructor-descriptor",
        "validated-constructor-descriptor-different-writer",
        "validated-constructor-descriptor-alternate-producer",
        "validated-constructor-descriptor-changed-descriptor",
        "validated-constructor-descriptor-tag-only",
        "validated-constructor-descriptor-incomplete-initializer-domain",
        "validated-constructor-descriptor-retail-guard-arms",
        "validated-constructor-descriptor-wrapper-global",
        "validated-constructor-descriptor-wrapper-global-double",
        "validated-constructor-descriptor-wrapper-global-double-unrelocated",
        "validated-constructor-descriptor-wrapper-global-alternate-writer",
        "validated-constructor-descriptor-wrapper-global-incomplete-domain",
        "validated-constructor-descriptor-forwarded-global-switch",
        "validated-constructor-descriptor-forwarded-global-switch-unknown-tag",
        "validated-constructor-descriptor-forwarded-global-switch-hidden-caller",
        "validated-constructor-descriptor-forwarded-global-switch-alternate-writer",
        "validated-constructor-descriptor-multi-tag",
        "validated-constructor-descriptor-multi-tag-rejected-only",
        "validated-constructor-descriptor-multi-tag-same-tag",
        "validated-constructor-descriptor-multi-tag-unknown-tag",
    }:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        wrapper_global = mode.startswith(
            "validated-constructor-descriptor-wrapper-global"
        )
        forwarded_global_switch = mode.startswith(
            "validated-constructor-descriptor-forwarded-global-switch"
        )
        multi_tag = mode.startswith(
            "validated-constructor-descriptor-multi-tag"
        )
        if forwarded_global_switch:
            struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 8, 0x200)
            struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x200)
            # Two fresh-object factories feed one forwarded switch.  Both
            # switch arms call the sole loader-zero global writer, matching
            # the retail Pars path without making either call site special.
            pass
        elif multi_tag:
            # Two closed fresh-object producers reach the same validated
            # consumer.  The exported alternate factory calls the primary
            # factory after its own consumer call, making both caller domains
            # reachable without treating either constructor as an export.
            text[0x00:0x23] = bytes.fromhex(
                "6a 38 e8 d9 00 00 00 59 89 c3 85 db 74 12 "
                "89 d9 e8 8b 00 00 00 53 e8 40 00 00 00 59 c3 "
                "cc cc cc 31 c0 c3"
            )
            text[0x30:0x58] = bytes.fromhex(
                "6a 38 e8 a9 00 00 00 59 89 c3 85 db 74 17 "
                "89 d9 e8 7b 00 00 00 53 e8 10 00 00 00 59 "
                "e8 af ff ff ff c3 cc cc cc 31 c0 c3"
            )
            text[0x60:0x7A] = bytes.fromhex(
                "ff 74 24 04 e8 17 00 00 00 59 85 c0 74 0b "
                "8b 98 34 00 00 00 ff 53 04 c3 cc c3"
            )
            if mode == (
                "validated-constructor-descriptor-multi-tag-rejected-only"
            ):
                text[0x15:0x1D] = bytes.fromhex(
                    "c3 cc cc cc cc cc cc cc"
                )
        elif mode == "validated-constructor-descriptor-tag-only":
            text[0x00:0x0C] = bytes.fromhex(
                "68 00 25 40 00 e8 46 00 00 00 59 c3"
            )
            struct.pack_into("<I", data, 0x920, 0x50617273)
            struct.pack_into("<I", data, 0x934, 0x00402400)
        elif wrapper_global:
            factory = bytes.fromhex(
                "6a 38 e8 d9 00 00 00 59 89 c3 85 db 74 22 "
                "89 d9 e8 8b 00 00 00 bf 00 26 40 00 89 5f 0c "
                "ff 77 0c ff 15 40 26 40 00 59 e8 24 00 00 00 "
                "c3 cc cc cc c7 44 24 34 00 00 00 00 31 c0 c3"
            )
            text[: len(factory)] = factory
        else:
            factory = bytearray(
                bytes.fromhex(
                    "6a 38 e8 d9 00 00 00 59 89 c3 85 db 74 12 "
                    "89 d9 e8 8b 00 00 00"
                )
            )
            if mode in {
                "validated-constructor-descriptor-different-writer",
                "validated-constructor-descriptor-changed-descriptor",
            }:
                factory.extend(bytes.fromhex("89 d9 e8 b4 00 00 00"))
            factory.extend(b"\x53\xE8")
            call_end = len(factory) + 4
            factory.extend(struct.pack("<i", 0x50 - call_end))
            factory.extend(bytes.fromhex("59 c3"))
            if len(factory) > 0x20:
                factory[0x0D] = 0x1A
            text[: len(factory)] = factory
            failure = 0x28 if len(factory) > 0x20 else 0x20
            text[failure : failure + 3] = bytes.fromhex("31 c0 c3")
        # Consumer accepts only the validator's non-null identity return.
        if forwarded_global_switch:
            text[0x50:0x6C] = bytes.fromhex(
                "ff 35 00 27 40 00 e8 25 00 00 00 59 85 c0 74 0b "
                "8b 98 34 00 00 00 ff 53 04 c3 cc c3"
            )
        elif multi_tag:
            pass
        elif mode.startswith(
            "validated-constructor-descriptor-wrapper-global-double"
        ):
            text[0x50:0x6D] = bytes.fromhex(
                "a1 10 27 40 00 ff 30 e8 24 00 00 00 59 85 c0 74 0b "
                "8b 98 34 00 00 00 ff 53 04 c3 cc c3"
            )
            text[0x70:0x7A] = bytes.fromhex(
                "8b 44 24 04 a3 00 27 40 00 c3"
            )
        elif wrapper_global:
            text[0x50:0x6C] = bytes.fromhex(
                "ff 35 00 27 40 00 e8 25 00 00 00 59 85 c0 74 0b "
                "8b 98 34 00 00 00 ff 53 04 c3 cc c3"
            )
            text[0x70:0x7A] = bytes.fromhex(
                "8b 44 24 04 a3 00 27 40 00 c3"
            )
        elif mode == "validated-constructor-descriptor-retail-guard-arms":
            text[0x50:0x70] = bytes.fromhex(
                "ff 74 24 04 e8 27 00 00 00 59 85 c0 74 02 eb 06 "
                "31 c0 90 90 90 c3 8b 98 34 00 00 00 ff 53 04 c3"
            )
        else:
            text[0x50:0x6A] = bytes.fromhex(
                "ff 74 24 04 e8 27 00 00 00 59 85 c0 74 0b "
                "8b 98 34 00 00 00 ff 53 04 c3 cc c3"
            )
        # Validator identity-returns exactly a non-null object with the tag.
        text[0x80:0x98] = bytes.fromhex(
            "8b 44 24 04 85 c0 74 0a "
            "81 78 20 73 72 61 50 75 01 c3 31 c0 c3 cc cc cc"
        )
        # The constructor establishes both the tag and descriptor field.
        descriptor = (
            0x00402420
            if mode == "validated-constructor-descriptor-changed-descriptor"
            else 0x00402400
        )
        text[0xA0:0xB5] = (
            bytes.fromhex("c7 81 20 00 00 00 73 72 61 50")
            + bytes.fromhex("c7 81 34 00 00 00")
            + struct.pack("<I", descriptor)
            + b"\xC3"
        )
        if multi_tag:
            alternate_tag = (
                0x50617273
                if mode.endswith("same-tag")
                else 0x436F6D70
            )
            if mode.endswith("unknown-tag"):
                text[0xC0:0xC7] = bytes.fromhex(
                    "89 91 20 00 00 00 c3"
                )
            else:
                text[0xC0:0xCB] = (
                    bytes.fromhex("c7 81 20 00 00 00")
                    + struct.pack("<I", alternate_tag)
                    + b"\xC3"
                )
        if mode == "validated-constructor-descriptor-alternate-producer":
            text[0xC0:0xCC] = bytes.fromhex(
                "ff 74 24 04 e8 87 ff ff ff 59 c3 cc"
            )
        elif mode == (
            "validated-constructor-descriptor-incomplete-initializer-domain"
        ):
            text[0xC0:0xCA] = bytes.fromhex(
                "8b 4c 24 04 e8 d7 ff ff ff c3"
            )
        elif mode == (
            "validated-constructor-descriptor-wrapper-global-alternate-writer"
        ):
            text[0xC0:0xCA] = bytes.fromhex(
                "8b 44 24 04 a3 00 27 40 00 c3"
            )
        elif mode == (
            "validated-constructor-descriptor-wrapper-global-incomplete-domain"
        ):
            text[0xC0:0xCA] = bytes.fromhex(
                "51 ff 15 40 26 40 00 59 c3 cc"
            )
        if mode == "validated-constructor-descriptor-different-writer":
            text[0xD0:0xD8] = bytes.fromhex(
                "89 89 34 00 00 00 c3 cc"
            )
        elif mode == "validated-constructor-descriptor-changed-descriptor":
            text[0xD0:0xDB] = bytes.fromhex(
                "c7 81 34 00 00 00 20 24 40 00 c3"
            )
        text[0xE0] = 0xC3
        text[0xF0] = 0xC3
        struct.pack_into("<I", data, 0x804, 0x004010F0)
        if forwarded_global_switch:
            # Forwarder/switch: every arm forwards arg0 to the same writer.
            text[0x100:0x11E] = bytes.fromhex(
                "8b 44 24 04 83 3d 20 27 40 00 00 74 09 50 "
                "e8 1d 00 00 00 59 c3 cc 50 e8 14 00 00 00 59 c3"
            )
            text[0x130:0x13A] = bytes.fromhex(
                "8b 44 24 04 a3 00 27 40 00 c3"
            )
            # Generic tag initializer.  The hostile variant accepts an open
            # tag argument instead of the caller's guarded immediate.
            text[0x140:0x14F] = bytes.fromhex(
                "8b 44 24 04 89 41 20 c2 04 00 cc cc cc cc cc"
            )
            text[0x160:0x1AA] = bytes.fromhex(
                "56 6a 38 e8 78 ff ff ff 59 89 c3 85 db 74 13 89 d9 "
                "e8 2a ff ff ff 53 e8 84 ff ff ff 59 e8 ce fe ff ff "
                "6a 38 e8 57 ff ff ff 59 89 c6 85 f6 74 18 89 f1 68 "
                "70 6d 6f 43 e8 a4 ff ff ff 56 e8 5e ff ff ff 59 e8 "
                "a8 fe ff ff 5e c3"
            )
            if mode.endswith("unknown-tag"):
                text[0x192:0x197] = bytes.fromhex("ff 74 24 08 90")
            elif mode.endswith("hidden-caller"):
                # Raw but unreachable E8 into the switch must make its caller
                # domain open even though ordinary decoding never owns it.
                text[0x1B0:0x1B5] = bytes.fromhex("e8 4b ff ff ff")
            elif mode.endswith("alternate-writer"):
                text[0x1A8:0x1AF] = bytes.fromhex(
                    "e8 13 00 00 00 5e c3"
                )
                text[0x1C0:0x1C8] = bytes.fromhex(
                    "89 0d 00 27 40 00 c3 cc"
                )
        if wrapper_global:
            struct.pack_into("<I", data, 0xA40, 0x00401070)
        if mode.startswith(
            "validated-constructor-descriptor-wrapper-global-double"
        ):
            struct.pack_into("<I", data, 0xB10, 0x00402700)
    elif mode in {
        "copied-descriptor-callback",
        "copied-descriptor-unknown-source",
        "copied-descriptor-six-movsd-decoy",
        "copied-descriptor-cross-block-clobber",
        "copied-descriptor-unproven-object",
        "copied-descriptor-forwarded-object",
        "copied-descriptor-source-forwarded-object",
        "copied-descriptor-source-forwarded-object-unknown",
        "copied-descriptor-wrapper-returned-object",
        "copied-descriptor-wrapper-returned-object-unknown-return",
        "copied-descriptor-field-forwarded-object",
        "copied-descriptor-field-forwarded-object-unknown-write",
        "copied-descriptor-field-forwarded-object-null-branch",
        "copied-descriptor-field-forwarded-object-unknown-branch",
        "copied-descriptor-field-list-returned-object",
        "copied-descriptor-field-list-returned-object-unknown-insert",
        "copied-descriptor-field-list-returned-object-runtime-zeroed",
        "copied-descriptor-field-list-returned-object-runtime-nonzero",
        "copied-descriptor-registered-object",
        "copied-descriptor-registered-object-back-reference",
        "copied-descriptor-registered-object-global-pointer-back-reference",
        "copied-descriptor-registered-object-global-pointer-hostile-back-reference",
        "copied-descriptor-registered-object-stack-forwarded-back-reference",
        "copied-descriptor-registered-object-link-cursor",
        "copied-descriptor-registered-object-link-cursor-post-clobber",
        "copied-descriptor-registered-object-link-cursor-unknown",
        "copied-descriptor-registered-object-runtime-global-field",
        "copied-descriptor-registered-object-guarded-runtime-global-field",
        "copied-descriptor-registered-object-guarded-runtime-global-field-clobber",
        "copied-descriptor-registered-object-runtime-global-field-unknown",
        "copied-descriptor-registered-object-stack-return",
        "copied-descriptor-registered-object-stack-return-unknown",
        "copied-descriptor-registered-object-unknown-writer",
        "copied-descriptor-registered-object-cursor-lookup",
        "copied-descriptor-registered-object-unknown-cursor-lookup",
        "copied-descriptor-slot-zero-hypothesis",
        "copied-descriptor-slot-zero-correlated-sources",
        "copied-descriptor-slot-zero-tagged-rejected-callback",
        "copied-descriptor-slot-zero-tagged-rejected-callback-missing-stamper",
        "copied-descriptor-slot-zero-tagged-rejected-callback-same-tag",
        "copied-descriptor-slot-zero-tagged-rejected-callback-unrelocated-provider",
        "copied-descriptor-slot-zero-hidden-caller",
        "copied-descriptor-slot-zero-unrelocated-record",
        "copied-descriptor-object-hypothesis-chain",
    }:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        text[0x00:0x1A] = bytes.fromhex(
            "6a 00 6a 00 68 00 23 40 00 e8 52 00 00 00 "
            "83 c4 0c 50 e8 19 00 00 00 83 c4 04 c3"
        )
        slot_zero_hypothesis = mode.startswith(
            "copied-descriptor-slot-zero-"
        ) or mode == "copied-descriptor-object-hypothesis-chain"
        if slot_zero_hypothesis:
            text[0x00:0x1C] = bytes.fromhex(
                "6a 00 6a 00 68 00 23 40 00 e8 52 00 00 00 "
                "83 c4 0c ff 74 24 04 e8 16 00 00 00 59 c3"
            )
        elif mode == "copied-descriptor-unknown-source":
            text[0x11:0x1F] = bytes.fromhex(
                "6a 00 6a 00 51 e8 45 00 00 00 83 c4 0c 50"
            )
            text[0x1F:0x27] = bytes.fromhex(
                "e8 0c 00 00 00 83 c4 04"
            )
            text[0x27] = 0xC3
        elif mode == "copied-descriptor-unproven-object":
            text[0x11:0x1F] = bytes.fromhex(
                "ff 74 24 04 e8 16 00 00 00 83 c4 04 c3 cc"
            )
        elif mode == "copied-descriptor-forwarded-object":
            text[0x12:0x17] = bytes.fromhex("e8 31 00 00 00")
            text[0x48:0x58] = bytes.fromhex(
                "53 8b 5c 24 08 53 e8 dd ff ff ff 59 5b c2 04 00"
            )
        elif mode.startswith("copied-descriptor-source-forwarded-object"):
            forwarded_source = (
                "00 24 40 00" if mode.endswith("unknown") else "00 23 40 00"
            )
            text[0x11:0x28] = bytes.fromhex(
                "50 e8 31 00 00 00 83 c4 04 68 "
                + forwarded_source
                + " e8 24 00 00 00 83 c4 04 c3"
            )
            text[0x48:0x58] = bytes.fromhex(
                "53 8b 5c 24 08 53 e8 dd ff ff ff 59 5b c2 04 00"
            )
        elif mode.startswith("copied-descriptor-wrapper-returned-object"):
            struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 8, 0x200)
            struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x200)
            text[0xA:0xE] = bytes.fromhex("42 01 00 00")
            if mode.endswith("unknown-return"):
                text[0x151:0x170] = bytes.fromhex(
                    "85 c9 74 06 e8 47 00 00 00 c3 "
                    "ff 74 24 0c ff 74 24 0c ff 74 24 0c "
                    "e8 f5 fe ff ff 83 c4 0c c3"
                )
                text[0x1A1] = 0xC3
            else:
                text[0x151:0x166] = bytes.fromhex(
                    "ff 74 24 0c ff 74 24 0c ff 74 24 0c "
                    "e8 ff fe ff ff 83 c4 0c c3"
                )
        elif mode.startswith("copied-descriptor-field-forwarded-object"):
            struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 8, 0x200)
            struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x200)
            entry = bytearray.fromhex(
                "6a 00 6a 00 68 00 23 40 00 e8 52 00 00 00 "
                "83 c4 0c bb 00 26 40 00"
            )
            if mode.endswith("null-branch"):
                entry.extend(
                    bytes.fromhex(
                        "85 c9 74 05 89 43 34 eb 07 "
                        "c7 43 34 00 00 00 00"
                    )
                )
            elif mode.endswith("unknown-branch"):
                entry.extend(
                    bytes.fromhex(
                        "85 c9 74 05 89 43 34 eb 03 89 4b 34"
                    )
                )
            else:
                entry.extend(bytes.fromhex("89 43 34"))
            if mode.endswith("unknown-write"):
                entry.extend(bytes.fromhex("ff 74 24 04 53"))
                call_offset = len(entry)
                entry.append(0xE8)
                entry.extend(struct.pack("<i", 0x150 - (call_offset + 5)))
                entry.extend(bytes.fromhex("83 c4 08"))
            entry.extend(bytes.fromhex("53"))
            call_offset = len(entry)
            entry.append(0xE8)
            entry.extend(struct.pack("<i", 0x48 - (call_offset + 5)))
            entry.extend(bytes.fromhex("83 c4 04 c3"))
            text[: len(entry)] = entry
            text[0x48:0x59] = bytes.fromhex(
                "53 8b 5c 24 08 8b 4b 34 51 e8 da ff ff ff "
                "59 5b c3"
            )
            if mode.endswith("unknown-write"):
                # The common legacy fixed-copy template below contracts its
                # slice by one byte, so later synthetic functions are staged
                # one byte high here and land at their advertised VAs.
                text[0x151:0x15D] = bytes.fromhex(
                    "8b 44 24 04 8b 4c 24 08 89 48 34 c3"
                )
        elif mode.startswith("copied-descriptor-field-list-returned-object"):
            struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 8, 0x200)
            struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x200)
            text[0x12:0x17] = bytes.fromhex("e8 f9 00 00 00")

            runtime_container = "runtime-" in mode
            builder = bytearray.fromhex("53")

            def emit_builder(hex_bytes):
                builder.extend(bytes.fromhex(hex_bytes))

            def emit_builder_call(target):
                # The common legacy fixed-copy template below contracts its
                # slice by one byte.  Stage this synthetic function one byte
                # high so its prologue and internal call targets land at the
                # advertised addresses after that contraction.
                call_offset = 0x111 + len(builder)
                builder.append(0xE8)
                builder.extend(
                    struct.pack("<i", target - (call_offset + 5))
                )

            if runtime_container:
                emit_builder_call(0x1D1)
                emit_builder("a3 00 29 40 00")
            emit_builder("bb 00 26 40 00 8b 4c 24 08 89 4b 34")
            emit_builder("a1 00 29 40 00 83 c0 20 53 50")
            emit_builder_call(0x181)
            emit_builder("59 59")
            if mode.endswith("unknown-insert"):
                emit_builder(
                    "a1 00 29 40 00 83 c0 20 "
                    "68 00 27 40 00 50"
                )
                emit_builder_call(0x181)
                emit_builder("59 59")
            emit_builder("6a 00 a1 00 29 40 00 83 c0 20 50")
            emit_builder_call(0x161)
            emit_builder("59 59 50")
            emit_builder_call(0x48)
            emit_builder("59 5b c3")
            text[0x111 : 0x111 + len(builder)] = builder
            text[0x48:0x59] = bytes.fromhex(
                "53 8b 5c 24 08 8b 4b 34 51 e8 da ff ff ff "
                "59 5b c3"
            )
            text[0x161:0x168] = bytes.fromhex(
                "8b 4c 24 04 8b 01 c3"
            )
            text[0x181:0x192] = bytes.fromhex(
                "8b 54 24 04 8d 12 8b 44 24 08 "
                "8b 0a 89 08 89 02 c3"
            )
            if runtime_container:
                zeroer = bytearray.fromhex(
                    "8b 54 24 04 57 55 8b 6c 24 10 55 52"
                )
                call_offset = 0x1A1 + len(zeroer)
                zeroer.append(0xE8)
                zeroer.extend(
                    struct.pack("<i", 0xE1 - (call_offset + 5))
                )
                zeroer.extend(
                    bytes.fromhex(
                        "89 c2 59 31 c0 59 89 e9 89 d7 f3 aa "
                        "89 d0 5d 5f c3"
                    )
                )
                if mode.endswith("runtime-nonzero"):
                    zeroer[20:22] = bytes.fromhex("b0 01")
                text[0x1A1 : 0x1A1 + len(zeroer)] = zeroer

                constructor = bytearray.fromhex(
                    "68 00 01 00 00 6a 00 e8"
                )
                constructor.extend(
                    struct.pack("<i", 0x1A1 - (0x1D1 + 12))
                )
                constructor.extend(bytes.fromhex("83 c4 08 c3"))
                text[0x1D1 : 0x1D1 + len(constructor)] = constructor
                struct.pack_into("<I", data, 0xD00, 0)
            else:
                struct.pack_into("<I", data, 0xD00, 0x00402A00)
        elif mode.startswith("copied-descriptor-registered-object"):
            struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 8, 0x200)
            struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x200)
            entry = bytearray.fromhex(
                "6a 00 6a 00 68 00 23 40 00 e8 52 00 00 00 "
                "83 c4 0c 50"
            )

            def emit_entry_call(target):
                call_offset = len(entry)
                entry.append(0xE8)
                entry.extend(struct.pack("<i", target - (call_offset + 5)))

            emit_entry_call(0x150)
            entry.extend(bytes.fromhex("59"))
            if mode.endswith("unknown-writer"):
                entry.extend(bytes.fromhex("ff 74 24 04"))
                emit_entry_call(0x150)
                entry.extend(bytes.fromhex("59"))
            if "runtime-global-field" in mode:
                emit_entry_call(0x110)
                entry.extend(bytes.fromhex("c3"))
            else:
                if "cursor-lookup" in mode:
                    if "unknown-cursor" not in mode:
                        entry.extend(bytes.fromhex("ff 74 24 04"))
                        emit_entry_call(0x170)
                        entry.extend(bytes.fromhex("59"))
                    entry.extend(
                        bytes.fromhex(
                            "ff 74 24 04"
                            if "unknown-cursor" in mode
                            else "6a 00"
                        )
                    )
                    emit_entry_call(0x170)
                    entry.extend(bytes.fromhex("59"))
                else:
                    emit_entry_call(0x170)
                entry.extend(bytes.fromhex("50"))
                emit_entry_call(0x30)
                entry.extend(bytes.fromhex("59 c3"))
            text[: len(entry)] = entry
            text[0x151:0x16A] = bytes.fromhex(
                "8b 44 24 04 be 00 29 40 00 8b 0e 85 c9 74 07 "
                "8b 36 83 c6 10 eb f3 89 06 c3"
            )
            if "stack-return" in mode:
                if mode.endswith("unknown"):
                    text[0x171:0x18A] = bytes.fromhex(
                        "a1 00 29 40 00 83 ec 04 89 04 24 "
                        "c7 04 24 00 24 40 00 8b 04 24 83 c4 04 c3"
                    )
                else:
                    text[0x171:0x183] = bytes.fromhex(
                        "a1 00 29 40 00 83 ec 04 89 04 24 "
                        "8b 04 24 83 c4 04 c3"
                    )
            elif "link-cursor" in mode:
                cursor_head = (
                    "00 2a 40 00"
                    if mode.endswith("unknown")
                    else "00 29 40 00"
                )
                if mode.endswith("post-clobber"):
                    text[0x171:0x192] = bytes.fromhex(
                        "be "
                        + cursor_head
                        + " eb 05 "
                        "8b 36 83 c6 10 8b 06 85 c0 74 09 "
                        "83 7c 24 04 00 75 02 eb ec "
                        "be 00 2a 40 00 c3"
                    )
                else:
                    text[0x171:0x18D] = bytes.fromhex(
                        "be "
                        + cursor_head
                        + " eb 05 "
                        "8b 36 83 c6 10 8b 06 85 c0 74 09 "
                        "83 7c 24 04 00 75 02 eb ec c3"
                    )
            elif "cursor-lookup" in mode:
                text[0x171:0x17F] = bytes.fromhex(
                    "8b 44 24 04 85 c0 75 05 a1 00 29 40 00 c3"
                )
            else:
                text[0x171:0x177] = bytes.fromhex(
                    "a1 00 29 40 00 c3"
                )
            if mode.endswith("back-reference"):
                entry = bytearray.fromhex(
                    "53 6a 00 6a 00 68 00 23 40 00"
                )

                def emit_back_reference_call(target):
                    call_offset = len(entry)
                    entry.append(0xE8)
                    entry.extend(
                        struct.pack("<i", target - (call_offset + 5))
                    )

                emit_back_reference_call(0x60)
                entry.extend(bytes.fromhex("83 c4 0c 89 c3 53"))
                emit_back_reference_call(
                    0x1A8 if "stack-forwarded" in mode else 0x110
                )
                if "stack-forwarded" in mode:
                    entry.extend(bytes.fromhex("59 53"))
                    emit_back_reference_call(0x1B0)
                    entry.extend(bytes.fromhex("59 90"))
                else:
                    entry.extend(
                        bytes.fromhex("59 8b 43 08 a3 00 2b 40 00")
                    )
                emit_back_reference_call(0x190)
                entry.extend(bytes.fromhex("5b c3"))
                text[: len(entry)] = entry
                text[0x30] = 0xC3
                # The fixed-copy template below contracts the text by one
                # byte, so these land at 0x401110 and 0x401190.
                text[0x111:0x11E] = bytes.fromhex(
                    "8b 44 24 04 8b 50 08 8b 0a 89 41 04 c3"
                )
                text[0x191:0x1A3] = bytes.fromhex(
                    "a1 00 2b 40 00 8b 10 8b 4a 04 51 "
                    "e8 90 fe ff ff 59 c3"
                )
                if "global-pointer" in mode:
                    initializer = bytearray.fromhex(
                        "8b 44 24 04 8b 50 08 8b 0a 89 41 04 "
                        "c7 05 00 2a 40 00 00 2b 40 00"
                    )
                    if "hostile" in mode:
                        initializer.extend(
                            bytes.fromhex(
                                "c7 05 00 2a 40 00 10 2b 40 00"
                            )
                        )
                    initializer.append(0xC3)
                    text[0x111 : 0x111 + len(initializer)] = initializer
                    text[0x191:0x1A5] = bytes.fromhex(
                        "a1 00 2a 40 00 8b 00 8b 10 8b 4a 04 51 "
                        "e8 8e fe ff ff 59 c3"
                    )
                if "stack-forwarded" in mode:
                    text[0x1A9] = 0xC3
                    text[0x1B1:0x1D4] = bytes.fromhex(
                        "ff 74 24 04 e8 57 ff ff ff 59 "
                        "8b 44 24 04 8b 40 08 50 "
                        "e8 0d 00 00 00 59 "
                        "ff 74 24 04 e8 0f 00 00 00 59 c3"
                    )
                    text[0x1D5] = 0xC3
                    text[0x1E1:0x1EE] = bytes.fromhex(
                        "8b 44 24 04 8b 40 08 a3 00 2b 40 00 c3"
                    )
                # A relocated read in unowned executable residue must not
                # poison the closed domain of the reachable global slot.
                residue_offset = (
                    0x1F1 if "stack-forwarded" in mode else 0x1D1
                )
                text[residue_offset : residue_offset + 7] = bytes.fromhex(
                    "ff 35 00 2b 40 00 c3"
                )
            if "runtime-global-field" in mode:
                helper = bytearray()

                def emit_helper_call(target):
                    call_offset = 0x110 + len(helper)
                    helper.append(0xE8)
                    helper.extend(
                        struct.pack("<i", target - (call_offset + 5))
                    )

                emit_helper_call(0x1D0)
                helper.extend(bytes.fromhex("a3 00 2a 40 00"))
                if mode.endswith("unknown"):
                    helper.extend(bytes.fromhex("b8 00 24 40 00"))
                else:
                    emit_helper_call(0x170)
                helper.extend(
                    bytes.fromhex(
                        "8b 15 00 2a 40 00 89 42 34 "
                        "8b 0d 00 2a 40 00 8b 41 34"
                    )
                )
                if "guarded-runtime-global-field-clobber" in mode:
                    helper.extend(
                        bytes.fromhex(
                            "85 d2 74 05 b8 00 24 40 00"
                        )
                    )
                elif "guarded-runtime-global-field" in mode:
                    helper.extend(bytes.fromhex("85 c0 74 01 90"))
                helper.extend(bytes.fromhex("50"))
                emit_helper_call(0x30)
                helper.extend(bytes.fromhex("59 c3"))
                text[0x111 : 0x111 + len(helper)] = helper

                zeroer = bytearray.fromhex(
                    "8b 54 24 04 57 55 8b 6c 24 10 55 52"
                )
                zeroer_call = 0x1A0 + len(zeroer)
                zeroer.append(0xE8)
                zeroer.extend(struct.pack("<i", 0xE0 - (zeroer_call + 5)))
                zeroer.extend(
                    bytes.fromhex(
                        "89 c2 59 31 c0 59 89 e9 89 d7 f3 aa "
                        "89 d0 5d 5f c3"
                    )
                )
                text[0x1A1 : 0x1A1 + len(zeroer)] = zeroer

                constructor = bytearray.fromhex("6a 40 6a 00 e8")
                constructor.extend(
                    struct.pack("<i", 0x1A0 - (0x1D0 + 9))
                )
                constructor.extend(bytes.fromhex("83 c4 08 c3"))
                text[0x1D1 : 0x1D1 + len(constructor)] = constructor
        text[0x30:0x42] = bytes.fromhex(
            "53 8b 5c 24 08 8b 03 8b 58 0c 85 db 74 02 "
            "ff d3 5b c3"
        )
        if mode.endswith("field-forwarded-object-null-branch"):
            # The consumer is also an exact caller of the field-forwarder
            # with a null object.  That dereference faults before the later
            # indirect transfer, so null contributes no callback target.
            text[0x30:0x48] = bytes.fromhex(
                "8b 44 24 04 8b 00 8b 40 0c 85 c0 74 03 90 ff d0 "
                "6a 00 e8 01 00 00 00 c3"
            )
        if slot_zero_hypothesis:
            text[0x30:0x41] = bytes.fromhex(
                "53 8b 44 24 08 8b 08 8b 19 85 db 74 02 "
                "ff d3 5b c3"
            )
            if mode == "copied-descriptor-slot-zero-hidden-caller":
                text[0x48:0x50] = bytes.fromhex(
                    "51 e8 12 00 00 00 59 c3"
                )
            elif mode == "copied-descriptor-slot-zero-correlated-sources":
                text[0x1B:0x21] = bytes.fromhex(
                    "e8 28 00 00 00 c3"
                )
                text[0x48:0x5A] = bytes.fromhex(
                    "6a 00 6a 00 68 00 24 40 00 e8 0a 00 00 00 "
                    "83 c4 0c c3"
                )
            elif mode == "copied-descriptor-object-hypothesis-chain":
                text[0x48:0x5B] = bytes.fromhex(
                    "c7 80 04 01 00 00 00 25 40 00 "
                    "8b 98 04 01 00 00 ff 13 c3"
                )
        if mode == "copied-descriptor-cross-block-clobber":
            text[0x30:0x44] = bytes.fromhex(
                "53 8b 5c 24 08 8b 03 8b 58 0c 85 db 74 04 "
                "89 cb ff d3 5b c3"
            )
        text[0x60:0x81] = bytes.fromhex(
            "57 56 bf 00 24 40 00 8b 74 24 0c "
            "b9 09 00 00 00 f3 a5 a5 a5 a5 a5 a5 a5 "
            "b8 00 25 40 00 5e 5f c3"
        )
        if mode == "copied-descriptor-six-movsd-decoy":
            text[0x90] = 0xC3
            callback_target = 0x00401090
        else:
            constructor = bytearray()

            def emit(hex_bytes):
                constructor.extend(bytes.fromhex(hex_bytes))

            def emit_allocator_call():
                call_offset = 0x60 + len(constructor)
                constructor.append(0xE8)
                constructor.extend(
                    struct.pack("<i", 0xE0 - (call_offset + 5))
                )

            emit("53 56 57 55 bd 00 25 40 00 8b 5c 24 1c")
            emit("6a 24 6a 00")
            emit_allocator_call()
            emit("89 45 00 83 c4 08")
            emit("8b 45 00 85 c0 75 03 31 c0 c3")
            emit("8d 38 8b 44 24 14 8d 30")
            emit("b9 09 00 00 00 f3 a5")
            emit("6a 18 6a 00")
            emit_allocator_call()
            emit("89 45 04 83 c4 08")
            emit("8b 45 04 8d 38 8b 44 24 18 8d 30")
            emit("a5 a5 a5 a5 a5 a5")
            emit("6a 08 6a 00")
            emit_allocator_call()
            emit("89 45 08 83 c4 08")
            emit("8b 75 08 8b 43 04 8b 13 89 16 89 46 04")
            emit("89 e8 5d 5f 5e 5b c3")
            text[0x60:0x100] = b"\xCC" * 0xA0
            text[0x60 : 0x60 + len(constructor)] = constructor
            text[0xE0] = 0xC3
            text[0xF0] = 0xC3
            callback_target = (
                0x00401048
                if mode == "copied-descriptor-object-hypothesis-chain"
                else 0x004010F0
            )
        if slot_zero_hypothesis:
            struct.pack_into("<I", data, 0x700, callback_target)
            if mode == "copied-descriptor-slot-zero-correlated-sources":
                struct.pack_into("<I", data, 0x800, 0x004010D8)
                text[0xD8] = 0xC3
            if mode == (
                "copied-descriptor-slot-zero-unrelocated-record"
            ):
                struct.pack_into("<I", data, 0x704, callback_target)
            if mode == "copied-descriptor-object-hypothesis-chain":
                struct.pack_into(
                    "<III",
                    data,
                    0x900,
                    0x004010D8,
                    0x004010F0,
                    0,
                )
                text[0xD8] = 0xC3
                text[0xF0] = 0xC3
        else:
            struct.pack_into("<I", data, 0x70C, callback_target)
        if mode.startswith(
            "copied-descriptor-slot-zero-tagged-rejected-callback"
        ):
            # Mirror the retail chain that copies a descriptor table, stamps
            # the copied record's object from slot-one metadata, publishes the
            # object through slot zero, then rejects it at a strict validator.
            struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 8, 0x200)
            struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x200)
            text[0x00:0x2C] = bytes.fromhex(
                "53 6a 00 6a 00 68 00 23 40 00 e8 51 00 00 00 "
                "83 c4 0c 89 c3 53 e8 56 01 00 00 53 e8 e0 00 "
                "00 00 e8 bb 01 00 00 e8 66 01 00 00 5b c3"
            )
            text[0x30:0x4D] = bytes.fromhex(
                "8b 44 24 04 53 8b 08 8b 19 85 db 74 09 "
                "8b 44 24 0c 50 ff d3 5b c3 b8 02 00 00 00 5b c3"
            )
            text[0xF0:0xFC] = bytes.fromhex(
                "8b 44 24 04 a3 00 29 40 00 c2 04 00"
            )
            text[0x100:0x114] = bytes.fromhex(
                "8b 44 24 04 8b 48 08 51 50 e8 22 ff ff ff "
                "83 c4 08 c2 04 00"
            )
            text[0x118:0x131] = bytes.fromhex(
                "8b 54 24 04 8b 4c 24 08 c7 02 00 28 40 00 "
                "c7 01 12 00 00 00 31 c0 c2 08 00"
            )
            text[0x138:0x169] = bytes.fromhex(
                "83 ec 08 8b 44 24 0c 8b 00 8b 40 04 85 c0 74 19 "
                "8d 0c 24 8d 54 24 04 52 51 ff d0 66 85 c0 75 09 "
                "8b 04 24 83 c4 08 c2 04 00 31 c0 83 c4 08 c2 04 00"
            )
            text[0x170:0x188] = bytes.fromhex(
                "53 8b 5c 24 08 53 e8 bd ff ff ff 8b 40 02 "
                "8b 4b 08 89 41 20 5b c2 04 00"
            )
            text[0x190:0x1A9] = bytes.fromhex(
                "ff 35 00 29 40 00 e8 15 00 00 00 83 c4 04 "
                "85 c0 74 06 8b 58 34 ff 53 04 c3"
            )
            text[0x1B0:0x1C7] = bytes.fromhex(
                "8b 44 24 04 85 c0 74 0c 81 78 20 73 72 61 50 "
                "75 03 c3 cc cc 31 c0 c3"
            )
            text[0x1D0:0x1D8] = bytes.fromhex(
                "c7 41 34 00 27 40 00 c3"
            )
            text[0x1E0:0x1FB] = bytes.fromhex(
                "6a 38 e8 f9 fe ff ff 59 89 c3 85 db 74 0a "
                "89 d9 e8 db ff ff ff 89 d8 c3 31 c0 c3"
            )
            text[0x1FC] = 0xC3
            struct.pack_into("<II", data, 0x700, 0x004010F0, 0x00401118)
            struct.pack_into("<I", data, 0xB04, 0x004011FC)
            metadata_tag = (
                0x50617273 if mode.endswith("same-tag") else 0x436F6D70
            )
            struct.pack_into("<I", data, 0xC02, metadata_tag)
            if mode.endswith("missing-stamper"):
                text[0x16:0x1A] = struct.pack("<i", 0xC6)
    elif mode in {
        "bounded-descriptor-array",
        "unbounded-descriptor-array",
        "nested-bounded-descriptor-array",
        "nested-bounded-descriptor-array-with-outer-clobber",
        "nested-bounded-descriptor-array-dead-end-clobber",
    }:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        if mode.startswith("nested-bounded-descriptor-array"):
            text[0x00:0x23] = bytes.fromhex(
                "57 55 53 31 db bf 00 23 40 00 31 ed 90 ff 57 08 "
                "45 83 c7 0c 83 fd 03 7c f4 43 83 fb 02 7c e6 "
                "5b 5d 5f c3"
            )
            if mode == "nested-bounded-descriptor-array-with-outer-clobber":
                # Move the base initialization before the outer loop and mutate
                # it between inner-loop executions.  The inner backedge alone
                # is therefore insufficient to prove a finite callback domain.
                text[0x03:0x23] = bytes.fromhex(
                    "bf 00 23 40 00 31 db 31 ed 90 ff 57 08 45 "
                    "83 c7 0c 83 fd 03 7c f4 83 c7 04 43 83 fb "
                    "02 7c e8 c3"
                )
            elif mode == "nested-bounded-descriptor-array-dead-end-clobber":
                text[0x00:0x31] = bytes.fromhex(
                    "57 55 53 31 db bf 00 23 40 00 31 ed 90 ff 57 08 "
                    "85 c0 75 0b 45 83 c7 0c 83 fd 03 7c f0 eb 08 "
                    "89 cf eb 04 90 90 90 90 43 83 fb 02 7c d8 "
                    "5b 5d 5f c3"
                )
        else:
            text[0x00:0x1B] = bytes.fromhex(
                "57 55 bf 00 23 40 00 31 ed ff 57 08 45 "
                "83 c7 0c 83 fd 03 7c f4 5d 5f c3 cc cc cc"
            )
            if mode == "unbounded-descriptor-array":
                text[0x10:0x16] = bytes.fromhex("eb f7 cc cc cc cc")
        text[0x90] = 0xC3
        struct.pack_into("<III", data, 0x708, 0x00401090, 0x004010A0, 0x004010B0)
        struct.pack_into("<I", data, 0x714, 0x004010A0)
        struct.pack_into("<I", data, 0x720, 0x004010B0)
        text[0xA0] = 0xC3
        text[0xB0] = 0xC3
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
    elif mode in {"registrar-table", "registrar-empty"}:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        if mode == "registrar-table":
            text[0x00:0x11] = bytes.fromhex(
                "68 90 10 40 00 e8 26 00 00 00 59 "
                "e8 50 00 00 00 c3"
            )
            text[0x30:0x59] = bytes.fromhex(
                "83 3d 00 23 40 00 04 73 1a "
                "8b 44 24 04 8b 0d 00 23 40 00 "
                "89 04 8d 00 22 40 00 ff 05 00 23 40 00 "
                "31 c0 c3 b8 ff ff ff ff c3"
            )
        else:
            text[0x00:0x06] = bytes.fromhex("e8 5b 00 00 00 c3")
        text[0x60:0x86] = bytes.fromhex(
            "83 3d 00 23 40 00 00 7e 1c "
            "ff 0d 00 23 40 00 8b 1d 00 23 40 00 "
            "ff 14 9d 00 22 40 00 83 3d 00 23 40 00 00 "
            "7f e4 c3"
        )
        text[0x90] = 0xC3
    elif mode == "crt-empty-sentinel":
        text[:] = b"\xCC" * len(text)
        text[0x00:0x1B] = bytes.fromhex(
            "55 89 e5 53 bb 00 23 40 00 56 eb 05 ff d6 "
            "83 c3 04 8b 33 85 f6 75 f5 5e 5b 5d c3"
        )
        text[0x60] = 0xC3
        section_name = SECTION_TABLE_OFFSET + 40
        data[section_name : section_name + 8] = b".CRT\0\0\0\0"
    elif mode == "global-cdecl-callback":
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        text[0x00:0x12] = bytes.fromhex(
            "68 90 10 40 00 e8 26 00 00 00 59 "
            "ff 15 00 23 40 00 c3"
        )
        text[0x30:0x3D] = bytes.fromhex(
            "55 89 e5 8b 45 08 a3 00 23 40 00 5d c3"
        )
        text[0x90] = 0xC3
    elif mode in {
        "finite-object-runtime-field-callback",
        "finite-object-runtime-field-unknown-write",
    }:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        text[0x00:0x18] = bytes.fromhex(
            "c7 05 04 24 40 00 00 25 40 00 "
            "68 00 24 40 00 e8 1c 00 00 00 83 c4 04 c3"
        )
        text[0x30:0x3F] = bytes.fromhex(
            "53 8b 5c 24 08 8b 43 04 ff 50 0c 5b c2 04 00"
        )
        if mode == "finite-object-runtime-field-unknown-write":
            text[0x00:0x22] = bytes.fromhex(
                "ff 74 24 04 e8 57 00 00 00 59 "
                "c7 05 04 24 40 00 00 25 40 00 "
                "68 00 24 40 00 e8 12 00 00 00 83 c4 04 c3"
            )
            text[0x60:0x6D] = bytes.fromhex(
                "55 89 e5 8b 45 08 a3 04 24 40 00 5d c3"
            )
        text[0x90] = 0xC3
        struct.pack_into("<I", data, 0x90C, 0x00401090)
    elif mode in {
        "global-descriptor-callback",
        "global-descriptor-ebp-callback",
        "global-descriptor-loop-reload-callback",
        "global-descriptor-loop-reload-clobber",
        "global-descriptor-guarded-alias-callback",
        "global-descriptor-guarded-alias-clobber",
        "global-descriptor-unknown-write",
    }:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        guarded_alias = mode.startswith(
            "global-descriptor-guarded-alias-"
        )
        if guarded_alias:
            text[0x00:0x10] = bytes.fromhex(
                "68 00 24 40 00 e8 56 00 00 00 59 e8 20 00 00 00"
            )
            text[0x10] = 0xC3
        elif mode == "global-descriptor-unknown-write":
            text[0x00:0x1A] = bytes.fromhex(
                "8b 4c 24 04 89 0d 00 23 40 00 "
                "c7 05 00 23 40 00 00 24 40 00 "
                "e8 17 00 00 00 c3"
            )
        else:
            text[0x00:0x10] = bytes.fromhex(
                "c7 05 00 23 40 00 00 24 40 00 "
                "e8 21 00 00 00 c3"
            )
        if guarded_alias:
            text[0x30:0x44] = bytes.fromhex(
                "56 8b 15 00 23 40 00 83 7a 04 00 74 05 "
                "89 d6 ff 56 04 5e c3"
            )
            if mode == "global-descriptor-guarded-alias-clobber":
                text[0x3D:0x46] = bytes.fromhex(
                    "31 d2 89 d6 ff 56 04 5e c3"
                )
                text[0x3B:0x3D] = bytes.fromhex("74 07")
            text[0x60:0x6B] = bytes.fromhex(
                "8b 54 24 04 89 15 00 23 40 00 c3"
            )
        elif mode == "global-descriptor-ebp-callback":
            text[0x30:0x3A] = bytes.fromhex(
                "8b 2d 00 23 40 00 ff 55 10 c3"
            )
        elif mode.startswith("global-descriptor-loop-reload-"):
            text[0x30:0x4A] = bytes.fromhex(
                "57 56 31 f6 8b 3d 00 23 40 00 53 ff 57 04 "
                "83 c4 04 46 83 fe 03 7c ed 5e 5f c3"
            )
            if mode == "global-descriptor-loop-reload-clobber":
                text[0x3A:0x4C] = bytes.fromhex(
                    "01 f7 53 ff 57 04 83 c4 04 46 83 fe 03 "
                    "7c eb 5e 5f c3"
                )
        else:
            text[0x30:0x39] = bytes.fromhex(
                "a1 00 23 40 00 ff 50 04 c3"
            )
        text[0x90] = 0xC3
        struct.pack_into("<I", data, 0x804, 0x00401090)
        struct.pack_into("<I", data, 0x810, 0x00401090)
    elif mode in {
        "object-callback-table",
        "object-callback-table-no-dispatch",
        "object-callback-table-unreachable-store",
        "object-callback-table-unknown-source",
        "object-callback-table-isolated",
        "object-callback-table-missing-terminator",
        "object-callback-table-relocated-terminator",
        "object-callback-table-interior-target",
        "object-callback-table-unknown-overlap",
        "object-callback-table-late-rmw",
    }:
        struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x100)
        text[:] = b"\xCC" * len(text)
        dispatch_modes = {
            "object-callback-table",
            "object-callback-table-unreachable-store",
            "object-callback-table-unknown-source",
            "object-callback-table-missing-terminator",
            "object-callback-table-relocated-terminator",
            "object-callback-table-interior-target",
            "object-callback-table-unknown-overlap",
            "object-callback-table-late-rmw",
        }
        if mode in {
            "object-callback-table",
            "object-callback-table-missing-terminator",
            "object-callback-table-relocated-terminator",
            "object-callback-table-interior-target",
            "object-callback-table-late-rmw",
        }:
            text[0x00:0x06] = bytes.fromhex("e8 2b 00 00 00 c3")
            text[0x30:0x3F] = bytes.fromhex(
                "8b 44 24 04 c7 80 04 01 00 00 00 23 40 00 c3"
            )
        elif mode == "object-callback-table-no-dispatch":
            text[0x00:0x06] = bytes.fromhex("e8 2b 00 00 00 c3")
            text[0x30:0x3F] = bytes.fromhex(
                "8b 44 24 04 c7 80 04 01 00 00 00 23 40 00 c3"
            )
        elif mode == "object-callback-table-unreachable-store":
            text[0x00] = 0xC3
            text[0x30:0x3B] = bytes.fromhex(
                "c7 80 04 01 00 00 00 23 40 00 c3"
            )
        elif mode == "object-callback-table-unknown-source":
            text[0x00:0x06] = bytes.fromhex("e8 2b 00 00 00 c3")
            text[0x30:0x3B] = bytes.fromhex(
                "8b 44 24 04 89 88 04 01 00 00 c3"
            )
        elif mode == "object-callback-table-unknown-overlap":
            text[0x00:0x06] = bytes.fromhex("e8 2b 00 00 00 c3")
            text[0x30:0x45] = bytes.fromhex(
                "8b 44 24 04 c7 80 04 01 00 00 00 23 40 00 "
                "89 90 04 01 00 00 c3"
            )
        else:
            text[0x00] = 0xC3
        text[0x20] = 0xC3
        if mode in dispatch_modes:
            text[0x60:0x6E] = bytes.fromhex(
                "8b 44 24 04 8b 88 04 01 00 00 ff 51 04 c3"
            )
        if mode == "object-callback-table":
            # Forward a fresh-copy return to the slot-one callback.  That
            # callback publishes it through a relocated global slot and a
            # direct wrapper forwards the slot to a final consumer.
            text[0x00:0x0B] = bytes.fromhex(
                "e8 2b 00 00 00 e8 a6 00 00 00 c3"
            )
            text[0x60:0x79] = bytes.fromhex(
                "53 8b 5c 24 08 e8 26 00 00 00 "
                "8b 8b 04 01 00 00 50 ff 51 04 83 c4 04 5b c3"
            )
        text[0x90] = 0xC3
        text[0xA0] = 0xC3
        if mode == "object-callback-table":
            text[0xA0:0xAA] = bytes.fromhex(
                "8b 44 24 04 a3 00 25 40 00 c3"
            )
            text[0xB0:0xBD] = bytes.fromhex(
                "ff 35 00 25 40 00 e8 05 00 00 00 59 c3"
            )
            text[0xC0] = 0xC3
        if mode == "object-callback-table-interior-target":
            text[0x05:0x0B] = bytes.fromhex("e8 86 00 00 00 c3")
            text[0x90:0x93] = bytes.fromhex("89 c0 c3")
        elif mode == "object-callback-table-late-rmw":
            text[0x90:0x97] = bytes.fromhex(
                "ff 80 04 01 00 00 c3"
            )
        first_target = (
            0x00401091
            if mode == "object-callback-table-interior-target"
            else 0x00401090
        )
        terminator = (
            0x11223344
            if mode == "object-callback-table-missing-terminator"
            else 0
        )
        struct.pack_into("<III", data, 0x700, first_target, 0x004010A0, terminator)
    data[0x200:0x400] = text

    # Export a real target and retain the relocation-proven second target.
    export_rva = {
        "owned-dispatch-interior": 0x1041,
        "owned-relocation-interior": 0x1034,
        "registrar-table": 0x1090,
        "registrar-empty": 0x1090,
        "cdecl-spill-callback": 0x1090,
        "cdecl-esp-callback": 0x1090,
        "guarded-equal-callback": 0x1090,
        "guarded-equal-clobber": 0x1090,
        "outparam-callback": 0x1090,
        "outparam-conditional-callback": 0x1090,
        "cdecl-cross-block-callback": 0x1090,
        "cdecl-cross-block-clobber": 0x1090,
        "cdecl-recursive-callback": 0x1090,
        "cdecl-recursive-unknown": 0x1090,
        "cdecl-forwarder-chain": 0x1090,
        "cdecl-forwarder-chain-alternate-caller": 0x10A0,
        "cdecl-forwarder-chain-overwrite": 0x1090,
        "cdecl-forwarder-chain-ebp-complex": 0x1090,
        "cdecl-forwarder-chain-ebp-clobber": 0x1090,
        "external-code-pointer-escape": 0x1090,
        "signed-byte-domain-table": 0x1090,
        "signed-byte-domain-exact-spill": 0x1090,
        "signed-byte-domain-one-sided": 0x1090,
        "signed-byte-domain-admits-sixteen": 0x1090,
        "signed-byte-domain-bad-slot": 0x1090,
        "signed-byte-domain-relocations-only": 0x1090,
        "zero-guarded-callback": 0x1090,
        "zero-unguarded-callback": 0x1090,
        "mixed-zero-nonzero-guarded-callback": 0x1090,
        "zero-loop-guarded-callback": 0x1090,
        "zero-loop-clobbered-callback": 0x1090,
        "noreturn-guarded-callback": 0x1090,
        "returning-guarded-callback": 0x1090,
        "zero-distant-guarded-callback": 0x10F0,
        "zero-distant-unguarded-callback": 0x10F0,
        "linear-prologue-conflicting-tail": 0x1000,
        "constructor-field-callback": 0x1090,
        "constructor-field-ebp-callback": 0x1090,
        "constructor-field-stack-decoy": 0x1090,
        "constructor-field-late-finite-write": 0x1000,
        "constructor-field-unknown-write": 0x1090,
        "validated-constructor-descriptor": 0x10F0,
        "validated-constructor-descriptor-different-writer": 0x10F0,
        "validated-constructor-descriptor-alternate-producer": 0x10C0,
        "validated-constructor-descriptor-changed-descriptor": 0x10F0,
        "validated-constructor-descriptor-tag-only": 0x10F0,
        "validated-constructor-descriptor-incomplete-initializer-domain": 0x10C0,
        "validated-constructor-descriptor-retail-guard-arms": 0x10F0,
        "validated-constructor-descriptor-wrapper-global": 0x10F0,
        "validated-constructor-descriptor-wrapper-global-double": 0x10F0,
        "validated-constructor-descriptor-wrapper-global-double-unrelocated": 0x10F0,
        "validated-constructor-descriptor-wrapper-global-alternate-writer": 0x10C0,
        "validated-constructor-descriptor-wrapper-global-incomplete-domain": 0x10C0,
        "validated-constructor-descriptor-multi-tag": 0x1030,
        "validated-constructor-descriptor-multi-tag-rejected-only": 0x1030,
        "validated-constructor-descriptor-multi-tag-same-tag": 0x1030,
        "validated-constructor-descriptor-multi-tag-unknown-tag": 0x1030,
        "copied-descriptor-callback": 0x10F0,
        "copied-descriptor-unknown-source": 0x10F0,
        "copied-descriptor-six-movsd-decoy": 0x1090,
        "copied-descriptor-cross-block-clobber": 0x10F0,
        "copied-descriptor-unproven-object": 0x10F0,
        "copied-descriptor-forwarded-object": 0x10F0,
        "copied-descriptor-source-forwarded-object": 0x10F0,
        "copied-descriptor-source-forwarded-object-unknown": 0x10F0,
        "copied-descriptor-wrapper-returned-object": 0x10F0,
        "copied-descriptor-wrapper-returned-object-unknown-return": 0x10F0,
        "copied-descriptor-field-forwarded-object": 0x10F0,
        "copied-descriptor-field-forwarded-object-unknown-write": 0x10F0,
        "copied-descriptor-field-forwarded-object-null-branch": 0x10F0,
        "copied-descriptor-field-forwarded-object-unknown-branch": 0x10F0,
        "copied-descriptor-field-list-returned-object": 0x10F0,
        "copied-descriptor-field-list-returned-object-unknown-insert": 0x10F0,
        "copied-descriptor-field-list-returned-object-runtime-zeroed": 0x10F0,
        "copied-descriptor-field-list-returned-object-runtime-nonzero": 0x10F0,
        "copied-descriptor-registered-object": 0x10F0,
        "copied-descriptor-registered-object-back-reference": 0x10F0,
        "copied-descriptor-registered-object-global-pointer-back-reference": 0x10F0,
        "copied-descriptor-registered-object-global-pointer-hostile-back-reference": 0x10F0,
        "copied-descriptor-registered-object-stack-forwarded-back-reference": 0x10F0,
        "copied-descriptor-registered-object-link-cursor": 0x10F0,
        "copied-descriptor-registered-object-link-cursor-post-clobber": 0x10F0,
        "copied-descriptor-registered-object-link-cursor-unknown": 0x10F0,
        "copied-descriptor-registered-object-runtime-global-field": 0x10F0,
        "copied-descriptor-registered-object-guarded-runtime-global-field": 0x10F0,
        "copied-descriptor-registered-object-guarded-runtime-global-field-clobber": 0x10F0,
        "copied-descriptor-registered-object-runtime-global-field-unknown": 0x10F0,
        "copied-descriptor-registered-object-stack-return": 0x10F0,
        "copied-descriptor-registered-object-stack-return-unknown": 0x10F0,
        "copied-descriptor-registered-object-unknown-writer": 0x10F0,
        "copied-descriptor-registered-object-cursor-lookup": 0x10F0,
        "copied-descriptor-registered-object-unknown-cursor-lookup": 0x10F0,
        "copied-descriptor-slot-zero-hypothesis": 0x10F0,
        "copied-descriptor-slot-zero-correlated-sources": 0x10F0,
        "copied-descriptor-slot-zero-tagged-rejected-callback": 0x1000,
        "copied-descriptor-slot-zero-tagged-rejected-callback-missing-stamper": 0x1000,
        "copied-descriptor-slot-zero-tagged-rejected-callback-same-tag": 0x1000,
        "copied-descriptor-slot-zero-tagged-rejected-callback-unrelocated-provider": 0x1000,
        "copied-descriptor-slot-zero-hidden-caller": 0x10F0,
        "copied-descriptor-slot-zero-unrelocated-record": 0x10F0,
        "copied-descriptor-object-hypothesis-chain": 0x1000,
        "bounded-descriptor-array": 0x1090,
        "unbounded-descriptor-array": 0x1090,
        "nested-bounded-descriptor-array": 0x1090,
        "nested-bounded-descriptor-array-with-outer-clobber": 0x1090,
        "nested-bounded-descriptor-array-dead-end-clobber": 0x1090,
        "crt-empty-sentinel": 0x1000,
        "global-cdecl-callback": 0x1090,
        "finite-object-runtime-field-callback": 0x1090,
        "finite-object-runtime-field-unknown-write": 0x1090,
        "global-descriptor-callback": 0x1090,
        "global-descriptor-ebp-callback": 0x1090,
        "global-descriptor-loop-reload-callback": 0x1090,
        "global-descriptor-loop-reload-clobber": 0x1090,
        "global-descriptor-guarded-alias-callback": 0x1090,
        "global-descriptor-guarded-alias-clobber": 0x1090,
        "global-descriptor-unknown-write": 0x1090,
        "object-callback-table": 0x1060,
        "object-callback-table-no-dispatch": 0x1020,
        "object-callback-table-unreachable-store": 0x1060,
        "object-callback-table-unknown-source": 0x1060,
        "object-callback-table-isolated": 0x1020,
        "object-callback-table-missing-terminator": 0x1060,
        "object-callback-table-relocated-terminator": 0x1060,
        "object-callback-table-interior-target": 0x1060,
        "object-callback-table-unknown-overlap": 0x1060,
        "object-callback-table-late-rmw": 0x1060,
        "validated-constructor-descriptor-forwarded-global-switch": 0x1160,
        "validated-constructor-descriptor-forwarded-global-switch-unknown-tag": 0x1160,
        "validated-constructor-descriptor-forwarded-global-switch-hidden-caller": 0x1160,
        "validated-constructor-descriptor-forwarded-global-switch-alternate-writer": 0x1160,
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
    elif mode in {"outparam-callback", "outparam-conditional-callback"}:
        relocation = (
            0x303B
            if mode == "outparam-conditional-callback"
            else 0x3037
        )
        struct.pack_into("<IIHH", data, 0x1400, 0x1000, 12, relocation, 0)
    elif mode in {
        "registrar-table",
        "cdecl-spill-callback",
        "cdecl-esp-callback",
        "cdecl-cross-block-callback",
        "cdecl-cross-block-clobber",
        "cdecl-recursive-callback",
        "cdecl-recursive-unknown",
        "cdecl-forwarder-chain",
        "cdecl-forwarder-chain-alternate-caller",
        "cdecl-forwarder-chain-overwrite",
        "cdecl-forwarder-chain-ebp-complex",
        "cdecl-forwarder-chain-ebp-clobber",
        "external-code-pointer-escape",
        "global-cdecl-callback",
    }:
        struct.pack_into("<IIHH", data, 0x1400, 0x1000, 12, 0x3001, 0)
    elif mode in {
        "signed-byte-domain-table",
        "signed-byte-domain-exact-spill",
        "signed-byte-domain-one-sided",
        "signed-byte-domain-admits-sixteen",
        "signed-byte-domain-bad-slot",
        "signed-byte-domain-relocations-only",
    }:
        struct.pack_into(
            "<I", data, OPTIONAL_OFFSET + 96 + 5 * 8 + 4, 52
        )
        relocation_entry = (
            0x301E
            if mode == "signed-byte-domain-exact-spill"
            else 0x3017
        )
        struct.pack_into(
            "<IIHH", data, 0x1400, 0x1000, 12, relocation_entry, 0
        )
        entries = [0x3300 + index * 4 for index in range(16)]
        if mode == "signed-byte-domain-bad-slot":
            entries[8] = 0
        struct.pack_into(
            "<II" + "H" * 16,
            data,
            0x140C,
            0x2000,
            40,
            *entries,
        )
    elif mode == "mixed-zero-nonzero-guarded-callback":
        struct.pack_into("<IIHH", data, 0x1400, 0x1000, 12, 0x3009, 0)
    elif mode in {
        "global-descriptor-callback",
        "global-descriptor-ebp-callback",
        "global-descriptor-loop-reload-callback",
        "global-descriptor-loop-reload-clobber",
        "global-descriptor-guarded-alias-callback",
        "global-descriptor-guarded-alias-clobber",
        "global-descriptor-unknown-write",
    }:
        struct.pack_into(
            "<I", data, OPTIONAL_OFFSET + 96 + 5 * 8 + 4, 14
        )
        struct.pack_into(
            "<IIHHH", data, 0x1400, 0x2000, 14, 0x3404, 0x3410, 0
        )
    elif mode in {
        "object-callback-table",
        "object-callback-table-no-dispatch",
        "object-callback-table-unreachable-store",
        "object-callback-table-missing-terminator",
        "object-callback-table-relocated-terminator",
        "object-callback-table-interior-target",
        "object-callback-table-unknown-overlap",
        "object-callback-table-late-rmw",
    }:
        store_relocation = (
            0x3036
            if mode == "object-callback-table-unreachable-store"
            else 0x303A
        )
        relocation_size = (
            28
            if mode
            in {
                "object-callback-table",
                "object-callback-table-relocated-terminator",
            }
            else 24
        )
        struct.pack_into(
            "<I", data, OPTIONAL_OFFSET + 96 + 5 * 8 + 4, relocation_size
        )
        struct.pack_into(
            "<IIHH", data, 0x1400, 0x1000, 12, store_relocation, 0
        )
        if mode == "object-callback-table":
            struct.pack_into(
                "<IIHHHH",
                data,
                0x1400,
                0x1000,
                16,
                store_relocation,
                0x30A5,
                0x30B2,
                0,
            )
            struct.pack_into(
                "<IIHH", data, 0x1410, 0x2000, 12, 0x3300, 0x3304
            )
        elif mode == "object-callback-table-relocated-terminator":
            struct.pack_into(
                "<IIHHHH",
                data,
                0x140C,
                0x2000,
                16,
                0x3300,
                0x3304,
                0x3308,
                0,
            )
        else:
            struct.pack_into(
                "<IIHH", data, 0x140C, 0x2000, 12, 0x3300, 0x3304
            )
    elif mode in {
        "object-callback-table-unknown-source",
        "object-callback-table-isolated",
    }:
        struct.pack_into(
            "<IIHH", data, 0x1400, 0x2000, 12, 0x3300, 0x3304
        )
    elif mode in {
        "constructor-field-callback",
        "constructor-field-ebp-callback",
        "constructor-field-stack-decoy",
        "constructor-field-late-finite-write",
        "constructor-field-unknown-write",
    }:
        if mode == "constructor-field-late-finite-write":
            struct.pack_into(
                "<I", data, OPTIONAL_OFFSET + 96 + 5 * 8 + 4, 16
            )
            struct.pack_into(
                "<IIHHHH",
                data,
                0x1400,
                0x2000,
                16,
                0x3304,
                0x3324,
                0,
                0,
            )
        else:
            struct.pack_into(
                "<IIHH", data, 0x1400, 0x2000, 12, 0x3304, 0
            )
    elif mode.startswith("validated-constructor-descriptor"):
        code_entries = [0x30B0]
        data_entries = [0x3404]
        if mode == "validated-constructor-descriptor-tag-only":
            code_entries = [0x3001]
            data_entries.append(0x3534)
        elif mode.startswith(
            "validated-constructor-descriptor-wrapper-global"
        ):
            code_entries = [0x3016, 0x3022, 0x3052, 0x3075, 0x30B0]
            data_entries.append(0x3640)
            if mode.endswith("double"):
                code_entries[2] = 0x3051
                data_entries.append(0x3710)
            elif mode.endswith("double-unrelocated"):
                code_entries[2] = 0x3051
            if mode.endswith("alternate-writer"):
                code_entries.append(0x30C5)
            elif mode.endswith("incomplete-domain"):
                code_entries.append(0x30C3)
        elif mode.startswith(
            "validated-constructor-descriptor-forwarded-global-switch"
        ):
            code_entries = [0x3052, 0x30B0, 0x3106, 0x3135]
            if mode.endswith("alternate-writer"):
                code_entries.append(0x31C2)
        code_entries += [0] * ((-len(code_entries)) % 2)
        data_entries += [0] * ((-len(data_entries)) % 2)
        code_block_size = 8 + len(code_entries) * 2
        data_block_size = 8 + len(data_entries) * 2
        struct.pack_into(
            "<I",
            data,
            OPTIONAL_OFFSET + 96 + 5 * 8 + 4,
            code_block_size + data_block_size,
        )
        struct.pack_into(
            "<II" + "H" * len(code_entries),
            data,
            0x1400,
            0x1000,
            code_block_size,
            *code_entries,
        )
        struct.pack_into(
            "<II" + "H" * len(data_entries),
            data,
            0x1400 + code_block_size,
            0x2000,
            data_block_size,
            *data_entries,
        )
    elif mode in {
        "copied-descriptor-callback",
        "copied-descriptor-unknown-source",
        "copied-descriptor-six-movsd-decoy",
        "copied-descriptor-cross-block-clobber",
        "copied-descriptor-unproven-object",
        "copied-descriptor-forwarded-object",
        "copied-descriptor-source-forwarded-object",
        "copied-descriptor-source-forwarded-object-unknown",
        "copied-descriptor-wrapper-returned-object",
        "copied-descriptor-wrapper-returned-object-unknown-return",
        "copied-descriptor-field-forwarded-object",
        "copied-descriptor-field-forwarded-object-unknown-write",
        "copied-descriptor-field-forwarded-object-null-branch",
        "copied-descriptor-field-forwarded-object-unknown-branch",
        "copied-descriptor-field-list-returned-object",
        "copied-descriptor-field-list-returned-object-unknown-insert",
        "copied-descriptor-field-list-returned-object-runtime-zeroed",
        "copied-descriptor-field-list-returned-object-runtime-nonzero",
        "copied-descriptor-registered-object",
        "copied-descriptor-registered-object-back-reference",
        "copied-descriptor-registered-object-global-pointer-back-reference",
        "copied-descriptor-registered-object-global-pointer-hostile-back-reference",
        "copied-descriptor-registered-object-stack-forwarded-back-reference",
        "copied-descriptor-registered-object-link-cursor",
        "copied-descriptor-registered-object-link-cursor-post-clobber",
        "copied-descriptor-registered-object-link-cursor-unknown",
        "copied-descriptor-registered-object-runtime-global-field",
        "copied-descriptor-registered-object-guarded-runtime-global-field",
        "copied-descriptor-registered-object-guarded-runtime-global-field-clobber",
        "copied-descriptor-registered-object-runtime-global-field-unknown",
        "copied-descriptor-registered-object-stack-return",
        "copied-descriptor-registered-object-stack-return-unknown",
        "copied-descriptor-registered-object-unknown-writer",
        "copied-descriptor-registered-object-cursor-lookup",
        "copied-descriptor-registered-object-unknown-cursor-lookup",
        "copied-descriptor-slot-zero-hypothesis",
        "copied-descriptor-slot-zero-correlated-sources",
        "copied-descriptor-slot-zero-tagged-rejected-callback",
        "copied-descriptor-slot-zero-tagged-rejected-callback-missing-stamper",
        "copied-descriptor-slot-zero-tagged-rejected-callback-same-tag",
        "copied-descriptor-slot-zero-tagged-rejected-callback-unrelocated-provider",
        "copied-descriptor-slot-zero-hidden-caller",
        "copied-descriptor-slot-zero-unrelocated-record",
        "copied-descriptor-object-hypothesis-chain",
    }:
        if mode.startswith(
            "copied-descriptor-slot-zero-tagged-rejected-callback"
        ):
            struct.pack_into(
                "<I", data, OPTIONAL_OFFSET + 96 + 5 * 8 + 4, 40
            )
            struct.pack_into(
                "<II" + "H" * 6,
                data,
                0x1400,
                0x1000,
                20,
                0x3006,
                0x30F5,
                0x3122,
                0x3192,
                0x31D3,
                0,
            )
            struct.pack_into(
                "<II" + "H" * 6,
                data,
                0x1414,
                0x2000,
                20,
                0x3300,
                (
                    0
                    if mode.endswith("unrelocated-provider")
                    else 0x3304
                ),
                0x3704,
                0,
                0,
                0,
            )
        elif mode == "copied-descriptor-object-hypothesis-chain":
            struct.pack_into(
                "<I", data, OPTIONAL_OFFSET + 96 + 5 * 8 + 4, 28
            )
            struct.pack_into(
                "<IIHH", data, 0x1400, 0x1000, 12, 0x304E, 0
            )
            struct.pack_into(
                "<IIHHHH",
                data,
                0x140C,
                0x2000,
                16,
                0x3300,
                0x3500,
                0x3504,
                0,
            )
        elif mode == "copied-descriptor-slot-zero-correlated-sources":
            struct.pack_into(
                "<I", data, OPTIONAL_OFFSET + 96 + 5 * 8 + 4, 16
            )
            struct.pack_into(
                "<IIHHHH",
                data,
                0x1400,
                0x2000,
                16,
                0x3300,
                0x3400,
                0,
                0,
            )
        else:
            if mode.startswith("copied-descriptor-registered-object"):
                if mode.endswith("back-reference"):
                    if "global-pointer" in mode:
                        code_entries = [
                            0x301F,
                            0x311E,
                            0x3122,
                            0x3155,
                            0x3171,
                            0x3191,
                            0x31D2,
                        ]
                        if "hostile" in mode:
                            code_entries[3:3] = [0x3128, 0x312C]
                        if len(code_entries) % 2:
                            code_entries.append(0)
                        code_block_size = 8 + 2 * len(code_entries)
                        struct.pack_into(
                            "<I",
                            data,
                            OPTIONAL_OFFSET + 96 + 5 * 8 + 4,
                            code_block_size + 12,
                        )
                        struct.pack_into(
                            "<II" + "H" * len(code_entries),
                            data,
                            0x1400,
                            0x1000,
                            code_block_size,
                            *code_entries,
                        )
                        struct.pack_into(
                            "<IIHH",
                            data,
                            0x1400 + code_block_size,
                            0x2000,
                            12,
                            0x330C,
                            0,
                        )
                        return bytes(data)
                    struct.pack_into(
                        "<I", data, OPTIONAL_OFFSET + 96 + 5 * 8 + 4, 32
                    )
                    struct.pack_into(
                        "<II" + "H" * 6,
                        data,
                        0x1400,
                        0x1000,
                        20,
                        (
                            0x31E8
                            if "stack-forwarded" in mode
                            else 0x301F
                        ),
                        0x3155,
                        0x3171,
                        0x3191,
                        (
                            0x31F2
                            if "stack-forwarded" in mode
                            else 0x31D2
                        ),
                        0,
                    )
                    struct.pack_into(
                        "<IIHH", data, 0x1414, 0x2000, 12, 0x330C, 0
                    )
                    return bytes(data)
                struct.pack_into(
                    "<I", data, OPTIONAL_OFFSET + 96 + 5 * 8 + 4, 28
                )
                struct.pack_into(
                    "<IIHHHH",
                    data,
                    0x1400,
                    0x1000,
                    16,
                    0x3155,
                    (
                        0x3179
                        if "cursor-lookup" in mode
                        else 0x3171
                    ),
                    0,
                    0,
                )
                struct.pack_into(
                    "<IIHH", data, 0x1410, 0x2000, 12, 0x330C, 0
                )
                return bytes(data)
            if mode.startswith("copied-descriptor-field-list-returned-object"):
                if "runtime-" in mode:
                    struct.pack_into(
                        "<I", data, OPTIONAL_OFFSET + 96 + 5 * 8 + 4, 12
                    )
                    struct.pack_into(
                        "<IIHH", data, 0x1400, 0x2000, 12, 0x330C, 0
                    )
                else:
                    struct.pack_into(
                        "<I", data, OPTIONAL_OFFSET + 96 + 5 * 8 + 4, 16
                    )
                    struct.pack_into(
                        "<IIHHHH",
                        data,
                        0x1400,
                        0x2000,
                        16,
                        0x330C,
                        0x3900,
                        0,
                        0,
                    )
            else:
                relocation = (
                    0x3300
                    if mode.startswith("copied-descriptor-slot-zero-")
                    else 0x330C
                )
                struct.pack_into(
                    "<IIHH", data, 0x1400, 0x2000, 12, relocation, 0
                )
    elif mode in {
        "bounded-descriptor-array",
        "unbounded-descriptor-array",
        "nested-bounded-descriptor-array",
        "nested-bounded-descriptor-array-with-outer-clobber",
        "nested-bounded-descriptor-array-dead-end-clobber",
    }:
        struct.pack_into(
            "<I", data, OPTIONAL_OFFSET + 96 + 5 * 8 + 4, 16
        )
        struct.pack_into(
            "<IIHHHH", data, 0x1400, 0x2000, 16, 0x3308, 0x3314, 0x3320, 0
        )
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
    if mode in {"registrar-table", "registrar-empty"}:
        targets = ()
        data[0x600:0x610] = b"\0" * 16
    elif mode.startswith("signed-byte-domain-"):
        targets = (0x00401090,) * 16
        if mode == "signed-byte-domain-bad-slot":
            targets = (*targets[:8], 0x2D, *targets[9:])
        table_offset = 0x700
    elif mode == "byte-return-table":
        targets = tuple(
            0x00401020 if index % 2 == 0 else 0x00401060
            for index in range(256)
        )
    if mode == "target-outside-text":
        targets = (0x00402000, *targets[1:])
    table_offset = (
        0x15FC
        if mode == "unmapped-entry"
        else (0x700 if mode.startswith("signed-byte-domain-") else 0x600)
    )
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
