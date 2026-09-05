"""Retail MWCC compiler identification for mwcc-retro."""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from . import pe


@dataclass(frozen=True)
class RetroCompiler:
    key: str          # "1.1" | "1.2.5" | "1.2.5n"
    family: str       # "GC/1.1" | "GC/1.2.5"
    build_date: str
    banner_va: int


# Ninji patch signature (the 46-byte stub) identifies 1.2.5n vs stock 1.2.5.
_NINJA_MARK = b"Hacked by Ninji"


def detect_build_date(path: str | Path) -> str:
    """Build-date string, read the way mwcc-inspector does: u32 at file 0x1fc
    is the .data section RVA; the date lives at base + that_rva + 0x10."""
    data = Path(path).read_bytes()
    img = pe.load(path)
    data_rva = struct.unpack_from("<I", data, 0x1FC)[0]
    off = img.va_to_offset(img.image_base + data_rva)
    if off is None:
        raise ValueError("could not map .data for build-date")
    return data[off + 0x10 : off + 0x40].split(b"\x00")[0].decode("latin-1")


def identify(path: str | Path) -> RetroCompiler:
    data = Path(path).read_bytes()
    bd = detect_build_date(path)
    img = pe.load(path)
    if bd == "Feb  7 2001":
        return RetroCompiler("1.1", "GC/1.1", bd,
                             img.find_string_vas(b"Metrowerks C/C++")[0])
    if bd == "Apr 23 2001":
        key = "1.2.5n" if _NINJA_MARK in data else "1.2.5"
        return RetroCompiler(key, "GC/1.2.5", bd,
                             img.find_string_vas(b"Metrowerks C/C++")[0])
    raise ValueError(f"unrecognized MWCC build date: {bd!r}")
