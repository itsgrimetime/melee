"""Tests for the compile.sh fixer (decomp-permuter mac+wine workaround)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.mwcc_debug.fix_perm_compile import (
    FixResult,
    fix_compile_sh,
    fix_perm_dir,
)


# A literal compile.sh as written by decomp-permuter's import.py.
BUGGY_COMPILE_SH = textwrap.dedent('''\
    #!/usr/bin/env bash
    INPUT="$(realpath "$1")"
    OUTPUT="$(realpath "$3")"
    cd /Users/mike/code/melee
    wine build/compilers/GC/1.2.5n/mwcceppc.exe -Cpp_exceptions off -proc gekko "$INPUT" -o "$OUTPUT"
''')


def test_fix_compile_sh_rewrites_buggy_file(tmp_path: Path) -> None:
    """A fresh import.py-generated compile.sh gets the staging trick applied."""
    compile_sh = tmp_path / "compile.sh"
    compile_sh.write_text(BUGGY_COMPILE_SH)

    result = fix_compile_sh(compile_sh)
    assert result.action == "fixed"

    new_text = compile_sh.read_text()
    # The fix marker is present
    assert "Patched by melee-agent debug fix-perm-compile" in new_text
    # The staging trick is in place
    assert 'STAGE="nonmatchings/.permuter_stage_$$.c"' in new_text
    assert 'cp "$INPUT_ABS" "$STAGE"' in new_text
    assert 'trap' in new_text
    # The buggy `realpath "$1"` line is gone (replaced by INPUT_ABS)
    assert 'INPUT="$(realpath "$1")"' not in new_text
    assert 'INPUT_ABS="$(realpath "$1")"' in new_text
    # The wine command still exists with $INPUT and $OUTPUT
    assert 'wine build/compilers' in new_text
    assert '"$INPUT" -o "$OUTPUT"' in new_text


def test_fix_compile_sh_is_idempotent(tmp_path: Path) -> None:
    """Re-fixing an already-fixed file is a no-op."""
    compile_sh = tmp_path / "compile.sh"
    compile_sh.write_text(BUGGY_COMPILE_SH)

    first = fix_compile_sh(compile_sh)
    assert first.action == "fixed"
    after_first = compile_sh.read_text()

    second = fix_compile_sh(compile_sh)
    assert second.action == "already-fixed"
    # File unchanged on second call
    assert compile_sh.read_text() == after_first


def test_fix_compile_sh_skips_unrelated_file(tmp_path: Path) -> None:
    """If the file doesn't have the `realpath "$1"` pattern, do nothing."""
    compile_sh = tmp_path / "compile.sh"
    compile_sh.write_text("#!/usr/bin/env bash\necho hi\n")

    result = fix_compile_sh(compile_sh)
    assert result.action == "not-applicable"
    # File unchanged
    assert "echo hi" in compile_sh.read_text()


def test_fix_compile_sh_handles_missing_file(tmp_path: Path) -> None:
    """Missing file → skipped action, no exception."""
    nonexistent = tmp_path / "nope.sh"
    result = fix_compile_sh(nonexistent)
    assert result.action == "skipped"


def test_fix_perm_dir_finds_compile_sh(tmp_path: Path) -> None:
    """Pointing at a nonmatchings/<fn>/ dir finds compile.sh and fixes it."""
    perm_dir = tmp_path / "nonmatchings" / "fn_xyz"
    perm_dir.mkdir(parents=True)
    compile_sh = perm_dir / "compile.sh"
    compile_sh.write_text(BUGGY_COMPILE_SH)

    result = fix_perm_dir(perm_dir)
    assert result.action == "fixed"
    assert "nonmatchings/.permuter_stage_$$.c" in compile_sh.read_text()


def test_fix_perm_dir_skips_when_no_compile_sh(tmp_path: Path) -> None:
    perm_dir = tmp_path / "empty"
    perm_dir.mkdir()
    result = fix_perm_dir(perm_dir)
    assert result.action == "skipped"


def test_fixed_script_preserves_executable_bit(tmp_path: Path) -> None:
    compile_sh = tmp_path / "compile.sh"
    compile_sh.write_text(BUGGY_COMPILE_SH)
    compile_sh.chmod(0o755)
    fix_compile_sh(compile_sh)
    # 0o755 = rwxr-xr-x
    assert compile_sh.stat().st_mode & 0o111  # at least some execute bit set


def test_fixed_script_keeps_compile_command(tmp_path: Path) -> None:
    """All the original mwcc flags survive the rewrite."""
    compile_sh = tmp_path / "compile.sh"
    long_cmd = textwrap.dedent('''\
        #!/usr/bin/env bash
        INPUT="$(realpath "$1")"
        OUTPUT="$(realpath "$3")"
        cd /Users/mike/code/melee
        wine build/compilers/GC/1.2.5n/mwcceppc.exe -Cpp_exceptions off -proc gekko -fp hard -fp_contract on -O4,p -enum int -nodefaults -inline auto -c -i src -i src/MSL -i src/Runtime -i extern/dolphin/include -i src/melee -i src/melee/ft/chara -i src/sysdolphin -DBUILD_VERSION=0 -DVERSION_GALE01 "$INPUT" -o "$OUTPUT"
    ''')
    compile_sh.write_text(long_cmd)

    fix_compile_sh(compile_sh)
    new_text = compile_sh.read_text()
    # All flags survive
    for flag in [
        "-Cpp_exceptions off", "-proc gekko", "-fp hard", "-fp_contract on",
        "-O4,p", "-enum int", "-nodefaults", "-inline auto", "-c",
        "-i src", "-i src/MSL", "-i src/melee/ft/chara",
        "-DBUILD_VERSION=0", "-DVERSION_GALE01",
    ]:
        assert flag in new_text, f"flag {flag!r} missing from rewritten script"
