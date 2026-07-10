"""Conservative discovery and cleanup of ignored worktree artifacts.

Every directory walk is bound to file descriptors opened with ``O_NOFOLLOW``.
Apply-mode cleanup also binds the reviewed device/inode pair, moves the direct
candidate into a same-parent quarantine, and deletes only after confirming the
quarantined directory still has that identity.
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
import subprocess
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

ARTIFACT_DIRS = (Path("build"), Path(".cache"))
DEFAULT_MIN_AGE_DAYS = 7.0
DEFAULT_MIN_BYTES = 1024**3

_GIT_TIMEOUT_SECONDS = 15
_PROCESS_TIMEOUT_SECONDS = 15
_ARTIFACT_KINDS = frozenset(item.as_posix() for item in ARTIFACT_DIRS)


@dataclass(frozen=True)
class ArtifactCandidate:
    worktree: Path
    root: Path
    kind: str
    size_bytes: int
    newest_mtime: float | None
    eligible: bool
    skip_reasons: tuple[str, ...]
    root_device: int | None = None
    root_inode: int | None = None


@dataclass(frozen=True)
class ArtifactReport:
    worktrees: tuple[Path, ...]
    candidates: tuple[ArtifactCandidate, ...]


@dataclass(frozen=True)
class CleanupSkip:
    root: Path
    reason: str


@dataclass(frozen=True)
class CleanupResult:
    planned: tuple[Path, ...]
    removed: tuple[Path, ...]
    reclaimed_bytes: int
    skipped: tuple[CleanupSkip, ...]


@dataclass(frozen=True)
class _TreeFacts:
    size_bytes: int
    newest_mtime: float | None
    regular_files: tuple[Path, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _DirectoryHandle:
    fd: int
    device: int
    inode: int


def discover_worktrees(repo_root: Path, scan_roots: Sequence[Path] = ()) -> tuple[Path, ...]:
    """Return registered worktrees plus opt-in, descriptor-scanned roots."""
    discovered: list[Path] = []
    seen: set[Path] = set()

    repo = _absolute_path(repo_root)
    result = _run_git(repo, ["worktree", "list", "--porcelain"])
    if result is not None and result.returncode == 0:
        for line in result.stdout.splitlines():
            if not line.startswith("worktree "):
                continue
            registered = _validated_git_toplevel(Path(line.removeprefix("worktree ")))
            if registered is not None:
                _append_unique(discovered, seen, registered)

    for scan_root in scan_roots:
        for directory in _scan_directories(scan_root):
            worktree = _validated_git_toplevel(directory)
            if worktree is not None:
                _append_unique(discovered, seen, worktree)

    return tuple(discovered)


def inspect_artifacts(
    worktrees: Sequence[Path],
    *,
    min_age_days: float,
    min_bytes: int,
    now: float | None = None,
    active_commands: Sequence[str] | None = None,
) -> ArtifactReport:
    """Inspect direct artifact directories without following any symlinks."""
    if min_age_days < 0:
        raise ValueError("min_age_days must be non-negative")
    if min_bytes < 0:
        raise ValueError("min_bytes must be non-negative")

    reference_time = time.time() if now is None else now
    commands, process_error = _active_commands(active_commands)
    normalized_worktrees = _unique_paths(worktrees)
    candidates: list[ArtifactCandidate] = []

    for worktree in normalized_worktrees:
        for artifact_dir in ARTIFACT_DIRS:
            candidate = _inspect_candidate(
                worktree,
                artifact_dir,
                min_age_days=min_age_days,
                min_bytes=min_bytes,
                now=reference_time,
                active_commands=commands,
                process_error=process_error,
            )
            if candidate is not None:
                candidates.append(candidate)

    return ArtifactReport(worktrees=tuple(normalized_worktrees), candidates=tuple(candidates))


def cleanup_artifacts(
    candidates: Sequence[ArtifactCandidate],
    *,
    apply: bool,
    active_commands: Sequence[str] | None = None,
) -> CleanupResult:
    """Plan or apply cleanup, with identity-checked quarantine deletion."""
    planned: list[Path] = []
    removed: list[Path] = []
    skipped: list[CleanupSkip] = []
    reclaimed_bytes = 0
    seen: set[Path] = set()

    commands: tuple[str, ...] = ()
    process_error: str | None = None
    if apply:
        commands, process_error = _active_commands(active_commands)

    for candidate in candidates:
        root = _absolute_path(candidate.root)
        if root in seen:
            continue
        seen.add(root)

        if not candidate.eligible:
            skipped.append(CleanupSkip(root, _first_reason(candidate, "ineligible")))
            continue

        planned.append(root)
        if not apply:
            continue
        if process_error is not None:
            skipped.append(CleanupSkip(root, process_error))
            continue

        current, invalid_reason = _revalidate_candidate(candidate, commands)
        if invalid_reason is not None:
            skipped.append(CleanupSkip(root, invalid_reason))
            continue
        assert current is not None
        if not current.eligible:
            skipped.append(CleanupSkip(root, _first_reason(current, "ineligible")))
            continue
        if not _same_candidate_identity(candidate, current):
            skipped.append(CleanupSkip(root, "replaced-during-cleanup"))
            continue
        if (
            current.size_bytes != candidate.size_bytes
            or current.newest_mtime != candidate.newest_mtime
        ):
            skipped.append(CleanupSkip(root, "artifact-changed"))
            continue

        deletion_reason = _quarantine_and_delete(candidate)
        if deletion_reason is not None:
            skipped.append(CleanupSkip(root, deletion_reason))
            continue
        removed.append(root)
        reclaimed_bytes += current.size_bytes

    return CleanupResult(
        planned=tuple(planned),
        removed=tuple(removed),
        reclaimed_bytes=reclaimed_bytes,
        skipped=tuple(skipped),
    )


def _inspect_candidate(
    worktree: Path,
    artifact_dir: Path,
    *,
    min_age_days: float,
    min_bytes: int,
    now: float,
    active_commands: Sequence[str],
    process_error: str | None,
) -> ArtifactCandidate | None:
    worktree = _absolute_path(worktree)
    root = worktree / artifact_dir
    worktree_handle, _ = _open_directory_path(worktree)
    if worktree_handle is None:
        return None

    try:
        root_handle, root_error = _open_directory_child(worktree_handle.fd, artifact_dir.name)
        if root_error == "missing":
            return None
        if root_handle is None:
            return _ineligible_candidate(
                worktree,
                root,
                artifact_dir,
                _candidate_open_reason(root_error),
            )

        root_device = root_handle.device
        root_inode = root_handle.inode
        tree_facts = _walk_regular_files(root_handle.fd)
    finally:
        os.close(worktree_handle.fd)

    reasons = list(tree_facts.reasons)
    git_root = _validated_git_toplevel(worktree)
    if git_root is None:
        _add_reason(reasons, "git-error")
    elif (metadata_reason := _git_metadata_reason(worktree)) is not None:
        _add_reason(reasons, metadata_reason)
    else:
        _check_git_ownership(worktree, artifact_dir, tree_facts.regular_files, reasons)

    if process_error is not None:
        _add_reason(reasons, process_error)
    elif _has_active_command(worktree, root, active_commands):
        _add_reason(reasons, "active-process")

    if tree_facts.size_bytes < min_bytes:
        _add_reason(reasons, "below-min-bytes")
    if tree_facts.newest_mtime is None:
        _add_reason(reasons, "unknown-age")
    elif now - tree_facts.newest_mtime < min_age_days * 24 * 60 * 60:
        _add_reason(reasons, "below-min-age")

    return ArtifactCandidate(
        worktree=worktree,
        root=root,
        kind=artifact_dir.as_posix(),
        size_bytes=tree_facts.size_bytes,
        newest_mtime=tree_facts.newest_mtime,
        eligible=not reasons,
        skip_reasons=tuple(reasons),
        root_device=root_device,
        root_inode=root_inode,
    )


def _ineligible_candidate(
    worktree: Path,
    root: Path,
    artifact_dir: Path,
    reason: str,
) -> ArtifactCandidate:
    return ArtifactCandidate(
        worktree=worktree,
        root=root,
        kind=artifact_dir.as_posix(),
        size_bytes=0,
        newest_mtime=None,
        eligible=False,
        skip_reasons=(reason,),
    )


def _revalidate_candidate(
    candidate: ArtifactCandidate,
    active_commands: Sequence[str],
) -> tuple[ArtifactCandidate | None, str | None]:
    if candidate.kind not in _ARTIFACT_KINDS:
        return None, "invalid-candidate"
    worktree = _absolute_path(candidate.worktree)
    root = _absolute_path(candidate.root)
    artifact_dir = Path(candidate.kind)
    if root != worktree / artifact_dir:
        return None, "invalid-candidate"

    report = inspect_artifacts(
        [worktree],
        min_age_days=0,
        min_bytes=0,
        active_commands=active_commands,
    )
    current = next((item for item in report.candidates if item.root == root), None)
    if current is None:
        return None, "candidate-missing"
    return current, None


def _quarantine_and_delete(candidate: ArtifactCandidate) -> str | None:
    if candidate.kind not in _ARTIFACT_KINDS or candidate.root_device is None or candidate.root_inode is None:
        return "invalid-candidate"

    worktree = _absolute_path(candidate.worktree)
    root = _absolute_path(candidate.root)
    artifact_name = candidate.kind
    if root != worktree / artifact_name:
        return "invalid-candidate"

    parent_handle, _ = _open_directory_path(worktree)
    if parent_handle is None:
        return "replaced-during-cleanup"
    try:
        current_handle, current_error = _open_directory_child(parent_handle.fd, artifact_name)
        if current_handle is None:
            return "replaced-during-cleanup" if current_error is not None else "cleanup-error"
        try:
            if not _matches_identity(current_handle, candidate.root_device, candidate.root_inode):
                return "replaced-during-cleanup"
        finally:
            os.close(current_handle.fd)

        quarantine = _quarantine_name(parent_handle.fd, artifact_name)
        if quarantine is None:
            return "cleanup-error"
        try:
            os.rename(
                artifact_name,
                quarantine,
                src_dir_fd=parent_handle.fd,
                dst_dir_fd=parent_handle.fd,
            )
        except OSError as exc:
            return "replaced-during-cleanup" if exc.errno in {errno.ENOENT, errno.ENOTDIR} else "cleanup-error"

        quarantined_handle, _ = _open_directory_child(parent_handle.fd, quarantine)
        if quarantined_handle is None:
            _restore_quarantine(parent_handle.fd, artifact_name, quarantine)
            return "replaced-during-cleanup"
        try:
            if not _matches_identity(quarantined_handle, candidate.root_device, candidate.root_inode):
                _restore_quarantine(parent_handle.fd, artifact_name, quarantine)
                return "replaced-during-cleanup"
        finally:
            os.close(quarantined_handle.fd)

        if not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
            _restore_quarantine(parent_handle.fd, artifact_name, quarantine)
            return "cleanup-error"
        try:
            shutil.rmtree(quarantine, dir_fd=parent_handle.fd)
        except OSError:
            _restore_quarantine(parent_handle.fd, artifact_name, quarantine)
            return "cleanup-error"
        return None
    finally:
        os.close(parent_handle.fd)


def _restore_quarantine(parent_fd: int, artifact_name: str, quarantine: str) -> None:
    if not _entry_missing(parent_fd, artifact_name):
        return
    try:
        os.rename(quarantine, artifact_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    except OSError:
        pass


def _quarantine_name(parent_fd: int, artifact_name: str) -> str | None:
    for _ in range(8):
        name = f".{artifact_name}.artifact-quarantine-{uuid4().hex}"
        if _entry_missing(parent_fd, name):
            return name
    return None


def _check_git_ownership(
    worktree: Path,
    artifact_dir: Path,
    files: Sequence[Path],
    reasons: list[str],
) -> None:
    root_tracked = _git_tracked(worktree, artifact_dir, reasons)
    if root_tracked is True:
        _add_reason(reasons, "root-git-tracked")
        return
    if root_tracked is None:
        return

    for file_path in files:
        relative = artifact_dir / file_path
        tracked = _git_tracked(worktree, relative, reasons)
        if tracked is True:
            _add_reason(reasons, "git-tracked")
            continue
        if tracked is None:
            continue
        if not _git_ignored(worktree, relative, reasons):
            _add_reason(reasons, "contains-nonignored")

    if not _git_ignored(worktree, artifact_dir, reasons):
        _add_reason(reasons, "root-not-git-ignored")


def _git_ignored(worktree: Path, relative: Path, reasons: list[str]) -> bool:
    result = _run_git(worktree, ["check-ignore", "--quiet", "--", relative.as_posix()])
    if result is None or result.returncode not in (0, 1):
        _add_reason(reasons, "git-error")
        return False
    return result.returncode == 0


def _git_tracked(worktree: Path, relative: Path, reasons: list[str]) -> bool | None:
    result = _run_git(worktree, ["ls-files", "--error-unmatch", "--stage", "--", relative.as_posix()])
    if result is None or result.returncode not in (0, 1):
        _add_reason(reasons, "git-error")
        return None
    if result.returncode == 1:
        return False
    expected = relative.as_posix()
    return any(line.rpartition("\t")[2] == expected for line in result.stdout.splitlines())


def _walk_regular_files(root_fd: int) -> _TreeFacts:
    size_bytes = 0
    newest_mtime: float | None = None
    files: list[Path] = []
    reasons: list[str] = []
    pending: list[tuple[int, Path]] = [(root_fd, Path())]

    try:
        while pending:
            directory_fd, relative_directory = pending.pop()
            try:
                try:
                    with os.scandir(directory_fd) as entries:
                        directory_entries = sorted(entries, key=lambda entry: entry.name)
                except OSError:
                    _add_reason(reasons, "filesystem-error")
                    continue

                for entry in directory_entries:
                    try:
                        entry_stat = os.stat(entry.name, dir_fd=directory_fd, follow_symlinks=False)
                    except OSError:
                        _add_reason(reasons, "filesystem-error")
                        continue

                    mode = entry_stat.st_mode
                    relative_path = relative_directory / entry.name
                    if stat.S_ISLNK(mode):
                        _add_reason(reasons, "nested-symlink")
                    elif stat.S_ISDIR(mode):
                        child, child_error = _open_directory_child(directory_fd, entry.name)
                        if child is None:
                            _add_reason(
                                reasons,
                                "nested-symlink" if child_error == "symlink" else "filesystem-error",
                            )
                            continue
                        pending.append((child.fd, relative_path))
                    elif stat.S_ISREG(mode):
                        files.append(relative_path)
                        size_bytes += entry_stat.st_size
                        newest_mtime = (
                            entry_stat.st_mtime
                            if newest_mtime is None
                            else max(newest_mtime, entry_stat.st_mtime)
                        )
                    else:
                        _add_reason(reasons, "non-regular-entry")
            finally:
                os.close(directory_fd)
    finally:
        for directory_fd, _ in pending:
            os.close(directory_fd)

    return _TreeFacts(size_bytes, newest_mtime, tuple(files), tuple(reasons))


def _active_commands(active_commands: Sequence[str] | None) -> tuple[tuple[str, ...], str | None]:
    if active_commands is not None:
        return tuple(str(command) for command in active_commands), None
    try:
        result = subprocess.run(
            ["ps", "-axo", "command="],
            capture_output=True,
            text=True,
            timeout=_PROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return (), "process-query-failed"
    if result.returncode != 0:
        return (), "process-query-failed"
    return tuple(result.stdout.splitlines()), None


def _has_active_command(worktree: Path, root: Path, commands: Sequence[str]) -> bool:
    worktree_path = str(worktree.resolve(strict=False))
    root_path = str(root.resolve(strict=False))
    return any(worktree_path in command or root_path in command for command in commands)


def _validated_git_toplevel(directory: Path) -> Path | None:
    directory = _absolute_path(directory)
    result = _run_git(directory, ["rev-parse", "--show-toplevel"])
    if result is None or result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        expected = directory.resolve(strict=True)
        reported = Path(result.stdout.strip()).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return expected if reported == expected else None


def _git_metadata_reason(worktree: Path) -> str | None:
    try:
        mode = os.lstat(worktree / ".git").st_mode
    except OSError:
        return "gitdir-missing"
    if stat.S_ISLNK(mode):
        return "gitdir-symlink"
    if stat.S_ISDIR(mode):
        return "main-worktree"
    if not stat.S_ISREG(mode):
        return "gitdir-invalid"
    return None


def _scan_directories(scan_root: Path) -> Iterator[Path]:
    root = _absolute_path(scan_root)
    root_handle, _ = _open_directory_path(root)
    if root_handle is None:
        return
    pending: list[tuple[int, Path]] = [(root_handle.fd, root)]

    try:
        while pending:
            directory_fd, directory = pending.pop()
            try:
                try:
                    with os.scandir(directory_fd) as entries:
                        directory_entries = sorted(entries, key=lambda entry: entry.name, reverse=True)
                except OSError:
                    continue

                for entry in directory_entries:
                    if entry.name == ".git":
                        continue
                    try:
                        entry_stat = os.stat(entry.name, dir_fd=directory_fd, follow_symlinks=False)
                    except OSError:
                        continue
                    if not stat.S_ISDIR(entry_stat.st_mode) or stat.S_ISLNK(entry_stat.st_mode):
                        continue
                    child, _ = _open_directory_child(directory_fd, entry.name)
                    if child is not None:
                        pending.append((child.fd, directory / entry.name))
                yield directory
            finally:
                os.close(directory_fd)
    finally:
        for directory_fd, _ in pending:
            os.close(directory_fd)


def _open_directory_path(path: Path) -> tuple[_DirectoryHandle | None, str | None]:
    flags = _directory_open_flags()
    if flags is None:
        return None, "filesystem-error"
    try:
        before = os.lstat(path)
    except OSError as exc:
        return None, _open_error_reason(exc)
    if stat.S_ISLNK(before.st_mode):
        return None, "symlink"
    if not stat.S_ISDIR(before.st_mode):
        return None, "not-directory"
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        return None, _open_error_reason(exc)
    try:
        after = os.fstat(fd)
        if not stat.S_ISDIR(after.st_mode) or not _same_stat_identity(before, after):
            return None, "replaced"
        return _DirectoryHandle(fd, after.st_dev, after.st_ino), None
    except OSError:
        return None, "filesystem-error"
    finally:
        if "after" not in locals() or not stat.S_ISDIR(after.st_mode) or not _same_stat_identity(before, after):
            os.close(fd)


def _open_directory_child(parent_fd: int, name: str) -> tuple[_DirectoryHandle | None, str | None]:
    flags = _directory_open_flags()
    if flags is None:
        return None, "filesystem-error"
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        return None, _open_error_reason(exc)
    if stat.S_ISLNK(before.st_mode):
        return None, "symlink"
    if not stat.S_ISDIR(before.st_mode):
        return None, "not-directory"
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        return None, _open_error_reason(exc)
    try:
        after = os.fstat(fd)
        if not stat.S_ISDIR(after.st_mode) or not _same_stat_identity(before, after):
            return None, "replaced"
        return _DirectoryHandle(fd, after.st_dev, after.st_ino), None
    except OSError:
        return None, "filesystem-error"
    finally:
        if "after" not in locals() or not stat.S_ISDIR(after.st_mode) or not _same_stat_identity(before, after):
            os.close(fd)


def _directory_open_flags() -> int | None:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        return None
    return os.O_RDONLY | directory | nofollow | getattr(os, "O_CLOEXEC", 0)


def _candidate_open_reason(reason: str | None) -> str:
    if reason == "symlink":
        return "candidate-symlink"
    if reason == "not-directory":
        return "candidate-not-directory"
    if reason == "replaced":
        return "replaced-during-inspection"
    return "filesystem-error"


def _open_error_reason(exc: OSError) -> str:
    if exc.errno in {errno.ENOENT, errno.ENOTDIR}:
        return "missing"
    if exc.errno == errno.ELOOP:
        return "symlink"
    return "filesystem-error"


def _same_candidate_identity(first: ArtifactCandidate, second: ArtifactCandidate) -> bool:
    return (
        first.root_device is not None
        and first.root_inode is not None
        and first.root_device == second.root_device
        and first.root_inode == second.root_inode
    )


def _matches_identity(handle: _DirectoryHandle, device: int, inode: int) -> bool:
    return handle.device == device and handle.inode == inode


def _same_stat_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _entry_missing(parent_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _run_git(cwd: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _unique_paths(paths: Sequence[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        normalized = _absolute_path(path)
        if normalized not in seen:
            _append_unique(unique, seen, normalized)
    return unique


def _append_unique(paths: list[Path], seen: set[Path], path: Path) -> None:
    if path not in seen:
        paths.append(path)
        seen.add(path)


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(Path(path).expanduser()))


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _first_reason(candidate: ArtifactCandidate, fallback: str) -> str:
    return candidate.skip_reasons[0] if candidate.skip_reasons else fallback
