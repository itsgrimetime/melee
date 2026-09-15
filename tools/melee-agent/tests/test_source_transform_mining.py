from __future__ import annotations

import os
import subprocess

from src.source_transform_mining import (
    LEDGER_MISSING_HASH,
    TransformMiningStore,
    diff_signature,
)


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
    return source


def _make_repo_with_transform_commit(tmp_path):
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
    return repo


def test_create_job_splits_changed_existing_functions_and_skips_ledger_hits(tmp_path):
    repo = _make_repo_with_transform_commit(tmp_path)
    store = TransformMiningStore(tmp_path / "mining.db")

    created = store.create_job(repo=repo, commit_range="HEAD~1..HEAD")

    assert created.tasks_created == 1
    assert created.skipped_ledger_hits == 0
    tasks = store.list_tasks(created.job_id)
    assert [task.function_name for task in tasks] == ["foo"]
    assert {task.status for task in tasks} == {"pending"}
    assert tasks[0].before_hash != tasks[0].after_hash

    duplicate = store.create_job(repo=repo, commit_range="HEAD~1..HEAD")

    assert duplicate.tasks_created == 0
    assert duplicate.skipped_ledger_hits == 1
    assert store.job_status(duplicate.job_id).total_tasks == 0


def test_create_job_can_include_function_additions_when_requested(tmp_path):
    repo = _make_repo_with_transform_commit(tmp_path)
    store = TransformMiningStore(tmp_path / "mining.db")

    created = store.create_job(
        repo=repo,
        commit_range="HEAD~1..HEAD",
        include_additions=True,
    )

    assert created.tasks_created == 2
    tasks = store.list_tasks(created.job_id)
    assert [task.function_name for task in tasks] == ["foo", "bar"]
    assert tasks[1].before_hash == LEDGER_MISSING_HASH


def test_claim_task_can_skip_function_additions(tmp_path):
    repo = _make_repo_with_transform_commit(tmp_path)
    store = TransformMiningStore(tmp_path / "mining.db")
    created = store.create_job(
        repo=repo,
        commit_range="HEAD~1..HEAD",
        include_additions=True,
    )

    task = store.claim_task(created.job_id, agent_id="agent-a", existing_only=True)

    assert task is not None
    assert task.function_name == "foo"
    assert task.before_source is not None
    assert task.after_source is not None
    assert store.claim_task(created.job_id, agent_id="agent-a", existing_only=True) is None
    addition = store.claim_task(created.job_id, agent_id="agent-a")
    assert addition is not None
    assert addition.function_name == "bar"
    assert addition.before_source is None


def test_task_lifecycle_updates_ledger_and_job_counts(tmp_path):
    repo = _make_repo_with_transform_commit(tmp_path)
    store = TransformMiningStore(tmp_path / "mining.db")
    created = store.create_job(repo=repo, commit_range="HEAD~1..HEAD")

    task = store.claim_task(created.job_id, agent_id="agent-a")

    assert task is not None
    assert task.status == "assigned"
    assert store.ledger_stats()["assigned"] == 1

    store.complete_task(
        task.id,
        analysis_notes="bar is an example of a simple added final source",
        result_kind="example-for-existing-family",
        family_id="declaration_use_boundary",
    )

    status = store.job_status(created.job_id)
    assert status.processed_tasks == 1
    assert store.ledger_stats()["completed"] == 1
    completed = store.get_task(task.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.result_kind == "example-for-existing-family"
    assert completed.family_id == "declaration_use_boundary"
    results = store.list_results(result_kind="example-for-existing-family")
    assert [result.id for result in results] == [task.id]
    assert results[0].analysis_notes == "bar is an example of a simple added final source"


def test_fail_task_records_failure_without_requeueing_same_transition(tmp_path):
    repo = _make_repo_with_transform_commit(tmp_path)
    store = TransformMiningStore(tmp_path / "mining.db")
    created = store.create_job(repo=repo, commit_range="HEAD~1..HEAD")
    task = store.claim_task(created.job_id, agent_id="agent-a")
    assert task is not None

    store.fail_task(task.id, "source extraction was not useful")

    assert store.ledger_stats()["failed"] == 1
    duplicate = store.create_job(repo=repo, commit_range="HEAD~1..HEAD")
    assert duplicate.tasks_created == 0
    assert duplicate.skipped_ledger_hits == 1


def test_complete_pending_additions_bulk_marks_additions_out_of_scope(tmp_path):
    repo = _make_repo_with_transform_commit(tmp_path)
    store = TransformMiningStore(tmp_path / "mining.db")
    created = store.create_job(
        repo=repo,
        commit_range="HEAD~1..HEAD",
        include_additions=True,
    )

    completed = store.complete_pending_additions(created.job_id)

    assert completed == 1
    status = store.job_status(created.job_id)
    assert status.processed_tasks == 1
    tasks = {task.function_name: task for task in store.list_tasks(created.job_id)}
    assert tasks["bar"].status == "completed"
    assert tasks["bar"].result_kind == "not-useful"
    assert tasks["bar"].family_id is None
    assert tasks["foo"].status == "pending"


def test_diff_clusters_group_existing_function_rewrites_and_bulk_complete(tmp_path):
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

int baz(int x)
{
    return x + 2;
}

int qux(int x)
{
    return x - 1;
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

int baz(int x)
{
    int y = x + 2;
    return y;
}

int qux(int x)
{
    return -x;
}
""",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "match: cluster rewrites")
    store = TransformMiningStore(tmp_path / "mining.db")
    created = store.create_job(repo=repo, commit_range="HEAD~1..HEAD")

    clusters = store.diff_clusters(created.job_id)

    assert sum(cluster.task_count for cluster in clusters) == 3
    split_return = next(
        cluster
        for cluster in clusters
        if {sample.function_name for sample in cluster.samples} == {"foo", "baz"}
    )
    assert split_return.task_count == 2

    completed = store.complete_cluster(
        created.job_id,
        split_return.signature,
        analysis_notes="split return expression into local temp",
        result_kind="example-for-existing-family",
        family_id="scoped_alias",
    )

    assert completed == 2
    tasks = {task.function_name: task for task in store.list_tasks(created.job_id)}
    assert tasks["foo"].status == "completed"
    assert tasks["baz"].status == "completed"
    assert tasks["qux"].status == "pending"


def test_diff_signature_distinguishes_identifier_to_float_literal_from_float_value_change():
    symbol_to_literal = diff_signature(
        "void f(void)\n{\n    call(global_float);\n}\n",
        "void f(void)\n{\n    call(0.0F);\n}\n",
    )
    float_value_change = diff_signature(
        "void f(void)\n{\n    call(1.0F);\n}\n",
        "void f(void)\n{\n    call(2.0F);\n}\n",
    )

    assert symbol_to_literal != float_value_change
    assert symbol_to_literal != "e3b0c44298fc1c14"
