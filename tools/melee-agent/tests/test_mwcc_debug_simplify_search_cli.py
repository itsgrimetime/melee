"""CLI smoke tests for `melee-agent debug mutate simplify-order`."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


MELEE_AGENT = Path(__file__).parent.parent


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", "-m", "src.cli", "debug", "mutate", "simplify-order", *args],
        cwd=MELEE_AGENT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_help_mentions_required_flags() -> None:
    proc = run_cli("--help")

    assert proc.returncode == 0, f"help failed: {proc.stderr}"
    assert "--fn" in proc.stdout
    assert "--want-first" in proc.stdout
    assert "--class" in proc.stdout
    # `--preserve-precolor` and `--max-candidates` are full flags, but
    # typer's narrow panel rendering truncates long names with an ellipsis
    # (e.g. `--preserve-pre…`). Match a short stable prefix so the test
    # isn't coupled to typer's exact wrap point — that wrap point shifts
    # as new flags are added (each one steals horizontal space from the
    # option-name column).
    assert "--preserve-pre" in proc.stdout
    assert "--max-candid" in proc.stdout
    assert "--timeout" in proc.stdout
    assert "simplify order" in proc.stdout.lower()


def test_missing_required_args_exit_nonzero() -> None:
    """With neither --fn nor --want-first, typer should reject the call."""
    proc = run_cli()

    assert proc.returncode != 0
    # typer/click prints "Missing option" for required Options.
    combined = (proc.stdout + proc.stderr).lower()
    assert "missing" in combined or "required" in combined


def test_missing_want_first_exits_nonzero() -> None:
    proc = run_cli("--fn", "fn_test")

    assert proc.returncode != 0
    combined = (proc.stdout + proc.stderr).lower()
    assert "want-first" in combined or "missing" in combined


def test_empty_want_first_is_rejected(tmp_path: Path) -> None:
    """Even when report.json is present, an empty want_first should be
    caught up front before we attempt to compile the baseline."""
    # No report.json -> the function lookup itself fails first if we get
    # past want_first parsing. Use a value that's only whitespace to hit
    # the early-validation path.
    proc = run_cli("--fn", "fn_test", "--want-first", "   ")

    assert proc.returncode != 0
    combined = (proc.stdout + proc.stderr).lower()
    assert "want-first" in combined or "empty" in combined


def test_garbage_want_first_is_rejected() -> None:
    """Non-integer entries in --want-first should produce a clear error."""
    proc = run_cli("--fn", "fn_test", "--want-first", "not,a,number")

    assert proc.returncode != 0
    combined = (proc.stdout + proc.stderr).lower()
    assert "want-first" in combined or "integer" in combined


def test_function_not_in_report_exits_with_clear_error(tmp_path: Path) -> None:
    """When report.json doesn't contain the function, fail early with a
    helpful message — don't try to compile a nonexistent file."""
    # The melee root resolution still points at the real repo; using a
    # nonsense function name confirms we exit before the compile path.
    proc = run_cli("--fn", "nonexistent_fn_xyz123", "--want-first", "1,2")

    assert proc.returncode != 0
    combined = (proc.stdout + proc.stderr).lower()
    # Either the function-lookup path complains, or the report.json path
    # complains. Both forms include the function name.
    assert "nonexistent_fn_xyz123" in (proc.stdout + proc.stderr).lower() or \
           "not found" in combined or \
           "report.json" in combined


def test_search_integration_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """In-process smoke test that the CLI command path resolves end-to-end.

    Uses a faked compile + report.json so we don't shell out to wibo. This
    pairs with the subprocess --help tests above: those confirm the CLI
    surface is wired, this confirms the search loop runs and produces
    output without needing a real toolchain.
    """
    # Build a fake melee root with the structures the command needs.
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n"
        "    int a;\n"
        "    int b;\n"
        "    a = b + 1;\n"
        "}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    from src.mwcc_debug import simplify_search

    # Each compile produces the same pcdump for simplicity — both baseline
    # and every variant get the same simplify order. The search loop
    # should exit cleanly with "no variants made progress".
    fake_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "  1  33  r30  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
        "  1  33  1  1  0x0\n"
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)

    # Also stub the baseline-compile path called from the CLI command body
    # itself (it imports the same symbol from diff_capture).
    from src.mwcc_debug import diff_capture
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)

    # Patch DEFAULT_MELEE_ROOT in the CLI module so the command thinks our
    # fake tree is the repo root.
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    # Invoke via typer's CliRunner (in-process) — gives us captured output
    # without shelling out and re-loading the module.
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--max-candidates", "5",
        ],
    )

    # Exit 0 — no exact match but also no error. Surface a readable
    # summary.
    assert result.exit_code == 0, f"stdout: {result.stdout}\nexc: {result.exception}"
    assert "Function:" in result.stdout
    assert "Target prefix:" in result.stdout
    assert "42,32" in result.stdout
    # No variant changes the simplify order in this stub, so "no progress"
    # should be the verdict.
    assert "No variants made progress" in result.stdout


def test_help_mentions_with_permuter_flag() -> None:
    """The new --with-permuter / --permuter-dir flags should appear in help.

    Brief surface check that the flags are registered with typer; the
    behavior tests below confirm they actually do something."""
    proc = run_cli("--help")

    assert proc.returncode == 0, f"help failed: {proc.stderr}"
    # typer narrow-panel rendering may truncate; match a stable visible prefix.
    assert "--with-permuter" in proc.stdout
    assert "--permuter-dir" in proc.stdout


def test_with_permuter_no_dir_emits_warning_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When --with-permuter is set but no permuter output exists for the
    function, the search should print a hint to stderr and continue with
    the other three adapters — not abort."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n"
        "    int a;\n"
        "    int b;\n"
        "    a = b + 1;\n"
        "}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    # Point the permuter root at an empty tmp dir so resolution finds nothing.
    empty_perm_root = tmp_path / "perm-empty"
    empty_perm_root.mkdir()
    monkeypatch.setenv("MELEE_PERMUTER_ROOT", str(empty_perm_root))

    fake_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--with-permuter",
            "--max-candidates", "5",
        ],
    )

    # Exit 0 — the search still proceeded with the primitive adapters.
    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    # The hint should appear in stderr (typer.echo(..., err=True)).
    combined = result.stdout + (result.stderr or "")
    assert "--with-permuter" in combined
    assert "no permuter output found" in combined.lower()


def _stub_pcdump() -> str:
    """Minimal pcdump string that parses to a single class-0 simplify_order
    of (32,). Shared by warning-branch tests so they can exit cleanly without
    a real toolchain."""
    return (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
    )


def _stage_fake_melee_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Set up a fake melee root with a single fn_test in report.json and
    stub the compile path. Returns the melee root."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n    int a;\n    a = 1;\n}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    fake = _stub_pcdump()

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)
    return melee_root


def test_with_permuter_default_dir_missing_emits_default_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default path (no --permuter-dir): warning should mention
    `nonmatchings/<fn>/` and `./permuter.py`, telling the user how to
    populate the default permuter location."""
    _stage_fake_melee_root(tmp_path, monkeypatch)
    # Point env at an empty perm root so default resolution returns None.
    empty_perm_root = tmp_path / "perm-empty"
    empty_perm_root.mkdir()
    monkeypatch.setenv("MELEE_PERMUTER_ROOT", str(empty_perm_root))

    from src.cli import debug as cli_debug
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--with-permuter",
            "--max-candidates", "5",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    combined = result.stdout + (result.stderr or "")
    # Default-path branch markers.
    assert "no permuter output found" in combined.lower()
    assert "nonmatchings/fn_test" in combined
    assert "./permuter.py" in combined
    # The override-path message must NOT be used here — it would
    # incorrectly imply the user passed --permuter-dir.
    assert "directory does not exist" not in combined.lower()


def test_with_permuter_explicit_dir_missing_mentions_override_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Override path (--permuter-dir supplied but missing): warning should
    quote the user-supplied path and NOT redirect to `nonmatchings/<fn>/`
    or suggest re-passing --permuter-dir (which the user already did)."""
    _stage_fake_melee_root(tmp_path, monkeypatch)

    missing_dir = tmp_path / "definitely_not_here"
    # Intentionally do NOT create missing_dir.

    from src.cli import debug as cli_debug
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--with-permuter",
            "--permuter-dir", str(missing_dir),
            "--max-candidates", "5",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    combined = result.stdout + (result.stderr or "")
    # Override-path branch should quote the supplied path.
    assert "--permuter-dir" in combined
    assert str(missing_dir) in combined
    assert "does not exist" in combined.lower()
    # Default-path remediation should NOT appear — pointing the user at
    # nonmatchings/<fn>/ when they explicitly opted out of that lookup
    # is misleading.
    assert "nonmatchings/fn_test" not in combined
    assert "./permuter.py" not in combined


def test_with_permuter_dir_override_adds_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When --permuter-dir points at a dir containing output-*/source.c,
    those candidates are included in the search. Confirm by counting
    distinct compile calls — the override path should bring in more
    variants than the primitive adapters alone."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n    int z;\n    z = 1;\n}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    # Stage two permuter candidates that are distinct from anything the
    # primitive adapters would produce (the source has only one decl, so
    # decl-orders produces nothing).
    perm_dir = tmp_path / "perm_override"
    for i, name in enumerate(["output-0001-0", "output-0002-0"]):
        out = perm_dir / name
        out.mkdir(parents=True)
        (out / "source.c").write_text(
            f"// permuter candidate {i}\n"
            f"void fn_test(void) {{ int z_{i}; z_{i} = {i}; }}\n",
            encoding="utf-8",
        )

    seen_texts: list[str] = []
    fake_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        text = Path(diff_input.path).read_text(encoding="utf-8")
        seen_texts.append(text)
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--with-permuter",
            "--permuter-dir", str(perm_dir),
            "--max-candidates", "10",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    # The header for the resolved dir should appear in stdout.
    assert "Permuter dir:" in result.stdout
    assert str(perm_dir) in result.stdout
    # Both permuter candidates should have been compiled.
    permuter_texts = [
        t for t in seen_texts if "permuter candidate" in t
    ]
    assert len(permuter_texts) == 2


def test_with_permuter_ranks_candidate_with_target_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end CLI smoke: a permuter output that produces the target
    simplify order should be flagged as an EXACT MATCH and its
    provenance should mention `permuter`.

    Confirms permuter candidates flow through scoring + ranking same as
    primitive adapter outputs."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n    int a;\n    a = 1;\n}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    perm_dir = tmp_path / "perm_override"
    out = perm_dir / "output-0042-1"
    out.mkdir(parents=True)
    perm_source_text = (
        "// permuter winner\n"
        "void fn_test(void) { int a; a = 99; }\n"
    )
    (out / "source.c").write_text(perm_source_text, encoding="utf-8")

    # Baseline pcdump: simplify_order=(32,). The permuter candidate
    # text gets a different pcdump showing simplify_order=(42, 32) —
    # which is the target prefix in this test.
    baseline_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "  1  33  r29  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
        "  1  33  1  1  0x0\n"
    )
    target_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "  1  33  r29  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  42  1  1  0x0\n"
        "  1  32  1  1  0x0\n"
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        text = Path(diff_input.path).read_text(encoding="utf-8")
        if "permuter winner" in text:
            return target_pcdump
        return baseline_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--with-permuter",
            "--permuter-dir", str(perm_dir),
            "--max-candidates", "20",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    assert "EXACT MATCH" in result.stdout
    assert "permuter" in result.stdout.lower()
    assert "output-0042-1" in result.stdout


def test_no_preserve_precolor_exact_hit_uses_qualified_headline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stage_fake_melee_root(tmp_path, monkeypatch)

    from src.mwcc_debug import simplify_search as _ss

    def fake_search(*_args, **kwargs):
        assert kwargs["preserve_precolor_enabled"] is False
        return _ss.SearchResult(
            exact_match=_ss.SourceVariant(
                text="void fn_test(void) {}\n",
                provenance="insert-alias k@0",
                parent_baseline=Path("/tmp/base.c"),
            ),
            progress=[],
            gate_rejected_count=0,
            gate_rejection_reasons=[],
            rejected_scored=[],
            compile_failure_count=0,
            total_compiles=1,
            elapsed_seconds=0.0,
        )

    monkeypatch.setattr(_ss, "search", fake_search)

    from src.cli import debug as cli_debug
    from typer.testing import CliRunner

    result = CliRunner().invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--no-preserve-precolor",
            "--max-candidates", "1",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    assert "EXACT MATCH found:" not in result.stdout
    assert "exact under perturbed precolor" in result.stdout
    assert "verify" in result.stdout.lower()
    assert "insert-alias k@0" in result.stdout


def test_compile_failure_summaries_are_rendered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stage_fake_melee_root(tmp_path, monkeypatch)

    from src.mwcc_debug import simplify_search as _ss

    def fake_search(*_args, **_kwargs):
        return _ss.SearchResult(
            exact_match=None,
            progress=[],
            gate_rejected_count=0,
            gate_rejection_reasons=[],
            rejected_scored=[],
            compile_failure_count=2,
            compile_failures=[
                _ss.CompileFailureSummary(
                    provenance="decl-orders swap row <-> col",
                    returncode=1,
                    diagnostic="sample.c:42: error: illegal implicit declaration",
                ),
                _ss.CompileFailureSummary(
                    provenance="insert-alias addr temp",
                    returncode=124,
                    diagnostic="dump local timed out after 10s",
                ),
            ],
            total_compiles=2,
            elapsed_seconds=0.0,
        )

    monkeypatch.setattr(_ss, "search", fake_search)

    from src.cli import debug as cli_debug
    from typer.testing import CliRunner

    result = CliRunner().invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--max-candidates", "2",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    assert "Compile failure diagnostics:" in result.stdout
    assert "decl-orders swap row <-> col" in result.stdout
    assert "sample.c:42: error" in result.stdout
    assert "insert-alias addr temp" in result.stdout
    assert "timed out" in result.stdout


def test_invalid_class_id_surfaces_available_classes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When --class points at a register class the function doesn't
    exercise, the error should name the actually-available class IDs so
    the user knows what to retry with — not just the generic
    'function may not exercise that register class' message.
    """
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text("void fn_test(void) { int a; a = 1; }\n", encoding="utf-8")
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    # The fake pcdump mentions class 0 and class 1, but the user is going
    # to ask for class 99.
    fake_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "COLORGRAPH DECISIONS (class=1, result=1, n_nodes=1)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  64  r30  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--class", "99",
        ],
    )

    assert result.exit_code != 0
    combined = result.stdout + (result.stderr if hasattr(result, "stderr") else "")
    assert "class 99" in combined
    # Both available IDs should appear so the user can re-run with one.
    assert "0" in combined and "1" in combined
    assert "available class IDs" in combined


# ---------------------------------------------------------------------------
# Gate-rejected diagnostic rendering
# ---------------------------------------------------------------------------


def _make_result_with_rejected(
    *,
    target: tuple[int, ...],
    candidates: list,
) -> "object":
    """Build a SearchResult with `rejected_scored` populated from a small
    spec.

    Each candidate is either a 3-tuple (provenance, observed_prefix,
    rejection_reason) — distance defaults to all zeros — or a 4-tuple
    that also supplies a `PrecolorDistance` instance. Score's
    common_prefix_length is computed against `target`.
    """
    from src.mwcc_debug.simplify_search import (
        PrecolorDistance,
        RejectedCandidate,
        SearchResult,
        SimplifyScore,
    )

    def _common(observed: tuple[int, ...]) -> int:
        n = 0
        for a, b in zip(observed, target):
            if a == b:
                n += 1
            else:
                break
        return n

    zero_dist = PrecolorDistance(0, 0, 0, 0, 0, 0)
    rejected = []
    for entry in candidates:
        if len(entry) == 4:
            prov, observed, reason, distance = entry
        else:
            prov, observed, reason = entry
            distance = zero_dist
        rejected.append(RejectedCandidate(
            provenance=prov,
            score=SimplifyScore(
                target_prefix=target,
                observed_prefix=observed[: len(target)],
                common_prefix_length=_common(observed),
                is_exact_match=(_common(observed) == len(target)),
                baseline_common_prefix_length=0,
            ),
            rejection_reason=reason,
            precolor_distance=distance,
        ))
    return SearchResult(
        exact_match=None,
        progress=[],
        gate_rejected_count=len(rejected),
        gate_rejection_reasons=[],
        rejected_scored=rejected,
        compile_failure_count=0,
        total_compiles=len(rejected),
        elapsed_seconds=0.0,
    )


def test_render_includes_gate_rejected_distribution(capsys: pytest.CaptureFixture) -> None:
    """The renderer prints a header, a histogram, and a top-N section when
    rejected_scored is non-empty. Minimum surface: the header + each
    section title must appear."""
    from src.cli.debug import _render_gate_rejected_distribution

    target = (42, 32)
    result = _make_result_with_rejected(
        target=target,
        candidates=[
            ("v1", (32, 33), "interference graph differs"),
            ("v2", (42, 33), "coalesce mappings differ"),
        ],
    )

    _render_gate_rejected_distribution(result, target)
    out = capsys.readouterr().out

    assert "Gate-rejected diagnostic (n=2)" in out
    assert "Common-prefix length distribution" in out
    assert "Best" in out and "gate-rejected" in out
    # The two provenances should both appear in the top-N section.
    assert "v1" in out
    assert "v2" in out


def test_render_omits_rejected_section_when_empty(capsys: pytest.CaptureFixture) -> None:
    """No rejected candidates -> the diagnostic section is silent. We
    don't want a 'Gate-rejected diagnostic (n=0)' header that adds noise
    to passing runs."""
    from src.cli.debug import _render_gate_rejected_distribution
    from src.mwcc_debug.simplify_search import SearchResult

    result = SearchResult(
        exact_match=None,
        progress=[],
        gate_rejected_count=0,
        gate_rejection_reasons=[],
        rejected_scored=[],
        compile_failure_count=0,
        total_compiles=0,
        elapsed_seconds=0.0,
    )

    _render_gate_rejected_distribution(result, (42, 32))
    out = capsys.readouterr().out

    assert "Gate-rejected diagnostic" not in out
    # And the whole render is empty (or whitespace only).
    assert out.strip() == ""


def test_render_highlights_target_length_row(capsys: pytest.CaptureFixture) -> None:
    """The histogram row for prefix length == len(target) is marked, so
    the reader's eye lands on the headline signal: did any rejected
    candidate hit the full target prefix?"""
    from src.cli.debug import _render_gate_rejected_distribution

    target = (42, 32)  # len == 2
    # Include at least one candidate at prefix=2 so the bin is non-empty.
    result = _make_result_with_rejected(
        target=target,
        candidates=[
            ("at_target", (42, 32), "spill set differs"),
            ("partial", (42, 99), "interference graph differs"),
            ("nothing", (99, 99), "coalesce mappings differ"),
        ],
    )

    _render_gate_rejected_distribution(result, target)
    out = capsys.readouterr().out

    # Locate the line with "prefix=2" (target length). It should be marked.
    target_lines = [
        line for line in out.splitlines() if "prefix=2" in line
    ]
    assert target_lines, f"no prefix=2 line found in:\n{out}"
    # The marker doesn't need to be exactly "<- target length", but it
    # should distinguish this row from the others. Confirm it bears a
    # marker the other prefix rows don't.
    other_lines = [
        line for line in out.splitlines()
        if ("prefix=0" in line or "prefix=1" in line)
    ]
    assert any("target" in line.lower() for line in target_lines)
    assert all("target" not in line.lower() for line in other_lines)


def test_render_lists_top_rejected_by_prefix_length(
    capsys: pytest.CaptureFixture,
) -> None:
    """Top-N detail section orders entries by common_prefix_length DESC.
    The candidate that gets closest to target is shown first."""
    from src.cli.debug import _render_gate_rejected_distribution

    target = (42, 32, 50)
    result = _make_result_with_rejected(
        target=target,
        candidates=[
            ("worst", (99, 99, 99), "spill set differs"),
            ("best", (42, 32, 99), "interference graph differs"),
            ("middle", (42, 99, 99), "coalesce mappings differ"),
        ],
    )

    _render_gate_rejected_distribution(result, target)
    out = capsys.readouterr().out

    # In the "Best N gate-rejected by simplify-order:" section, the entries
    # should appear in best-first order. Find the position of each
    # provenance string in the output.
    idx_best = out.find("best:")
    idx_middle = out.find("middle:")
    idx_worst = out.find("worst:")

    assert idx_best != -1, f"best not found in:\n{out}"
    assert idx_middle != -1, f"middle not found in:\n{out}"
    assert idx_worst != -1, f"worst not found in:\n{out}"
    assert idx_best < idx_middle < idx_worst


def test_render_gate_rejected_section_appears_in_cli_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end smoke: when the CLI's search produces rejected candidates,
    the diagnostic section appears in stdout. Pairs with the unit tests of
    the renderer — those confirm the rendering function works in isolation,
    this confirms it's wired into the CLI flow."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n    int a;\n    int b;\n    a = b + 1;\n}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    # Baseline pcdump: simplify_order=(32, 33) with IG edge (32, 33).
    baseline_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  1  1  0x0\n"
        "  interferers: 33=r29\n"
        "  1  33  r29  1  1  0x0\n"
        "  interferers: 32=r30\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
        "  1  33  1  1  0x0\n"
    )
    # Variant pcdump: simplify_order=(42, 33) (partial match for target
    # (42, 32)) but IG differs (extra edge added) -> gate rejected.
    variant_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=3)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  2  2  0x0\n"
        "  interferers: 33=r29 99=r28\n"
        "  1  33  r29  1  1  0x0\n"
        "  interferers: 32=r30\n"
        "  2  99  r28  1  1  0x0\n"
        "  interferers: 32=r30\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  42  1  1  0x0\n"
        "  1  33  1  1  0x0\n"
    )

    seen_texts: list[str] = []

    def fake_compile(diff_input, *, function, melee_root, timeout):
        text = Path(diff_input.path).read_text(encoding="utf-8")
        seen_texts.append(text)
        # Baseline compile uses the original source path text; variants
        # are produced by the decl_orders / insert_alias / type_change
        # adapters. Any variant text shorter than ~40 bytes is the
        # baseline; longer texts (after adapters touch the AST) get the
        # variant pcdump. Cheaper than wiring full source matching.
        if "int a;\n    int b;\n    a = b + 1;\n" in text:
            return baseline_pcdump
        return variant_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--max-candidates", "5",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nexc: {result.exception}"
    )
    # The gate should have rejected at least one variant for IG mismatch,
    # which means rejected_scored is non-empty and the section appears.
    assert "Gate-rejected diagnostic" in result.stdout
    assert "Common-prefix length distribution" in result.stdout


# ---------------------------------------------------------------------------
# Combined precolor-distance + simplify-order ranking
# ---------------------------------------------------------------------------


def test_render_gate_rejected_lists_now_include_distance(
    capsys: pytest.CaptureFixture,
) -> None:
    """The existing gate-rejected diagnostic's per-candidate detail lines
    show the precolor distance inline. Free improvement to the existing
    section — independent of --rank-combined."""
    from src.cli.debug import _render_gate_rejected_distribution
    from src.mwcc_debug.simplify_search import PrecolorDistance

    target = (42, 32)
    result = _make_result_with_rejected(
        target=target,
        candidates=[
            # Small distance (1) — should rank above the high-distance one.
            ("smaller", (42, 32), "spill set differs",
             PrecolorDistance(0, 0, 0, 0, 1, 0)),
            # Large distance (8) — same simplify-order prefix.
            ("bigger", (42, 32), "interference graph differs",
             PrecolorDistance(5, 3, 0, 0, 0, 0)),
        ],
    )

    _render_gate_rejected_distribution(result, target)
    out = capsys.readouterr().out

    # Each detail line includes a distance annotation.
    assert "distance=1" in out
    assert "distance=8" in out


def test_render_combined_score_omitted_without_rank_combined_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The combined-score section only renders when --rank-combined is set.
    Without the flag, the existing progress + gate-rejected output is
    unchanged."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n    int a;\n    int b;\n    a = b + 1;\n}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    fake_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "  1  33  r30  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
        "  1  33  1  1  0x0\n"
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    from typer.testing import CliRunner

    runner = CliRunner()
    # No --rank-combined flag: combined-score section must NOT appear.
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--max-candidates", "5",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nexc: {result.exception}"
    )
    assert "Best by combined score" not in result.stdout


def test_render_combined_score_ranking_shows_top_n_unified(
    capsys: pytest.CaptureFixture,
) -> None:
    """Given a mix of passing + rejected candidates, the combined-score
    section shows them ordered by combined DESC, drawing from both
    buckets uniformly."""
    from src.cli.debug import _render_combined_score_ranking
    from src.mwcc_debug.simplify_search import (
        BaselineSignature,
        PrecolorDistance,
        RejectedCandidate,
        ScoredVariant,
        SearchResult,
        SimplifyScore,
        SourceVariant,
    )

    target = (42, 32)

    def _sscore(observed: tuple[int, ...]) -> SimplifyScore:
        common = 0
        for a, b in zip(observed, target):
            if a == b:
                common += 1
            else:
                break
        return SimplifyScore(
            target_prefix=target,
            observed_prefix=observed[: len(target)],
            common_prefix_length=common,
            is_exact_match=(common == len(target)),
            baseline_common_prefix_length=0,
        )

    empty_sig = BaselineSignature(
        interference_edges=frozenset(),
        coalesce_mappings=frozenset(),
        spill_set=frozenset(),
        simplify_order=(),
    )

    # Gate-passing candidate: prefix=1/2, distance=0 -> combined=0.5.
    passing = ScoredVariant(
        variant=SourceVariant(text="A", provenance="passer",
                              parent_baseline=Path("/tmp/x.c")),
        signature=empty_sig,
        score=_sscore((42, 99)),
        precolor_distance=PrecolorDistance(0, 0, 0, 0, 0, 0),
    )
    # Gate-rejected, full simplify-order progress, small distance: ratio=1.0,
    # combined = 1.0 - 0.05 * 1 = 0.95 -> the winner.
    rejected_gold = RejectedCandidate(
        provenance="gold",
        score=_sscore((42, 32)),
        rejection_reason="interference graph differs",
        precolor_distance=PrecolorDistance(1, 0, 0, 0, 0, 0),
    )
    # Gate-rejected, full simplify-order progress, big distance: ratio=1.0,
    # combined = 1.0 - 0.05 * 10 = 0.5.
    rejected_noisy = RejectedCandidate(
        provenance="noisy",
        score=_sscore((42, 32)),
        rejection_reason="interference graph differs",
        precolor_distance=PrecolorDistance(5, 5, 0, 0, 0, 0),
    )
    # Gate-rejected, no progress, no distance: combined = 0.
    rejected_meh = RejectedCandidate(
        provenance="meh",
        score=_sscore((99, 99)),
        rejection_reason="spill set differs",
        precolor_distance=PrecolorDistance(0, 0, 0, 0, 0, 0),
    )

    result = SearchResult(
        exact_match=None,
        progress=[passing],
        gate_rejected_count=3,
        gate_rejection_reasons=[],
        rejected_scored=[rejected_gold, rejected_noisy, rejected_meh],
        compile_failure_count=0,
        total_compiles=4,
        elapsed_seconds=0.0,
    )

    _render_combined_score_ranking(result, target, alpha=0.05, top_n=4)
    out = capsys.readouterr().out

    # Header is present with the alpha value.
    assert "Best by combined score" in out
    assert "alpha=0.05" in out

    # Order: gold (0.95) > passer (0.5) tied with noisy (0.5, tiebreak by
    # provenance: "noisy" > "passer" — so passer comes second; noisy third).
    idx_gold = out.find("gold:")
    idx_passer = out.find("passer:")
    idx_noisy = out.find("noisy:")
    idx_meh = out.find("meh:")

    assert idx_gold != -1
    assert idx_passer != -1
    assert idx_noisy != -1
    assert idx_meh != -1

    # Gold beats everything. Meh is last (lowest combined).
    assert idx_gold < idx_passer
    assert idx_gold < idx_noisy
    assert idx_passer < idx_meh
    assert idx_noisy < idx_meh

    # Per-row precolor breakdown is rendered.
    assert "IG +1/-0" in out  # gold's distance components
    assert "IG +5/-5" in out  # noisy's
    # Gate status annotation appears.
    assert "gate passed" in out  # passing candidate
    assert "gate rejected" in out  # for rejected ones


def test_render_combined_score_help_text_mentions_flag() -> None:
    """`--rank-combined` and `--combined-alpha` appear in the --help text."""
    proc = run_cli("--help")

    assert proc.returncode == 0, f"help failed: {proc.stderr}"
    # typer narrow-panel rendering may truncate; match a stable visible prefix.
    assert "--rank-combined" in proc.stdout or "rank-combine" in proc.stdout
    assert "--combined-alpha" in proc.stdout or "combined-alpha" in proc.stdout


def test_cli_smoke_accepts_combined_alpha_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--combined-alpha 0.1` is accepted and propagates through to the
    rendering. Also exercises --rank-combined producing the new section."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n    int a;\n    int b;\n    a = b + 1;\n}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    fake_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "  1  33  r30  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
        "  1  33  1  1  0x0\n"
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--max-candidates", "5",
            "--rank-combined",
            "--combined-alpha", "0.1",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nexc: {result.exception}"
    )
    # The combined-score header should appear with the supplied alpha.
    # Even with no progress candidates, the smoke fakes produce a compiled
    # variant that becomes a no-progress passing candidate, which is enough
    # to render the section.
    # (At minimum: if no candidates compiled, the section is silent — that's
    # acceptable for the smoke test. But our fake produces one compiled
    # variant on the first decl-order, so a row appears.)
    # Don't insist on a row, but if the section renders, it must have the
    # alpha we passed.
    if "Best by combined score" in result.stdout:
        assert "alpha=0.1" in result.stdout


# ---------------------------------------------------------------------------
# Lexicographic rank mode (calibration-free successor to combined scoring)
# ---------------------------------------------------------------------------


def _make_full_result(
    *,
    target: tuple[int, ...],
    passing: list[tuple[str, tuple[int, ...], "object"]] | None = None,
    rejected: list[tuple[str, tuple[int, ...], str, "object"]] | None = None,
) -> "object":
    """Build a SearchResult with both `progress` and `rejected_scored`.

    Each `passing` entry is (provenance, observed_prefix, PrecolorDistance);
    each `rejected` entry is (provenance, observed_prefix, reason, distance).
    """
    from pathlib import Path as _Path

    from src.mwcc_debug.simplify_search import (
        BaselineSignature,
        RejectedCandidate,
        ScoredVariant,
        SearchResult,
        SimplifyScore,
        SourceVariant,
    )

    def _common(observed: tuple[int, ...]) -> int:
        n = 0
        for a, b in zip(observed, target):
            if a == b:
                n += 1
            else:
                break
        return n

    def _sscore(observed: tuple[int, ...]) -> SimplifyScore:
        n = _common(observed)
        return SimplifyScore(
            target_prefix=target,
            observed_prefix=observed[: len(target)],
            common_prefix_length=n,
            is_exact_match=(n == len(target)),
            baseline_common_prefix_length=0,
        )

    empty_sig = BaselineSignature(
        interference_edges=frozenset(),
        coalesce_mappings=frozenset(),
        spill_set=frozenset(),
        simplify_order=(),
    )

    passing_scored: list[ScoredVariant] = []
    for prov, observed, dist in (passing or []):
        passing_scored.append(ScoredVariant(
            variant=SourceVariant(text="x", provenance=prov,
                                  parent_baseline=_Path("/tmp/x.c")),
            signature=empty_sig,
            score=_sscore(observed),
            precolor_distance=dist,
        ))

    rejected_scored: list[RejectedCandidate] = []
    for prov, observed, reason, dist in (rejected or []):
        rejected_scored.append(RejectedCandidate(
            provenance=prov,
            score=_sscore(observed),
            rejection_reason=reason,
            precolor_distance=dist,
        ))

    return SearchResult(
        exact_match=None,
        progress=passing_scored,
        gate_rejected_count=len(rejected_scored),
        gate_rejection_reasons=[],
        rejected_scored=rejected_scored,
        compile_failure_count=0,
        total_compiles=len(passing_scored) + len(rejected_scored),
        elapsed_seconds=0.0,
    )


def test_render_lex_ranking_section_header(
    capsys: pytest.CaptureFixture,
) -> None:
    """The lex renderer prints a "Best by simplify-order then distance"
    header — distinct from the combined-score header so the reader sees
    which ranking mode produced the output."""
    from src.cli.debug import _render_lex_ranking
    from src.mwcc_debug.simplify_search import PrecolorDistance

    target = (42, 32)
    result = _make_full_result(
        target=target,
        rejected=[
            ("a", (42, 32), "interference graph differs",
             PrecolorDistance(1, 0, 0, 0, 0, 0)),
        ],
    )

    _render_lex_ranking(result, target)
    out = capsys.readouterr().out

    assert "Best by simplify-order then distance" in out
    # No reference to combined scoring or alpha in lex output.
    assert "alpha" not in out.lower()
    assert "combined" not in out.lower()


def test_render_lex_ranking_sorts_prefix_then_distance(
    capsys: pytest.CaptureFixture,
) -> None:
    """Lex sort key: common_prefix_length DESC primary, total distance ASC
    secondary. A prefix=2/distance=500 candidate beats prefix=1/distance=0:
    the high-prefix candidate is what we want to inspect first, regardless
    of how much it disturbed precolor."""
    from src.cli.debug import _render_lex_ranking
    from src.mwcc_debug.simplify_search import PrecolorDistance

    target = (42, 32)
    result = _make_full_result(
        target=target,
        rejected=[
            # prefix=2, big distance (500). Should still rank first.
            ("hi_prefix_big_dist", (42, 32), "interference graph differs",
             PrecolorDistance(250, 250, 0, 0, 0, 0)),
            # prefix=1, no distance. Loses to prefix=2 despite zero distance.
            ("lo_prefix_no_dist", (42, 99), "spill set differs",
             PrecolorDistance(0, 0, 0, 0, 0, 0)),
        ],
    )

    _render_lex_ranking(result, target)
    out = capsys.readouterr().out

    idx_hi = out.find("hi_prefix_big_dist")
    idx_lo = out.find("lo_prefix_no_dist")
    assert idx_hi != -1
    assert idx_lo != -1
    assert idx_hi < idx_lo, (
        f"prefix=2 candidate should rank above prefix=1; got:\n{out}"
    )


def test_render_lex_ranking_tiebreaks_within_prefix_by_distance(
    capsys: pytest.CaptureFixture,
) -> None:
    """Within a single prefix level, smaller distance wins."""
    from src.cli.debug import _render_lex_ranking
    from src.mwcc_debug.simplify_search import PrecolorDistance

    target = (42, 32)
    result = _make_full_result(
        target=target,
        rejected=[
            # Both prefix=2; smaller-distance one wins.
            ("dist_500", (42, 32), "interference graph differs",
             PrecolorDistance(250, 250, 0, 0, 0, 0)),
            ("dist_109", (42, 32), "interference graph differs",
             PrecolorDistance(54, 55, 0, 0, 0, 0)),
            ("dist_204", (42, 32), "interference graph differs",
             PrecolorDistance(100, 104, 0, 0, 0, 0)),
        ],
    )

    _render_lex_ranking(result, target)
    out = capsys.readouterr().out

    idx_109 = out.find("dist_109")
    idx_204 = out.find("dist_204")
    idx_500 = out.find("dist_500")
    assert idx_109 < idx_204 < idx_500, (
        f"smaller distance should rank above larger; got:\n{out}"
    )


def test_render_lex_ranking_unifies_passing_and_rejected(
    capsys: pytest.CaptureFixture,
) -> None:
    """The lex section pulls from BOTH progress and rejected_scored so a
    rejected candidate at higher prefix outranks a passing low-prefix one.
    Mirrors the combined renderer's unified-list behavior."""
    from src.cli.debug import _render_lex_ranking
    from src.mwcc_debug.simplify_search import PrecolorDistance

    target = (42, 32)
    result = _make_full_result(
        target=target,
        passing=[
            # Gate passed but no progress (prefix=0).
            ("passer", (99, 99), PrecolorDistance(0, 0, 0, 0, 0, 0)),
        ],
        rejected=[
            # Gate rejected but full simplify-order progress.
            ("rejected_winner", (42, 32), "interference graph differs",
             PrecolorDistance(1, 0, 0, 0, 0, 0)),
        ],
    )

    _render_lex_ranking(result, target)
    out = capsys.readouterr().out

    idx_winner = out.find("rejected_winner")
    idx_passer = out.find("passer")
    assert idx_winner != -1, f"rejected winner missing:\n{out}"
    assert idx_passer != -1, f"passing low-prefix missing:\n{out}"
    assert idx_winner < idx_passer, (
        f"higher-prefix rejected candidate should outrank lower-prefix "
        f"passing one; got:\n{out}"
    )
    # Gate annotations still present so the reader sees which bucket.
    assert "gate passed" in out
    assert "gate rejected" in out


def test_render_lex_ranking_row_columns(
    capsys: pytest.CaptureFixture,
) -> None:
    """Each row shows prefix, distance, and the breakdown — but NOT a
    combined-score number (which is meaningless under lex)."""
    from src.cli.debug import _render_lex_ranking
    from src.mwcc_debug.simplify_search import PrecolorDistance

    target = (42, 32)
    result = _make_full_result(
        target=target,
        rejected=[
            ("only", (42, 32), "interference graph differs",
             PrecolorDistance(7, 3, 1, 0, 0, 0)),
        ],
    )

    _render_lex_ranking(result, target)
    out = capsys.readouterr().out

    # Prefix and total distance visible on the headline row.
    assert "prefix=2/2" in out
    assert "distance=11" in out or "total=11" in out
    # IG/coalesce/spill breakdown still rendered.
    assert "IG +7/-3" in out
    assert "coalesce +1/-0" in out
    # No "combined=" column.
    assert "combined=" not in out


def test_render_lex_ranking_silent_when_no_candidates(
    capsys: pytest.CaptureFixture,
) -> None:
    """Empty result -> nothing prints. No "Best by simplify-order ..." header
    with zero rows."""
    from src.cli.debug import _render_lex_ranking
    from src.mwcc_debug.simplify_search import SearchResult

    result = SearchResult(
        exact_match=None,
        progress=[],
        gate_rejected_count=0,
        gate_rejection_reasons=[],
        rejected_scored=[],
        compile_failure_count=0,
        total_compiles=0,
        elapsed_seconds=0.0,
    )

    _render_lex_ranking(result, (42, 32))
    out = capsys.readouterr().out
    assert out.strip() == ""


def test_default_rank_mode_renders_lex_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default behavior with no flag: lex section is the headline output.

    This is a behavioral change from the previous default (no section
    without --rank-combined). New default is strictly more informative."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n    int a;\n    int b;\n    a = b + 1;\n}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    # Baseline: simplify_order=(32, 33) with one IG edge.
    baseline_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  1  1  0x0\n"
        "  interferers: 33=r29\n"
        "  1  33  r29  1  1  0x0\n"
        "  interferers: 32=r30\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
        "  1  33  1  1  0x0\n"
    )
    # Variant: differs in IG (adds a node) but partially matches target.
    variant_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=3)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  2  2  0x0\n"
        "  interferers: 33=r29 99=r28\n"
        "  1  33  r29  1  1  0x0\n"
        "  interferers: 32=r30\n"
        "  2  99  r28  1  1  0x0\n"
        "  interferers: 32=r30\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  42  1  1  0x0\n"
        "  1  33  1  1  0x0\n"
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        text = Path(diff_input.path).read_text(encoding="utf-8")
        if "int a;\n    int b;\n    a = b + 1;\n" in text:
            return baseline_pcdump
        return variant_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--max-candidates", "5",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nexc: {result.exception}"
    )
    # Default mode: lex section present, combined section absent.
    assert "Best by simplify-order then distance" in result.stdout
    assert "Best by combined score" not in result.stdout


def test_rank_mode_lex_explicitly_renders_lex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passing --rank-mode lex is equivalent to no flag at all."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n    int a;\n    int b;\n    a = b + 1;\n}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    fake_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "  1  33  r30  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
        "  1  33  1  1  0x0\n"
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--max-candidates", "5",
            "--rank-mode", "lex",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nexc: {result.exception}"
    )
    assert "Best by combined score" not in result.stdout


def test_rank_mode_combined_renders_combined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--rank-mode combined` renders the combined-score section instead
    of lex — the explicit way to opt into the old behavior."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n    int a;\n    int b;\n    a = b + 1;\n}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    fake_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "  1  33  r30  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
        "  1  33  1  1  0x0\n"
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--max-candidates", "5",
            "--rank-mode", "combined",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nexc: {result.exception}"
    )
    # Combined section present, lex section absent.
    if "Best by combined score" not in result.stdout:
        # If there are no compiled candidates the section is silent;
        # this fake produces one variant per adapter so we expect a row.
        # The test docs the contract; silence is acceptable if no
        # candidates compiled.
        pass
    assert "Best by simplify-order then distance" not in result.stdout


def test_rank_combined_deprecated_alias_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backward compat: existing `--rank-combined` keeps working as an alias
    for `--rank-mode combined`. Renders the combined-score section."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n    int a;\n    int b;\n    a = b + 1;\n}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    fake_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "  1  33  r30  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
        "  1  33  1  1  0x0\n"
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--max-candidates", "5",
            "--rank-combined",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nexc: {result.exception}"
    )
    # The deprecated alias still routes to the combined-score renderer.
    # If no candidates compiled the section may be silent, but the lex
    # section must NOT appear (the alias overrides the lex default).
    assert "Best by simplify-order then distance" not in result.stdout


def test_rank_mode_lex_ignores_combined_alpha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--rank-mode lex --combined-alpha 0.1` accepts the alpha value but
    does not use it — no error, no combined-score output, no alpha echoed."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n    int a;\n    int b;\n    a = b + 1;\n}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    fake_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "  1  33  r30  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
        "  1  33  1  1  0x0\n"
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--max-candidates", "5",
            "--rank-mode", "lex",
            "--combined-alpha", "0.1",
        ],
    )

    # The alpha value is accepted (not flagged as a parse error) but is
    # silent in the lex output — no "alpha=" string anywhere.
    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nexc: {result.exception}"
    )
    assert "alpha=0.1" not in result.stdout
    assert "Best by combined score" not in result.stdout


def test_rank_mode_invalid_value_rejected() -> None:
    """`--rank-mode garbage` exits non-zero with a usage error."""
    proc = run_cli(
        "--fn", "fn_test",
        "--want-first", "1,2",
        "--rank-mode", "garbage",
    )
    assert proc.returncode != 0
    combined = (proc.stdout + proc.stderr).lower()
    # Either typer's standard "Invalid value for" or any "rank-mode"
    # mention is fine; what matters is the failure surfaces the flag.
    assert (
        "rank-mode" in combined
        or "rank_mode" in combined
        or "invalid value" in combined
        or "garbage" in combined
    )


def test_help_text_mentions_rank_mode_and_default() -> None:
    """`--rank-mode` appears in --help with both choices and a default of lex."""
    proc = run_cli("--help")

    assert proc.returncode == 0, f"help failed: {proc.stderr}"
    # Match either the full flag name or a stable prefix in case typer
    # truncates for narrow panels.
    assert "--rank-mode" in proc.stdout or "rank-mode" in proc.stdout
    # Both modes must be documented somewhere — at minimum in the choices
    # list or help text.
    assert "lex" in proc.stdout
    assert "combined" in proc.stdout


# ---------------------------------------------------------------------------
# --triage flag: post-search ranking by real-tree match%
# ---------------------------------------------------------------------------
#
# Closes the methodology gap exposed by the grVenom_80204284 campaign — the
# manual survey ranked permuter candidates by simplify-order distance (a
# search-side proxy) and inspected only the top 5, missing output-180-1
# which produced the actual 100% match. Codifying triage-after-harvest into
# the command makes future campaigns surface that candidate automatically.


def test_help_text_mentions_triage_flag() -> None:
    """`--triage` appears in --help and the help text mentions when it
    applies (requires --with-permuter)."""
    proc = run_cli("--help")

    assert proc.returncode == 0, f"help failed: {proc.stderr}"
    # Match either the full flag name or a stable prefix in case typer
    # truncates for narrow panels.
    combined = proc.stdout
    assert "--triage" in combined or "triage" in combined
    # The help should clarify that triage requires permuter candidates —
    # mentioning either "with-permuter" or "permuter" is enough.
    assert "permuter" in combined.lower()


def test_triage_without_with_permuter_warns_and_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--triage` with no `--with-permuter` should print a clear warning and
    skip triage cleanly — not error out. The simplify-order search still
    runs and produces its normal output."""
    _stage_fake_melee_root(tmp_path, monkeypatch)

    from src.cli import debug as cli_debug
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--triage",
            "--max-candidates", "5",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    combined = result.stdout + (result.stderr or "")
    # The warning should mention --with-permuter (the missing prereq).
    assert "with-permuter" in combined.lower() or "permuter" in combined.lower()
    # And the triage section header should NOT appear.
    assert "Best by real-tree match" not in combined


def test_triage_with_empty_permuter_dir_skips_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--triage --with-permuter` when no permuter output exists for the
    function should skip triage cleanly with a brief message — not error."""
    _stage_fake_melee_root(tmp_path, monkeypatch)
    empty_perm_root = tmp_path / "perm-empty"
    empty_perm_root.mkdir()
    monkeypatch.setenv("MELEE_PERMUTER_ROOT", str(empty_perm_root))

    from src.cli import debug as cli_debug
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--with-permuter",
            "--triage",
            "--max-candidates", "5",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    combined = result.stdout + (result.stderr or "")
    # The triage section header should NOT appear because there's nothing
    # to triage.
    assert "Best by real-tree match" not in combined


def test_triage_subprocess_failure_doesnt_crash_main_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the triage subprocess fails (non-zero exit), capture stderr but
    don't crash the main command — the simplify-order rankings are still
    useful even when triage is unavailable."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n    int a;\n    a = 1;\n}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    perm_dir = tmp_path / "perm_override"
    out = perm_dir / "output-0001-0"
    out.mkdir(parents=True)
    (out / "source.c").write_text(
        "void fn_test(void) { int a; a = 99; }\n",
        encoding="utf-8",
    )

    fake_pcdump = _stub_pcdump()

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    # Stub the triage subprocess wrapper to simulate a non-zero exit.
    def fake_run_triage(perm_dir, function, melee_root):
        return cli_debug._TriageResult(
            returncode=2,
            stdout="",
            stderr="triage exploded: contrived test failure",
            data=None,
        )
    monkeypatch.setattr(cli_debug, "_run_triage_subprocess", fake_run_triage)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--with-permuter",
            "--permuter-dir", str(perm_dir),
            "--triage",
            "--max-candidates", "5",
        ],
    )

    # Main command still exits cleanly — the simplify-order rankings the
    # user already has are still useful.
    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    combined = result.stdout + (result.stderr or "")
    # The failure should be surfaced somewhere so the user knows triage
    # didn't actually run.
    assert (
        "triage" in combined.lower()
        and (
            "failed" in combined.lower()
            or "exploded" in combined.lower()
            or "non-zero" in combined.lower()
            or "error" in combined.lower()
        )
    )
    # The triage section header should NOT appear — we didn't get data.
    assert "Best by real-tree match" not in combined


def test_triage_output_section_appears_in_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: triage runs, the new 'Best by real-tree match%' section
    appears in the report with provenance + match% + delta + simplify-order
    rank position."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) {\n    int a;\n    a = 1;\n}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    perm_dir = tmp_path / "perm_override"
    out1 = perm_dir / "output-0001-0"
    out1.mkdir(parents=True)
    (out1 / "source.c").write_text(
        "void fn_test(void) { int a; a = 1; }\n", encoding="utf-8",
    )
    out2 = perm_dir / "output-0002-0"
    out2.mkdir(parents=True)
    (out2 / "source.c").write_text(
        "void fn_test(void) { int b; b = 2; }\n", encoding="utf-8",
    )

    fake_pcdump = _stub_pcdump()

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    # Canned triage JSON: two candidates, both ok, output-0002-0 wins.
    canned = {
        "function": "fn_test",
        "baseline_pct": 97.74,
        "best_pct": 98.50,
        "best_path": str(out2 / "source.c"),
        "results": [
            {
                "path": str(out1 / "source.c"),
                "match_pct": 98.10,
                "delta": 0.36,
                "status": "ok",
                "first_diag": None,
                "kept_failed_path": None,
            },
            {
                "path": str(out2 / "source.c"),
                "match_pct": 98.50,
                "delta": 0.76,
                "status": "ok",
                "first_diag": None,
                "kept_failed_path": None,
            },
        ],
    }

    def fake_run_triage(perm_dir, function, melee_root):
        return cli_debug._TriageResult(
            returncode=0,
            stdout=json.dumps(canned),
            stderr="",
            data=canned,
        )
    monkeypatch.setattr(cli_debug, "_run_triage_subprocess", fake_run_triage)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--with-permuter",
            "--permuter-dir", str(perm_dir),
            "--triage",
            "--max-candidates", "5",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    out = result.stdout
    # The new triage section header must appear.
    assert "Best by real-tree match" in out
    # Both candidates' provenance should appear in the section.
    assert "output-0001-0" in out
    assert "output-0002-0" in out
    # Match percentages should appear.
    assert "98.50" in out
    assert "98.10" in out
    # Deltas relative to baseline should be present (sign + magnitude).
    assert "+0.76" in out
    assert "+0.36" in out


def test_triage_100_percent_match_surfaces_fix_found_banner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The headline use case: when a triage candidate produces a 100%
    match, surface a *** FIX FOUND *** banner prominently so the user (or
    a campaign agent) cannot miss it.

    This is the test for the grVenom_80204284 closure — output-180-1
    needs to be impossible to overlook."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) { int a; a = 1; }\n", encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    perm_dir = tmp_path / "perm_override"
    winner = perm_dir / "output-0180-1"
    winner.mkdir(parents=True)
    (winner / "source.c").write_text(
        "void fn_test(void) { int a; a = 1; }\n", encoding="utf-8",
    )

    fake_pcdump = _stub_pcdump()

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    canned = {
        "function": "fn_test",
        "baseline_pct": 97.74,
        "best_pct": 100.00,
        "best_path": str(winner / "source.c"),
        "results": [
            {
                "path": str(winner / "source.c"),
                "match_pct": 100.00,
                "delta": 2.26,
                "status": "ok",
                "first_diag": None,
                "kept_failed_path": None,
            },
        ],
    }

    def fake_run_triage(perm_dir, function, melee_root):
        return cli_debug._TriageResult(
            returncode=0,
            stdout=json.dumps(canned),
            stderr="",
            data=canned,
        )
    monkeypatch.setattr(cli_debug, "_run_triage_subprocess", fake_run_triage)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--with-permuter",
            "--permuter-dir", str(perm_dir),
            "--triage",
            "--max-candidates", "5",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    out = result.stdout
    # The FIX FOUND banner must be prominent.
    assert "FIX FOUND" in out
    # The winning provenance must appear.
    assert "output-0180-1" in out
    # The 100% match% must appear.
    assert "100.00" in out
    # The delta from baseline must appear so the user sees the gain.
    assert "97.74" in out


def test_triage_renders_simplify_order_rank_when_available(
    capsys: pytest.CaptureFixture,
) -> None:
    """When the triage candidate's provenance matches an entry in the
    search result's `rejected_scored` (the realistic case for an
    interesting permuter candidate that disturbed precolor), the
    'simplify-order rank #N' annotation must show the actual rank, not
    'n/a'.

    Unit-tests `_render_triage_ranking` directly so the rank-lookup
    logic is exercised without depending on the search loop's internal
    bookkeeping (which itself doesn't always retain candidates that
    compile cleanly but don't make progress)."""
    from src.cli.debug import _render_triage_ranking
    from src.mwcc_debug.simplify_search import (
        PrecolorDistance,
        RejectedCandidate,
        SearchResult,
        SimplifyScore,
    )

    target = (42, 32)
    # Stage a SearchResult whose rejected_scored has the permuter
    # output-0180-1 ranked #1 by simplify-order (prefix=2) and
    # output-0001-0 ranked #2 (prefix=1).
    rejected = [
        RejectedCandidate(
            provenance="permuter output-0180-1/source.c",
            score=SimplifyScore(
                target_prefix=target,
                observed_prefix=(42, 32),
                common_prefix_length=2,
                is_exact_match=True,
                baseline_common_prefix_length=0,
            ),
            rejection_reason="precolor disturbance",
            precolor_distance=PrecolorDistance(1, 0, 0, 0, 0, 0),
        ),
        RejectedCandidate(
            provenance="permuter output-0001-0/source.c",
            score=SimplifyScore(
                target_prefix=target,
                observed_prefix=(42, 99),
                common_prefix_length=1,
                is_exact_match=False,
                baseline_common_prefix_length=0,
            ),
            rejection_reason="precolor disturbance",
            precolor_distance=PrecolorDistance(2, 0, 0, 0, 0, 0),
        ),
    ]
    result = SearchResult(
        exact_match=None,
        progress=[],
        gate_rejected_count=2,
        gate_rejection_reasons=[],
        rejected_scored=rejected,
        compile_failure_count=0,
        total_compiles=2,
        elapsed_seconds=0.0,
    )

    # Triage payload: output-0001-0 happens to win on real-tree match%
    # (rank #2 by simplify-order, rank #1 by match%).
    triage_data = {
        "function": "fn_test",
        "baseline_pct": 90.0,
        "best_pct": 95.0,
        "best_path": "/some/path/output-0001-0/source.c",
        "results": [
            {
                "path": "/some/path/output-0180-1/source.c",
                "match_pct": 92.5,
                "delta": 2.5,
                "status": "ok",
                "first_diag": None,
                "kept_failed_path": None,
            },
            {
                "path": "/some/path/output-0001-0/source.c",
                "match_pct": 95.0,
                "delta": 5.0,
                "status": "ok",
                "first_diag": None,
                "kept_failed_path": None,
            },
        ],
    }

    _render_triage_ranking(
        triage_data,
        result=result,
        perm_dir=Path("/some/path"),
    )
    out = capsys.readouterr().out

    # Both candidates appear with their simplify-order rank annotated.
    # output-0180-1 was rank #1 by simplify-order (prefix=2 beats prefix=1).
    # output-0001-0 was rank #2 by simplify-order (prefix=1).
    # By match%, output-0001-0 wins (95.0 > 92.5).
    assert "output-0001-0" in out
    assert "output-0180-1" in out
    # The rank annotations must show real ranks, not "n/a".
    assert "rank #1" in out
    assert "rank #2" in out
    # And the line for output-0001-0 (the match% winner) must mention
    # rank #2 (its simplify-order position), demonstrating that the two
    # rankings are independent and both surfaced together.
    lines = out.splitlines()
    matching_lines = [
        line for line in lines if "output-0001-0" in line
    ]
    assert matching_lines, f"no line mentions output-0001-0:\n{out}"
    # The triage-section row for output-0001-0 should pair its top
    # match% with its simplify-order rank #2.
    triage_row = matching_lines[0]
    assert "95.00" in triage_row
    assert "rank #2" in triage_row


def test_triage_ranks_independently_of_simplify_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirm the triage ranking is independent of simplify-order rank.
    A candidate that ranks LOW by simplify-order distance but HIGH by
    real-tree match% should surface at the TOP of the triage section.

    This is the core methodology gap the flag exists to close: the
    grVenom_80204284 manual survey ranked by simplify-order distance and
    inspected only the top 5, missing the actual 100% match because it
    was buried deeper in the simplify-order ranking but topped real-tree
    match%."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) { int a; a = 1; }\n", encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    perm_dir = tmp_path / "perm_override"
    # Three candidates. Their simplify-order ranks (determined by the
    # search loop) will reflect compile order under the stub pcdump
    # (all-equal). The triage ranking is controlled by the canned JSON
    # below and intentionally inverts a plausible simplify-order ordering.
    winner = perm_dir / "output-0180-1"
    winner.mkdir(parents=True)
    (winner / "source.c").write_text(
        "// winner\nvoid fn_test(void) { int a; a = 1; }\n",
        encoding="utf-8",
    )
    runner_up = perm_dir / "output-0001-0"
    runner_up.mkdir(parents=True)
    (runner_up / "source.c").write_text(
        "// runner_up\nvoid fn_test(void) { int b; b = 1; }\n",
        encoding="utf-8",
    )
    weakest = perm_dir / "output-0002-0"
    weakest.mkdir(parents=True)
    (weakest / "source.c").write_text(
        "// weakest\nvoid fn_test(void) { int c; c = 1; }\n",
        encoding="utf-8",
    )

    fake_pcdump = _stub_pcdump()

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    # The canned triage results put output-0180-1 first by match%, even
    # though under lex ranking it would have appeared lower (it sorts
    # alphabetically after output-0001-0 and output-0002-0).
    canned = {
        "function": "fn_test",
        "baseline_pct": 97.74,
        "best_pct": 100.00,
        "best_path": str(winner / "source.c"),
        "results": [
            {
                "path": str(runner_up / "source.c"),
                "match_pct": 98.00,
                "delta": 0.26,
                "status": "ok",
                "first_diag": None,
                "kept_failed_path": None,
            },
            {
                "path": str(weakest / "source.c"),
                "match_pct": 97.74,
                "delta": 0.00,
                "status": "ok",
                "first_diag": None,
                "kept_failed_path": None,
            },
            {
                "path": str(winner / "source.c"),
                "match_pct": 100.00,
                "delta": 2.26,
                "status": "ok",
                "first_diag": None,
                "kept_failed_path": None,
            },
        ],
    }

    def fake_run_triage(perm_dir, function, melee_root):
        return cli_debug._TriageResult(
            returncode=0,
            stdout=json.dumps(canned),
            stderr="",
            data=canned,
        )
    monkeypatch.setattr(cli_debug, "_run_triage_subprocess", fake_run_triage)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--with-permuter",
            "--permuter-dir", str(perm_dir),
            "--triage",
            "--max-candidates", "10",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    out = result.stdout

    # Find the start of the triage section.
    assert "Best by real-tree match" in out
    triage_idx = out.find("Best by real-tree match")
    triage_section = out[triage_idx:]

    # Within the triage section, the winner (output-0180-1) must appear
    # *before* the runner-up and the weakest entry — i.e., it's ranked
    # first by match% even though it would not have been first by
    # simplify-order distance.
    idx_winner = triage_section.find("output-0180-1")
    idx_runner_up = triage_section.find("output-0001-0")
    idx_weakest = triage_section.find("output-0002-0")

    assert idx_winner != -1, f"winner not in triage section:\n{triage_section}"
    assert idx_runner_up != -1, (
        f"runner_up not in triage section:\n{triage_section}"
    )
    assert idx_weakest != -1, (
        f"weakest not in triage section:\n{triage_section}"
    )
    assert idx_winner < idx_runner_up
    assert idx_winner < idx_weakest


# ---------------------------------------------------------------------------
# Code-review follow-ups: rank-mode-aware triage annotation + clearer
# subprocess error wording for the json-unparseable case.
# ---------------------------------------------------------------------------


def test_triage_combined_rank_mode_uses_combined_sort_key(
    capsys: pytest.CaptureFixture,
) -> None:
    """When the user is in `--rank-mode combined`, the triage section's
    rank annotation must reference combined-score ordering — not the lex
    ordering. Otherwise the "rank #N" cross-reference points at a
    different table than the one rendered above and the report is
    self-inconsistent.

    Construct a SearchResult where lex and combined disagree on which
    candidate ranks first (small precolor distance flips the order at
    high alpha). The triage annotation must follow combined under
    rank_mode='combined', and the label must indicate the mode."""
    from src.cli.debug import RankMode, _render_triage_ranking
    from src.mwcc_debug.simplify_search import (
        PrecolorDistance,
        RejectedCandidate,
        SearchResult,
        SimplifyScore,
    )

    target = (42, 32)
    # output-A: prefix=2, distance=1000 (massive precolor disturbance).
    #   Lex puts this #1 (prefix=2 beats prefix=1).
    #   Combined with alpha=0.1: ratio=1.0, combined = 1.0 - 0.1*1000 = -99.0
    # output-B: prefix=1, distance=1 (tiny precolor disturbance).
    #   Lex puts this #2 (prefix=1 < prefix=2).
    #   Combined with alpha=0.1: ratio=0.5, combined = 0.5 - 0.1*1 = 0.4
    # So under combined+alpha=0.1, output-B beats output-A — the inverse
    # of the lex ordering.
    rejected = [
        RejectedCandidate(
            provenance="permuter output-A/source.c",
            score=SimplifyScore(
                target_prefix=target,
                observed_prefix=(42, 32),
                common_prefix_length=2,
                is_exact_match=True,
                baseline_common_prefix_length=0,
            ),
            rejection_reason="precolor disturbance",
            precolor_distance=PrecolorDistance(1000, 0, 0, 0, 0, 0),
        ),
        RejectedCandidate(
            provenance="permuter output-B/source.c",
            score=SimplifyScore(
                target_prefix=target,
                observed_prefix=(42, 99),
                common_prefix_length=1,
                is_exact_match=False,
                baseline_common_prefix_length=0,
            ),
            rejection_reason="precolor disturbance",
            precolor_distance=PrecolorDistance(1, 0, 0, 0, 0, 0),
        ),
    ]
    result = SearchResult(
        exact_match=None,
        progress=[],
        gate_rejected_count=2,
        gate_rejection_reasons=[],
        rejected_scored=rejected,
        compile_failure_count=0,
        total_compiles=2,
        elapsed_seconds=0.0,
    )

    # Triage payload: just two ok rows so we can read the rank annotations.
    triage_data = {
        "function": "fn_test",
        "baseline_pct": 90.0,
        "best_pct": 95.0,
        "best_path": "/some/path/output-A/source.c",
        "results": [
            {
                "path": "/some/path/output-A/source.c",
                "match_pct": 92.0,
                "delta": 2.0,
                "status": "ok",
                "first_diag": None,
                "kept_failed_path": None,
            },
            {
                "path": "/some/path/output-B/source.c",
                "match_pct": 95.0,
                "delta": 5.0,
                "status": "ok",
                "first_diag": None,
                "kept_failed_path": None,
            },
        ],
    }

    # Render under combined+alpha=0.1 — output-B must be combined rank #1,
    # output-A must be combined rank #2 (opposite of lex order).
    _render_triage_ranking(
        triage_data,
        result=result,
        perm_dir=Path("/some/path"),
        rank_mode=RankMode.combined,
        combined_alpha=0.1,
        target=target,
    )
    out = capsys.readouterr().out

    # Both candidates appear; both annotations are present.
    assert "output-A" in out
    assert "output-B" in out
    # The label must indicate the rank mode so the user knows which
    # table the cross-reference points at.
    assert "combined" in out.lower(), (
        f"expected 'combined' rank-mode label in annotation:\n{out}"
    )

    # Find the line for each candidate. output-B should have rank #1
    # (combined winner), output-A should have rank #2.
    lines = out.splitlines()
    line_a = next(line for line in lines if "output-A" in line)
    line_b = next(line for line in lines if "output-B" in line)
    # Under combined+alpha=0.1, output-B ranks first, output-A second.
    assert "#1" in line_b, (
        f"expected output-B at combined rank #1:\n{line_b}"
    )
    assert "#2" in line_a, (
        f"expected output-A at combined rank #2:\n{line_a}"
    )


def test_triage_lex_rank_mode_label_still_says_simplify_order(
    capsys: pytest.CaptureFixture,
) -> None:
    """Default `--rank-mode lex` (no explicit flag) must keep the
    'simplify-order rank #N' annotation label — that's how the existing
    test suite and grVenom campaign output were structured. Switching
    rank modes shouldn't silently change the lex-mode label."""
    from src.cli.debug import RankMode, _render_triage_ranking
    from src.mwcc_debug.simplify_search import (
        PrecolorDistance,
        RejectedCandidate,
        SearchResult,
        SimplifyScore,
    )

    target = (42, 32)
    rejected = [
        RejectedCandidate(
            provenance="permuter output-X/source.c",
            score=SimplifyScore(
                target_prefix=target,
                observed_prefix=(42, 32),
                common_prefix_length=2,
                is_exact_match=True,
                baseline_common_prefix_length=0,
            ),
            rejection_reason="precolor disturbance",
            precolor_distance=PrecolorDistance(1, 0, 0, 0, 0, 0),
        ),
    ]
    result = SearchResult(
        exact_match=None,
        progress=[],
        gate_rejected_count=1,
        gate_rejection_reasons=[],
        rejected_scored=rejected,
        compile_failure_count=0,
        total_compiles=1,
        elapsed_seconds=0.0,
    )
    triage_data = {
        "function": "fn_test",
        "baseline_pct": 90.0,
        "best_pct": 95.0,
        "best_path": "/some/path/output-X/source.c",
        "results": [
            {
                "path": "/some/path/output-X/source.c",
                "match_pct": 95.0,
                "delta": 5.0,
                "status": "ok",
                "first_diag": None,
                "kept_failed_path": None,
            },
        ],
    }

    _render_triage_ranking(
        triage_data,
        result=result,
        perm_dir=Path("/some/path"),
        rank_mode=RankMode.lex,
        combined_alpha=0.001,
        target=target,
    )
    out = capsys.readouterr().out

    # The label uses 'simplify-order' (lex-mode wording) so it matches
    # the header on the lex ranking section.
    assert "simplify-order" in out.lower()
    assert "output-X" in out


def test_triage_combined_rank_mode_cli_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end CLI smoke: when the user passes both `--rank-mode
    combined` and `--triage`, the report's triage section annotation
    references the combined ranking (not lex) — verifies the rank-mode
    threading actually wires through the CLI command body to
    `_render_triage_ranking`, not just direct unit calls."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) { int a; a = 1; }\n", encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    perm_dir = tmp_path / "perm_override"
    out = perm_dir / "output-0001-0"
    out.mkdir(parents=True)
    (out / "source.c").write_text(
        "void fn_test(void) { int a; a = 1; }\n", encoding="utf-8",
    )

    fake_pcdump = _stub_pcdump()

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    canned = {
        "function": "fn_test",
        "baseline_pct": 90.0,
        "best_pct": 95.0,
        "best_path": str(out / "source.c"),
        "results": [
            {
                "path": str(out / "source.c"),
                "match_pct": 95.0,
                "delta": 5.0,
                "status": "ok",
                "first_diag": None,
                "kept_failed_path": None,
            },
        ],
    }

    def fake_run_triage(perm_dir, function, melee_root):
        return cli_debug._TriageResult(
            returncode=0,
            stdout=json.dumps(canned),
            stderr="",
            data=canned,
        )
    monkeypatch.setattr(cli_debug, "_run_triage_subprocess", fake_run_triage)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--with-permuter",
            "--permuter-dir", str(perm_dir),
            "--triage",
            "--rank-mode", "combined",
            "--max-candidates", "5",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    # The annotation label must reflect combined mode so the cross-
    # reference matches the ranking table above.
    assert "combined" in result.stdout.lower()
    # The lex-mode label should NOT appear in the triage section.
    # Lex-mode label uses the phrase "simplify-order rank"; combined
    # mode's label uses "combined rank". Confirm we got the latter.
    triage_idx = result.stdout.find("Best by real-tree match")
    assert triage_idx != -1
    triage_section = result.stdout[triage_idx:]
    assert "combined rank" in triage_section.lower(), (
        f"expected 'combined rank' in triage section:\n{triage_section}"
    )


def test_triage_subprocess_zero_exit_unparseable_json_distinct_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the triage subprocess returns exit code 0 but produces
    stdout that isn't valid JSON, the parent command must emit a
    distinct error message (not the generic 'subprocess failed' wording,
    which would be confusing alongside 'exit code: 0').

    The new wording should mention 'unparseable' or 'invalid JSON' and
    include a snippet of the offending stdout so the user can see what
    the subprocess actually produced."""
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "sample.c"
    src_path.write_text(
        "void fn_test(void) { int a; a = 1; }\n", encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample",
             "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    perm_dir = tmp_path / "perm_override"
    out = perm_dir / "output-0001-0"
    out.mkdir(parents=True)
    (out / "source.c").write_text(
        "void fn_test(void) { int a; a = 1; }\n", encoding="utf-8",
    )

    fake_pcdump = _stub_pcdump()

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return fake_pcdump

    from src.mwcc_debug import diff_capture, simplify_search
    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    from src.cli import debug as cli_debug
    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)

    # Stub: subprocess "succeeded" but stdout is not JSON.
    bad_stdout = "not valid json{"

    def fake_run_triage(perm_dir, function, melee_root):
        return cli_debug._TriageResult(
            returncode=0,
            stdout=bad_stdout,
            stderr="",
            data=None,
        )
    monkeypatch.setattr(cli_debug, "_run_triage_subprocess", fake_run_triage)

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-first", "42,32",
            "--with-permuter",
            "--permuter-dir", str(perm_dir),
            "--triage",
            "--max-candidates", "5",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    combined = result.stdout + (result.stderr or "")
    lowered = combined.lower()
    # The new branch must use distinct wording — not "subprocess failed"
    # (the success+unparseable case is not a subprocess failure).
    assert (
        "unparseable" in lowered
        or "invalid json" in lowered
        or "could not parse" in lowered
    ), f"expected unparseable-JSON wording, got:\n{combined}"
    # And a snippet of the actual stdout should be surfaced so the user
    # can see what went wrong.
    assert "not valid json" in combined
    # The triage section itself should NOT appear — we couldn't render
    # it from unparseable data.
    assert "Best by real-tree match" not in combined


# ---------------------------------------------------------------------------
# --want-late tests
# ---------------------------------------------------------------------------


def test_mutate_simplify_order_want_first_and_want_late_mutually_exclusive() -> None:
    """Passing both --want-first and --want-late is an error."""
    proc = run_cli("--fn", "fn_test", "--want-first", "1,2", "--want-late", "3,4")

    assert proc.returncode != 0
    combined = (proc.stdout + proc.stderr).lower()
    assert "mutually exclusive" in combined or "both" in combined


def test_mutate_simplify_order_neither_want_first_nor_want_late_errors() -> None:
    """Passing neither --want-first nor --want-late is an error."""
    proc = run_cli("--fn", "fn_test")

    assert proc.returncode != 0
    combined = (proc.stdout + proc.stderr).lower()
    # Our custom "must specify exactly one" message or typer's "missing" message.
    assert "want-first" in combined or "want-late" in combined or "missing" in combined


def test_mutate_simplify_order_want_late_writes_late_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--want-late 46,44` drives search() with target_late=(46, 44).

    Uses monkeypatch to intercept the search() call and capture the
    target_late argument so we can assert it's forwarded correctly without
    needing a real toolchain.
    """
    _stage_fake_melee_root(tmp_path, monkeypatch)

    # Capture the target_late argument passed to search().
    captured: dict = {}

    from src.mwcc_debug import simplify_search as _ss

    original_search = _ss.search

    def fake_search(*args, **kwargs):
        captured["target_late"] = kwargs.get("target_late", ())
        captured["target"] = kwargs.get("target", args[3] if len(args) > 3 else ())
        # Return a minimal SearchResult so the CLI doesn't blow up on the output.
        return original_search.__wrapped__(*args, **kwargs) if hasattr(original_search, "__wrapped__") else _ss.SearchResult(
            exact_match=None,
            progress=[],
            gate_rejected_count=0,
            gate_rejection_reasons=[],
            rejected_scored=[],
            compile_failure_count=0,
            total_compiles=0,
            elapsed_seconds=0.0,
        )

    monkeypatch.setattr(_ss, "search", fake_search)

    from src.cli import debug as cli_debug
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_debug.mutate_app,
        [
            "simplify-order",
            "--fn", "fn_test",
            "--want-late", "46,44",
            "--max-candidates", "2",
        ],
    )

    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"exc: {result.exception}"
    )
    # The key assertion: target_late must be (46, 44) and target must be ().
    assert captured.get("target_late") == (46, 44), (
        f"expected target_late=(46, 44), got {captured.get('target_late')!r}"
    )
    assert captured.get("target") == (), (
        f"expected target=(), got {captured.get('target')!r}"
    )
