"""Strict discovery and policy classification for registered Git worktrees."""

from __future__ import annotations

import fcntl
import os
import re
import selectors
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import assets
from .retained_evidence import RetainedEvidenceSnapshot, discover_retained_evidence


@dataclass(frozen=True)
class RegisteredWorktree:
    path: Path
    head: str
    branch: str | None
    detached: bool
    locked_reason: str | None
    prunable_reason: str | None


class WorktreeParseError(ValueError):
    """Raised when registered-worktree discovery cannot be trusted."""


@dataclass(frozen=True)
class IgnoredEntry:
    relative: Path
    kind: str
    device: int
    inode: int
    size: int
    mtime: float

    @classmethod
    def from_path(cls, worktree: Path, relative: Path) -> "IgnoredEntry":
        entry_stat = (worktree / relative).lstat()
        if stat.S_ISREG(entry_stat.st_mode):
            kind = "file"
        elif stat.S_ISDIR(entry_stat.st_mode):
            kind = "directory"
        elif stat.S_ISLNK(entry_stat.st_mode):
            kind = "symlink"
        else:
            kind = "unsupported"
        return cls(
            relative=relative,
            kind=kind,
            device=entry_stat.st_dev,
            inode=entry_stat.st_ino,
            size=entry_stat.st_size,
            mtime=entry_stat.st_mtime,
        )


@dataclass(frozen=True)
class ProcessSnapshot:
    paths: tuple[tuple[int, Path], ...]
    commands: tuple[tuple[int, str], ...]
    errors: tuple[str, ...]

    def active_pids(self, canonical: Path, reported: Path) -> tuple[int, ...]:
        canonical_text = os.fspath(canonical)
        reported_text = os.fspath(reported)
        active = {
            pid
            for pid, path in self.paths
            if path == canonical or path.is_relative_to(canonical)
        }
        active.update(
            pid
            for pid, command in self.commands
            if canonical_text in command or reported_text in command
        )
        return tuple(sorted(active))


@dataclass(frozen=True)
class WorktreeRecord:
    path: Path
    canonical_path: Path
    path_device: int | None
    path_inode: int | None
    head: str
    branch: str | None
    detached: bool
    locked_reason: str | None
    prunable_reason: str | None
    branch_head: str | None
    estimated_disk_bytes: int
    last_activity: float | None
    dirty: bool | None
    ignored_entries: tuple[IgnoredEntry, ...]
    unapproved_ignored_paths: tuple[Path, ...]
    retained_evidence: RetainedEvidenceSnapshot
    asset_snapshot: assets.HydratedAssetSnapshot | None
    dol_identity: tuple[int, int, int, int, str] | None
    active_pids: tuple[int, ...]
    merged_into_master: bool | None
    eligible: bool
    skip_reasons: tuple[str, ...]


@dataclass(frozen=True)
class WorktreeReport:
    repo_root: Path
    common_git_dir: Path
    current_worktree: Path
    min_idle_hours: float
    records: tuple[WorktreeRecord, ...]
    global_errors: tuple[str, ...]


@dataclass(frozen=True)
class RetirementCandidate:
    path: Path
    branch: str
    head: str
    estimated_disk_bytes: int
    last_activity: float


@dataclass(frozen=True)
class RetirementSkip:
    path: Path
    branch: str
    head: str
    phase: str
    reason: str


@dataclass(frozen=True)
class RetirementRemoval:
    path: Path
    branch: str
    head: str
    branch_head_after: str
    estimated_reclaimed_bytes: int


@dataclass(frozen=True)
class RetirementError:
    reason: str
    detail: str


@dataclass(frozen=True)
class RetirementResult:
    planned: tuple[RetirementCandidate, ...]
    removed: tuple[RetirementRemoval, ...]
    skipped: tuple[RetirementSkip, ...]
    errors: tuple[RetirementError, ...]


_OBJECT_HEX_LENGTHS = {b"sha1": 40, b"sha256": 64}
_HEX_OID = re.compile(rb"[0-9a-fA-F]+\Z")
_BRANCH_PREFIX = b"refs/heads/"
_INVALID_REF_BYTES = frozenset(b" ~^:?*[\\")
_AGENT_BRANCH_PREFIXES = ("codex/", "claude/", "wall/")
_IGNORED_MAX_BYTES = 32 * 1024 * 1024
_IGNORED_MAX_ENTRIES = 500_000
_PROCESS_STDOUT_MAX = 8 * 1024 * 1024
_PROCESS_STDERR_MAX = 1024 * 1024
_PROCESS_RECORD_MAX = 200_000
_PROCESS_TIMEOUT = 15.0
_SENSITIVE_COMPONENTS = frozenset({"log", "logs", "dump", "dumps"})
_DENIED_COMPONENTS = frozenset(
    {
        ".env",
        ".venv",
        "venv",
        ".claude",
        ".codex",
        "candidate",
        "candidates",
        "run",
        "runs",
    }
)
_CACHE_COMPONENTS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", "htmlcov"})
_ROOT_GENERATED = frozenset(
    {
        "build.ninja",
        ".ninja_deps",
        ".ninja_log",
        "compile_commands.json",
        "objdiff.json",
        "ctx.c",
        "ctx_includes.h",
    }
)


def _git_failure(command: str, stderr: bytes) -> WorktreeParseError:
    detail = os.fsdecode(stderr).strip()
    suffix = f": {detail}" if detail else ""
    return WorktreeParseError(f"git {command} failed{suffix}")


def repository_object_hex_length(repo_root: Path) -> int:
    """Return the one supported OID width reported by *repo_root*."""

    args = [
        "git",
        "-C",
        os.fspath(repo_root),
        "rev-parse",
        "--show-object-format",
    ]
    try:
        result = subprocess.run(args, capture_output=True)
    except OSError as error:
        raise WorktreeParseError(f"git object format query failed: {error}") from error
    if result.returncode != 0:
        raise _git_failure("object format query", result.stderr)

    object_format = result.stdout.rstrip(b"\r\n")
    try:
        return _OBJECT_HEX_LENGTHS[object_format]
    except KeyError as error:
        rendered = os.fsdecode(object_format)
        raise WorktreeParseError(
            f"unsupported repository object format: {rendered!r}"
        ) from error


def _decode_field_value(value: bytes) -> str:
    return os.fsdecode(value)


def _is_valid_git_ref(value: bytes) -> bool:
    """Match ``git check-ref-format`` rules without decoding ref bytes."""

    if (
        value == b"@"
        or value.startswith(b"/")
        or value.endswith((b"/", b"."))
        or b"//" in value
        or b".." in value
        or b"@{" in value
    ):
        return False

    components = value.split(b"/")
    if len(components) < 2 or any(
        not component
        or component.startswith(b".")
        or component.endswith(b".lock")
        for component in components
    ):
        return False

    return not any(
        byte < 0x20 or byte == 0x7F or byte in _INVALID_REF_BYTES for byte in value
    )


def _parse_record(fields: list[bytes], *, object_hex_length: int) -> RegisteredWorktree:
    if not fields or not fields[0].startswith(b"worktree "):
        raise WorktreeParseError("record must begin with a worktree field")

    path_bytes = fields[0][len(b"worktree ") :]
    if not path_bytes:
        raise WorktreeParseError("worktree path is empty")
    path = Path(os.fsdecode(path_bytes))
    if not path.is_absolute():
        raise WorktreeParseError("worktree path is not absolute")

    head: str | None = None
    branch: str | None = None
    detached = False
    locked_reason: str | None = None
    prunable_reason: str | None = None
    seen = {"worktree"}

    for field in fields[1:]:
        if field.startswith(b"HEAD "):
            name = "HEAD"
            oid = field[len(b"HEAD ") :]
            if not oid:
                raise WorktreeParseError("HEAD value is empty")
            if name in seen:
                raise WorktreeParseError("duplicate HEAD field")
            seen.add(name)
            if len(oid) != object_hex_length or _HEX_OID.fullmatch(oid) is None:
                raise WorktreeParseError(
                    f"HEAD is not a {object_hex_length}-digit hexadecimal OID"
                )
            head = oid.decode("ascii")
        elif field.startswith(b"branch "):
            name = "branch"
            value = field[len(b"branch ") :]
            if name in seen:
                raise WorktreeParseError("duplicate branch field")
            seen.add(name)
            if not value.startswith(_BRANCH_PREFIX) or value == _BRANCH_PREFIX:
                raise WorktreeParseError("branch field is not a refs/heads name")
            if not _is_valid_git_ref(value):
                raise WorktreeParseError("branch field is not a valid Git ref")
            branch = _decode_field_value(value[len(_BRANCH_PREFIX) :])
        elif field == b"detached":
            name = "detached"
            if name in seen:
                raise WorktreeParseError("duplicate detached field")
            seen.add(name)
            detached = True
        elif field == b"locked" or field.startswith(b"locked "):
            name = "locked"
            if name in seen:
                raise WorktreeParseError("duplicate locked field")
            seen.add(name)
            value = b"" if field == b"locked" else field[len(b"locked ") :]
            if field != b"locked" and not value:
                raise WorktreeParseError("locked reason is empty")
            locked_reason = _decode_field_value(value)
        elif field == b"prunable" or field.startswith(b"prunable "):
            name = "prunable"
            if name in seen:
                raise WorktreeParseError("duplicate prunable field")
            seen.add(name)
            value = b"" if field == b"prunable" else field[len(b"prunable ") :]
            if field != b"prunable" and not value:
                raise WorktreeParseError("prunable reason is empty")
            prunable_reason = _decode_field_value(value)
        elif field.startswith(b"worktree "):
            raise WorktreeParseError("duplicate worktree field")
        else:
            raise WorktreeParseError(
                f"unknown or malformed worktree field: {os.fsdecode(field)!r}"
            )

    if head is None:
        raise WorktreeParseError("record is missing HEAD")
    if branch is not None and detached:
        raise WorktreeParseError("record contains both branch and detached")
    if branch is None and not detached:
        raise WorktreeParseError("record contains neither branch nor detached")

    return RegisteredWorktree(
        path=path,
        head=head,
        branch=branch,
        detached=detached,
        locked_reason=locked_reason,
        prunable_reason=prunable_reason,
    )


def parse_worktree_porcelain(
    data: bytes, *, object_hex_length: int
) -> tuple[RegisteredWorktree, ...]:
    """Strictly parse ``git worktree list --porcelain -z`` output."""

    if object_hex_length not in _OBJECT_HEX_LENGTHS.values():
        raise WorktreeParseError(
            f"unsupported repository object length: {object_hex_length}"
        )
    if not data:
        raise WorktreeParseError("worktree porcelain output is empty")
    if not data.endswith(b"\0\0"):
        raise WorktreeParseError("worktree porcelain is missing final record separator")

    records: list[RegisteredWorktree] = []
    fields: list[bytes] = []
    # Strip only the field terminator after the final empty record field. Each
    # remaining empty token therefore has exactly one meaning: end of record.
    for token in data[:-1].split(b"\0"):
        if token:
            fields.append(token)
            continue
        if not fields:
            raise WorktreeParseError("worktree porcelain contains an empty record")
        records.append(_parse_record(fields, object_hex_length=object_hex_length))
        fields = []
    if fields:
        raise WorktreeParseError("worktree porcelain contains trailing record data")
    if not records:
        raise WorktreeParseError("worktree porcelain contains no records")

    canonical_paths: set[Path] = set()
    for item in records:
        try:
            canonical = item.path.resolve(strict=False)
        except OSError as error:
            raise WorktreeParseError(
                f"cannot canonicalize worktree path {item.path!s}: {error}"
            ) from error
        if canonical in canonical_paths:
            raise WorktreeParseError(
                f"duplicate canonical path in worktree porcelain: {canonical}"
            )
        canonical_paths.add(canonical)
    return tuple(records)


def discover_registered_worktrees(repo_root: Path) -> tuple[RegisteredWorktree, ...]:
    """Discover all worktrees registered in *repo_root*, failing closed."""

    object_hex_length = repository_object_hex_length(repo_root)
    args = [
        "git",
        "-C",
        os.fspath(repo_root),
        "worktree",
        "list",
        "--porcelain",
        "-z",
    ]
    try:
        result = subprocess.run(args, capture_output=True)
    except OSError as error:
        raise WorktreeParseError(f"git worktree list failed: {error}") from error
    if result.returncode != 0:
        raise _git_failure("worktree list", result.stderr)
    return parse_worktree_porcelain(
        result.stdout, object_hex_length=object_hex_length
    )


def _canonical(path: Path) -> Path:
    return path.resolve(strict=False)


def _is_beneath(path: Path, root: Path) -> bool:
    return path != root and path.is_relative_to(root)


def policy_skip_reasons(
    record: RegisteredWorktree,
    *,
    main_worktree: Path,
    current_worktree: Path,
    agent_roots: Sequence[Path],
) -> tuple[str, ...]:
    """Return stable policy reasons which prevent retiring *record*."""

    try:
        path = _canonical(record.path)
        main = _canonical(main_worktree)
        current = _canonical(current_worktree)
        roots = tuple(_canonical(root) for root in agent_roots)
    except OSError:
        return ("invalid-worktree-path",)

    reasons: list[str] = []
    if path == main:
        reasons.append("main-worktree")
    if path == current:
        reasons.append("current-worktree")
    if not any(_is_beneath(path, root) for root in roots):
        reasons.append("outside-agent-roots")

    protected_pr_branch = (
        record.branch is not None and record.branch.startswith("pr/")
    )
    protected_pr_path = any(
        part == "melee-pr" or part.startswith("pr-") for part in path.parts
    )
    protected_wip_branch = (
        record.branch is not None and record.branch.startswith("wip/")
    )
    protected = protected_pr_branch or protected_pr_path or protected_wip_branch

    if record.branch is None or record.detached:
        reasons.append("detached-head")
    elif not protected and not record.branch.startswith(_AGENT_BRANCH_PREFIXES):
        reasons.append("unrecognized-agent-branch")
    if protected_pr_branch:
        reasons.append("protected-pr-branch")
    if protected_pr_path:
        reasons.append("protected-pr-path")
    if protected_wip_branch:
        reasons.append("protected-wip-branch")

    if record.locked_reason is not None:
        reasons.append("locked-worktree")
    if record.prunable_reason is not None:
        reasons.append("prunable-worktree")
    return tuple(reasons)


def common_git_dir(repo_root: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", os.fspath(repo_root), "rev-parse", "--git-common-dir"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise WorktreeParseError("git common directory query failed")
    value = Path(os.fsdecode(result.stdout.rstrip(b"\r\n")))
    if not value.is_absolute():
        value = repo_root / value
    return value.resolve(strict=False)


def _parse_ignored_inventory(
    worktree: Path, data: bytes
) -> tuple[tuple[IgnoredEntry, ...], tuple[str, ...]]:
    if len(data) > _IGNORED_MAX_BYTES or (data and not data.endswith(b"\0")):
        return (), ("ignored-inventory-invalid",)
    if not data:
        return (), ()
    raw_entries = data[:-1].split(b"\0")
    if len(raw_entries) > _IGNORED_MAX_ENTRIES or any(not item for item in raw_entries):
        return (), ("ignored-inventory-invalid",)

    seen: set[Path] = set()
    entries: list[IgnoredEntry] = []
    try:
        root_fd = os.open(
            worktree,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        return (), ("ignored-inventory-invalid",)
    try:
        for raw in raw_entries:
            if os.path.isabs(raw) or os.path.splitdrive(raw)[0]:
                return (), ("ignored-inventory-invalid",)
            raw_components = raw.split(os.fsencode(os.sep))
            if os.altsep is not None:
                alternate = os.fsencode(os.altsep)
                raw_components = [
                    component
                    for group in raw_components
                    for component in group.split(alternate)
                ]
            if any(component in {b"", b".", b".."} for component in raw_components):
                return (), ("ignored-inventory-invalid",)
            normalized = Path(os.fsdecode(raw))
            if normalized in seen:
                return (), ("ignored-inventory-invalid",)
            seen.add(normalized)
            try:
                entry = _ignored_entry_at(root_fd, normalized)
            except OSError:
                return (), ("ignored-inventory-invalid",)
            if entry.kind == "unsupported":
                return (), ("ignored-inventory-invalid",)
            entries.append(entry)
    finally:
        os.close(root_fd)
    return (
        tuple(sorted(entries, key=lambda item: item.relative.as_posix())),
        (),
    )


def _ignored_entry_at(root_fd: int, relative: Path) -> IgnoredEntry:
    current_fd = os.dup(root_fd)
    try:
        for component in relative.parts[:-1]:
            child_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = child_fd
        entry_stat = os.stat(
            relative.name, dir_fd=current_fd, follow_symlinks=False
        )
    finally:
        os.close(current_fd)
    if stat.S_ISREG(entry_stat.st_mode):
        kind = "file"
    elif stat.S_ISDIR(entry_stat.st_mode):
        kind = "directory"
    elif stat.S_ISLNK(entry_stat.st_mode):
        kind = "symlink"
    else:
        kind = "unsupported"
    return IgnoredEntry(
        relative,
        kind,
        entry_stat.st_dev,
        entry_stat.st_ino,
        entry_stat.st_size,
        entry_stat.st_mtime,
    )


def _ignored_entries_match(worktree: Path, entries: Sequence[IgnoredEntry]) -> bool:
    try:
        root_fd = os.open(
            worktree,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        return False
    try:
        for expected in entries:
            try:
                current = _ignored_entry_at(root_fd, expected.relative)
            except OSError:
                return False
            if current != expected:
                return False
        return True
    finally:
        os.close(root_fd)


def _sensitive(relative: Path) -> bool:
    if relative == Path(".ninja_log"):
        return False
    return any(part in _SENSITIVE_COMPONENTS for part in relative.parts) or any(
        part.endswith((".log", ".dump")) for part in relative.parts
    )


def _is_disposable_ignored(relative: Path, kind: str) -> bool:
    if _sensitive(relative) or any(
        part in _DENIED_COMPONENTS for part in relative.parts
    ):
        return False
    if relative.as_posix() in _ROOT_GENERATED and len(relative.parts) == 1:
        return kind == "file"
    if relative == Path("tools/melee-agent/.coverage"):
        return kind == "file"
    if any(part in _CACHE_COMPONENTS for part in relative.parts):
        return True
    return bool(relative.parts and relative.parts[0] in {"build", ".cache"})


def _is_under(relative: Path, root: Path) -> bool:
    return relative == root or relative.is_relative_to(root)


def _open_absolute_nofollow(path: Path, *, directory: bool) -> int | None:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_flag is None:
        return None
    normalized = Path(os.path.abspath(os.fspath(path)))
    if not normalized.is_absolute() or not normalized.parts:
        return None
    try:
        current_fd = os.open(
            normalized.anchor,
            os.O_RDONLY | directory_flag | nofollow | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError:
        return None
    try:
        components = normalized.parts[1:]
        for index, component in enumerate(components):
            is_final = index == len(components) - 1
            flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
            if not is_final or directory:
                flags |= directory_flag
            child_fd = os.open(component, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = child_fd
        opened = os.fstat(current_fd)
        expected_kind = stat.S_ISDIR if directory else stat.S_ISREG
        if not expected_kind(opened.st_mode):
            os.close(current_fd)
            return None
        return current_fd
    except OSError:
        os.close(current_fd)
        return None


def _open_relative_directory_nofollow(parent_fd: int, parts: Sequence[str]) -> int | None:
    current_fd = os.dup(parent_fd)
    try:
        for component in parts:
            child_fd = os.open(
                component,
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except OSError:
        os.close(current_fd)
        return None


def _open_link_target_nofollow(parent_fd: int, link_text: str) -> int | None:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if (
        nofollow is None
        or directory_flag is None
        or not link_text
        or link_text.endswith(os.sep)
    ):
        return None
    try:
        if os.path.isabs(link_text):
            current_fd = os.open(
                os.path.abspath(os.sep),
                os.O_RDONLY
                | directory_flag
                | nofollow
                | getattr(os, "O_CLOEXEC", 0),
            )
        else:
            current_fd = os.dup(parent_fd)
    except OSError:
        return None
    try:
        components = [
            component
            for component in link_text.split(os.sep)
            if component not in {"", "."}
        ]
        if not components:
            os.close(current_fd)
            return None
        for index, component in enumerate(components):
            is_final = index == len(components) - 1
            flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
            if not is_final:
                flags |= directory_flag
            child_fd = os.open(component, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = child_fd
        opened = os.fstat(current_fd)
        if not stat.S_ISREG(opened.st_mode):
            os.close(current_fd)
            return None
        return current_fd
    except OSError:
        os.close(current_fd)
        return None


def _inspect_dol(worktree: Path) -> tuple[tuple[int, int, int, int, str] | None, bool]:
    relative = Path("orig/GALE01/sys/main.dol")
    worktree_fd = _open_absolute_nofollow(worktree, directory=True)
    if worktree_fd is None:
        return None, False
    parent_fd = _open_relative_directory_nofollow(worktree_fd, relative.parts[:-1])
    os.close(worktree_fd)
    if parent_fd is None:
        return None, False
    try:
        try:
            link_stat = os.stat(
                relative.name, dir_fd=parent_fd, follow_symlinks=False
            )
            if not stat.S_ISLNK(link_stat.st_mode):
                return None, False
            link_text = os.readlink(relative.name, dir_fd=parent_fd)
            link_after = os.stat(
                relative.name, dir_fd=parent_fd, follow_symlinks=False
            )
        except OSError:
            return None, False
        if (
            link_stat.st_dev,
            link_stat.st_ino,
            link_stat.st_size,
            link_stat.st_mtime_ns,
        ) != (
            link_after.st_dev,
            link_after.st_ino,
            link_after.st_size,
            link_after.st_mtime_ns,
        ):
            return None, False

        target_fd = _open_link_target_nofollow(parent_fd, link_text)
        if target_fd is None:
            return None, False
        try:
            target_stat = os.fstat(target_fd)
            from . import DOL_CANDIDATES

            for candidate in DOL_CANDIDATES:
                if not candidate.is_absolute():
                    continue
                candidate_fd = _open_absolute_nofollow(candidate, directory=False)
                if candidate_fd is None:
                    continue
                try:
                    candidate_stat = os.fstat(candidate_fd)
                finally:
                    os.close(candidate_fd)
                if (target_stat.st_dev, target_stat.st_ino) == (
                    candidate_stat.st_dev,
                    candidate_stat.st_ino,
                ):
                    return (
                        link_stat.st_dev,
                        link_stat.st_ino,
                        target_stat.st_dev,
                        target_stat.st_ino,
                        link_text,
                    ), True
        finally:
            os.close(target_fd)
        return None, False
    finally:
        os.close(parent_fd)


def _classify_ignored(
    entries: Sequence[IgnoredEntry],
    retained: RetainedEvidenceSnapshot,
    asset_snapshot: assets.HydratedAssetSnapshot | None,
    dol_identity: tuple[int, int, int, int, str] | None,
) -> tuple[tuple[Path, ...], bool]:
    retained_roots = (
        Path("build/diagnostics"),
        Path("build/diagnostics/runs"),
        Path("build/runs"),
        *(manifest[0].parent.parent for manifest in retained.manifests),
    )
    asset_paths = set()
    if asset_snapshot is not None:
        asset_paths.update(link.relative for link in asset_snapshot.links)
        asset_paths.update(assets.ASSET_PATHS[:-1])
    unapproved: list[Path] = []
    has_retained = False
    owned_manifests = {item[0] for item in retained.manifests}
    for entry in entries:
        relative = entry.relative
        if relative.name == "manifest.json" and relative not in owned_manifests:
            unapproved.append(relative)
            continue
        if any(_is_under(relative, root) for root in retained_roots):
            has_retained = True
            continue
        if relative in asset_paths:
            continue
        if relative == Path("orig/GALE01/sys/main.dol") and dol_identity is not None:
            continue
        if not _is_disposable_ignored(relative, entry.kind):
            unapproved.append(relative)
    return tuple(unapproved), has_retained


def _walk_tree(path: Path) -> tuple[int, float, tuple[str, ...]]:
    total = 0
    newest = 0.0

    def walk(directory_fd: int) -> None:
        nonlocal total, newest
        directory_stat = os.fstat(directory_fd)
        total += directory_stat.st_blocks * 512
        newest = max(newest, directory_stat.st_mtime)
        scan_fd = os.dup(directory_fd)
        try:
            with os.scandir(scan_fd) as iterator:
                children = sorted(iterator, key=lambda item: item.name)
            for child in children:
                child_stat = child.stat(follow_symlinks=False)
                newest = max(newest, child_stat.st_mtime)
                if stat.S_ISDIR(child_stat.st_mode) and not stat.S_ISLNK(
                    child_stat.st_mode
                ):
                    child_fd = os.open(
                        child.name,
                        os.O_RDONLY
                        | os.O_DIRECTORY
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=directory_fd,
                    )
                    try:
                        opened = os.fstat(child_fd)
                        if (opened.st_dev, opened.st_ino) != (
                            child_stat.st_dev,
                            child_stat.st_ino,
                        ):
                            raise OSError("directory replaced during scan")
                        walk(child_fd)
                    finally:
                        os.close(child_fd)
                elif stat.S_ISREG(child_stat.st_mode) or stat.S_ISLNK(
                    child_stat.st_mode
                ):
                    total += child_stat.st_blocks * 512
                else:
                    raise OSError("unsupported filesystem entry")
        finally:
            os.close(scan_fd)

    try:
        root_stat = path.lstat()
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            return 0, 0.0, ("invalid-worktree-path",)
        fd = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (root_stat.st_dev, root_stat.st_ino):
                return 0, 0.0, ("scan-failed",)
            walk(fd)
        finally:
            os.close(fd)
    except OSError:
        return 0, 0.0, ("scan-failed",)
    return total, newest, ()


def _parse_lsof(data: bytes, *, self_pid: int) -> tuple[tuple[int, Path], ...]:
    fields = data.replace(b"\0", b"\n").splitlines()
    result: list[tuple[int, Path]] = []
    pid: int | None = None
    for field in fields:
        if not field:
            continue
        tag, value = field[:1], field[1:]
        if tag == b"p":
            try:
                pid = int(value)
            except ValueError as error:
                raise ValueError("malformed lsof PID") from error
            if pid <= 0:
                raise ValueError("malformed lsof PID")
        elif tag == b"n":
            if pid is None:
                raise ValueError("lsof name before PID")
            if pid != self_pid and value.startswith(b"/"):
                result.append((pid, Path(os.fsdecode(value)).resolve(strict=False)))
        elif tag != b"f":
            raise ValueError("unknown lsof field")
    return tuple(sorted(set(result), key=lambda item: (item[0], os.fspath(item[1]))))


def _parse_ps(data: bytes, *, self_pid: int) -> tuple[tuple[int, str], ...]:
    result: list[tuple[int, str]] = []
    for line in data.splitlines():
        if not line.strip():
            continue
        fields = line.lstrip().split(maxsplit=1)
        if len(fields) != 2:
            raise ValueError("malformed ps record")
        try:
            pid = int(fields[0])
        except ValueError as error:
            raise ValueError("malformed ps PID") from error
        if pid <= 0:
            raise ValueError("malformed ps PID")
        if pid != self_pid:
            result.append((pid, os.fsdecode(fields[1])))
    return tuple(result)


def _kill_and_reap_bounded(
    process: subprocess.Popen[bytes], *, deadline: float
) -> None:
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except (OSError, subprocess.TimeoutExpired):
        pass


def _bounded_command(
    args: Sequence[str],
    *,
    popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    record_limit: int | None = None,
) -> tuple[bytes, bytes, str | None]:
    try:
        process = popen_factory(
            list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except OSError:
        return b"", b"", "process-query-failed"
    deadline = time.monotonic() + _PROCESS_TIMEOUT
    if process.stdout is None or process.stderr is None:
        _kill_and_reap_bounded(process, deadline=deadline)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        return b"", b"", "process-query-failed"

    selector = selectors.DefaultSelector()
    outputs = {process.stdout: bytearray(), process.stderr: bytearray()}
    limits = {process.stdout: _PROCESS_STDOUT_MAX, process.stderr: _PROCESS_STDERR_MAX}
    record_count = 0
    try:
        for stream in outputs:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_and_reap_bounded(process, deadline=deadline)
                return b"", b"", "process-query-failed"
            events = selector.select(remaining)
            if not events:
                _kill_and_reap_bounded(process, deadline=deadline)
                return b"", b"", "process-query-failed"
            for key, _ in events:
                stream = key.fileobj
                chunk = os.read(stream.fileno(), 65536)
                if not chunk:
                    selector.unregister(stream)
                    continue
                output = outputs[stream]
                output.extend(chunk)
                if len(output) > limits[stream]:
                    _kill_and_reap_bounded(process, deadline=deadline)
                    return b"", b"", "process-query-overflow"
                if stream is process.stdout and record_limit is not None:
                    record_count += chunk.count(b"\n") + chunk.count(b"\0")
                    if record_count > record_limit:
                        _kill_and_reap_bounded(process, deadline=deadline)
                        return b"", b"", "process-query-overflow"
        returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except (OSError, subprocess.TimeoutExpired):
        _kill_and_reap_bounded(process, deadline=deadline)
        return b"", b"", "process-query-failed"
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
    if returncode != 0:
        return b"", b"", "process-query-failed"
    return bytes(outputs[process.stdout]), bytes(outputs[process.stderr]), None


def collect_process_snapshot(
    *,
    popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> ProcessSnapshot:
    self_pid = os.getpid()
    lsof, _, error = _bounded_command(
        ("lsof", "-nP", "-F", "pfn"),
        popen_factory=popen_factory,
        record_limit=_PROCESS_RECORD_MAX,
    )
    if error is not None:
        return ProcessSnapshot((), (), (error,))
    ps, _, error = _bounded_command(
        ("ps", "-axo", "pid=,command="),
        popen_factory=popen_factory,
        record_limit=_PROCESS_RECORD_MAX,
    )
    if error is not None:
        return ProcessSnapshot((), (), (error,))
    lsof_records = len(lsof.replace(b"\0", b"\n").splitlines())
    ps_records = len(ps.splitlines())
    if lsof_records > _PROCESS_RECORD_MAX or ps_records > _PROCESS_RECORD_MAX:
        return ProcessSnapshot((), (), ("process-query-overflow",))
    try:
        return ProcessSnapshot(
            _parse_lsof(lsof, self_pid=self_pid),
            _parse_ps(ps, self_pid=self_pid),
            (),
        )
    except ValueError:
        return ProcessSnapshot((), (), ("process-query-failed",))


def _git_bytes(path: Path, args: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", os.fspath(path), *args], capture_output=True
        )
    except OSError:
        return subprocess.CompletedProcess(args, 127, b"", b"")


def _admin_activity(worktree: Path) -> tuple[float, tuple[str, ...]]:
    marker = worktree / ".git"
    try:
        marker_stat = marker.lstat()
        newest = marker_stat.st_mtime
        if stat.S_ISDIR(marker_stat.st_mode):
            admin = marker
        elif stat.S_ISREG(marker_stat.st_mode):
            raw = marker.read_bytes()
            if not raw.startswith(b"gitdir: "):
                return 0.0, ("scan-failed",)
            admin = Path(os.fsdecode(raw[len(b"gitdir: ") :].strip()))
            if not admin.is_absolute():
                admin = worktree / admin
        else:
            return 0.0, ("scan-failed",)
        for relative in (Path("HEAD"), Path("logs/HEAD"), Path("index")):
            current = admin / relative
            try:
                newest = max(newest, current.lstat().st_mtime)
            except FileNotFoundError:
                return 0.0, ("scan-failed",)
            except OSError:
                return 0.0, ("scan-failed",)
        return newest, ()
    except OSError:
        return 0.0, ("scan-failed",)


def _inspect_one(
    item: RegisteredWorktree,
    *,
    repo_root: Path,
    main_worktree: Path,
    current_worktree: Path,
    agent_roots: Sequence[Path],
    snapshot: ProcessSnapshot,
    min_idle_hours: float,
    now: float,
) -> WorktreeRecord:
    reasons = list(
        policy_skip_reasons(
            item,
            main_worktree=main_worktree,
            current_worktree=current_worktree,
            agent_roots=agent_roots,
        )
    )
    canonical = item.path.resolve(strict=False)
    path_device: int | None = None
    path_inode: int | None = None
    try:
        path_stat = item.path.lstat()
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
            reasons.append("invalid-worktree-path")
        else:
            path_device, path_inode = path_stat.st_dev, path_stat.st_ino
    except FileNotFoundError:
        reasons.append("missing-directory")
    except OSError:
        reasons.append("invalid-worktree-path")

    branch_head: str | None = None
    if item.branch is not None:
        result = _git_bytes(repo_root, ("rev-parse", "--verify", f"refs/heads/{item.branch}"))
        if result.returncode != 0:
            reasons.append("branch-missing")
        else:
            branch_head = os.fsdecode(result.stdout.strip())
            if branch_head != item.head:
                reasons.append("branch-head-mismatch")

    admin_activity, admin_errors = _admin_activity(item.path)
    for reason in admin_errors:
        if reason not in reasons:
            reasons.append(reason)

    status = _git_bytes(
        item.path,
        (
            "--no-optional-locks",
            "status",
            "--porcelain=v2",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ),
    )
    dirty: bool | None = None
    if status.returncode != 0:
        reasons.append("status-query-failed")
    else:
        dirty = bool(status.stdout)
        if dirty:
            reasons.append("dirty-worktree")

    ignored_result = _git_bytes(
        item.path, ("ls-files", "--others", "-i", "--exclude-standard", "-z", "--")
    )
    ignored_entries: tuple[IgnoredEntry, ...] = ()
    retained = RetainedEvidenceSnapshot((), ())
    asset_snapshot: assets.HydratedAssetSnapshot | None = None
    dol_identity = None
    unapproved: tuple[Path, ...] = ()
    if ignored_result.returncode != 0:
        reasons.append("ignored-inventory-invalid")
    else:
        ignored_entries, inventory_errors = _parse_ignored_inventory(
            item.path, ignored_result.stdout
        )
        reasons.extend(inventory_errors)
        if not inventory_errors:
            retained, retained_errors = discover_retained_evidence(
                item.path, ignored_entries
            )
            reasons.extend(retained_errors)
            asset_related = any(
                any(_is_under(entry.relative, root) for root in assets.ASSET_PATHS)
                for entry in ignored_entries
            )
            if asset_related:
                asset_snapshot, asset_errors = assets.inspect_hydrated_assets(
                    item.path, assets.default_cache_root()
                )
                reasons.extend(asset_errors)
            if any(
                entry.relative == Path("orig/GALE01/sys/main.dol")
                for entry in ignored_entries
            ):
                dol_identity, dol_valid = _inspect_dol(item.path)
                if not dol_valid:
                    reasons.append("asset-validation-failed")
            unapproved, has_retained = _classify_ignored(
                ignored_entries, retained, asset_snapshot, dol_identity
            )
            if has_retained:
                reasons.append("retained-evidence-present")
            if unapproved:
                reasons.append("contains-unapproved-ignored")

    estimated_bytes, tree_activity, walk_errors = _walk_tree(item.path)
    reasons.extend(reason for reason in walk_errors if reason not in reasons)
    if ignored_entries and not _ignored_entries_match(item.path, ignored_entries):
        if "ignored-inventory-invalid" not in reasons:
            reasons.append("ignored-inventory-invalid")
    last_activity = max(admin_activity, tree_activity) if not walk_errors else None
    if last_activity is not None:
        if last_activity > now + 1.0:
            reasons.append("clock-skew")
        elif now - last_activity < min_idle_hours * 3600:
            reasons.append("below-min-idle")

    active_pids = snapshot.active_pids(canonical, item.path)
    if active_pids:
        reasons.append("active-process")
    reasons.extend(reason for reason in snapshot.errors if reason not in reasons)

    merged: bool | None = None
    if item.branch is not None:
        merge = _git_bytes(repo_root, ("merge-base", "--is-ancestor", item.head, "master"))
        if merge.returncode in {0, 1}:
            merged = merge.returncode == 0

    ordered_reasons = tuple(dict.fromkeys(reasons))
    return WorktreeRecord(
        path=item.path,
        canonical_path=canonical,
        path_device=path_device,
        path_inode=path_inode,
        head=item.head,
        branch=item.branch,
        detached=item.detached,
        locked_reason=item.locked_reason,
        prunable_reason=item.prunable_reason,
        branch_head=branch_head,
        estimated_disk_bytes=estimated_bytes,
        last_activity=last_activity,
        dirty=dirty,
        ignored_entries=ignored_entries,
        unapproved_ignored_paths=unapproved,
        retained_evidence=retained,
        asset_snapshot=asset_snapshot,
        dol_identity=dol_identity,
        active_pids=active_pids,
        merged_into_master=merged,
        eligible=not ordered_reasons,
        skip_reasons=ordered_reasons,
    )


def inspect_worktrees(
    repo_root: Path,
    *,
    current_worktree: Path,
    min_idle_hours: float,
    now: float | None = None,
    process_snapshot: ProcessSnapshot | None = None,
) -> WorktreeReport:
    if min_idle_hours < 0 or not __import__("math").isfinite(min_idle_hours):
        raise ValueError("min_idle_hours must be finite and non-negative")
    repo_root = repo_root.resolve(strict=False)
    registered = discover_registered_worktrees(repo_root)
    snapshot = process_snapshot or collect_process_snapshot()
    current_time = time.time() if now is None else now
    main_worktree = registered[0].path.resolve(strict=False)
    agent_roots = (
        Path.home() / ".codex" / "worktrees",
        Path.home() / ".claude" / "worktrees",
        main_worktree / ".claude" / "worktrees",
    )
    records = tuple(
        sorted(
            (
                _inspect_one(
                    item,
                    repo_root=repo_root,
                    main_worktree=main_worktree,
                    current_worktree=current_worktree,
                    agent_roots=agent_roots,
                    snapshot=snapshot,
                    min_idle_hours=min_idle_hours,
                    now=current_time,
                )
                for item in registered
            ),
            key=lambda record: os.fspath(record.canonical_path),
        )
    )
    return WorktreeReport(
        repo_root=repo_root,
        common_git_dir=common_git_dir(repo_root),
        current_worktree=current_worktree.resolve(strict=False),
        min_idle_hours=min_idle_hours,
        records=records,
        global_errors=snapshot.errors,
    )


def _retirement_plan(report: WorktreeReport) -> tuple[RetirementCandidate, ...]:
    candidates: list[RetirementCandidate] = []
    ordered_records = sorted(
        report.records, key=lambda record: os.fspath(record.canonical_path)
    )
    for record in ordered_records:
        if not record.eligible or record.branch is None or record.last_activity is None:
            continue
        candidates.append(
            RetirementCandidate(
                path=record.path,
                branch=record.branch,
                head=record.head,
                estimated_disk_bytes=record.estimated_disk_bytes,
                last_activity=record.last_activity,
            )
        )
    return tuple(candidates)


def _retirement_errors(
    reasons: Sequence[str], *, detail: str
) -> tuple[RetirementError, ...]:
    return tuple(RetirementError(reason=reason, detail=detail) for reason in reasons)


def _fresh_retirement_report(report: WorktreeReport) -> WorktreeReport:
    return inspect_worktrees(
        report.repo_root,
        current_worktree=report.current_worktree,
        min_idle_hours=report.min_idle_hours,
    )


def _record_at_path(
    report: WorktreeReport, canonical_path: Path
) -> WorktreeRecord | None:
    return next(
        (
            record
            for record in report.records
            if record.canonical_path == canonical_path
        ),
        None,
    )


_REVALIDATION_REASON_PRIORITY = (
    "dirty-worktree",
    "active-process",
    "locked-worktree",
    "prunable-worktree",
    "detached-head",
    "branch-missing",
    "branch-head-mismatch",
    "retained-evidence-present",
    "contains-unapproved-ignored",
    "asset-validation-failed",
)


def _revalidation_reason(
    planned: WorktreeRecord, current: WorktreeRecord | None
) -> str | None:
    if current is None:
        return "changed-during-retirement"
    if (
        current.path_device != planned.path_device
        or current.path_inode != planned.path_inode
    ):
        return "replaced-during-retirement"

    for reason in _REVALIDATION_REASON_PRIORITY:
        if reason in current.skip_reasons:
            return reason

    identity_facts = (
        current.path,
        current.canonical_path,
        current.head,
        current.branch,
        current.detached,
        current.locked_reason,
        current.prunable_reason,
        current.branch_head,
    )
    planned_identity_facts = (
        planned.path,
        planned.canonical_path,
        planned.head,
        planned.branch,
        planned.detached,
        planned.locked_reason,
        planned.prunable_reason,
        planned.branch_head,
    )
    bound_facts = (
        current.last_activity,
        current.estimated_disk_bytes,
        current.dirty,
        current.ignored_entries,
        current.unapproved_ignored_paths,
        current.retained_evidence,
        current.asset_snapshot,
        current.dol_identity,
        current.active_pids,
    )
    planned_bound_facts = (
        planned.last_activity,
        planned.estimated_disk_bytes,
        planned.dirty,
        planned.ignored_entries,
        planned.unapproved_ignored_paths,
        planned.retained_evidence,
        planned.asset_snapshot,
        planned.dol_identity,
        planned.active_pids,
    )
    if identity_facts != planned_identity_facts or bound_facts != planned_bound_facts:
        return "changed-during-retirement"
    if not current.eligible:
        return (
            current.skip_reasons[0]
            if current.skip_reasons
            else "changed-during-retirement"
        )
    return None


def _skip(candidate: RetirementCandidate, *, phase: str, reason: str) -> RetirementSkip:
    return RetirementSkip(
        path=candidate.path,
        branch=candidate.branch,
        head=candidate.head,
        phase=phase,
        reason=reason,
    )


def _porcelain_error(error: WorktreeParseError, *, phase: str) -> RetirementError:
    return RetirementError(
        reason="worktree-porcelain-invalid",
        detail=f"{phase}: {error}",
    )


def _path_exists_nofollow(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _strict_registered_canonical_paths(
    registered: Sequence[RegisteredWorktree],
) -> tuple[Path, ...]:
    canonical_paths: list[Path] = []
    for item in registered:
        try:
            canonical_paths.append(item.path.resolve(strict=True))
        except OSError as error:
            raise WorktreeParseError(
                f"cannot strictly canonicalize registered worktree "
                f"{item.path!s}: {error}"
            ) from error
    return tuple(canonical_paths)


def retire_worktrees(report: WorktreeReport, *, apply: bool) -> RetirementResult:
    """Plan or safely apply retirement of eligible registered worktrees."""

    if report.global_errors:
        return RetirementResult(
            planned=(),
            removed=(),
            skipped=(),
            errors=_retirement_errors(
                report.global_errors, detail="initial inspection failed"
            ),
        )
    if not apply:
        return RetirementResult(
            planned=_retirement_plan(report),
            removed=(),
            skipped=(),
            errors=(),
        )

    lock_descriptor: int | None = None
    try:
        try:
            locked_common_git_dir = report.common_git_dir.resolve(strict=True)
            lock_path = locked_common_git_dir / "worktree-doctor-retirement.lock"
            lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(
                lock_descriptor,
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
            locked_common_git_stat = locked_common_git_dir.stat()
            locked_common_git_identity = (
                locked_common_git_stat.st_dev,
                locked_common_git_stat.st_ino,
            )
        except OSError as error:
            if lock_descriptor is not None:
                os.close(lock_descriptor)
                lock_descriptor = None
            return RetirementResult(
                planned=(),
                removed=(),
                skipped=(),
                errors=(
                    RetirementError(
                        reason="retirement-lock-unavailable",
                        detail=str(error),
                    ),
                ),
            )

        try:
            preflight = _fresh_retirement_report(report)
        except WorktreeParseError as error:
            return RetirementResult(
                planned=(),
                removed=(),
                skipped=(),
                errors=(_porcelain_error(error, phase="preflight"),),
            )
        if preflight.global_errors:
            return RetirementResult(
                planned=(),
                removed=(),
                skipped=(),
                errors=_retirement_errors(
                    preflight.global_errors, detail="preflight inspection failed"
                ),
            )
        try:
            preflight_common_git_dir = preflight.common_git_dir.resolve(strict=True)
            preflight_common_git_stat = preflight_common_git_dir.stat()
            preflight_common_git_identity = (
                preflight_common_git_stat.st_dev,
                preflight_common_git_stat.st_ino,
            )
        except OSError as error:
            return RetirementResult(
                planned=(),
                removed=(),
                skipped=(),
                errors=(
                    RetirementError(
                        reason="common-git-dir-changed",
                        detail=f"preflight common Git directory is unavailable: {error}",
                    ),
                ),
            )
        if (
            preflight_common_git_dir != locked_common_git_dir
            or preflight_common_git_identity != locked_common_git_identity
        ):
            return RetirementResult(
                planned=(),
                removed=(),
                skipped=(),
                errors=(
                    RetirementError(
                        reason="common-git-dir-changed",
                        detail=(
                            "preflight common Git directory does not match the "
                            "locked directory"
                        ),
                    ),
                ),
            )

        planned = _retirement_plan(preflight)
        preflight_records = {
            record.path: record for record in preflight.records if record.eligible
        }
        removed: list[RetirementRemoval] = []
        skipped: list[RetirementSkip] = []
        errors: list[RetirementError] = []

        for candidate in planned:
            original = preflight_records[candidate.path]
            canonical_path = original.canonical_path
            try:
                current_report = _fresh_retirement_report(report)
            except WorktreeParseError as error:
                errors.append(_porcelain_error(error, phase="revalidate"))
                break
            if current_report.global_errors:
                errors.extend(
                    _retirement_errors(
                        current_report.global_errors,
                        detail=f"revalidation failed for {candidate.path}",
                    )
                )
                break
            current = _record_at_path(current_report, canonical_path)
            reason = _revalidation_reason(original, current)
            if reason is not None:
                skipped.append(_skip(candidate, phase="revalidate", reason=reason))
                continue

            final_process_snapshot = collect_process_snapshot()
            if final_process_snapshot.errors:
                errors.extend(
                    _retirement_errors(
                        final_process_snapshot.errors,
                        detail=f"final process check failed for {candidate.path}",
                    )
                )
                break
            if final_process_snapshot.active_pids(canonical_path, candidate.path):
                skipped.append(
                    _skip(
                        candidate,
                        phase="revalidate",
                        reason="active-process",
                    )
                )
                continue

            args = [
                "git",
                "-C",
                os.fspath(report.repo_root),
                "worktree",
                "remove",
                "--",
                os.fspath(candidate.path),
            ]
            try:
                removal = subprocess.run(args, capture_output=True)
            except OSError:
                skipped.append(
                    _skip(candidate, phase="remove", reason="git-remove-failed")
                )
                continue
            if removal.returncode != 0:
                skipped.append(
                    _skip(candidate, phase="remove", reason="git-remove-failed")
                )
                continue

            try:
                registered = discover_registered_worktrees(report.repo_root)
                registered_canonical_paths = _strict_registered_canonical_paths(
                    registered
                )
            except WorktreeParseError as error:
                errors.append(_porcelain_error(error, phase="verify"))
                break
            still_registered = canonical_path in registered_canonical_paths
            if _path_exists_nofollow(candidate.path) or still_registered:
                skipped.append(
                    _skip(candidate, phase="verify", reason="git-remove-failed")
                )
                continue

            branch_result = _git_bytes(
                report.repo_root,
                ("rev-parse", "--verify", f"refs/heads/{candidate.branch}"),
            )
            branch_head_after = os.fsdecode(branch_result.stdout.strip())
            if branch_result.returncode != 0 or branch_head_after != candidate.head:
                skipped.append(
                    _skip(
                        candidate,
                        phase="verify",
                        reason="branch-preservation-failed",
                    )
                )
                continue
            removed.append(
                RetirementRemoval(
                    path=candidate.path,
                    branch=candidate.branch,
                    head=candidate.head,
                    branch_head_after=branch_head_after,
                    estimated_reclaimed_bytes=candidate.estimated_disk_bytes,
                )
            )

        return RetirementResult(
            planned=planned,
            removed=tuple(removed),
            skipped=tuple(skipped),
            errors=tuple(errors),
        )
    finally:
        if lock_descriptor is not None:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            finally:
                os.close(lock_descriptor)
