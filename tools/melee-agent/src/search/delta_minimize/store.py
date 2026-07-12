"""Atomic, provenance-checked storage for resumable delta-minimize runs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from src.search.store import ArtifactStore

from .contracts import DeltaMinimizeError

_EVIDENCE_SCHEMA = "delta-minimize-evidence.v1"
_CANDIDATE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
_PROVENANCE_FIELDS = frozenset(
    {
        "cflags_hash",
        "compiler_fingerprint",
        "expected_object_hash",
        "objective_manifest_hash",
        "parser_schema_hash",
        "inspector_version",
    }
)
_PARENT_PROVENANCE_FIELDS = _PROVENANCE_FIELDS - {"objective_manifest_hash"}
_INSPECTOR_MODE_SUFFIX = re.compile(r";mode=(?:objobjects|no-objobjects)\Z")


def _json_value(value: Any) -> Any:
    """Return deterministic JSON data, normalizing JSON-compatible map keys."""

    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, (str, int)) or isinstance(key, bool):
                raise TypeError("JSON object keys must be strings or integers")
            text_key = str(key)
            if text_key in normalized:
                raise TypeError(f"duplicate JSON key after normalization: {text_key!r}")
            normalized[text_key] = _json_value(item)
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not (value == value and abs(value) != float("inf")):
            raise ValueError("non-finite values are not valid run-store JSON")
        return value
    raise TypeError(f"unsupported run-store JSON value: {type(value).__name__}")


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    normalized = _json_value(payload)
    return (json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    normalized = _json_value(payload)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _has_parent_reference(path: Path) -> bool:
    return any(part == ".." for part in path.parts)


def _has_symlink_component(path: Path) -> bool:
    absolute = _absolute_lexical(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
        if not current.exists():
            break
    return False


def _require_safe_path(path: Path) -> Path:
    if _has_parent_reference(path) or _has_symlink_component(path):
        raise DeltaMinimizeError("unsafe-store-path", {"path": str(path)})
    return _absolute_lexical(path)


def _mkdir_safe(path: Path) -> None:
    safe = _require_safe_path(path)
    safe.mkdir(parents=True, exist_ok=True)
    if _has_symlink_component(safe) or not safe.is_dir():
        raise DeltaMinimizeError("unsafe-store-path", {"path": str(path)})


def _open_safe_directory(path: Path) -> int:
    safe = _require_safe_path(path)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(safe, flags)
    except OSError as error:
        raise DeltaMinimizeError("unsafe-store-path", {"path": str(path)}) from error
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise DeltaMinimizeError("unsafe-store-path", {"path": str(path)})
    return fd


def _read_regular_bytes(path: Path, *, corruption: str) -> bytes | None:
    """Read a regular file without following its final path component."""

    safe = _require_safe_path(path)
    directory_fd = _open_safe_directory(safe.parent)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            fd = os.open(safe.name, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise DeltaMinimizeError("unsafe-store-path", {"path": str(path)}) from error
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise DeltaMinimizeError(corruption, {"path": str(path)})
            with os.fdopen(fd, "rb") as handle:
                fd = -1
                return handle.read()
        finally:
            if fd >= 0:
                os.close(fd)
    finally:
        os.close(directory_fd)


def _write_bytes_atomic(path: Path, blob: bytes) -> None:
    """Durably replace one regular file through an already-open directory."""

    safe = _require_safe_path(path)
    _mkdir_safe(safe.parent)
    safe = _require_safe_path(safe)
    directory_fd = _open_safe_directory(safe.parent)
    temp_name = f".{safe.name}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = -1
    try:
        fd = os.open(temp_name, flags, 0o600, dir_fd=directory_fd)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        _require_safe_path(safe)
        os.replace(
            temp_name,
            safe.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


@contextmanager
def _exclusive_file_lock(target: Path):
    """Serialize immutable content-addressed writes using a sibling lock."""

    safe_target = _require_safe_path(target)
    _mkdir_safe(safe_target.parent)
    lock_path = _require_safe_path(safe_target.with_name(f".{safe_target.name}.lock"))
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise DeltaMinimizeError("unsafe-store-path", {"path": str(lock_path)}) from error
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        _require_safe_path(safe_target)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Durably replace one JSON file without exposing a partial write."""

    if not isinstance(path, Path) or not isinstance(payload, Mapping):
        raise TypeError("write_json_atomic requires a Path and mapping payload")
    safe_path = _require_safe_path(path)
    _mkdir_safe(safe_path.parent)
    safe_path = _require_safe_path(safe_path)
    blob = _json_bytes(payload)

    fd, raw_temp = tempfile.mkstemp(
        prefix=f".{safe_path.name}.",
        suffix=".tmp",
        dir=safe_path.parent,
    )
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, safe_path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(safe_path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp.unlink(missing_ok=True)


# The shorter name is the public phase-ledger spelling; keep the explicit name
# for callers that want to emphasize replacement semantics.
write_json = write_json_atomic


@dataclass(frozen=True)
class EvidenceKey:
    source_hash: str
    function: str
    cflags_hash: str
    compiler_fingerprint: str
    expected_object_hash: str
    objective_manifest_hash: str
    parser_schema_hash: str
    inspector_version: str

    def __post_init__(self) -> None:
        _validate_key_values(asdict(self))

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:32]


@dataclass(frozen=True)
class ParentEvidenceKey:
    source_hash: str
    function: str
    cflags_hash: str
    compiler_fingerprint: str
    expected_object_hash: str
    parser_schema_hash: str
    inspector_version: str

    def __post_init__(self) -> None:
        _validate_key_values(asdict(self))

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:32]


def _validate_key_values(values: Mapping[str, Any]) -> None:
    if any(type(value) is not str or not value for value in values.values()):
        raise ValueError("evidence key fields must be non-empty strings")


def inspector_version_for_mode(inspector_version: str, include_objobjects: bool) -> str:
    """Bind the evaluator's inspector invocation mode into cache provenance.

    The convention deliberately keeps the version in the existing provenance
    lane so older callers do not need a second, independently mutable mode
    field.  A pre-existing mode suffix is replaced rather than accumulated.
    """

    if not isinstance(inspector_version, str) or not inspector_version:
        raise DeltaMinimizeError("invalid-evidence-provenance")
    if not isinstance(include_objobjects, bool):
        raise DeltaMinimizeError("invalid-evidence-key-input")
    base = _INSPECTOR_MODE_SUFFIX.sub("", inspector_version)
    mode = "objobjects" if include_objobjects else "no-objobjects"
    return f"{base};mode={mode}"


class DeltaRunStore:
    """Own all durable state below one delta-minimize output directory."""

    def __init__(self, root: Path, provenance: Mapping[str, str] | None = None):
        if not isinstance(root, Path):
            raise TypeError("run-store root must be a Path")
        self.root = _require_safe_path(root)
        _mkdir_safe(self.root)
        self.provenance: dict[str, str] = {}
        self._provenance_bound = False
        self.sources = self._initialize_artifact_store()
        if provenance is not None:
            self.bind_provenance(provenance)

    def _initialize_artifact_store(self) -> ArtifactStore:
        """Prepare every legacy ArtifactStore path before its constructor runs."""

        artifact_root = self._safe_path("artifacts")
        _mkdir_safe(artifact_root)
        for directory in ("sources", "manifests", "objects"):
            _mkdir_safe(self._safe_path("artifacts", directory))

        gitignore = self._safe_path("artifacts", ".gitignore")
        with _exclusive_file_lock(gitignore):
            existing = _read_regular_bytes(gitignore, corruption="corrupt-artifact-store")
            if existing != b"*\n":
                _write_bytes_atomic(gitignore, b"*\n")

        # ArtifactStore remains the shared layout/API owner. Its constructor is
        # safe here because every directory and file it may touch now exists and
        # has passed the no-symlink checks above.
        for component in (artifact_root, *(artifact_root / name for name in ("sources", "manifests", "objects"))):
            _require_safe_path(component)
        _require_safe_path(gitignore)
        return ArtifactStore(artifact_root)

    def _safe_path(self, *parts: str) -> Path:
        if any(not isinstance(part, str) or not part or Path(part).name != part for part in parts):
            raise DeltaMinimizeError("unsafe-store-path")
        candidate = self.root.joinpath(*parts)
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise DeltaMinimizeError("unsafe-store-path", {"path": str(candidate)}) from error
        return _require_safe_path(candidate)

    def write_json(self, path: Path | str, payload: Mapping[str, Any]) -> Path:
        target = Path(path)
        if target.is_absolute():
            target = _require_safe_path(target)
            try:
                target.relative_to(self.root)
            except ValueError as error:
                raise DeltaMinimizeError("unsafe-store-path", {"path": str(target)}) from error
        else:
            if _has_parent_reference(target):
                raise DeltaMinimizeError("unsafe-store-path", {"path": str(target)})
            target = self.root / target
        write_json_atomic(target, payload)
        return target

    def put_source(self, source_text: str) -> Path:
        if not isinstance(source_text, str):
            raise TypeError("candidate source must be text")
        blob = source_text.encode()
        digest = hashlib.sha256(blob).hexdigest()[:32]
        path = self._safe_path("artifacts", "sources", f"{digest}.c")
        with _exclusive_file_lock(path):
            existing = _read_regular_bytes(path, corruption="corrupt-source-artifact")
            if existing is not None:
                if existing != blob or hashlib.sha256(existing).hexdigest()[:32] != digest:
                    raise DeltaMinimizeError("corrupt-source-artifact", {"path": str(path)})
                return path
            _write_bytes_atomic(path, blob)
        return path

    def bind_provenance(self, provenance: Mapping[str, str]) -> None:
        values = dict(provenance)
        if set(values) != _PROVENANCE_FIELDS or any(type(value) is not str or not value for value in values.values()):
            raise DeltaMinimizeError(
                "invalid-evidence-provenance",
                {"required": sorted(_PROVENANCE_FIELDS), "provided": sorted(values)},
            )
        if self._provenance_bound and values != self.provenance:
            raise DeltaMinimizeError("evidence-provenance-already-bound")
        self.provenance = values
        self._provenance_bound = True

    def evidence_key(self, candidate: Any, config: Any) -> EvidenceKey:
        if not self._provenance_bound:
            raise DeltaMinimizeError("unbound-evidence-provenance")
        try:
            source_hash = candidate.source_hash
            function = config.function
            include_objobjects = config.include_objobjects
        except AttributeError as error:
            raise DeltaMinimizeError("invalid-evidence-key-input") from error
        return EvidenceKey(
            source_hash=source_hash,
            function=function,
            cflags_hash=self.provenance["cflags_hash"],
            compiler_fingerprint=self.provenance["compiler_fingerprint"],
            expected_object_hash=self.provenance["expected_object_hash"],
            objective_manifest_hash=self.provenance["objective_manifest_hash"],
            parser_schema_hash=self.provenance["parser_schema_hash"],
            inspector_version=inspector_version_for_mode(self.provenance["inspector_version"], include_objobjects),
        )

    def parent_evidence_key(
        self,
        candidate: Any,
        config: Any,
        provenance: Mapping[str, str],
    ) -> ParentEvidenceKey:
        values = dict(provenance)
        if set(values) != _PARENT_PROVENANCE_FIELDS or any(
            type(value) is not str or not value for value in values.values()
        ):
            raise DeltaMinimizeError("invalid-parent-evidence-provenance")
        try:
            return ParentEvidenceKey(
                source_hash=candidate.source_hash,
                function=config.function,
                **{
                    **values,
                    "inspector_version": inspector_version_for_mode(
                        values["inspector_version"], config.include_objobjects
                    ),
                },
            )
        except (AttributeError, TypeError) as error:
            raise DeltaMinimizeError("invalid-evidence-key-input") from error

    def evidence_path(self, key: EvidenceKey) -> Path:
        if not isinstance(key, EvidenceKey):
            raise TypeError("candidate evidence requires EvidenceKey")
        return self._safe_path("evidence", "cache", f"{key.digest()}.json")

    def parent_evidence_path(self, key: ParentEvidenceKey) -> Path:
        if not isinstance(key, ParentEvidenceKey):
            raise TypeError("parent evidence requires ParentEvidenceKey")
        return self._safe_path("evidence", "parents", f"{key.digest()}.json")

    def inspect_output_path(self, candidate_id: str) -> Path:
        if not isinstance(candidate_id, str) or _CANDIDATE_ID.fullmatch(candidate_id) is None:
            raise DeltaMinimizeError("invalid-candidate-id", {"candidate_id": candidate_id})
        return self._safe_path("evidence", candidate_id, "inspect.txt")

    def write_evidence(self, key: EvidenceKey, payload: Mapping[str, Any]) -> Path:
        return self._write_evidence(self.evidence_path(key), "candidate", key.to_dict(), key.digest(), payload)

    def write_parent_evidence(self, key: ParentEvidenceKey, payload: Mapping[str, Any]) -> Path:
        return self._write_evidence(self.parent_evidence_path(key), "parent", key.to_dict(), key.digest(), payload)

    def _write_evidence(
        self,
        path: Path,
        key_type: str,
        key: Mapping[str, str],
        key_digest: str,
        payload: Mapping[str, Any],
    ) -> Path:
        normalized_payload = _json_value(payload)
        if normalized_payload.get("status", "complete") != "complete":
            raise DeltaMinimizeError("incomplete-evidence")
        payload_digest = hashlib.sha256(_canonical_json_bytes(normalized_payload)).hexdigest()
        envelope = {
            "schema_version": _EVIDENCE_SCHEMA,
            "status": "complete",
            "key_type": key_type,
            "key": key,
            "key_digest": key_digest,
            "payload_digest": payload_digest,
            "payload": normalized_payload,
        }
        normalized_envelope = _json_value(envelope)
        with _exclusive_file_lock(path):
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as error:
                    raise DeltaMinimizeError("corrupt-cached-evidence") from error
                if existing != normalized_envelope:
                    raise DeltaMinimizeError("immutable-evidence-conflict")
                return path
            write_json_atomic(path, normalized_envelope)
        return path

    def load_evidence(self, key: EvidenceKey) -> dict[str, Any] | None:
        try:
            path = self.evidence_path(key)
        except DeltaMinimizeError:
            return None
        return self._load_evidence(path, "candidate", key.to_dict(), key.digest())

    def invalidate_evidence(self, key: EvidenceKey) -> None:
        """Remove a cache envelope whose retained artifacts are no longer valid."""

        self._invalidate_evidence_path(self.evidence_path(key))

    def invalidate_parent_evidence(self, key: ParentEvidenceKey) -> None:
        """Remove parent evidence after its retained artifacts become stale."""

        self._invalidate_evidence_path(self.parent_evidence_path(key))

    def _invalidate_evidence_path(self, path: Path) -> None:
        with _exclusive_file_lock(path):
            safe = _require_safe_path(path)
            directory_fd = _open_safe_directory(safe.parent)
            try:
                try:
                    os.unlink(safe.name, dir_fd=directory_fd)
                except FileNotFoundError:
                    return
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

    def load_parent_evidence(self, key: ParentEvidenceKey) -> dict[str, Any] | None:
        try:
            path = self.parent_evidence_path(key)
        except DeltaMinimizeError:
            return None
        return self._load_evidence(path, "parent", key.to_dict(), key.digest())

    def _load_evidence(
        self,
        path: Path,
        key_type: str,
        key: Mapping[str, str],
        key_digest: str,
    ) -> dict[str, Any] | None:
        try:
            if path.is_symlink() or not path.is_file():
                return None
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version",
            "status",
            "key_type",
            "key",
            "key_digest",
            "payload_digest",
            "payload",
        }:
            return None
        payload = raw.get("payload")
        if (
            raw.get("schema_version") != _EVIDENCE_SCHEMA
            or raw.get("status") != "complete"
            or raw.get("key_type") != key_type
            or raw.get("key") != key
            or raw.get("key_digest") != key_digest
            or not isinstance(payload, dict)
            or payload.get("status", "complete") != "complete"
        ):
            return None
        try:
            actual_payload_digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
        except (TypeError, ValueError):
            return None
        if raw.get("payload_digest") != actual_payload_digest:
            return None
        return payload

    def write_color_target(self, target_spec: Mapping[str, Any]) -> Path:
        normalized = _json_value(target_spec)
        digest = hashlib.sha256(_canonical_json_bytes(normalized)).hexdigest()
        path = self._safe_path("objective", "color-targets", f"{digest}.json")
        with _exclusive_file_lock(path):
            existing_blob = _read_regular_bytes(path, corruption="corrupt-color-target-artifact")
            if existing_blob is not None:
                try:
                    existing = json.loads(existing_blob)
                except (UnicodeError, json.JSONDecodeError) as error:
                    raise DeltaMinimizeError("corrupt-color-target-artifact") from error
                if existing != normalized or hashlib.sha256(_canonical_json_bytes(existing)).hexdigest() != digest:
                    raise DeltaMinimizeError("corrupt-color-target-artifact")
            else:
                write_json_atomic(path, normalized)
        current = self._safe_path("objective", "color-target-current.json")
        with _exclusive_file_lock(current):
            write_json_atomic(
                current,
                {
                    "artifact": str(path.relative_to(self.root)),
                    "sha256": digest,
                },
            )
        return path

    def write_score_target(self, function: str, virtuals: Mapping[int, int]) -> Path:
        """Write the legacy target projection consumed by score-source.

        The objective's rich role-descriptor target remains a separate,
        immutable artifact.  Candidate compilation only needs this exact IG
        to physical-register projection, and it must also be content-addressed
        so a changed objective starts a new evidence-cache epoch.
        """
        if not isinstance(function, str) or not function or not virtuals:
            raise DeltaMinimizeError("invalid-score-target")
        normalized_virtuals: dict[int, int] = {}
        for ig_idx, physical in virtuals.items():
            if (
                type(ig_idx) is not int
                or ig_idx < 0
                or type(physical) is not int
                or not 0 <= physical <= 31
                or ig_idx in normalized_virtuals
            ):
                raise DeltaMinimizeError("invalid-score-target")
            normalized_virtuals[ig_idx] = physical
        normalized = _json_value(
            {
                "function": function,
                "virtuals": dict(sorted(normalized_virtuals.items())),
            }
        )
        digest = hashlib.sha256(_canonical_json_bytes(normalized)).hexdigest()
        path = self._safe_path("objective", "score-targets", f"{digest}.json")
        with _exclusive_file_lock(path):
            existing_blob = _read_regular_bytes(path, corruption="corrupt-score-target-artifact")
            if existing_blob is not None:
                try:
                    existing = json.loads(existing_blob)
                except (UnicodeError, json.JSONDecodeError) as error:
                    raise DeltaMinimizeError("corrupt-score-target-artifact") from error
                if existing != normalized or hashlib.sha256(_canonical_json_bytes(existing)).hexdigest() != digest:
                    raise DeltaMinimizeError("corrupt-score-target-artifact")
            else:
                write_json_atomic(path, normalized)
        return path

    def write_objective_manifest(self, payload: Mapping[str, Any]) -> Path:
        return self.write_json("objective-manifest.json", payload)

    def write_delta_manifest(self, payload: Mapping[str, Any]) -> Path:
        return self.write_json("delta-manifest.json", payload)

    def write_candidates(self, payload: Mapping[str, Any]) -> Path:
        return self.write_json("candidates.json", payload)

    def write_result(self, payload: Mapping[str, Any]) -> Path:
        return self.write_json("result.json", payload)

    def invalidate_publications(self) -> None:
        """Remove outputs derived from a superseded delta manifest."""
        for name in ("candidates.json", "result.json"):
            self._invalidate_evidence_path(self._safe_path(name))
