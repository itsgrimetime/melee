"""Smoke test for `debug search run` CLI.

Uses --dry-compiler so no real mwcc/wibo/SSH is needed.
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from src.search.cli import search_app


def test_search_run_dry(tmp_path: Path) -> None:
    runner = CliRunner()
    seed = tmp_path / "seed.c"
    seed.write_text("int MatToQuat(){return 0;}")
    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "MatToQuat",
            "--unit", "quatlib",
            "--no-remote",
            "--seed", str(seed),
            "--store", str(tmp_path / "store"),
            "--max-iters", "1",
            "--dry-compiler",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "accounting" in result.stdout.lower()
