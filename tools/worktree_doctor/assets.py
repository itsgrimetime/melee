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
import secrets
import stat
import sys
from collections.abc import Callable
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
class _CacheIdentity:
    root_device: int
    root_inode: int
    manifest_device: int
    manifest_inode: int
    files: dict[Path, tuple[int, int]]


@dataclass(frozen=True)
class _ValidatedCache:
    files: tuple[_AssetFile, ...]
    identity: _CacheIdentity


@dataclass(frozen=True)
class _Staging:
    parent_fd: int
    parent_identity: tuple[int, int]
    root_fd: int
    root_identity: tuple[int, int]
    name: str


@dataclass(frozen=True)
class _CreatedLink:
    parent_fd: int
    name: str
    target: str
    identity: tuple[int, int]


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
        try:
            manifest = _copy_source_files(source_fd, source_files, staging.root_fd)
            if manifest is None:
                return _result("invalid-source", cache_root)
            if not _write_manifest(staging.root_fd, manifest):
                return _result("cache-unavailable", cache_root)
            if not _seal_cache_directories(staging.root_fd, include_root=False):
                return _result("cache-unavailable", cache_root)
            staged_state, staged_cache = _validated_cache_fd(
                staging.root_fd, allow_writable_root=True
            )
            if staged_state != "valid" or staged_cache is None:
                return _result("invalid-cache", cache_root)
            if not _staging_entry_matches(staging):
                return _result("cache-unavailable", cache_root)

            publish_status = _publish_staging(staging, cache_root, staged_cache.identity)
            if publish_status == "published":
                try:
                    os.fchmod(staging.root_fd, 0o555)
                except OSError:
                    return _result("cache-unavailable", cache_root)
                published_state, published_cache = _validated_cache(cache_root)
                if (
                    published_state != "valid"
                    or published_cache is None
                    or published_cache.identity != staged_cache.identity
                ):
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
            os.close(staging.root_fd)
            os.close(staging.parent_fd)
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
    cache_state, cache = _validated_cache(cache_root)
    if cache_state == "missing":
        if asset_source is None:
            return _result("cache-missing", cache_root)
        seeded = seed_shared_assets(asset_source, cache_root)
        if seeded.status not in {"seeded", "cache-exists"}:
            return seeded
        cache_state, cache = _validated_cache(cache_root)

    if cache_state != "valid" or cache is None:
        return _result("invalid-cache", cache_root)
    cache_files = cache.files
    cache_identity = cache.identity

    target_fd = _open_directory(target)
    if target_fd is None:
        return _result("invalid-target", cache_root)

    linked: list[Path] = []
    skipped: list[str] = []
    created_links: list[_CreatedLink] = []
    try:
        for cached_file in cache_files:
            if not _cache_identity_matches(cache_root, cache_identity, cached_file):
                _rollback_created_links(created_links)
                return _result("invalid-cache", cache_root)
            parent_fd, parent_relative = _ensure_real_target_parent(
                target_fd,
                cached_file.relative.parts[:-1],
                before_create=lambda: _cache_identity_matches(
                    cache_root, cache_identity, cached_file
                ),
            )
            relative_text = cached_file.relative.as_posix()
            if parent_fd is None:
                if not _cache_identity_matches(cache_root, cache_identity, cached_file):
                    _rollback_created_links(created_links)
                    return _result("invalid-cache", cache_root)
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
                    if not _cache_identity_matches(cache_root, cache_identity, cached_file):
                        _rollback_created_links(created_links)
                        return _result("invalid-cache", cache_root)
                    try:
                        os.symlink(expected_link, filename, dir_fd=parent_fd)
                    except FileExistsError:
                        skipped.append(relative_text)
                    except OSError:
                        skipped.append(relative_text)
                    else:
                        created_identity = _symlink_identity(
                            parent_fd, filename, expected_link
                        )
                        if created_identity is None:
                            skipped.append(relative_text)
                            continue
                        created_links.append(
                            _CreatedLink(
                                parent_fd=os.dup(parent_fd),
                                name=filename,
                                target=expected_link,
                                identity=created_identity,
                            )
                        )
                        if not _cache_identity_matches(cache_root, cache_identity, cached_file):
                            _rollback_created_links(created_links)
                            return _result("invalid-cache", cache_root)
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
        if not _cache_identity_matches(cache_root, cache_identity):
            _rollback_created_links(created_links)
            return _result("invalid-cache", cache_root)
    finally:
        os.close(target_fd)
        for created_link in created_links:
            os.close(created_link.parent_fd)

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
    staging_fd: int,
) -> dict[str, object] | None:
    manifest_files: list[dict[str, object]] = []
    for source_file in source_files:
        input_fd = _open_expected_source_file(source_fd, source_file)
        if input_fd is None:
            return None
        parent_fd, _ = _ensure_real_target_parent(
            staging_fd, ("files", *source_file.relative.parts[:-1])
        )
        if parent_fd is None:
            os.close(input_fd)
            return None
        try:
            digest = hashlib.sha256()
            output_fd = os.open(
                source_file.relative.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent_fd,
            )
        except OSError:
            os.close(input_fd)
            os.close(parent_fd)
            return None
        try:
            while chunk := os.read(input_fd, _BUFFER_SIZE):
                digest.update(chunk)
                _write_all(output_fd, chunk)
            os.fchmod(output_fd, 0o444 | (source_file.mode & 0o111))
        except OSError:
            return None
        finally:
            os.close(output_fd)
            os.close(input_fd)
            os.close(parent_fd)
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


def _write_all(fd: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(fd, content[offset:])
        if written <= 0:
            raise OSError("short write")
        offset += written


def _write_manifest(staging_fd: int, manifest: dict[str, object]) -> bool:
    try:
        manifest_fd = os.open(
            "manifest.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=staging_fd,
        )
    except OSError:
        return False
    try:
        _write_all(
            manifest_fd,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        os.fchmod(manifest_fd, 0o444)
    except OSError:
        return False
    finally:
        os.close(manifest_fd)
    return True


def _seal_cache_directories(staging_fd: int, *, include_root: bool = True) -> bool:
    """Seal a descriptor-bound staging tree without following its pathname."""
    try:
        with os.scandir(os.dup(staging_fd)) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError:
        return False
    for entry in entries:
        try:
            entry_stat = entry.stat(follow_symlinks=False)
        except OSError:
            return False
        if stat.S_ISREG(entry_stat.st_mode):
            continue
        if not stat.S_ISDIR(entry_stat.st_mode) or stat.S_ISLNK(entry_stat.st_mode):
            return False
        child_fd, status = _open_child_directory(staging_fd, entry.name)
        if child_fd is None or status != "ok":
            return False
        try:
            child_stat = os.fstat(child_fd)
            if (child_stat.st_dev, child_stat.st_ino) != (entry_stat.st_dev, entry_stat.st_ino):
                return False
            if not _seal_cache_directories(child_fd):
                return False
        except OSError:
            return False
        finally:
            os.close(child_fd)
    if include_root:
        try:
            os.fchmod(staging_fd, 0o555)
        except OSError:
            return False
    return True


def _make_staging_directory(cache_root: Path) -> _Staging | None:
    parent = cache_root.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    parent_fd = _open_directory(parent)
    if parent_fd is None:
        return None
    try:
        parent_stat = os.fstat(parent_fd)
    except OSError:
        os.close(parent_fd)
        return None
    for _ in range(64):
        name = f".{cache_root.name}.staging-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        except OSError:
            os.close(parent_fd)
            return None
        root_fd, status = _open_child_directory(parent_fd, name)
        if root_fd is None or status != "ok":
            os.close(parent_fd)
            return None
        try:
            root_stat = os.fstat(root_fd)
        except OSError:
            os.close(root_fd)
            os.close(parent_fd)
            return None
        return _Staging(
            parent_fd=parent_fd,
            parent_identity=(parent_stat.st_dev, parent_stat.st_ino),
            root_fd=root_fd,
            root_identity=(root_stat.st_dev, root_stat.st_ino),
            name=name,
        )
    os.close(parent_fd)
    return None


def _validated_cache(cache_root: Path) -> tuple[str, _ValidatedCache | None]:
    try:
        os.lstat(cache_root)
    except FileNotFoundError:
        return "missing", None
    except OSError:
        return "invalid", None
    root_fd = _open_directory(cache_root)
    if root_fd is None:
        return "invalid", None
    try:
        return _validated_cache_fd(root_fd)
    finally:
        os.close(root_fd)


def _validated_cache_fd(
    root_fd: int,
    *,
    allow_writable_root: bool = False,
) -> tuple[str, _ValidatedCache | None]:
    try:
        root_stat = os.fstat(root_fd)
    except OSError:
        return "invalid", None
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or (not allow_writable_root and root_stat.st_mode & 0o222)
    ):
        return "invalid", None
    manifest_fd = _open_regular_child(root_fd, "manifest.json")
    if manifest_fd is None:
        return "invalid", None
    try:
        manifest_stat = os.fstat(manifest_fd)
        if (
            not stat.S_ISREG(manifest_stat.st_mode)
            or manifest_stat.st_mode & 0o222
        ):
            return "invalid", None
        content = _read_all(manifest_fd)
        manifest = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "invalid", None
    finally:
        os.close(manifest_fd)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != CACHE_SCHEMA_VERSION:
        return "invalid", None
    if manifest.get("platform") != _platform_identity():
        return "invalid", None
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        return "invalid", None

    cache_files: list[_AssetFile] = []
    identities: dict[Path, tuple[int, int]] = {}
    seen: set[str] = set()
    for raw_file in raw_files:
        parsed = _parse_manifest_file(raw_file)
        if parsed is None:
            return "invalid", None
        path_text = parsed.relative.as_posix()
        if path_text in seen:
            return "invalid", None
        seen.add(path_text)
        file_identity = _validated_cached_file_fd(root_fd, parsed)
        if file_identity is None:
            return "invalid", None
        cache_files.append(parsed)
        identities[parsed.relative] = file_identity
    if [item.relative.as_posix() for item in cache_files] != sorted(seen):
        return "invalid", None
    return (
        "valid",
        _ValidatedCache(
            files=tuple(cache_files),
            identity=_CacheIdentity(
                root_device=root_stat.st_dev,
                root_inode=root_stat.st_ino,
                manifest_device=manifest_stat.st_dev,
                manifest_inode=manifest_stat.st_ino,
                files=identities,
            ),
        ),
    )


def _read_all(fd: int) -> bytes:
    chunks: list[bytes] = []
    while chunk := os.read(fd, _BUFFER_SIZE):
        chunks.append(chunk)
    return b"".join(chunks)


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


def _validated_cached_file_fd(
    root_fd: int,
    cached_file: _AssetFile,
) -> tuple[int, int] | None:
    file_fd = _open_cache_file(root_fd, cached_file.relative)
    if file_fd is None:
        return None
    try:
        file_stat = os.fstat(file_fd)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_size != cached_file.size_bytes
            or file_stat.st_mode & 0o222
        ):
            return None
        digest = hashlib.sha256()
        while chunk := os.read(file_fd, _BUFFER_SIZE):
            digest.update(chunk)
        if digest.hexdigest() != cached_file.sha256:
            return None
        return file_stat.st_dev, file_stat.st_ino
    except OSError:
        return None
    finally:
        os.close(file_fd)


def _open_cache_file(root_fd: int, relative: Path) -> int | None:
    current_fd = os.dup(root_fd)
    try:
        for component in ("files", *relative.parts[:-1]):
            child_fd, status = _open_child_directory(current_fd, component)
            if child_fd is None or status != "ok":
                return None
            try:
                child_stat = os.fstat(child_fd)
            except OSError:
                os.close(child_fd)
                return None
            if child_stat.st_mode & 0o222:
                os.close(child_fd)
                return None
            os.close(current_fd)
            current_fd = child_fd
        return _open_regular_child(current_fd, relative.name)
    finally:
        os.close(current_fd)


def _cache_identity_matches(
    cache_root: Path,
    identity: _CacheIdentity,
    cached_file: _AssetFile | None = None,
) -> bool:
    root_fd = _open_directory(cache_root)
    if root_fd is None:
        return False
    try:
        root_stat = os.fstat(root_fd)
        if (
            root_stat.st_mode & 0o222
            or (root_stat.st_dev, root_stat.st_ino)
            != (identity.root_device, identity.root_inode)
        ):
            return False
        manifest_fd = _open_regular_child(root_fd, "manifest.json")
        if manifest_fd is None:
            return False
        try:
            manifest_stat = os.fstat(manifest_fd)
            if (
                manifest_stat.st_mode & 0o222
                or (manifest_stat.st_dev, manifest_stat.st_ino)
                != (identity.manifest_device, identity.manifest_inode)
            ):
                return False
        except OSError:
            return False
        finally:
            os.close(manifest_fd)
        relatives = (
            (cached_file.relative,)
            if cached_file is not None
            else tuple(identity.files)
        )
        for relative in relatives:
            expected_identity = identity.files.get(relative)
            if expected_identity is None:
                return False
            file_fd = _open_cache_file(root_fd, relative)
            if file_fd is None:
                return False
            try:
                file_stat = os.fstat(file_fd)
                if (
                    not stat.S_ISREG(file_stat.st_mode)
                    or file_stat.st_mode & 0o222
                    or (file_stat.st_dev, file_stat.st_ino) != expected_identity
                ):
                    return False
            except OSError:
                return False
            finally:
                os.close(file_fd)
        return True
    except OSError:
        return False
    finally:
        os.close(root_fd)


def _ensure_real_target_parent(
    target_fd: int,
    parent_parts: tuple[str, ...],
    *,
    before_create: Callable[[], bool] | None = None,
) -> tuple[int | None, Path]:
    current_fd = os.dup(target_fd)
    relative = Path()
    try:
        for component in parent_parts:
            child_fd, status = _open_child_directory(current_fd, component)
            if status == "missing":
                if before_create is not None and not before_create():
                    os.close(current_fd)
                    return None, relative
                try:
                    os.mkdir(component, mode=0o755, dir_fd=current_fd)
                except FileExistsError:
                    pass
                except OSError:
                    os.close(current_fd)
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


def _symlink_identity(
    parent_fd: int,
    name: str,
    expected_target: str,
) -> tuple[int, int] | None:
    try:
        entry_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        target = os.readlink(name, dir_fd=parent_fd)
    except OSError:
        return None
    if not stat.S_ISLNK(entry_stat.st_mode) or target != expected_target:
        return None
    return entry_stat.st_dev, entry_stat.st_ino


def _unlink_expected_symlink(
    parent_fd: int,
    name: str,
    expected_target: str,
    expected_identity: tuple[int, int],
) -> bool:
    """Retain a link when POSIX cannot unlink it by verified identity.

    ``unlinkat`` accepts only a pathname.  Once a caller has checked that name,
    another process can replace it before the unlink, so an attempted rollback
    could delete user data.  There is no macOS/Linux inode-conditional unlink
    primitive, therefore fail closed and leave the invocation-created link in
    place for explicit operator cleanup.
    """
    if _symlink_identity(parent_fd, name, expected_target) != expected_identity:
        return False
    return False


def _rollback_created_links(created_links: list[_CreatedLink]) -> None:
    for created_link in reversed(created_links):
        _unlink_expected_symlink(
            created_link.parent_fd,
            created_link.name,
            created_link.target,
            created_link.identity,
        )


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


def _open_regular_child(parent_fd: int, name: str) -> int | None:
    try:
        fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
    except OSError:
        return None
    try:
        opened = os.fstat(fd)
    except OSError:
        os.close(fd)
        return None
    if not stat.S_ISREG(opened.st_mode):
        os.close(fd)
        return None
    return fd


def _publish_staging(
    staging: _Staging,
    cache_root: Path,
    expected_identity: _CacheIdentity,
) -> str:
    expected_root = (expected_identity.root_device, expected_identity.root_inode)
    if staging.root_identity != expected_root:
        return "staging-replaced"
    if not _directory_path_matches(cache_root.parent, staging.parent_identity):
        return "unavailable"
    if not _directory_entry_matches(staging.parent_fd, staging.name, expected_root):
        return "staging-replaced"
    result = _rename_no_replace(staging.parent_fd, staging.name, cache_root.name)
    if result == "ok":
        return (
            "published"
            if _directory_entry_matches(staging.parent_fd, cache_root.name, expected_root)
            else "staging-replaced"
        )
    if result == "destination-exists":
        cache_state, _ = _validated_cache(cache_root)
        return "cache-exists" if cache_state == "valid" else "invalid-cache"
    return "unavailable"


def _directory_entry_matches(
    parent_fd: int,
    name: str,
    expected_identity: tuple[int, int],
) -> bool:
    directory_fd, status = _open_child_directory(parent_fd, name)
    if directory_fd is None or status != "ok":
        return False
    try:
        current = os.fstat(directory_fd)
    except OSError:
        return False
    finally:
        os.close(directory_fd)
    return (current.st_dev, current.st_ino) == expected_identity


def _directory_path_matches(path: Path, expected_identity: tuple[int, int]) -> bool:
    directory_fd = _open_directory(path)
    if directory_fd is None:
        return False
    try:
        current = os.fstat(directory_fd)
    except OSError:
        return False
    finally:
        os.close(directory_fd)
    return (current.st_dev, current.st_ino) == expected_identity


def _staging_entry_matches(staging: _Staging) -> bool:
    return _directory_entry_matches(staging.parent_fd, staging.name, staging.root_identity)


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
        # renameat2(RENAME_NOREPLACE) excludes destination replacement but
        # does not provide the source nofollow guarantee required to publish
        # an untrusted directory entry.  Fail closed instead of emulating it.
        return "unsupported"
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
