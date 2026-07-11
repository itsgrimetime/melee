"""Atomic, provenance-checked storage for resumable delta-minimize runs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from src.search.store import ArtifactStore

from .contracts import DeltaMinimizeError

_EVIDENCE_SCHEMA = "delta-minimize-evidence.v1"
_CANDIDATE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}\Z")
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


class DeltaRunStore:
    """Own all durable state below one delta-minimize output directory."""

    def __init__(self, root: Path, provenance: Mapping[str, str] | None = None):
        if not isinstance(root, Path):
            raise TypeError("run-store root must be a Path")
        self.root = _require_safe_path(root)
        _mkdir_safe(self.root)
        self.provenance: dict[str, str] = {}
        self._provenance_bound = False
        self.sources = ArtifactStore(self._safe_path("artifacts"))
        if provenance is not None:
            self.bind_provenance(provenance)

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
        self._safe_path("artifacts")
        path = self.sources.put_source(source_text)
        _require_safe_path(path)
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
            inspector_version=self.provenance["inspector_version"],
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
                **values,
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
        path = self._safe_path("objective", "color-target.json")
        with _exclusive_file_lock(path):
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as error:
                    raise DeltaMinimizeError("immutable-color-target-conflict") from error
                if existing != normalized:
                    raise DeltaMinimizeError("immutable-color-target-conflict")
                return path
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
