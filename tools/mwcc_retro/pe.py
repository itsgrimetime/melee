"""Strict read-only PE32 parser for MWCC introspection. Pure stdlib."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path


I386_MACHINE = 0x014C
PE32_MAGIC = 0x010B
SECTION_EXECUTABLE = 0x20000000
UINT32_LIMIT = 1 << 32

_DIRECTORY_NAMES = (
    "export",
    "import",
    "resource",
    "exception",
    "certificate",
    "base_relocation",
    "debug",
    "architecture",
    "global_pointer",
    "tls",
    "load_config",
    "bound_import",
    "iat",
    "delay_import",
    "clr",
    "reserved",
)


@dataclass(frozen=True)
class DataDirectory:
    index: int
    name: str
    rva: int
    size: int


@dataclass(frozen=True)
class Import:
    dll: str
    name: str | None
    ordinal: int | None
    hint: int | None
    iat_va: int


@dataclass(frozen=True)
class Export:
    name: str | None
    ordinal: int
    va: int | None
    forwarded_to: str | None


@dataclass(frozen=True)
class Relocation:
    va: int
    type: int


@dataclass(frozen=True)
class Section:
    name: str
    va: int  # absolute virtual address (image_base + rva)
    raw_offset: int  # file offset
    raw_size: int
    virt_size: int
    characteristics: int

    @property
    def mapped_size(self) -> int:
        return max(self.raw_size, self.virt_size)

    @property
    def is_executable(self) -> bool:
        return bool(self.characteristics & SECTION_EXECUTABLE)


@dataclass(frozen=True)
class Image:
    data: bytes = field(repr=False, compare=False)
    sha256: str
    machine: int
    optional_magic: int
    image_base: int
    size_of_headers: int
    entrypoint: int
    directories: tuple[DataDirectory, ...]
    sections: tuple[Section, ...]
    imports: tuple[Import, ...]
    exports: tuple[Export, ...]
    relocations: tuple[Relocation, ...]
    executable_ranges: tuple[tuple[int, int], ...]

    def va_to_offset(self, va: int) -> int | None:
        if self.image_base <= va < self.image_base + self.size_of_headers:
            return va - self.image_base
        for section in self.sections:
            if section.va <= va < section.va + section.raw_size:
                return section.raw_offset + (va - section.va)
        return None

    def offset_to_va(self, off: int) -> int | None:
        if 0 <= off < self.size_of_headers:
            return self.image_base + off
        for section in self.sections:
            if section.raw_offset <= off < section.raw_offset + section.raw_size:
                return section.va + (off - section.raw_offset)
        return None

    def section_of_va(self, va: int) -> str | None:
        for section in self.sections:
            if section.va <= va < section.va + section.mapped_size:
                return section.name
        return None

    def find_string_vas(self, needle: bytes) -> list[int]:
        """Return mapped VAs containing an exact byte string."""
        out: list[int] = []
        start = 0
        while True:
            offset = self.data.find(needle, start)
            if offset < 0:
                break
            va = self.offset_to_va(offset)
            if va is not None:
                out.append(va)
            start = offset + 1
        return out

    def push_imm32_sites(self, target_va: int) -> list[int]:
        """Return executable VAs containing ``PUSH target_va``."""
        pattern = b"\x68" + struct.pack("<I", target_va)
        out: list[int] = []
        for section in self.sections:
            if not section.is_executable:
                continue
            blob = self.data[
                section.raw_offset : section.raw_offset + section.raw_size
            ]
            start = 0
            while True:
                offset = blob.find(pattern, start)
                if offset < 0:
                    break
                out.append(section.va + offset)
                start = offset + 1
        return out

    def read(self, va: int, size: int) -> bytes:
        if size < 0:
            raise ValueError("read size must be non-negative")
        header_delta = va - self.image_base
        if 0 <= header_delta <= self.size_of_headers:
            if size <= self.size_of_headers - header_delta:
                result = self.data[header_delta : header_delta + size]
                if len(result) == size:
                    return result
        for section in self.sections:
            delta = va - section.va
            if delta < 0 or delta > section.raw_size:
                continue
            if size <= section.raw_size - delta:
                offset = section.raw_offset + delta
                result = self.data[offset : offset + size]
                if len(result) == size:
                    return result
        raise ValueError(f"read is not wholly mapped: VA {va:#x}, size {size:#x}")


def _checked_slice(data: bytes, offset: int, size: int, label: str) -> bytes:
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise ValueError(f"truncated {label}")
    return data[offset : offset + size]


def _unpack_from(
    fmt: str, data: bytes, offset: int, label: str
) -> tuple[int, ...]:
    size = struct.calcsize(fmt)
    blob = _checked_slice(data, offset, size, label)
    return struct.unpack(fmt, blob)


def _checked_u32_end(start: int, size: int, label: str) -> int:
    if start < 0 or size < 0 or start >= UINT32_LIMIT:
        raise ValueError(f"invalid {label}")
    if size > UINT32_LIMIT - start:
        raise ValueError(f"invalid {label}")
    return start + size


def _section_for_rva(
    sections: tuple[Section, ...], image_base: int, rva: int, size: int
) -> tuple[Section, int] | None:
    for section in sections:
        section_rva = section.va - image_base
        delta = rva - section_rva
        if delta < 0 or delta > section.raw_size:
            continue
        if size <= section.raw_size - delta:
            return section, delta
    return None


def _mapped_file_span(
    sections: tuple[Section, ...],
    image_base: int,
    size_of_headers: int,
    rva: int,
) -> tuple[int, int] | None:
    if 0 <= rva < size_of_headers:
        return rva, size_of_headers - rva
    mapped = _section_for_rva(sections, image_base, rva, 1)
    if mapped is None:
        return None
    section, delta = mapped
    return section.raw_offset + delta, section.raw_size - delta


def _read_rva(
    data: bytes,
    sections: tuple[Section, ...],
    image_base: int,
    size_of_headers: int,
    rva: int,
    size: int,
    label: str,
) -> bytes:
    _checked_u32_end(rva, size, label)
    mapped = _mapped_file_span(
        sections, image_base, size_of_headers, rva
    )
    if mapped is None or size > mapped[1]:
        raise ValueError(f"{label} is not wholly mapped")
    offset, _ = mapped
    return _checked_slice(data, offset, size, label)


def _read_c_string(
    data: bytes,
    sections: tuple[Section, ...],
    image_base: int,
    size_of_headers: int,
    rva: int,
    label: str,
    *,
    end_rva: int | None = None,
) -> str:
    mapped = _mapped_file_span(
        sections, image_base, size_of_headers, rva
    )
    if mapped is None:
        raise ValueError(f"{label} is not wholly mapped")
    start, available = mapped
    if end_rva is not None:
        if rva >= end_rva:
            raise ValueError(f"unterminated {label}")
        available = min(available, end_rva - rva)
    limit = start + available
    end = data.find(b"\0", start, limit)
    if end < 0:
        raise ValueError(f"unterminated {label}")
    return data[start:end].decode("latin-1")


def _read_u32_array(
    data: bytes,
    sections: tuple[Section, ...],
    image_base: int,
    size_of_headers: int,
    rva: int,
    count: int,
    label: str,
) -> tuple[int, ...]:
    if count == 0:
        return ()
    if count > len(data) // 4:
        raise ValueError(f"invalid {label} count")
    blob = _read_rva(
        data, sections, image_base, size_of_headers, rva, count * 4, label
    )
    return struct.unpack(f"<{count}I", blob)


def _read_u16_array(
    data: bytes,
    sections: tuple[Section, ...],
    image_base: int,
    size_of_headers: int,
    rva: int,
    count: int,
    label: str,
) -> tuple[int, ...]:
    if count == 0:
        return ()
    if count > len(data) // 2:
        raise ValueError(f"invalid {label} count")
    blob = _read_rva(
        data, sections, image_base, size_of_headers, rva, count * 2, label
    )
    return struct.unpack(f"<{count}H", blob)


def _parse_exports(
    data: bytes,
    sections: tuple[Section, ...],
    image_base: int,
    size_of_headers: int,
    directory: DataDirectory | None,
) -> tuple[Export, ...]:
    if directory is None or directory.size == 0:
        return ()
    if directory.size < 40:
        raise ValueError("truncated PE export directory")
    values = struct.unpack(
        "<IIHHIIIIIII",
        _read_rva(
            data,
            sections,
            image_base,
            size_of_headers,
            directory.rva,
            40,
            "PE export directory",
        ),
    )
    (
        _,
        _,
        _,
        _,
        dll_name_rva,
        ordinal_base,
        function_count,
        name_count,
        functions_rva,
        names_rva,
        ordinals_rva,
    ) = values
    if not dll_name_rva:
        raise ValueError("invalid PE export DLL name")
    _read_c_string(
        data,
        sections,
        image_base,
        size_of_headers,
        dll_name_rva,
        "PE export DLL name",
    )

    functions = _read_u32_array(
        data,
        sections,
        image_base,
        size_of_headers,
        functions_rva,
        function_count,
        "PE export address table",
    )
    name_rvas = _read_u32_array(
        data,
        sections,
        image_base,
        size_of_headers,
        names_rva,
        name_count,
        "PE export name table",
    )
    name_ordinals = _read_u16_array(
        data,
        sections,
        image_base,
        size_of_headers,
        ordinals_rva,
        name_count,
        "PE export ordinal table",
    )
    names_by_index: dict[int, list[str]] = {}
    for name_rva, function_index in zip(name_rvas, name_ordinals, strict=True):
        if function_index >= function_count:
            raise ValueError("invalid PE export ordinal")
        name = _read_c_string(
            data,
            sections,
            image_base,
            size_of_headers,
            name_rva,
            "PE export name",
        )
        names_by_index.setdefault(function_index, []).append(name)

    directory_end = _checked_u32_end(
        directory.rva, directory.size, "PE export directory"
    )
    exports: list[Export] = []
    for function_index, function_rva in enumerate(functions):
        if function_rva == 0:
            continue
        forwarded_to: str | None = None
        va: int | None = image_base + function_rva
        if directory.rva <= function_rva < directory_end:
            forwarded_to = _read_c_string(
                data,
                sections,
                image_base,
                size_of_headers,
                function_rva,
                "PE export forwarder",
                end_rva=directory_end,
            )
            va = None
        elif not any(
            section.va <= va < section.va + section.mapped_size
            for section in sections
        ):
            raise ValueError("PE export target is not mapped")
        names = sorted(names_by_index.get(function_index, [None]), key=str)
        for name in names:
            exports.append(
                Export(
                    name=name,
                    ordinal=ordinal_base + function_index,
                    va=va,
                    forwarded_to=forwarded_to,
                )
            )
    return tuple(
        sorted(
            set(exports),
            key=lambda entry: (
                entry.ordinal,
                entry.name is None,
                entry.name or "",
                entry.va is None,
                entry.va if entry.va is not None else -1,
                entry.forwarded_to is None,
                entry.forwarded_to or "",
            ),
        )
    )


def _read_import_table(
    data: bytes,
    sections: tuple[Section, ...],
    image_base: int,
    size_of_headers: int,
    table_rva: int,
    label: str,
) -> tuple[int, ...]:
    entries: list[int] = []
    for index in range(len(data) // 4 + 1):
        slot_rva = _checked_u32_end(table_rva, index * 4, label)
        try:
            slot = _read_rva(
                data,
                sections,
                image_base,
                size_of_headers,
                slot_rva,
                4,
                label,
            )
        except ValueError as error:
            raise ValueError(f"unterminated {label}") from error
        value = struct.unpack("<I", slot)[0]
        if value == 0:
            return tuple(entries)
        entries.append(value)
    raise ValueError(f"unterminated {label}")


def _parse_imports(
    data: bytes,
    sections: tuple[Section, ...],
    image_base: int,
    size_of_headers: int,
    directory: DataDirectory | None,
) -> tuple[Import, ...]:
    if directory is None or directory.size == 0:
        return ()
    imports: list[Import] = []
    descriptor_offset = 0
    terminated = False
    while descriptor_offset + 20 <= directory.size:
        descriptor_rva = directory.rva + descriptor_offset
        descriptor = struct.unpack(
            "<IIIII",
            _read_rva(
                data,
                sections,
                image_base,
                size_of_headers,
                descriptor_rva,
                20,
                "PE import descriptor",
            ),
        )
        descriptor_offset += 20
        if not any(descriptor):
            terminated = True
            break
        original_lookup_rva, _, _, dll_name_rva, iat_rva = descriptor
        if not dll_name_rva or not iat_rva:
            raise ValueError("invalid PE import descriptor")
        lookup_rva = original_lookup_rva or iat_rva
        dll = _read_c_string(
            data,
            sections,
            image_base,
            size_of_headers,
            dll_name_rva,
            "PE import DLL name",
        )
        lookup_entries = _read_import_table(
            data,
            sections,
            image_base,
            size_of_headers,
            lookup_rva,
            "PE import lookup table",
        )
        if original_lookup_rva:
            iat_entries = _read_import_table(
                data,
                sections,
                image_base,
                size_of_headers,
                iat_rva,
                "PE import address table",
            )
            if len(lookup_entries) != len(iat_entries):
                raise ValueError(
                    "PE import lookup and address table lengths differ"
                )

        for index, thunk in enumerate(lookup_entries):
            iat_slot_rva = _checked_u32_end(
                iat_rva, index * 4, "PE import address table"
            )
            if thunk & 0x80000000:
                name = None
                ordinal = thunk & 0xFFFF
                hint = None
            else:
                hint = struct.unpack(
                    "<H",
                    _read_rva(
                        data,
                        sections,
                        image_base,
                        size_of_headers,
                        thunk,
                        2,
                        "PE import hint",
                    ),
                )[0]
                name_rva = _checked_u32_end(thunk, 2, "PE import name")
                name = _read_c_string(
                    data,
                    sections,
                    image_base,
                    size_of_headers,
                    name_rva,
                    "PE import name",
                )
                ordinal = None
            imports.append(
                Import(
                    dll=dll,
                    name=name,
                    ordinal=ordinal,
                    hint=hint,
                    iat_va=image_base + iat_slot_rva,
                )
            )
    if not terminated:
        raise ValueError("unterminated PE import directory")
    return tuple(
        sorted(
            set(imports),
            key=lambda entry: (
                entry.dll.casefold(),
                entry.dll,
                entry.name is None,
                entry.name or "",
                entry.ordinal is None,
                entry.ordinal if entry.ordinal is not None else -1,
                entry.hint is None,
                entry.hint if entry.hint is not None else -1,
                entry.iat_va,
            ),
        )
    )


def _parse_relocations(
    data: bytes,
    sections: tuple[Section, ...],
    image_base: int,
    size_of_headers: int,
    machine: int,
    directory: DataDirectory | None,
) -> tuple[Relocation, ...]:
    if directory is None or directory.size == 0:
        return ()
    relocations: list[Relocation] = []
    offset = 0
    while offset < directory.size:
        if directory.size - offset < 8:
            raise ValueError("truncated PE base relocation block")
        block_rva = directory.rva + offset
        page_rva, block_size = struct.unpack(
            "<II",
            _read_rva(
                data,
                sections,
                image_base,
                size_of_headers,
                block_rva,
                8,
                "PE base relocation block",
            ),
        )
        if block_size < 8 or block_size % 2 or block_size > directory.size - offset:
            raise ValueError("invalid PE base relocation block")
        entries = _read_rva(
            data,
            sections,
            image_base,
            size_of_headers,
            block_rva + 8,
            block_size - 8,
            "PE base relocation entries",
        )
        entry_words = struct.unpack(f"<{len(entries) // 2}H", entries)
        entry_index = 0
        while entry_index < len(entry_words):
            entry = entry_words[entry_index]
            relocation_type = entry >> 12
            if relocation_type == 0:
                entry_index += 1
                continue
            width = 1
            if machine == I386_MACHINE:
                widths = {1: 2, 2: 2, 3: 4, 4: 2}
                if relocation_type not in widths:
                    raise ValueError(
                        f"unsupported i386 base relocation type: {relocation_type}"
                    )
                width = widths[relocation_type]
                if relocation_type == 4:
                    if entry_index + 1 >= len(entry_words):
                        raise ValueError(
                            "HIGHADJ relocation missing companion"
                        )
                    struct.unpack_from("<h", entries, (entry_index + 1) * 2)
            target_rva = _checked_u32_end(
                page_rva, entry & 0xFFF, "PE base relocation target"
            )
            target_va = image_base + target_rva
            _read_rva(
                data,
                sections,
                image_base,
                size_of_headers,
                target_rva,
                width,
                "PE base relocation target",
            )
            relocations.append(
                Relocation(va=target_va, type=relocation_type)
            )
            entry_index += 2 if machine == I386_MACHINE and relocation_type == 4 else 1
        offset += block_size
    return tuple(
        sorted(set(relocations), key=lambda entry: (entry.va, entry.type))
    )


def _validate_non_overlapping_sections(sections: tuple[Section, ...]) -> None:
    raw_ranges = sorted(
        (
            section.raw_offset,
            section.raw_offset + section.raw_size,
            section.name,
        )
        for section in sections
        if section.raw_size
    )
    for previous, current in zip(raw_ranges, raw_ranges[1:], strict=False):
        if current[0] < previous[1]:
            raise ValueError("overlapping PE raw sections")

    virtual_ranges = sorted(
        (section.va, section.va + section.mapped_size, section.name)
        for section in sections
        if section.mapped_size
    )
    for previous, current in zip(
        virtual_ranges, virtual_ranges[1:], strict=False
    ):
        if current[0] < previous[1]:
            raise ValueError("overlapping PE virtual sections")


def _validate_directories(
    data: bytes,
    directories: tuple[DataDirectory, ...],
    sections: tuple[Section, ...],
    image_base: int,
    size_of_headers: int,
) -> None:
    for directory in directories:
        if bool(directory.rva) != bool(directory.size):
            raise ValueError("invalid PE data directory")
        if directory.size == 0:
            continue
        if directory.index == 4:
            _checked_slice(
                data,
                directory.rva,
                directory.size,
                "PE certificate directory",
            )
            continue
        mapped = _mapped_file_span(
            sections, image_base, size_of_headers, directory.rva
        )
        if mapped is None or directory.size > mapped[1]:
            raise ValueError("PE data directory is not wholly mapped")


def load(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
    require_pe32_i386: bool = False,
) -> Image:
    data = Path(path).read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None:
        is_lower_hex = (
            isinstance(expected_sha256, str)
            and len(expected_sha256) == 64
            and expected_sha256 == expected_sha256.lower()
            and all(char in "0123456789abcdef" for char in expected_sha256)
        )
        if not is_lower_hex:
            raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")
        if sha256 != expected_sha256:
            raise ValueError(
                f"PE SHA-256 mismatch: expected {expected_sha256}, got {sha256}"
            )

    _checked_slice(data, 0, 64, "DOS header")
    if data[:2] != b"MZ":
        raise ValueError("not a PE file: missing DOS signature")
    pe_offset = _unpack_from("<I", data, 0x3C, "DOS header")[0]
    _checked_slice(data, pe_offset, 24, "PE header")
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ValueError("not a PE file")

    machine, section_count, _, _, _, optional_size, _ = _unpack_from(
        "<HHIIIHH", data, pe_offset + 4, "PE file header"
    )
    if section_count == 0:
        raise ValueError("PE must contain at least one section")
    optional_offset = pe_offset + 24
    _checked_slice(data, optional_offset, optional_size, "PE optional header")
    if optional_size < 96:
        raise ValueError("truncated PE optional header")
    optional_magic = _unpack_from(
        "<H", data, optional_offset, "PE optional header"
    )[0]
    if optional_magic != PE32_MAGIC:
        raise ValueError("optional header must be PE32")
    if require_pe32_i386 and machine != I386_MACHINE:
        raise ValueError("PE machine must be i386")

    entrypoint_rva = _unpack_from(
        "<I", data, optional_offset + 16, "PE optional header"
    )[0]
    image_base = _unpack_from(
        "<I", data, optional_offset + 28, "PE optional header"
    )[0]
    size_of_image = _unpack_from(
        "<I", data, optional_offset + 56, "PE optional header"
    )[0]
    size_of_headers = _unpack_from(
        "<I", data, optional_offset + 60, "PE optional header"
    )[0]
    directory_count = _unpack_from(
        "<I", data, optional_offset + 92, "PE optional header"
    )[0]
    available_directories = (optional_size - 96) // 8
    if directory_count > available_directories:
        raise ValueError("truncated PE data directory")

    directories: list[DataDirectory] = []
    for index in range(directory_count):
        rva, size = _unpack_from(
            "<II",
            data,
            optional_offset + 96 + index * 8,
            "PE data directory",
        )
        name = (
            _DIRECTORY_NAMES[index]
            if index < len(_DIRECTORY_NAMES)
            else f"directory_{index}"
        )
        directories.append(
            DataDirectory(index=index, name=name, rva=rva, size=size)
        )

    section_table_offset = optional_offset + optional_size
    section_table_size = section_count * 40
    try:
        _checked_slice(
            data, section_table_offset, section_table_size, "PE section table"
        )
    except ValueError as error:
        raise ValueError("truncated PE section table") from error
    section_table_end = section_table_offset + section_table_size
    if (
        size_of_headers < section_table_end
        or size_of_headers > len(data)
        or size_of_headers > size_of_image
        or size_of_image == 0
    ):
        raise ValueError("invalid PE header or image size")
    _checked_u32_end(image_base, size_of_headers, "PE headers")

    sections: list[Section] = []
    for index in range(section_count):
        offset = section_table_offset + index * 40
        name = (
            _checked_slice(data, offset, 8, "PE section header")
            .split(b"\0", 1)[0]
            .decode("latin-1")
        )
        virt_size, rva, raw_size, raw_offset = _unpack_from(
            "<IIII", data, offset + 8, "PE section header"
        )
        characteristics = _unpack_from(
            "<I", data, offset + 36, "PE section header"
        )[0]
        mapped_size = max(virt_size, raw_size)
        virtual_end = _checked_u32_end(rva, mapped_size, "PE virtual section")
        if mapped_size and rva < size_of_headers:
            raise ValueError("PE virtual section overlaps headers")
        if virtual_end > size_of_image:
            raise ValueError("PE virtual section exceeds image size")
        if raw_size:
            if raw_offset < size_of_headers:
                raise ValueError("PE section raw data overlaps headers")
            _checked_slice(data, raw_offset, raw_size, "PE section raw data")
        _checked_u32_end(image_base, virtual_end, "PE virtual address")
        sections.append(
            Section(
                name=name,
                va=image_base + rva,
                raw_offset=raw_offset,
                raw_size=raw_size,
                virt_size=virt_size,
                characteristics=characteristics,
            )
        )
    frozen_sections = tuple(sections)
    _validate_non_overlapping_sections(frozen_sections)

    frozen_directories = tuple(directories)
    _validate_directories(
        data,
        frozen_directories,
        frozen_sections,
        image_base,
        size_of_headers,
    )
    directory_by_index = {
        directory.index: directory
        for directory in frozen_directories
        if directory.size
    }

    entrypoint = _checked_u32_end(
        image_base, entrypoint_rva, "PE entry point"
    )
    executable_ranges = tuple(
        sorted(
            (section.va, section.va + section.mapped_size)
            for section in frozen_sections
            if section.is_executable and section.mapped_size
        )
    )
    if entrypoint_rva and not any(
        start <= entrypoint < end for start, end in executable_ranges
    ):
        raise ValueError("PE entry point is not in an executable section")

    exports = _parse_exports(
        data,
        frozen_sections,
        image_base,
        size_of_headers,
        directory_by_index.get(0),
    )
    imports = _parse_imports(
        data,
        frozen_sections,
        image_base,
        size_of_headers,
        directory_by_index.get(1),
    )
    relocations = _parse_relocations(
        data,
        frozen_sections,
        image_base,
        size_of_headers,
        machine,
        directory_by_index.get(5),
    )
    return Image(
        data=data,
        sha256=sha256,
        machine=machine,
        optional_magic=optional_magic,
        image_base=image_base,
        size_of_headers=size_of_headers,
        entrypoint=entrypoint,
        directories=frozen_directories,
        sections=frozen_sections,
        imports=imports,
        exports=exports,
        relocations=relocations,
        executable_ranges=executable_ranges,
    )
