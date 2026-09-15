"""Discover manifest-owned diagnostic evidence from an ignored inventory."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


_ARTIFACT_FORMAT = "melee-agent.mwcc-debug-artifact-run/v1"
_RUN_NAME = re.compile(r"\d{8}T\d{6}\.\d{6}Z-[0-9a-f]{32}\Z")
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})


class _IgnoredEntry(Protocol):
    relative: Path
    kind: str
    device: int
    inode: int
    size: int
    mtime: float


@dataclass(frozen=True)
class RetainedEvidenceSnapshot:
    roots: tuple[Path, ...]
    manifests: tuple[tuple[Path, int, int, int, float], ...]


def _real_directory(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISDIR(mode) and not stat.S_ISLNK(mode)


def _owned_layout(manifest_path: Path, payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    run_dir = manifest_path.parent
    if payload.get("artifact_format") != _ARTIFACT_FORMAT:
        return False
    run_id = payload.get("run_id")
    if (
        not isinstance(run_id, str)
        or run_id != run_dir.name
        or _RUN_NAME.fullmatch(run_id) is None
    ):
        return False
    if not _real_directory(run_dir) or not _real_directory(run_dir / "evidence"):
        return False

    state = payload.get("state")
    transient = run_dir / "transient"
    if state == "active":
        return _real_directory(transient)
    if state not in _TERMINAL_STATES or not isinstance(payload.get("finished_at"), str):
        return False
    try:
        transient_mode = transient.lstat().st_mode
    except FileNotFoundError:
        return payload.get("cleanup_skipped_reason") is None
    except OSError:
        return False
    cleanup_reason = payload.get("cleanup_skipped_reason")
    return (
        stat.S_ISDIR(transient_mode)
        and not stat.S_ISLNK(transient_mode)
        and isinstance(cleanup_reason, str)
        and bool(cleanup_reason)
    )


def discover_retained_evidence(
    worktree: Path, ignored: Sequence[_IgnoredEntry]
) -> tuple[RetainedEvidenceSnapshot, tuple[str, ...]]:
    """Return roots proven to be owned by exact artifact-run manifests.

    Manifest-looking but unowned files are intentionally not errors: callers
    leave them in the unapproved ignored inventory and therefore fail closed.
    """

    roots: set[Path] = set()
    manifests: list[tuple[Path, int, int, int, float]] = []
    for entry in ignored:
        if entry.kind != "file" or entry.relative.name != "manifest.json":
            continue
        path = worktree / entry.relative
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
                current = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(current.st_mode)
                    or (current.st_dev, current.st_ino, current.st_size, current.st_mtime)
                    != (entry.device, entry.inode, entry.size, entry.mtime)
                ):
                    continue
                payload = json.load(stream)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not _owned_layout(path, payload):
            continue
        roots.add(path.parent.parent)
        manifests.append(
            (
                entry.relative,
                entry.device,
                entry.inode,
                entry.size,
                entry.mtime,
            )
        )
    return (
        RetainedEvidenceSnapshot(
            roots=tuple(sorted(roots, key=lambda path: path.as_posix())),
            manifests=tuple(sorted(manifests, key=lambda item: item[0].as_posix())),
        ),
        (),
    )
