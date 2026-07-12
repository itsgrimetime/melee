"""Strict, provenance-bound reviewed allocator namespace attestations."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from .contracts import DeltaMinimizeError
from .epochs import PARSER_SCHEMA_HASH
from .objectives import ROLE_NAMESPACE_SCHEMA

NAMESPACE_REVIEW_REQUEST_SCHEMA = "delta-minimize-namespace-review-request.v1"
REVIEWED_NAMESPACES_SCHEMA = "delta-minimize-reviewed-namespaces.v1"

_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_id",
        "kind",
        "side",
        "candidate",
        "mask",
        "source_sha256",
        "pcdump_sha256",
        "domain",
        "automatically_resolved",
        "diagnostic",
    }
)
_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "function",
        "class_id",
        "register_class",
        "namespace_schema",
        "parser_schema_hash",
        "target_sha256",
        "delta_manifest_sha256",
        "left_source_sha256",
        "right_source_sha256",
        "cflags_hash",
        "compiler_fingerprint",
        "expected_object_hash",
        "inspector_version",
        "canonical_artifact_id",
        "canonical_source_sha256",
        "canonical_pcdump_sha256",
        "reviewed_anchors",
        "artifacts",
    }
)
_BINDING_FIELDS = frozenset(
    {
        "artifact_id",
        "source_sha256",
        "pcdump_sha256",
        "canonical_to_artifact",
    }
)
_REVIEW_FIELDS = frozenset({"schema_version", "request_sha256", "request", "bindings"})


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe loader that rejects duplicate mapping keys at every depth."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as error:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _sha256(raw: object, reason: str) -> str:
    if not isinstance(raw, str) or len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise DeltaMinimizeError(reason)
    return raw


def _text(raw: object, reason: str) -> str:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise DeltaMinimizeError(reason)
    return raw


def _canonical_int(raw: object, reason: str) -> int:
    if _is_int(raw) and raw >= 0:
        return raw
    if isinstance(raw, str) and (
        raw == "0" or (raw and "1" <= raw[0] <= "9" and all("0" <= character <= "9" for character in raw[1:]))
    ):
        return int(raw)
    raise DeltaMinimizeError(reason)


def _int_mapping(raw: object, reason: str) -> Mapping[int, int]:
    if not isinstance(raw, Mapping):
        raise DeltaMinimizeError(reason)
    parsed: dict[int, int] = {}
    for raw_key, raw_value in raw.items():
        key = _canonical_int(raw_key, reason)
        if key in parsed or not _is_int(raw_value) or raw_value < 0:
            raise DeltaMinimizeError(reason)
        parsed[key] = raw_value
    return MappingProxyType(dict(sorted(parsed.items())))


def _path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


def _load_unique_yaml(path: Path, reason: str) -> Mapping[str, Any]:
    if not isinstance(path, Path) or _path_has_symlink(path) or not path.is_file():
        raise DeltaMinimizeError(reason)
    try:
        documents = list(yaml.load_all(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise DeltaMinimizeError(reason) from error
    if len(documents) != 1 or not isinstance(documents[0], Mapping):
        raise DeltaMinimizeError(reason)
    return documents[0]


def _write_text_atomic(path: Path, text: str, reason: str) -> None:
    if not isinstance(path, Path) or _path_has_symlink(path):
        raise DeltaMinimizeError(reason)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise DeltaMinimizeError(reason) from error
    if _path_has_symlink(path.parent) or path.is_symlink():
        raise DeltaMinimizeError(reason)
    fd = -1
    temporary: Path | None = None
    try:
        fd, raw_temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(raw_temporary)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            fd = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if _path_has_symlink(path) or path.is_symlink():
            raise DeltaMinimizeError(reason)
        os.replace(temporary, path)
        temporary = None
    except (OSError, UnicodeError) as error:
        raise DeltaMinimizeError(reason) from error
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _canonical_yaml(data: Mapping[str, Any]) -> str:
    return yaml.safe_dump(
        data,
        allow_unicode=False,
        default_flow_style=False,
        sort_keys=False,
    )


@dataclass(frozen=True)
class NamespaceArtifact:
    artifact_id: str
    kind: str
    side: str | None
    candidate: str | None
    mask: int | None
    source_sha256: str
    pcdump_sha256: str
    domain: tuple[int, ...]
    automatically_resolved: bool
    diagnostic: str | None

    def __post_init__(self) -> None:
        _text(self.artifact_id, "invalid-namespace-artifact")
        _sha256(self.source_sha256, "invalid-namespace-artifact")
        _sha256(self.pcdump_sha256, "invalid-namespace-artifact")
        if not isinstance(self.domain, (tuple, list)) or any(not _is_int(role) or role < 0 for role in self.domain):
            raise DeltaMinimizeError("invalid-namespace-artifact")
        domain = tuple(self.domain)
        if len(domain) < 32 or domain != tuple(range(domain[-1] + 1)):
            raise DeltaMinimizeError("invalid-namespace-artifact")
        if not isinstance(self.automatically_resolved, bool):
            raise DeltaMinimizeError("invalid-namespace-artifact")
        if self.automatically_resolved:
            if self.diagnostic is not None:
                raise DeltaMinimizeError("invalid-namespace-artifact")
        else:
            _text(self.diagnostic, "invalid-namespace-artifact")
        if self.kind == "parent":
            if (
                self.side not in {"left", "right"}
                or self.artifact_id != f"parent:{self.side}"
                or self.candidate is not None
                or self.mask is not None
            ):
                raise DeltaMinimizeError("invalid-namespace-artifact")
        elif self.kind == "candidate":
            if (
                self.side is not None
                or not _is_int(self.mask)
                or not 0 <= self.mask <= 7
                or self.candidate != f"mask-{self.mask:03b}"
                or self.artifact_id != f"candidate:{self.candidate}"
            ):
                raise DeltaMinimizeError("invalid-namespace-artifact")
        else:
            raise DeltaMinimizeError("invalid-namespace-artifact")
        object.__setattr__(self, "domain", domain)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "side": self.side,
            "candidate": self.candidate,
            "mask": self.mask,
            "source_sha256": self.source_sha256,
            "pcdump_sha256": self.pcdump_sha256,
            "domain": list(self.domain),
            "automatically_resolved": self.automatically_resolved,
            "diagnostic": self.diagnostic,
        }

    @classmethod
    def from_dict(cls, raw: object) -> NamespaceArtifact:
        if not isinstance(raw, Mapping) or set(raw) != _ARTIFACT_FIELDS:
            raise DeltaMinimizeError("invalid-namespace-artifact")
        try:
            return cls(**dict(raw))
        except (KeyError, TypeError, ValueError) as error:
            raise DeltaMinimizeError("invalid-namespace-artifact") from error


def _artifact_sort_key(artifact: NamespaceArtifact) -> tuple[int, int, str]:
    if artifact.kind == "parent":
        return (0, 0 if artifact.side == "left" else 1, artifact.artifact_id)
    return (1, artifact.mask or 0, artifact.artifact_id)


@dataclass(frozen=True)
class NamespaceReviewRequest:
    function: str
    class_id: int
    register_class: str
    namespace_schema: str
    parser_schema_hash: str
    target_sha256: str
    delta_manifest_sha256: str
    left_source_sha256: str
    right_source_sha256: str
    cflags_hash: str
    compiler_fingerprint: str
    expected_object_hash: str
    inspector_version: str
    canonical_artifact_id: str
    canonical_source_sha256: str
    canonical_pcdump_sha256: str
    reviewed_anchors: Mapping[int, int]
    artifacts: tuple[NamespaceArtifact, ...]
    schema_version: str = NAMESPACE_REVIEW_REQUEST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != NAMESPACE_REVIEW_REQUEST_SCHEMA:
            raise DeltaMinimizeError("unsupported-namespace-review-request-schema")
        if self.namespace_schema != ROLE_NAMESPACE_SCHEMA:
            raise DeltaMinimizeError("unsupported-namespace-review-epoch")
        if self.parser_schema_hash != PARSER_SCHEMA_HASH:
            raise DeltaMinimizeError("unsupported-namespace-review-epoch")
        _text(self.function, "invalid-namespace-review-request")
        if (self.class_id, self.register_class) not in {(0, "GPR"), (1, "FPR")}:
            raise DeltaMinimizeError("invalid-namespace-review-request")
        for digest in (
            self.target_sha256,
            self.delta_manifest_sha256,
            self.left_source_sha256,
            self.right_source_sha256,
            self.cflags_hash,
            self.expected_object_hash,
            self.canonical_source_sha256,
            self.canonical_pcdump_sha256,
        ):
            _sha256(digest, "invalid-namespace-review-request")
        _text(self.parser_schema_hash, "invalid-namespace-review-request")
        _text(self.compiler_fingerprint, "invalid-namespace-review-request")
        _text(self.inspector_version, "invalid-namespace-review-request")
        anchors = _int_mapping(self.reviewed_anchors, "invalid-namespace-review-anchors")
        if not anchors or len(set(anchors.values())) != len(anchors):
            raise DeltaMinimizeError("invalid-namespace-review-anchors")
        if (
            not isinstance(self.artifacts, (tuple, list))
            or not self.artifacts
            or any(not isinstance(artifact, NamespaceArtifact) for artifact in self.artifacts)
        ):
            raise DeltaMinimizeError("invalid-namespace-review-request")
        artifacts = tuple(sorted(self.artifacts, key=_artifact_sort_key))
        artifact_ids = {artifact.artifact_id for artifact in artifacts}
        if len(artifact_ids) != len(artifacts):
            raise DeltaMinimizeError("duplicate-namespace-artifact-id")
        domains = {artifact.domain for artifact in artifacts}
        canonical = next(
            (artifact for artifact in artifacts if artifact.artifact_id == self.canonical_artifact_id),
            None,
        )
        left = next(
            (artifact for artifact in artifacts if artifact.artifact_id == "parent:left"),
            None,
        )
        right = next(
            (artifact for artifact in artifacts if artifact.artifact_id == "parent:right"),
            None,
        )
        if (
            len(domains) != 1
            or canonical is None
            or left is None
            or right is None
            or left.source_sha256 != self.left_source_sha256
            or right.source_sha256 != self.right_source_sha256
            or canonical.source_sha256 != self.canonical_source_sha256
            or canonical.pcdump_sha256 != self.canonical_pcdump_sha256
            or not canonical.automatically_resolved
            or any(key not in canonical.domain or value not in canonical.domain for key, value in anchors.items())
        ):
            raise DeltaMinimizeError("invalid-namespace-review-request")
        object.__setattr__(self, "reviewed_anchors", anchors)
        object.__setattr__(self, "artifacts", artifacts)

    @property
    def domain(self) -> tuple[int, ...]:
        return self.artifacts[0].domain

    @property
    def sha256(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "function": self.function,
            "class_id": self.class_id,
            "register_class": self.register_class,
            "namespace_schema": self.namespace_schema,
            "parser_schema_hash": self.parser_schema_hash,
            "target_sha256": self.target_sha256,
            "delta_manifest_sha256": self.delta_manifest_sha256,
            "left_source_sha256": self.left_source_sha256,
            "right_source_sha256": self.right_source_sha256,
            "cflags_hash": self.cflags_hash,
            "compiler_fingerprint": self.compiler_fingerprint,
            "expected_object_hash": self.expected_object_hash,
            "inspector_version": self.inspector_version,
            "canonical_artifact_id": self.canonical_artifact_id,
            "canonical_source_sha256": self.canonical_source_sha256,
            "canonical_pcdump_sha256": self.canonical_pcdump_sha256,
            "reviewed_anchors": dict(self.reviewed_anchors),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }

    def to_yaml(self) -> str:
        return _canonical_yaml(self.to_dict())

    def write(self, path: Path) -> None:
        _write_text_atomic(path, self.to_yaml(), "invalid-namespace-review-request-path")

    @classmethod
    def from_dict(cls, raw: object) -> NamespaceReviewRequest:
        if not isinstance(raw, Mapping):
            raise DeltaMinimizeError("invalid-namespace-review-request-fields")
        if raw.get("schema_version") != NAMESPACE_REVIEW_REQUEST_SCHEMA:
            if "schema_version" in raw:
                raise DeltaMinimizeError("unsupported-namespace-review-request-schema")
            raise DeltaMinimizeError("invalid-namespace-review-request-fields")
        if set(raw) != _REQUEST_FIELDS:
            raise DeltaMinimizeError("invalid-namespace-review-request-fields")
        raw_artifacts = raw["artifacts"]
        if not isinstance(raw_artifacts, list):
            raise DeltaMinimizeError("invalid-namespace-review-request")
        values = dict(raw)
        values["reviewed_anchors"] = _int_mapping(raw["reviewed_anchors"], "invalid-namespace-review-anchors")
        values["artifacts"] = tuple(NamespaceArtifact.from_dict(artifact) for artifact in raw_artifacts)
        try:
            return cls(**values)
        except (KeyError, TypeError, ValueError) as error:
            raise DeltaMinimizeError("invalid-namespace-review-request") from error


@dataclass(frozen=True)
class ReviewedNamespaceBinding:
    artifact_id: str
    source_sha256: str
    pcdump_sha256: str
    canonical_to_artifact: Mapping[int, int]

    def __post_init__(self) -> None:
        _text(self.artifact_id, "invalid-reviewed-namespace-binding")
        _sha256(self.source_sha256, "invalid-reviewed-namespace-binding")
        _sha256(self.pcdump_sha256, "invalid-reviewed-namespace-binding")
        mapping = _int_mapping(self.canonical_to_artifact, "invalid-reviewed-namespace-map")
        if not mapping or len(set(mapping.values())) != len(mapping):
            raise DeltaMinimizeError("invalid-reviewed-namespace-map")
        object.__setattr__(self, "canonical_to_artifact", mapping)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "source_sha256": self.source_sha256,
            "pcdump_sha256": self.pcdump_sha256,
            "canonical_to_artifact": dict(self.canonical_to_artifact),
        }

    @classmethod
    def from_dict(cls, raw: object) -> ReviewedNamespaceBinding:
        if not isinstance(raw, Mapping) or set(raw) != _BINDING_FIELDS:
            raise DeltaMinimizeError("invalid-reviewed-namespace-binding")
        try:
            return cls(**dict(raw))
        except (KeyError, TypeError, ValueError) as error:
            raise DeltaMinimizeError("invalid-reviewed-namespace-binding") from error


def _validate_full_map(
    request: NamespaceReviewRequest,
    binding: ReviewedNamespaceBinding,
) -> None:
    mapping = binding.canonical_to_artifact
    domain = request.domain
    content = (binding.source_sha256, binding.pcdump_sha256)
    group = _content_groups(request).get(content, ())
    if (
        not group
        or all(artifact.artifact_id != binding.artifact_id for artifact in group)
        or set(mapping) != set(domain)
        or set(mapping.values()) != set(domain)
        or any(mapping[role] != role for role in range(32))
        or (
            any(artifact.kind == "parent" for artifact in group)
            and any(mapping[role] != artifact_role for role, artifact_role in request.reviewed_anchors.items())
        )
    ):
        raise DeltaMinimizeError("invalid-reviewed-namespace-map")


def _content_groups(
    request: NamespaceReviewRequest,
) -> Mapping[tuple[str, str], tuple[NamespaceArtifact, ...]]:
    groups: dict[tuple[str, str], list[NamespaceArtifact]] = {}
    for artifact in request.artifacts:
        key = (artifact.source_sha256, artifact.pcdump_sha256)
        groups.setdefault(key, []).append(artifact)
    return MappingProxyType({key: tuple(artifacts) for key, artifacts in groups.items()})


def _unresolved_content_groups(
    request: NamespaceReviewRequest,
) -> Mapping[tuple[str, str], tuple[NamespaceArtifact, ...]]:
    unresolved: dict[tuple[str, str], tuple[NamespaceArtifact, ...]] = {}
    for key, artifacts in _content_groups(request).items():
        if any(artifact.automatically_resolved for artifact in artifacts):
            continue
        unresolved[key] = artifacts
    return MappingProxyType(unresolved)


@dataclass(frozen=True)
class ReviewedNamespaces:
    request: NamespaceReviewRequest
    request_sha256: str
    bindings: tuple[ReviewedNamespaceBinding, ...]
    schema_version: str = REVIEWED_NAMESPACES_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != REVIEWED_NAMESPACES_SCHEMA:
            raise DeltaMinimizeError("unsupported-reviewed-namespaces-schema")
        if not isinstance(self.request, NamespaceReviewRequest):
            raise DeltaMinimizeError("invalid-reviewed-namespaces")
        _sha256(self.request_sha256, "invalid-reviewed-namespace-request-digest")
        if self.request_sha256 != self.request.sha256:
            raise DeltaMinimizeError("reviewed-namespace-request-digest-mismatch")
        if not isinstance(self.bindings, (tuple, list)) or any(
            not isinstance(binding, ReviewedNamespaceBinding) for binding in self.bindings
        ):
            raise DeltaMinimizeError("invalid-reviewed-namespaces")
        bindings = tuple(sorted(self.bindings, key=lambda binding: binding.artifact_id))
        artifact_by_id = {artifact.artifact_id: artifact for artifact in self.request.artifacts}
        seen_ids: set[str] = set()
        seen_content: set[tuple[str, str]] = set()
        for binding in bindings:
            artifact = artifact_by_id.get(binding.artifact_id)
            content = (binding.source_sha256, binding.pcdump_sha256)
            if (
                artifact is None
                or binding.artifact_id in seen_ids
                or content in seen_content
                or artifact.automatically_resolved
                or content != (artifact.source_sha256, artifact.pcdump_sha256)
            ):
                raise DeltaMinimizeError("invalid-reviewed-namespace-binding")
            _validate_full_map(self.request, binding)
            seen_ids.add(binding.artifact_id)
            seen_content.add(content)
        required = set(_unresolved_content_groups(self.request))
        if seen_content != required:
            raise DeltaMinimizeError("incomplete-reviewed-namespaces")
        object.__setattr__(self, "bindings", bindings)

    @property
    def sha256(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_sha256": self.request_sha256,
            "request": self.request.to_dict(),
            "bindings": [binding.to_dict() for binding in self.bindings],
        }

    def to_yaml(self) -> str:
        return _canonical_yaml(self.to_dict())

    def write(self, path: Path) -> None:
        _write_text_atomic(path, self.to_yaml(), "invalid-reviewed-namespaces-path")

    @classmethod
    def from_dict(cls, raw: object) -> ReviewedNamespaces:
        if not isinstance(raw, Mapping):
            raise DeltaMinimizeError("invalid-reviewed-namespaces-fields")
        if raw.get("schema_version") != REVIEWED_NAMESPACES_SCHEMA:
            if "schema_version" in raw:
                raise DeltaMinimizeError("unsupported-reviewed-namespaces-schema")
            raise DeltaMinimizeError("invalid-reviewed-namespaces-fields")
        if set(raw) != _REVIEW_FIELDS or not isinstance(raw["bindings"], list):
            raise DeltaMinimizeError("invalid-reviewed-namespaces-fields")
        try:
            return cls(
                schema_version=raw["schema_version"],
                request_sha256=raw["request_sha256"],
                request=NamespaceReviewRequest.from_dict(raw["request"]),
                bindings=tuple(ReviewedNamespaceBinding.from_dict(binding) for binding in raw["bindings"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise DeltaMinimizeError("invalid-reviewed-namespaces") from error


def load_review_request(path: Path) -> NamespaceReviewRequest:
    """Load an exact request schema from a non-symlinked regular file."""

    return NamespaceReviewRequest.from_dict(_load_unique_yaml(path, "invalid-namespace-review-request-path"))


def load_reviewed_namespaces(
    path: Path,
    *,
    request: NamespaceReviewRequest | None = None,
) -> ReviewedNamespaces:
    """Load and optionally bind a reviewed sidecar to the current request."""

    reviewed = ReviewedNamespaces.from_dict(_load_unique_yaml(path, "invalid-reviewed-namespaces-path"))
    if request is not None and reviewed.request != request:
        raise DeltaMinimizeError("reviewed-namespace-context-drift")
    return reviewed


def _load_review_map(path: Path) -> Mapping[int, int]:
    return _int_mapping(
        _load_unique_yaml(path, "invalid-reviewed-namespace-map-path"),
        "invalid-reviewed-namespace-map",
    )


def seal_namespace_review(
    request: NamespaceReviewRequest,
    identity_ids: tuple[str, ...] | list[str],
    map_paths: Mapping[str, Path],
) -> ReviewedNamespaces:
    """Seal exactly one explicit full map for every unresolved content identity."""

    if (
        not isinstance(request, NamespaceReviewRequest)
        or not isinstance(identity_ids, (tuple, list))
        or isinstance(identity_ids, (str, bytes))
        or any(not isinstance(artifact_id, str) for artifact_id in identity_ids)
        or len(set(identity_ids)) != len(identity_ids)
        or not isinstance(map_paths, Mapping)
        or any(
            not isinstance(artifact_id, str) or not isinstance(path, Path) for artifact_id, path in map_paths.items()
        )
    ):
        raise DeltaMinimizeError("invalid-namespace-review-approvals")
    identity_set = set(identity_ids)
    if identity_set & set(map_paths):
        raise DeltaMinimizeError("redundant-namespace-review-approval")
    artifact_by_id = {artifact.artifact_id: artifact for artifact in request.artifacts}
    approval_ids = (*identity_ids, *map_paths)
    if any(artifact_id not in artifact_by_id for artifact_id in approval_ids):
        raise DeltaMinimizeError("unknown-namespace-review-artifact")

    bindings: list[ReviewedNamespaceBinding] = []
    seen_content: dict[tuple[str, str], Mapping[int, int]] = {}
    for artifact_id in approval_ids:
        artifact = artifact_by_id[artifact_id]
        if artifact.automatically_resolved:
            raise DeltaMinimizeError("redundant-automatic-namespace-review")
        mapping: Mapping[int, int]
        if artifact_id in identity_set:
            mapping = MappingProxyType({role: role for role in artifact.domain})
        else:
            mapping = _load_review_map(map_paths[artifact_id])
        binding = ReviewedNamespaceBinding(
            artifact_id=artifact_id,
            source_sha256=artifact.source_sha256,
            pcdump_sha256=artifact.pcdump_sha256,
            canonical_to_artifact=mapping,
        )
        _validate_full_map(request, binding)
        content = (artifact.source_sha256, artifact.pcdump_sha256)
        previous = seen_content.get(content)
        if previous is not None:
            if dict(previous) != dict(mapping):
                raise DeltaMinimizeError("conflicting-reviewed-namespace-maps")
            raise DeltaMinimizeError("redundant-namespace-review-approval")
        seen_content[content] = mapping
        bindings.append(binding)

    if set(seen_content) != set(_unresolved_content_groups(request)):
        raise DeltaMinimizeError("incomplete-namespace-review-approvals")
    return ReviewedNamespaces(
        request=request,
        request_sha256=request.sha256,
        bindings=tuple(bindings),
    )


def resolve_reviewed_map(
    reviewed: ReviewedNamespaces,
    request: NamespaceReviewRequest,
    *,
    artifact_id: str,
    source_sha256: str,
    pcdump_sha256: str,
) -> Mapping[int, int]:
    """Return an artifact-to-canonical map after exact request/content checks."""

    if not isinstance(reviewed, ReviewedNamespaces) or not isinstance(request, NamespaceReviewRequest):
        raise DeltaMinimizeError("invalid-reviewed-namespace-resolution")
    # Reconstruct the envelope so nested maps and binding completeness are
    # revalidated even when this object came from a non-loader caller.
    reviewed = ReviewedNamespaces(
        request=reviewed.request,
        request_sha256=reviewed.request_sha256,
        bindings=reviewed.bindings,
        schema_version=reviewed.schema_version,
    )
    if reviewed.request != request or reviewed.request_sha256 != request.sha256:
        raise DeltaMinimizeError("reviewed-namespace-context-drift")
    _sha256(source_sha256, "invalid-reviewed-namespace-current-content")
    _sha256(pcdump_sha256, "invalid-reviewed-namespace-current-content")
    artifact = next(
        (candidate for candidate in request.artifacts if candidate.artifact_id == artifact_id),
        None,
    )
    if (
        artifact is None
        or artifact.automatically_resolved
        or artifact.source_sha256 != source_sha256
        or artifact.pcdump_sha256 != pcdump_sha256
    ):
        raise DeltaMinimizeError("reviewed-namespace-artifact-drift")
    binding = next(
        (
            candidate
            for candidate in reviewed.bindings
            if candidate.source_sha256 == source_sha256 and candidate.pcdump_sha256 == pcdump_sha256
        ),
        None,
    )
    if binding is None:
        raise DeltaMinimizeError("missing-reviewed-namespace-binding")
    _validate_full_map(request, binding)
    return MappingProxyType(
        {artifact_role: canonical_role for canonical_role, artifact_role in binding.canonical_to_artifact.items()}
    )
