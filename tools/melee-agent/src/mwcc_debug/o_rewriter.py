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


def find_named_sdata2_symbols_by_offset(
    o_path: Path,
) -> dict[int, str]:
    """Scan a .o for NAMED (non-anonymous) .sdata2 symbols, indexed by
    their byte offset within .sdata2.

    Used to cross-reference an anonymous @N symbol in the base (compiled)
    .o against a named symbol at the same offset in the target .o.
    When they match, we can generate a copy-pastable `--map` for
    `verify-with-name-magic` without making the agent grep symbols.txt.
    """
    from elftools.elf.elffile import ELFFile

    out: dict[int, str] = {}
    with o_path.open("rb") as f:
        elf = ELFFile(f)
        sdata2 = elf.get_section_by_name(".sdata2")
        if sdata2 is None:
            return out
        sdata2_idx = elf.get_section_index(".sdata2")
        symtab = elf.get_section_by_name(".symtab")
        if symtab is None:
            return out
        for sym in symtab.iter_symbols():
            if sym["st_shndx"] != sdata2_idx:
                continue
            name = sym.name
            if not name or name.startswith("@"):
                continue
            # Skip section symbols (no useful name for our purposes)
            if name.startswith("."):
                continue
            offset = sym["st_value"]
            # If multiple named symbols share an offset (rare), prefer
            # the first one encountered (deterministic via symtab order).
            out.setdefault(offset, name)
    return out


def find_named_sdata2_symbols_by_value(
    o_path: Path,
) -> dict[int, str]:
    """Scan a .o for NAMED (non-anonymous) .sdata2 symbols, indexed by
    the 64-bit big-endian value of their backing bytes.

    Unlike ``find_named_sdata2_symbols_by_offset``, this matches on the
    *actual bytes* stored at the symbol's location rather than the section
    offset.  This is what ``suggest_name_magic_map`` needs: the two .o files
    (compiled vs target) can have different .sdata2 layouts, so offsets don't
    align.  The magic values (0x4330000080000000 / 0x4330000000000000) are
    globally unique bit patterns, so matching by value is unambiguous.

    Only 8-byte symbols are included (magic constants are always 8 bytes).
    If multiple named symbols happen to contain the same 8-byte value at
    different offsets (extremely rare), the first one in symtab order wins.
    """
    from elftools.elf.elffile import ELFFile

    out: dict[int, str] = {}
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
            name = sym.name
            if not name or name.startswith("@"):
                continue
            if name.startswith("."):
                continue
            size = sym["st_size"]
            if size != 8:
                continue
            offset = sym["st_value"]
            if offset + 8 > len(data):
                continue
            value = struct.unpack(">Q", data[offset:offset + 8])[0]
            # Only index magic-constant values to keep lookups unambiguous.
            out.setdefault(value, name)
    return out


def suggest_name_magic_map(
    base_o_path: Path,
    target_o_path: Optional[Path] = None,
) -> tuple[list[MagicSymbol], list[tuple[MagicSymbol, str]]]:
    """For each anonymous @N symbol in ``base_o_path``, try to find a
    matching named symbol in ``target_o_path``.

    Matching is done by **value** (the actual 8-byte big-endian contents of
    the symbol's backing storage), NOT by section offset.  The two .o files
    frequently have different .sdata2 layouts — the compiled .o puts anonymous
    constants in emission order while the target .o has them in the original
    TU's declaration order.  An offset-based match would silently swap the
    s32 and u32 magic symbols when their order differs between the two files.

    Returns (all_anonymous, suggested_renames). suggested_renames is
    the subset for which a named counterpart was found in the target,
    paired with that named symbol. Callers render this as a copy-
    pastable --map (key=value pairs).

    If target_o_path is None or doesn't exist, suggested_renames is
    empty — caller falls back to the placeholder suggestion.
    """
    anons = find_all_anonymous_sdata2_symbols(base_o_path)
    if target_o_path is None or not target_o_path.exists():
        return (anons, [])
    try:
        named_by_value = find_named_sdata2_symbols_by_value(target_o_path)
    except Exception:
        return (anons, [])
    suggested: list[tuple[MagicSymbol, str]] = []
    for sym in anons:
        if sym.size != 8:
            continue
        named = named_by_value.get(sym.value)
        if named:
            suggested.append((sym, named))
    return (anons, suggested)


# Known assert-filename byte strings found in .sdata (NOT .sdata2).
# These come from HSD_ASSERT / __assert calls where jobj.h (and similar)
# inline functions emit the __FILE__ string into .sdata.  When MWCC names
# these @N (anonymous), checkdiff reports a relocation-name mismatch.
_KNOWN_ASSERT_STRINGS: frozenset[str] = frozenset([
    "jobj.h", "jobj",
    "lobj.h", "lobj",
    "dobj.h", "dobj",
    "aobj.h", "aobj",
    "cobj.h", "cobj",
    "mobj.h", "mobj",
])


def find_anonymous_assert_strings(
    o_path: Path,
) -> list[tuple[str, str]]:
    """Scan the .sdata section of `o_path` for anonymous @N symbols whose
    content is a known HSD_ASSERT filename or condition string.

    Returns a list of (symbol_name, decoded_string) pairs — e.g.
    [("@12", "jobj.h"), ("@13", "jobj")].

    Empty list if no .sdata section exists, pyelftools is unavailable, or no
    anonymous assert strings are found.

    This is used by `stuck` / `ceiling` to detect the "HSD_ASSERT override"
    pattern: when jobj.h inline functions emit anonymous @N strings, the fix
    is to `#undef`/`#define HSD_ASSERT` before the `<baselib/jobj.h>` include
    and route the assert through named extern char[] symbols.
    """
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError:
        return []

    out: list[tuple[str, str]] = []
    try:
        with o_path.open("rb") as f:
            elf = ELFFile(f)
            sdata = elf.get_section_by_name(".sdata")
            if sdata is None:
                return []
            sdata_idx = elf.get_section_index(".sdata")
            data = sdata.data()
            symtab = elf.get_section_by_name(".symtab")
            if symtab is None:
                return []
            for sym in symtab.iter_symbols():
                if sym["st_shndx"] != sdata_idx:
                    continue
                name = sym.name
                if not name or not name.startswith("@"):
                    continue
                size = sym["st_size"]
                # Assert strings are short (5-12 bytes) and NUL-terminated.
                if not (4 <= size <= 16):
                    continue
                offset = sym["st_value"]
                if offset + size > len(data):
                    continue
                raw = data[offset:offset + size]
                # Must be printable ASCII followed by a NUL byte.
                if raw[-1] != 0:
                    continue
                try:
                    decoded = raw[:-1].decode("ascii")
                except (UnicodeDecodeError, ValueError):
                    continue
                if not all(0x20 <= b < 0x7F for b in raw[:-1]):
                    continue
                # Match against known set OR any short printable string that
                # looks like an assert filename (contains '.' or is all alpha).
                if (decoded in _KNOWN_ASSERT_STRINGS
                        or (len(decoded) <= 12
                            and decoded.replace(".", "").replace("_", "").isalpha())):
                    out.append((name, decoded))
    except Exception:
        pass
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


def globalize_symbols(
    o_path: Path,
    names: list[str],
    objcopy: str = "/opt/devkitpro/devkitPPC/bin/powerpc-eabi-objcopy",
) -> None:
    """Make each symbol in `names` global (STB_GLOBAL) in `o_path`.

    Uses objcopy with one ``--globalize-symbol <name>`` argument per name.
    The operation is in-place: a temp file is written then atomically moved
    over the original.

    Raises subprocess.CalledProcessError if objcopy fails.
    Raises FileNotFoundError if objcopy is not found.
    """
    if not names:
        return

    with tempfile.NamedTemporaryFile(suffix=".o", delete=False) as tf_out:
        tmp_out = tf_out.name
    try:
        args = [objcopy]
        for name in names:
            args += ["--globalize-symbol", name]
        args += [str(o_path), tmp_out]
        subprocess.run(args, check=True)
        shutil.move(tmp_out, str(o_path))
    finally:
        Path(tmp_out).unlink(missing_ok=True)
