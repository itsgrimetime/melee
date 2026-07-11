"""Behavior tests for conservative worktree artifact cleanup."""

from __future__ import annotations

import importlib
import json
import os
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

artifacts = importlib.import_module("worktree_doctor.artifacts")
assets = importlib.import_module("worktree_doctor.assets")
doctor = importlib.import_module("worktree_doctor")


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


def _asset_source(root: Path) -> Path:
    compiler = root / "build" / "compilers" / "GC" / "1.2.5n" / "mwcceppc.exe"
    compiler.parent.mkdir(parents=True)
    compiler.write_bytes(b"compiler")
    wibo = root / "build" / "tools" / "wibo"
    wibo.parent.mkdir(parents=True)
    wibo.write_bytes(b"wibo")
    table_typer = root / "tools" / "table-typer" / "table-typer"
    table_typer.parent.mkdir(parents=True)
    table_typer.write_bytes(b"table-typer")
    return root


def _candidate(report: artifacts.ArtifactReport, worktree: Path, kind: str) -> artifacts.ArtifactCandidate:
    return next(
        candidate
        for candidate in report.candidates
        if candidate.worktree == worktree.resolve() and candidate.kind == kind
    )


def test_artifacts_cli_report_json_is_read_only(monkeypatch, capsys) -> None:
    candidate = artifacts.ArtifactCandidate(
        worktree=Path("/repo"),
        root=Path("/repo/build"),
        kind="build",
        size_bytes=32,
        newest_mtime=NOW - 8 * 24 * 60 * 60,
        eligible=True,
        skip_reasons=(),
    )
    report = artifacts.ArtifactReport(worktrees=(Path("/repo"),), candidates=(candidate,))
    monkeypatch.setattr(doctor.time, "time", lambda: NOW)
    monkeypatch.setattr(artifacts, "discover_worktrees", lambda root, scan_roots=(): (Path("/repo"),))
    monkeypatch.setattr(artifacts, "inspect_artifacts", lambda *args, **kwargs: report)
    monkeypatch.setattr(
        artifacts,
        "cleanup_artifacts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("report must not clean up")),
    )

    assert doctor.main(["artifacts", "report", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "report"
    assert payload["schema_version"] == 1
    assert payload["candidates"] == [
        {
            "age_seconds": 8 * 24 * 60 * 60,
            "worktree": "/repo",
            "root": "/repo/build",
            "kind": "build",
            "size_bytes": 32,
            "newest_mtime": NOW - 8 * 24 * 60 * 60,
            "eligible": True,
            "skip_reasons": [],
        }
    ]
    assert payload["planned"] == []
    assert payload["removed"] == []
    assert payload["reclaimed_bytes"] == 0
    assert payload["skipped"] == []


def test_artifacts_cli_cleanup_requires_apply(monkeypatch, capsys) -> None:
    candidate = artifacts.ArtifactCandidate(
        worktree=Path("/repo"),
        root=Path("/repo/build"),
        kind="build",
        size_bytes=32,
        newest_mtime=NOW - 8 * 24 * 60 * 60,
        eligible=True,
        skip_reasons=(),
    )
    report = artifacts.ArtifactReport(worktrees=(Path("/repo"),), candidates=(candidate,))
    result = artifacts.CleanupResult(
        planned=(Path("/repo/build"),),
        removed=(Path("/repo/build"),),
        reclaimed_bytes=32,
        skipped=(),
    )
    inspection_protection: list[tuple[Path, ...]] = []
    cleanup_protection: list[tuple[bool, tuple[Path, ...]]] = []
    monkeypatch.setattr(artifacts, "discover_worktrees", lambda root, scan_roots=(): (Path("/repo"),))

    def inspect(*args, **kwargs):
        inspection_protection.append(tuple(kwargs["protected_worktrees"]))
        return report

    def cleanup(candidates, *, apply, protected_worktrees):
        cleanup_protection.append((apply, tuple(protected_worktrees)))
        return result

    monkeypatch.setattr(artifacts, "inspect_artifacts", inspect)
    monkeypatch.setattr(
        artifacts,
        "cleanup_artifacts",
        cleanup,
    )

    assert doctor.main(["artifacts", "cleanup", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "dry-run"
    assert doctor.main(["artifacts", "cleanup", "--apply", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "cleanup"
    assert inspection_protection == [(doctor.ROOT,), (doctor.ROOT,)]
    assert cleanup_protection == [(False, (doctor.ROOT,)), (True, (doctor.ROOT,))]


def test_artifacts_cli_dispatches_process_arguments(monkeypatch, capsys) -> None:
    report = artifacts.ArtifactReport(worktrees=(), candidates=())
    monkeypatch.setattr(sys, "argv", ["worktree-doctor.py", "artifacts", "report", "--json"])
    monkeypatch.setattr(artifacts, "discover_worktrees", lambda root, scan_roots=(): ())
    monkeypatch.setattr(artifacts, "inspect_artifacts", lambda *args, **kwargs: report)

    assert doctor.main() == 0

    assert json.loads(capsys.readouterr().out)["mode"] == "report"


def test_artifacts_cli_help_includes_required_prefix(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["worktree-doctor.py"])

    with pytest.raises(SystemExit) as error:
        doctor.main(["artifacts", "report", "--help"])

    assert error.value.code == 0
    assert "usage: worktree-doctor.py artifacts report" in capsys.readouterr().out


def test_artifacts_cli_preserves_legacy_banner(monkeypatch, capsys) -> None:
    monkeypatch.setattr(doctor, "banner_line", lambda root: "legacy banner")

    assert doctor.main(["--banner"]) == 0

    assert capsys.readouterr().out == "legacy banner\n"


def test_default_discovery_only_uses_registered_worktrees(tmp_path: Path) -> None:
    repo, linked = _make_repo_and_linked_worktree(tmp_path)
    unregistered = tmp_path / "unregistered"
    unregistered.mkdir()

    assert artifacts.discover_worktrees(repo) == (repo.resolve(), linked.resolve())
    assert unregistered.resolve() not in artifacts.discover_worktrees(repo)


def test_scan_root_only_validates_git_markers_and_prunes_repo_contents(
    tmp_path: Path, monkeypatch
) -> None:
    nonrepo = tmp_path / "nonrepo"
    nonrepo.mkdir()
    scan_root = tmp_path / "scan-root"
    repo = scan_root / "arbitrary" / "depth" / "repo"
    repo.mkdir(parents=True)
    _run_git(repo, "init")

    nested_repo = repo / "large" / "tree" / "nested-repo"
    nested_repo.mkdir(parents=True)
    _run_git(nested_repo, "init")
    for index in range(64):
        (repo / "large" / "tree" / f"directory-{index}" / "child").mkdir(parents=True)

    real_run_git = artifacts._run_git
    validated: list[Path] = []

    def record_git(cwd, args, **kwargs):
        if args == ["rev-parse", "--show-toplevel"]:
            validated.append(Path(cwd))
        return real_run_git(cwd, args, **kwargs)

    monkeypatch.setattr(artifacts, "_run_git", record_git)

    discovered = artifacts.discover_worktrees(nonrepo, scan_roots=[scan_root])

    assert discovered == (repo.resolve(),)
    assert validated == [repo.resolve()]
    assert nested_repo.resolve() not in discovered


def test_git_ownership_batches_large_candidate_queries(tmp_path: Path, monkeypatch) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    for index in range(63):
        _write_ignored_file(linked / "build" / f"object-{index}.o", b"x")
    _track_file(linked, "build/tracked\nobject.o", "tracked")

    real_run_git = artifacts._run_git
    ownership_calls: list[tuple[list[str], str | None]] = []

    def record_git(cwd, args, **kwargs):
        if args and args[0] in {"ls-files", "check-ignore"}:
            ownership_calls.append((list(args), kwargs.get("input_text")))
        return real_run_git(cwd, args, **kwargs)

    monkeypatch.setattr(artifacts, "_run_git", record_git)

    candidate = _candidate(
        artifacts.inspect_artifacts(
            [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
        ),
        linked,
        "build",
    )

    ls_files_calls = [call for call in ownership_calls if call[0][0] == "ls-files"]
    check_ignore_calls = [call for call in ownership_calls if call[0][0] == "check-ignore"]
    assert len(ls_files_calls) == 1
    assert len(check_ignore_calls) == 1
    assert "git-tracked" in candidate.skip_reasons
    assert ls_files_calls[0][0] == ["ls-files", "--stage", "-z", "--", "build"]
    assert check_ignore_calls[0][0] == ["check-ignore", "--stdin", "-z"]
    ignore_input = check_ignore_calls[0][1]
    assert ignore_input is not None
    ignore_paths = ignore_input.split("\0")
    assert ignore_paths[0] == "build/"
    assert ignore_paths[-1] == ""
    assert set(ignore_paths[1:-1]) == {f"build/object-{index}.o" for index in range(63)}


def test_current_worktree_is_reported_but_never_eligible_for_cleanup(tmp_path: Path) -> None:
    repo, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(repo / "build/primary.o", b"primary")
    _write_ignored_file(linked / "build/linked.o", b"linked")

    report = artifacts.inspect_artifacts(
        [repo, linked],
        min_age_days=0,
        min_bytes=0,
        now=NOW,
        active_commands=[],
        protected_worktrees=[linked],
    )

    assert report.worktrees == (repo.resolve(), linked.resolve())
    primary = _candidate(report, repo, "build")
    assert primary.eligible is False
    assert primary.skip_reasons == ("main-worktree",)
    current = _candidate(report, linked, "build")
    assert current.eligible is False
    assert current.skip_reasons == ("protected-worktree",)

    # Revalidation must preserve the protection even if an untrusted caller
    # supplies a forged eligible candidate from the current checkout.
    forged_current = replace(current, eligible=True, skip_reasons=())
    revalidated, invalid_reason = artifacts._revalidate_candidate(
        forged_current,
        (),
        (linked,),
    )
    assert invalid_reason is None
    assert revalidated is not None
    assert revalidated.skip_reasons == ("protected-worktree",)

    result = artifacts.cleanup_artifacts(
        [forged_current],
        apply=True,
        active_commands=[],
        protected_worktrees=[linked],
    )

    assert result.planned == ()
    assert result.removed == ()
    assert result.skipped[0].reason == "protected-worktree"
    assert (linked / "build" / "linked.o").read_bytes() == b"linked"


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


def test_cleanup_revalidates_ownership_immediately_before_quarantine(
    tmp_path: Path, monkeypatch
) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x")
    report = artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
    )
    real_quarantine = artifacts._quarantine_and_delete
    injected = False

    def add_nonignored_file_after_apply_revalidation(*args, **kwargs):
        nonlocal injected
        assert injected is False
        # The candidate was ignored when reviewed; make the new file
        # nonignored in the gap immediately before its quarantine move.
        (linked / ".gitignore").write_text("build/*.o\n.cache/\n", encoding="utf-8")
        (linked / "build/late.txt").write_text("user owned", encoding="utf-8")
        injected = True
        return real_quarantine(*args, **kwargs)

    monkeypatch.setattr(artifacts, "_quarantine_and_delete", add_nonignored_file_after_apply_revalidation)
    result = artifacts.cleanup_artifacts(report.candidates, apply=True, active_commands=[])

    assert injected is True
    assert result.removed == ()
    assert result.skipped[0].reason == "contains-nonignored"
    assert (linked / "build/late.txt").read_text(encoding="utf-8") == "user owned"


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
    assert (linked / "build").is_symlink()
    assert (linked / "build").resolve() == outside.resolve()
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
    assert (linked / "build/sentinel.txt").read_bytes() == b"preserve replacement"
    container_fd = selected["fd"]
    assert isinstance(container_fd, int)
    replacement_fd = os.open("reviewed", os.O_RDONLY | os.O_DIRECTORY, dir_fd=container_fd)
    try:
        sentinel_fd = os.open("obj.o", os.O_RDONLY, dir_fd=replacement_fd)
        try:
            assert os.read(sentinel_fd, 64) == b"x"
        finally:
            os.close(sentinel_fd)
    finally:
        os.close(replacement_fd)
        os.close(container_fd)


def test_cleanup_preserves_replacement_before_expected_rmtree(
    tmp_path: Path, monkeypatch
) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x")
    report = artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
    )
    real_rmtree_expected = getattr(artifacts, "_rmtree_expected", None)
    real_move = artifacts._rename_no_replace
    selected: dict[str, int | str] = {}

    def capture_removal_name(source_fd, source_name, destination_fd, destination_name):
        if source_name == "candidate" and "name" not in selected:
            selected["fd"] = os.dup(source_fd)
            selected["name"] = destination_name
        return real_move(source_fd, source_name, destination_fd, destination_name)

    def replace_before_rmtree(directory_fd, expected_stat):
        if "replaced" not in selected:
            container_fd = selected["fd"]
            assert isinstance(container_fd, int)
            name = str(selected["name"])
            os.rename(name, "reviewed", src_dir_fd=container_fd, dst_dir_fd=container_fd)
            os.mkdir(name, dir_fd=container_fd)
            replacement_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=container_fd)
            try:
                sentinel_fd = os.open(
                    "sentinel.txt",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=replacement_fd,
                )
                try:
                    os.write(sentinel_fd, b"preserve before rmtree")
                finally:
                    os.close(sentinel_fd)
            finally:
                os.close(replacement_fd)
            selected["replaced"] = "yes"
        if real_rmtree_expected is None:
            return "quarantine-child-replaced"
        return real_rmtree_expected(directory_fd, expected_stat)

    monkeypatch.setattr(artifacts, "_rename_no_replace", capture_removal_name)
    monkeypatch.setattr(artifacts, "_rmtree_expected", replace_before_rmtree, raising=False)
    result = artifacts.cleanup_artifacts(report.candidates, apply=True, active_commands=[])

    assert "fd" in selected
    assert result.removed == ()
    assert result.skipped[0].reason == "quarantine-child-replaced"
    assert (linked / "build/sentinel.txt").read_bytes() == b"preserve before rmtree"
    container_fd = selected["fd"]
    assert isinstance(container_fd, int)
    reviewed_fd = os.open("reviewed", os.O_RDONLY | os.O_DIRECTORY, dir_fd=container_fd)
    try:
        assert os.listdir(reviewed_fd) == []
    finally:
        os.close(reviewed_fd)
        os.close(container_fd)


def test_cleanup_preserves_replacement_after_expected_rmtree_verification(
    tmp_path: Path, monkeypatch
) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x")
    report = artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
    )
    real_move = artifacts._rename_no_replace
    real_rmtree = artifacts.shutil.rmtree
    selected: dict[str, int | str] = {}

    def capture_removal_name(source_fd, source_name, destination_fd, destination_name):
        if source_name == "candidate" and "name" not in selected:
            selected["fd"] = os.dup(source_fd)
            selected["name"] = destination_name
        return real_move(source_fd, source_name, destination_fd, destination_name)

    def replace_after_helper_verification(path, *args, dir_fd=None, **kwargs):
        if "name" in selected and "replaced" not in selected and path in {
            ".",
            str(selected["name"]),
        }:
            container_fd = selected["fd"]
            assert isinstance(container_fd, int)
            name = str(selected["name"])
            os.rename(name, "reviewed", src_dir_fd=container_fd, dst_dir_fd=container_fd)
            os.mkdir(name, dir_fd=container_fd)
            replacement_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=container_fd)
            try:
                sentinel_fd = os.open(
                    "sentinel.txt",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=replacement_fd,
                )
                try:
                    os.write(sentinel_fd, b"preserve after verification")
                finally:
                    os.close(sentinel_fd)
            finally:
                os.close(replacement_fd)
            selected["replaced"] = "yes"
        return real_rmtree(path, *args, dir_fd=dir_fd, **kwargs)

    monkeypatch.setattr(artifacts, "_rename_no_replace", capture_removal_name)
    monkeypatch.setattr(artifacts.shutil, "rmtree", replace_after_helper_verification)
    monkeypatch.setattr(
        artifacts.shutil.rmtree,
        "avoids_symlink_attacks",
        getattr(real_rmtree, "avoids_symlink_attacks", False),
        raising=False,
    )
    result = artifacts.cleanup_artifacts(report.candidates, apply=True, active_commands=[])

    assert selected["replaced"] == "yes"
    assert result.removed == ()
    assert result.skipped[0].reason == "quarantine-child-replaced"
    assert (linked / "build/sentinel.txt").read_bytes() == b"preserve after verification"
    container_fd = selected["fd"]
    assert isinstance(container_fd, int)
    os.close(container_fd)


def test_cleanup_retains_replaced_quarantine_container(tmp_path: Path, monkeypatch) -> None:
    _, linked = _make_repo_and_linked_worktree(tmp_path)
    _write_ignored_file(linked / "build/obj.o", b"x")
    report = artifacts.inspect_artifacts(
        [linked], min_age_days=0, min_bytes=0, now=NOW, active_commands=[]
    )
    real_create_container = artifacts._create_quarantine_container
    selected: dict[str, int | str] = {}

    def replace_opened_container(parent_fd, artifact_name):
        container = real_create_container(parent_fd, artifact_name)
        assert container is not None
        reviewed_name = f"{container.name}.reviewed"
        os.rename(container.name, reviewed_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.mkdir(container.name, dir_fd=parent_fd)
        selected["fd"] = os.dup(parent_fd)
        selected["name"] = container.name
        return container

    monkeypatch.setattr(artifacts, "_create_quarantine_container", replace_opened_container)
    result = artifacts.cleanup_artifacts(report.candidates, apply=True, active_commands=[])

    assert result.removed == (linked / "build",)
    assert result.skipped[0].reason == "quarantine-container-retained"
    container_fd = selected["fd"]
    assert isinstance(container_fd, int)
    try:
        replacement_stat = os.stat(str(selected["name"]), dir_fd=container_fd, follow_symlinks=False)
        assert stat.S_ISDIR(replacement_stat.st_mode)
    finally:
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


def test_seed_and_hydrate_uses_file_level_symlinks(tmp_path: Path) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()

    assert assets.seed_shared_assets(source, cache).status == "seeded"
    result = assets.hydrate_shared_assets(target, cache)
    assert result.status == "hydrated"
    consumer = target / "build" / "compilers" / "GC" / "1.2.5n" / "mwcceppc.exe"
    assert consumer.is_symlink()
    assert consumer.read_bytes() == b"compiler"
    assert consumer in result.linked
    consumer.unlink()
    assert (
        cache / "files" / "build" / "compilers" / "GC" / "1.2.5n" / "mwcceppc.exe"
    ).read_bytes() == b"compiler"


def test_hydrate_preserves_real_file_and_rejects_bad_digest(tmp_path: Path) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()
    assert assets.seed_shared_assets(source, cache).status == "seeded"
    existing = target / "build" / "tools" / "wibo"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"local")
    result = assets.hydrate_shared_assets(target, cache)
    assert "build/tools/wibo" in result.skipped
    assert existing.read_bytes() == b"local"

    manifest_path = cache / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["sha256"] = "0" * 64
    manifest_path.chmod(0o644)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert assets.hydrate_shared_assets(target, cache).status == "invalid-cache"


def test_seed_rejects_symlinked_asset_source(tmp_path: Path) -> None:
    source = _asset_source(tmp_path / "source")
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside")
    (source / "build" / "tools" / "unsafe").symlink_to(outside)
    cache = tmp_path / "cache"

    result = assets.seed_shared_assets(source, cache)

    assert result.status == "invalid-source"
    assert not cache.exists()


def test_seed_makes_cache_payload_files_and_directories_read_only(tmp_path: Path) -> None:
    cache = tmp_path / "cache"

    assert assets.seed_shared_assets(_asset_source(tmp_path / "source"), cache).status == "seeded"

    payload = cache / "files" / "build" / "tools" / "wibo"
    assert payload.stat().st_mode & 0o222 == 0
    assert (cache / "manifest.json").stat().st_mode & 0o222 == 0
    for directory in (cache, cache / "files", cache / "files" / "build"):
        assert directory.stat().st_mode & 0o222 == 0


def test_hydrate_rejects_writable_manifest_before_target_mutation(tmp_path: Path) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()
    assert assets.seed_shared_assets(source, cache).status == "seeded"
    (cache / "manifest.json").chmod(0o644)

    result = assets.hydrate_shared_assets(target, cache)

    assert result.status == "invalid-cache"
    assert not (target / "build").exists()


def test_hydrate_rejects_writable_cache_directories_before_target_mutation(
    tmp_path: Path,
) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()
    assert assets.seed_shared_assets(source, cache).status == "seeded"
    (cache / "files").chmod(0o755)

    result = assets.hydrate_shared_assets(target, cache)

    assert result.status == "invalid-cache"
    assert not (target / "build").exists()


def test_seed_preserves_a_valid_different_cache(tmp_path: Path) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    assert assets.seed_shared_assets(source, cache).status == "seeded"
    (source / "build" / "tools" / "wibo").write_bytes(b"new-source")

    result = assets.seed_shared_assets(source, cache)

    assert result.status == "cache-exists"
    assert (cache / "files" / "build" / "tools" / "wibo").read_bytes() == b"wibo"


def test_hydrate_rejects_manifest_platform_and_path_tampering_before_mutation(
    tmp_path: Path,
) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()
    assert assets.seed_shared_assets(source, cache).status == "seeded"
    manifest_path = cache / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["platform"]["machine"] = "other-machine"
    manifest["files"][0]["path"] = "../outside"
    manifest_path.chmod(0o644)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = assets.hydrate_shared_assets(target, cache)

    assert result.status == "invalid-cache"
    assert not (target / "build").exists()


def test_hydrate_seeds_missing_cache_only_with_explicit_source(tmp_path: Path) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()

    assert assets.hydrate_shared_assets(target, cache).status == "cache-missing"
    result = assets.hydrate_shared_assets(target, cache, asset_source=source)

    assert result.status == "hydrated"
    assert (target / "build" / "tools" / "wibo").is_symlink()


def test_hydrate_preserves_a_mismatched_consumer_symlink(tmp_path: Path) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()
    assert assets.seed_shared_assets(source, cache).status == "seeded"
    consumer = target / "build" / "tools" / "wibo"
    consumer.parent.mkdir(parents=True)
    other = tmp_path / "other"
    other.write_bytes(b"other")
    consumer.symlink_to(os.path.relpath(other, start=consumer.parent))

    result = assets.hydrate_shared_assets(target, cache)

    assert "build/tools/wibo" in result.skipped
    assert consumer.is_symlink()
    assert consumer.read_bytes() == b"other"


def test_hydrate_rejects_cache_root_replacement_before_target_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()
    assert assets.seed_shared_assets(source, cache).status == "seeded"
    reviewed = tmp_path / "cache-reviewed"
    real_ensure_parent = assets._ensure_real_target_parent
    replaced = False

    def replace_cache_before_target_mutation(*args, **kwargs):
        nonlocal replaced
        if not replaced:
            cache.chmod(0o755)
            cache.rename(reviewed)
            cache.mkdir()
            replaced = True
        return real_ensure_parent(*args, **kwargs)

    monkeypatch.setattr(assets, "_ensure_real_target_parent", replace_cache_before_target_mutation)
    result = assets.hydrate_shared_assets(target, cache)

    assert replaced is True
    assert result.status == "invalid-cache"
    assert not (target / "build").exists()


def test_hydrate_rejects_cache_replacement_between_validation_and_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    source = _asset_source(tmp_path / "source")
    replacement_source = _asset_source(tmp_path / "replacement-source")
    (replacement_source / "build" / "compilers" / "GC" / "1.2.5n" / "mwcceppc.exe").write_bytes(
        b"replacement"
    )
    cache = tmp_path / "cache"
    replacement = tmp_path / "replacement-cache"
    target = tmp_path / "target"
    target.mkdir()
    assert assets.seed_shared_assets(source, cache).status == "seeded"
    assert assets.seed_shared_assets(replacement_source, replacement).status == "seeded"
    reviewed = tmp_path / "cache-reviewed"
    real_validate = assets._validated_cache
    armed = False
    replaced = False

    def replace_after_validation(cache_root, *args, **kwargs):
        nonlocal replaced
        result = real_validate(cache_root, *args, **kwargs)
        if armed and cache_root == cache and not replaced:
            cache.chmod(0o755)
            replacement.chmod(0o755)
            cache.rename(reviewed)
            replacement.rename(cache)
            replaced = True
        return result

    monkeypatch.setattr(assets, "_validated_cache", replace_after_validation)
    armed = True
    result = assets.hydrate_shared_assets(target, cache)

    assert replaced is True
    assert result.status == "invalid-cache"
    assert not (target / "build").exists()


def test_hydrate_retains_its_link_when_cache_changes_after_link_creation(
    tmp_path: Path, monkeypatch
) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()
    assert assets.seed_shared_assets(source, cache).status == "seeded"
    reviewed = tmp_path / "cache-reviewed"
    real_symlink = assets.os.symlink
    replaced = False

    def replace_cache_after_link(link_target, link_name, *, dir_fd=None):
        nonlocal replaced
        real_symlink(link_target, link_name, dir_fd=dir_fd)
        if not replaced:
            cache.chmod(0o755)
            cache.rename(reviewed)
            cache.mkdir()
            replaced = True

    monkeypatch.setattr(assets.os, "symlink", replace_cache_after_link)
    result = assets.hydrate_shared_assets(target, cache)

    consumer = target / "build" / "compilers" / "GC" / "1.2.5n" / "mwcceppc.exe"
    assert replaced is True
    assert result.status == "invalid-cache"
    assert consumer.is_symlink()


def test_hydrate_retains_earlier_links_when_cache_changes_after_second_link(
    tmp_path: Path, monkeypatch
) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()
    assert assets.seed_shared_assets(source, cache).status == "seeded"
    reviewed = tmp_path / "cache-reviewed"
    real_symlink = assets.os.symlink
    links_created = 0

    def replace_cache_after_second_link(link_target, link_name, *, dir_fd=None):
        nonlocal links_created
        real_symlink(link_target, link_name, dir_fd=dir_fd)
        links_created += 1
        if links_created == 2:
            cache.chmod(0o755)
            cache.rename(reviewed)
            cache.mkdir()

    monkeypatch.setattr(assets.os, "symlink", replace_cache_after_second_link)
    result = assets.hydrate_shared_assets(target, cache)

    compiler = target / "build" / "compilers" / "GC" / "1.2.5n" / "mwcceppc.exe"
    wibo = target / "build" / "tools" / "wibo"
    assert links_created == 2
    assert result.status == "invalid-cache"
    assert compiler.is_symlink()
    assert wibo.is_symlink()


def test_hydrate_rejects_prior_payload_replacement_at_final_verification(
    tmp_path: Path, monkeypatch
) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()
    assert assets.seed_shared_assets(source, cache).status == "seeded"
    original = cache / "files" / "build" / "compilers" / "GC" / "1.2.5n" / "mwcceppc.exe"
    real_symlink = assets.os.symlink
    links_created = 0

    def replace_prior_payload_after_last_link(link_target, link_name, *, dir_fd=None):
        nonlocal links_created
        real_symlink(link_target, link_name, dir_fd=dir_fd)
        links_created += 1
        if links_created == 3:
            original.parent.chmod(0o755)
            replacement = original.with_name("mwcceppc.exe.replacement")
            replacement.write_bytes(b"replacement")
            os.replace(replacement, original)
            original.parent.chmod(0o555)

    monkeypatch.setattr(assets.os, "symlink", replace_prior_payload_after_last_link)
    result = assets.hydrate_shared_assets(target, cache)

    assert links_created == 3
    assert result.status == "invalid-cache"


def test_rollback_retains_consumer_replaced_after_identity_check(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    consumer = target / "consumer"
    expected_target = "../cache/file"
    consumer.symlink_to(expected_target)
    target_fd = assets._open_directory(target)
    assert target_fd is not None
    expected_identity = assets._symlink_identity(target_fd, "consumer", expected_target)
    assert expected_identity is not None
    real_identity = assets._symlink_identity
    replaced = False

    def replace_after_identity_check(parent_fd, name, link_target):
        nonlocal replaced
        identity = real_identity(parent_fd, name, link_target)
        if identity == expected_identity and not replaced:
            os.unlink(name, dir_fd=parent_fd)
            replacement_fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
                dir_fd=parent_fd,
            )
            os.close(replacement_fd)
            replaced = True
        return identity

    monkeypatch.setattr(assets, "_symlink_identity", replace_after_identity_check)
    try:
        removed = assets._unlink_expected_symlink(
            target_fd, "consumer", expected_target, expected_identity
        )
    finally:
        os.close(target_fd)

    assert replaced is True
    assert removed is False
    assert consumer.exists()
    assert not consumer.is_symlink()


def test_seed_never_follows_staging_path_replaced_after_creation(
    tmp_path: Path, monkeypatch
) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    outside = tmp_path / "outside"
    outside.mkdir()
    real_make_staging = assets._make_staging_directory

    def replace_staging_after_creation(cache_root):
        staging = real_make_staging(cache_root)
        assert staging is not None
        staging_path = staging if isinstance(staging, Path) else cache_root.parent / staging.name
        staging_path.rename(staging_path.with_name(f"{staging_path.name}.reviewed"))
        staging_path.symlink_to(outside, target_is_directory=True)
        return staging

    monkeypatch.setattr(assets, "_make_staging_directory", replace_staging_after_creation)
    result = assets.seed_shared_assets(source, cache)

    assert list(outside.iterdir()) == []
    assert result.status == "cache-unavailable"


def test_seed_rejects_valid_staging_directory_replacement_before_publish(
    tmp_path: Path, monkeypatch
) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()
    replacement = tmp_path / "replacement-cache"
    assert assets.seed_shared_assets(source, replacement).status == "seeded"
    real_rename = assets._rename_no_replace
    replaced = False

    def replace_staging_before_rename(parent_fd, source_name, destination_name):
        nonlocal replaced
        if source_name.startswith(".cache.staging-") and not replaced:
            os.rename(source_name, f"{source_name}.reviewed", src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            replacement.chmod(0o755)
            os.rename(replacement, source_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            replaced = True
        return real_rename(parent_fd, source_name, destination_name)

    monkeypatch.setattr(assets, "_rename_no_replace", replace_staging_before_rename)
    result = assets.seed_shared_assets(source, cache)

    assert replaced is True
    assert result.status == "cache-unavailable"
    assert cache.exists()
    assert not cache.is_symlink()
    assert assets.hydrate_shared_assets(target, cache).status == "invalid-cache"
    assert not (target / "build").exists()


def test_seed_rejects_staging_symlink_replacement_before_publish(
    tmp_path: Path, monkeypatch
) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    real_rename = assets._rename_no_replace
    replaced = False

    def replace_staging_before_rename(parent_fd, source_name, destination_name):
        nonlocal replaced
        if source_name.startswith(".cache.staging-") and not replaced:
            os.rename(source_name, f"{source_name}.reviewed", src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            os.symlink(outside, source_name, dir_fd=parent_fd)
            replaced = True
        return real_rename(parent_fd, source_name, destination_name)

    monkeypatch.setattr(assets, "_rename_no_replace", replace_staging_before_rename)
    result = assets.seed_shared_assets(source, cache)

    assert replaced is True
    assert result.status == "cache-unavailable"
    assert cache.is_symlink()
    assert list(outside.iterdir()) == []
    assert assets.hydrate_shared_assets(target, cache).status == "invalid-cache"
    assert not (target / "build").exists()


def test_seed_retains_replaced_staging_entry(tmp_path: Path, monkeypatch) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    replacement: dict[str, Path] = {}

    def replace_staging_before_publish(staging, cache_root: Path, expected_identity) -> str:
        staging_path = cache_root.parent / staging.name
        staging_path.rename(staging_path.with_name(f"{staging.name}.reviewed"))
        staging_path.mkdir()
        sentinel = staging_path / "sentinel.txt"
        sentinel.write_text("preserve replacement", encoding="utf-8")
        replacement["sentinel"] = sentinel
        return "cache-exists"

    monkeypatch.setattr(assets, "_publish_staging", replace_staging_before_publish)
    result = assets.seed_shared_assets(source, cache)

    assert result.status == "cache-exists"
    assert replacement["sentinel"].read_text(encoding="utf-8") == "preserve replacement"


def test_assets_cli_seeds_and_hydrates_with_explicit_paths(tmp_path: Path, capsys) -> None:
    source = _asset_source(tmp_path / "source")
    cache = tmp_path / "cache"
    target = tmp_path / "target"
    target.mkdir()

    assert doctor.main(["assets", "seed", "--source", str(source), "--cache-root", str(cache)]) == 0
    assert "status: seeded" in capsys.readouterr().out

    original_root = doctor.ROOT
    try:
        doctor.ROOT = target
        assert doctor.main(["assets", "hydrate", "--cache-root", str(cache)]) == 0
    finally:
        doctor.ROOT = original_root
    assert "status: hydrated" in capsys.readouterr().out
    assert (target / "tools" / "table-typer" / "table-typer").is_symlink()
