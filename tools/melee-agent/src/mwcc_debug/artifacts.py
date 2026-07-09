"""Manifest-owned diagnostic artifact runs.

Each run owns one direct child under ``build/diagnostics/runs``.  Retained
evidence and disposable compiler output are kept separate so finalization can
remove only the latter without relying on caller-provided cleanup paths.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

DEFAULT_ARTIFACT_ROOT = Path("build/diagnostics/runs")
DEFAULT_MAX_AGE_DAYS = 30.0
DEFAULT_MAX_TOTAL_BYTES = 10 * 1024**3
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})

_ACTIVE_STATE = "active"
_MANIFEST_NAME = "manifest.json"
_EVIDENCE_DIRNAME = "evidence"
_TRANSIENT_DIRNAME = "transient"


@dataclass(frozen=True)
class ArtifactRun:
    root: Path
    run_dir: Path
    evidence_dir: Path
    transient_dir: Path
    manifest_path: Path

    def retain_text(self, relative: str, text: str) -> Path:
        """Retain UTF-8 text as evidence owned by this run."""
        destination = _prepare_owned_file(self.evidence_dir, relative)
        destination.write_text(text, encoding="utf-8")
        return destination

    def retain_json(self, relative: str, payload: Mapping[str, Any]) -> Path:
        """Retain JSON evidence owned by this run."""
        destination = _prepare_owned_file(self.evidence_dir, relative)
        destination.write_text(
            json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination

    def retain_file(self, source: Path, relative: str) -> Path:
        """Copy a file into evidence owned by this run."""
        destination = _prepare_owned_file(self.evidence_dir, relative)
        shutil.copy2(source, destination)
        return destination

    def transient_path(self, relative: str) -> Path:
        """Return a validated path for disposable output owned by this run."""
        return _validate_owned_child(self.transient_dir, relative)

    def finalize(
        self,
        state: str,
        *,
        result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Finalize the manifest, preserving evidence and removing transients."""
        if state not in TERMINAL_STATES:
            raise ValueError(f"terminal state required, got {state!r}")

        _validate_run_layout(self)
        manifest = _read_regular_manifest(self.manifest_path)
        if manifest.get("state") != _ACTIVE_STATE:
            raise ValueError("only an active artifact run can be finalized")

        evidence = _regular_file_sizes(self.evidence_dir)
        reclaimed_transient_bytes = _regular_tree_size(self.transient_dir)
        _remove_owned_transient_dir(self)

        manifest.update(
            {
                "state": state,
                "finished_at": _utc_now(),
                "result": dict(result) if result is not None else None,
                "evidence": evidence,
                "reclaimed_transient_bytes": reclaimed_transient_bytes,
            }
        )
        _write_json_atomically(self.manifest_path, manifest)
        return manifest


@dataclass(frozen=True)
class RunSummary:
    run_dir: Path
    state: str
    created_at: str
    finished_at: str | None
    evidence_bytes: int


@dataclass(frozen=True)
class SkippedRun:
    path: Path
    reason: str


@dataclass(frozen=True)
class ArtifactReport:
    artifact_root: Path
    completed_runs: int
    active_runs: int
    completed_bytes: int
    cache_bytes: int
    runs: tuple[RunSummary, ...]
    skipped: tuple[SkippedRun, ...]


@dataclass(frozen=True)
class PrunePlan:
    planned_run_dirs: tuple[Path, ...]
    removed_run_dirs: tuple[Path, ...]
    reclaimed_bytes: int
    skipped: tuple[SkippedRun, ...]


@dataclass(frozen=True)
class _ScannedRun:
    summary: RunSummary
    finished_at: datetime | None


def create_run(
    melee_root: Path,
    *,
    command: Sequence[str],
    artifact_root: Path | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> ArtifactRun:
    """Create a direct-child run directory and its active manifest."""
    root = _resolve_artifact_root(melee_root, artifact_root)
    _create_owned_artifact_root(root, melee_root)

    run_name = f"{datetime.now(UTC):%Y%m%dT%H%M%S.%fZ}-{uuid4().hex}"
    run_dir = root / run_name
    run_dir.mkdir()
    evidence_dir = run_dir / _EVIDENCE_DIRNAME
    transient_dir = run_dir / _TRANSIENT_DIRNAME
    evidence_dir.mkdir()
    transient_dir.mkdir()
    manifest_path = run_dir / _MANIFEST_NAME

    manifest: dict[str, Any] = {
        "state": _ACTIVE_STATE,
        "created_at": _utc_now(),
        "command": list(command),
        "provenance": dict(provenance) if provenance is not None else {},
    }
    _write_json_atomically(manifest_path, manifest)
    return ArtifactRun(
        root=root,
        run_dir=run_dir,
        evidence_dir=evidence_dir,
        transient_dir=transient_dir,
        manifest_path=manifest_path,
    )


def report_runs(
    melee_root: Path,
    *,
    artifact_root: Path | None = None,
) -> ArtifactReport:
    """Report direct-child artifact bundles from current filesystem facts."""
    root = _resolve_artifact_root(melee_root, artifact_root)
    scanned, skipped = _scan_runs(root)
    summaries = tuple(
        item.summary for item in sorted(scanned, key=lambda item: item.summary.run_dir.name)
    )
    completed = [item.summary for item in scanned if item.summary.state in TERMINAL_STATES]
    active = [item.summary for item in scanned if item.summary.state == _ACTIVE_STATE]
    cache_root = _resolve_melee_root(melee_root) / "build" / "mwcc_debug_cache"
    return ArtifactReport(
        artifact_root=root,
        completed_runs=len(completed),
        active_runs=len(active),
        completed_bytes=sum(item.evidence_bytes for item in completed),
        cache_bytes=_regular_tree_size(cache_root),
        runs=summaries,
        skipped=tuple(skipped),
    )


def prune_runs(
    melee_root: Path,
    *,
    artifact_root: Path | None = None,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    apply: bool = False,
) -> PrunePlan:
    """Plan or apply conservative deletion of terminal artifact bundles."""
    if max_age_days < 0:
        raise ValueError("max_age_days must be non-negative")
    if max_total_bytes < 0:
        raise ValueError("max_total_bytes must be non-negative")

    root = _resolve_artifact_root(melee_root, artifact_root)
    scanned, skipped = _scan_runs(root)
    terminal: list[_ScannedRun] = []
    for item in scanned:
        if item.summary.state == _ACTIVE_STATE:
            skipped.append(SkippedRun(item.summary.run_dir, "active"))
        else:
            terminal.append(item)

    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    selected: list[_ScannedRun] = []
    remaining: list[_ScannedRun] = []
    for item in terminal:
        if item.finished_at is None:
            skipped.append(SkippedRun(item.summary.run_dir, "invalid-finished-at"))
        elif item.finished_at < cutoff:
            selected.append(item)
        else:
            remaining.append(item)

    remaining_bytes = sum(item.summary.evidence_bytes for item in remaining)
    for item in sorted(
        remaining,
        key=lambda item: (item.finished_at, item.summary.run_dir.name),
    ):
        if remaining_bytes <= max_total_bytes:
            break
        selected.append(item)
        remaining_bytes -= item.summary.evidence_bytes

    selected_paths = tuple(item.summary.run_dir for item in selected)
    reclaimed_bytes = sum(item.summary.evidence_bytes for item in selected)
    if not apply:
        return PrunePlan(
            planned_run_dirs=selected_paths,
            removed_run_dirs=(),
            reclaimed_bytes=reclaimed_bytes,
            skipped=tuple(skipped),
        )

    removed: list[Path] = []
    for run_dir in selected_paths:
        if _remove_owned_run_dir(root, run_dir):
            removed.append(run_dir)
        else:
            skipped.append(SkippedRun(run_dir, "changed-before-removal"))
    return PrunePlan(
        planned_run_dirs=selected_paths,
        removed_run_dirs=tuple(removed),
        reclaimed_bytes=sum(
            item.summary.evidence_bytes
            for item in selected
            if item.summary.run_dir in removed
        ),
        skipped=tuple(skipped),
    )


def _resolve_melee_root(melee_root: Path) -> Path:
    return Path(melee_root).expanduser().resolve(strict=False)


def _resolve_artifact_root(melee_root: Path, artifact_root: Path | None) -> Path:
    resolved_melee_root = _resolve_melee_root(melee_root)
    candidate = DEFAULT_ARTIFACT_ROOT if artifact_root is None else Path(artifact_root)
    if not candidate.is_absolute():
        candidate = resolved_melee_root / candidate
    resolved_root = candidate.expanduser().resolve(strict=False)
    if not _is_relative_to(resolved_root, resolved_melee_root):
        raise ValueError("artifact root must resolve inside the Melee root")
    return resolved_root


def _create_owned_artifact_root(root: Path, melee_root: Path) -> None:
    resolved_melee_root = _resolve_melee_root(melee_root)
    if not _is_relative_to(root, resolved_melee_root):
        raise ValueError("artifact root must resolve inside the Melee root")
    root.mkdir(parents=True, exist_ok=True)
    _require_directory_not_symlink(root, "artifact root")


def _prepare_owned_file(owner: Path, relative: str) -> Path:
    destination = _validate_owned_child(owner, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    return _validate_owned_child(owner, relative)


def _validate_owned_child(owner: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute() or not relative_path.parts:
        raise ValueError("artifact child path must be a non-empty relative path")
    if ".." in relative_path.parts:
        raise ValueError("artifact child path cannot contain '..'")

    _require_directory_not_symlink(owner, "artifact owner")
    destination = owner / relative_path
    owner_resolved = owner.resolve(strict=False)
    destination_resolved = destination.resolve(strict=False)
    if not _is_relative_to(destination_resolved, owner_resolved):
        raise ValueError("artifact child path escapes its owner")

    current = owner
    for component in relative_path.parts:
        current = current / component
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError("artifact child path cannot traverse a symlink")
    return destination


def _validate_run_layout(run: ArtifactRun) -> None:
    _require_directory_not_symlink(run.root, "artifact root")
    _require_directory_not_symlink(run.run_dir, "artifact run")
    if run.run_dir.parent != run.root:
        raise ValueError("artifact run directory is not a direct child of its root")
    if run.evidence_dir != run.run_dir / _EVIDENCE_DIRNAME:
        raise ValueError("artifact evidence directory is not owned by its run")
    if run.transient_dir != run.run_dir / _TRANSIENT_DIRNAME:
        raise ValueError("artifact transient directory is not owned by its run")
    _require_directory_not_symlink(run.evidence_dir, "artifact evidence directory")
    _require_directory_not_symlink(run.transient_dir, "artifact transient directory")
    if run.manifest_path != run.run_dir / _MANIFEST_NAME:
        raise ValueError("artifact manifest is not owned by its run")
    _require_regular_file_not_symlink(run.manifest_path, "artifact manifest")


def _remove_owned_transient_dir(run: ArtifactRun) -> None:
    _require_directory_not_symlink(run.transient_dir, "artifact transient directory")
    shutil.rmtree(run.transient_dir)


def _write_json_atomically(path: Path, payload: Mapping[str, Any]) -> None:
    _require_directory_not_symlink(path.parent, "manifest parent")
    try:
        current_mode = path.lstat().st_mode
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISLNK(current_mode) or not stat.S_ISREG(current_mode):
            raise ValueError("manifest path must be a regular file")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(dict(payload), temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _read_regular_manifest(path: Path) -> dict[str, Any]:
    _require_regular_file_not_symlink(path, "manifest")
    with path.open(encoding="utf-8") as manifest_file:
        payload = json.load(manifest_file)
    if not isinstance(payload, dict):
        raise ValueError("manifest must contain a JSON object")
    return payload


def _scan_runs(root: Path) -> tuple[list[_ScannedRun], list[SkippedRun]]:
    """Read only valid direct-child manifests without following symlinks."""
    try:
        root_mode = root.lstat().st_mode
    except FileNotFoundError:
        return [], []
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        return [], [SkippedRun(root, "artifact-root-not-directory")]

    scanned: list[_ScannedRun] = []
    skipped: list[SkippedRun] = []
    for entry in sorted(root.iterdir(), key=lambda path: path.name):
        try:
            entry_mode = entry.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(entry_mode):
            skipped.append(SkippedRun(entry, "symlink"))
            continue
        if not stat.S_ISDIR(entry_mode):
            skipped.append(SkippedRun(entry, "not-directory"))
            continue

        manifest_path = entry / _MANIFEST_NAME
        try:
            manifest_mode = manifest_path.lstat().st_mode
        except FileNotFoundError:
            skipped.append(SkippedRun(entry, "missing-manifest"))
            continue
        if stat.S_ISLNK(manifest_mode) or not stat.S_ISREG(manifest_mode):
            skipped.append(SkippedRun(entry, "manifest-not-regular"))
            continue
        try:
            manifest = _read_regular_manifest(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError):
            skipped.append(SkippedRun(entry, "malformed-manifest"))
            continue

        state = manifest.get("state")
        created_at = manifest.get("created_at")
        finished_at = manifest.get("finished_at")
        if state not in TERMINAL_STATES | {_ACTIVE_STATE}:
            skipped.append(SkippedRun(entry, "invalid-state"))
            continue
        if not isinstance(created_at, str):
            skipped.append(SkippedRun(entry, "missing-created-at"))
            continue
        if state in TERMINAL_STATES and not isinstance(finished_at, str):
            skipped.append(SkippedRun(entry, "missing-finished-at"))
            continue
        if state == _ACTIVE_STATE:
            finished_at = None

        scanned.append(
            _ScannedRun(
                summary=RunSummary(
                    run_dir=entry,
                    state=state,
                    created_at=created_at,
                    finished_at=finished_at,
                    evidence_bytes=_regular_tree_size(entry / _EVIDENCE_DIRNAME),
                ),
                finished_at=_parse_utc_timestamp(finished_at),
            )
        )
    return scanned, skipped


def _remove_owned_run_dir(root: Path, run_dir: Path) -> bool:
    """Remove one still-valid direct-child terminal bundle, never a symlink."""
    try:
        root_mode = root.lstat().st_mode
        run_mode = run_dir.lstat().st_mode
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        return False
    if run_dir.parent != root or stat.S_ISLNK(run_mode) or not stat.S_ISDIR(run_mode):
        return False

    manifest_path = run_dir / _MANIFEST_NAME
    try:
        manifest_mode = manifest_path.lstat().st_mode
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(manifest_mode) or not stat.S_ISREG(manifest_mode):
        return False
    try:
        manifest = _read_regular_manifest(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if manifest.get("state") not in TERMINAL_STATES:
        return False

    shutil.rmtree(run_dir)
    return True


def _regular_file_sizes(root: Path) -> dict[str, int]:
    """Return regular-file byte counts below ``root`` without following symlinks."""
    try:
        root_mode = root.lstat().st_mode
    except FileNotFoundError:
        return {}
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        return {}

    sizes: dict[str, int] = {}

    def visit(directory: Path, relative_directory: Path) -> None:
        try:
            entries = list(os.scandir(directory))
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return
        for entry in entries:
            try:
                entry_mode = entry.stat(follow_symlinks=False).st_mode
            except FileNotFoundError:
                continue
            relative_path = relative_directory / entry.name
            if stat.S_ISREG(entry_mode):
                sizes[relative_path.as_posix()] = entry.stat(follow_symlinks=False).st_size
            elif stat.S_ISDIR(entry_mode):
                visit(Path(entry.path), relative_path)

    visit(root, Path())
    return sizes


def _regular_tree_size(root: Path) -> int:
    return sum(_regular_file_sizes(root).values())


def _require_directory_not_symlink(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise ValueError(f"{label} does not exist") from error
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ValueError(f"{label} must be a non-symlink directory")


def _require_regular_file_not_symlink(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise ValueError(f"{label} does not exist") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError(f"{label} must be a regular non-symlink file")


def _parse_utc_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
