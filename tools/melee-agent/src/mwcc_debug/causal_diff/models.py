"""Immutable records shared by causal-difference adapters and stores."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, field_validator

from .canonical import stable_id

CORE_BACKEND_CAPABILITIES = frozenset(
    {
        "pcode-occurrences",
        "virtual-use-def",
        "virtual-to-allocator-node",
        "allocator-decisions",
        "interference-edges",
    }
)
OBJECT_BINDING_BACKEND_CAPABILITIES = frozenset(
    {
        "compiler-object-bindings",
        "object-to-virtual",
        "object-to-frame",
        "pcode-to-code-range",
        "object-to-source",
    }
)


def _validate_digest(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("digest must contain exactly 64 hexadecimal characters in canonical lowercase")
    return value


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    sha256: str

    _validate_sha256 = field_validator("sha256")(_validate_digest)


class BackendArtifactRef(ArtifactRef):
    format: Literal["mwcc-debug-pcdump", "backend-trace.v1"]
    capabilities: tuple[str, ...]

    @field_validator("capabilities")
    @classmethod
    def _validate_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = set(value) - CORE_BACKEND_CAPABILITIES
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unknown backend capability: {names}")
        return value


class BackendArtifactRefV2(ArtifactRef):
    format: Literal["backend-trace.v2"]
    capabilities: tuple[str, ...]
    capture_identity_sha256: str
    compiler_executable_sha256: str
    mwcc_command_sha256: str
    environment_digest: str
    candidate_object_sha256: str

    _validate_identity_digests = field_validator(
        "capture_identity_sha256",
        "compiler_executable_sha256",
        "mwcc_command_sha256",
        "environment_digest",
        "candidate_object_sha256",
    )(_validate_digest)

    @field_validator("capabilities")
    @classmethod
    def _validate_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        supported = CORE_BACKEND_CAPABILITIES | OBJECT_BINDING_BACKEND_CAPABILITIES
        unknown = set(value) - supported
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unknown backend capability: {names}")
        return value


class CaptureIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nonce: str
    compiler_executable_sha256: str
    source_sha256: str
    mwcc_command_sha256: str
    environment_digest: str
    candidate_object_sha256: str
    function: str
    capture_run_id: str

    _validate_digests = field_validator(
        "compiler_executable_sha256",
        "source_sha256",
        "mwcc_command_sha256",
        "environment_digest",
        "candidate_object_sha256",
        "capture_run_id",
    )(_validate_digest)

    @field_validator("nonce")
    @classmethod
    def _validate_nonce(cls, value: str) -> str:
        if len(value) != 32 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("nonce must contain exactly 32 hexadecimal characters in canonical lowercase")
        return value


class CompileManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    compiler: str
    target_build: Literal["GALE01"]
    flags_digest: str
    environment_digest: str
    source_digest: str
    expected_assembly_digest: str

    _validate_digests = field_validator(
        "id",
        "flags_digest",
        "environment_digest",
        "source_digest",
        "expected_assembly_digest",
    )(_validate_digest)


class ArtifactsManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: ArtifactRef
    checkdiff: ArtifactRef
    backend: tuple[BackendArtifactRef, ...]
    inspector: ArtifactRef
    frame_report: ArtifactRef | None = None

    @field_validator("backend")
    @classmethod
    def _require_backend(cls, value: tuple[BackendArtifactRef, ...]) -> tuple[BackendArtifactRef, ...]:
        if not value:
            raise ValueError("at least one backend artifact is required")
        return value


ArtifactsManifestV1 = ArtifactsManifest


class FrontierBundleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["causal-frontier-bundle.v1"]
    label: str
    function: str
    compile: CompileManifest
    artifacts: ArtifactsManifest
    producer_versions: Mapping[str, str]

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
            raise ValueError("label must match [A-Za-z0-9_-]+")
        return value


FrontierBundleManifestV1 = FrontierBundleManifest


class ArtifactsManifestV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: ArtifactRef
    checkdiff: ArtifactRef
    backend: tuple[BackendArtifactRef | BackendArtifactRefV2, ...]
    inspector: ArtifactRef
    frame_report: ArtifactRef | None = None
    candidate_object: ArtifactRef

    @field_validator("backend")
    @classmethod
    def _require_backend(
        cls, value: tuple[BackendArtifactRef | BackendArtifactRefV2, ...]
    ) -> tuple[BackendArtifactRef | BackendArtifactRefV2, ...]:
        if not value:
            raise ValueError("at least one backend artifact is required")
        return value


class FrontierBundleManifestV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["causal-frontier-bundle.v2"]
    label: str
    function: str
    compile: CompileManifest
    artifacts: ArtifactsManifestV2
    producer_versions: Mapping[str, str]

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
            raise ValueError("label must match [A-Za-z0-9_-]+")
        return value


BundleManifest = FrontierBundleManifestV1 | FrontierBundleManifestV2


class Confidence(StrEnum):
    HEURISTIC = "heuristic"
    DERIVED_UNIQUE = "derived-unique"
    OBSERVED = "observed"


_CONFIDENCE_RANK = {
    Confidence.HEURISTIC: 0,
    Confidence.DERIVED_UNIQUE: 1,
    Confidence.OBSERVED: 2,
}

_ADDED_RELATIONS = frozenset({"node-added", "edge-added"})
_REMOVED_RELATIONS = frozenset({"node-removed", "edge-removed"})


def min_confidence(
    *confidences: Confidence,
    input_confidences: Iterable[Confidence] = (),
) -> Confidence:
    """Return the weakest declared or input-record confidence."""

    values = (*confidences, *input_confidences)
    if not values:
        raise ValueError("at least one confidence is required")
    return min(values, key=_CONFIDENCE_RANK.__getitem__)


def _validated_input_confidences(
    provenance: Provenance,
    input_confidences: Iterable[Confidence],
) -> tuple[Confidence, ...]:
    values = tuple(input_confidences)
    if len(values) != len(provenance.input_record_ids):
        raise ValueError("input confidences must correspond to provenance input record IDs")
    return values


def _immutable_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _immutable_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_immutable_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_immutable_value(item) for item in value)
    return value


def _immutable_attributes(attributes: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({str(key): _immutable_value(value) for key, value in attributes.items()})


@dataclass(frozen=True, slots=True)
class Provenance:
    artifact_sha256: str
    parser: str
    raw_start: int | None
    raw_end: int | None
    derivation_rule: str
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_record_ids", tuple(self.input_record_ids))


@dataclass(frozen=True, slots=True)
class EvidenceNode:
    record_id: str
    compile_id: str
    function: str
    kind: str
    role_key: str | None
    producer_confidence: Confidence
    adapter_confidence: Confidence
    confidence: Confidence
    provenance: Provenance
    attributes: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", _immutable_attributes(self.attributes))

    @classmethod
    def create(
        cls,
        *,
        compile_id: str,
        function: str,
        kind: str,
        local_key: object,
        role_key: str | None,
        producer_confidence: Confidence,
        adapter_confidence: Confidence,
        provenance: Provenance,
        attributes: Mapping[str, object],
        input_confidences: Iterable[Confidence] = (),
    ) -> EvidenceNode:
        input_confidences = _validated_input_confidences(provenance, input_confidences)
        return cls(
            record_id=stable_id(compile_id, kind, local_key),
            compile_id=compile_id,
            function=function,
            kind=kind,
            role_key=role_key,
            producer_confidence=producer_confidence,
            adapter_confidence=adapter_confidence,
            confidence=min_confidence(
                producer_confidence,
                adapter_confidence,
                input_confidences=input_confidences,
            ),
            provenance=provenance,
            attributes=_immutable_attributes(attributes),
        )

    def with_attributes(self, attributes: Mapping[str, object]) -> EvidenceNode:
        """Return altered content while retaining identity for integrity checks."""

        return replace(self, attributes=_immutable_attributes(attributes))


@dataclass(frozen=True, slots=True)
class EvidenceEdge:
    record_id: str
    compile_id: str
    function: str
    kind: str
    source_id: str
    target_id: str
    producer_confidence: Confidence
    adapter_confidence: Confidence
    confidence: Confidence
    provenance: Provenance
    attributes: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", _immutable_attributes(self.attributes))

    @classmethod
    def create(
        cls,
        *,
        compile_id: str,
        function: str,
        kind: str,
        source_id: str,
        target_id: str,
        occurrence_ordinal: int,
        producer_confidence: Confidence,
        adapter_confidence: Confidence,
        provenance: Provenance,
        attributes: Mapping[str, object],
        input_confidences: Iterable[Confidence] = (),
    ) -> EvidenceEdge:
        input_confidences = _validated_input_confidences(provenance, input_confidences)
        local_key = (
            kind,
            source_id,
            target_id,
            provenance.derivation_rule,
            occurrence_ordinal,
        )
        return cls(
            record_id=stable_id(compile_id, kind, local_key),
            compile_id=compile_id,
            function=function,
            kind=kind,
            source_id=source_id,
            target_id=target_id,
            producer_confidence=producer_confidence,
            adapter_confidence=adapter_confidence,
            confidence=min_confidence(
                producer_confidence,
                adapter_confidence,
                input_confidences=input_confidences,
            ),
            provenance=provenance,
            attributes=_immutable_attributes(attributes),
        )

    def with_attributes(self, attributes: Mapping[str, object]) -> EvidenceEdge:
        return replace(self, attributes=_immutable_attributes(attributes))


@dataclass(frozen=True, slots=True)
class ComparisonRecord:
    record_id: str
    analysis_id: str
    relation_kind: str
    left_compile_id: str
    left_record_id: str | None
    right_compile_id: str
    right_record_id: str | None
    confidence: Confidence
    provenance: Provenance
    attributes: Mapping[str, object]
    _owner_authority: object | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", _immutable_attributes(self.attributes))
        if self.relation_kind == "backend-owner-abstained":
            valid_endpoints = True
        elif self.relation_kind in _ADDED_RELATIONS:
            valid_endpoints = self.left_record_id is None and self.right_record_id is not None
        elif self.relation_kind in _REMOVED_RELATIONS:
            valid_endpoints = self.left_record_id is not None and self.right_record_id is None
        else:
            valid_endpoints = self.left_record_id is not None and self.right_record_id is not None
        if not valid_endpoints:
            raise ValueError(f"invalid comparison endpoints for relation: {self.relation_kind}")

    @classmethod
    def create(
        cls,
        *,
        analysis_id: str,
        relation_kind: str,
        left_compile_id: str,
        left_record_id: str | None,
        right_compile_id: str,
        right_record_id: str | None,
        producer_confidence: Confidence,
        adapter_confidence: Confidence,
        provenance: Provenance,
        attributes: Mapping[str, object],
        input_confidences: Iterable[Confidence] = (),
        occurrence_ordinal: int = 0,
    ) -> ComparisonRecord:
        input_confidences = _validated_input_confidences(provenance, input_confidences)
        local_key = (
            relation_kind,
            left_compile_id,
            left_record_id,
            right_compile_id,
            right_record_id,
            provenance.derivation_rule,
            occurrence_ordinal,
        )
        return cls(
            record_id=stable_id(analysis_id, relation_kind, local_key),
            analysis_id=analysis_id,
            relation_kind=relation_kind,
            left_compile_id=left_compile_id,
            left_record_id=left_record_id,
            right_compile_id=right_compile_id,
            right_record_id=right_record_id,
            confidence=min_confidence(
                producer_confidence,
                adapter_confidence,
                input_confidences=input_confidences,
            ),
            provenance=provenance,
            attributes=_immutable_attributes(attributes),
        )

    def with_attributes(self, attributes: Mapping[str, object]) -> ComparisonRecord:
        return replace(self, attributes=_immutable_attributes(attributes))

    def __copy__(self) -> ComparisonRecord:
        return replace(self)

    def __deepcopy__(self, memo: dict[int, object]) -> ComparisonRecord:
        del memo
        return replace(self)


@dataclass(frozen=True, slots=True)
class AdapterResult:
    nodes: tuple[EvidenceNode, ...] = ()
    edges: tuple[EvidenceEdge, ...] = ()
    verified_capabilities: frozenset[str] = frozenset()
    warnings: tuple[str, ...] = ()
