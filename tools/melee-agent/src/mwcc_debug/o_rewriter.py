"""Post-process MWCC-produced .o files to rename anonymous `@N` symbols
whose backing .sdata2 data matches user-supplied magic constants.

Background: MWCC's int-to-float cast emits a magic constant into the
.sdata2 literal pool:

  - Signed:   0x4330000080000000 (decimal 4503599627370496.0 + bias)
  - Unsigned: 0x4330000000000000

The literal entry gets an anonymous local symbol name like `@491`. The
matching .o (extracted from the binary) references the same data via a
named global like `mnVibration_804DC018` (from symbols.txt). The
relocation target name differs, so checkdiff reports a diff even
though the bytes are otherwise identical.

This module identifies anonymous `@N` symbols by value, then uses
GNU's `objcopy --redefine-sym` to rewrite the symbol table with
user-supplied names.

The hook-based alternative (patching mwcc's literal-pool naming code)
would require RE-ing the v1.2.5n binary; the post-process approach is
faster to ship and equivalent in observable behavior.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Known PowerPC int-to-float bias constants
MAGIC_S32 = 0x4330000080000000
MAGIC_U32 = 0x4330000000000000

_SHORTCUT_TO_VALUE = {
    "s32": MAGIC_S32,
    "u32": MAGIC_U32,
}


@dataclass
class MagicSymbol:
    """An anonymous .sdata2 symbol whose backing data is a 64-bit value."""
    name: str  # the @N name from the .o
    offset: int  # offset within .sdata2
    value: int  # the 64-bit big-endian value at that offset
    size: int  # size in bytes (typically 8)


def find_magic_symbols(o_path: Path) -> list[MagicSymbol]:
    """Scan a .o file for anonymous symbols in .sdata2 with 8-byte values.

    Returns a list of MagicSymbol entries — caller decides which (if any)
    to rename based on value matching. Only 8-byte symbols are returned;
    4-byte floats are visible via find_all_anonymous_sdata2_symbols().
    """
    return [s for s in find_all_anonymous_sdata2_symbols(o_path) if s.size == 8]


def find_all_anonymous_sdata2_symbols(o_path: Path) -> list[MagicSymbol]:
    """Scan a .o for ALL anonymous .sdata2 symbols (4-byte and 8-byte).

    4-byte symbols store the value in the low 32 bits of MagicSymbol.value;
    they're typically float literals (e.g. 0.0f → 0x00000000, 1.0f →
    0x3F800000). 8-byte symbols are typically int-to-float magic constants
    or doubles.

    Returns the list in offset-ascending order.
    """
    from elftools.elf.elffile import ELFFile

    out: list[MagicSymbol] = []
    with o_path.open("rb") as f:
        elf = ELFFile(f)
        sdata2 = elf.get_section_by_name(".sdata2")
        if sdata2 is None:
            return out
        sdata2_idx = elf.get_section_index(".sdata2")
        data = sdata2.data()
        symtab = elf.get_section_by_name(".symtab")
        if symtab is None:
            return out
        for sym in symtab.iter_symbols():
            if sym["st_shndx"] != sdata2_idx:
                continue
            if not sym.name or not sym.name.startswith("@"):
                continue
            size = sym["st_size"]
            offset = sym["st_value"]
            if size == 8 and offset + 8 <= len(data):
                value = struct.unpack(">Q", data[offset:offset + 8])[0]
            elif size == 4 and offset + 4 <= len(data):
                value = struct.unpack(">I", data[offset:offset + 4])[0]
            else:
                continue
            out.append(MagicSymbol(
                name=sym.name,
                offset=offset,
                value=value,
                size=size,
            ))
    out.sort(key=lambda s: s.offset)
    return out


@dataclass
class Mapping:
    """A parsed mapping: either by-value (matches data content) or by-name
    (matches an anonymous symbol name directly).
    """
    by_value: dict[int, str]  # 64-bit value → new name
    by_name: dict[str, str]  # @N → new name


def parse_mapping(mapping: str) -> Mapping:
    """Parse a comma-separated mapping string of the form:
        '<key>=<name>,<key>=<name>,...'

    Where <key> is one of:
      - `s32`        — matches 0x4330000080000000 (signed int-to-float bias)
      - `u32`        — matches 0x4330000000000000 (unsigned int-to-float bias)
      - hex/decimal  — matches a 64-bit value at an 8-byte .sdata2 entry
      - `@N`         — matches an anonymous symbol named `@N` directly
                       (works for 4-byte float literals too)

    Returns a Mapping with separate by_value and by_name dicts.
    """
    result = Mapping(by_value={}, by_name={})
    for entry in mapping.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(
                f"invalid mapping entry (need '<key>=<name>'): {entry!r}"
            )
        key, name = entry.split("=", 1)
        key = key.strip()
        name = name.strip()
        if not name:
            raise ValueError(f"empty name in mapping entry: {entry!r}")
        if key.startswith("@"):
            # Direct symbol-name mapping
            result.by_name[key] = name
            continue
        if key in _SHORTCUT_TO_VALUE:
            value = _SHORTCUT_TO_VALUE[key]
        else:
            try:
                value = int(key, 0)  # supports 0x... and decimal
            except ValueError:
                raise ValueError(
                    f"invalid value in mapping entry: {key!r} (expected "
                    f"'s32', 'u32', a 64-bit integer literal, or '@N')"
                )
        result.by_value[value] = name
    return result


def rename_magic_symbols(
    o_path: Path,
    mapping,  # dict[int, str] (legacy) OR Mapping (preferred)
    out_path: Optional[Path] = None,
    objcopy: str = "/opt/devkitpro/devkitPPC/bin/powerpc-eabi-objcopy",
) -> list[tuple[str, str]]:
    """Rename anonymous .sdata2 symbols in `o_path` using `objcopy`.

    `mapping` is either:
      - a dict[int, str] from 64-bit value to desired symbol name
        (legacy API; still supported for backward compatibility), OR
      - a `Mapping` instance with separate by_value and by_name maps.

    If `out_path` is None, the rename is in-place on `o_path`.

    Returns a list of (old_name, new_name) renames performed.
    """
    # Normalize mapping to a Mapping instance
    if isinstance(mapping, dict):
        m = Mapping(by_value=dict(mapping), by_name={})
    else:
        m = mapping

    symbols = find_magic_symbols(o_path)
    renames: list[tuple[str, str]] = []
    for sym in symbols:
        if sym.value in m.by_value:
            renames.append((sym.name, m.by_value[sym.value]))

    # Also handle direct @N → name mappings. These can target any
    # anonymous symbol (including 4-byte float literals that
    # find_magic_symbols filters out due to size != 8).
    if m.by_name:
        from elftools.elf.elffile import ELFFile
        with o_path.open("rb") as f:
            elf = ELFFile(f)
            symtab = elf.get_section_by_name(".symtab")
            if symtab is not None:
                for sym in symtab.iter_symbols():
                    if sym.name and sym.name in m.by_name:
                        renames.append((sym.name, m.by_name[sym.name]))

    if not renames:
        return []

    # objcopy --redefine-syms reads pairs from a file (old new\n)
    target = out_path if out_path is not None else o_path
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".redef", delete=False
    ) as tf:
        for old, new in renames:
            tf.write(f"{old} {new}\n")
        redef_file = tf.name

    try:
        if out_path is None:
            # In-place: objcopy writes to a temp file then we move it.
            with tempfile.NamedTemporaryFile(
                suffix=".o", delete=False
            ) as tf_out:
                tmp_out = tf_out.name
            try:
                subprocess.run(
                    [objcopy, "--redefine-syms", redef_file,
                     str(o_path), tmp_out],
                    check=True,
                )
                shutil.move(tmp_out, str(o_path))
            finally:
                # Clean up temp out if it still exists
                Path(tmp_out).unlink(missing_ok=True)
        else:
            subprocess.run(
                [objcopy, "--redefine-syms", redef_file,
                 str(o_path), str(out_path)],
                check=True,
            )
    finally:
        Path(redef_file).unlink(missing_ok=True)

    return renames
