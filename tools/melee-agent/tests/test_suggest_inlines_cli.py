"""CLI tests for debug suggest-inlines."""
from __future__ import annotations

import pathlib
import subprocess


CLI_CWD = pathlib.Path(__file__).parent.parent


def test_suggest_inlines_help() -> None:
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "suggest-inlines", "--help"],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0
    assert "--function" in proc.stdout
    assert "--seed-source" in proc.stdout
    assert "--verify" in proc.stdout
    assert "--apply-best" in proc.stdout


def test_suggest_inlines_rejects_apply_best_without_verify() -> None:
    proc = subprocess.run(
        [
            "python", "-m", "src.cli", "debug", "suggest-inlines",
            "-f", "fn_test",
            "--apply-best",
        ],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode != 0
    assert "--apply-best requires --verify" in proc.stderr


def test_suggest_inlines_help_mentions_threshold_and_keep_failed() -> None:
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "suggest-inlines", "--help"],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0
    assert "--threshold" in proc.stdout
    assert "--keep-failed" in proc.stdout
    assert "--target" in proc.stdout
    assert "--emit-patches" in proc.stdout
    assert "--checkdiff-timeout" in proc.stdout
