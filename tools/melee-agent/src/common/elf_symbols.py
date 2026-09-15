"""Read a relocatable object's symbol table via pyelftools.

Clean typed wrapper. (tools/checkdiff.py has a private equivalent,
_read_object_symbol_records; dedup is a possible later follow-up — kept off
that critical tool here to bound blast radius.)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ObjSymbol:
    name: str
    section: str | None  # e.g. ".data", ".bss", ".sdata2"; None if no section
    shndx: int
    value: int           # st_value — section-relative offset in a relocatable .o
    size: int            # st_size
    bind: str            # "STB_GLOBAL" | "STB_LOCAL" | "STB_WEAK"
    type: str            # "STT_OBJECT" | "STT_FUNC" | "STT_NOTYPE" | ...


def read_object_symbols(path: Path) -> list[ObjSymbol]:
    """Return all named symbols in ``path``'s .symtab. [] on any error."""
    try:
        from elftools.common.exceptions import ELFError
        from elftools.elf.elffile import ELFFile
    except ImportError:
        return []
    try:
        with Path(path).open("rb") as f:
            elf = ELFFile(f)
            symtab = elf.get_section_by_name(".symtab")
            if symtab is None:
                return []
            out: list[ObjSymbol] = []
            for sym in symtab.iter_symbols():
                name = sym.name
                shndx = sym["st_shndx"]
                if not name or not isinstance(shndx, int):
                    continue
                info = sym["st_info"]
                section = elf.get_section(shndx)
                out.append(ObjSymbol(
                    name=name,
                    section=section.name if section is not None else None,
                    shndx=shndx,
                    value=int(sym["st_value"]),
                    size=int(sym["st_size"]),
                    bind=info["bind"],
                    type=info["type"],
                ))
            return out
    except (OSError, KeyError, TypeError, ValueError, ELFError):
        return []
