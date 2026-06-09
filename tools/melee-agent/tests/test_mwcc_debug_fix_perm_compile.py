"""Tests for the compile.sh fixer (decomp-permuter mac+wine workaround)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.mwcc_debug.fix_perm_compile import (
    FixResult,
    _inject_null_define,
    _needs_null_define,
    fix_base_c,
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


BUGGY_BASE_C = textwrap.dedent('''\
    typedef float f32;
    typedef struct _PermuterTemp1 Vec;
    typedef struct _PermuterTemp1 Vec3;
    typedef struct HSD_JObj HSD_JObj;

    struct Example {
        Vec3 translate;
        Vec3 scale;
    };

    struct HSD_JObj {
        Vec3 translate;
    };
''')


def test_fix_compile_sh_rewrites_buggy_file(tmp_path: Path) -> None:
    """A fresh import.py-generated compile.sh gets the staging trick applied."""
    compile_sh = tmp_path / "compile.sh"
    compile_sh.write_text(BUGGY_COMPILE_SH)

    result = fix_compile_sh(compile_sh)
    assert result.action == "fixed"

    new_text = compile_sh.read_text()
    # The fix marker is present
    assert "Patched by melee-agent debug permute fix-compile" in new_text
    # The staging trick is in place
    assert 'STAGE="nonmatchings/.permuter_stage_$$.c"' in new_text
    assert 'cp "$INPUT_ABS" "$STAGE"' in new_text
    assert 'trap' in new_text
    # The buggy `realpath "$1"` line is gone (replaced by INPUT_ABS)
    assert 'INPUT="$(realpath "$1")"' not in new_text
    assert 'INPUT_ABS="$(realpath "$1")"' in new_text
    # The compiler now runs through local wibo, not Wine.
    assert 'WIBO="${MWCC_DEBUG_WIBO:-build/tools/wibo}"' in new_text
    assert '"$WIBO" build/compilers' in new_text
    assert 'wine build/compilers' not in new_text
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


def test_fix_perm_dir_defines_vec3_permuter_temp_in_base_c(tmp_path: Path) -> None:
    """Imported Melee cases can forward-declare Vec/Vec3 as an incomplete temp."""
    perm_dir = tmp_path / "nonmatchings" / "fn_xyz"
    perm_dir.mkdir(parents=True)
    compile_sh = perm_dir / "compile.sh"
    compile_sh.write_text(BUGGY_COMPILE_SH)
    base_c = perm_dir / "base.c"
    base_c.write_text(BUGGY_BASE_C)

    result = fix_perm_dir(perm_dir)

    assert result.action == "fixed"
    fixed = base_c.read_text()
    assert "typedef struct _PermuterTemp1 {\n  f32 x;\n  f32 y;\n  f32 z;\n} Vec;" in fixed
    assert "typedef struct _PermuterTemp1 Vec3;" in fixed


def test_fix_perm_dir_vec3_temp_patch_is_idempotent(tmp_path: Path) -> None:
    perm_dir = tmp_path / "nonmatchings" / "fn_xyz"
    perm_dir.mkdir(parents=True)
    (perm_dir / "compile.sh").write_text(BUGGY_COMPILE_SH)
    base_c = perm_dir / "base.c"
    base_c.write_text(BUGGY_BASE_C)

    first = fix_perm_dir(perm_dir)
    assert first.action == "fixed"
    after_first = base_c.read_text()
    second = fix_perm_dir(perm_dir)

    assert second.action == "already-fixed"
    assert base_c.read_text() == after_first


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


# ── NULL define tests ────────────────────────────────────────────────────────

BASE_C_WITH_NULL_NO_DEFINE = textwrap.dedent('''\
    #include "melee.h"
    #pragma _permuter latedefine end
    void fn_test(void) {
        if (ptr == NULL) return;
    }
''')


BASE_C_WITH_NULL_AND_DEFINE = textwrap.dedent('''\
    #include "melee.h"
    #pragma _permuter latedefine end
    #define NULL ((void *)0)
    void fn_test(void) {
        if (ptr == NULL) return;
    }
''')


BASE_C_WITHOUT_NULL = textwrap.dedent('''\
    #include "melee.h"
    #pragma _permuter latedefine end
    void fn_test(void) {
        return;
    }
''')


BASE_C_WITH_NULL_NO_LATEDEFINE = textwrap.dedent('''\
    #include "melee.h"
    void fn_test(void) {
        if (ptr == NULL) return;
    }
''')


def test_needs_null_define_detects_missing() -> None:
    lines = BASE_C_WITH_NULL_NO_DEFINE.splitlines()
    assert _needs_null_define(lines) is True


def test_needs_null_define_rejects_already_defined() -> None:
    lines = BASE_C_WITH_NULL_AND_DEFINE.splitlines()
    assert _needs_null_define(lines) is False


def test_needs_null_define_rejects_no_null_usage() -> None:
    lines = BASE_C_WITHOUT_NULL.splitlines()
    assert _needs_null_define(lines) is False


def test_inject_null_define_after_latedefine() -> None:
    lines = BASE_C_WITH_NULL_NO_DEFINE.splitlines()
    out, changed = _inject_null_define(lines)
    assert changed is True
    out_text = "\n".join(out)
    assert "#define NULL ((void *)0)" in out_text
    # Should appear after the latedefine pragma
    late_idx = out.index("#pragma _permuter latedefine end")
    null_idx = out.index("#define NULL ((void *)0)")
    assert null_idx == late_idx + 1


def test_inject_null_define_no_latedefine() -> None:
    lines = BASE_C_WITH_NULL_NO_LATEDEFINE.splitlines()
    out, changed = _inject_null_define(lines)
    assert changed is True
    out_text = "\n".join(out)
    assert "#define NULL ((void *)0)" in out_text


def test_inject_null_define_idempotent() -> None:
    lines = BASE_C_WITH_NULL_AND_DEFINE.splitlines()
    out, changed = _inject_null_define(lines)
    assert changed is False


def test_fix_base_c_injects_null_define(tmp_path: Path) -> None:
    base_c = tmp_path / "base.c"
    base_c.write_text(BASE_C_WITH_NULL_NO_DEFINE)
    result = fix_base_c(base_c)
    assert result.action == "fixed"
    assert "injected #define NULL" in result.reason
    assert "#define NULL ((void *)0)" in base_c.read_text()


def test_fix_base_c_null_define_idempotent(tmp_path: Path) -> None:
    base_c = tmp_path / "base.c"
    base_c.write_text(BASE_C_WITH_NULL_AND_DEFINE)
    first = fix_base_c(base_c)
    assert first.action == "already-fixed"


def test_fix_base_c_both_fixes_applied(tmp_path: Path) -> None:
    """When both Vec alias and NULL define need fixing, both are applied."""
    base_c = tmp_path / "base.c"
    both = (
        "typedef struct _PermuterTemp1 Vec;\n"
        "typedef struct _PermuterTemp1 Vec3;\n"
        + BASE_C_WITH_NULL_NO_DEFINE
    )
    base_c.write_text(both)
    result = fix_base_c(base_c)
    assert result.action == "fixed"
    out = base_c.read_text()
    assert "Vec;" in out
    assert "#define NULL ((void *)0)" in out
    assert "Vec/Vec3" in result.reason and "NULL" in result.reason
