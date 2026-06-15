"""Regression tests for local tooling documentation used by agents."""
from __future__ import annotations

import json
from pathlib import Path
import os

from typer.testing import CliRunner

from src import db as state_db
from src.cli import app
from src.cli import complete as complete_cli


REPO_ROOT = Path(__file__).resolve().parents[3]
runner = CliRunner()


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


def test_understand_skill_claim_command_is_registered() -> None:
    text = (REPO_ROOT / ".claude" / "skills" / "understand" / "SKILL.md").read_text()

    assert "melee-agent claim add <func_name>" in text
    result = runner.invoke(app, ["claim", "add", "--help"])

    assert result.exit_code == 0
    assert "Function name to claim" in result.stdout


def test_understand_skill_complete_document_command_is_registered() -> None:
    text = (REPO_ROOT / ".claude" / "skills" / "understand" / "SKILL.md").read_text()

    assert "melee-agent complete document <func_name>" in text
    result = runner.invoke(app, ["complete", "document", "--help"])

    assert result.exit_code == 0
    assert "Mark a function as documented" in result.stdout


def test_understand_skill_complete_document_releases_claim(monkeypatch, tmp_path) -> None:
    claims_file = tmp_path / "claims.json"
    monkeypatch.setattr(complete_cli, "DECOMP_CLAIMS_FILE", str(claims_file))
    claims_file.write_text(
        json.dumps(
            {
                "ftCo_8007E3B0": {
                    "agent_id": "doc-test",
                    "timestamp": 1_781_547_328.0,
                    "source_file": "src/melee/ft/chara/ftCommon/ftCo_Guard.c",
                }
            }
        )
    )
    state_db.reset_db()
    state_db.get_db(tmp_path / "state.db")

    try:
        assert "ftCo_8007E3B0" in json.loads(claims_file.read_text())

        complete_result = runner.invoke(app, ["complete", "document", "ftCo_8007E3B0", "--json"])

        assert complete_result.exit_code == 0
        assert json.loads(complete_result.stdout)["documentation_status"] == "complete"
        assert "ftCo_8007E3B0" not in json.loads(claims_file.read_text())
    finally:
        state_db.reset_db()
