"""Managed temporary storage for mwcc-debug scratch artifacts."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Iterator

DEFAULT_MAX_AGE_SECONDS = 12 * 60 * 60
DEFAULT_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_ACTIVE_GRACE_SECONDS = 5 * 60

ROOT_ENV = "MWCC_DEBUG_TMP_ROOT"
MAX_AGE_ENV = "MWCC_DEBUG_TMP_MAX_AGE_SECONDS"
MAX_BYTES_ENV = "MWCC_DEBUG_TMP_MAX_BYTES"
ACTIVE_GRACE_ENV = "MWCC_DEBUG_TMP_ACTIVE_GRACE_SECONDS"

LEGACY_FILE_PREFIXES = (
    "pcdump_forced_",
    "pcdump_nocache_",
    "pcdump_unstable-source_",
    "pcdump_local_keep_",
    "pcdump_local_discard_",
    "score_source_discard_",
)
LEGACY_DIR_PREFIXES = ("mwcc_diff_",)


def scratch_root() -> Path:
    override = os.environ.get(ROOT_ENV)
    if override:
        return Path(override).expanduser()
    return Path(tempfile.gettempdir()) / "melee-mwcc-debug"


def reaped_scratch_root(*, now: float | None = None) -> Path:
    root = scratch_root()
    root.mkdir(parents=True, exist_ok=True)
    timestamp = time.time() if now is None else now
    max_age = _float_env(MAX_AGE_ENV, DEFAULT_MAX_AGE_SECONDS)
    if max_age > 0:
        _remove_stale_entries(root, now=timestamp, max_age=max_age)
        _remove_stale_legacy_entries(root.parent, now=timestamp, max_age=max_age)
    max_bytes = int(_float_env(MAX_BYTES_ENV, DEFAULT_MAX_BYTES))
    if max_bytes > 0:
        active_grace = _float_env(ACTIVE_GRACE_ENV, DEFAULT_ACTIVE_GRACE_SECONDS)
        _cap_root_size(
            root,
            max_bytes=max_bytes,
            now=timestamp,
            active_grace=active_grace,
        )
    return root


def scratch_path(
    prefix: str,
    *,
    suffix: str = "",
    root: Path | None = None,
) -> Path:
    base = root or reaped_scratch_root()
    base.mkdir(parents=True, exist_ok=True)
    safe_prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", prefix).strip("._-") or "tmp"
    return base / f"{safe_prefix}_{os.getpid()}_{time.time_ns()}{suffix}"


def mkdtemp(*, prefix: str = "mwcc-debug-") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=reaped_scratch_root()))


@contextmanager
def temporary_directory(*, prefix: str = "mwcc-debug-") -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix=prefix, dir=reaped_scratch_root()) as td:
        yield Path(td)


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _remove_stale_entries(root: Path, *, now: float, max_age: float) -> None:
    for entry in _iter_entries(root):
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if now - mtime > max_age:
            _remove_entry(entry)


def _remove_stale_legacy_entries(parent: Path, *, now: float, max_age: float) -> None:
    for entry in _iter_entries(parent):
        name = entry.name
        if entry.is_dir() and any(
            name.startswith(prefix) for prefix in LEGACY_DIR_PREFIXES
        ):
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            if now - mtime > max_age:
                _remove_entry(entry)
            continue
        if not entry.is_file():
            continue
        if not any(name.startswith(prefix) for prefix in LEGACY_FILE_PREFIXES):
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if now - mtime > max_age:
            _remove_entry(entry)


def _cap_root_size(
    root: Path,
    *,
    max_bytes: int,
    now: float,
    active_grace: float,
) -> None:
    entries: list[tuple[float, int, Path]] = []
    total = 0
    for entry in _iter_entries(root):
        size = _entry_size(entry)
        total += size
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            mtime = now
        entries.append((mtime, size, entry))
    if total <= max_bytes:
        return
    for mtime, size, entry in sorted(entries, key=lambda item: item[0]):
        if total <= max_bytes:
            return
        if active_grace > 0 and now - mtime < active_grace:
            continue
        if _remove_entry(entry):
            total -= size


def _entry_size(path: Path) -> int:
    try:
        if path.is_file() or path.is_symlink():
            return path.lstat().st_size
    except OSError:
        return 0
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() or child.is_symlink():
                total += child.lstat().st_size
        except OSError:
            continue
    return total


def _iter_entries(root: Path) -> list[Path]:
    try:
        return list(root.iterdir())
    except OSError:
        return []


def _remove_entry(path: Path) -> bool:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except OSError:
        return False
