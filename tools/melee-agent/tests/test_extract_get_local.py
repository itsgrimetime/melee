"""Tests for `extract get` working without a decomp.me server.

Regression coverage for the shared issue queue:
- #21/#23/#85: `extract get --create-scratch` dead-ended agents when no local
  decomp.me server was reachable. It exited non-zero *before* printing any ASM
  and told agents to STOP and report instead of pointing at the supported
  local `/decomp` workflow. That hard-stop is what generated the repeat reports.
- #22 (remaining half): `extract get` produced no decompiled C. The opt-in
  `--decompile-c` flag now surfaces first-pass C via local m2c, no server needed.
"""

from __future__ import annotations

import re
import subprocess
import sys

from typer.testing import CliRunner

from src.cli import app
from src.extractor.models import FunctionInfo

runner = CliRunner()

_ASM_MARKER = ".fn fn_marker_8000ABCD, global\n/* 8000ABCD */ mflr r0\n/* magic-asm-line */ blr"


def _strip_ansi(text: str) -> str:
    return re.compile(r"\x1b\[[0-9;]*m").sub("", text)


def _fake_func() -> FunctionInfo:
    return FunctionInfo(
        name="fn_marker_8000ABCD",
        file_path="melee/lb/lbexample.c",
        address="0x8000ABCD",
        size_bytes=96,
        current_match=0.42,
        asm=_ASM_MARKER,
        object_status="NonMatching",
    )


def _patch_extract(monkeypatch) -> None:
    async def fake_extract_function(_root, _name):
        return _fake_func()

    import src.extractor as extractor_pkg

    monkeypatch.setattr(extractor_pkg, "extract_function", fake_extract_function)


def test_create_scratch_without_server_still_prints_asm_and_local_guidance(monkeypatch, tmp_path):
    """No server should NOT block the command: ASM is shown and the agent is
    pointed at the local workflow with a clean (exit 0) result."""
    _patch_extract(monkeypatch)
    monkeypatch.setattr("src.cli.extract.detect_local_api_url", lambda *a, **k: None)

    result = runner.invoke(
        app,
        ["extract", "get", "fn_marker_8000ABCD", "--create-scratch", "--melee-root", str(tmp_path)],
    )

    out = _strip_ansi(result.stdout)
    assert result.exit_code == 0, out
    # ASM is still emitted even though scratch creation was impossible.
    assert "magic-asm-line" in out
    # Actionable local-workflow guidance replaces the old dead-end message.
    assert "tools/checkdiff.py" in out
    assert "DECOMP_API_BASE" in out
    assert "melee/lb/lbexample.c" in out  # tells the agent where to edit
    # The misleading hard-stop wording must be gone.
    assert "STOP" not in out
    assert "local-only workarounds" not in out
    # No scratch was created against a (nonexistent) server.
    assert "Created scratch" not in out
    assert "Searching for existing scratches" not in out


def test_decompile_c_runs_local_m2c_and_prints_c(monkeypatch, tmp_path):
    """`--decompile-c` shells to tools/decomp.py and prints the first-pass C."""
    _patch_extract(monkeypatch)
    # decomp.py must exist under the melee root for the helper to launch it.
    (tmp_path / "tools").mkdir(parents=True)
    (tmp_path / "tools" / "decomp.py").write_text("# stub\n")

    captured = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(
            cmd, 0, stdout="void fn_marker_8000ABCD(void) { /* m2c first pass */ }\n", stderr=""
        )

    monkeypatch.setattr("src.cli.extract.subprocess.run", fake_run)

    result = runner.invoke(
        app,
        ["extract", "get", "fn_marker_8000ABCD", "--decompile-c", "--melee-root", str(tmp_path)],
    )

    out = _strip_ansi(result.stdout)
    assert result.exit_code == 0, out
    assert "void fn_marker_8000ABCD(void)" in out
    # Invoked tools/decomp.py with the function name and --no-copy.
    cmd = captured["cmd"]
    assert any("decomp.py" in str(c) for c in cmd)
    assert "fn_marker_8000ABCD" in cmd
    assert "--no-copy" in cmd
    # decomp.py uses an argparse.REMAINDER positional, so --no-copy MUST precede
    # the function name or it gets swallowed and forwarded to m2c (which rejects
    # it). Pin the order to guard that regression.
    assert cmd.index("--no-copy") < cmd.index("fn_marker_8000ABCD")


def test_decompile_c_failure_is_nonfatal(monkeypatch, tmp_path):
    """A failing/absent local m2c must not crash extract get."""
    _patch_extract(monkeypatch)
    (tmp_path / "tools").mkdir(parents=True)
    (tmp_path / "tools" / "decomp.py").write_text("# stub\n")

    def fake_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="m2c exploded")

    monkeypatch.setattr("src.cli.extract.subprocess.run", fake_run)

    result = runner.invoke(
        app,
        ["extract", "get", "fn_marker_8000ABCD", "--decompile-c", "--melee-root", str(tmp_path)],
    )

    out = _strip_ansi(result.stdout)
    assert result.exit_code == 0, out
    assert "magic-asm-line" in out  # ASM still shown
    assert "unavailable" in out.lower()


def test_decompile_c_missing_script_is_nonfatal(monkeypatch, tmp_path):
    """When tools/decomp.py is absent we report it rather than launching m2c."""
    _patch_extract(monkeypatch)

    def boom_run(cmd, *args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("subprocess.run should not be called when decomp.py is missing")

    monkeypatch.setattr("src.cli.extract.subprocess.run", boom_run)

    result = runner.invoke(
        app,
        ["extract", "get", "fn_marker_8000ABCD", "--decompile-c", "--melee-root", str(tmp_path)],
    )

    out = _strip_ansi(result.stdout)
    assert result.exit_code == 0, out
    assert "unavailable" in out.lower()
    assert "decomp.py" in out


def test_plain_extract_get_unaffected(monkeypatch, tmp_path):
    """Default invocation still prints ASM, exit 0, and does not run m2c."""
    _patch_extract(monkeypatch)

    def boom_run(cmd, *args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("plain extract get must not shell out to m2c")

    monkeypatch.setattr("src.cli.extract.subprocess.run", boom_run)

    result = runner.invoke(
        app,
        ["extract", "get", "fn_marker_8000ABCD", "--melee-root", str(tmp_path)],
    )

    out = _strip_ansi(result.stdout)
    assert result.exit_code == 0, out
    assert "magic-asm-line" in out
    assert "First-pass C" not in out
