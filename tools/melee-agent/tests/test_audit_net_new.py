"""Regression tests for audit net-new branch classification."""

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app

runner = CliRunner()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _write_report(repo: Path, percentages: dict[str, float]) -> None:
    report_path = repo / "build" / "GALE01" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/test",
                        "functions": [
                            {"name": name, "fuzzy_match_percent": pct}
                            for name, pct in percentages.items()
                        ],
                    }
                ]
            }
        )
    )


def _init_fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "melee"
    (repo / "src" / "melee").mkdir(parents=True)
    (repo / "config" / "GALE01").mkdir(parents=True)
    _git(tmp_path, "init", str(repo))
    _git(repo, "config", "user.email", "agent@example.invalid")
    _git(repo, "config", "user.name", "Agent")

    source = repo / "src" / "melee" / "test.c"
    source.write_text(
        "\n".join(
            [
                "void grKongo_801D5490(void)",
                "{",
                "}",
                "",
                "/// #grPura_80211DDC",
                "void grPura_80211DDC(void)",
                "{",
                "}",
                "",
                "/// #ifStatus_802F6EA4",
                "",
                "INCLUDE_ASM(\"asm/nonmatchings/test\", grGreatBay_801F60C4);",
                "",
                "/// #ifStatus_802F7000",
                "",
            ]
        )
    )
    _git(repo, "add", "src/melee/test.c", "config/GALE01")
    _git(repo, "commit", "-m", "upstream baseline")
    _git(repo, "branch", "upstream-master")

    _git(repo, "switch", "-c", "feature")
    source.write_text(
        "\n".join(
            [
                "void grKongo_801D5490(void)",
                "{",
                "}",
                "",
                "/// #grPura_80211DDC",
                "void grPura_80211DDC(void)",
                "{",
                "}",
                "",
                "void ifStatus_802F6EA4(void)",
                "{",
                "}",
                "",
                "void grGreatBay_801F60C4(void)",
                "{",
                "}",
                "",
                "void ifStatus_802F7000(void)",
                "{",
                "}",
                "",
                "static void local_helper(void)",
                "{",
                "}",
                "",
            ]
        )
    )
    _write_report(
        repo,
        {
            "grKongo_801D5490": 100.0,
            "grPura_80211DDC": 100.0,
            "ifStatus_802F6EA4": 100.0,
            "grGreatBay_801F60C4": 100.0,
            "ifStatus_802F7000": 87.25,
        },
    )
    _git(repo, "add", "src/melee/test.c", "build/GALE01/report.json")
    _git(repo, "commit", "-m", "feature branch")
    return repo


def _bucket_functions(payload: dict, bucket: str) -> set[str]:
    return {item["function"] for item in payload["buckets"][bucket]}


def test_audit_net_new_buckets_branch_bodies_against_upstream_placeholders(tmp_path: Path) -> None:
    repo = _init_fixture_repo(tmp_path)

    result = runner.invoke(
        app,
        [
            "audit",
            "net-new",
            "--melee-root",
            str(repo),
            "--origin",
            "feature",
            "--upstream",
            "upstream-master",
            "--no-fetch",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert _bucket_functions(payload, "net_new_100") == {
        "grGreatBay_801F60C4",
        "ifStatus_802F6EA4",
    }
    assert _bucket_functions(payload, "net_new_wip") == {"ifStatus_802F7000"}
    assert _bucket_functions(payload, "dup_upstream_has_body") == {"grKongo_801D5490"}
    assert _bucket_functions(payload, "dup_matched_but_unnamed") == {"grPura_80211DDC"}
    assert "local_helper" not in _bucket_functions(payload, "net_new_wip")
    assert payload["summary"]["origin_bodies"] == 6
    assert payload["summary"]["classified_origin_bodies"] == 5
    assert payload["summary"]["unreported_origin_helpers"] == 1
    assert payload["summary"]["net_new_100"] == 2
    assert payload["summary"]["net_new_wip"] == 1
    assert payload["summary"]["dup_upstream_has_body"] == 1
    assert payload["summary"]["dup_matched_but_unnamed"] == 1
