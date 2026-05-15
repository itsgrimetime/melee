"""Tests for trackable agent tooling overlay paths."""

from __future__ import annotations

import subprocess


def git_ignores(path: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", path], check=False).returncode == 0


def test_agent_overlay_sources_are_trackable():
    for path in (
        ".agents/skills/decomp/SKILL.md",
        ".claude/skills/decomp/SKILL.md",
        ".codex/skills",
        "tools/melee-agent/tests/test_attempts.py",
        "tools/melee-agent/tests/test_patterns_inline.py",
        "tools/melee-agent/tests/test_patterns_cli_aliases.py",
    ):
        assert not git_ignores(path), f"{path} should be trackable"


def test_melee_agent_generated_outputs_stay_ignored():
    for path in (
        "tools/melee-agent/.coverage",
        "tools/melee-agent/htmlcov/index.html",
    ):
        assert git_ignores(path), f"{path} should be ignored"
