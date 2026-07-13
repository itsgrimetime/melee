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


def write_synthetic_pe(
    tmp_path: Path, *, mutation: str | None = None
) -> Path:
    path = tmp_path / f"synthetic-{mutation or 'valid'}.exe"
    path.write_bytes(synthetic_pe_bytes(mutation=mutation))
    return path
