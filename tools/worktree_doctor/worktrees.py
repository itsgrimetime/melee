"""Strict discovery and policy classification for registered Git worktrees."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


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


_OBJECT_HEX_LENGTHS = {b"sha1": 40, b"sha256": 64}
_HEX_OID = re.compile(rb"[0-9a-fA-F]+\Z")
_BRANCH_PREFIX = b"refs/heads/"
_INVALID_REF_BYTES = frozenset(b" ~^:?*[\\")
_AGENT_BRANCH_PREFIXES = ("codex/", "claude/", "wall/")


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
