"""Validated, immutable file-level asset sharing for worktrees.

The cache deliberately contains only compiler and tool payloads.  It never
contains a whole ``build`` directory: consumer worktrees retain real
directories and receive relative symlinks for individual validated files.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import platform
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ASSET_PATHS = (
    Path("build/compilers"),
    Path("build/tools"),
    Path("tools/table-typer/table-typer"),
)
CACHE_SCHEMA_VERSION = 1

_BUFFER_SIZE = 1024 * 1024
_DARWIN_RENAME_EXCL = 0x00000004
_DARWIN_RENAME_NOFOLLOW_ANY = 0x00000010
_LINUX_RENAME_NOREPLACE = 0x00000001


@dataclass(frozen=True)
class AssetResult:
    status: str
    cache_root: Path
    linked: tuple[Path, ...]
    skipped: tuple[str, ...]


@dataclass(frozen=True)
class _AssetFile:
    relative: Path
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class _SourceFile:
    relative: Path
    device: int
    inode: int
    size_bytes: int
    mode: int


def default_cache_root() -> Path:
    """Return the per-platform immutable cache location."""
    platform_key = f"{sys.platform}-{platform.machine().lower()}"
    return (
        Path.home()
        / ".cache"
        / "melee-agent"
        / "worktree-assets"
        / f"v{CACHE_SCHEMA_VERSION}"
        / platform_key
    )


def seed_shared_assets(source: Path, cache_root: Path) -> AssetResult:
    """Copy approved regular source files into an atomically published cache."""
    source = _absolute_path(source)
    cache_root = _absolute_path(cache_root)
    source_fd = _open_directory(source)
    if source_fd is None:
        return _result("invalid-source", cache_root)

    try:
        source_files = _collect_source_files(source_fd)
        if source_files is None:
            return _result("invalid-source", cache_root)
        if not source_files:
            return _result("no-assets", cache_root)

        cache_state, _ = _validated_cache(cache_root)
        if cache_state == "valid":
            return _result("cache-exists", cache_root)
        if cache_state == "invalid":
            return _result("invalid-cache", cache_root)

        staging = _make_staging_directory(cache_root)
        if staging is None:
            return _result("cache-unavailable", cache_root)
        manifest = _copy_source_files(source_fd, source_files, staging)
        if manifest is None:
            return _result("invalid-source", cache_root)
        _write_manifest(staging, manifest)
        if not _seal_cache_directories(staging, include_root=False):
            return _result("cache-unavailable", cache_root)
        staged_state, _ = _validated_cache(staging)
        if staged_state != "valid":
            return _result("invalid-cache", cache_root)

        publish_status = _publish_staging(staging, cache_root)
        if publish_status == "published":
            if not _seal_cache_directories(cache_root):
                return _result("cache-unavailable", cache_root)
            return _result("seeded", cache_root)
        if publish_status == "cache-exists":
            return _result("cache-exists", cache_root)
        if publish_status == "invalid-cache":
            return _result("invalid-cache", cache_root)
        # Retain an unpublished staging directory.  A named staging path can
        # be replaced after a failed publish, so path-based recursive cleanup
        # would risk deleting data selected by a mutable pathname.
        return _result("cache-unavailable", cache_root)
    finally:
        os.close(source_fd)


def hydrate_shared_assets(
    target: Path,
    cache_root: Path,
    *,
    asset_source: Path | None = None,
) -> AssetResult:
    """Create relative file-level symlinks for a previously validated cache."""
    target = _absolute_path(target)
    cache_root = _absolute_path(cache_root)
    cache_state, cache_files = _validated_cache(cache_root)
    if cache_state == "missing":
        if asset_source is None:
            return _result("cache-missing", cache_root)
        seeded = seed_shared_assets(asset_source, cache_root)
        if seeded.status not in {"seeded", "cache-exists"}:
            return seeded
        cache_state, cache_files = _validated_cache(cache_root)

    if cache_state != "valid" or cache_files is None:
        return _result("invalid-cache", cache_root)

    target_fd = _open_directory(target)
    if target_fd is None:
        return _result("invalid-target", cache_root)

    linked: list[Path] = []
    skipped: list[str] = []
    try:
        for cached_file in cache_files:
            parent_fd, parent_relative = _ensure_real_target_parent(
                target_fd, cached_file.relative.parts[:-1]
            )
            relative_text = cached_file.relative.as_posix()
            if parent_fd is None:
                skipped.append(relative_text)
                continue
            try:
                filename = cached_file.relative.name
                expected_cache_file = cache_root / "files" / cached_file.relative
                expected_link = os.path.relpath(
                    expected_cache_file,
                    start=target / parent_relative,
                )
                try:
                    existing = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    try:
                        os.symlink(expected_link, filename, dir_fd=parent_fd)
                    except FileExistsError:
                        skipped.append(relative_text)
                    except OSError:
                        skipped.append(relative_text)
                    else:
                        linked.append(target / cached_file.relative)
                    continue
                except OSError:
                    skipped.append(relative_text)
                    continue

                if stat.S_ISLNK(existing.st_mode):
                    try:
                        current_link = os.readlink(filename, dir_fd=parent_fd)
                    except OSError:
                        skipped.append(relative_text)
                    else:
                        if current_link != expected_link:
                            skipped.append(relative_text)
                else:
                    skipped.append(relative_text)
            finally:
                os.close(parent_fd)
    finally:
        os.close(target_fd)

    return AssetResult(
        status="hydrated",
        cache_root=cache_root,
        linked=tuple(linked),
        skipped=tuple(skipped),
    )


def _result(status: str, cache_root: Path) -> AssetResult:
    return AssetResult(status=status, cache_root=cache_root, linked=(), skipped=())


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _collect_source_files(source_fd: int) -> tuple[_SourceFile, ...] | None:
    files: list[_SourceFile] = []
    for approved in ASSET_PATHS:
        handle, status = _open_relative(source_fd, approved.parts)
        if status == "missing":
            continue
        if handle is None:
            return None
        try:
            entry_stat = os.fstat(handle)
            if approved == ASSET_PATHS[-1]:
                if not stat.S_ISREG(entry_stat.st_mode):
                    return None
                files.append(
                    _SourceFile(
                        approved,
                        entry_stat.st_dev,
                        entry_stat.st_ino,
                        entry_stat.st_size,
                        entry_stat.st_mode,
                    )
                )
            else:
                if not stat.S_ISDIR(entry_stat.st_mode):
                    return None
                if not _walk_source_directory(handle, approved, files):
                    return None
        finally:
            os.close(handle)
    return tuple(sorted(files, key=lambda item: item.relative.as_posix()))


def _walk_source_directory(
    directory_fd: int,
    relative: Path,
    files: list[_SourceFile],
) -> bool:
    try:
        with os.scandir(os.dup(directory_fd)) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError:
        return False
    for entry in entries:
        try:
            entry_stat = entry.stat(follow_symlinks=False)
        except OSError:
            return False
        child_relative = relative / entry.name
        if stat.S_ISLNK(entry_stat.st_mode):
            return False
        if stat.S_ISREG(entry_stat.st_mode):
            files.append(
                _SourceFile(
                    child_relative,
                    entry_stat.st_dev,
                    entry_stat.st_ino,
                    entry_stat.st_size,
                    entry_stat.st_mode,
                )
            )
            continue
        if not stat.S_ISDIR(entry_stat.st_mode):
            return False
        child_fd, status = _open_child_directory(directory_fd, entry.name)
        if child_fd is None or status != "ok":
            return False
        try:
            current = os.fstat(child_fd)
            if (current.st_dev, current.st_ino) != (entry_stat.st_dev, entry_stat.st_ino):
                return False
            if not _walk_source_directory(child_fd, child_relative, files):
                return False
        finally:
            os.close(child_fd)
    return True


def _copy_source_files(
    source_fd: int,
    source_files: tuple[_SourceFile, ...],
    staging: Path,
) -> dict[str, object] | None:
    manifest_files: list[dict[str, object]] = []
    for source_file in source_files:
        input_fd = _open_expected_source_file(source_fd, source_file)
        if input_fd is None:
            return None
        destination = staging / "files" / source_file.relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            digest = hashlib.sha256()
            with os.fdopen(input_fd, "rb", closefd=True) as input_file:
                with destination.open("xb") as output_file:
                    while chunk := input_file.read(_BUFFER_SIZE):
                        digest.update(chunk)
                        output_file.write(chunk)
            destination.chmod(0o444 | (source_file.mode & 0o111))
        except OSError:
            return None
        manifest_files.append(
            {
                "path": source_file.relative.as_posix(),
                "size_bytes": source_file.size_bytes,
                "sha256": digest.hexdigest(),
            }
        )
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "platform": _platform_identity(),
        "files": manifest_files,
    }


def _open_expected_source_file(source_fd: int, source_file: _SourceFile) -> int | None:
    handle, status = _open_relative(source_fd, source_file.relative.parts)
    if handle is None or status != "ok":
        return None
    try:
        current = os.fstat(handle)
    except OSError:
        os.close(handle)
        return None
    if not stat.S_ISREG(current.st_mode) or (
        current.st_dev,
        current.st_ino,
        current.st_size,
    ) != (
        source_file.device,
        source_file.inode,
        source_file.size_bytes,
    ):
        os.close(handle)
        return None
    return handle


def _write_manifest(staging: Path, manifest: dict[str, object]) -> None:
    manifest_path = staging / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _seal_cache_directories(staging: Path, *, include_root: bool = True) -> bool:
    """Prevent payload replacement through a writable cache directory."""
    try:
        for root, _, _ in os.walk(staging, topdown=False, followlinks=False):
            if not include_root and Path(root) == staging:
                continue
            Path(root).chmod(0o555)
    except OSError:
        return False
    return True


def _make_staging_directory(cache_root: Path) -> Path | None:
    parent = cache_root.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        parent_stat = os.lstat(parent)
        if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
            return None
        return Path(tempfile.mkdtemp(prefix=f".{cache_root.name}.staging-", dir=parent))
    except OSError:
        return None


def _validated_cache(cache_root: Path) -> tuple[str, tuple[_AssetFile, ...] | None]:
    try:
        root_stat = os.lstat(cache_root)
    except FileNotFoundError:
        return "missing", None
    except OSError:
        return "invalid", None
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        return "invalid", None

    manifest_path = cache_root / "manifest.json"
    try:
        manifest_stat = os.lstat(manifest_path)
    except OSError:
        return "invalid", None
    if stat.S_ISLNK(manifest_stat.st_mode) or not stat.S_ISREG(manifest_stat.st_mode):
        return "invalid", None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "invalid", None
    if not isinstance(manifest, dict) or manifest.get("schema_version") != CACHE_SCHEMA_VERSION:
        return "invalid", None
    if manifest.get("platform") != _platform_identity():
        return "invalid", None
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        return "invalid", None

    cache_files: list[_AssetFile] = []
    seen: set[str] = set()
    for raw_file in raw_files:
        parsed = _parse_manifest_file(raw_file)
        if parsed is None:
            return "invalid", None
        path_text = parsed.relative.as_posix()
        if path_text in seen:
            return "invalid", None
        seen.add(path_text)
        if not _validate_cached_file(cache_root, parsed):
            return "invalid", None
        cache_files.append(parsed)
    if [item.relative.as_posix() for item in cache_files] != sorted(seen):
        return "invalid", None
    return "valid", tuple(cache_files)


def _parse_manifest_file(raw_file: object) -> _AssetFile | None:
    if not isinstance(raw_file, dict):
        return None
    path_text = raw_file.get("path")
    size_bytes = raw_file.get("size_bytes")
    digest = raw_file.get("sha256")
    if (
        not isinstance(path_text, str)
        or not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or size_bytes < 0
        or not isinstance(digest, str)
        or len(digest) != 64
    ):
        return None
    try:
        int(digest, 16)
    except ValueError:
        return None
    if digest.lower() != digest:
        return None
    relative = _safe_relative_path(path_text)
    if relative is None or not _is_approved_asset_path(relative):
        return None
    return _AssetFile(relative=relative, size_bytes=size_bytes, sha256=digest)


def _safe_relative_path(path_text: str) -> Path | None:
    if not path_text or "\\" in path_text:
        return None
    pure_path = PurePosixPath(path_text)
    if pure_path.is_absolute() or pure_path.as_posix() != path_text:
        return None
    if any(part in {"", ".", ".."} for part in pure_path.parts):
        return None
    return Path(*pure_path.parts)


def _is_approved_asset_path(relative: Path) -> bool:
    for approved in ASSET_PATHS[:-1]:
        if relative.parts[: len(approved.parts)] == approved.parts and len(relative.parts) > len(
            approved.parts
        ):
            return True
    return relative == ASSET_PATHS[-1]


def _validate_cached_file(cache_root: Path, cached_file: _AssetFile) -> bool:
    file_path = _safe_cache_file_path(cache_root, cached_file.relative)
    if file_path is None:
        return False
    try:
        file_stat = os.lstat(file_path)
    except OSError:
        return False
    if (
        stat.S_ISLNK(file_stat.st_mode)
        or not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_size != cached_file.size_bytes
        or file_stat.st_mode & 0o222
    ):
        return False
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(file_path, flags)
    except OSError:
        return False
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            file_stat.st_dev,
            file_stat.st_ino,
        ):
            return False
        digest = hashlib.sha256()
        while chunk := os.read(fd, _BUFFER_SIZE):
            digest.update(chunk)
        return digest.hexdigest() == cached_file.sha256
    except OSError:
        return False
    finally:
        os.close(fd)


def _safe_cache_file_path(cache_root: Path, relative: Path) -> Path | None:
    current = cache_root
    for component in ("files", *relative.parts[:-1]):
        current = current / component
        try:
            entry_stat = os.lstat(current)
        except OSError:
            return None
        if stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISDIR(entry_stat.st_mode):
            return None
    return current / relative.name


def _ensure_real_target_parent(
    target_fd: int,
    parent_parts: tuple[str, ...],
) -> tuple[int | None, Path]:
    current_fd = os.dup(target_fd)
    relative = Path()
    try:
        for component in parent_parts:
            child_fd, status = _open_child_directory(current_fd, component)
            if status == "missing":
                try:
                    os.mkdir(component, mode=0o755, dir_fd=current_fd)
                except FileExistsError:
                    pass
                except OSError:
                    return None, relative
                child_fd, status = _open_child_directory(current_fd, component)
            if child_fd is None or status != "ok":
                os.close(current_fd)
                return None, relative
            os.close(current_fd)
            current_fd = child_fd
            relative /= component
        return current_fd, relative
    except Exception:
        os.close(current_fd)
        raise


def _open_directory(path: Path) -> int | None:
    try:
        entry_stat = os.lstat(path)
        if stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISDIR(entry_stat.st_mode):
            return None
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        opened = os.fstat(fd)
    except OSError:
        os.close(fd)
        return None
    if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
        entry_stat.st_dev,
        entry_stat.st_ino,
    ):
        os.close(fd)
        return None
    return fd


def _open_relative(parent_fd: int, parts: tuple[str, ...]) -> tuple[int | None, str]:
    current_fd = os.dup(parent_fd)
    try:
        for component in parts:
            try:
                child_fd = os.open(
                    component,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=current_fd,
                )
            except FileNotFoundError:
                os.close(current_fd)
                return None, "missing"
            except OSError:
                os.close(current_fd)
                return None, "invalid"
            os.close(current_fd)
            current_fd = child_fd
        return current_fd, "ok"
    except Exception:
        os.close(current_fd)
        raise


def _open_child_directory(parent_fd: int, name: str) -> tuple[int | None, str]:
    try:
        fd = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "invalid"
    try:
        opened = os.fstat(fd)
        if not stat.S_ISDIR(opened.st_mode):
            os.close(fd)
            return None, "invalid"
    except OSError:
        os.close(fd)
        return None, "invalid"
    return fd, "ok"


def _publish_staging(staging: Path, cache_root: Path) -> str:
    parent_fd = _open_directory(cache_root.parent)
    if parent_fd is None:
        return "unavailable"
    try:
        result = _rename_no_replace(parent_fd, staging.name, cache_root.name)
    finally:
        os.close(parent_fd)
    if result == "ok":
        cache_state, _ = _validated_cache(cache_root)
        return "published" if cache_state == "valid" else "unavailable"
    if result == "destination-exists":
        cache_state, _ = _validated_cache(cache_root)
        return "cache-exists" if cache_state == "valid" else "invalid-cache"
    return "unavailable"


def _rename_no_replace(parent_fd: int, source_name: str, destination_name: str) -> str:
    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_name)
    destination = os.fsencode(destination_name)
    if sys.platform == "darwin":
        renameatx_np = getattr(libc, "renameatx_np", None)
        if renameatx_np is None:
            return "unsupported"
        renameatx_np.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameatx_np.restype = ctypes.c_int
        ctypes.set_errno(0)
        result = renameatx_np(
            parent_fd,
            source,
            parent_fd,
            destination,
            _DARWIN_RENAME_EXCL | _DARWIN_RENAME_NOFOLLOW_ANY,
        )
    elif sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            return "unsupported"
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        ctypes.set_errno(0)
        result = renameat2(
            parent_fd,
            source,
            parent_fd,
            destination,
            _LINUX_RENAME_NOREPLACE,
        )
    else:
        return "unsupported"
    if result == 0:
        return "ok"
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        return "destination-exists"
    return "error"


def _platform_identity() -> dict[str, str]:
    return {"system": sys.platform, "machine": platform.machine().lower()}
