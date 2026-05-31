"""Tests for the transparent name-magic auto-rename hook in ``tools/checkdiff.py``.

The MWCC compiler emits anonymous ``@N`` symbols into ``.sdata2`` for
int-to-float bias literals. The production .o (extracted from the binary)
references those literals via named globals like ``mnVibration_804DC018``.
The asm diff reports a relocation-name mismatch even though the bytes are
otherwise identical.

``melee-agent debug util verify-name-magic --apply-auto`` resolves this by
renaming the anonymous symbols via objcopy. These tests verify that
``checkdiff.py`` invokes the same auto-rename transparently on the
freshly-compiled .o so callers don't have to.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _load_checkdiff():
    """Dynamically load ``tools/checkdiff.py`` as a module."""
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "tools" / "checkdiff.py"
    assert script.is_file(), f"missing {script}"
    spec = importlib.util.spec_from_file_location("checkdiff", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checkdiff():
    return _load_checkdiff()


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_O = _REPO_ROOT / "build/GALE01/src/melee/mn/mnvibration.o"
_TARGET_O = _REPO_ROOT / "build/GALE01/obj/melee/mn/mnvibration.o"


def _sdata2_anon_symbol_count(o_path: Path) -> int:
    """Count @N anonymous symbols whose section is .sdata2."""
    from elftools.elf.elffile import ELFFile

    with o_path.open("rb") as f:
        elf = ELFFile(f)
        sdata2_idx = elf.get_section_index(".sdata2")
        symtab = elf.get_section_by_name(".symtab")
        return sum(
            1 for s in symtab.iter_symbols()
            if s["st_shndx"] == sdata2_idx
            and s.name and s.name.startswith("@")
            and s["st_size"] == 8
        )


@pytest.mark.skipif(
    not (_SRC_O.exists() and _TARGET_O.exists()),
    reason="requires built .o files; run `ninja` first",
)
def test_apply_name_magic_renames_anonymous_sdata2_symbols(
    tmp_path: Path, checkdiff,
) -> None:
    """The helper renames anonymous .sdata2 magic symbols via the production .o.

    Pre-condition: the fixture .o contains anonymous @N symbols for the s32
    and u32 int-to-float bias constants. After the helper runs, those
    symbols are gone (replaced by named globals from the target .o).
    """
    work_o = tmp_path / "mnvibration.o"
    shutil.copy(_SRC_O, work_o)

    assert _sdata2_anon_symbol_count(work_o) >= 2, (
        "fixture must have anonymous 8-byte @N symbols in .sdata2"
    )

    result = checkdiff.apply_name_magic_if_available(work_o, _TARGET_O)

    assert result is not None
    assert len(result["renames"]) >= 2, (
        f"expected at least 2 renames (s32 + u32 bias); got {result['renames']}"
    )
    assert _sdata2_anon_symbol_count(work_o) == 0, (
        "all 8-byte anonymous .sdata2 symbols should be renamed away"
    )


@pytest.mark.skipif(
    not (_SRC_O.exists() and _TARGET_O.exists()),
    reason="requires built .o files; run `ninja` first",
)
def test_apply_name_magic_is_idempotent(tmp_path: Path, checkdiff) -> None:
    """Running the rename twice produces zero renames the second time.

    This is the property that lets checkdiff invoke the rename
    unconditionally on every run without compounding effects.
    """
    work_o = tmp_path / "mnvibration.o"
    shutil.copy(_SRC_O, work_o)

    first = checkdiff.apply_name_magic_if_available(work_o, _TARGET_O)
    assert first is not None
    assert first["renames"], "first run should produce renames"

    second = checkdiff.apply_name_magic_if_available(work_o, _TARGET_O)
    assert second is not None
    assert second["renames"] == [], (
        f"second run on already-renamed .o should be a no-op; "
        f"got {second['renames']}"
    )


def test_apply_name_magic_returns_none_when_target_missing(
    tmp_path: Path, checkdiff,
) -> None:
    """No production .o → silently skip (return None). checkdiff still works
    on .o files that don't have a target counterpart yet.
    """
    fake_src = tmp_path / "src.o"
    fake_target = tmp_path / "does_not_exist.o"
    fake_src.write_bytes(b"")  # contents don't matter; target missing first

    result = checkdiff.apply_name_magic_if_available(fake_src, fake_target)
    assert result is None


@pytest.mark.skipif(
    not (_SRC_O.exists() and _TARGET_O.exists()),
    reason="requires built .o files; run `ninja` first",
)
def test_apply_name_magic_does_not_corrupt_already_matching_function(
    tmp_path: Path, checkdiff,
) -> None:
    """Renaming the .sdata2 anonymous magic symbols must not disturb functions
    that already match (they reference named globals, not @N).

    Canary: ``mnVibration_802474C4`` is in the same TU but references only
    named symbols. Its disassembly bytes and relocation targets must be
    bit-identical before and after the rename.
    """
    work_o = tmp_path / "mnvibration.o"
    shutil.copy(_SRC_O, work_o)

    def _function_bytes_and_relocs(o_path: Path, func_name: str) -> tuple:
        from elftools.elf.elffile import ELFFile

        with o_path.open("rb") as f:
            elf = ELFFile(f)
            text = elf.get_section_by_name(".text")
            symtab = elf.get_section_by_name(".symtab")
            sym_names = [s.name for s in symtab.iter_symbols()]
            faddr = fsize = None
            for s in symtab.iter_symbols():
                if s.name == func_name:
                    faddr = s["st_value"]
                    fsize = s["st_size"]
                    break
            assert faddr is not None, f"{func_name} not in symtab"
            text_data = text.data()
            body = bytes(text_data[faddr:faddr + fsize])
            relocs: list[tuple[int, str]] = []
            for sec in elf.iter_sections():
                if sec.name in (".rela.text", ".rel.text"):
                    for r in sec.iter_relocations():
                        off = r["r_offset"]
                        if faddr <= off < faddr + fsize:
                            relocs.append(
                                (off - faddr, sym_names[r["r_info_sym"]])
                            )
            relocs.sort()
            return body, relocs

    before = _function_bytes_and_relocs(work_o, "mnVibration_802474C4")
    checkdiff.apply_name_magic_if_available(work_o, _TARGET_O)
    after = _function_bytes_and_relocs(work_o, "mnVibration_802474C4")

    assert before == after, (
        "mnVibration_802474C4 bytes/relocs changed after auto-rename: "
        f"before={before}, after={after}"
    )


# ---------------------------------------------------------------------------
# End-to-end subprocess tests: run tools/checkdiff.py as a process and
# inspect the .o it produced. Verifies the main() wiring (--no-name-magic
# flag handling, automatic invocation on every run).
# ---------------------------------------------------------------------------

_CHECKDIFF = _REPO_ROOT / "tools" / "checkdiff.py"
_REPORT_JSON = _REPO_ROOT / "build/GALE01/report.json"


def _has_anon_sdata2_magic(o_path: Path) -> bool:
    """True if ``o_path`` still has any 8-byte anonymous .sdata2 symbol."""
    return _sdata2_anon_symbol_count(o_path) > 0


def _build_fresh_src_o() -> bool:
    """Rebuild ``build/GALE01/src/melee/mn/mnvibration.o`` from source so
    its .sdata2 has fresh @N anonymous symbols. Returns True on success.
    """
    _SRC_O.unlink(missing_ok=True)
    result = subprocess.run(
        ["ninja", str(_SRC_O.relative_to(_REPO_ROOT))],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and _SRC_O.exists()


@pytest.fixture
def _fresh_then_restored_src_o():
    """Rebuild ``_SRC_O`` before the test and again after, so the mutating
    subprocess tests don't leak the renamed state to later tests (here or
    in other files) that expect anonymous ``@N`` symbols.
    """
    if not _build_fresh_src_o():
        pytest.skip("ninja could not rebuild the source .o")
    yield
    _build_fresh_src_o()


@pytest.mark.skipif(
    not (_CHECKDIFF.exists() and _TARGET_O.exists() and _REPORT_JSON.exists()),
    reason="requires built fixtures (target .o + report.json); run `ninja` first",
)
def test_checkdiff_main_applies_name_magic_by_default(
    _fresh_then_restored_src_o,
) -> None:
    """End-to-end: running checkdiff with default flags renames the
    anonymous .sdata2 @N symbols in the source .o on disk.

    This is the canary the task description asks for — confirms the
    transparent auto-rename is wired up via ``main()`` and not only
    available as a helper.
    """
    assert _has_anon_sdata2_magic(_SRC_O), (
        "freshly-built .o should have anonymous @N magic symbols"
    )

    subprocess.run(
        [sys.executable, str(_CHECKDIFF),
         "mnVibration_802474C4", "--no-build", "--format", "json"],
        cwd=_REPO_ROOT,
        capture_output=True,
    )

    assert not _has_anon_sdata2_magic(_SRC_O), (
        "after default checkdiff run, the source .o should have its "
        "anonymous @N magic symbols renamed away"
    )


@pytest.mark.skipif(
    not (_CHECKDIFF.exists() and _TARGET_O.exists() and _REPORT_JSON.exists()),
    reason="requires built fixtures (target .o + report.json); run `ninja` first",
)
def test_checkdiff_main_respects_no_name_magic_flag(
    _fresh_then_restored_src_o,
) -> None:
    """``--no-name-magic`` must skip the rename entirely so users can
    inspect the raw anonymous-symbol state when debugging.
    """
    assert _has_anon_sdata2_magic(_SRC_O)

    subprocess.run(
        [sys.executable, str(_CHECKDIFF),
         "mnVibration_802474C4", "--no-build", "--no-name-magic",
         "--format", "json"],
        cwd=_REPO_ROOT,
        capture_output=True,
    )

    assert _has_anon_sdata2_magic(_SRC_O), (
        "--no-name-magic must leave anonymous @N magic symbols intact"
    )


@pytest.mark.skipif(
    not (_CHECKDIFF.exists() and _TARGET_O.exists() and _REPORT_JSON.exists()),
    reason="requires built fixtures (target .o + report.json); run `ninja` first",
)
def test_checkdiff_run_twice_is_idempotent(_fresh_then_restored_src_o) -> None:
    """Running checkdiff twice in a row produces identical JSON output.

    Property the task description calls out explicitly. Validates the
    rewrite is byte-stable across runs once @N symbols are gone.
    """
    def _run() -> dict:
        proc = subprocess.run(
            [sys.executable, str(_CHECKDIFF),
             "mnVibration_802474C4", "--no-build", "--format", "json"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )
        return json.loads(proc.stdout)

    first = _run()
    second = _run()
    # Drop run-relative bits (previous_run is the inverse of the current run).
    first.pop("previous_run", None)
    second.pop("previous_run", None)
    assert first == second, (
        "checkdiff run twice produced different output; the rename "
        "step must be idempotent"
    )
