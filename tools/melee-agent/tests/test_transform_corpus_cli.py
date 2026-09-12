from __future__ import annotations

import os
import json
import re
import subprocess

from typer.testing import CliRunner

from src.cli import app


runner = CliRunner()


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _git(repo, *args):
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_AUTHOR_DATE": "2026-06-13T12:00:00",
        "GIT_COMMITTER_DATE": "2026-06-13T12:00:00",
    }
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=dict(os.environ, **env),
    )


def _write_source(repo, text):
    source = repo / "src" / "melee" / "mn" / "mine.c"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text)


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _write_source(
        repo,
        """\
int foo(int x)
{
    return x + 1;
}
""",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _write_source(
        repo,
        """\
int foo(int x)
{
    int y = x + 1;
    return y;
}
""",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "match: foo")
    return repo


def test_transform_corpus_mine_help_is_registered():
    result = runner.invoke(app, ["transform-corpus", "mine", "--help"])

    assert result.exit_code == 0
    output = strip_ansi(result.stdout)
    assert "Mine source-transform corpus candidates" in output
    assert "create-job" in output
    assert "claim-task" in output


def test_transform_corpus_create_job_prints_created_and_skipped_counts(tmp_path):
    repo = _make_repo(tmp_path)
    db = tmp_path / "mining.db"

    first = runner.invoke(
        app,
        [
            "transform-corpus",
            "mine",
            "create-job",
            "--repo",
            str(repo),
            "--db",
            str(db),
            "--range",
            "HEAD~1..HEAD",
        ],
    )

    assert first.exit_code == 0
    first_output = strip_ansi(first.stdout)
    assert "Created job:" in first_output
    assert "Queued tasks: 1" in first_output
    assert "Skipped ledger hits: 0" in first_output

    second = runner.invoke(
        app,
        [
            "transform-corpus",
            "mine",
            "create-job",
            "--repo",
            str(repo),
            "--db",
            str(db),
            "--range",
            "HEAD~1..HEAD",
        ],
    )

    assert second.exit_code == 0
    second_output = strip_ansi(second.stdout)
    assert "Queued tasks: 0" in second_output
    assert "Skipped ledger hits: 1" in second_output


def test_transform_corpus_results_lists_completed_candidate_tasks(tmp_path):
    repo = _make_repo(tmp_path)
    db = tmp_path / "mining.db"
    runner.invoke(
        app,
        [
            "transform-corpus",
            "mine",
            "create-job",
            "--repo",
            str(repo),
            "--db",
            str(db),
            "--range",
            "HEAD~1..HEAD",
        ],
    )
    from src.source_transform_mining import TransformMiningStore

    store = TransformMiningStore(db)
    job_id = next(iter(store.conn.execute("SELECT id FROM transform_mining_jobs")))[0]
    task = store.claim_task(job_id, agent_id="cli-test")
    assert task is not None
    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps({
        "analysis_notes": "new bounded transform candidate",
        "result_kind": "new-family-candidate",
        "family_id": "phase_local_reuse",
    }))
    completed = runner.invoke(
        app,
        [
            "transform-corpus",
            "mine",
            "complete-task",
            task.id,
            str(result_file),
            "--db",
            str(db),
        ],
    )
    assert completed.exit_code == 0

    listed = runner.invoke(
        app,
        [
            "transform-corpus",
            "mine",
            "results",
            "--db",
            str(db),
            "--result-kind",
            "new-family-candidate",
        ],
    )

    assert listed.exit_code == 0
    output = strip_ansi(listed.stdout)
    assert task.id in output
    assert "phase_local_reuse" in output
    assert "foo" in output


def test_transform_corpus_complete_additions_and_clusters_cli(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _write_source(
        repo,
        """\
int foo(int x)
{
    return x + 1;
}
""",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _write_source(
        repo,
        """\
int foo(int x)
{
    int y = x + 1;
    return y;
}

int bar(int x)
{
    return x * 2;
}
""",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "match: foo and bar")
    db = tmp_path / "mining.db"

    created = runner.invoke(
        app,
        [
            "transform-corpus",
            "mine",
            "create-job",
            "--repo",
            str(repo),
            "--db",
            str(db),
            "--range",
            "HEAD~1..HEAD",
            "--include-additions",
        ],
    )
    assert created.exit_code == 0

    additions = runner.invoke(
        app,
        [
            "transform-corpus",
            "mine",
            "complete-additions",
            "--db",
            str(db),
            _job_id_from_db(db),
        ],
    )
    assert additions.exit_code == 0
    assert "Completed addition-only tasks: 1" in strip_ansi(additions.stdout)

    clusters = runner.invoke(
        app,
        [
            "transform-corpus",
            "mine",
            "clusters",
            "--db",
            str(db),
            _job_id_from_db(db),
        ],
    )
    assert clusters.exit_code == 0
    cluster_output = strip_ansi(clusters.stdout)
    assert "foo" in cluster_output
    signature = cluster_output.split()[0]

    completed = runner.invoke(
        app,
        [
            "transform-corpus",
            "mine",
            "complete-cluster",
            "--db",
            str(db),
            "--result-kind",
            "example-for-existing-family",
            "--family-id",
            "scoped_alias",
            "--notes",
            "split return into local temp",
            _job_id_from_db(db),
            signature,
        ],
    )
    assert completed.exit_code == 0
    assert "Completed cluster tasks: 1" in strip_ansi(completed.stdout)


def _job_id_from_db(db):
    from src.source_transform_mining import TransformMiningStore

    store = TransformMiningStore(db)
    return next(iter(store.conn.execute("SELECT id FROM transform_mining_jobs")))[0]
