"""Behavior tests for conservative worktree artifact cleanup."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

artifacts = importlib.import_module("worktree_doctor.artifacts")


NOW = 2_000_000_000.0


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _make_repo_and_linked_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "tests@example.invalid")
    _run_git(repo, "config", "user.name", "Artifact Tests")
    (repo / ".gitignore").write_text("*.o\n", encoding="utf-8")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _run_git(repo, "add", ".gitignore", "README.md")
    _run_git(repo, "commit", "-m", "fixture")

    linked = tmp_path / "linked"
    _run_git(repo, "worktree", "add", "--detach", str(linked))
    return repo, linked


def _write_ignored_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _track_file(root: Path, relative: str, contents: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    _run_git(root, "add", "--force", relative)


def _candidate(report: artifacts.ArtifactReport, worktree: Path, kind: str) -> artifacts.ArtifactCandidate:
    return next(
        candidate
        for candidate in report.candidates
        if candidate.worktree == worktree.resolve() and candidate.kind == kind
    )


def test_default_discovery_only_uses_registered_worktrees(tmp_path: Path) -> None:
    repo, linked = _make_repo_and_linked_worktree(tmp_path)
    unregistered = tmp_path / "unregistered"
    unregistered.mkdir()

    assert artifacts.discover_worktrees(repo) == (repo.resolve(), linked.resolve())
    assert unregistered.resolve() not in artifacts.discover_worktrees(repo)


def test_inspection_rejects_tracked_and_symlinked_build(tmp_path: Path) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x")
    _track_file(linked, "build/keep.txt", "tracked")
    (linked / "build/link").symlink_to(tmp_path / "outside")

    candidate = _candidate(
        artifacts.inspect_artifacts(
            [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
        ),
        linked,
        "build",
    )
    assert candidate.eligible is False
    assert set(candidate.skip_reasons) >= {"git-tracked", "nested-symlink"}


def test_cleanup_dry_run_then_revalidation_preserves_late_nonignored_file(tmp_path: Path) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x" * 32)
    report = artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
    )
    assert artifacts.cleanup_artifacts(report.candidates, apply=False).planned == (linked / "build",)

    (linked / "build/late.txt").write_text("user owned", encoding="utf-8")
    result = artifacts.cleanup_artifacts(report.candidates, apply=True)
    assert result.removed == ()
    assert result.skipped[0].reason == "contains-nonignored"
    assert (linked / "build").exists()


def test_active_command_and_thresholds_skip_candidate(tmp_path: Path) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x" * 32)

    active = _candidate(
        artifacts.inspect_artifacts(
            [linked],
            min_age_days=0,
            min_bytes=0,
            now=NOW,
            active_commands=[f"ninja -C {linked} build/GALE01/report.json"],
        ),
        linked,
        "build",
    )
    assert active.skip_reasons == ("active-process",)

    small = _candidate(
        artifacts.inspect_artifacts(
            [linked], min_age_days=0, min_bytes=64, now=NOW, active_commands=[]
        ),
        linked,
        "build",
    )
    assert small.skip_reasons == ("below-min-bytes",)


def test_inspection_fails_closed_when_git_metadata_is_symlinked(tmp_path: Path) -> None:
    repo, _ = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(repo / "build/obj.o", b"x")
    real_git_dir = tmp_path / "metadata"
    (repo / ".git").rename(real_git_dir)
    (repo / ".git").symlink_to(real_git_dir, target_is_directory=True)

    candidate = _candidate(
        artifacts.inspect_artifacts(
            [repo], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
        ),
        repo,
        "build",
    )
    assert candidate.eligible is False
    assert "gitdir-symlink" in candidate.skip_reasons
