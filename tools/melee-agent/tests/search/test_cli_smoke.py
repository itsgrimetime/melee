"""Smoke test for `debug search run` CLI.

Uses --dry-compiler so no real mwcc/wibo/SSH is needed.
"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from src.search.cli import _compute_melee_root, _resolve_expected_obj, search_app


def test_compute_melee_root_points_at_repo_root() -> None:
    """Regression guard for the parents[N] off-by-one.

    The computed root must be the melee repo root (contains configure.py and
    src/melee), NOT an ancestor like tools/ — otherwise the non-dry CLI builds
    against tools/build/... and fails for every function.
    """
    root = _compute_melee_root()
    assert root.name == "melee", root
    assert (root / "configure.py").exists(), f"no configure.py under {root}"
    assert (root / "src" / "melee").is_dir(), f"no src/melee under {root}"
    # The buggy parents[3] would land on tools/, which has neither marker.
    assert not (root / "melee-agent").exists(), (
        f"{root} looks like tools/, not the repo root"
    )


def test_search_run_dry(tmp_path: Path) -> None:
    runner = CliRunner()
    seed = tmp_path / "seed.c"
    seed.write_text("int MatToQuat(){return 0;}")
    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "MatToQuat",
            "--unit", "quatlib",
            "--no-remote",
            "--seed", str(seed),
            "--store", str(tmp_path / "store"),
            "--max-iters", "1",
            "--dry-compiler",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "accounting" in result.stdout.lower()


def test_expected_obj_resolves_original_obj_not_current_build_obj(tmp_path: Path) -> None:
    """The scorer must compare candidates against the target/original object.

    build/GALE01/src/<unit>.o is overwritten by the local candidate compile;
    using it as the expected object makes the baseline score as an exact match.
    """

    report = tmp_path / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/ft/ftdynamics",'
        '"functions":[{"name":"ftCo_8009E7B4"}]}]}'
    )

    resolved = _resolve_expected_obj(
        tmp_path,
        "ftCo_8009E7B4",
        "melee/ft/ftdynamics",
    )

    assert resolved == tmp_path / "build" / "GALE01" / "obj" / "melee" / "ft" / "ftdynamics.o"


def test_expected_obj_fallback_uses_original_obj_tree(tmp_path: Path) -> None:
    resolved = _resolve_expected_obj(
        tmp_path,
        "ftCo_8009E7B4",
        "melee/ft/ftdynamics",
    )

    assert resolved == tmp_path / "build" / "GALE01" / "obj" / "melee" / "ft" / "ftdynamics.o"


def test_search_run_missing_permuter_dir_degrades_to_local_only(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftdynamics",
            "--store", str(tmp_path / "store"),
            "--max-iters", "1",
            "--perm-root", str(tmp_path / "missing-decomp-permuter"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "remote producers disabled" in result.stderr
    assert "function dir, compile.sh, settings.toml, target.o" in result.stderr


def test_search_run_remote_progress_goes_to_stderr(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    repo = tmp_path / "repo"
    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/u","functions":[{"name":"f"}]}]}'
    )
    perm_dir = tmp_path / "perm" / "nonmatchings" / "f"
    perm_dir.mkdir(parents=True)
    (perm_dir / "base.c").write_text("int f(void){return 1;}\n")
    (perm_dir / "compile.sh").write_text("#!/bin/sh\nexit 0\n")
    (perm_dir / "settings.toml").write_text("base = \"base.c\"\n")
    (perm_dir / "target.o").write_bytes(b"target")

    class _QuietRemote:
        def __init__(self, melee_root):
            self.stopped = []

        def submit(self, base_dir, function, remote):
            return f"{function}-{remote}-job"

        def fetch(self, job_id):
            return []

        def status(self, job_id):
            return "running"

        def stop(self, job_id):
            self.stopped.append(job_id)

    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: repo)
    monkeypatch.setattr(
        "src.search.adapters.RealRemotePermuterClient",
        _QuietRemote,
    )

    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "f",
            "--unit", "u",
            "--store", str(tmp_path / "store"),
            "--perm-root", str(tmp_path / "perm"),
            "--remotes", "coder3",
            "--max-iters", "2",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["accounting"]["producer_polls"] == 2
    assert summary["accounting"]["budget_exhausted"] is True
    assert "producer-started" in result.stderr
    assert "job=f-coder3-job" in result.stderr
    assert "producer-poll" in result.stderr
    assert "state=running" in result.stderr
    assert "harvested=0" in result.stderr


def test_search_run_partial_remote_start_failure_keeps_healthy_remote(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    repo = tmp_path / "repo"
    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/u","functions":[{"name":"f"}]}]}'
    )
    perm_dir = tmp_path / "perm" / "nonmatchings" / "f"
    perm_dir.mkdir(parents=True)
    (perm_dir / "base.c").write_text("int f(void){return 1;}\n")
    (perm_dir / "compile.sh").write_text("#!/bin/sh\nexit 0\n")
    (perm_dir / "settings.toml").write_text("base = \"base.c\"\n")
    (perm_dir / "target.o").write_bytes(b"target")

    class _PartialRemote:
        def __init__(self, melee_root):
            self.stopped = []

        def submit(self, base_dir, function, remote):
            if remote == "coder1":
                raise RuntimeError("remote preflight failed for coder1: missing toml")
            return f"{function}-{remote}-job"

        def fetch(self, job_id):
            return []

        def status(self, job_id):
            return "running"

        def stop(self, job_id):
            self.stopped.append(job_id)

    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: repo)
    monkeypatch.setattr(
        "src.search.adapters.RealRemotePermuterClient",
        _PartialRemote,
    )

    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "f",
            "--unit", "u",
            "--store", str(tmp_path / "store"),
            "--perm-root", str(tmp_path / "perm"),
            "--remotes", "coder1,coder3",
            "--max-iters", "1",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["accounting"]["producer_started"] == 1
    assert summary["accounting"]["producer_failed"] == 1
    assert summary["accounting"]["producer_failures"] == [
        {
            "producer": "permuter-job",
            "jobs": [],
            "remote": "coder1",
            "detail": "remote preflight failed for coder1: missing toml",
        }
    ]
    assert "producer-start-failed" in result.stderr
    assert "remote=coder1" in result.stderr
    assert "job=f-coder3-job" in result.stderr
