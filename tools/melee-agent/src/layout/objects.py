"""Resolve a TU's ref/our object paths and read their data-section intervals."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..common.elf_symbols import read_object_symbols
from .compare import DATA_ELF_SECTIONS, Interval

_ANON_PREFIXES = ("@", "...", "$")


@dataclass(frozen=True)
class UnitPaths:
    obj_path: str
    ref_obj: Path
    our_obj: Path


def unit_paths(repo: Path, c_file: Path) -> UnitPaths:
    repo = Path(repo)
    c = Path(c_file)
    if c.is_absolute():
        c = c.relative_to(repo)
    parts = c.with_suffix("").parts
    if parts and parts[0] == "src":
        parts = parts[1:]
    obj_path = "/".join(parts)
    return UnitPaths(
        obj_path=obj_path,
        ref_obj=repo / "build" / "GALE01" / "obj" / f"{obj_path}.o",
        our_obj=repo / "build" / "GALE01" / "src" / f"{obj_path}.o",
    )


def _is_gap(name: str) -> bool:
    return bool(name) and name.startswith("gap_")


def _is_anonymous(name: str) -> bool:
    return (not name) or name.startswith(_ANON_PREFIXES) or ".data." in name


def section_intervals(obj: Path) -> dict[str, list[Interval]]:
    """Group a .o's data-section object symbols into Intervals by ELF section.

    Skips `gap_*` padding markers; marks @N/...data./$... as anonymous.
    lbl_<ADDR> symbols are real production data and are NOT treated as anonymous.
    """
    out: dict[str, list[Interval]] = {}
    for s in read_object_symbols(obj):
        if s.section not in DATA_ELF_SECTIONS:
            continue
        if s.type not in ("STT_OBJECT", "STT_NOTYPE"):
            continue
        if _is_gap(s.name):
            continue
        out.setdefault(s.section, []).append(Interval(
            name=s.name, offset=s.value, size=s.size,
            binding=s.bind, anonymous=_is_anonymous(s.name),
        ))
    return out
