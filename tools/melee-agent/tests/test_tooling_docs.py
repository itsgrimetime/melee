"""Regression tests for local tooling documentation used by agents."""
from __future__ import annotations

from pathlib import Path
import os


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_opseq_skill_uses_melee_agent_entrypoint() -> None:
    text = (REPO_ROOT / ".claude" / "skills" / "opseq" / "SKILL.md").read_text()

    assert "melee-agent opseq" in text
    assert "go run . opseq" not in text
    assert "tools/table-typer/table-typer opseq" not in text


def test_checkdiff_documented_entrypoint_is_executable() -> None:
    checkdiff = REPO_ROOT / "tools" / "checkdiff.py"

    assert checkdiff.exists()
    assert os.access(checkdiff, os.X_OK), (
        "tools/checkdiff.py is documented as a direct command and must be "
        "executable"
    )
