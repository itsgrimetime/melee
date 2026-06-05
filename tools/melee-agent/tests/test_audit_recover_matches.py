"""Regression tests for stranded match recovery audit."""

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app
from src.cli.audit import _parse_lowercase_match_subject

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


def test_parse_lowercase_match_subject_handles_real_agent_subjects() -> None:
    assert _parse_lowercase_match_subject("match: ftCo_8009C744 100%") == [
        "ftCo_8009C744"
    ]
    assert _parse_lowercase_match_subject(
        "match: fn_803ACF30 100%; improve fn_803B26CC"
    ) == ["fn_803ACF30"]
    assert _parse_lowercase_match_subject(
        "match: grIceMt_801F993C (gricemt.c) - 100%"
    ) == ["grIceMt_801F993C"]


def test_parse_lowercase_match_subject_dedupes_and_rejects_common_words() -> None:
    assert _parse_lowercase_match_subject("match: function 100%") == []
    assert _parse_lowercase_match_subject(
        "match: ftCo_80093790 100%; match: ftCo_80093790 100%"
    ) == ["ftCo_80093790"]


def _write_report(repo: Path, percentages: dict[str, float]) -> None:
    report_path = repo / "build" / "GALE01" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/test",
                        "metadata": {"source_path": "src/melee/test.c"},
                        "functions": [
                            {"name": name, "fuzzy_match_percent": pct}
                            for name, pct in percentages.items()
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _init_recover_fixture_repo(tmp_path: Path) -> Path:
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
                'INCLUDE_ASM("asm/nonmatchings/test", ftCo_80093790);',
                'INCLUDE_ASM("asm/nonmatchings/test", fn_803ACF30);',
                "void alreadyMatched_80000000(void) {}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (repo / "configure.py").write_text(
        "\n".join(
            [
                'MeleeLib("test", [',
                '    Object(NonMatching, "src/melee/test.c"),',
                "])",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (repo / "config" / "GALE01" / "symbols.txt").write_text(
        "\n".join(
            [
                "ftCo_80093790 = .text:0x80093790; // type:function size:0x20 scope:global",
                "fn_803ACF30 = .text:0x803ACF30; // type:function size:0x20 scope:global",
                "alreadyMatched_80000000 = .text:0x80000000; // type:function size:0x20 scope:global",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (repo / "config" / "GALE01" / "splits.txt").write_text(
        "\n".join(
            [
                "src/melee/test.c:",
                "    .text start:0x80000000 end:0x80400000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_report(
        repo,
        {
            "ftCo_80093790": 72.5,
            "fn_803ACF30": 88.0,
            "alreadyMatched_80000000": 100.0,
        },
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")
    _git(repo, "branch", "upstream-master")

    _git(repo, "switch", "-c", "agent-a")
    _git(repo, "commit", "--allow-empty", "-m", "match: ftCo_80093790 100%")
    _git(repo, "commit", "--allow-empty", "-m", "match: fn_803ACF30 100%; improve other")
    _git(repo, "commit", "--allow-empty", "-m", "match: alreadyMatched_80000000 100%")

    _git(repo, "switch", "-c", "agent-b", "upstream-master")
    _git(repo, "commit", "--allow-empty", "-m", "match: ftCo_80093790 (file.c) - 100%")
    _git(repo, "switch", "agent-a")
    return repo


def test_audit_recover_matches_groups_stranded_candidates_by_unmatched_function(
    tmp_path: Path,
) -> None:
    repo = _init_recover_fixture_repo(tmp_path)

    result = runner.invoke(
        app,
        [
            "audit",
            "recover-matches",
            "--melee-root",
            str(repo),
            "--upstream",
            "upstream-master",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["summary"]["candidate_functions"] == 2
    assert payload["summary"]["candidate_commits"] == 3
    by_function = {row["function"]: row for row in payload["candidates"]}
    assert set(by_function) == {"fn_803ACF30", "ftCo_80093790"}
    assert len(by_function["ftCo_80093790"]["commits"]) == 2
    assert by_function["ftCo_80093790"]["current_match_percent"] == 72.5
    assert by_function["fn_803ACF30"]["file_path"] == "src/melee/test.c"
    assert "alreadyMatched_80000000" not in by_function


def test_audit_recover_matches_rejects_missing_upstream_ref(tmp_path: Path) -> None:
    repo = _init_recover_fixture_repo(tmp_path)

    result = runner.invoke(
        app,
        [
            "audit",
            "recover-matches",
            "--melee-root",
            str(repo),
            "--upstream",
            "missing-upstream",
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert "could not read match commits" in result.output
