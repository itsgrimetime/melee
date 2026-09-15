"""Minimal read-only PE32 parser for MWCC introspection. Pure stdlib."""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Section:
    name: str
    va: int          # absolute virtual address (image_base + rva)
    raw_offset: int  # file offset
    raw_size: int
    virt_size: int


@dataclass
class Image:
    data: bytes
    image_base: int
    sections: list[Section]

    def va_to_offset(self, va: int) -> int | None:
        for s in self.sections:
            if s.va <= va < s.va + s.raw_size:
                return s.raw_offset + (va - s.va)
        return None

    def offset_to_va(self, off: int) -> int | None:
        for s in self.sections:
            if s.raw_offset <= off < s.raw_offset + s.raw_size:
                return s.va + (off - s.raw_offset)
        return None

    def section_of_va(self, va: int) -> str | None:
        for s in self.sections:
            if s.va <= va < s.va + max(s.raw_size, s.virt_size):
                return s.name
        return None

    def find_string_vas(self, needle: bytes) -> list[int]:
        """All VAs where `needle` appears (any section), exact byte match."""
        out: list[int] = []
        start = 0
        while True:
            i = self.data.find(needle, start)
            if i < 0:
                break
            va = self.offset_to_va(i)
            if va is not None:
                out.append(va)
            start = i + 1
        return out

    def push_imm32_sites(self, target_va: int) -> list[int]:
        """VAs of `68 <target_va as le32>` (x86 PUSH imm32) in executable
        sections. Used to find call sites that reference a string."""
        pat = b"\x68" + struct.pack("<I", target_va)
        out: list[int] = []
        for s in self.sections:
            if s.name not in (".text",):
                continue
            blob = self.data[s.raw_offset : s.raw_offset + s.raw_size]
            start = 0
            while True:
                i = blob.find(pat, start)
                if i < 0:
                    break
                out.append(s.va + i)
                start = i + 1
        return out

    def read(self, va: int, n: int) -> bytes:
        off = self.va_to_offset(va)
        if off is None:
            raise ValueError(f"VA {va:#x} not mapped")
        return self.data[off : off + n]


def load(path: str | Path) -> Image:
    data = Path(path).read_bytes()
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_off : pe_off + 4] != b"PE\x00\x00":
        raise ValueError("not a PE file")
    nsec = struct.unpack_from("<H", data, pe_off + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe_off + 20)[0]
    image_base = struct.unpack_from("<I", data, pe_off + 24 + 28)[0]
    sections: list[Section] = []
    off = pe_off + 24 + opt_size
    for _ in range(nsec):
        name = data[off : off + 8].rstrip(b"\x00").decode("latin-1")
        vsize, rva, rsize, raw = struct.unpack_from("<IIII", data, off + 8)
        sections.append(
            Section(name=name, va=image_base + rva, raw_offset=raw,
                    raw_size=rsize, virt_size=vsize)
        )
        off += 40
    return Image(data=data, image_base=image_base, sections=sections)
