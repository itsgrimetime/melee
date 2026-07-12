"""Local lifecycle policy for fetched remote permuter runs.

Inventory and planning are read-only. Applying a plan always recomputes it
under a lifecycle lock and removes only revalidated, quarantined runs. Manifest
production and CLI integration belong to later lifecycle layers.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import json
import math
import os
import shlex
import shutil
import stat
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal

FETCH_MANIFEST_FILENAME = "melee-agent-local-fetch.json"
FETCH_MANIFEST_KIND = "melee-agent-local-remote-fetch"
FETCH_MANIFEST_VERSION = 1

RETENTION_MARKER_FILENAME = "melee-agent-local-retention.json"
RETENTION_MARKER_KIND = "melee-agent-local-remote-retention"
RETENTION_MARKER_VERSION = 1

DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_MAX_TOTAL_BYTES = 5 * 1024**3
DEFAULT_REMOTE_STATUS_TIMEOUT = 15.0
DEFAULT_REMOTE_PROBE_WORKERS = 8
REMOTE_DETAIL_LIMIT = 500
REMOTE_SESSION_HEADER = "__MELEE_TMUX_SESSIONS_V1_BEGIN__"
REMOTE_SESSION_TRAILER = "__MELEE_TMUX_SESSIONS_V1_END__"
REMOTE_TMUX_MISSING_SENTINEL = "__MELEE_TMUX_MISSING__"
LIFECYCLE_LOCK_FILENAME = ".melee-agent-local-remote-runs.lock"
QUARANTINE_PREFIX = ".melee-agent-local-remote-run-quarantine-"

REMOTE_FETCH_WARNING_FILENAME = "remote-fetch-warning.json"
CANDIDATE_AUDIT_FILENAME = "candidate_audit.json"
CANDIDATE_STATUS_FILENAME = "melee-agent-candidate-status.json"

RemoteState = Literal["unprobed", "active", "stopped", "unknown"]
GitRunner = Callable[..., subprocess.CompletedProcess[str]]
TrackedState = Callable[[Path], tuple[bool, bool]]


@dataclass(frozen=True)
class RemoteRunIdentity:
    job_id: str
    function: str
    target: str
    ssh: str
    remote_perm_dir: str
    remote_run_dir: str
    local_perm_dir: str
    tmux_session: str
    threads: int
    mode: str
    created_at: str


@dataclass(frozen=True)
class ManifestRead:
    status: Literal["absent", "complete", "partial", "valid", "invalid"]
    payload: dict[str, Any] | None = None
    detail: str = ""


@dataclass(frozen=True)
class RunProtectionFlags:
    filesystem_error: bool = False
    nested_symlink: bool = False
    nonregular_entry: bool = False
    path_escape: bool = False
    tracked_files: bool = False
    git_check_failed: bool = False
    metadata_invalid: bool = False
    fetch_manifest_invalid: bool = False
    fetch_partial: bool = False
    fetch_warning: bool = False
    fetch_warning_invalid: bool = False
    candidate_audit_invalid: bool = False
    candidate_untriaged: bool = False
    candidate_status_invalid: bool = False
    winner: bool = False
    retention_marker_invalid: bool = False
    explicitly_retained: bool = False


@dataclass(frozen=True)
class InventoryIssue:
    path: Path
    code: str
    detail: str = ""


@dataclass(frozen=True)
class LocalRemoteRunSummary:
    path: Path
    function: str
    job_id: str
    identity: RemoteRunIdentity | None
    total_bytes: int
    latest_activity: float
    device: int
    inode: int
    flags: RunProtectionFlags
    local_reasons: tuple[str, ...]
    metadata_valid: bool
    fetch_manifest_status: str
    retention_marker_status: str
    legacy_fetch: bool
    candidate_audit_valid: bool
    candidate_count: int
    fully_triaged: bool
    winner: bool
    remote_state: RemoteState = "unprobed"
    remote_detail: str = ""

    @property
    def locally_protected(self) -> bool:
        return bool(self.local_reasons)

    @property
    def reasons(self) -> tuple[str, ...]:
        reasons = set(self.local_reasons)
        if self.remote_state == "active":
            reasons.add("remote-active")
        elif self.remote_state in {"unprobed", "unknown"}:
            reasons.add("remote-unknown")
        return tuple(sorted(reasons))

    @property
    def protected(self) -> bool:
        return bool(self.reasons)

    def with_remote_state(
        self,
        state: RemoteState,
        detail: str = "",
    ) -> LocalRemoteRunSummary:
        if state not in {"unprobed", "active", "stopped", "unknown"}:
            raise ValueError(f"invalid remote state: {state}")
        return replace(self, remote_state=state, remote_detail=detail)


@dataclass(frozen=True)
class LocalRemoteRunInventory:
    perm_root: Path
    runs: tuple[LocalRemoteRunSummary, ...]
    issues: tuple[InventoryIssue, ...]

    @property
    def total_bytes(self) -> int:
        return sum(run.total_bytes for run in self.runs)


@dataclass(frozen=True)
class RetentionPlanItem:
    summary: LocalRemoteRunSummary
    disposition: Literal["protected", "eligible", "selected"]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class LocalRemoteRunRetentionPlan:
    generated_at: datetime
    max_age_days: float
    max_total_bytes: int
    total_bytes: int
    protected_bytes: int
    eligible_bytes: int
    selected_bytes: int
    projected_total_bytes: int
    reclaimed_bytes: int
    inventory_complete: bool
    cap_satisfied: bool
    items: tuple[RetentionPlanItem, ...]

    @property
    def protected(self) -> tuple[RetentionPlanItem, ...]:
        return tuple(item for item in self.items if item.disposition == "protected")

    @property
    def eligible(self) -> tuple[RetentionPlanItem, ...]:
        return tuple(item for item in self.items if item.disposition in {"eligible", "selected"})

    @property
    def selected(self) -> tuple[RetentionPlanItem, ...]:
        selected = [item for item in self.items if item.disposition == "selected"]
        return tuple(sorted(selected, key=_plan_item_sort_key))


@dataclass(frozen=True)
class RetentionApplyAction:
    original_path: Path
    quarantine_path: Path | None
    function: str
    job_id: str
    status: Literal["removed", "skipped"]
    reasons: tuple[str, ...]
    planned_bytes: int
    reclaimed_bytes: int


@dataclass(frozen=True)
class LocalRemoteRunRetentionResult:
    status: Literal["completed", "lock-busy", "lock-unavailable"]
    plan: LocalRemoteRunRetentionPlan | None
    actions: tuple[RetentionApplyAction, ...]
    reclaimed_bytes: int
    projected_total_bytes: int
    inventory_complete: bool
    cap_satisfied: bool
    detail: str = ""

    @property
    def planned(self) -> tuple[RetentionApplyAction, ...]:
        return self.actions

    @property
    def removed(self) -> tuple[RetentionApplyAction, ...]:
        return tuple(action for action in self.actions if action.status == "removed")

    @property
    def skipped(self) -> tuple[RetentionApplyAction, ...]:
        return tuple(action for action in self.actions if action.status == "skipped")

    @property
    def planned_count(self) -> int:
        return len(self.planned)

    @property
    def removed_count(self) -> int:
        return len(self.removed)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


@dataclass(frozen=True)
class ManifestWriteResult:
    status: Literal[
        "written",
        "updated",
        "idempotent",
        "invalid",
        "unsafe-existing",
        "publish-failed",
    ]
    path: Path
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"written", "updated", "idempotent"}


@dataclass(frozen=True)
class RetentionMarkerWriteResult:
    status: Literal[
        "written",
        "idempotent",
        "conflict",
        "not-found",
        "duplicate",
        "invalid",
        "unsafe",
        "lock-busy",
        "lock-unavailable",
        "publish-failed",
    ]
    path: Path | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"written", "idempotent"}


@dataclass(frozen=True)
class _TreeFacts:
    total_bytes: int
    latest_activity: float
    nested_symlink: bool
    nonregular_entry: bool
    path_escape: bool
    filesystem_error: bool


def _is_nonbool_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return True


def _valid_ssh_target(value: object) -> bool:
    if not isinstance(value, str) or not value or value.startswith("-"):
        return False
    return all(
        not character.isspace() and character != "\x00" and ord(character) >= 32 and ord(character) != 127
        for character in value
    )


def _read_json_regular(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        file_stat = path.lstat()
    except FileNotFoundError:
        return None, "missing"
    except OSError as exc:
        return None, f"lstat failed: {exc}"
    if not stat.S_ISREG(file_stat.st_mode):
        return None, "not a regular file"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"read failed: {exc}"
    if not isinstance(payload, dict):
        return None, "root must be an object"
    return payload, ""


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _scan_tree(run: Path) -> _TreeFacts:
    try:
        run_stat = run.lstat()
    except OSError:
        return _TreeFacts(0, 0.0, False, False, False, True)
    total_bytes = 0
    regular_mtimes: list[float] = []
    nested_symlink = False
    nonregular_entry = False
    path_escape = False
    filesystem_error = False
    try:
        owned_root = run.resolve(strict=True)
    except (OSError, RuntimeError):
        owned_root = run.absolute()
        filesystem_error = True

    pending = [run]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError:
            filesystem_error = True
            continue
        for entry in entries:
            path = Path(entry.path)
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError:
                filesystem_error = True
                continue
            mode = entry_stat.st_mode
            if stat.S_ISLNK(mode):
                nested_symlink = True
                try:
                    target = path.resolve(strict=False)
                except (OSError, RuntimeError):
                    path_escape = True
                else:
                    if not _within(target, owned_root):
                        path_escape = True
                continue
            if stat.S_ISDIR(mode):
                pending.append(path)
                continue
            if stat.S_ISREG(mode):
                total_bytes += entry_stat.st_size
                regular_mtimes.append(entry_stat.st_mtime)
                continue
            nonregular_entry = True
    latest = max(regular_mtimes, default=run_stat.st_mtime)
    return _TreeFacts(
        total_bytes=total_bytes,
        latest_activity=latest,
        nested_symlink=nested_symlink,
        nonregular_entry=nonregular_entry,
        path_escape=path_escape,
        filesystem_error=filesystem_error,
    )


def read_legacy_metadata(
    run: Path,
    *,
    function: str,
    job_id: str,
) -> tuple[RemoteRunIdentity | None, str]:
    payload, detail = _read_json_regular(run / "remote-run" / "metadata.json")
    if payload is None:
        return None, detail
    string_fields = (
        "job_id",
        "function",
        "target",
        "ssh",
        "remote_perm_dir",
        "remote_run_dir",
        "local_perm_dir",
        "tmux_session",
        "mode",
        "created_at",
    )
    if any(not isinstance(payload.get(key), str) or not str(payload[key]).strip() for key in string_fields):
        return None, "metadata string fields are missing or invalid"
    if not _valid_ssh_target(payload["ssh"]):
        return None, "metadata ssh target is not a safe single token"
    threads = payload.get("threads")
    if not _is_nonbool_int(threads) or int(threads) <= 0:
        return None, "metadata threads must be a positive integer"
    if payload["job_id"] != job_id or payload["function"] != function:
        return None, "metadata identity contradicts owned path"
    function_dir = run.parent.parent
    local_perm_raw = Path(str(payload["local_perm_dir"])).expanduser()
    if not local_perm_raw.is_absolute():
        return None, "metadata local path must be absolute"
    try:
        local_perm_dir = local_perm_raw.resolve(strict=False)
        expected_local = function_dir.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, "metadata local path cannot be resolved"
    if local_perm_dir != expected_local:
        return None, "metadata local path contradicts owned path"
    remote_run = PurePosixPath(str(payload["remote_run_dir"]))
    remote_perm = PurePosixPath(str(payload["remote_perm_dir"]))
    if not remote_run.is_absolute() or not remote_perm.is_absolute():
        return None, "metadata remote paths must be absolute"
    if remote_run.name != job_id:
        return None, "metadata remote run path contradicts job id"
    if remote_run.parent.name != "remote-runs":
        return None, "metadata remote run path is outside remote-runs"
    expected_remote_perm = remote_run / "nonmatchings" / function
    if remote_perm != expected_remote_perm:
        return None, "metadata remote permuter path contradicts identity"
    if not _valid_timestamp(payload["created_at"]):
        return None, "metadata created_at is invalid"
    identity = RemoteRunIdentity(
        job_id=job_id,
        function=function,
        target=str(payload["target"]),
        ssh=str(payload["ssh"]),
        remote_perm_dir=str(payload["remote_perm_dir"]),
        remote_run_dir=str(payload["remote_run_dir"]),
        local_perm_dir=str(payload["local_perm_dir"]),
        tmux_session=str(payload["tmux_session"]),
        threads=int(threads),
        mode=str(payload["mode"]),
        created_at=str(payload["created_at"]),
    )
    return identity, ""


def _identity_matches(payload: dict[str, Any], identity: RemoteRunIdentity) -> bool:
    return all(
        payload.get(key) == getattr(identity, key)
        for key in (
            "job_id",
            "function",
            "target",
            "ssh",
            "remote_perm_dir",
            "remote_run_dir",
            "local_perm_dir",
            "tmux_session",
            "threads",
            "mode",
            "created_at",
        )
    )


def read_fetch_manifest(
    run: Path,
    *,
    identity: RemoteRunIdentity | None,
    candidate_count: int,
) -> ManifestRead:
    path = run / FETCH_MANIFEST_FILENAME
    payload, detail = _read_json_regular(path)
    if payload is None:
        if detail == "missing":
            return ManifestRead("absent")
        return ManifestRead("invalid", detail=detail)
    if identity is None:
        return ManifestRead("invalid", payload, "metadata identity unavailable")
    if (
        payload.get("kind") != FETCH_MANIFEST_KIND
        or not _is_nonbool_int(payload.get("version"))
        or payload.get("version") != FETCH_MANIFEST_VERSION
        or not _identity_matches(payload, identity)
        or not _valid_timestamp(payload.get("fetched_at"))
    ):
        return ManifestRead("invalid", payload, "manifest schema or identity invalid")
    state = payload.get("state")
    if state not in {"complete", "partial"}:
        return ManifestRead("invalid", payload, "manifest state invalid")
    audit = payload.get("candidate_audit")
    if not isinstance(audit, dict):
        return ManifestRead("invalid", payload, "manifest audit summary missing")
    total = audit.get("total")
    if not _is_nonbool_int(total) or total != candidate_count:
        return ManifestRead("invalid", payload, "manifest audit total invalid")
    return ManifestRead(state, payload)


def _utc_timestamp(clock: Callable[[], object]) -> tuple[str | None, str]:
    if not callable(clock):
        return None, "clock must be callable"
    try:
        value = clock()
    except Exception as exc:
        return None, f"clock failed: {exc}"
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None, "clock must return a timezone-aware datetime"
    try:
        utc = value.astimezone(UTC)
    except (OSError, OverflowError, ValueError) as exc:
        return None, f"clock returned an invalid datetime: {exc}"
    return utc.isoformat().replace("+00:00", "Z"), ""


def _manifest_owned_run_root(
    run: Path,
    identity: RemoteRunIdentity,
) -> tuple[Path | None, str]:
    local_raw = Path(identity.local_perm_dir).expanduser()
    if not local_raw.is_absolute():
        return None, "identity local permuter path is not absolute"
    function_dir = local_raw.absolute()
    if (
        function_dir.name != identity.function
        or function_dir.parent.name != "nonmatchings"
    ):
        return None, "identity local permuter path is outside nonmatchings"
    perm_root = function_dir.parent.parent
    expected = function_dir / "remote-runs" / identity.job_id
    if run.expanduser().absolute() != expected:
        return None, "run path contradicts identity"
    for owner in (
        perm_root,
        function_dir.parent,
        function_dir,
        function_dir / "remote-runs",
        expected,
    ):
        try:
            owner_stat = owner.lstat()
            resolved = owner.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            return None, f"owned path unavailable: {exc}"
        if (
            stat.S_ISLNK(owner_stat.st_mode)
            or not stat.S_ISDIR(owner_stat.st_mode)
            or resolved != owner
            or not _within(owner, perm_root)
        ):
            return None, f"unsafe owned path: {owner}"
    return perm_root, ""


def _normalized_audit_summary(
    run: Path,
    candidate_audit: object,
) -> tuple[dict[str, object] | None, str]:
    if not isinstance(candidate_audit, dict):
        return None, "candidate audit must be an object"
    total = candidate_audit.get("total")
    if not _is_nonbool_int(total) or total < 0:
        return None, "candidate audit total must be a nonnegative integer"
    sources, scan_failed = _actual_candidate_sources(run)
    if scan_failed or len(sources) != total:
        return None, "candidate audit total does not match local sources"
    candidates = candidate_audit.get("candidates")
    if candidates is not None and (
        not isinstance(candidates, list) or len(candidates) != total
    ):
        return None, "candidate audit entries do not match total"

    compact: dict[str, object] = {"total": total}
    for source_key, target_key in (
        ("by_status", "by_status"),
        ("by_semantic_risk_bucket", "by_semantic_risk_bucket"),
    ):
        raw_counts = candidate_audit.get(source_key)
        if raw_counts is None:
            continue
        if not isinstance(raw_counts, dict) or any(
            not isinstance(key, str)
            or not key
            or not _is_nonbool_int(value)
            or value < 0
            for key, value in raw_counts.items()
        ):
            return None, f"candidate audit {source_key} is invalid"
        if sum(raw_counts.values()) != total:
            return None, f"candidate audit {source_key} does not match total"
        compact[target_key] = dict(sorted(raw_counts.items()))
    return compact, ""


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_local_fetch_manifest(
    run: Path,
    *,
    identity: RemoteRunIdentity,
    state: Literal["complete", "partial"],
    candidate_audit: object,
    clock: Callable[[], object] | None = None,
) -> ManifestWriteResult:
    """Atomically publish fetched-run provenance under its owned run path."""
    manifest = run.expanduser().absolute() / FETCH_MANIFEST_FILENAME
    if state not in {"complete", "partial"}:
        return ManifestWriteResult("invalid", manifest, "invalid fetch state")
    _, detail = _manifest_owned_run_root(run, identity)
    if detail:
        return ManifestWriteResult("invalid", manifest, detail)
    try:
        run_stat = run.lstat()
    except OSError as exc:
        return ManifestWriteResult("invalid", manifest, _bounded_detail(exc))
    run_identity = (run_stat.st_dev, run_stat.st_ino)
    compact_audit, detail = _normalized_audit_summary(run, candidate_audit)
    if compact_audit is None:
        return ManifestWriteResult("invalid", manifest, detail)
    fetched_at, detail = _utc_timestamp(_utcnow if clock is None else clock)
    if fetched_at is None:
        return ManifestWriteResult("invalid", manifest, detail)
    payload: dict[str, object] = {
        "kind": FETCH_MANIFEST_KIND,
        "version": FETCH_MANIFEST_VERSION,
        **{
            field: getattr(identity, field)
            for field in (
                "job_id",
                "function",
                "target",
                "ssh",
                "remote_perm_dir",
                "remote_run_dir",
                "local_perm_dir",
                "tmux_session",
                "threads",
                "mode",
                "created_at",
            )
        },
        "fetched_at": fetched_at,
        "state": state,
        "candidate_audit": compact_audit,
    }

    existing_stat: os.stat_result | None = None
    existing, existing_detail = _read_json_regular(manifest)
    if existing is not None:
        try:
            existing_stat = manifest.lstat()
        except OSError as exc:
            return ManifestWriteResult("unsafe-existing", manifest, str(exc))
        if existing == payload:
            return ManifestWriteResult("idempotent", manifest)
        existing_read = read_fetch_manifest(
            run,
            identity=identity,
            candidate_count=int(compact_audit["total"]),
        )
        if existing_read.status not in {"complete", "partial"}:
            return ManifestWriteResult(
                "unsafe-existing",
                manifest,
                "existing manifest identity or schema conflicts",
            )
    elif existing_detail != "missing":
        return ManifestWriteResult("unsafe-existing", manifest, existing_detail)

    temp = run / f".melee-agent-local-fetch.{uuid.uuid4().hex}.tmp"
    descriptor: int | None = None
    temp_identity: tuple[int, int] | None = None
    published = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temp, flags, 0o600)
        temp_stat = os.fstat(descriptor)
        temp_identity = (temp_stat.st_dev, temp_stat.st_ino)
        encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        written, written_detail = _read_json_regular(temp)
        if written != payload:
            return ManifestWriteResult(
                "publish-failed",
                manifest,
                written_detail or "temporary manifest readback mismatch",
            )
        _, ownership_detail = _manifest_owned_run_root(run, identity)
        current_run = run.lstat()
        if (
            ownership_detail
            or (current_run.st_dev, current_run.st_ino) != run_identity
        ):
            return ManifestWriteResult(
                "publish-failed",
                manifest,
                ownership_detail or "owned run changed before publication",
            )
        if existing_stat is None:
            _rename_no_replace(temp, manifest)
            status: Literal["written", "updated"] = "written"
        else:
            current = manifest.lstat()
            if (
                not stat.S_ISREG(current.st_mode)
                or (current.st_dev, current.st_ino)
                != (existing_stat.st_dev, existing_stat.st_ino)
            ):
                return ManifestWriteResult(
                    "publish-failed",
                    manifest,
                    "existing manifest changed before update",
                )
            os.replace(temp, manifest)
            status = "updated"
        published = True
        _fsync_directory(run)
        readback = read_fetch_manifest(
            run,
            identity=identity,
            candidate_count=int(compact_audit["total"]),
        )
        if readback.payload != payload:
            raise RuntimeError("published manifest readback mismatch")
        return ManifestWriteResult(status, manifest)
    except Exception as exc:
        if published and temp_identity is not None:
            try:
                published_stat = manifest.lstat()
                if (
                    stat.S_ISREG(published_stat.st_mode)
                    and (published_stat.st_dev, published_stat.st_ino)
                    == temp_identity
                ):
                    manifest.unlink()
                    _fsync_directory(run)
            except OSError:
                pass
        return ManifestWriteResult(
            "publish-failed",
            manifest,
            _bounded_detail(type(exc).__name__, exc),
        )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            leftover = temp.lstat()
        except OSError:
            pass
        else:
            if (
                temp_identity is not None
                and stat.S_ISREG(leftover.st_mode)
                and (leftover.st_dev, leftover.st_ino) == temp_identity
            ):
                try:
                    temp.unlink()
                except OSError:
                    pass


def read_retention_marker(
    run: Path,
    *,
    function: str,
    job_id: str,
) -> ManifestRead:
    payload, detail = _read_json_regular(run / RETENTION_MARKER_FILENAME)
    if payload is None:
        if detail == "missing":
            return ManifestRead("absent")
        return ManifestRead("invalid", detail=detail)
    if (
        payload.get("kind") != RETENTION_MARKER_KIND
        or not _is_nonbool_int(payload.get("version"))
        or payload.get("version") != RETENTION_MARKER_VERSION
        or payload.get("job_id") != job_id
        or payload.get("function") != function
        or not isinstance(payload.get("reason"), str)
        or not str(payload["reason"]).strip()
        or not _valid_timestamp(payload.get("created_at"))
    ):
        return ManifestRead("invalid", payload, "retention marker invalid")
    return ManifestRead("valid", payload)


def _actual_candidate_sources(run: Path) -> tuple[tuple[Path, ...], bool]:
    sources: list[Path] = []
    try:
        entries = sorted(os.scandir(run), key=lambda item: item.name)
    except OSError:
        return (), True
    scan_failed = False
    for entry in entries:
        if not entry.name.startswith("output-"):
            continue
        try:
            is_directory = entry.is_dir(follow_symlinks=False)
        except OSError:
            scan_failed = True
            continue
        if not is_directory:
            continue
        source = Path(entry.path) / "source.c"
        try:
            source_stat = source.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            scan_failed = True
            continue
        if stat.S_ISREG(source_stat.st_mode):
            sources.append(source)
    return tuple(sorted(sources, key=lambda path: path.parent.name)), scan_failed


def _candidate_audit_valid(
    run: Path,
    *,
    function: str,
    sources: tuple[Path, ...],
) -> tuple[bool, bool]:
    payload, _ = _read_json_regular(run / CANDIDATE_AUDIT_FILENAME)
    if payload is None:
        return False, False
    total = payload.get("total")
    candidates = payload.get("candidates")
    if (
        payload.get("function") != function
        or not _is_nonbool_int(total)
        or total != len(sources)
        or not isinstance(candidates, list)
        or len(candidates) != len(sources)
    ):
        return False, False
    audit_root = payload.get("root")
    if not isinstance(audit_root, str) or not Path(audit_root).is_absolute():
        return False, False
    normalized_root = Path(os.path.abspath(audit_root))
    expected_root = run.absolute()
    if normalized_root != expected_root:
        return False, not _within(normalized_root, expected_root)
    expected = {str(path.absolute()) for path in sources}
    actual: list[str] = []
    for item in candidates:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            return False, False
        candidate_path = Path(str(item["path"]))
        if not candidate_path.is_absolute():
            return False, False
        normalized = str(Path(os.path.abspath(candidate_path)))
        if not _within(Path(normalized), run.absolute()):
            return False, True
        actual.append(normalized)
    valid = len(set(actual)) == len(actual) and set(actual) == expected
    return valid, False


def _candidate_status(
    source: Path,
    *,
    run: Path,
    function: str,
) -> tuple[bool, bool, bool]:
    """Return (fully_triaged, winner, invalid)."""
    payload, detail = _read_json_regular(source.parent / CANDIDATE_STATUS_FILENAME)
    if payload is None:
        return False, False, detail != "missing"
    if payload.get("source") not in {"triage", "verify"}:
        return False, False, False
    candidate = payload.get("candidate")
    if not isinstance(candidate, str):
        return False, False, True
    candidate_path = Path(candidate)
    if not candidate_path.is_absolute():
        return False, False, True
    normalized_candidate = Path(os.path.abspath(candidate_path))
    expected_candidate = source.absolute()
    if (
        not _within(normalized_candidate, run.absolute())
        or normalized_candidate != expected_candidate
        or payload.get("function") != function
    ):
        return False, False, True
    if not isinstance(payload.get("status"), str) or not str(payload["status"]).strip():
        return False, False, True

    kept = payload.get("kept", False)
    if "kept" in payload and not isinstance(kept, bool):
        return False, False, True
    winner = kept is True
    for key, threshold in (("delta", 0.0), ("match_pct", 100.0)):
        value = payload.get(key)
        if value is None:
            continue
        if not _is_finite_number(value):
            return False, False, True
        is_winner = float(value) > threshold if key == "delta" else float(value) >= threshold
        if is_winner:
            winner = True
    return True, winner, False


def _read_fetch_warning(
    run: Path,
    *,
    job_id: str,
) -> Literal["absent", "partial", "invalid"]:
    payload, detail = _read_json_regular(run / REMOTE_FETCH_WARNING_FILENAME)
    if payload is None:
        return "absent" if detail == "missing" else "invalid"
    if payload.get("status") != "partial" or payload.get("job_id") != job_id:
        return "invalid"
    return "partial"


def _run_git(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, **kwargs)


def _tracked_paths(
    perm_root: Path,
    git_runner: GitRunner,
) -> tuple[tuple[Path, ...], bool]:
    argv = ["git", "ls-files", "-z", "--"]
    try:
        result = git_runner(
            argv,
            cwd=perm_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return (), True
    try:
        returncode = result.returncode
        raw_stdout = result.stdout
    except (AttributeError, TypeError):
        return (), True
    if returncode != 0:
        return (), True
    stdout = raw_stdout.decode(errors="replace") if isinstance(raw_stdout, bytes) else raw_stdout
    if not isinstance(stdout, str):
        return (), True
    tracked: list[Path] = []
    for raw in stdout.split("\0"):
        if not raw:
            continue
        relative = Path(raw)
        if relative.is_absolute() or ".." in relative.parts:
            return (), True
        tracked.append(perm_root / relative)
    return tuple(sorted(tracked, key=str)), False


def _reasons(flags: RunProtectionFlags) -> tuple[str, ...]:
    mapping = {
        "filesystem_error": "filesystem-error",
        "nested_symlink": "nested-symlink",
        "nonregular_entry": "nonregular-entry",
        "path_escape": "path-escape",
        "tracked_files": "tracked-files",
        "git_check_failed": "git-check-failed",
        "metadata_invalid": "metadata-invalid",
        "fetch_manifest_invalid": "fetch-manifest-invalid",
        "fetch_partial": "fetch-partial",
        "fetch_warning": "fetch-warning",
        "fetch_warning_invalid": "fetch-warning-invalid",
        "candidate_audit_invalid": "candidate-audit-invalid",
        "candidate_untriaged": "candidate-untriaged",
        "candidate_status_invalid": "candidate-status-invalid",
        "winner": "winner",
        "retention_marker_invalid": "retention-marker-invalid",
        "explicitly_retained": "explicitly-retained",
    }
    return tuple(sorted(reason for field, reason in mapping.items() if getattr(flags, field)))


def _summarize_run(
    run: Path,
    *,
    function: str,
    job_id: str,
    tracked_state: TrackedState,
) -> LocalRemoteRunSummary:
    run_stat = run.lstat()
    tree = _scan_tree(run)
    identity, _ = read_legacy_metadata(
        run,
        function=function,
        job_id=job_id,
    )
    metadata_valid = identity is not None
    sources, candidate_scan_failed = _actual_candidate_sources(run)
    audit_valid, audit_path_escape = _candidate_audit_valid(
        run,
        function=function,
        sources=sources,
    )

    all_triaged = audit_valid
    winner = False
    status_invalid = False
    for source in sources:
        triaged, source_winner, invalid = _candidate_status(
            source,
            run=run,
            function=function,
        )
        all_triaged = all_triaged and triaged
        winner = winner or source_winner
        status_invalid = status_invalid or invalid

    fetch_manifest = read_fetch_manifest(
        run,
        identity=identity,
        candidate_count=len(sources),
    )
    retention = read_retention_marker(
        run,
        function=function,
        job_id=job_id,
    )
    warning = _read_fetch_warning(run, job_id=job_id)
    tracked, git_failed = tracked_state(run)
    flags = RunProtectionFlags(
        filesystem_error=tree.filesystem_error or candidate_scan_failed,
        nested_symlink=tree.nested_symlink,
        nonregular_entry=tree.nonregular_entry,
        path_escape=tree.path_escape or audit_path_escape,
        tracked_files=tracked,
        git_check_failed=git_failed,
        metadata_invalid=not metadata_valid,
        fetch_manifest_invalid=fetch_manifest.status == "invalid",
        fetch_partial=(fetch_manifest.status == "partial" or warning == "partial"),
        fetch_warning=warning == "partial",
        fetch_warning_invalid=warning == "invalid",
        candidate_audit_invalid=not audit_valid,
        candidate_untriaged=not all_triaged,
        candidate_status_invalid=status_invalid,
        winner=winner,
        retention_marker_invalid=retention.status == "invalid",
        explicitly_retained=retention.status == "valid",
    )
    return LocalRemoteRunSummary(
        path=run,
        function=function,
        job_id=job_id,
        identity=identity,
        total_bytes=tree.total_bytes,
        latest_activity=tree.latest_activity,
        device=run_stat.st_dev,
        inode=run_stat.st_ino,
        flags=flags,
        local_reasons=_reasons(flags),
        metadata_valid=metadata_valid,
        fetch_manifest_status=fetch_manifest.status,
        retention_marker_status=retention.status,
        legacy_fetch=fetch_manifest.status == "absent",
        candidate_audit_valid=audit_valid,
        candidate_count=len(sources),
        fully_triaged=all_triaged,
        winner=winner,
    )


def inventory_local_remote_runs(
    perm_root: Path,
    *,
    git_runner: GitRunner = _run_git,
) -> LocalRemoteRunInventory:
    """Inventory direct locally fetched remote-run directories without mutation."""
    requested_root = perm_root.expanduser().absolute()
    issues: list[InventoryIssue] = []
    try:
        root_stat = requested_root.lstat()
    except OSError as exc:
        return LocalRemoteRunInventory(
            requested_root,
            (),
            (InventoryIssue(requested_root, "root-unavailable", str(exc)),),
        )
    if stat.S_ISLNK(root_stat.st_mode):
        return LocalRemoteRunInventory(
            requested_root,
            (),
            (InventoryIssue(requested_root, "owner-symlink"),),
        )
    if not stat.S_ISDIR(root_stat.st_mode):
        return LocalRemoteRunInventory(
            requested_root,
            (),
            (InventoryIssue(requested_root, "root-not-directory"),),
        )
    try:
        resolved_root = requested_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return LocalRemoteRunInventory(
            requested_root,
            (),
            (InventoryIssue(requested_root, "root-unavailable", str(exc)),),
        )

    nonmatchings = resolved_root / "nonmatchings"
    try:
        nonmatchings_stat = nonmatchings.lstat()
    except FileNotFoundError:
        return LocalRemoteRunInventory(resolved_root, (), ())
    except OSError as exc:
        return LocalRemoteRunInventory(
            resolved_root,
            (),
            (InventoryIssue(nonmatchings, "owner-unreadable", str(exc)),),
        )
    if stat.S_ISLNK(nonmatchings_stat.st_mode):
        return LocalRemoteRunInventory(
            resolved_root,
            (),
            (InventoryIssue(nonmatchings, "owner-symlink"),),
        )
    if not stat.S_ISDIR(nonmatchings_stat.st_mode):
        return LocalRemoteRunInventory(
            resolved_root,
            (),
            (InventoryIssue(nonmatchings, "owner-not-directory"),),
        )
    try:
        resolved_nonmatchings = nonmatchings.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return LocalRemoteRunInventory(
            resolved_root,
            (),
            (InventoryIssue(nonmatchings, "owner-unreadable", str(exc)),),
        )
    if not _within(resolved_nonmatchings, resolved_root) or resolved_nonmatchings != nonmatchings:
        return LocalRemoteRunInventory(
            resolved_root,
            (),
            (InventoryIssue(nonmatchings, "path-escape"),),
        )
    try:
        function_entries = sorted(os.scandir(nonmatchings), key=lambda item: item.name)
    except OSError as exc:
        return LocalRemoteRunInventory(
            resolved_root,
            (),
            (InventoryIssue(nonmatchings, "owner-unreadable", str(exc)),),
        )

    runs: list[LocalRemoteRunSummary] = []
    tracked_cache: tuple[tuple[Path, ...], bool] | None = None
    tracked_ancestors: frozenset[Path] | None = None

    def tracked_state(run: Path) -> tuple[bool, bool]:
        nonlocal tracked_ancestors, tracked_cache
        if tracked_cache is None:
            tracked_cache = _tracked_paths(resolved_root, git_runner)
        tracked_paths, failed = tracked_cache
        if failed:
            return False, True
        if not _within(run, resolved_root):
            return False, True
        if tracked_ancestors is None:
            ancestors: set[Path] = set()
            for tracked_path in tracked_paths:
                current = tracked_path
                while _within(current, resolved_root):
                    ancestors.add(current)
                    if current == resolved_root:
                        break
                    current = current.parent
            tracked_ancestors = frozenset(ancestors)
        return run in tracked_ancestors, False

    for function_entry in function_entries:
        function_path = Path(function_entry.path)
        if function_entry.is_symlink():
            issues.append(InventoryIssue(function_path, "owner-symlink"))
            continue
        if not function_entry.is_dir(follow_symlinks=False):
            continue
        remote_runs = function_path / "remote-runs"
        try:
            remote_stat = remote_runs.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            issues.append(InventoryIssue(remote_runs, "owner-unreadable", str(exc)))
            continue
        if stat.S_ISLNK(remote_stat.st_mode):
            issues.append(InventoryIssue(remote_runs, "owner-symlink"))
            continue
        if not stat.S_ISDIR(remote_stat.st_mode):
            issues.append(InventoryIssue(remote_runs, "owner-not-directory"))
            continue
        try:
            job_entries = sorted(os.scandir(remote_runs), key=lambda item: item.name)
        except OSError as exc:
            issues.append(InventoryIssue(remote_runs, "owner-unreadable", str(exc)))
            continue
        for job_entry in job_entries:
            job_path = Path(job_entry.path)
            if job_entry.name.startswith(QUARANTINE_PREFIX):
                issues.append(
                    InventoryIssue(
                        job_path,
                        "quarantine-present",
                        "leftover quarantine is not a deletion candidate",
                    )
                )
                continue
            if job_entry.is_symlink():
                issues.append(InventoryIssue(job_path, "owner-symlink"))
                continue
            if not job_entry.is_dir(follow_symlinks=False):
                issues.append(
                    InventoryIssue(
                        job_path,
                        "unexpected-run-entry",
                        "direct remote-runs entry is not a directory",
                    )
                )
                continue
            try:
                runs.append(
                    _summarize_run(
                        job_path,
                        function=function_entry.name,
                        job_id=job_entry.name,
                        tracked_state=tracked_state,
                    )
                )
            except OSError as exc:
                issues.append(InventoryIssue(job_path, "run-unreadable", str(exc)))
    runs.sort(key=lambda run: (run.function, run.job_id, str(run.path)))
    issues.sort(key=lambda issue: (str(issue.path), issue.code, issue.detail))
    return LocalRemoteRunInventory(
        perm_root=resolved_root,
        runs=tuple(runs),
        issues=tuple(issues),
    )


def _production_remote_runner(
    argv: list[str],
    *,
    check: bool,
    timeout: float,
) -> Any:
    # Import lazily so the future fetch-manifest producer can depend on this
    # lifecycle module without creating an import cycle.
    from . import permuter_remote  # noqa: PLC0415

    return permuter_remote.run_command(
        argv,
        check=check,
        timeout=timeout,
    )


def _bounded_detail(*values: object) -> str:
    text = " ".join(part for value in values if value is not None for part in [" ".join(str(value).split())] if part)
    if not text:
        text = "remote activity probe failed without diagnostic output"
    return text[:REMOTE_DETAIL_LIMIT]


def _remote_tmux_inventory_argv(ssh: str) -> list[str]:
    script = "\n".join(
        [
            "set +e",
            "export LC_ALL=C",
            "if ! command -v tmux >/dev/null 2>&1; then",
            f"  printf '%s\\n' {shlex.quote(REMOTE_TMUX_MISSING_SENTINEL)} >&2",
            "  exit 127",
            "fi",
            "tmux_output=$(tmux list-sessions -F '#S' 2>&1)",
            "tmux_status=$?",
            'if [ "$tmux_status" -ne 0 ]; then',
            "  if printf '%s\\n' \"$tmux_output\" | grep -Eiq 'no server running|no sessions'; then",
            "    tmux_output=''",
            "  else",
            "    printf '%s\\n' \"$tmux_output\" >&2",
            '    exit "$tmux_status"',
            "  fi",
            "fi",
            f"printf '%s\\n' {shlex.quote(REMOTE_SESSION_HEADER)}",
            'if [ -n "$tmux_output" ]; then printf \'%s\\n\' "$tmux_output"; fi',
            f"printf '%s\\n' {shlex.quote(REMOTE_SESSION_TRAILER)}",
        ]
    )
    return ["ssh", "--", ssh, "sh -lc " + shlex.quote(script)]


def _parse_remote_sessions(stdout: object) -> tuple[frozenset[str] | None, str]:
    if not isinstance(stdout, str):
        return None, "remote tmux output was not text"
    lines = stdout.splitlines()
    if len(lines) < 2 or lines[0] != REMOTE_SESSION_HEADER or lines[-1] != REMOTE_SESSION_TRAILER:
        return None, "malformed remote tmux inventory"
    sessions = lines[1:-1]
    if any(
        not session
        or session != session.strip()
        or any(character.isspace() for character in session)
        or session in {REMOTE_SESSION_HEADER, REMOTE_SESSION_TRAILER}
        for session in sessions
    ):
        return None, "malformed remote tmux session name"
    if len(set(sessions)) != len(sessions):
        return None, "duplicate remote tmux session name"
    return frozenset(sessions), ""


def _probe_one_host(
    ssh: str,
    *,
    runner: Callable[..., Any],
    timeout: float,
) -> tuple[frozenset[str] | None, str]:
    argv = _remote_tmux_inventory_argv(ssh)
    try:
        result = runner(argv, check=False, timeout=timeout)
        returncode = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except Exception as exc:
        return None, _bounded_detail(type(exc).__name__, exc)
    if returncode != 0:
        detail = _bounded_detail(stderr, stdout)
        if REMOTE_TMUX_MISSING_SENTINEL in detail:
            detail = "remote tmux tooling is unavailable"
        return None, detail
    if stderr:
        return None, _bounded_detail("unexpected remote probe stderr", stderr)
    return _parse_remote_sessions(stdout)


def _valid_positive_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def probe_remote_run_activity(
    inventory: LocalRemoteRunInventory,
    *,
    runner: Callable[..., Any] = _production_remote_runner,
    timeout: float = DEFAULT_REMOTE_STATUS_TIMEOUT,
    max_workers: int = DEFAULT_REMOTE_PROBE_WORKERS,
) -> LocalRemoteRunInventory:
    """Return an inventory with active/stopped/unknown remote states."""
    if not _valid_positive_number(timeout):
        raise ValueError("timeout must be a positive finite number")
    if not _is_nonbool_int(max_workers) or max_workers <= 0 or max_workers > 64:
        raise ValueError("max_workers must be an integer from 1 through 64")

    hosts: dict[str, list[LocalRemoteRunSummary]] = {}
    for run in inventory.runs:
        if run.identity is not None and _valid_ssh_target(run.identity.ssh):
            hosts.setdefault(run.identity.ssh, []).append(run)

    host_results: dict[str, tuple[frozenset[str] | None, str]] = {}
    sorted_hosts = sorted(hosts)
    if sorted_hosts:
        worker_count = min(max_workers, len(sorted_hosts))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    _probe_one_host,
                    ssh,
                    runner=runner,
                    timeout=float(timeout),
                ): ssh
                for ssh in sorted_hosts
            }
            for future in as_completed(futures):
                ssh = futures[future]
                try:
                    host_results[ssh] = future.result()
                except Exception as exc:
                    host_results[ssh] = (
                        None,
                        _bounded_detail(type(exc).__name__, exc),
                    )

    updated: list[LocalRemoteRunSummary] = []
    for run in inventory.runs:
        if run.identity is None:
            updated.append(
                run.with_remote_state(
                    "unknown",
                    "missing valid remote job identity",
                )
            )
            continue
        if not _valid_ssh_target(run.identity.ssh):
            updated.append(
                run.with_remote_state(
                    "unknown",
                    "invalid ssh target in remote job identity",
                )
            )
            continue
        sessions, detail = host_results.get(
            run.identity.ssh,
            (None, "remote host probe did not complete"),
        )
        if sessions is None:
            updated.append(run.with_remote_state("unknown", detail))
        elif run.identity.tmux_session in sessions:
            updated.append(run.with_remote_state("active"))
        else:
            updated.append(run.with_remote_state("stopped"))
    return replace(inventory, runs=tuple(updated))


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _retention_sort_key(
    summary: LocalRemoteRunSummary,
) -> tuple[float, str, str, str]:
    return (
        summary.latest_activity,
        summary.function,
        summary.job_id,
        str(summary.path),
    )


def _plan_item_sort_key(
    item: RetentionPlanItem,
) -> tuple[float, str, str, str]:
    return _retention_sort_key(item.summary)


def _validate_plan_inputs(
    *,
    max_age_days: object,
    max_total_bytes: object,
    clock: Callable[[], object],
) -> tuple[float, int, datetime]:
    if (
        not isinstance(max_age_days, (int, float))
        or isinstance(max_age_days, bool)
        or not math.isfinite(float(max_age_days))
        or float(max_age_days) < 0
    ):
        raise ValueError("max_age_days must be a nonnegative finite number")
    if not _is_nonbool_int(max_total_bytes) or int(max_total_bytes) < 0:
        raise ValueError("max_total_bytes must be a nonnegative integer")
    if not callable(clock):
        raise ValueError("clock must be callable")
    try:
        now = clock()
    except Exception as exc:
        raise ValueError(f"clock failed: {exc}") from exc
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    try:
        offset = now.utcoffset()
    except Exception as exc:
        raise ValueError(f"clock timezone failed: {exc}") from exc
    if offset is None:
        raise ValueError("clock must return a timezone-aware datetime")
    try:
        now.timestamp()
    except (OSError, OverflowError, ValueError) as exc:
        raise ValueError(f"clock returned an invalid datetime: {exc}") from exc
    return float(max_age_days), int(max_total_bytes), now


def plan_local_remote_run_retention(
    inventory: LocalRemoteRunInventory,
    *,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    clock: Callable[[], object] = _utcnow,
) -> LocalRemoteRunRetentionPlan:
    """Build a deterministic, read-only retention plan for local run evidence."""
    age_days, byte_cap, now = _validate_plan_inputs(
        max_age_days=max_age_days,
        max_total_bytes=max_total_bytes,
        clock=clock,
    )
    for run in inventory.runs:
        if not _is_nonbool_int(run.total_bytes) or run.total_bytes < 0 or not _is_finite_number(run.latest_activity):
            raise ValueError(f"invalid run summary accounting: {run.path}")

    total_bytes = sum(run.total_bytes for run in inventory.runs)
    protected = [run for run in inventory.runs if run.reasons]
    eligible = [run for run in inventory.runs if not run.reasons]
    ordered_eligible = sorted(eligible, key=_retention_sort_key)
    cutoff = now.timestamp() - age_days * 86400

    selected_reasons: dict[Path, tuple[str, ...]] = {}
    for run in ordered_eligible:
        if run.latest_activity < cutoff:
            selected_reasons[run.path] = ("age",)
    reclaimed = sum(run.total_bytes for run in ordered_eligible if run.path in selected_reasons)
    projected = total_bytes - reclaimed
    if projected > byte_cap:
        for run in ordered_eligible:
            if run.path in selected_reasons:
                continue
            selected_reasons[run.path] = ("cap",)
            reclaimed += run.total_bytes
            projected = total_bytes - reclaimed
            if projected <= byte_cap:
                break

    items: list[RetentionPlanItem] = []
    for run in inventory.runs:
        if run.reasons:
            items.append(RetentionPlanItem(run, "protected", run.reasons))
        elif run.path in selected_reasons:
            items.append(
                RetentionPlanItem(
                    run,
                    "selected",
                    selected_reasons[run.path],
                )
            )
        else:
            items.append(RetentionPlanItem(run, "eligible", ()))
    selected_bytes = sum(item.summary.total_bytes for item in items if item.disposition == "selected")
    return LocalRemoteRunRetentionPlan(
        generated_at=now,
        max_age_days=age_days,
        max_total_bytes=byte_cap,
        total_bytes=total_bytes,
        protected_bytes=sum(run.total_bytes for run in protected),
        eligible_bytes=sum(run.total_bytes for run in eligible),
        selected_bytes=selected_bytes,
        projected_total_bytes=total_bytes - selected_bytes,
        reclaimed_bytes=selected_bytes,
        inventory_complete=not inventory.issues,
        cap_satisfied=(not inventory.issues and total_bytes - selected_bytes <= byte_cap),
        items=tuple(items),
    )


def _targeted_tracked_state(
    perm_root: Path,
    run: Path,
    git_runner: GitRunner,
) -> tuple[bool, bool]:
    try:
        relative = run.relative_to(perm_root)
    except ValueError:
        return False, True
    argv = ["git", "ls-files", "-z", "--", str(relative)]
    try:
        result = git_runner(
            argv,
            cwd=perm_root,
            capture_output=True,
            text=True,
            check=False,
        )
        returncode = result.returncode
        stdout = result.stdout
    except Exception:
        return False, True
    if returncode != 0:
        return False, True
    if isinstance(stdout, bytes):
        stdout = stdout.decode(errors="replace")
    if not isinstance(stdout, str):
        return False, True
    for raw in stdout.split("\0"):
        if not raw:
            continue
        tracked = Path(raw)
        if tracked.is_absolute() or ".." in tracked.parts:
            return False, True
        if _within(perm_root / tracked, run):
            return True, False
    return False, False


def _same_planned_run(
    planned: LocalRemoteRunSummary,
    current: LocalRemoteRunSummary,
) -> bool:
    return (
        current.path == planned.path
        and current.function == planned.function
        and current.job_id == planned.job_id
        and current.identity == planned.identity
        and current.device == planned.device
        and current.inode == planned.inode
        and current.total_bytes == planned.total_bytes
        and current.latest_activity == planned.latest_activity
        and not current.local_reasons
    )


def _owned_parents_are_safe(
    perm_root: Path,
    root_identity: tuple[int, int],
    summary: LocalRemoteRunSummary,
) -> bool:
    expected_parent = perm_root / "nonmatchings" / summary.function / "remote-runs"
    if summary.path != expected_parent / summary.job_id:
        return False
    for index, owner in enumerate(
        (
            perm_root,
            perm_root / "nonmatchings",
            perm_root / "nonmatchings" / summary.function,
            expected_parent,
        )
    ):
        try:
            owner_stat = owner.lstat()
            resolved = owner.resolve(strict=True)
        except (OSError, RuntimeError):
            return False
        if (
            stat.S_ISLNK(owner_stat.st_mode)
            or not stat.S_ISDIR(owner_stat.st_mode)
            or resolved != owner
            or not _within(owner, perm_root)
        ):
            return False
        if index == 0 and (owner_stat.st_dev, owner_stat.st_ino) != root_identity:
            return False
    return True


def _validate_quarantine(
    original: Path,
    quarantine: Path,
    planned: LocalRemoteRunSummary,
    perm_root: Path,
    root_identity: tuple[int, int],
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    try:
        original.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        reasons.append("original-state-unknown")
    else:
        reasons.append("original-still-present")
    try:
        quarantine_stat = quarantine.lstat()
    except OSError:
        reasons.append("quarantine-unavailable")
        return False, tuple(sorted(set(reasons)))
    if not stat.S_ISDIR(quarantine_stat.st_mode):
        reasons.append("quarantine-not-directory")
    if quarantine_stat.st_dev != planned.device or quarantine_stat.st_ino != planned.inode:
        reasons.append("quarantine-identity-mismatch")
    if quarantine.parent != original.parent or not _owned_parents_are_safe(perm_root, root_identity, planned):
        reasons.append("quarantine-owner-mismatch")
    tree = _scan_tree(quarantine)
    if tree.filesystem_error:
        reasons.append("quarantine-filesystem-error")
    if tree.nested_symlink:
        reasons.append("quarantine-nested-symlink")
    if tree.nonregular_entry:
        reasons.append("quarantine-nonregular-entry")
    if tree.path_escape:
        reasons.append("quarantine-path-escape")
    marker = quarantine / RETENTION_MARKER_FILENAME
    try:
        marker.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        reasons.append("quarantine-marker-state-unknown")
    else:
        reasons.append("quarantine-retention-marker")
    return not reasons, tuple(sorted(set(reasons)))


def _restore_quarantine(
    original: Path,
    quarantine: Path,
    rename: Callable[[Path, Path], Any],
) -> tuple[str, ...]:
    try:
        original.lstat()
    except FileNotFoundError:
        try:
            rename(quarantine, original)
        except Exception as exc:
            return ("restore-failed", _bounded_detail(type(exc).__name__, exc))
        return ("restored",)
    except OSError as exc:
        return ("restore-unsafe", _bounded_detail(type(exc).__name__, exc))
    return ("restore-original-present",)


def _rename_no_replace(source: Path, destination: Path) -> None:
    """Atomically rename a directory without replacing an existing path."""
    libc = ctypes.CDLL(None, use_errno=True)
    encoded_source = os.fsencode(source)
    encoded_destination = os.fsencode(destination)
    if sys.platform == "darwin":
        rename_exclusive = 0x00000004
        renamex = libc.renamex_np
        renamex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex.restype = ctypes.c_int
        result = renamex(
            encoded_source,
            encoded_destination,
            rename_exclusive,
        )
    elif sys.platform.startswith("linux"):
        at_fdcwd = -100
        rename_noreplace = 1
        renameat2 = libc.renameat2
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            at_fdcwd,
            encoded_source,
            at_fdcwd,
            encoded_destination,
            rename_noreplace,
        )
    else:
        raise OSError(
            errno.ENOTSUP,
            "atomic no-replace rename is unavailable",
            str(destination),
        )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


@dataclass
class _LifecycleLock:
    perm_root: Path
    root_identity: tuple[int, int]
    descriptor: int

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1


def _acquire_lifecycle_lock(
    perm_root: Path,
) -> tuple[
    _LifecycleLock | None,
    Literal["locked", "lock-busy", "lock-unavailable"],
    str,
]:
    requested_root = perm_root.expanduser().absolute()
    try:
        root_stat = requested_root.lstat()
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            return None, "lock-unavailable", "unsafe perm root"
        resolved_root = requested_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return None, "lock-unavailable", _bounded_detail(exc)
    if resolved_root != requested_root:
        return None, "lock-unavailable", "perm root path is not canonical"

    lock_path = resolved_root / LIFECYCLE_LOCK_FILENAME
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        return None, "lock-unavailable", _bounded_detail(exc)
    keep_open = False
    try:
        lock_stat = os.fstat(descriptor)
        try:
            lock_path_stat = lock_path.lstat()
        except OSError as exc:
            return None, "lock-unavailable", _bounded_detail(exc)
        if (
            not stat.S_ISREG(lock_stat.st_mode)
            or stat.S_ISLNK(lock_path_stat.st_mode)
            or (lock_path_stat.st_dev, lock_path_stat.st_ino)
            != (lock_stat.st_dev, lock_stat.st_ino)
            or lock_stat.st_nlink != 1
            or lock_stat.st_uid != os.geteuid()
            or lock_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            return None, "lock-unavailable", "unsafe lifecycle lock file"
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            return None, "lock-busy", _bounded_detail(exc)
        except OSError as exc:
            return None, "lock-unavailable", _bounded_detail(exc)
        keep_open = True
        return (
            _LifecycleLock(
                resolved_root,
                (root_stat.st_dev, root_stat.st_ino),
                descriptor,
            ),
            "locked",
            "",
        )
    finally:
        if not keep_open:
            os.close(descriptor)


def _locate_owned_job(
    perm_root: Path,
    job_id: str,
) -> tuple[
    Literal["found", "not-found", "duplicate", "unsafe"],
    Path | None,
    str,
]:
    nonmatchings = perm_root / "nonmatchings"
    try:
        owner_stat = nonmatchings.lstat()
    except FileNotFoundError:
        return "not-found", None, "job id was not found"
    except OSError as exc:
        return "unsafe", None, _bounded_detail(exc)
    if stat.S_ISLNK(owner_stat.st_mode) or not stat.S_ISDIR(owner_stat.st_mode):
        return "unsafe", None, "unsafe nonmatchings owner"
    try:
        function_entries = sorted(os.scandir(nonmatchings), key=lambda entry: entry.name)
    except OSError as exc:
        return "unsafe", None, _bounded_detail(exc)
    matches: list[Path] = []
    unsafe_match = False
    for function_entry in function_entries:
        try:
            if function_entry.is_symlink() or not function_entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        remote_runs = Path(function_entry.path) / "remote-runs"
        try:
            remote_stat = remote_runs.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            unsafe_match = True
            continue
        if stat.S_ISLNK(remote_stat.st_mode) or not stat.S_ISDIR(remote_stat.st_mode):
            unsafe_match = True
            continue
        candidate = remote_runs / job_id
        try:
            candidate_stat = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            unsafe_match = True
            continue
        if stat.S_ISLNK(candidate_stat.st_mode) or not stat.S_ISDIR(candidate_stat.st_mode):
            unsafe_match = True
            continue
        matches.append(candidate)
    if len(matches) > 1:
        return "duplicate", None, "job id matches multiple owned runs"
    if len(matches) == 1:
        return "found", matches[0], ""
    if unsafe_match:
        return "unsafe", None, "job ownership could not be proven"
    return "not-found", None, "job id was not found"


def _publish_retention_marker(
    run: Path,
    marker: Path,
    payload: dict[str, object],
    *,
    identity: RemoteRunIdentity,
    run_identity: tuple[int, int],
) -> tuple[bool, str]:
    temp = run / f".melee-agent-local-retention.{uuid.uuid4().hex}.tmp"
    descriptor: int | None = None
    temp_identity: tuple[int, int] | None = None
    published = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temp, flags, 0o600)
        temp_stat = os.fstat(descriptor)
        temp_identity = (temp_stat.st_dev, temp_stat.st_ino)
        encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        written, detail = _read_json_regular(temp)
        if written != payload:
            return False, detail or "temporary marker readback mismatch"
        _, detail = _manifest_owned_run_root(run, identity)
        if detail:
            return False, detail
        current = run.lstat()
        if (
            not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != run_identity
        ):
            return False, "owned run changed before marker publication"
        try:
            marker.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            return False, _bounded_detail(exc)
        else:
            return False, "retention marker appeared before publication"
        _rename_no_replace(temp, marker)
        published = True
        _fsync_directory(run)
        readback = read_retention_marker(
            run,
            function=identity.function,
            job_id=identity.job_id,
        )
        if readback.status != "valid" or readback.payload != payload:
            raise RuntimeError("published marker readback mismatch")
        return True, ""
    except Exception as exc:
        if published and temp_identity is not None:
            try:
                published_stat = marker.lstat()
                if (
                    stat.S_ISREG(published_stat.st_mode)
                    and (published_stat.st_dev, published_stat.st_ino)
                    == temp_identity
                ):
                    marker.unlink()
                    _fsync_directory(run)
            except OSError:
                pass
        return False, _bounded_detail(type(exc).__name__, exc)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            leftover = temp.lstat()
        except OSError:
            pass
        else:
            if (
                temp_identity is not None
                and stat.S_ISREG(leftover.st_mode)
                and (leftover.st_dev, leftover.st_ino) == temp_identity
            ):
                try:
                    temp.unlink()
                except OSError:
                    pass


def retain_local_remote_run(
    perm_root: Path,
    job_id: str,
    *,
    reason: str,
    clock: Callable[[], object] = _utcnow,
) -> RetentionMarkerWriteResult:
    """Atomically mark exactly one owned local remote run for retention."""
    if (
        not isinstance(job_id, str)
        or not job_id
        or job_id in {".", ".."}
        or any(character.isspace() or ord(character) < 32 for character in job_id)
        or "/" in job_id
        or "\\" in job_id
    ):
        return RetentionMarkerWriteResult("invalid", detail="invalid job id")
    if not isinstance(reason, str) or not reason.strip():
        return RetentionMarkerWriteResult("invalid", detail="reason is required")
    created_at, detail = _utc_timestamp(clock)
    if created_at is None:
        return RetentionMarkerWriteResult("invalid", detail=detail)

    lifecycle_lock, lock_status, lock_detail = _acquire_lifecycle_lock(perm_root)
    if lifecycle_lock is None:
        return RetentionMarkerWriteResult(lock_status, detail=lock_detail)
    try:
        locate_status, run, detail = _locate_owned_job(
            lifecycle_lock.perm_root,
            job_id,
        )
        if run is None:
            return RetentionMarkerWriteResult(locate_status, detail=detail)
        function = run.parent.parent.name
        identity, metadata_detail = read_legacy_metadata(
            run,
            function=function,
            job_id=job_id,
        )
        marker = run / RETENTION_MARKER_FILENAME
        if identity is None:
            return RetentionMarkerWriteResult(
                "invalid",
                marker,
                f"invalid job metadata: {metadata_detail}",
            )
        _, ownership_detail = _manifest_owned_run_root(run, identity)
        if ownership_detail:
            return RetentionMarkerWriteResult("unsafe", marker, ownership_detail)
        try:
            run_stat = run.lstat()
        except OSError as exc:
            return RetentionMarkerWriteResult("unsafe", marker, _bounded_detail(exc))

        existing = read_retention_marker(
            run,
            function=function,
            job_id=job_id,
        )
        if existing.status == "valid":
            if existing.payload is not None and existing.payload.get("reason") == reason:
                return RetentionMarkerWriteResult("idempotent", marker)
            return RetentionMarkerWriteResult(
                "conflict",
                marker,
                "a different retention marker already exists",
            )
        if existing.status != "absent":
            return RetentionMarkerWriteResult(
                "invalid",
                marker,
                existing.detail or "existing retention marker is invalid",
            )
        payload: dict[str, object] = {
            "kind": RETENTION_MARKER_KIND,
            "version": RETENTION_MARKER_VERSION,
            "job_id": job_id,
            "function": function,
            "reason": reason,
            "created_at": created_at,
        }
        published, detail = _publish_retention_marker(
            run,
            marker,
            payload,
            identity=identity,
            run_identity=(run_stat.st_dev, run_stat.st_ino),
        )
        if not published:
            return RetentionMarkerWriteResult("publish-failed", marker, detail)
        return RetentionMarkerWriteResult("written", marker)
    finally:
        lifecycle_lock.close()


def _lock_failure(
    status: Literal["lock-busy", "lock-unavailable"],
    detail: str,
) -> LocalRemoteRunRetentionResult:
    return LocalRemoteRunRetentionResult(
        status=status,
        plan=None,
        actions=(),
        reclaimed_bytes=0,
        projected_total_bytes=0,
        inventory_complete=False,
        cap_satisfied=False,
        detail=detail,
    )


def apply_local_remote_run_retention(
    perm_root: Path,
    *,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    status_timeout: float = DEFAULT_REMOTE_STATUS_TIMEOUT,
    max_workers: int = DEFAULT_REMOTE_PROBE_WORKERS,
    remote_runner: Callable[..., Any] = _production_remote_runner,
    git_runner: GitRunner = _run_git,
    clock: Callable[[], object] = _utcnow,
    rename: Callable[[Path, Path], Any] | None = None,
    remover: Callable[[Path], Any] = shutil.rmtree,
) -> LocalRemoteRunRetentionResult:
    """Recompute and safely apply local remote-run retention under a lock."""
    rename_operation = _rename_no_replace if rename is None else rename
    lifecycle_lock, lock_status, lock_detail = _acquire_lifecycle_lock(perm_root)
    if lifecycle_lock is None:
        return _lock_failure(lock_status, lock_detail)
    resolved_root = lifecycle_lock.perm_root
    root_identity = lifecycle_lock.root_identity
    try:
        inventory = inventory_local_remote_runs(resolved_root, git_runner=git_runner)
        probed = probe_remote_run_activity(
            inventory,
            runner=remote_runner,
            timeout=status_timeout,
            max_workers=max_workers,
        )
        plan = plan_local_remote_run_retention(
            probed,
            max_age_days=max_age_days,
            max_total_bytes=max_total_bytes,
            clock=clock,
        )
        selected = tuple(item.summary for item in plan.selected)
        selected_inventory = LocalRemoteRunInventory(
            perm_root=resolved_root,
            runs=selected,
            issues=(),
        )
        rechecked = (
            probe_remote_run_activity(
                selected_inventory,
                runner=remote_runner,
                timeout=status_timeout,
                max_workers=max_workers,
            )
            if selected
            else selected_inventory
        )
        rechecked_by_path = {run.path: run for run in rechecked.runs}

        actions: list[RetentionApplyAction] = []
        reclaimed = 0
        for planned in selected:
            second = rechecked_by_path.get(planned.path)
            if second is None or second.identity != planned.identity or second.remote_state != "stopped":
                reasons = second.reasons if second is not None else ("remote-missing",)
                actions.append(
                    RetentionApplyAction(
                        planned.path,
                        None,
                        planned.function,
                        planned.job_id,
                        "skipped",
                        reasons or ("remote-mismatch",),
                        planned.total_bytes,
                        0,
                    )
                )
                continue

            try:
                targeted_tracked = _targeted_tracked_state(
                    resolved_root,
                    planned.path,
                    git_runner,
                )
                if not _owned_parents_are_safe(
                    resolved_root,
                    root_identity,
                    planned,
                ):
                    actions.append(
                        RetentionApplyAction(
                            planned.path,
                            None,
                            planned.function,
                            planned.job_id,
                            "skipped",
                            ("ownership-changed",),
                            planned.total_bytes,
                            0,
                        )
                    )
                    continue
                current = _summarize_run(
                    planned.path,
                    function=planned.function,
                    job_id=planned.job_id,
                    tracked_state=lambda _run: targeted_tracked,
                )
            except OSError as exc:
                actions.append(
                    RetentionApplyAction(
                        planned.path,
                        None,
                        planned.function,
                        planned.job_id,
                        "skipped",
                        ("revalidation-failed", _bounded_detail(exc)),
                        planned.total_bytes,
                        0,
                    )
                )
                continue
            if not _same_planned_run(planned, current):
                reasons = current.local_reasons or ("run-changed",)
                actions.append(
                    RetentionApplyAction(
                        planned.path,
                        None,
                        planned.function,
                        planned.job_id,
                        "skipped",
                        reasons,
                        planned.total_bytes,
                        0,
                    )
                )
                continue

            quarantine = planned.path.parent / f"{QUARANTINE_PREFIX}{uuid.uuid4().hex}"
            try:
                quarantine.lstat()
            except FileNotFoundError:
                pass
            except OSError as exc:
                actions.append(
                    RetentionApplyAction(
                        planned.path,
                        quarantine,
                        planned.function,
                        planned.job_id,
                        "skipped",
                        ("quarantine-state-unknown", _bounded_detail(exc)),
                        planned.total_bytes,
                        0,
                    )
                )
                continue
            else:
                actions.append(
                    RetentionApplyAction(
                        planned.path,
                        quarantine,
                        planned.function,
                        planned.job_id,
                        "skipped",
                        ("quarantine-collision",),
                        planned.total_bytes,
                        0,
                    )
                )
                continue
            try:
                rename_operation(planned.path, quarantine)
            except Exception as exc:
                actions.append(
                    RetentionApplyAction(
                        planned.path,
                        quarantine,
                        planned.function,
                        planned.job_id,
                        "skipped",
                        ("rename-failed", _bounded_detail(type(exc).__name__, exc)),
                        planned.total_bytes,
                        0,
                    )
                )
                continue

            quarantine_valid, reasons = _validate_quarantine(
                planned.path,
                quarantine,
                planned,
                resolved_root,
                root_identity,
            )
            if not quarantine_valid:
                ambiguous = {
                    "original-state-unknown",
                    "original-still-present",
                    "quarantine-unavailable",
                    "quarantine-not-directory",
                    "quarantine-identity-mismatch",
                    "quarantine-owner-mismatch",
                }
                restore = (
                    ("restore-skipped-ambiguous",)
                    if ambiguous.intersection(reasons)
                    else _restore_quarantine(
                        planned.path,
                        quarantine,
                        rename_operation,
                    )
                )
                actions.append(
                    RetentionApplyAction(
                        planned.path,
                        quarantine,
                        planned.function,
                        planned.job_id,
                        "skipped",
                        reasons + restore,
                        planned.total_bytes,
                        0,
                    )
                )
                continue
            try:
                remover(quarantine)
            except Exception as exc:
                actions.append(
                    RetentionApplyAction(
                        planned.path,
                        quarantine,
                        planned.function,
                        planned.job_id,
                        "skipped",
                        ("removal-failed", _bounded_detail(type(exc).__name__, exc)),
                        planned.total_bytes,
                        0,
                    )
                )
                continue
            try:
                quarantine.lstat()
            except FileNotFoundError:
                reclaimed += planned.total_bytes
                actions.append(
                    RetentionApplyAction(
                        planned.path,
                        quarantine,
                        planned.function,
                        planned.job_id,
                        "removed",
                        (),
                        planned.total_bytes,
                        planned.total_bytes,
                    )
                )
            except OSError as exc:
                actions.append(
                    RetentionApplyAction(
                        planned.path,
                        quarantine,
                        planned.function,
                        planned.job_id,
                        "skipped",
                        ("removal-state-unknown", _bounded_detail(exc)),
                        planned.total_bytes,
                        0,
                    )
                )
            else:
                actions.append(
                    RetentionApplyAction(
                        planned.path,
                        quarantine,
                        planned.function,
                        planned.job_id,
                        "skipped",
                        ("removal-incomplete",),
                        planned.total_bytes,
                        0,
                    )
                )

        projected = plan.total_bytes - reclaimed
        return LocalRemoteRunRetentionResult(
            status="completed",
            plan=plan,
            actions=tuple(actions),
            reclaimed_bytes=reclaimed,
            projected_total_bytes=projected,
            inventory_complete=plan.inventory_complete,
            cap_satisfied=(plan.inventory_complete and projected <= plan.max_total_bytes),
        )
    finally:
        lifecycle_lock.close()
