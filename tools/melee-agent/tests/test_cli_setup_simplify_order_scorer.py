"""Tests for `debug permute setup-simplify-order-scorer` end-to-end wiring.

These tests use a fake perm dir layout (no actual decomp-permuter install
needed) and stub the wibo + debug compiler resolution so the test runs
on any machine. Covers:

  * Happy path: spec.yaml, settings.toml, wrapped compile.sh all
    appear with the expected contents.
  * Pre-existing weight_overrides survive the rewrite (merge=True).
  * Missing --baseline-dump prints a helpful error.
  * Missing perm dir prints a helpful error.
  * Already-wrapped compile.sh refuses to clobber without --force.
  * Function name not in baseline pcdump errors clearly.
"""

from __future__ import annotations

import os
import shutil
import stat
import textwrap
from pathlib import Path

import pytest
import toml
from typer.testing import CliRunner

from src.cli import app


runner = CliRunner()


# A minimal mwcc-style compile.sh body. We only need to satisfy:
#   * has a `cd <project_root>` line that _detect_existing_compile_sh_project_root parses
#   * contains a `mwcceppc.exe <flags...> -c "$INPUT" -o "$OUTPUT"` line so
#     _extract_cflags_from_compile_sh can pick out the flags.
SAMPLE_COMPILE_SH = (
    "#!/usr/bin/env bash\n"
    "set -e\n"
    'INPUT_ABS="$(realpath "$1")"\n'
    'OUTPUT_ABS="$(realpath "$3")"\n'
    "cd /fake/project/root\n"
    'STAGE="nonmatchings/.permuter_stage_$$.c"\n'
    'cp "$INPUT_ABS" "$STAGE"\n'
    'INPUT="$STAGE"\n'
    'OUTPUT="$OUTPUT_ABS"\n'
    "wine build/compilers/GC/1.2.5n/mwcceppc.exe -Cpp_exceptions off "
    "-proc gekko -fp hard -O4,p -nodefaults -inline auto "
    '-c "$INPUT" -o "$OUTPUT"\n'
)


def _make_perm_dir(
    tmp_path: Path,
    *,
    function: str,
    compile_sh: str = SAMPLE_COMPILE_SH,
    settings_toml: str | None = None,
) -> Path:
    """Set up a fake <perm_root>/nonmatchings/<function>/ layout."""
    perm_root = tmp_path / "decomp-permuter"
    perm_dir = perm_root / "nonmatchings" / function
    perm_dir.mkdir(parents=True)
    (perm_dir / "base.c").write_text(f"void {function}(void) {{}}\n")
    (perm_dir / "target.o").write_bytes(b"\x00" * 32)
    csh = perm_dir / "compile.sh"
    csh.write_text(compile_sh)
    csh.chmod(0o755)
    if settings_toml is not None:
        (perm_dir / "settings.toml").write_text(settings_toml)
    return perm_root


def _make_baseline_dump(tmp_path: Path, function: str) -> Path:
    """A minimal pcdump that contains the function name. Sufficient for
    the setup command's pre-flight grep (the scorer reads the file at
    score time and re-validates structure)."""
    p = tmp_path / "baseline.pcdump.txt"
    p.write_text(
        f"Starting function {function}\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  42  r30  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  42  1  1  0x0\n"
    )
    return p


def _stub_wibo_and_compiler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Create fake wibo + mwcceppc_debug.exe files and patch the finders.

    Returns (wibo_path, debug_compiler_path).
    """
    wibo = tmp_path / "bin" / "wibo"
    wibo.parent.mkdir(parents=True, exist_ok=True)
    wibo.write_text("#!/bin/sh\nexit 0\n")
    wibo.chmod(0o755)

    compiler_dir = tmp_path / "fake_compilers"
    compiler_dir.mkdir(parents=True, exist_ok=True)
    debug_compiler = compiler_dir / "mwcceppc_debug.exe"
    debug_compiler.write_bytes(b"MZ" + b"\x00" * 32)

    from src.cli import debug as cli_debug

    monkeypatch.setattr(cli_debug, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(cli_debug, "_find_compiler_dir", lambda: compiler_dir)

    return wibo, debug_compiler


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_setup_writes_spec_settings_and_compile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    function = "fn_test"
    perm_root = _make_perm_dir(tmp_path, function=function)
    baseline = _make_baseline_dump(tmp_path, function)
    wibo, debug_compiler = _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "42,32",
            "--class", "0",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
        ],
    )
    assert result.exit_code == 0, result.stdout + "\n" + (result.stderr or "")

    perm_dir = perm_root / "nonmatchings" / function

    # Spec file present and parseable
    spec_path = perm_dir / "simplify_order_target.yaml"
    assert spec_path.exists()
    spec_text = spec_path.read_text()
    assert "function: fn_test" in spec_text
    assert "simplify_order_target: [42, 32]" in spec_text
    assert "class_id: 0" in spec_text
    assert str(baseline) in spec_text

    # Settings.toml present with [scorer] section
    settings_path = perm_dir / "settings.toml"
    assert settings_path.exists()
    parsed = toml.loads(settings_path.read_text())
    assert "scorer" in parsed
    assert "score-simplify-order" in parsed["scorer"]["command"]
    assert "--function" in parsed["scorer"]["command"]
    assert function in parsed["scorer"]["command"]
    assert parsed["scorer"]["timeout_seconds"] == 5.0

    # Compile.sh rewritten with marker + pcdump emit env var + new compiler
    csh = (perm_dir / "compile.sh").read_text()
    assert "setup-simplify-order-scorer" in csh
    assert "MWCC_DEBUG_PCDUMP_PATH" in csh
    assert "mwcceppc_debug.exe" in csh
    assert "-Cpp_exceptions off" in csh  # cflags preserved
    assert "/fake/project/root" in csh  # project root preserved
    # And executable
    mode = (perm_dir / "compile.sh").stat().st_mode
    assert mode & stat.S_IXUSR


def test_setup_preserves_existing_weight_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-existing [weight_overrides] keys must survive the rewrite."""
    function = "fn_test"
    existing_settings = textwrap.dedent("""\
        func_name = "fn_test"
        compiler_type = "mwcc"

        [weight_overrides]
        perm_xor_zero = 5.0
        perm_reorder_decls = 50.0
    """)
    perm_root = _make_perm_dir(
        tmp_path,
        function=function,
        settings_toml=existing_settings,
    )
    baseline = _make_baseline_dump(tmp_path, function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "42",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
        ],
    )
    assert result.exit_code == 0, result.stdout + "\n" + (result.stderr or "")

    parsed = toml.loads(
        (perm_root / "nonmatchings" / function / "settings.toml").read_text()
    )
    assert parsed["weight_overrides"]["perm_xor_zero"] == 5.0
    assert parsed["weight_overrides"]["perm_reorder_decls"] == 50.0
    assert "scorer" in parsed


def test_setup_passes_custom_scorer_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    function = "fn_test"
    perm_root = _make_perm_dir(tmp_path, function=function)
    baseline = _make_baseline_dump(tmp_path, function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "42",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
            "--scorer-timeout", "15.0",
        ],
    )
    assert result.exit_code == 0, result.stdout + "\n" + (result.stderr or "")
    parsed = toml.loads(
        (perm_root / "nonmatchings" / function / "settings.toml").read_text()
    )
    assert parsed["scorer"]["timeout_seconds"] == 15.0


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_setup_missing_perm_dir_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    perm_root = tmp_path / "empty-perm"
    perm_root.mkdir()
    baseline = _make_baseline_dump(tmp_path, "fn_test")
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", "fn_test",
            "--want-first", "42",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
        ],
    )
    assert result.exit_code == 2
    assert "perm dir not found" in (result.stderr or result.stdout)


def test_setup_missing_baseline_dump_fails_with_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    function = "fn_test"
    perm_root = _make_perm_dir(tmp_path, function=function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "42",
            # no --baseline-dump
            "--perm-root", str(perm_root),
        ],
    )
    assert result.exit_code == 2
    err = result.stderr or result.stdout
    assert "--baseline-dump is required" in err
    assert "debug dump local" in err


def test_setup_baseline_missing_function_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Baseline dump exists but doesn't mention the function -> error."""
    function = "fn_test"
    perm_root = _make_perm_dir(tmp_path, function=function)
    # Baseline for a different function — does not mention `fn_test`
    baseline = _make_baseline_dump(tmp_path, "fn_other_unrelated")
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "42",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
        ],
    )
    assert result.exit_code == 2
    err = result.stderr or result.stdout
    assert "does not appear to contain function" in err


def test_setup_refuses_to_re_wrap_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    function = "fn_test"
    perm_root = _make_perm_dir(tmp_path, function=function)
    baseline = _make_baseline_dump(tmp_path, function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    # First run: succeeds
    r1 = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "42",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
        ],
    )
    assert r1.exit_code == 0

    # Second run without --force: refuses
    r2 = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "32,42",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
        ],
    )
    assert r2.exit_code == 2

    # Third run with --force: succeeds and updates
    r3 = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "32,42",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
            "--force",
        ],
    )
    assert r3.exit_code == 0
    spec_text = (
        perm_root / "nonmatchings" / function / "simplify_order_target.yaml"
    ).read_text()
    assert "[32, 42]" in spec_text


def test_setup_invalid_want_first_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    function = "fn_test"
    perm_root = _make_perm_dir(tmp_path, function=function)
    baseline = _make_baseline_dump(tmp_path, function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "not,an,int",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
        ],
    )
    assert result.exit_code == 2
    err = result.stderr or result.stdout
    assert "must be a comma-separated list of integers" in err


def test_setup_missing_compile_sh_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    function = "fn_test"
    perm_root = tmp_path / "decomp-permuter"
    perm_dir = perm_root / "nonmatchings" / function
    perm_dir.mkdir(parents=True)
    (perm_dir / "base.c").write_text("void fn_test(void) {}\n")
    (perm_dir / "target.o").write_bytes(b"\x00" * 32)
    # NO compile.sh

    baseline = _make_baseline_dump(tmp_path, function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "42",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
        ],
    )
    assert result.exit_code == 2
    err = result.stderr or result.stdout
    assert "compile.sh" in err


# ---------------------------------------------------------------------------
# --force-phys flag tests
# ---------------------------------------------------------------------------


def test_setup_force_phys_flag_parses_and_writes_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--force-phys 44:10,46:12` writes force_phys into target.yaml."""
    function = "lbDvd_test"
    perm_root = _make_perm_dir(tmp_path, function=function)
    baseline = _make_baseline_dump(tmp_path, function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "46,44",
            "--class", "0",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
            "--force-phys", "44:10,46:12",
            "--force",
        ],
    )

    assert result.exit_code == 0, result.stdout + "\n" + (result.stderr or "")
    perm_dir = perm_root / "nonmatchings" / function
    target_yaml = perm_dir / "simplify_order_target.yaml"
    assert target_yaml.exists()
    content = target_yaml.read_text(encoding="utf-8")
    assert "force_phys:" in content
    assert "44: 10" in content
    assert "46: 12" in content


def test_setup_without_force_phys_omits_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without --force-phys, target.yaml does not contain force_phys."""
    function = "gm_test"
    perm_root = _make_perm_dir(tmp_path, function=function)
    baseline = _make_baseline_dump(tmp_path, function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "34,37,32",
            "--class", "0",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
            "--force",
        ],
    )

    assert result.exit_code == 0, result.stdout + "\n" + (result.stderr or "")
    perm_dir = perm_root / "nonmatchings" / function
    target_yaml = perm_dir / "simplify_order_target.yaml"
    content = target_yaml.read_text(encoding="utf-8")
    assert "force_phys:" not in content


def test_setup_force_phys_invalid_format_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--force-phys with bad format gives clear error."""
    function = "fn_test"
    perm_root = _make_perm_dir(tmp_path, function=function)
    baseline = _make_baseline_dump(tmp_path, function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "1",
            "--class", "0",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
            "--force-phys", "not-a-pair",
            "--force",
        ],
    )

    assert result.exit_code != 0
    err = result.stderr or result.stdout
    assert "force-phys" in err.lower()


# ---------------------------------------------------------------------------
# --no-coalesce-preservation flag tests
# ---------------------------------------------------------------------------


def test_setup_default_coalesce_preservation_omits_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without --no-coalesce-preservation, target.yaml omits the key."""
    function = "gm_test"
    perm_root = _make_perm_dir(tmp_path, function=function)
    baseline = _make_baseline_dump(tmp_path, function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "1",
            "--class", "0",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
            "--force-phys", "34:31",
            "--force",
        ],
    )

    assert result.exit_code == 0, result.stdout + "\n" + (result.stderr or "")
    perm_dir = perm_root / "nonmatchings" / function
    content = (perm_dir / "simplify_order_target.yaml").read_text(encoding="utf-8")
    assert "coalesce_preservation" not in content


def test_setup_no_coalesce_preservation_writes_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--no-coalesce-preservation writes the opt-out into target.yaml."""
    function = "gm_test"
    perm_root = _make_perm_dir(tmp_path, function=function)
    baseline = _make_baseline_dump(tmp_path, function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "1",
            "--class", "0",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
            "--force-phys", "34:31",
            "--no-coalesce-preservation",
            "--force",
        ],
    )

    assert result.exit_code == 0, result.stdout + "\n" + (result.stderr or "")
    perm_dir = perm_root / "nonmatchings" / function
    content = (perm_dir / "simplify_order_target.yaml").read_text(encoding="utf-8")
    assert "coalesce_preservation: false" in content


# ---------------------------------------------------------------------------
# --want-late flag tests
# ---------------------------------------------------------------------------


def test_setup_want_late_writes_simplify_order_target_late(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--want-late 46,44` writes simplify_order_target_late to target.yaml."""
    function = "lbDvd_test"
    perm_root = _make_perm_dir(tmp_path, function=function)
    baseline = _make_baseline_dump(tmp_path, function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-late", "46,44",
            "--class", "0",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
            "--force-phys", "44:10,46:12",
            "--force",
        ],
    )

    assert result.exit_code == 0, result.stdout + "\n" + (result.stderr or "")
    perm_dir = perm_root / "nonmatchings" / function
    content = (perm_dir / "simplify_order_target.yaml").read_text(encoding="utf-8")
    assert "simplify_order_target_late: [46, 44]" in content
    # The front-target key should NOT appear
    # (prefix with newline to avoid false positive on "simplify_order_target_late:")
    assert "\nsimplify_order_target:" not in "\n" + content


def test_setup_want_first_and_want_late_mutually_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passing both --want-first and --want-late is an error."""
    function = "x"
    perm_root = _make_perm_dir(tmp_path, function=function)
    baseline = _make_baseline_dump(tmp_path, function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--want-first", "1,2",
            "--want-late", "3,4",
            "--class", "0",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
            "--force",
        ],
    )

    assert result.exit_code != 0
    output = (result.stdout + (result.stderr or "")).lower()
    assert "mutually exclusive" in output or "both" in output


def test_setup_neither_want_first_nor_want_late_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passing neither --want-first nor --want-late is an error."""
    function = "x"
    perm_root = _make_perm_dir(tmp_path, function=function)
    baseline = _make_baseline_dump(tmp_path, function)
    _stub_wibo_and_compiler(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "setup-simplify-order-scorer",
            "--function", function,
            "--class", "0",
            "--baseline-dump", str(baseline),
            "--perm-root", str(perm_root),
            "--force",
        ],
    )

    assert result.exit_code != 0
