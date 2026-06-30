"""Regression tests for confirmed correctness bugs in mismatch_db.backfill.

Covers:
- BUG 20: function-name extraction from commit messages (colon convention,
  'Matched', and melee identifier shapes).
- BUG 21: commit metadata parsing breaks when the subject contains a '|'.
- BUG 22: generate_analysis_prompt renders literal "None" for a missing
  function name in the JSON examples block.
"""

import os
import subprocess

import pytest

from src.mismatch_db.backfill import (
    AnalysisTask,
    BackfillOrchestrator,
    TaskStatus,
    _extract_function_name,
    generate_analysis_prompt,
)


@pytest.fixture(autouse=True)
def _reset_global_db():
    """BackfillOrchestrator(db_path=...) routes through the module-level
    get_db() singleton, which caches the StateDB on first use and ignores
    later paths. Reset it before and after each test so these tests neither
    inherit a stale singleton nor leak their temp DB to later tests (the
    leak previously surfaced unrelated suites as flaky under full-run load)."""
    from src.db import reset_db

    reset_db()
    yield
    reset_db()

# ---------------------------------------------------------------------------
# BUG 20: _extract_function_name
# ---------------------------------------------------------------------------


def test_bug20_colon_convention():
    """'match: <func>' (the dominant repo convention) must resolve the name."""
    assert _extract_function_name("match: fn_801D542C via x") == "fn_801D542C"


def test_bug20_matched_word():
    """'Matched <func>' must resolve the name."""
    assert _extract_function_name("Matched if_2F72 by converting") == "if_2F72"


def test_bug20_prefixed_melee_identifier():
    """Prefixed melee identifiers (grCastle_*) must be recognized."""
    assert _extract_function_name("Make grCastle_801CDFD8 match") == "grCastle_801CDFD8"


def test_bug20_space_form_still_works():
    """GUARD: the original whitespace form must still work."""
    assert _extract_function_name("match fn_80001234") == "fn_80001234"


def test_bug20_no_function_token_does_not_crash():
    """GUARD: a message with no melee-shaped token returns the 100%-token or
    None as before, and never crashes."""
    # Per the documented behavior this may yield the legacy "<word> 100%"
    # token or None; it must not crash and must not invent a melee identifier.
    result = _extract_function_name("cleanup of headers 100%")
    assert result in (None, "headers")


def test_bug20_stopword_not_returned():
    """GUARD: 'match the X' must not return the stopword 'the'."""
    assert _extract_function_name("match the thing") != "the"


# ---------------------------------------------------------------------------
# BUG 21: pipe in commit subject must not corrupt message/date
# ---------------------------------------------------------------------------


def _git(repo, *args):
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_AUTHOR_DATE": "2026-06-07T12:00:00",
        "GIT_COMMITTER_DATE": "2026-06-07T12:00:00",
    }
    merged = dict(os.environ, **env)
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=merged,
    )


def _make_repo(tmp_path, subject):
    repo = tmp_path / "melee"
    # The orchestrator's pathspec is src/melee/**/*.c, which only matches
    # files nested under a subdirectory, so place the file accordingly.
    (repo / "src" / "melee" / "mn").mkdir(parents=True)
    (repo / "src" / "melee" / "mn" / "x.c").write_text("void x(void) {}\n")
    _git(repo, "init")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", subject)
    return repo


def test_bug21_pipe_in_subject_preserves_message_and_date(tmp_path):
    """A '|' in the subject must not truncate the message or corrupt the date."""
    subject = "match: foo | bar fixup 100%"
    repo = _make_repo(tmp_path, subject)

    db_path = tmp_path / "state.db"
    orch = BackfillOrchestrator(db_path=db_path)
    job_id = orch.create_job(commit_range="HEAD")
    orch.populate_tasks(job_id, repo)

    tasks = orch.list_tasks(job_id)
    assert len(tasks) == 1
    full = orch.get_task(tasks[0].id)

    assert full.commit_message == subject
    assert full.commit_date == "2026-06-07"


def test_bug21_normal_subject_still_parses(tmp_path):
    """GUARD: a subject without a pipe still parses correctly."""
    subject = "match: foo fixup 100%"
    repo = _make_repo(tmp_path, subject)

    db_path = tmp_path / "state.db"
    orch = BackfillOrchestrator(db_path=db_path)
    job_id = orch.create_job(commit_range="HEAD")
    orch.populate_tasks(job_id, repo)

    tasks = orch.list_tasks(job_id)
    assert len(tasks) == 1
    full = orch.get_task(tasks[0].id)

    assert full.commit_message == subject
    assert full.commit_date == "2026-06-07"


# ---------------------------------------------------------------------------
# BUG 22: generate_analysis_prompt None fallback in examples block
# ---------------------------------------------------------------------------


def _task(function_name):
    return AnalysisTask(
        id="t1",
        job_id="j1",
        status=TaskStatus.PENDING,
        commit_sha="deadbeef",
        commit_message="match: something",
        function_name=function_name,
    )


def test_bug22_none_function_renders_unknown():
    out = generate_analysis_prompt(_task(None))
    assert '"function": "Unknown"' in out
    assert '"function": "None"' not in out


def test_bug22_real_name_renders_name():
    """GUARD: a real function name renders that name, not Unknown."""
    out = generate_analysis_prompt(_task("fn_801D542C"))
    assert '"function": "fn_801D542C"' in out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
