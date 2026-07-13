"""Build content-addressed certificates for verified capture-local owners."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping, TypeVar

import rfc8785

from .canonical import canonical_bytes, stable_id
from .models import Confidence, EvidenceEdge, EvidenceNode, Provenance
from .object_binding_adapter import (
    _OBJECT_BINDING_ADAPTER_TOKEN,
    ObjectBindingEvidence,
    _valid_owner_instrumentation_identity,
)
from .store import canonical_record_bytes

_TRUST_TOKEN = object()
_RUNTIME_ONLY_ATTRIBUTE_KEYS = frozenset(
    {
        "runtime_address",
        "ignode_runtime_address",
        "list_node_runtime_address",
    }
)
_PARSER = "mwcc-retro-backend-trace.v2"
_REQUIRED_CAPABILITIES = frozenset(
    {
        "compiler-object-bindings",
        "object-to-frame",
        "object-to-virtual",
        "pcode-to-code-range",
    }
)
_REJECTION_REASONS = frozenset(
    {
        "untrusted-diagnostic-materialization",
        "missing-required-capability",
        "missing-instrumentation-identity",
        "mixed-record-scope",
        "unregistered-support",
        "malformed-support",
        "disconnected-owner-path",
        "plausible-owner-alternative",
        "split-physical-assignment",
        "lineage-parent-mismatch",
        "allocator-origin-contradiction",
        "frame-binding-contradiction",
    }
)
_CONTRADICTORY_REASONS = frozenset(
    {
        "split-physical-assignment",
        "lineage-parent-mismatch",
        "allocator-origin-contradiction",
        "frame-binding-contradiction",
    }
)
_INCOMPLETE_REASONS = frozenset(
    {
        "missing-required-capability",
        "missing-instrumentation-identity",
        "mixed-record-scope",
        "unregistered-support",
        "malformed-support",
        "disconnected-owner-path",
        "untrusted-diagnostic-materialization",
    }
)


class OwnerResolutionStatus(StrEnum):
    UNIQUE = "unique"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    CONTRADICTORY = "contradictory"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True, order=True)
class OwnerRoleKey:
    operand_key: str
    register_class: str
    semantic_stack_role: str
    type_size: int
    frame_area: str

    def validate(self) -> None:
        if re.fullmatch(r"^(def|use):(0|[1-9][0-9]*)$", self.operand_key) is None:
            raise ValueError("invalid owner operand key")
        if self.register_class not in {"gpr", "fpr"}:
            raise ValueError("invalid owner register class")
        if re.fullmatch(r"^[a-z][a-z0-9-]{0,63}$", self.semantic_stack_role) is None:
            raise ValueError("invalid semantic stack role")
        if (
            isinstance(self.type_size, bool)
            or not isinstance(self.type_size, int)
            or not 1 <= self.type_size <= 0x7FFFFFFF
        ):
            raise ValueError("invalid owner type size")
        if self.frame_area not in {"arguments", "locals", "temps"}:
            raise ValueError("invalid owner frame area")

    def as_json(self) -> dict[str, object]:
        self.validate()
        return {
            "operand_key": self.operand_key,
            "register_class": self.register_class,
            "semantic_stack_role": self.semantic_stack_role,
            "type_size": self.type_size,
            "frame_area": self.frame_area,
        }


@dataclass(frozen=True, slots=True, order=True)
class OwnerSemanticState:
    assigned_physical_register: int
    stack_offset: int
    stack_size: int

    def validate(self) -> None:
        values = (self.assigned_physical_register, self.stack_offset, self.stack_size)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError("owner semantic state values must be integers")
        if not 0 <= self.assigned_physical_register <= 31:
            raise ValueError("invalid assigned physical register")
        if not -0x80000000 <= self.stack_offset <= 0x7FFFFFFF:
            raise ValueError("invalid stack offset")
        if not 1 <= self.stack_size <= 0x7FFFFFFF:
            raise ValueError("invalid stack size")

    def as_json(self) -> dict[str, int]:
        self.validate()
        return {
            "assigned_physical_register": self.assigned_physical_register,
            "stack_offset": self.stack_offset,
            "stack_size": self.stack_size,
        }


@dataclass(frozen=True, slots=True)
class OwnerCertificateRejection:
    rejection_id: str
    reason: str
    role: OwnerRoleKey | None
    candidate_record_ids: tuple[str, ...]
    raw_support_record_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OwnerRoleResolution:
    role: OwnerRoleKey
    status: OwnerResolutionStatus
    certificate_record_ids: tuple[str, ...]
    rejections: tuple[OwnerCertificateRejection, ...]


@dataclass(frozen=True, slots=True)
class _CanonicalAlternativeGroup:
    role: OwnerRoleKey
    semantic_state: OwnerSemanticState | None
    rejection_reason: str | None
    multiplicity: int
    provenance_record_ids: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class _CertificateSupportBinding:
    certificate_record_id: str
    node: EvidenceNode
    canonical_content: bytes


@dataclass(frozen=True, slots=True)
class OwnerCertificateResult:
    certificate_nodes: tuple[EvidenceNode, ...]
    role_resolutions: tuple[OwnerRoleResolution, ...]
    global_rejections: tuple[OwnerCertificateRejection, ...]
    _token: object | None = field(default=None, init=False, repr=False, compare=False)
    _canonical_groups: tuple[_CanonicalAlternativeGroup, ...] = field(default=(), init=False, repr=False, compare=False)
    _certificate_support_bindings: tuple[_CertificateSupportBinding, ...] = field(
        default=(), init=False, repr=False, compare=False
    )

    @property
    def is_trusted(self) -> bool:
        return _result_is_trusted(self)

    def certificate(self, record_id: str) -> EvidenceNode | None:
        if not _result_is_trusted(self):
            return None
        return next((node for node in self.certificate_nodes if node.record_id == record_id), None)

    def certificate_support_node(
        self,
        certificate_record_id: str,
        support_record_id: str,
    ) -> EvidenceNode | None:
        if not _result_is_trusted(self):
            return None
        certificate = self.certificate(certificate_record_id)
        if certificate is None or support_record_id not in certificate.provenance.input_record_ids:
            return None
        matches = tuple(
            binding
            for binding in self._certificate_support_bindings
            if binding.certificate_record_id == certificate_record_id and binding.node.record_id == support_record_id
        )
        if len(matches) != 1:
            return None
        binding = matches[0]
        if canonical_record_bytes(binding.node) != binding.canonical_content:
            return None
        return binding.node

    def resolution_for(self, role: OwnerRoleKey) -> OwnerRoleResolution:
        role.validate()
        base = next(
            (item for item in self.role_resolutions if item.role == role),
            OwnerRoleResolution(role, OwnerResolutionStatus.MISSING, (), ()),
        )
        if not _result_is_trusted(self) or self.global_rejections:
            return OwnerRoleResolution(
                role,
                OwnerResolutionStatus.INCOMPLETE,
                base.certificate_record_ids,
                base.rejections,
            )
        return base

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("OwnerCertificateResult is runtime-final")


def _result_is_trusted(result: OwnerCertificateResult) -> bool:
    return type(result) is OwnerCertificateResult and object.__getattribute__(result, "_token") is _TRUST_TOKEN


def _trusted_result(
    certificate_nodes: tuple[EvidenceNode, ...],
    role_resolutions: tuple[OwnerRoleResolution, ...],
    global_rejections: tuple[OwnerCertificateRejection, ...],
    canonical_groups: tuple[_CanonicalAlternativeGroup, ...] = (),
    certificate_support_bindings: tuple[_CertificateSupportBinding, ...] = (),
) -> OwnerCertificateResult:
    result = OwnerCertificateResult(certificate_nodes, role_resolutions, global_rejections)
    object.__setattr__(result, "_canonical_groups", canonical_groups)
    object.__setattr__(
        result,
        "_certificate_support_bindings",
        certificate_support_bindings,
    )
    object.__setattr__(result, "_token", _TRUST_TOKEN)
    return result


@dataclass(frozen=True, slots=True)
class _OwnerPath:
    role: OwnerRoleKey
    semantic_state: OwnerSemanticState
    owner: EvidenceNode
    anchor: EvidenceNode
    pcode: EvidenceNode
    lineage: EvidenceNode
    virtual: EvidenceNode
    allocator: EvidenceNode
    stack: EvidenceNode
    path_records: tuple[EvidenceNode | EvidenceEdge, ...]
    raw_support: tuple[EvidenceNode, ...]


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items() if key not in _RUNTIME_ONLY_ATTRIBUTE_KEYS}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=repr)
    if isinstance(value, StrEnum):
        return value.value
    return value


def _provenance_json(provenance: Provenance) -> dict[str, object]:
    return {
        "artifact_sha256": provenance.artifact_sha256,
        "parser": provenance.parser,
        "raw_start": provenance.raw_start,
        "raw_end": provenance.raw_end,
        "derivation_rule": provenance.derivation_rule,
        "input_record_ids": list(provenance.input_record_ids),
    }


def _record_json(record: EvidenceNode | EvidenceEdge) -> dict[str, object]:
    payload: dict[str, object] = {
        "record_type": "edge" if isinstance(record, EvidenceEdge) else "node",
        "record_id": record.record_id,
        "compile_id": record.compile_id,
        "function": record.function,
        "kind": record.kind,
        "producer_confidence": record.producer_confidence.value,
        "adapter_confidence": record.adapter_confidence.value,
        "confidence": record.confidence.value,
        "attributes": _json_value(record.attributes),
        "provenance": _provenance_json(record.provenance),
    }
    if isinstance(record, EvidenceEdge):
        payload.update(source_id=record.source_id, target_id=record.target_id)
    else:
        payload["role_key"] = record.role_key
    return payload


def _unique_records(
    records: tuple[EvidenceNode | EvidenceEdge, ...],
) -> tuple[EvidenceNode | EvidenceEdge, ...]:
    by_id: dict[str, EvidenceNode | EvidenceEdge] = {}
    for record in records:
        by_id.setdefault(record.record_id, record)
    return tuple(by_id.values())


def _proof_content_sha256(
    path: _OwnerPath,
    evidence: ObjectBindingEvidence,
) -> str:
    proof_payload = {
        "schema_version": "causal-owner-certificate.v1",
        "capture_run_id": evidence.capture_run_id,
        "instrumentation_identity": list(evidence.instrumentation_identity or ()),
        "role": path.role.as_json(),
        "semantic_state": path.semantic_state.as_json(),
        "path_records": [_record_json(record) for record in path.path_records],
        "raw_support_records": [_record_json(record) for record in path.raw_support],
    }
    try:
        payload_bytes = canonical_bytes(proof_payload)
    except rfc8785.CanonicalizationError as error:
        raise _MalformedEvidence("owner proof content is not canonical JSON") from error
    return hashlib.sha256(payload_bytes).hexdigest()


def _certificate_record_id(
    path: _OwnerPath,
    evidence: ObjectBindingEvidence,
) -> str:
    return stable_id(
        path.owner.compile_id,
        "owner-proof-certificate",
        _proof_content_sha256(path, evidence),
    )


def _certificate(path: _OwnerPath, evidence: ObjectBindingEvidence) -> EvidenceNode:
    cited_records = (*path.path_records, *path.raw_support)
    proof_content_sha256 = _proof_content_sha256(path, evidence)
    path_record_ids = tuple(record.record_id for record in path.path_records)
    raw_support_record_ids = tuple(record.record_id for record in path.raw_support)
    all_input_ids = tuple(record.record_id for record in cited_records)
    return EvidenceNode.create(
        compile_id=path.owner.compile_id,
        function=path.owner.function,
        kind="owner-proof-certificate",
        local_key=proof_content_sha256,
        role_key=path.role.semantic_stack_role,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        provenance=Provenance(
            artifact_sha256=path.owner.provenance.artifact_sha256,
            parser="causal-owner-certificate.v1",
            raw_start=None,
            raw_end=None,
            derivation_rule="verified-capture-local-owner-path",
            input_record_ids=all_input_ids,
        ),
        input_confidences=tuple(record.confidence for record in cited_records),
        attributes={
            "schema_version": "causal-owner-certificate.v1",
            "capture_run_id": evidence.capture_run_id,
            "role": path.role.as_json(),
            "semantic_state": path.semantic_state.as_json(),
            "owner_record_id": path.owner.record_id,
            "anchor_record_id": path.anchor.record_id,
            "pcode_record_id": path.pcode.record_id,
            "lineage_record_ids": (path.lineage.record_id,),
            "virtual_record_id": path.virtual.record_id,
            "allocator_record_id": path.allocator.record_id,
            "stack_record_id": path.stack.record_id,
            "path_record_ids": path_record_ids,
            "raw_support_record_ids": raw_support_record_ids,
            "proof_content_sha256": proof_content_sha256,
            "instrumentation_identity": evidence.instrumentation_identity,
        },
    )


def _certificate_support_bindings(
    certificates: tuple[EvidenceNode, ...],
    paths: tuple[_OwnerPath, ...],
) -> tuple[_CertificateSupportBinding, ...]:
    bindings: list[_CertificateSupportBinding] = []
    for certificate, path in zip(certificates, paths, strict=True):
        cited_ids = set(certificate.provenance.input_record_ids)
        by_id: dict[str, _CertificateSupportBinding] = {}
        for record in (*path.path_records, *path.raw_support):
            if not isinstance(record, EvidenceNode) or record.record_id not in cited_ids:
                continue
            binding = _CertificateSupportBinding(
                certificate.record_id,
                record,
                canonical_record_bytes(record),
            )
            prior = by_id.get(record.record_id)
            if prior is not None and prior.canonical_content != binding.canonical_content:
                raise _MalformedEvidence("certificate support ID has conflicting content")
            by_id[record.record_id] = binding
        bindings.extend(by_id[record_id] for record_id in sorted(by_id))
    return tuple(
        sorted(
            bindings,
            key=lambda item: (item.certificate_record_id, item.node.record_id),
        )
    )


@dataclass(frozen=True, slots=True)
class _CandidatePath:
    owner: EvidenceNode
    anchor: EvidenceNode
    pcode: EvidenceNode
    lineage: EvidenceNode
    virtual: EvidenceNode
    allocator: EvidenceNode
    stack: EvidenceNode
    path_records: tuple[EvidenceNode | EvidenceEdge, ...]


class _OwnerPathStage(StrEnum):
    ANCHOR = "anchor"
    PCODE_LINEAGE = "pcode-lineage"
    VIRTUAL = "virtual"
    OBJECT = "object"
    ALLOCATOR = "allocator"
    FRAME = "frame"


@dataclass(frozen=True, slots=True)
class _OwnerRoleHint:
    operand_key: str | None = None
    register_class: str | None = None
    semantic_stack_role: str | None = None
    type_size: int | None = None
    frame_area: str | None = None


@dataclass(frozen=True, slots=True)
class _PartialOwnerPath:
    stage: _OwnerPathStage
    hint: _OwnerRoleHint
    records: tuple[EvidenceNode | EvidenceEdge, ...]
    stop_reason: str

    def __post_init__(self) -> None:
        if self.stop_reason not in {
            "plausible-owner-alternative",
            "unregistered-support",
            "malformed-support",
        }:
            raise ValueError("invalid partial owner path stop reason")


@dataclass(frozen=True, slots=True)
class _CandidateEnumeration:
    complete: tuple[_CandidatePath, ...]
    partial: tuple[_PartialOwnerPath, ...]
    traversed_edge_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class _ValidationOutcome:
    paths: tuple[_OwnerPath, ...]
    role_rejections: tuple[OwnerCertificateRejection, ...]
    global_rejections: tuple[OwnerCertificateRejection, ...]


class _MalformedEvidence(Exception):
    """Signal malformed persisted input at a validated semantic boundary."""


@dataclass(frozen=True, slots=True)
class _OwnerEvidenceIndex:
    records_by_id: Mapping[str, tuple[EvidenceNode | EvidenceEdge, ...]]
    node_by_id: Mapping[str, EvidenceNode]
    edges_by_kind: Mapping[str, tuple[EvidenceEdge, ...]]
    edges_by_kind_source: Mapping[tuple[str, str], tuple[EvidenceEdge, ...]]
    edges_by_kind_target: Mapping[tuple[str, str], tuple[EvidenceEdge, ...]]


_IndexKey = TypeVar("_IndexKey")
_IndexValue = TypeVar("_IndexValue")


def _freeze_groups(
    groups: Mapping[_IndexKey, list[_IndexValue]],
) -> Mapping[_IndexKey, tuple[_IndexValue, ...]]:
    return MappingProxyType({key: tuple(values) for key, values in groups.items()})


def _index_evidence(evidence: ObjectBindingEvidence) -> _OwnerEvidenceIndex:
    records_by_id: dict[str, list[EvidenceNode | EvidenceEdge]] = {}
    node_by_id: dict[str, EvidenceNode] = {}
    edges_by_kind: dict[str, list[EvidenceEdge]] = {}
    edges_by_kind_source: dict[tuple[str, str], list[EvidenceEdge]] = {}
    edges_by_kind_target: dict[tuple[str, str], list[EvidenceEdge]] = {}

    for node in evidence.nodes:
        records_by_id.setdefault(node.record_id, []).append(node)
        node_by_id[node.record_id] = node
    for edge in evidence.edges:
        records_by_id.setdefault(edge.record_id, []).append(edge)
        edges_by_kind.setdefault(edge.kind, []).append(edge)
        edges_by_kind_source.setdefault((edge.kind, edge.source_id), []).append(edge)
        edges_by_kind_target.setdefault((edge.kind, edge.target_id), []).append(edge)

    return _OwnerEvidenceIndex(
        _freeze_groups(records_by_id),
        MappingProxyType(dict(node_by_id)),
        _freeze_groups(edges_by_kind),
        _freeze_groups(edges_by_kind_source),
        _freeze_groups(edges_by_kind_target),
    )


def _record_content(record: EvidenceNode | EvidenceEdge) -> bytes:
    return canonical_record_bytes(record)


def _conflicting_record_groups(
    index: _OwnerEvidenceIndex,
) -> tuple[tuple[EvidenceNode | EvidenceEdge, ...], ...]:
    groups = tuple(
        tuple(sorted(records, key=_record_content))
        for records in index.records_by_id.values()
        if any(_record_content(record) != _record_content(records[0]) for record in records[1:])
    )
    return tuple(
        sorted(
            groups,
            key=lambda records: tuple(_record_content(record) for record in records),
        )
    )


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validated_instruction_anchor(
    range_start: object,
    range_end: object,
    instruction_offset: object,
) -> int | None:
    if not (
        _is_int(range_start)
        and _is_int(range_end)
        and _is_int(instruction_offset)
        and 0 <= range_start < range_end
        and 0 <= instruction_offset
        and instruction_offset % 4 == 0
        and instruction_offset + 4 <= range_end - range_start
    ):
        return None
    return range_start + instruction_offset


def _raw_mapping_matches_supported_anchor(
    code_range: Mapping[str, object],
    mapping: Mapping[str, object],
    supported_start: object,
    supported_end: object,
    absolute_anchor: object,
) -> bool:
    raw_start = code_range.get("start")
    raw_end = code_range.get("end_exclusive")
    if not (_is_int(raw_start) and _is_int(raw_end)):
        return False
    mapping_anchor = _validated_instruction_anchor(
        raw_start,
        raw_end,
        mapping.get("instruction_offset_within_range"),
    )
    return raw_start == supported_start and raw_end == supported_end and mapping_anchor == absolute_anchor


def _is_physical(value: object) -> bool:
    return _is_int(value) and 0 <= value <= 31


def _is_string_tuple(value: object) -> bool:
    return (
        isinstance(value, tuple)
        and bool(value)
        and all(_is_nonempty_str(item) for item in value)
        and value == tuple(sorted(set(value)))
    )


def _is_lineage_side(value: object) -> bool:
    return isinstance(value, str) and value in {"inputs", "outputs"}


def _support_schema(**values: object) -> dict[str, object]:
    return {
        "capture_run_id": _is_nonempty_str,
        "verified_capability": _is_nonempty_str,
        "support_kind": _is_nonempty_str,
        **values,
    }


_SUPPORT_SCHEMAS: Mapping[str, tuple[Mapping[str, object], ...]] = {
    "object-stage-snapshot": (
        _support_schema(
            object_id=_is_nonempty_str,
            stage=_is_nonempty_str,
            allocation_generation=_is_int,
            lifecycle_sequence_at_capture=_is_int,
        ),
    ),
    "pcode-generation": (_support_schema(pcode_id=_is_nonempty_str, allocation_generation=_is_int),),
    "pcode-code-range": (
        _support_schema(
            pcode_id=_is_nonempty_str,
            allocation_generation=_is_int,
            start=_is_int,
            end_exclusive=_is_int,
        ),
    ),
    "pcode-emission": (
        _support_schema(
            pcode_id=_is_nonempty_str,
            allocation_generation=_is_int,
            code_offset=_is_int,
            machine_operand_key=_is_nonempty_str,
            operand_lineage_id=_is_nonempty_str,
            physical_register=_is_physical,
        ),
    ),
    "pcode-rewrite": (
        _support_schema(
            pcode_id=_is_nonempty_str,
            allocation_generation=_is_int,
            operand_lineage_id=_is_nonempty_str,
            class_id=_is_int,
            virtual=_is_int,
            allocated_physical=_is_physical,
        ),
    ),
    "pcode-lineage-event": (
        _support_schema(
            pcode_id=_is_nonempty_str,
            allocation_generation=_is_int,
            code_offset=_is_int,
            operand_lineage_id=_is_nonempty_str,
            event_kind=lambda value: value == "emission-lineage",
        ),
        _support_schema(
            pcode_id=_is_nonempty_str,
            allocation_generation=_is_int,
            event_index=_is_int,
            side=_is_lineage_side,
            mutation_kind=_is_nonempty_str,
            operand_lineage_id=_is_nonempty_str,
            parent_lineage_ids=_is_string_tuple,
        ),
    ),
    "object-virtual-binding": (
        _support_schema(
            object_id=_is_nonempty_str,
            allocation_generation=_is_int,
            class_id=_is_int,
            virtual=_is_int,
            ig_id=_is_int,
        ),
    ),
    "object-frame-binding": (
        _support_schema(
            object_id=_is_nonempty_str,
            allocation_generation=_is_int,
            area=_is_nonempty_str,
            semantic_stack_role=_is_nonempty_str,
            final_r1_offset=_is_int,
            size=_is_int,
        ),
    ),
}

_SUPPORT_CAPABILITIES = {
    "object-stage-snapshot": "compiler-object-bindings",
    "pcode-generation": "pcode-to-code-range",
    "pcode-code-range": "pcode-to-code-range",
    "pcode-emission": "pcode-to-code-range",
    "pcode-rewrite": "pcode-to-code-range",
    "pcode-lineage-event": "pcode-to-code-range",
    "object-virtual-binding": "object-to-virtual",
    "object-frame-binding": "object-to-frame",
}


def _safe_json(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        return {"unsupported_float": repr(value)}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe_json(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_safe_json(item) for item in value), key=repr)
    return {"unsupported_type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _rejection(
    reason: str,
    role: OwnerRoleKey | None = None,
    candidates: Iterable[EvidenceNode | EvidenceEdge] = (),
    raw_support: Iterable[EvidenceNode] = (),
) -> OwnerCertificateRejection:
    if reason not in _REJECTION_REASONS:
        raise ValueError(f"unknown owner certificate rejection: {reason}")
    candidate_values = tuple(candidates)
    support_values = tuple(raw_support)
    candidate_records = tuple(
        sorted(
            (_record_json(record) for record in candidate_values),
            key=lambda item: canonical_bytes(_safe_json(item)),
        )
    )
    support_records = tuple(
        sorted(
            (_record_json(record) for record in support_values),
            key=lambda item: canonical_bytes(_safe_json(item)),
        )
    )
    payload = {
        "schema_version": "causal-owner-certificate-rejection.v1",
        "reason": reason,
        "role": None if role is None else role.as_json(),
        "candidate_records": [_safe_json(record) for record in candidate_records],
        "raw_support_records": [_safe_json(record) for record in support_records],
    }
    rejection_id = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return OwnerCertificateRejection(
        rejection_id,
        reason,
        role,
        tuple(sorted(record.record_id for record in candidate_values)),
        tuple(sorted(record.record_id for record in support_values)),
    )


def _registered_record(
    index: _OwnerEvidenceIndex,
    record_id: str,
) -> EvidenceNode | EvidenceEdge | OwnerCertificateRejection:
    matches = index.records_by_id.get(record_id, ())
    if not matches or any(_record_content(record) != _record_content(matches[0]) for record in matches[1:]):
        return _rejection("unregistered-support", candidates=matches)
    return matches[0]


def _validate_common_scope(
    evidence: ObjectBindingEvidence,
    records: Iterable[EvidenceNode | EvidenceEdge],
) -> None | OwnerCertificateRejection:
    values = tuple(records)
    if not values:
        return None
    domains = tuple(
        (
            record.compile_id,
            record.function,
            record.provenance.artifact_sha256,
            record.provenance.parser,
            record.attributes.get("capture_run_id"),
        )
        for record in values
    )
    if not _is_nonempty_str(evidence.capture_run_id) or any(
        not all(_is_nonempty_str(item) for item in domain) for domain in domains
    ):
        return _rejection("malformed-support", candidates=values)
    first_domain = domains[0]
    if any(domain != first_domain for domain in domains[1:]) or first_domain[3:] != (_PARSER, evidence.capture_run_id):
        return _rejection("mixed-record-scope", candidates=values)
    try:
        canonical_bytes([_record_json(record) for record in values])
    except rfc8785.CanonicalizationError:
        return _rejection("malformed-support", candidates=values)
    return None


def _support_attributes_are_exact(support: EvidenceNode) -> bool:
    support_kind = support.attributes.get("support_kind")
    schemas = _SUPPORT_SCHEMAS.get(str(support_kind), ())
    return any(
        set(support.attributes) == set(schema)
        and all(predicate(support.attributes[key]) for key, predicate in schema.items())
        for schema in schemas
    )


def _validated_support_records(
    evidence: ObjectBindingEvidence,
    index: _OwnerEvidenceIndex,
    dependent: EvidenceNode | EvidenceEdge,
    excluded_ids: Iterable[str],
    role: OwnerRoleKey | None = None,
) -> tuple[EvidenceNode, ...] | OwnerCertificateRejection:
    excluded = frozenset(excluded_ids)
    selected: list[EvidenceNode] = []
    for input_id in dependent.provenance.input_record_ids:
        if input_id in excluded:
            continue
        registered = _registered_record(index, input_id)
        if not isinstance(registered, EvidenceNode) or registered.kind != "backend-support-record":
            candidates = () if isinstance(registered, OwnerCertificateRejection) else (registered,)
            return _rejection(
                "unregistered-support",
                role,
                (dependent, *candidates),
            )
        support_kind = str(registered.attributes.get("support_kind"))
        capability = _SUPPORT_CAPABILITIES.get(support_kind)
        # The capture-level capability set is a global authority gate. A
        # persisted path may still be validated diagnostically from its exact
        # per-record capability claims so global taint can preserve its ID.
        if (
            capability is None
            or registered.attributes.get("verified_capability") != capability
            or not _support_attributes_are_exact(registered)
            or registered.provenance.input_record_ids
            or registered.producer_confidence is Confidence.HEURISTIC
            or registered.adapter_confidence is Confidence.HEURISTIC
            or registered.confidence is Confidence.HEURISTIC
            or registered.compile_id != dependent.compile_id
            or registered.function != dependent.function
            or registered.provenance.artifact_sha256 != dependent.provenance.artifact_sha256
            or registered.provenance.parser != _PARSER
            or registered.attributes.get("capture_run_id") != evidence.capture_run_id
        ):
            return _rejection(
                "malformed-support",
                role,
                (dependent,),
                (registered,),
            )
        selected.append(registered)
    return tuple(selected)


def _enumerate_candidates(index: _OwnerEvidenceIndex) -> tuple[_CandidatePath, ...]:
    candidates: list[_CandidatePath] = []
    for anchor_edge in index.edges_by_kind.get("assembly-anchor-emitted-by-pcode", ()):
        anchor = index.node_by_id.get(anchor_edge.source_id)
        pcode = index.node_by_id.get(anchor_edge.target_id)
        if anchor is None or pcode is None:
            continue
        for lineage_edge in index.edges_by_kind_source.get(("pcode-operand-lineage", pcode.record_id), ()):
            lineage = index.node_by_id.get(lineage_edge.target_id)
            if lineage is None:
                continue
            for virtual_edge in index.edges_by_kind_source.get(("pcode-operand-uses-virtual", lineage.record_id), ()):
                virtual = index.node_by_id.get(virtual_edge.target_id)
                if virtual is None:
                    continue
                for object_edge in index.edges_by_kind_target.get(
                    ("object-materializes-virtual", virtual.record_id), ()
                ):
                    owner = index.node_by_id.get(object_edge.source_id)
                    if owner is None:
                        continue
                    for allocator_edge in index.edges_by_kind_source.get(
                        ("maps-to-allocator-node", virtual.record_id), ()
                    ):
                        allocator = index.node_by_id.get(allocator_edge.target_id)
                        if allocator is None:
                            continue
                        for frame_edge in index.edges_by_kind_source.get(
                            ("object-has-stack-home", owner.record_id), ()
                        ):
                            stack = index.node_by_id.get(frame_edge.target_id)
                            if stack is None:
                                continue
                            candidates.append(
                                _CandidatePath(
                                    owner,
                                    anchor,
                                    pcode,
                                    lineage,
                                    virtual,
                                    allocator,
                                    stack,
                                    (
                                        anchor,
                                        anchor_edge,
                                        pcode,
                                        lineage_edge,
                                        lineage,
                                        virtual_edge,
                                        virtual,
                                        owner,
                                        object_edge,
                                        allocator_edge,
                                        allocator,
                                        frame_edge,
                                        stack,
                                    ),
                                )
                            )
    return tuple(candidates)


_OWNER_EDGE_STAGES = MappingProxyType(
    {
        "assembly-anchor-emitted-by-pcode": _OwnerPathStage.ANCHOR,
        "pcode-operand-lineage": _OwnerPathStage.PCODE_LINEAGE,
        "pcode-operand-uses-virtual": _OwnerPathStage.VIRTUAL,
        "object-materializes-virtual": _OwnerPathStage.OBJECT,
        "maps-to-allocator-node": _OwnerPathStage.ALLOCATOR,
        "object-has-stack-home": _OwnerPathStage.FRAME,
    }
)


def _branch_sort_key(
    records: tuple[EvidenceNode | EvidenceEdge, ...],
) -> bytes:
    return canonical_bytes([_record_json(record) for record in records])


def _node_for_edge_endpoint(
    index: _OwnerEvidenceIndex,
    edge: EvidenceEdge,
    endpoint: str,
) -> EvidenceNode | None:
    record_id = edge.source_id if endpoint == "source" else edge.target_id
    return index.node_by_id.get(record_id)


def _consistent_hint_value(values: Iterable[object]) -> object | None:
    known = tuple(value for value in values if value is not None)
    return known[0] if known and all(value == known[0] for value in known[1:]) else None


def _hint_for_branch(
    records: tuple[EvidenceNode | EvidenceEdge, ...],
) -> _OwnerRoleHint:
    operand_values: list[object] = []
    register_values: list[object] = []
    stack_role_values: list[object] = []
    type_size_values: list[object] = []
    frame_area_values: list[object] = []
    for record in records:
        operand_values.append(record.attributes.get("machine_operand_key"))
        if isinstance(record, EvidenceNode):
            if record.kind == "assembly-operand-anchor":
                operand_values.append(record.role_key)
            elif record.kind == "retail-virtual-register":
                register_values.append({0: "gpr", 1: "fpr"}.get(record.attributes.get("class_id")))
            elif record.kind == "compiler-object":
                type_size = record.attributes.get("type_size")
                type_size_values.append(type_size if _is_int(type_size) and type_size > 0 else None)
            elif record.kind == "stack-object":
                stack_role_values.append(record.role_key)
                frame_area_values.append(record.attributes.get("area"))
        elif record.kind == "object-has-stack-home":
            stack_role_values.append(record.attributes.get("semantic_stack_role"))
            frame_area_values.append(record.attributes.get("area"))
    operand = _consistent_hint_value(operand_values)
    register_class = _consistent_hint_value(register_values)
    semantic_stack_role = _consistent_hint_value(stack_role_values)
    type_size = _consistent_hint_value(type_size_values)
    frame_area = _consistent_hint_value(frame_area_values)
    return _OwnerRoleHint(
        operand if isinstance(operand, str) else None,
        register_class if isinstance(register_class, str) else None,
        semantic_stack_role if isinstance(semantic_stack_role, str) else None,
        type_size if _is_int(type_size) and type_size > 0 else None,
        frame_area if isinstance(frame_area, str) else None,
    )


def _edge_endpoint_kinds_are_valid(
    edge: EvidenceEdge,
    source: EvidenceNode,
    target: EvidenceNode,
) -> bool:
    if edge.kind == "pcode-operand-lineage":
        return (source.kind, target.kind) in {
            ("retail-pcode", "pcode-operand"),
            ("pcode-operand", "pcode-operand"),
        }
    return (source.kind, target.kind) == {
        "assembly-anchor-emitted-by-pcode": (
            "assembly-operand-anchor",
            "retail-pcode",
        ),
        "pcode-operand-uses-virtual": (
            "pcode-operand",
            "retail-virtual-register",
        ),
        "object-materializes-virtual": (
            "compiler-object",
            "retail-virtual-register",
        ),
        "maps-to-allocator-node": (
            "retail-virtual-register",
            "allocator-node",
        ),
        "object-has-stack-home": ("compiler-object", "stack-object"),
    }.get(edge.kind)


def _partial_for_edge(
    index: _OwnerEvidenceIndex,
    edge: EvidenceEdge,
) -> _PartialOwnerPath:
    source = _node_for_edge_endpoint(index, edge, "source")
    target = _node_for_edge_endpoint(index, edge, "target")
    records = tuple(record for record in (source, edge, target) if record is not None)
    if source is None or target is None:
        reason = "unregistered-support"
    elif not _edge_endpoint_kinds_are_valid(edge, source, target):
        reason = "malformed-support"
    else:
        reason = "plausible-owner-alternative"
    return _PartialOwnerPath(
        _OWNER_EDGE_STAGES[edge.kind],
        _hint_for_branch(records),
        records,
        reason,
    )


def _enumerate_candidate_branches(
    index: _OwnerEvidenceIndex,
) -> _CandidateEnumeration:
    complete = tuple(
        sorted(
            _enumerate_candidates(index),
            key=lambda candidate: _branch_sort_key(candidate.path_records),
        )
    )
    accounted_edge_ids = {
        record.record_id
        for candidate in complete
        for record in candidate.path_records
        if isinstance(record, EvidenceEdge) and record.kind in _OWNER_EDGE_STAGES
    }

    # Mutation-parent lineage edges are a side proof validated by
    # _validate_lineage_output, not another retail-PCode continuation.
    complete_lineage_ids = {candidate.lineage.record_id for candidate in complete}
    for edge in index.edges_by_kind.get("pcode-operand-lineage", ()):
        source = index.node_by_id.get(edge.source_id)
        if edge.target_id in complete_lineage_ids and source is not None and source.kind != "retail-pcode":
            accounted_edge_ids.add(edge.record_id)

    remaining_edges = tuple(
        edge
        for kind in _OWNER_EDGE_STAGES
        for edge in sorted(index.edges_by_kind.get(kind, ()), key=_record_content)
        if edge.record_id not in accounted_edge_ids
    )
    complete_node_ids = {
        record.record_id
        for candidate in complete
        for record in candidate.path_records
        if isinstance(record, EvidenceNode)
    }
    edge_indices_by_noncomplete_node: dict[str, list[int]] = {}
    for edge_index, edge in enumerate(remaining_edges):
        for record_id in (edge.source_id, edge.target_id):
            if record_id not in complete_node_ids:
                edge_indices_by_noncomplete_node.setdefault(record_id, []).append(edge_index)

    partial: list[_PartialOwnerPath] = []
    visited_edge_indices: set[int] = set()
    stage_order = {stage: index for index, stage in enumerate(_OwnerPathStage)}
    for initial_index in range(len(remaining_edges)):
        if initial_index in visited_edge_indices:
            continue
        component_indices: set[int] = set()
        pending = [initial_index]
        while pending:
            edge_index = pending.pop()
            if edge_index in component_indices:
                continue
            component_indices.add(edge_index)
            edge = remaining_edges[edge_index]
            for record_id in (edge.source_id, edge.target_id):
                if record_id in complete_node_ids:
                    continue
                pending.extend(edge_indices_by_noncomplete_node.get(record_id, ()))
        visited_edge_indices.update(component_indices)
        component_edges = tuple(remaining_edges[edge_index] for edge_index in sorted(component_indices))
        edge_occurrences: dict[str, int] = {}
        representative_edges: dict[str, EvidenceEdge] = {}
        for edge in component_edges:
            edge_occurrences[edge.record_id] = edge_occurrences.get(edge.record_id, 0) + 1
            representative_edges.setdefault(edge.record_id, edge)
        record_by_id: dict[str, EvidenceNode | EvidenceEdge] = {}
        for edge in representative_edges.values():
            source = _node_for_edge_endpoint(index, edge, "source")
            target = _node_for_edge_endpoint(index, edge, "target")
            for record in (source, edge, target):
                if record is not None:
                    record_by_id.setdefault(record.record_id, record)
        records = tuple(sorted(record_by_id.values(), key=_record_content))
        edge_partials = tuple(_partial_for_edge(index, edge) for edge in representative_edges.values())
        reason = (
            "unregistered-support"
            if any(item.stop_reason == "unregistered-support" for item in edge_partials)
            else (
                "malformed-support"
                if any(item.stop_reason == "malformed-support" for item in edge_partials)
                else "plausible-owner-alternative"
            )
        )
        stage = max(
            (item.stage for item in edge_partials),
            key=stage_order.__getitem__,
        )
        branch = _PartialOwnerPath(
            stage,
            _hint_for_branch(records),
            records,
            reason,
        )
        partial.extend(branch for _ in range(max(edge_occurrences.values())))
    anchor_edge_source_ids = {
        edge.source_id
        for edge in index.edges_by_kind.get(
            "assembly-anchor-emitted-by-pcode",
            (),
        )
    }
    complete_anchor_ids = {candidate.anchor.record_id for candidate in complete}
    partial.extend(
        _PartialOwnerPath(
            _OwnerPathStage.ANCHOR,
            _hint_for_branch((anchor,)),
            (anchor,),
            "plausible-owner-alternative",
        )
        for anchor in sorted(index.node_by_id.values(), key=_record_content)
        if anchor.kind == "assembly-operand-anchor"
        and anchor.record_id not in anchor_edge_source_ids
        and anchor.record_id not in complete_anchor_ids
    )
    partial.sort(
        key=lambda item: canonical_bytes(
            {
                "stage": item.stage.value,
                "hint": {
                    "operand_key": item.hint.operand_key,
                    "register_class": item.hint.register_class,
                    "semantic_stack_role": item.hint.semantic_stack_role,
                    "type_size": item.hint.type_size,
                    "frame_area": item.hint.frame_area,
                },
                "stop_reason": item.stop_reason,
                "records": [_record_json(record) for record in item.records],
            }
        )
    )
    traversed = frozenset(edge.record_id for kind in _OWNER_EDGE_STAGES for edge in index.edges_by_kind.get(kind, ()))
    return _CandidateEnumeration(complete, tuple(partial), traversed)


def _role_matches_hint(role: OwnerRoleKey, hint: _OwnerRoleHint) -> bool:
    comparisons = (
        (hint.operand_key, role.operand_key),
        (hint.register_class, role.register_class),
        (hint.semantic_stack_role, role.semantic_stack_role),
        (hint.type_size, role.type_size),
        (hint.frame_area, role.frame_area),
    )
    known = tuple((actual, expected) for actual, expected in comparisons if actual is not None)
    return bool(known) and all(actual == expected for actual, expected in known)


def _partial_rejections(
    enumeration: _CandidateEnumeration,
    observed_roles: Iterable[OwnerRoleKey],
) -> tuple[
    tuple[OwnerCertificateRejection, ...],
    tuple[OwnerCertificateRejection, ...],
]:
    roles = tuple(sorted(set(observed_roles)))
    role_rejections: list[OwnerCertificateRejection] = []
    global_rejections: list[OwnerCertificateRejection] = []
    for partial in enumeration.partial:
        compatible = tuple(role for role in roles if _role_matches_hint(role, partial.hint))
        if compatible:
            role_rejections.extend(_rejection(partial.stop_reason, role, partial.records) for role in compatible)
            continue
        global_reason = (
            partial.stop_reason
            if partial.stop_reason in {"unregistered-support", "malformed-support"}
            else "disconnected-owner-path"
        )
        global_rejections.append(_rejection(global_reason, candidates=partial.records))
    return tuple(role_rejections), tuple(global_rejections)


def _role_for(candidate: _CandidatePath) -> OwnerRoleKey | OwnerCertificateRejection:
    try:
        role = OwnerRoleKey(
            str(candidate.anchor.attributes.get("machine_operand_key")),
            {0: "gpr", 1: "fpr"}[candidate.virtual.attributes.get("class_id")],
            str(candidate.stack.role_key),
            candidate.owner.attributes.get("type_size"),
            str(candidate.stack.attributes.get("area")),
        )
        role.validate()
    except (KeyError, TypeError, ValueError):
        return _rejection("malformed-support", candidates=candidate.path_records)
    return role


def _supports_for_records(
    evidence: ObjectBindingEvidence,
    index: _OwnerEvidenceIndex,
    records: Iterable[EvidenceNode | EvidenceEdge],
    role: OwnerRoleKey,
) -> tuple[EvidenceNode, ...] | OwnerCertificateRejection:
    by_id: dict[str, EvidenceNode] = {}
    for record in records:
        registered = _registered_record(index, record.record_id)
        if isinstance(registered, OwnerCertificateRejection) or _record_content(registered) != _record_content(record):
            return _rejection("unregistered-support", role, (record,))
        if (
            record.producer_confidence is Confidence.HEURISTIC
            or record.adapter_confidence is Confidence.HEURISTIC
            or record.confidence is Confidence.HEURISTIC
        ):
            return _rejection("malformed-support", role, (record,))
        endpoints = (record.source_id, record.target_id) if isinstance(record, EvidenceEdge) else ()
        if isinstance(record, EvidenceEdge) and not set(endpoints).issubset(record.provenance.input_record_ids):
            return _rejection("unregistered-support", role, (record,))
        support = _validated_support_records(evidence, index, record, endpoints, role)
        if isinstance(support, OwnerCertificateRejection):
            return support
        for item in support:
            by_id[item.record_id] = item
    return tuple(by_id[key] for key in sorted(by_id))


def _support_of_kind(
    support: Iterable[EvidenceNode],
    support_kind: str,
    *,
    shape: str | None = None,
) -> tuple[EvidenceNode, ...]:
    return tuple(
        item
        for item in support
        if item.attributes.get("support_kind") == support_kind
        and (
            shape is None
            or (shape == "emission" and "code_offset" in item.attributes)
            or (shape == "mutation" and "event_index" in item.attributes)
        )
    )


def _validate_emission(
    evidence: ObjectBindingEvidence,
    candidate: _CandidatePath,
    role: OwnerRoleKey,
    support: tuple[EvidenceNode, ...],
) -> tuple[int, tuple[EvidenceNode, ...]] | OwnerCertificateRejection:
    generations = _support_of_kind(support, "pcode-generation")
    ranges = _support_of_kind(support, "pcode-code-range")
    emissions = _support_of_kind(support, "pcode-emission")
    direct_lineages = tuple(
        item
        for item in _support_of_kind(support, "pcode-lineage-event", shape="emission")
        if item.attributes.get("event_kind") == "emission-lineage"
    )
    if not all(len(items) == 1 for items in (generations, ranges, emissions, direct_lineages)):
        return _rejection("malformed-support", role, candidate.path_records, support)
    generation, code_range, emission, direct_lineage = (
        generations[0],
        ranges[0],
        emissions[0],
        direct_lineages[0],
    )
    anchor_edge = next(
        edge
        for edge in candidate.path_records
        if isinstance(edge, EvidenceEdge) and edge.kind == "assembly-anchor-emitted-by-pcode"
    )
    pcode_lineage_edge = next(
        edge
        for edge in candidate.path_records
        if isinstance(edge, EvidenceEdge)
        and edge.kind == "pcode-operand-lineage"
        and edge.source_id == candidate.pcode.record_id
    )
    if (
        any(
            generation.record_id not in record.provenance.input_record_ids
            for record in (candidate.pcode, candidate.anchor, anchor_edge)
        )
        or any(
            code_range.record_id not in record.provenance.input_record_ids for record in (candidate.anchor, anchor_edge)
        )
        or any(
            emission.record_id not in record.provenance.input_record_ids
            for record in (candidate.anchor, anchor_edge, pcode_lineage_edge)
        )
        or any(
            direct_lineage.record_id not in record.provenance.input_record_ids
            for record in (candidate.anchor, anchor_edge, pcode_lineage_edge)
        )
    ):
        return _rejection("malformed-support", role, candidate.path_records, support)
    pcode_id = candidate.pcode.attributes.get("pcode_id")
    allocation_generation = candidate.pcode.attributes.get("allocation_generation")
    offset = candidate.anchor.attributes.get("code_offset")
    operand_key = candidate.anchor.attributes.get("machine_operand_key")
    lineage_id = candidate.lineage.attributes.get("operand_lineage_id")
    range_start = code_range.attributes.get("start")
    range_end = code_range.attributes.get("end_exclusive")
    mappings = tuple(
        mapping
        for item in candidate.pcode.attributes.get("code_ranges", ())
        if isinstance(item, Mapping)
        for mapping in item.get("machine_operand_mappings", ())
        if isinstance(mapping, Mapping)
        and mapping.get("machine_operand_key") == operand_key
        and mapping.get("operand_lineage_id") == lineage_id
        and _raw_mapping_matches_supported_anchor(
            item,
            mapping,
            range_start,
            range_end,
            offset,
        )
    )
    values = (
        candidate.anchor.attributes.get("physical_register"),
        emission.attributes.get("physical_register"),
        *(mapping.get("physical_register") for mapping in mappings),
    )
    if (
        len(mappings) != 1
        or any(
            item.attributes.get("pcode_id") != pcode_id
            or item.attributes.get("allocation_generation") != allocation_generation
            for item in (generation, code_range, emission, direct_lineage)
        )
        or not (
            _is_int(offset)
            and _validated_instruction_anchor(
                range_start,
                range_end,
                mappings[0].get("instruction_offset_within_range"),
            )
            == offset
        )
        or emission.attributes.get("code_offset") != offset
        or emission.attributes.get("machine_operand_key") != operand_key
        or emission.attributes.get("operand_lineage_id") != lineage_id
        or direct_lineage.attributes.get("code_offset") != offset
        or direct_lineage.attributes.get("operand_lineage_id") != lineage_id
        or any(
            edge.attributes.get("code_offset") != offset or edge.attributes.get("machine_operand_key") != operand_key
            for edge in candidate.path_records
            if isinstance(edge, EvidenceEdge)
            and edge.kind in {"assembly-anchor-emitted-by-pcode", "pcode-operand-lineage"}
            and edge.source_id in {candidate.anchor.record_id, candidate.pcode.record_id}
        )
    ):
        return _rejection("malformed-support", role, candidate.path_records, support)
    if not all(_is_physical(value) for value in values):
        return _rejection("malformed-support", role, candidate.path_records, support)
    if any(value != values[0] for value in values[1:]):
        return _rejection("split-physical-assignment", role, candidate.path_records, support)
    return values[0], (generation, code_range, emission, direct_lineage)


def _validate_lineage_output(
    evidence: ObjectBindingEvidence,
    index: _OwnerEvidenceIndex,
    candidate: _CandidatePath,
    role: OwnerRoleKey,
    support: tuple[EvidenceNode, ...],
) -> tuple[tuple[EvidenceNode | EvidenceEdge, ...], tuple[EvidenceNode, ...]] | OwnerCertificateRejection:
    mutation_support = tuple(
        item
        for item in _support_of_kind(support, "pcode-lineage-event", shape="mutation")
        if item.attributes.get("operand_lineage_id") == candidate.lineage.attributes.get("operand_lineage_id")
        and item.attributes.get("side") == "outputs"
    )
    if len(mutation_support) != 1:
        return _rejection("lineage-parent-mismatch", role, candidate.path_records, mutation_support)
    lineage_support = mutation_support[0]
    parent_ids = lineage_support.attributes.get("parent_lineage_ids")
    if not _is_string_tuple(parent_ids):
        return _rejection("lineage-parent-mismatch", role, candidate.path_records, mutation_support)
    selected = tuple(
        edge
        for edge in index.edges_by_kind_target.get(("pcode-operand-lineage", candidate.lineage.record_id), ())
        if edge.attributes.get("event_index") == lineage_support.attributes.get("event_index")
        and edge.attributes.get("lineage_event_side") == "outputs"
        and edge.attributes.get("mutation_kind") == lineage_support.attributes.get("mutation_kind")
        and edge.attributes.get("operand_lineage_id") == lineage_support.attributes.get("operand_lineage_id")
        and edge.attributes.get("parent_lineage_ids") == parent_ids
    )
    parent_pairs: list[tuple[EvidenceNode, EvidenceEdge]] = []
    for edge in selected:
        parent_node = index.node_by_id.get(edge.source_id)
        if (
            parent_node is None
            or parent_node.kind != "pcode-operand"
            or edge.attributes.get("parent_lineage_id") != parent_node.attributes.get("operand_lineage_id")
        ):
            return _rejection(
                "lineage-parent-mismatch",
                role,
                (*candidate.path_records, *selected),
                mutation_support,
            )
        parent_pairs.append((parent_node, edge))
    parent_pairs.sort(
        key=lambda pair: (
            str(pair[0].attributes.get("operand_lineage_id")),
            pair[0].record_id,
            pair[1].record_id,
            canonical_bytes(_safe_json(_record_json(pair[0]))),
            canonical_bytes(_safe_json(_record_json(pair[1]))),
        )
    )
    parent_nodes = tuple(node for node, _edge in parent_pairs)
    selected = tuple(edge for _node, edge in parent_pairs)
    actual = tuple(sorted(str(node.attributes.get("operand_lineage_id")) for node in parent_nodes))
    if actual != parent_ids:
        return _rejection("lineage-parent-mismatch", role, (*candidate.path_records, *selected), mutation_support)
    if lineage_support.record_id not in candidate.lineage.provenance.input_record_ids or any(
        lineage_support.record_id not in edge.provenance.input_record_ids for edge in selected
    ):
        return _rejection("lineage-parent-mismatch", role, (*candidate.path_records, *selected), mutation_support)
    parent_records: tuple[EvidenceNode | EvidenceEdge, ...] = (
        *parent_nodes,
        *selected,
    )
    parent_support = _supports_for_records(evidence, index, parent_records, role)
    if isinstance(parent_support, OwnerCertificateRejection):
        return parent_support
    return parent_records, tuple({item.record_id: item for item in (*mutation_support, *parent_support)}.values())


def _validate_allocator_origin(
    candidate: _CandidatePath,
    role: OwnerRoleKey,
    support: tuple[EvidenceNode, ...],
    decoded_physical: int,
) -> tuple[int, tuple[EvidenceNode, ...]] | OwnerCertificateRejection:
    rewrites = _support_of_kind(support, "pcode-rewrite")
    bindings = _support_of_kind(support, "object-virtual-binding")
    if len(rewrites) != 1 or len(bindings) != 1:
        return _rejection("allocator-origin-contradiction", role, candidate.path_records, support)
    rewrite, binding = rewrites[0], bindings[0]
    object_edge = next(
        edge
        for edge in candidate.path_records
        if isinstance(edge, EvidenceEdge) and edge.kind == "object-materializes-virtual"
    )
    allocator_edge = next(
        edge
        for edge in candidate.path_records
        if isinstance(edge, EvidenceEdge) and edge.kind == "maps-to-allocator-node"
    )
    virtual_edge = next(
        edge
        for edge in candidate.path_records
        if isinstance(edge, EvidenceEdge) and edge.kind == "pcode-operand-uses-virtual"
    )
    if any(
        rewrite.record_id not in record.provenance.input_record_ids
        for record in (virtual_edge, allocator_edge, candidate.allocator)
    ) or any(
        binding.record_id not in record.provenance.input_record_ids
        for record in (object_edge, allocator_edge, candidate.allocator)
    ):
        return _rejection("allocator-origin-contradiction", role, candidate.path_records, support)
    common = {
        "class_id": candidate.virtual.attributes.get("class_id"),
        "virtual": candidate.virtual.attributes.get("virtual"),
    }
    physicals = (
        decoded_physical,
        candidate.virtual.attributes.get("physical_register"),
        rewrite.attributes.get("allocated_physical"),
        candidate.allocator.attributes.get("assigned_phys"),
        allocator_edge.attributes.get("assigned_phys"),
    )
    if not all(_is_physical(value) for value in physicals):
        return _rejection("malformed-support", role, candidate.path_records, support)
    if any(value != physicals[0] for value in physicals[1:]):
        return _rejection("split-physical-assignment", role, candidate.path_records, support)
    if (
        any(rewrite.attributes.get(key) != value for key, value in common.items())
        or any(binding.attributes.get(key) != value for key, value in common.items())
        or any(object_edge.attributes.get(key) != value for key, value in common.items())
        or allocator_edge.attributes.get("class_id") != common["class_id"]
        or candidate.allocator.attributes.get("class_id") != common["class_id"]
        or candidate.allocator.attributes.get("virtual") != common["virtual"]
        or candidate.virtual.attributes.get("class") != {0: "r", 1: "f"}.get(common["class_id"])
        or binding.attributes.get("object_id") != candidate.owner.attributes.get("object_id")
        or object_edge.attributes.get("object_id") != candidate.owner.attributes.get("object_id")
        or binding.attributes.get("allocation_generation") != candidate.owner.attributes.get("allocation_generation")
        or binding.attributes.get("ig_id") != object_edge.attributes.get("ig_id")
        or binding.attributes.get("ig_id") != allocator_edge.attributes.get("ig_id")
        or binding.attributes.get("ig_id") != candidate.allocator.attributes.get("ig_id")
        or rewrite.attributes.get("operand_lineage_id") != candidate.lineage.attributes.get("operand_lineage_id")
        or rewrite.attributes.get("pcode_id") != candidate.pcode.attributes.get("pcode_id")
        or virtual_edge.attributes.get("pcode_id") != candidate.pcode.attributes.get("pcode_id")
        or virtual_edge.attributes.get("operand_lineage_id") != candidate.lineage.attributes.get("operand_lineage_id")
        or virtual_edge.attributes.get("machine_operand_key") != role.operand_key
        or rewrite.attributes.get("allocation_generation") != candidate.pcode.attributes.get("allocation_generation")
    ):
        return _rejection("allocator-origin-contradiction", role, candidate.path_records, support)
    return physicals[0], (rewrite, binding)


def _validate_object_identity(
    candidate: _CandidatePath,
    role: OwnerRoleKey,
    support: tuple[EvidenceNode, ...],
) -> tuple[EvidenceNode, ...] | OwnerCertificateRejection:
    snapshots = _support_of_kind(support, "object-stage-snapshot")
    owner_snapshots = candidate.owner.attributes.get("stage_snapshots")
    if not isinstance(owner_snapshots, tuple) or len(snapshots) != len(owner_snapshots):
        return _rejection("allocator-origin-contradiction", role, candidate.path_records, snapshots)
    object_id = candidate.owner.attributes.get("object_id")
    generation = candidate.owner.attributes.get("allocation_generation")
    expected = tuple(
        sorted(
            (
                snapshot.get("stage"),
                snapshot.get("allocation_generation"),
                snapshot.get("lifecycle_sequence_at_capture"),
            )
            for snapshot in owner_snapshots
            if isinstance(snapshot, Mapping)
        )
    )
    actual = tuple(
        sorted(
            (
                item.attributes.get("stage"),
                item.attributes.get("allocation_generation"),
                item.attributes.get("lifecycle_sequence_at_capture"),
            )
            for item in snapshots
        )
    )
    if (
        len(expected) != len(owner_snapshots)
        or expected != actual
        or len({item[0] for item in actual}) != len(actual)
        or any(
            item.attributes.get("object_id") != object_id
            or item.attributes.get("allocation_generation") != generation
            or item.record_id not in candidate.owner.provenance.input_record_ids
            for item in snapshots
        )
    ):
        return _rejection("allocator-origin-contradiction", role, candidate.path_records, snapshots)
    return snapshots


def _validate_frame_binding(
    candidate: _CandidatePath,
    role: OwnerRoleKey,
    support: tuple[EvidenceNode, ...],
) -> tuple[OwnerSemanticState, tuple[EvidenceNode, ...]] | OwnerCertificateRejection:
    frames = _support_of_kind(support, "object-frame-binding")
    if len(frames) != 1:
        return _rejection("frame-binding-contradiction", role, candidate.path_records, support)
    frame = frames[0]
    frame_edge = next(
        edge
        for edge in candidate.path_records
        if isinstance(edge, EvidenceEdge) and edge.kind == "object-has-stack-home"
    )
    if any(frame.record_id not in record.provenance.input_record_ids for record in (candidate.stack, frame_edge)):
        return _rejection("frame-binding-contradiction", role, candidate.path_records, (frame,))
    areas = candidate.owner.attributes.get("areas")
    if not isinstance(areas, tuple) or not all(isinstance(item, str) for item in areas):
        return _rejection("malformed-support", role, candidate.path_records, (frame,))
    if (
        frame.attributes.get("object_id") != candidate.owner.attributes.get("object_id")
        or frame.attributes.get("allocation_generation") != candidate.owner.attributes.get("allocation_generation")
        or frame.attributes.get("area") != candidate.stack.attributes.get("area")
        or frame.attributes.get("area") != frame_edge.attributes.get("area")
        or frame.attributes.get("area") not in areas
        or frame.attributes.get("semantic_stack_role") != candidate.stack.role_key
        or frame.attributes.get("semantic_stack_role") != frame_edge.attributes.get("semantic_stack_role")
        or frame.attributes.get("final_r1_offset") != candidate.stack.attributes.get("offset")
        or frame.attributes.get("size") != candidate.stack.attributes.get("size")
        or candidate.stack.attributes.get("start") != candidate.stack.attributes.get("offset")
        or candidate.stack.attributes.get("symbol") != candidate.stack.role_key
        or candidate.stack.attributes.get("side") != "current"
    ):
        return _rejection("frame-binding-contradiction", role, candidate.path_records, (frame,))
    try:
        state = OwnerSemanticState(
            0,
            frame.attributes.get("final_r1_offset"),
            frame.attributes.get("size"),
        )
        state.validate()
    except (TypeError, ValueError):
        return _rejection("malformed-support", role, candidate.path_records, (frame,))
    return state, (frame,)


def _validate_candidate(
    evidence: ObjectBindingEvidence,
    index: _OwnerEvidenceIndex,
    candidate: _CandidatePath,
) -> _OwnerPath | OwnerCertificateRejection:
    role = _role_for(candidate)
    if isinstance(role, OwnerCertificateRejection):
        return role
    expected_node_kinds = (
        (candidate.owner, "compiler-object"),
        (candidate.anchor, "assembly-operand-anchor"),
        (candidate.pcode, "retail-pcode"),
        (candidate.lineage, "pcode-operand"),
        (candidate.virtual, "retail-virtual-register"),
        (candidate.allocator, "allocator-node"),
        (candidate.stack, "stack-object"),
    )
    if any(node.kind != kind for node, kind in expected_node_kinds) or candidate.anchor.role_key != role.operand_key:
        return _rejection("malformed-support", role, candidate.path_records)
    support = _supports_for_records(evidence, index, candidate.path_records, role)
    if isinstance(support, OwnerCertificateRejection):
        return support
    scope_rejection = _validate_common_scope(evidence, (*candidate.path_records, *support))
    if scope_rejection is not None:
        return _rejection(scope_rejection.reason, role, candidate.path_records, support)
    emission = _validate_emission(evidence, candidate, role, support)
    if isinstance(emission, OwnerCertificateRejection):
        return emission
    decoded_physical, emission_support = emission
    lineage = _validate_lineage_output(evidence, index, candidate, role, support)
    if isinstance(lineage, OwnerCertificateRejection):
        return lineage
    lineage_records, lineage_support = lineage
    all_records = _unique_records((*candidate.path_records, *lineage_records))
    all_support = tuple({item.record_id: item for item in (*support, *emission_support, *lineage_support)}.values())
    object_identity = _validate_object_identity(candidate, role, all_support)
    if isinstance(object_identity, OwnerCertificateRejection):
        return object_identity
    allocator = _validate_allocator_origin(candidate, role, all_support, decoded_physical)
    if isinstance(allocator, OwnerCertificateRejection):
        return allocator
    physical, allocator_support = allocator
    frame = _validate_frame_binding(candidate, role, all_support)
    if isinstance(frame, OwnerCertificateRejection):
        return frame
    state, frame_support = frame
    state = OwnerSemanticState(physical, state.stack_offset, state.stack_size)
    state.validate()
    raw_support = tuple(
        sorted(
            {
                item.record_id: item
                for item in (
                    *all_support,
                    *allocator_support,
                    *frame_support,
                )
            }.values(),
            key=lambda item: item.record_id,
        )
    )
    return _OwnerPath(
        role,
        state,
        candidate.owner,
        candidate.anchor,
        candidate.pcode,
        candidate.lineage,
        candidate.virtual,
        candidate.allocator,
        candidate.stack,
        all_records,
        raw_support,
    )


def _validate_core(evidence: ObjectBindingEvidence) -> _ValidationOutcome:
    global_rejections: list[OwnerCertificateRejection] = []
    if not isinstance(evidence.capabilities, frozenset) or not all(
        _is_nonempty_str(item) for item in evidence.capabilities
    ):
        global_rejections.append(_rejection("malformed-support"))
    elif not _REQUIRED_CAPABILITIES <= evidence.capabilities:
        global_rejections.append(_rejection("missing-required-capability"))
    if not _valid_owner_instrumentation_identity(evidence.instrumentation_identity):
        global_rejections.append(_rejection("missing-instrumentation-identity"))
    all_records = (*evidence.nodes, *evidence.edges)
    scope_rejection = _validate_common_scope(evidence, all_records)
    if scope_rejection is not None:
        global_rejections.append(scope_rejection)
    if scope_rejection is not None or any(rejection.reason == "malformed-support" for rejection in global_rejections):
        return _ValidationOutcome(
            (),
            (),
            tuple(sorted(global_rejections, key=lambda item: item.rejection_id)),
        )

    index = _index_evidence(evidence)
    conflicting_groups = _conflicting_record_groups(index)
    if conflicting_groups:
        global_rejections.extend(
            _rejection("unregistered-support", candidates=records) for records in conflicting_groups
        )
        return _ValidationOutcome(
            (),
            (),
            tuple(sorted(global_rejections, key=lambda item: item.rejection_id)),
        )
    enumeration = _enumerate_candidate_branches(index)
    paths: list[_OwnerPath] = []
    role_rejections: list[OwnerCertificateRejection] = []
    for candidate in enumeration.complete:
        validated = _validate_candidate(evidence, index, candidate)
        if isinstance(validated, OwnerCertificateRejection):
            if validated.role is None:
                global_rejections.append(validated)
            else:
                role_rejections.append(validated)
        else:
            paths.append(validated)

    roles = {path.role for path in paths}
    roles.update(rejection.role for rejection in role_rejections if rejection.role is not None)
    partial_role_rejections, partial_global_rejections = _partial_rejections(
        enumeration,
        roles,
    )
    if any(rejection.reason == "missing-required-capability" for rejection in global_rejections):
        partial_global_rejections = tuple(
            rejection for rejection in partial_global_rejections if rejection.reason != "disconnected-owner-path"
        )
    role_rejections.extend(partial_role_rejections)
    global_rejections.extend(partial_global_rejections)
    return _ValidationOutcome(
        tuple(paths),
        tuple(sorted(role_rejections, key=lambda item: item.rejection_id)),
        tuple(sorted(global_rejections, key=lambda item: item.rejection_id)),
    )


def _validate_provenance_shape(provenance: object) -> None:
    if type(provenance) is not Provenance:
        raise _MalformedEvidence("record provenance has an unexpected type")
    if (
        not _is_sha256(provenance.artifact_sha256)
        or not _is_nonempty_str(provenance.parser)
        or not _is_nonempty_str(provenance.derivation_rule)
        or not isinstance(provenance.input_record_ids, tuple)
        or not all(_is_nonempty_str(item) for item in provenance.input_record_ids)
    ):
        raise _MalformedEvidence("record provenance strings are malformed")
    for raw_offset in (provenance.raw_start, provenance.raw_end):
        if raw_offset is not None and (not _is_int(raw_offset) or not 0 <= raw_offset <= 0x7FFFFFFFFFFFFFFF):
            raise _MalformedEvidence("record provenance range is malformed")
    if (
        provenance.raw_start is not None
        and provenance.raw_end is not None
        and provenance.raw_start > provenance.raw_end
    ):
        raise _MalformedEvidence("record provenance range is reversed")


def _validate_record_shape(record: EvidenceNode | EvidenceEdge) -> None:
    if not all(
        _is_nonempty_str(value) for value in (record.record_id, record.compile_id, record.function, record.kind)
    ):
        raise _MalformedEvidence("evidence record identity is malformed")
    if any(
        type(value) is not Confidence
        for value in (
            record.producer_confidence,
            record.adapter_confidence,
            record.confidence,
        )
    ):
        raise _MalformedEvidence("evidence record confidence is malformed")
    _validate_provenance_shape(record.provenance)
    if not isinstance(record.attributes, Mapping) or not all(isinstance(key, str) for key in record.attributes):
        raise _MalformedEvidence("evidence record attributes are malformed")
    if isinstance(record, EvidenceNode):
        if record.role_key is not None and not _is_nonempty_str(record.role_key):
            raise _MalformedEvidence("evidence node role is malformed")
    elif not _is_nonempty_str(record.source_id) or not _is_nonempty_str(record.target_id):
        raise _MalformedEvidence("evidence edge endpoints are malformed")


def _validate_diagnostic_shape(evidence: ObjectBindingEvidence) -> None:
    if type(evidence) is not ObjectBindingEvidence:
        raise _MalformedEvidence("unexpected owner evidence type")
    if (
        not isinstance(evidence.nodes, tuple)
        or not all(type(node) is EvidenceNode for node in evidence.nodes)
        or not isinstance(evidence.edges, tuple)
        or not all(type(edge) is EvidenceEdge for edge in evidence.edges)
    ):
        raise _MalformedEvidence("owner evidence record containers are malformed")
    if (
        type(evidence.capabilities) is not frozenset
        or not all(_is_nonempty_str(item) for item in evidence.capabilities)
        or not _is_nonempty_str(evidence.capture_run_id)
        or (evidence.instrumentation_identity is not None and not isinstance(evidence.instrumentation_identity, tuple))
    ):
        raise _MalformedEvidence("owner evidence metadata is malformed")
    for record in (*evidence.nodes, *evidence.edges):
        _validate_record_shape(record)


def _validate_diagnostic_core(evidence: ObjectBindingEvidence) -> _ValidationOutcome:
    """Validate the public persistence shape before semantic validation."""

    _validate_diagnostic_shape(evidence)
    return _validate_core(evidence)


def _path_provenance(path: _OwnerPath) -> tuple[str, ...]:
    return tuple(sorted(record.record_id for record in (*path.path_records, *path.raw_support)))


def _path_group_key(
    path: _OwnerPath,
) -> tuple[OwnerRoleKey, OwnerSemanticState, tuple[str, ...]]:
    return path.role, path.semantic_state, _path_provenance(path)


def _canonical_groups(
    outcome: _ValidationOutcome,
) -> tuple[_CanonicalAlternativeGroup, ...]:
    grouped_paths: dict[
        tuple[OwnerRoleKey, OwnerSemanticState, tuple[str, ...]],
        list[tuple[str, ...]],
    ] = {}
    for path in outcome.paths:
        provenance = _path_provenance(path)
        grouped_paths.setdefault(_path_group_key(path), []).append(provenance)
    groups = [
        _CanonicalAlternativeGroup(
            role,
            state,
            None,
            len(provenance),
            tuple(sorted(provenance)),
        )
        for (role, state, _), provenance in grouped_paths.items()
    ]
    grouped_rejections: dict[tuple[OwnerRoleKey, str, tuple[str, ...]], list[tuple[str, ...]]] = {}
    for rejection in outcome.role_rejections:
        if rejection.role is None:
            continue
        provenance = tuple(sorted((*rejection.candidate_record_ids, *rejection.raw_support_record_ids)))
        grouped_rejections.setdefault((rejection.role, rejection.reason, provenance), []).append(provenance)
    groups.extend(
        _CanonicalAlternativeGroup(
            role,
            None,
            reason,
            len(provenance),
            tuple(sorted(provenance)),
        )
        for (role, reason, _), provenance in grouped_rejections.items()
    )
    return tuple(
        sorted(
            groups,
            key=lambda item: canonical_bytes(
                {
                    "role": item.role.as_json(),
                    "semantic_state": (None if item.semantic_state is None else item.semantic_state.as_json()),
                    "rejection_reason": item.rejection_reason,
                    "multiplicity": item.multiplicity,
                    "provenance_record_ids": item.provenance_record_ids,
                }
            ),
        )
    )


def _representative_paths(
    outcome: _ValidationOutcome,
    canonical_groups: tuple[_CanonicalAlternativeGroup, ...],
) -> tuple[_OwnerPath, ...]:
    by_group: dict[tuple[OwnerRoleKey, OwnerSemanticState, tuple[str, ...]], _OwnerPath] = {}
    for path in outcome.paths:
        by_group.setdefault(_path_group_key(path), path)
    representatives = tuple(
        by_group[(group.role, group.semantic_state, group.provenance_record_ids[0])]
        for group in canonical_groups
        if group.semantic_state is not None and group.rejection_reason is None and group.provenance_record_ids
    )
    return tuple(
        sorted(
            representatives,
            key=lambda path: canonical_bytes(
                {
                    "role": path.role.as_json(),
                    "semantic_state": path.semantic_state.as_json(),
                    "provenance_record_ids": _path_provenance(path),
                }
            ),
        )
    )


def _role_resolutions(
    outcome: _ValidationOutcome,
    certificate_record_ids: tuple[str, ...],
    certificate_paths: tuple[_OwnerPath, ...],
    canonical_groups: tuple[_CanonicalAlternativeGroup, ...],
) -> tuple[OwnerRoleResolution, ...]:
    roles = {path.role for path in outcome.paths}
    roles.update(rejection.role for rejection in outcome.role_rejections if rejection.role is not None)
    resolutions: list[OwnerRoleResolution] = []
    for role in sorted(roles):
        role_groups = tuple(
            group
            for group in canonical_groups
            if group.role == role and group.semantic_state is not None and group.rejection_reason is None
        )
        role_certificate_ids = tuple(
            certificate_record_id
            for certificate_record_id, path in zip(certificate_record_ids, certificate_paths, strict=True)
            if path.role == role
        )
        rejection_by_id: dict[str, OwnerCertificateRejection] = {}
        for rejection in sorted(
            (rejection for rejection in outcome.role_rejections if rejection.role == role),
            key=lambda item: item.rejection_id,
        ):
            rejection_by_id.setdefault(rejection.rejection_id, rejection)
        rejections = tuple(rejection_by_id.values())
        semantic_states = {group.semantic_state for group in role_groups if group.semantic_state is not None}
        if outcome.global_rejections:
            status = OwnerResolutionStatus.INCOMPLETE
        elif any(item.reason in _CONTRADICTORY_REASONS for item in rejections):
            status = OwnerResolutionStatus.CONTRADICTORY
        elif any(item.reason in _INCOMPLETE_REASONS for item in rejections):
            status = OwnerResolutionStatus.INCOMPLETE
        elif len(semantic_states) > 1:
            status = OwnerResolutionStatus.CONTRADICTORY
        elif len(role_groups) > 1 or any(item.reason == "plausible-owner-alternative" for item in rejections):
            status = OwnerResolutionStatus.AMBIGUOUS
        elif len(role_groups) == 1:
            status = OwnerResolutionStatus.UNIQUE
        elif rejections:
            status = OwnerResolutionStatus.INCOMPLETE
        else:
            status = OwnerResolutionStatus.MISSING
        resolutions.append(
            OwnerRoleResolution(
                role,
                status,
                tuple(sorted(set(role_certificate_ids))),
                rejections,
            )
        )
    return tuple(resolutions)


def _validate_owner_evidence(evidence: ObjectBindingEvidence) -> OwnerCertificateResult:
    outcome = _validate_diagnostic_core(evidence)
    canonical_groups = _canonical_groups(outcome)
    certificate_paths = _representative_paths(outcome, canonical_groups)
    try:
        candidate_certificate_ids = tuple(_certificate_record_id(path, evidence) for path in certificate_paths)
    except _MalformedEvidence:
        if not outcome.global_rejections:
            raise
        canonical_groups = _canonical_groups(outcome)
        certificate_paths = ()
        candidate_certificate_ids = ()
    result = OwnerCertificateResult(
        (),
        _role_resolutions(
            outcome,
            candidate_certificate_ids,
            certificate_paths,
            canonical_groups,
        ),
        outcome.global_rejections,
    )
    object.__setattr__(result, "_canonical_groups", canonical_groups)
    return result


def validate_owner_evidence(evidence: ObjectBindingEvidence) -> OwnerCertificateResult:
    """Diagnose arbitrary owner evidence without granting certificate authority."""

    try:
        return _validate_owner_evidence(evidence)
    except _MalformedEvidence:
        return OwnerCertificateResult(
            (),
            (),
            (_rejection("malformed-support"),),
        )


def build_owner_certificates(evidence: ObjectBindingEvidence) -> OwnerCertificateResult:
    """Derive all connected capture-local roles from trusted adapter evidence."""

    if (
        type(evidence) is not ObjectBindingEvidence
        or object.__getattribute__(evidence, "_adapter_token") is not _OBJECT_BINDING_ADAPTER_TOKEN
    ):
        return _trusted_result(
            (),
            (),
            (_rejection("untrusted-diagnostic-materialization"),),
        )
    outcome = _validate_core(evidence)
    canonical_groups = _canonical_groups(outcome)
    ordered_paths = _representative_paths(outcome, canonical_groups)
    try:
        candidate_certificate_ids = tuple(_certificate_record_id(path, evidence) for path in ordered_paths)
    except _MalformedEvidence:
        if outcome.global_rejections:
            return _trusted_result(
                (),
                _role_resolutions(outcome, (), (), canonical_groups),
                outcome.global_rejections,
                canonical_groups,
            )
        malformed = _ValidationOutcome(
            (),
            outcome.role_rejections,
            (_rejection("malformed-support"),),
        )
        malformed_groups = _canonical_groups(malformed)
        return _trusted_result(
            (),
            _role_resolutions(malformed, (), (), malformed_groups),
            malformed.global_rejections,
            malformed_groups,
        )
    blocking_global_rejections = tuple(
        rejection for rejection in outcome.global_rejections if rejection.reason != "disconnected-owner-path"
    )
    if blocking_global_rejections:
        return _trusted_result(
            (),
            _role_resolutions(
                outcome,
                candidate_certificate_ids,
                ordered_paths,
                canonical_groups,
            ),
            outcome.global_rejections,
            canonical_groups,
        )
    try:
        certificates = tuple(_certificate(path, evidence) for path in ordered_paths)
        certificate_support_bindings = _certificate_support_bindings(
            certificates,
            ordered_paths,
        )
    except _MalformedEvidence:
        malformed = _ValidationOutcome(
            (),
            outcome.role_rejections,
            (_rejection("malformed-support"),),
        )
        malformed_groups = _canonical_groups(malformed)
        return _trusted_result(
            (),
            _role_resolutions(malformed, (), (), malformed_groups),
            malformed.global_rejections,
            malformed_groups,
        )
    return _trusted_result(
        certificates,
        _role_resolutions(
            outcome,
            tuple(certificate.record_id for certificate in certificates),
            ordered_paths,
            canonical_groups,
        ),
        outcome.global_rejections,
        canonical_groups,
        certificate_support_bindings,
    )
