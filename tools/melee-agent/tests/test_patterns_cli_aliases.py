"""Tests for pattern command aliases used by agent instructions."""

import re

from typer.testing import CliRunner

from src.cli import app


runner = CliRunner()


def strip_ansi(text: str) -> str:
    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_escape.sub("", text)


def test_patterns_wrappers_alias_matches_wrapper_command():
    result = runner.invoke(app, ["patterns", "wrappers", "gobj->user_data"])

    assert result.exit_code == 0, result.stdout
    assert "HSD_GObjGetUserData" in strip_ansi(result.stdout)


def test_patterns_anti_patterns_alias_matches_anti_pattern_command():
    result = runner.invoke(app, ["patterns", "anti-patterns", "list"])

    assert result.exit_code == 0, result.stdout
    assert "Known Anti-Patterns" in strip_ansi(result.stdout)
