"""Tests for the `debug inspect ceiling` decl-order candidate runner.

Issues #36/#37: the decl-order enumeration phase compiled each candidate with no
per-candidate output and no time bound, so when piped to an agent it block-
buffered and looked hung for ~a minute. The extracted `_run_decl_candidates`
emits streaming progress and honors a wall-clock budget for a clear stop mode.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.cli import debug as debug_cli
from src.cli.debug import (
    DeclCandidateFailure,
    _build_and_match_with_diagnostic,
    _run_decl_candidates,
)


def _candidates(*labels):
    # perm payloads are opaque to the runner; identity is fine for tests.
    return [(label, [i]) for i, label in enumerate(labels)]


def test_emits_progress_per_candidate_and_tracks_best():
    emitted: list[str] = []
    pcts = {0: 90.0, 1: 95.0, 2: 80.0}

    results, best_pct, best_label, stopped = _run_decl_candidates(
        _candidates("promote a", "promote b", "promote c"),
        reorder=lambda perm: f"patched-{perm[0]}",
        build_and_match=lambda patched: pcts[int(patched.split("-")[1])],
        baseline=88.0,
        emit=emitted.append,
    )

    assert stopped is False
    assert len(results) == 3
    assert best_label == "promote b"  # 95.0 is the only one above baseline-best progression
    assert best_pct == 95.0
    # One streaming progress line per candidate, with pct shown.
    assert sum("promote a" in line for line in emitted) == 1
    assert any("95.00%" in line for line in emitted)
    assert any("(1/3)" in line for line in emitted)


def test_stops_early_when_time_budget_exceeded():
    emitted: list[str] = []
    build_calls: list[str] = []
    # now() sequence: start=0, iter1 check=0, iter2 check=50 (>=budget 10 -> stop)
    clock = iter([0.0, 0.0, 50.0, 999.0])

    results, best_pct, best_label, stopped = _run_decl_candidates(
        _candidates("c0", "c1", "c2"),
        reorder=lambda perm: "patched",
        build_and_match=lambda patched: build_calls.append(patched) or 90.0,
        baseline=88.0,
        max_seconds=10.0,
        emit=emitted.append,
        now=lambda: next(clock),
    )

    assert stopped is True
    assert len(build_calls) == 1  # only the first candidate ran before the budget tripped
    assert any("time budget" in line.lower() for line in emitted)


def test_reorder_none_skips_without_building():
    build_calls: list[str] = []

    results, _best_pct, best_label, stopped = _run_decl_candidates(
        _candidates("skip", "run"),
        reorder=lambda perm: None if perm[0] == 0 else "patched",
        build_and_match=lambda patched: build_calls.append(patched) or 91.0,
        baseline=88.0,
    )

    assert stopped is False
    assert build_calls == ["patched"]  # the skipped candidate never compiled
    assert [r["label"] for r in results] == ["run"]
    assert best_label == "run"


def test_build_failure_records_none_and_continues():
    emitted: list[str] = []

    results, best_pct, best_label, stopped = _run_decl_candidates(
        _candidates("broken", "ok"),
        reorder=lambda perm: "patched",
        build_and_match=lambda patched: None if len(emitted) == 0 else 90.0,
        baseline=88.0,
        emit=emitted.append,
    )

    assert [r["pct"] for r in results] == [None, 90.0]
    assert best_label == "ok"
    assert best_pct == 90.0


def test_build_failure_emits_candidate_path_and_first_diagnostic():
    emitted: list[str] = []
    failure = DeclCandidateFailure(
        status="invalid-probe",
        diagnostic="src/melee/mn/sample.c:42: error: undeclared identifier 'x'",
        candidate_path=Path("/tmp/melee-agent-diagnose/failure.c"),
    )

    results, best_pct, best_label, stopped = _run_decl_candidates(
        _candidates("promote table", "ok"),
        reorder=lambda perm: "patched",
        build_and_match=lambda patched: failure if len(emitted) == 0 else 90.0,
        baseline=88.0,
        emit=emitted.append,
    )

    assert stopped is False
    assert results[0] == {
        "label": "promote table",
        "pct": None,
        "delta": None,
        "status": "invalid-probe",
        "candidate_path": "/tmp/melee-agent-diagnose/failure.c",
        "diagnostic": "src/melee/mn/sample.c:42: error: undeclared identifier 'x'",
    }
    assert best_label == "ok"
    assert best_pct == 90.0
    assert any("promote table: invalid-probe" in line for line in emitted)
    assert any(
        "candidate: /tmp/melee-agent-diagnose/failure.c" in line
        for line in emitted
    )
    assert any(
        "first error: src/melee/mn/sample.c:42: error" in line
        for line in emitted
    )


def test_build_and_match_returns_first_compiler_diagnostic(monkeypatch, tmp_path):
    def fake_ninja(cmd, melee_root):
        return (
            subprocess.CompletedProcess(
                cmd,
                1,
                stdout="",
                stderr=(
                    "# File: src/melee/mn/sample.c\n"
                    "# Line: 42\n"
                    "# Error: undeclared identifier 'x'\n"
                ),
            ),
            False,
        )

    monkeypatch.setattr(debug_cli, "_run_ninja_with_no_diag_retry", fake_ninja)

    pct, diagnostic = _build_and_match_with_diagnostic(
        "melee/mn/sample",
        "fn_80000000",
        tmp_path,
    )

    assert pct is None
    assert (
        diagnostic
        == "src/melee/mn/sample.c:42: error: undeclared identifier 'x'"
    )
