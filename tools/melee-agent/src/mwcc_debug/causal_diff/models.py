"""Immutable records shared by causal-difference adapters and stores."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping

from .canonical import stable_id


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", _immutable_attributes(self.attributes))
        if self.relation_kind in _ADDED_RELATIONS:
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


@dataclass(frozen=True, slots=True)
class AdapterResult:
    nodes: tuple[EvidenceNode, ...] = ()
    edges: tuple[EvidenceEdge, ...] = ()
    verified_capabilities: frozenset[str] = frozenset()
    warnings: tuple[str, ...] = ()
