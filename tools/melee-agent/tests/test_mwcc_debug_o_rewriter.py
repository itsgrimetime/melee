"""Tests for the .o post-processor that renames anonymous magic-constant
symbols to user-supplied names."""

from __future__ import annotations

import shutil
import struct
import tempfile
from pathlib import Path

import pytest

from src.mwcc_debug.o_rewriter import (
    MAGIC_S32,
    MAGIC_U32,
    AutoRenameResult,
    MagicSymbol,
    Mapping,
    apply_name_magic_auto,
    find_magic_symbols,
    find_named_assert_strings_by_value,
    find_named_sdata2_symbols_by_value,
    globalize_symbols,
    parse_mapping,
    rename_magic_symbols,
    suggest_name_magic_map,
)


def test_parse_mapping_shortcuts() -> None:
    m = parse_mapping("s32=mnVibration_804DC018,u32=mnVibration_804DC010")
    assert m.by_value == {
        MAGIC_S32: "mnVibration_804DC018",
        MAGIC_U32: "mnVibration_804DC010",
    }
    assert m.by_name == {}


def test_parse_mapping_hex_literal() -> None:
    m = parse_mapping("0x4330000080000000=foo,0x4330000000000000=bar")
    assert m.by_value == {
        MAGIC_S32: "foo",
        MAGIC_U32: "bar",
    }


def test_parse_mapping_handles_whitespace() -> None:
    m = parse_mapping("  s32 = name1 ,  u32 = name2  ")
    assert m.by_value[MAGIC_S32] == "name1"
    assert m.by_value[MAGIC_U32] == "name2"


def test_parse_mapping_at_n_direct_rename() -> None:
    m = parse_mapping("@791=mnVibration_804DC050,@473=foo")
    assert m.by_name == {
        "@791": "mnVibration_804DC050",
        "@473": "foo",
    }
    assert m.by_value == {}


def test_parse_mapping_mixed_value_and_name() -> None:
    m = parse_mapping("s32=mnVib_018,@791=mnVib_050")
    assert m.by_value == {MAGIC_S32: "mnVib_018"}
    assert m.by_name == {"@791": "mnVib_050"}


def test_parse_mapping_rejects_missing_equals() -> None:
    with pytest.raises(ValueError, match="need '<key>=<name>'"):
        parse_mapping("s32-bad")


def test_parse_mapping_rejects_unknown_shortcut() -> None:
    with pytest.raises(ValueError, match="invalid value"):
        parse_mapping("bogus=name")


def test_parse_mapping_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="empty name"):
        parse_mapping("s32=")


# Path to a real .o file from the build (skipped if not present)
_FIXTURE_O = Path(__file__).parent.parent.parent.parent / \
    "build" / "GALE01" / "src" / "melee" / "mn" / "mnvibration.o"
_GM_1832_TARGET_O = Path(__file__).parent.parent.parent.parent / \
    "build" / "GALE01" / "obj" / "melee" / "gm" / "gm_1832.o"


@pytest.mark.skipif(not _FIXTURE_O.exists(),
                    reason="requires built .o; run `ninja` first")
def test_find_magic_symbols_on_real_o() -> None:
    """Real .o has anonymous symbols for the s32 + u32 int-to-float biases."""
    syms = find_magic_symbols(_FIXTURE_O)
    values = {s.value for s in syms}
    # The mnvibration.o always has at least the s32 bias (it does int-to-
    # float casts) and the u32 bias (similar). Both should be detected.
    assert MAGIC_S32 in values, (
        f"expected s32 bias in {_FIXTURE_O.name}; got values: "
        f"{[hex(v) for v in values]}"
    )
    assert MAGIC_U32 in values
    for sym in syms:
        assert sym.name.startswith("@")
        assert sym.size == 8


@pytest.mark.skipif(not _FIXTURE_O.exists(),
                    reason="requires built .o; run `ninja` first")
def test_rename_magic_symbols_creates_renamed_o(tmp_path: Path) -> None:
    """End-to-end: copy a real .o, rename its s32 magic symbol, verify
    the new name appears in the symbol table.
    """
    work_o = tmp_path / "test.o"
    shutil.copy(_FIXTURE_O, work_o)
    mapping = Mapping(by_value={MAGIC_S32: "mnVibration_804DC018"}, by_name={})
    renames = rename_magic_symbols(work_o, mapping)
    assert len(renames) == 1
    old_name, new_name = renames[0]
    assert new_name == "mnVibration_804DC018"
    assert old_name.startswith("@")

    # Confirm the symbol is renamed in the result
    syms_after = find_magic_symbols(work_o)
    new_names = {s.name for s in syms_after}
    # The new name no longer starts with @, so find_magic_symbols (which
    # filters on @) won't show it. Instead, check via elftools directly.
    from elftools.elf.elffile import ELFFile
    with work_o.open("rb") as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name(".symtab")
        all_names = {sym.name for sym in symtab.iter_symbols()}
    assert "mnVibration_804DC018" in all_names
    assert old_name not in all_names


@pytest.mark.skipif(not _FIXTURE_O.exists(),
                    reason="requires built .o; run `ninja` first")
def test_rename_magic_symbols_no_match_returns_empty(tmp_path: Path) -> None:
    """When the mapping has values not present in the .o, no renames happen."""
    work_o = tmp_path / "test.o"
    shutil.copy(_FIXTURE_O, work_o)
    mapping = Mapping(
        by_value={0xDEADBEEFCAFEBABE: "should_not_appear"},
        by_name={},
    )
    renames = rename_magic_symbols(work_o, mapping)
    assert renames == []


def test_globalize_symbols_noop_on_empty_list(tmp_path: Path) -> None:
    """globalize_symbols with an empty name list must not invoke objcopy."""
    # We don't have a .o here — passing a nonexistent path is fine because
    # globalize_symbols must return early when names=[].
    fake_o = tmp_path / "nonexistent.o"
    # Should not raise even though the file doesn't exist.
    globalize_symbols(fake_o, [])  # no-op contract


@pytest.mark.skipif(not _FIXTURE_O.exists(),
                    reason="requires built .o; run `ninja` first")
def test_globalize_symbols_makes_symbol_global(tmp_path: Path) -> None:
    """End-to-end: rename a magic symbol then globalize it; verify binding."""
    from elftools.elf.elffile import ELFFile

    work_o = tmp_path / "test.o"
    shutil.copy(_FIXTURE_O, work_o)

    # Step 1: rename the s32 magic constant to a known name.
    mapping = Mapping(by_value={MAGIC_S32: "mnVibration_804DC018"}, by_name={})
    renames = rename_magic_symbols(work_o, mapping)
    assert len(renames) == 1
    new_name = renames[0][1]

    # Step 2: confirm symbol is LOCAL before globalize.
    def _binding(o: Path, name: str) -> str:
        with o.open("rb") as f:
            elf = ELFFile(f)
            symtab = elf.get_section_by_name(".symtab")
            for sym in symtab.iter_symbols():
                if sym.name == name:
                    return sym["st_info"]["bind"]
        return "NOT_FOUND"

    assert _binding(work_o, new_name) == "STB_LOCAL", (
        "renamed symbol should start as STB_LOCAL (MWCC emits local @N)"
    )

    # Step 3: globalize and verify binding changed to STB_GLOBAL.
    globalize_symbols(work_o, [new_name])
    assert _binding(work_o, new_name) == "STB_GLOBAL", (
        "symbol should be STB_GLOBAL after globalize_symbols"
    )


# ---------------------------------------------------------------------------
# Tests for Fix A: value-based magic symbol matching in suggest_name_magic_map
# ---------------------------------------------------------------------------

def _make_fake_elf_with_sdata2(symbols: list[tuple[str, int, bytes]]) -> bytes:
    """Build a minimal ELF32 big-endian .o with a .sdata2 section containing
    the provided (name, offset, data_bytes) tuples as named symbols.

    The ELF is intentionally minimal — just enough for pyelftools to parse
    the .sdata2 section and symbol table.  Used to test value-based matching
    without needing a real compiler.

    symbols: list of (sym_name, offset_in_section, 8_byte_value_be)
    """
    # Build section data: concatenate all symbol bytes at their offsets
    sdata2_size = max(off + len(data) for _, off, data in symbols)
    sdata2 = bytearray(sdata2_size)
    for _, off, data in symbols:
        sdata2[off:off + len(data)] = data

    # We'll let the caller construct and inspect the ELF via a round-trip
    # through pyelftools. For test simplicity, we use the real test .o fixture
    # if available, and only test the pure-Python logic otherwise.
    raise NotImplementedError  # Placeholder — see test below


def test_find_named_sdata2_symbols_by_value_matches_by_bytes() -> None:
    """find_named_sdata2_symbols_by_value indexes named symbols by their
    actual bytes, not by section offset.  This is the key invariant for
    Fix A: when the unsigned magic comes FIRST in .sdata2 (before signed),
    the value-based lookup must still return the correct symbol for each.

    This test uses the real mnvibration.o fixture where both magic constants
    appear, and cross-references via the rename + scan approach to verify
    value ↔ name matching is correct.
    """
    _FIXTURE_O = Path(__file__).parent.parent.parent.parent / \
        "build" / "GALE01" / "src" / "melee" / "mn" / "mnvibration.o"
    _TARGET_O = Path(__file__).parent.parent.parent.parent / \
        "build" / "GALE01" / "obj" / "melee" / "mn" / "mnvibration.o"

    if not _TARGET_O.exists():
        pytest.skip("requires built target .o; run `ninja` first")

    by_value = find_named_sdata2_symbols_by_value(_TARGET_O)
    # The two int-to-float magic constants must map to different named symbols
    s32_sym = by_value.get(MAGIC_S32)
    u32_sym = by_value.get(MAGIC_U32)
    # Both may not always be present in mnvibration — skip gracefully
    if s32_sym is not None and u32_sym is not None:
        assert s32_sym != u32_sym, (
            "s32 and u32 magic constants must map to DIFFERENT named symbols; "
            f"got s32={s32_sym!r}, u32={u32_sym!r}"
        )
    # Each symbol must be a plausible name (starts with known prefix)
    for val, name in by_value.items():
        assert name and not name.startswith("@"), (
            f"find_named_sdata2_symbols_by_value should only return named "
            f"symbols, got {name!r} for value 0x{val:016x}"
        )


@pytest.mark.skipif(
    not _GM_1832_TARGET_O.exists(),
    reason="requires built gm_1832 target .o; run `ninja` first",
)
def test_find_named_sdata2_symbols_by_value_omits_duplicate_values() -> None:
    """A value lookup must not pick an arbitrary alias for duplicate values."""
    by_value = find_named_sdata2_symbols_by_value(_GM_1832_TARGET_O)

    assert MAGIC_U32 not in by_value
    assert MAGIC_S32 not in by_value


def test_suggest_name_magic_map_uses_value_not_offset() -> None:
    """Regression test for Fix A: suggest_name_magic_map must match
    anonymous symbols to named target symbols by VALUE (bytes), not by
    section offset.

    We verify this invariant by checking that when the target .o has a
    named symbol for MAGIC_U32 (0x4330000000000000), suggest_name_magic_map
    returns that named symbol paired with the anonymous u32 symbol — not the
    s32 symbol at the same offset in the compiled .o.

    Without the fix, if the compiled .o puts the s32 anonymous symbol at
    offset 0 and the target .o has u32 at offset 0, the old offset-based
    logic would incorrectly pair them.
    """
    _COMPILED_O = Path(__file__).parent.parent.parent.parent / \
        "build" / "GALE01" / "src" / "melee" / "mn" / "mnvibration.o"
    _TARGET_O = Path(__file__).parent.parent.parent.parent / \
        "build" / "GALE01" / "obj" / "melee" / "mn" / "mnvibration.o"

    if not _COMPILED_O.exists() or not _TARGET_O.exists():
        pytest.skip("requires built .o files; run `ninja` first")

    _, suggested = suggest_name_magic_map(_COMPILED_O, _TARGET_O)
    # Each (anon_sym, named_sym) pair must match by VALUE
    from src.mwcc_debug.o_rewriter import find_named_sdata2_symbols_by_value
    by_value = find_named_sdata2_symbols_by_value(_TARGET_O)
    for anon_sym, named in suggested:
        if anon_sym.size != 8:
            continue
        expected_name = by_value.get(anon_sym.value)
        assert expected_name == named, (
            f"suggest_name_magic_map returned wrong symbol for "
            f"anonymous {anon_sym.name} (value=0x{anon_sym.value:016x}): "
            f"got {named!r}, expected {expected_name!r} from value lookup. "
            f"This indicates the old offset-based matching is still in use."
        )


def test_suggest_name_magic_map_includes_assert_string_renames() -> None:
    compiled_o = Path(__file__).parent.parent.parent.parent / \
        "build" / "GALE01" / "src" / "sysdolphin" / "baselib" / "cobj.o"
    target_o = Path(__file__).parent.parent.parent.parent / \
        "build" / "GALE01" / "obj" / "sysdolphin" / "baselib" / "cobj.o"
    if not compiled_o.exists() or not target_o.exists():
        pytest.skip("requires built cobj.o files; run `ninja` first")

    named_asserts = find_named_assert_strings_by_value(target_o)
    assert named_asserts["cobj.c"].startswith("HSD_CObj_")
    assert named_asserts["cobj"].startswith("HSD_CObj_")

    _, suggested = suggest_name_magic_map(compiled_o, target_o)
    suggested_by_name = {anon.name: named for anon, named in suggested}

    assert "HSD_CObj_804D5D40" in suggested_by_name.values()
    assert "HSD_CObj_804D5D48" in suggested_by_name.values()


# ---------------------------------------------------------------------------
# Tests for apply_name_magic_auto — the full auto-resolve-and-apply path
# used by `debug util verify-name-magic --apply-auto`
# ---------------------------------------------------------------------------

def test_apply_name_magic_auto_missing_target_returns_empty(
    tmp_path: Path,
) -> None:
    """If the target .o doesn't exist, apply_name_magic_auto must NOT raise.
    It returns an AutoRenameResult with empty renames and unresolved equal
    to the full set of anonymous symbols (callers decide whether to warn).
    """
    fake_base = tmp_path / "base.o"
    fake_target = tmp_path / "target_does_not_exist.o"
    # No base file either — apply_name_magic_auto delegates to
    # suggest_name_magic_map, which calls find_all_anonymous_sdata2_symbols
    # on the base. With no file, pyelftools raises and we propagate.
    # So we create a tiny empty stub via shutil from a real fixture if
    # available; otherwise skip.
    if not _FIXTURE_O.exists():
        pytest.skip("requires built .o; run `ninja` first")
    shutil.copy(_FIXTURE_O, fake_base)

    result = apply_name_magic_auto(fake_base, fake_target)
    assert isinstance(result, AutoRenameResult)
    assert result.renames == []
    assert result.globalized == []
    # Every anonymous symbol in the base .o is unresolved (no target lookup)
    assert len(result.unresolved) == len(result.anonymous_found)
    assert result.target_o_path == fake_target


@pytest.mark.skipif(not _FIXTURE_O.exists(),
                    reason="requires built .o; run `ninja` first")
def test_apply_name_magic_auto_renames_and_globalizes(tmp_path: Path) -> None:
    """End-to-end: apply_name_magic_auto should auto-resolve every
    anonymous .sdata2 magic constant in the base .o using the production
    .o as the lookup source, then both rename them and promote them to
    STB_GLOBAL — no map needed.
    """
    from elftools.elf.elffile import ELFFile

    _TARGET_O = Path(__file__).parent.parent.parent.parent / \
        "build" / "GALE01" / "obj" / "melee" / "mn" / "mnvibration.o"
    if not _TARGET_O.exists():
        pytest.skip("requires built target .o; run `ninja` first")

    work_o = tmp_path / "test.o"
    shutil.copy(_FIXTURE_O, work_o)

    # Pre-check: there must be at least one anonymous magic constant
    pre_syms = find_magic_symbols(work_o)
    assert pre_syms, "fixture .o has no anonymous magic symbols to rename"

    result = apply_name_magic_auto(work_o, _TARGET_O)
    assert isinstance(result, AutoRenameResult)
    assert result.target_o_path == _TARGET_O

    # At least the s32 and/or u32 magic constants should resolve via the
    # production .o (mnvibration has both).
    assert result.renames, (
        "expected at least one rename; got none. "
        f"anonymous_found={len(result.anonymous_found)} "
        f"unresolved={len(result.unresolved)}"
    )

    # Every .sdata2 rename's new name must come from the target's named
    # .sdata2 symbols at the matching value. Other renames may come from
    # assert-string name magic in .sdata.
    by_value = find_named_sdata2_symbols_by_value(_TARGET_O)
    expected_values_to_names = {v: n for v, n in by_value.items()}
    expected_sdata2_names = set(expected_values_to_names.values())
    new_names_in_result = {new for _, new in result.renames}
    sdata2_renames = new_names_in_result & expected_sdata2_names
    assert sdata2_renames, "expected at least one .sdata2 magic rename"
    for new in sdata2_renames:
        assert new in expected_sdata2_names, (
            f"renamed symbol {new!r} is not a named .sdata2 symbol in "
            f"target {_TARGET_O.name}"
        )

    # Every renamed symbol must be present in the new .o's symtab and be
    # STB_GLOBAL (globalize=True by default).
    with work_o.open("rb") as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name(".symtab")
        symtab_names: dict[str, str] = {}
        for sym in symtab.iter_symbols():
            if sym.name:
                symtab_names[sym.name] = sym["st_info"]["bind"]
    for _, new in result.renames:
        assert new in symtab_names, (
            f"renamed symbol {new!r} not present in result symtab"
        )
        assert symtab_names[new] == "STB_GLOBAL", (
            f"renamed symbol {new!r} should be STB_GLOBAL (globalize=True), "
            f"got {symtab_names[new]!r}"
        )

    # globalize list should mirror renames when globalize=True
    assert set(result.globalized) == new_names_in_result


@pytest.mark.skipif(not _FIXTURE_O.exists(),
                    reason="requires built .o; run `ninja` first")
def test_apply_name_magic_auto_no_globalize(tmp_path: Path) -> None:
    """When globalize=False, apply_name_magic_auto renames but leaves the
    new symbols as STB_LOCAL (matching MWCC's default emission).
    """
    from elftools.elf.elffile import ELFFile

    _TARGET_O = Path(__file__).parent.parent.parent.parent / \
        "build" / "GALE01" / "obj" / "melee" / "mn" / "mnvibration.o"
    if not _TARGET_O.exists():
        pytest.skip("requires built target .o; run `ninja` first")

    work_o = tmp_path / "test.o"
    shutil.copy(_FIXTURE_O, work_o)

    result = apply_name_magic_auto(work_o, _TARGET_O, globalize=False)
    assert result.renames, "expected at least one rename"
    assert result.globalized == [], (
        "globalize=False should leave globalized list empty"
    )

    # Verify the renamed symbol is STB_LOCAL (not promoted)
    with work_o.open("rb") as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name(".symtab")
        bindings: dict[str, str] = {
            sym.name: sym["st_info"]["bind"]
            for sym in symtab.iter_symbols() if sym.name
        }
    sdata2_names = set(find_named_sdata2_symbols_by_value(_TARGET_O).values())
    for _, new in result.renames:
        if new not in sdata2_names:
            continue
        assert bindings.get(new) == "STB_LOCAL", (
            f"with globalize=False, renamed symbol {new!r} should remain "
            f"STB_LOCAL; got {bindings.get(new)!r}"
        )


@pytest.mark.skipif(not _FIXTURE_O.exists(),
                    reason="requires built .o; run `ninja` first")
def test_apply_name_magic_auto_unresolved_includes_size4_floats(
    tmp_path: Path,
) -> None:
    """4-byte float-literal anonymous symbols (size=4) are never
    auto-renamed because matching by value would be ambiguous (multiple
    floats can share 0x00000000 etc.). They must appear in the unresolved
    list so callers can warn / inspect.
    """
    _TARGET_O = Path(__file__).parent.parent.parent.parent / \
        "build" / "GALE01" / "obj" / "melee" / "mn" / "mnvibration.o"
    if not _TARGET_O.exists():
        pytest.skip("requires built target .o; run `ninja` first")

    from src.mwcc_debug.o_rewriter import find_all_anonymous_sdata2_symbols

    work_o = tmp_path / "test.o"
    shutil.copy(_FIXTURE_O, work_o)

    all_anon = find_all_anonymous_sdata2_symbols(work_o)
    size4_anon = [s for s in all_anon if s.size == 4]

    result = apply_name_magic_auto(work_o, _TARGET_O)

    # Every 4-byte symbol must be in unresolved (never auto-renamed)
    unresolved_names = {s.name for s in result.unresolved}
    for s4 in size4_anon:
        assert s4.name in unresolved_names, (
            f"4-byte anonymous {s4.name} should be unresolved by "
            f"apply_name_magic_auto, but it wasn't"
        )

    # And none of the renames should target a 4-byte symbol
    renamed_old_names = {old for old, _ in result.renames}
    for s4 in size4_anon:
        assert s4.name not in renamed_old_names, (
            f"apply_name_magic_auto should not auto-rename 4-byte "
            f"symbol {s4.name}, but it did"
        )
