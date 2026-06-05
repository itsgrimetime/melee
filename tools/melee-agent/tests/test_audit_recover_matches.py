"""Regression tests for stranded match recovery audit."""

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app
from src.cli.audit import (
    _normalize_recovery_source_path,
    _parse_lowercase_match_subject,
)

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


def test_normalize_recovery_source_path_accepts_taxonomy_style_paths(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "melee"
    git_path, disk_path = _normalize_recovery_source_path(
        repo,
        "melee/pl/plbonuslib.c",
    )

    assert git_path == "src/melee/pl/plbonuslib.c"
    assert disk_path == repo / "src" / "melee" / "pl" / "plbonuslib.c"


def test_normalize_recovery_source_path_preserves_src_prefixed_paths(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "melee"
    git_path, disk_path = _normalize_recovery_source_path(
        repo,
        "src/melee/test.c",
    )

    assert git_path == "src/melee/test.c"
    assert disk_path == repo / "src" / "melee" / "test.c"


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


def _write_fake_checkdiff(repo: Path, *, force_match: bool | None = None) -> None:
    tools = repo / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    match_expr = (
        repr(force_match)
        if force_match is not None
        else "f'void {fn}(void)' in text"
    )
    (tools / "checkdiff.py").write_text(
        "\n".join(
            [
                "import json",
                "import pathlib",
                "import sys",
                "fn = sys.argv[1]",
                "text = pathlib.Path('src/melee/test.c').read_text()",
                f"matched = {match_expr}",
                "assert '--no-fingerprint' in sys.argv",
                "print(json.dumps({'function': fn, 'match': matched, 'fuzzy_match_percent': 100.0 if matched else 72.5}))",
                "raise SystemExit(0 if matched else 1)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "tools/checkdiff.py")
    _git(repo, "commit", "-m", "test checkdiff fixture")


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


def _add_recover_candidate_commit(
    repo: Path,
    *,
    function: str = "ftCo_80093790",
    body: bool = True,
    sibling_edit: bool = False,
) -> str:
    start_branch = _git(repo, "branch", "--show-current").strip()
    branch = f"candidate-{function}-{body}-{sibling_edit}"
    _git(repo, "switch", "-c", branch, "agent-b")
    source = repo / "src" / "melee" / "test.c"
    lines = [
        'INCLUDE_ASM("asm/nonmatchings/test", ftCo_80093790);',
        'INCLUDE_ASM("asm/nonmatchings/test", fn_803ACF30);',
        "void alreadyMatched_80000000(void) {}",
        "",
    ]
    if body:
        lines[0] = "void ftCo_80093790(void) {}"
    if sibling_edit:
        lines[1] = "void fn_803ACF30(void) {}"
    source.write_text("\n".join(lines), encoding="utf-8")
    _git(repo, "add", "src/melee/test.c")
    if body or sibling_edit:
        _git(repo, "commit", "-m", f"match: {function} 100%")
    else:
        _git(repo, "commit", "--allow-empty", "-m", f"match: {function} 100%")
    commit = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "switch", start_branch)
    return commit


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


def test_audit_recover_matches_verify_reapplies_and_restores_candidate(
    tmp_path: Path,
) -> None:
    repo = _init_recover_fixture_repo(tmp_path)
    _write_fake_checkdiff(repo)
    _add_recover_candidate_commit(repo)
    source = repo / "src" / "melee" / "test.c"
    before = source.read_text(encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "audit",
            "recover-matches",
            "--melee-root",
            str(repo),
            "--upstream",
            "upstream-master",
            "--verify",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    verified = [
        row for row in payload["verification"]
        if row["function"] == "ftCo_80093790"
    ]
    verified_row = next(row for row in verified if row["status"] == "verified")
    assert verified_row["match"] is True
    assert verified_row["match_percent"] == 100.0
    verified_index = verified.index(verified_row)
    assert any(row["status"] == "skipped_after_verified" for row in verified[verified_index + 1:])
    assert source.read_text(encoding="utf-8") == before
    assert _git(repo, "status", "--porcelain") == ""


def test_audit_recover_matches_verify_preserves_unrelated_dirty_work(
    tmp_path: Path,
) -> None:
    repo = _init_recover_fixture_repo(tmp_path)
    _write_fake_checkdiff(repo)
    _add_recover_candidate_commit(repo)
    extra = repo / "README.md"
    extra.write_text("local note\n", encoding="utf-8")
    before_status = _git(repo, "status", "--porcelain")

    result = runner.invoke(
        app,
        [
            "audit",
            "recover-matches",
            "--melee-root",
            str(repo),
            "--upstream",
            "upstream-master",
            "--verify",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert _git(repo, "status", "--porcelain") == before_status
    assert extra.read_text(encoding="utf-8") == "local note\n"


def test_audit_recover_matches_apply_leaves_verified_candidate_applied(
    tmp_path: Path,
) -> None:
    repo = _init_recover_fixture_repo(tmp_path)
    _write_fake_checkdiff(repo)
    _add_recover_candidate_commit(repo)
    source = repo / "src" / "melee" / "test.c"

    result = runner.invoke(
        app,
        [
            "audit",
            "recover-matches",
            "--melee-root",
            str(repo),
            "--upstream",
            "upstream-master",
            "--apply",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    applied = next(
        row for row in payload["verification"]
        if row["function"] == "ftCo_80093790"
        and row["status"] == "applied"
    )
    assert applied["status"] == "applied"
    assert "void ftCo_80093790(void)" in source.read_text(encoding="utf-8")


def test_audit_recover_matches_apply_ignores_same_file_sibling_edit(
    tmp_path: Path,
) -> None:
    repo = _init_recover_fixture_repo(tmp_path)
    _write_fake_checkdiff(repo)
    _add_recover_candidate_commit(repo, sibling_edit=True)
    source = repo / "src" / "melee" / "test.c"

    result = runner.invoke(
        app,
        [
            "audit",
            "recover-matches",
            "--melee-root",
            str(repo),
            "--upstream",
            "upstream-master",
            "--apply",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    text = source.read_text(encoding="utf-8")
    assert "void ftCo_80093790(void)" in text
    assert 'INCLUDE_ASM("asm/nonmatchings/test", fn_803ACF30);' in text
    assert "void fn_803ACF30(void)" not in text


def test_audit_recover_matches_match_false_json_exit_one_is_not_match(
    tmp_path: Path,
) -> None:
    repo = _init_recover_fixture_repo(tmp_path)
    _write_fake_checkdiff(repo, force_match=False)
    _add_recover_candidate_commit(repo)

    result = runner.invoke(
        app,
        [
            "audit",
            "recover-matches",
            "--melee-root",
            str(repo),
            "--upstream",
            "upstream-master",
            "--verify",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    row = next(
        row for row in payload["verification"]
        if row["function"] == "ftCo_80093790"
        and row["status"] == "not_match"
    )
    assert row["status"] == "not_match"
    assert row["match"] is False
    assert row["match_percent"] == 72.5


def test_audit_recover_matches_candidate_without_body_reports_apply_failed(
    tmp_path: Path,
) -> None:
    repo = _init_recover_fixture_repo(tmp_path)
    _write_fake_checkdiff(repo)
    _add_recover_candidate_commit(repo, body=False)

    result = runner.invoke(
        app,
        [
            "audit",
            "recover-matches",
            "--melee-root",
            str(repo),
            "--upstream",
            "upstream-master",
            "--verify",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    row = [
        row for row in payload["verification"]
        if row["function"] == "ftCo_80093790"
    ][0]
    assert row["status"] == "apply_failed"
    assert row["reason"] == "no_candidate_function"


def test_audit_recover_matches_apply_rejects_dirty_tracked_worktree(
    tmp_path: Path,
) -> None:
    repo = _init_recover_fixture_repo(tmp_path)
    _write_fake_checkdiff(repo)
    _add_recover_candidate_commit(repo)
    (repo / "src" / "melee" / "test.c").write_text("dirty\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "audit",
            "recover-matches",
            "--melee-root",
            str(repo),
            "--upstream",
            "upstream-master",
            "--apply",
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert "tracked worktree has local changes" in result.output
