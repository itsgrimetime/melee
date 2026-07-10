"""Behavior tests for conservative worktree artifact cleanup."""

from __future__ import annotations

import importlib
import os
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
    (repo / ".gitignore").write_text("build/\n.cache/\n", encoding="utf-8")
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

    (linked / ".gitignore").write_text("build/*.o\n.cache/\n", encoding="utf-8")
    (linked / "build/late.txt").write_text("user owned", encoding="utf-8")
    result = artifacts.cleanup_artifacts(report.candidates, apply=True)
    assert result.removed == ()
    assert result.skipped[0].reason == "contains-nonignored"
    assert (linked / "build").exists()


def test_cleanup_removes_identity_checked_ignored_artifact(tmp_path: Path) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x" * 32)
    report = artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
    )

    result = artifacts.cleanup_artifacts(report.candidates, apply=True, active_commands=[])

    assert result.removed == (linked / "build",)
    assert result.reclaimed_bytes == 32
    assert not (linked / "build").exists()


def test_inspection_rejects_unignored_root_with_ignored_child(tmp_path: Path) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x")
    (linked / ".gitignore").write_text("build/*.o\n.cache/\n", encoding="utf-8")

    candidate = _candidate(
        artifacts.inspect_artifacts(
            [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
        ),
        linked,
        "build",
    )
    assert candidate.eligible is False
    assert "root-not-git-ignored" in candidate.skip_reasons


def test_inspection_rejects_gitlink_candidate_root(tmp_path: Path) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=linked, check=True, capture_output=True, text=True
    ).stdout.strip()
    _run_git(linked, "update-index", "--add", "--cacheinfo", f"160000,{head},build")

    candidate = _candidate(
        artifacts.inspect_artifacts(
            [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
        ),
        linked,
        "build",
    )
    assert candidate.eligible is False
    assert "root-git-tracked" in candidate.skip_reasons


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


def test_cleanup_preserves_replaced_candidate_and_outside_data(
    tmp_path: Path, monkeypatch
) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x")
    report = artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("do not delete", encoding="utf-8")
    original_build = tmp_path / "original-build"
    real_move = artifacts._rename_no_replace
    raced = False

    def replace_before_quarantine(source_fd, source_name, destination_fd, destination_name):
        nonlocal raced
        if source_name == "build" and not raced:
            os.rename(linked / "build", original_build)
            (linked / "build").symlink_to(outside, target_is_directory=True)
            raced = True
        return real_move(source_fd, source_name, destination_fd, destination_name)

    monkeypatch.setattr(artifacts, "_rename_no_replace", replace_before_quarantine)
    result = artifacts.cleanup_artifacts(report.candidates, apply=True, active_commands=[])

    assert raced is True
    assert result.removed == ()
    assert result.skipped[0].reason == "quarantine-child-replaced"
    assert sentinel.read_text(encoding="utf-8") == "do not delete"
    assert (original_build / "obj.o").read_bytes() == b"x"


def test_scan_root_replacement_never_traverses_outside_symlink(
    tmp_path: Path, monkeypatch
) -> None:
    repo, _ = _make_repo_and_linked_worktree(tmp_path)
    scan_root = tmp_path / "scan-root"
    victim = scan_root / "victim"
    victim.mkdir(parents=True)
    outside = tmp_path / "outside-repo"
    outside.mkdir()
    _run_git(outside, "init")
    real_open = artifacts.os.open
    raced = False

    def replace_before_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal raced
        if path == "victim" and dir_fd is not None and not raced:
            victim.rename(scan_root / "victim-original")
            victim.symlink_to(outside, target_is_directory=True)
            raced = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(artifacts.os, "open", replace_before_open)
    discovered = artifacts.discover_worktrees(repo, scan_roots=[scan_root])

    assert raced is True
    assert outside.resolve() not in discovered


def test_cleanup_destination_collision_preserves_candidate_and_sentinel(
    tmp_path: Path, monkeypatch
) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x")
    report = artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
    )
    selected: dict[str, int | str] = {}

    def collide(source_fd, source_name, destination_fd, destination_name):
        if source_name == "build":
            os.mkdir(destination_name, dir_fd=destination_fd)
            child_fd = os.open(destination_name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=destination_fd)
            try:
                sentinel_fd = os.open(
                    "sentinel.txt",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=child_fd,
                )
                try:
                    os.write(sentinel_fd, b"preserve collision")
                finally:
                    os.close(sentinel_fd)
            finally:
                os.close(child_fd)
            selected["fd"] = os.dup(destination_fd)
            selected["name"] = destination_name
            return "destination-exists"
        return "unsupported"

    monkeypatch.setattr(artifacts, "_rename_no_replace", collide, raising=False)
    result = artifacts.cleanup_artifacts(report.candidates, apply=True, active_commands=[])

    assert "fd" in selected
    assert result.removed == ()
    assert result.skipped[0].reason == "quarantine-destination-exists"
    assert (linked / "build/obj.o").read_bytes() == b"x"
    container_fd = selected["fd"]
    assert isinstance(container_fd, int)
    child_fd = os.open(str(selected["name"]), os.O_RDONLY | os.O_DIRECTORY, dir_fd=container_fd)
    try:
        sentinel_fd = os.open("sentinel.txt", os.O_RDONLY, dir_fd=child_fd)
        try:
            assert os.read(sentinel_fd, 64) == b"preserve collision"
        finally:
            os.close(sentinel_fd)
    finally:
        os.close(child_fd)
        os.close(container_fd)


def test_cleanup_skips_when_no_safe_rename_is_available(tmp_path: Path, monkeypatch) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x")
    report = artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
    )
    monkeypatch.setattr(artifacts, "_rename_no_replace", lambda *_: "unsupported")

    result = artifacts.cleanup_artifacts(report.candidates, apply=True, active_commands=[])

    assert result.removed == ()
    assert result.skipped[0].reason == "safe-rename-unavailable"
    assert (linked / "build/obj.o").read_bytes() == b"x"


def test_cleanup_preserves_child_replaced_after_identity_check(
    tmp_path: Path, monkeypatch
) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x")
    report = artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
    )
    real_move = getattr(artifacts, "_rename_no_replace", None)
    selected: dict[str, int | str] = {}

    def replace_child(source_fd, source_name, destination_fd, destination_name):
        if source_name == "candidate" and "fd" not in selected:
            os.rename("candidate", "reviewed", src_dir_fd=source_fd, dst_dir_fd=source_fd)
            os.mkdir("candidate", dir_fd=source_fd)
            replacement_fd = os.open("candidate", os.O_RDONLY | os.O_DIRECTORY, dir_fd=source_fd)
            try:
                sentinel_fd = os.open(
                    "sentinel.txt",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=replacement_fd,
                )
                try:
                    os.write(sentinel_fd, b"preserve replacement")
                finally:
                    os.close(sentinel_fd)
            finally:
                os.close(replacement_fd)
            selected["fd"] = os.dup(source_fd)
            selected["name"] = destination_name
        if real_move is None:
            return "unsupported"
        return real_move(source_fd, source_name, destination_fd, destination_name)

    monkeypatch.setattr(artifacts, "_rename_no_replace", replace_child, raising=False)
    result = artifacts.cleanup_artifacts(report.candidates, apply=True, active_commands=[])

    assert "fd" in selected
    assert result.removed == ()
    assert result.skipped[0].reason == "quarantine-child-replaced"
    container_fd = selected["fd"]
    assert isinstance(container_fd, int)
    replacement_fd = os.open(str(selected["name"]), os.O_RDONLY | os.O_DIRECTORY, dir_fd=container_fd)
    try:
        sentinel_fd = os.open("sentinel.txt", os.O_RDONLY, dir_fd=replacement_fd)
        try:
            assert os.read(sentinel_fd, 64) == b"preserve replacement"
        finally:
            os.close(sentinel_fd)
    finally:
        os.close(replacement_fd)
        os.close(container_fd)


def test_scan_root_child_replaced_before_git_validation_is_skipped(
    tmp_path: Path, monkeypatch
) -> None:
    nonrepo = tmp_path / "nonrepo"
    nonrepo.mkdir()
    scan_root = tmp_path / "scan-root"
    victim = scan_root / "victim"
    victim.mkdir(parents=True)
    _run_git(victim, "init")
    outside = tmp_path / "outside-repo"
    outside.mkdir()
    _run_git(outside, "init")
    victim_stat = victim.stat()
    real_run_git = artifacts._run_git
    raced = False

    def replace_before_git(cwd, args, **kwargs):
        nonlocal raced
        if args == ["rev-parse", "--show-toplevel"] and not raced:
            try:
                cwd_stat = os.stat(cwd)
            except OSError:
                cwd_stat = None
            if cwd_stat is not None and (cwd_stat.st_dev, cwd_stat.st_ino) == (
                victim_stat.st_dev,
                victim_stat.st_ino,
            ):
                victim.rename(scan_root / "victim-original")
                victim.symlink_to(outside, target_is_directory=True)
                raced = True
        return real_run_git(cwd, args, **kwargs)

    monkeypatch.setattr(artifacts, "_run_git", replace_before_git)
    discovered = artifacts.discover_worktrees(nonrepo, scan_roots=[scan_root])

    assert raced is True
    assert outside.resolve() not in discovered
