"""Conservative discovery and cleanup of ignored worktree artifacts.

Only direct ``build`` and ``.cache`` directories in Git worktrees are ever
considered.  The checks deliberately favour a skipped candidate over a risky
deletion: Git, process, filesystem, and symlink uncertainty all make a
candidate ineligible.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

ARTIFACT_DIRS = (Path("build"), Path(".cache"))
DEFAULT_MIN_AGE_DAYS = 7.0
DEFAULT_MIN_BYTES = 1024**3

_GIT_TIMEOUT_SECONDS = 15
_PROCESS_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class ArtifactCandidate:
    worktree: Path
    root: Path
    kind: str
    size_bytes: int
    newest_mtime: float | None
    eligible: bool
    skip_reasons: tuple[str, ...]


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


def discover_worktrees(repo_root: Path, scan_roots: Sequence[Path] = ()) -> tuple[Path, ...]:
    """Return real Git worktrees registered by ``repo_root``, plus safe scans.

    Default discovery is intentionally limited to ``git worktree list``.  A
    scan root is opt-in and only contributes a directory Git itself identifies
    as that directory's top-level worktree; symlinks are never traversed.
    """
    discovered: list[Path] = []
    seen: set[Path] = set()

    repo = _absolute_path(repo_root)
    if _is_real_directory(repo):
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
    """Inspect direct ignored artifact directories without modifying them."""
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
            root = worktree / artifact_dir
            if not _path_exists_without_following(root):
                continue
            candidates.append(
                _inspect_candidate(
                    worktree,
                    root,
                    artifact_dir,
                    min_age_days=min_age_days,
                    min_bytes=min_bytes,
                    now=reference_time,
                    active_commands=commands,
                    process_error=process_error,
                )
            )

    return ArtifactReport(worktrees=tuple(normalized_worktrees), candidates=tuple(candidates))


def cleanup_artifacts(
    candidates: Sequence[ArtifactCandidate],
    *,
    apply: bool,
    active_commands: Sequence[str] | None = None,
) -> CleanupResult:
    """Plan or apply conservative cleanup of inspected artifact candidates.

    ``apply=False`` is purely a plan.  Before every actual removal, the
    candidate is freshly inspected with the same structural, Git, symlink, and
    active-process checks.  A changed artifact is skipped as an additional
    guard against a report becoming stale between planning and deletion.
    """
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
            skipped.append(CleanupSkip(root=root, reason=_first_reason(candidate, "ineligible")))
            continue

        planned.append(root)
        if not apply:
            continue

        if process_error is not None:
            skipped.append(CleanupSkip(root=root, reason=process_error))
            continue

        current, invalid_reason = _revalidate_candidate(candidate, commands)
        if invalid_reason is not None:
            skipped.append(CleanupSkip(root=root, reason=invalid_reason))
            continue
        assert current is not None

        if not current.eligible:
            skipped.append(CleanupSkip(root=root, reason=_first_reason(current, "ineligible")))
            continue

        if (
            current.size_bytes != candidate.size_bytes
            or current.newest_mtime != candidate.newest_mtime
        ):
            skipped.append(CleanupSkip(root=root, reason="artifact-changed"))
            continue

        # Re-check the candidate identity immediately before rmtree.  The
        # preceding inspection has already walked this exact directory without
        # following links; this final lstat closes the ordinary replacement
        # race before delegating deletion to shutil's symlink-safe rmtree.
        if not _is_removal_root(candidate, root):
            skipped.append(CleanupSkip(root=root, reason="invalid-candidate"))
            continue

        try:
            shutil.rmtree(root)
        except OSError:
            skipped.append(CleanupSkip(root=root, reason="cleanup-error"))
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
    root: Path,
    artifact_dir: Path,
    *,
    min_age_days: float,
    min_bytes: int,
    now: float,
    active_commands: Sequence[str],
    process_error: str | None,
) -> ArtifactCandidate:
    worktree = _absolute_path(worktree)
    root = _absolute_path(root)
    kind = artifact_dir.as_posix()
    reasons: list[str] = []

    valid_layout = True
    if not _is_real_directory(worktree):
        _add_reason(reasons, "worktree-symlink" if _is_symlink(worktree) else "worktree-not-directory")
        valid_layout = False
    if root != worktree / artifact_dir:
        _add_reason(reasons, "invalid-candidate")
        valid_layout = False
    if not _is_real_directory(root):
        _add_reason(reasons, "candidate-symlink" if _is_symlink(root) else "candidate-not-directory")
        valid_layout = False

    tree_facts = _walk_regular_files(root) if _is_real_directory(root) else _TreeFacts(0, None, (), ())
    for reason in tree_facts.reasons:
        _add_reason(reasons, reason)

    git_root = _validated_git_toplevel(worktree) if _is_real_directory(worktree) else None
    if not valid_layout:
        pass
    elif git_root is None:
        _add_reason(reasons, "git-error")
    elif (metadata_reason := _git_metadata_reason(worktree)) is not None:
        _add_reason(reasons, metadata_reason)
    else:
        _check_git_ownership(worktree, root, tree_facts.regular_files, reasons)

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
        kind=kind,
        size_bytes=tree_facts.size_bytes,
        newest_mtime=tree_facts.newest_mtime,
        eligible=not reasons,
        skip_reasons=tuple(reasons),
    )


def _revalidate_candidate(
    candidate: ArtifactCandidate,
    active_commands: Sequence[str],
) -> tuple[ArtifactCandidate | None, str | None]:
    if candidate.kind not in {item.as_posix() for item in ARTIFACT_DIRS}:
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


def _is_removal_root(candidate: ArtifactCandidate, root: Path) -> bool:
    if candidate.kind not in {item.as_posix() for item in ARTIFACT_DIRS}:
        return False
    worktree = _absolute_path(candidate.worktree)
    expected = worktree / Path(candidate.kind)
    return root == expected and _is_real_directory(worktree) and _is_real_directory(root)


def _check_git_ownership(
    worktree: Path,
    root: Path,
    files: Sequence[Path],
    reasons: list[str],
) -> None:
    for file_path in files:
        relative = _relative_to_worktree(file_path, worktree)
        if relative is None:
            _add_reason(reasons, "invalid-candidate")
            continue
        tracked = _git_tracked(worktree, relative, reasons)
        if tracked is True:
            _add_reason(reasons, "git-tracked")
            continue
        if tracked is None:
            continue
        if not _git_ignored(worktree, relative, reasons):
            _add_reason(reasons, "contains-nonignored")


def _git_ignored(worktree: Path, relative: Path, reasons: list[str]) -> bool:
    result = _run_git(worktree, ["check-ignore", "--quiet", "--", relative.as_posix()])
    if result is None or result.returncode not in (0, 1):
        _add_reason(reasons, "git-error")
        return False
    return result.returncode == 0


def _git_tracked(worktree: Path, relative: Path, reasons: list[str]) -> bool | None:
    result = _run_git(worktree, ["ls-files", "--error-unmatch", "--", relative.as_posix()])
    if result is None or result.returncode not in (0, 1):
        _add_reason(reasons, "git-error")
        return None
    return result.returncode == 0


def _walk_regular_files(root: Path) -> _TreeFacts:
    size_bytes = 0
    newest_mtime: float | None = None
    files: list[Path] = []
    reasons: list[str] = []
    pending = [root]

    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                sorted_entries = sorted(entries, key=lambda entry: entry.name)
        except OSError:
            _add_reason(reasons, "filesystem-error")
            continue

        for entry in sorted_entries:
            path = Path(entry.path)
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError:
                _add_reason(reasons, "filesystem-error")
                continue

            mode = entry_stat.st_mode
            if stat.S_ISLNK(mode):
                _add_reason(reasons, "nested-symlink")
            elif stat.S_ISDIR(mode):
                pending.append(path)
            elif stat.S_ISREG(mode):
                files.append(path)
                size_bytes += entry_stat.st_size
                newest_mtime = (
                    entry_stat.st_mtime
                    if newest_mtime is None
                    else max(newest_mtime, entry_stat.st_mtime)
                )
            else:
                _add_reason(reasons, "non-regular-entry")

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
    if not _is_real_directory(directory):
        return None
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
    pending = [_absolute_path(scan_root)]
    while pending:
        directory = pending.pop()
        if not _is_real_directory(directory):
            continue
        yield directory
        try:
            with os.scandir(directory) as entries:
                children = sorted(entries, key=lambda entry: entry.name, reverse=True)
        except OSError:
            continue
        for entry in children:
            if entry.name == ".git":
                continue
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError:
                continue
            if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
                pending.append(Path(entry.path))


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


def _path_exists_without_following(path: Path) -> bool:
    try:
        os.lstat(path)
    except OSError:
        return False
    return True


def _is_real_directory(path: Path) -> bool:
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return False
    return stat.S_ISDIR(mode) and not stat.S_ISLNK(mode)


def _is_symlink(path: Path) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


def _relative_to_worktree(path: Path, worktree: Path) -> Path | None:
    try:
        return path.relative_to(worktree)
    except ValueError:
        return None


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _first_reason(candidate: ArtifactCandidate, fallback: str) -> str:
    return candidate.skip_reasons[0] if candidate.skip_reasons else fallback
