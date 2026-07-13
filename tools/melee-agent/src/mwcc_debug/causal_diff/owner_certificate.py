"""Build content-addressed certificates for verified capture-local owners."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from .canonical import canonical_bytes
from .models import Confidence, EvidenceEdge, EvidenceNode, Provenance
from .object_binding_adapter import (
    _OBJECT_BINDING_ADAPTER_TOKEN,
    ObjectBindingEvidence,
    exact_owner_path_record,
)

_TRUST_TOKEN = object()
_RUNTIME_ONLY_ATTRIBUTE_KEYS = frozenset(
    {
        "runtime_address",
        "ignode_runtime_address",
        "list_node_runtime_address",
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
class OwnerCertificateResult:
    certificate_nodes: tuple[EvidenceNode, ...]
    role_resolutions: tuple[OwnerRoleResolution, ...]
    global_rejections: tuple[OwnerCertificateRejection, ...]
    _token: object | None = field(default=None, repr=False, compare=False)

    @property
    def is_trusted(self) -> bool:
        return self._token is _TRUST_TOKEN

    def certificate(self, record_id: str) -> EvidenceNode | None:
        if not self.is_trusted:
            return None
        return next((node for node in self.certificate_nodes if node.record_id == record_id), None)

    def resolution_for(self, role: OwnerRoleKey) -> OwnerRoleResolution:
        role.validate()
        base = next(
            (item for item in self.role_resolutions if item.role == role),
            OwnerRoleResolution(role, OwnerResolutionStatus.MISSING, (), ()),
        )
        if not self.is_trusted or self.global_rejections:
            return OwnerRoleResolution(
                role,
                OwnerResolutionStatus.INCOMPLETE,
                base.certificate_record_ids,
                (*base.rejections, *self.global_rejections),
            )
        return base


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
        return {
            str(key): _json_value(item)
            for key, item in value.items()
            if key not in _RUNTIME_ONLY_ATTRIBUTE_KEYS
        }
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


def _rejection(reason: str) -> OwnerCertificateRejection:
    rejection_id = hashlib.sha256(
        canonical_bytes(
            {
                "schema_version": "causal-owner-certificate-rejection.v1",
                "reason": reason,
                "role": None,
                "candidate_record_ids": [],
                "raw_support_record_ids": [],
            }
        )
    ).hexdigest()
    return OwnerCertificateRejection(rejection_id, reason, None, (), ())


def _registered_support(
    records: tuple[EvidenceNode | EvidenceEdge, ...],
    registered: Mapping[str, EvidenceNode | EvidenceEdge],
) -> tuple[EvidenceNode, ...]:
    support_ids = {
        input_id
        for record in records
        for input_id in record.provenance.input_record_ids
        if isinstance(registered.get(input_id), EvidenceNode)
        and registered[input_id].kind == "backend-support-record"
    }
    return tuple(
        registered[record_id]
        for record_id in sorted(support_ids)
        if isinstance(registered[record_id], EvidenceNode)
    )


def _unique_records(
    records: tuple[EvidenceNode | EvidenceEdge, ...],
) -> tuple[EvidenceNode | EvidenceEdge, ...]:
    by_id: dict[str, EvidenceNode | EvidenceEdge] = {}
    for record in records:
        by_id.setdefault(record.record_id, record)
    return tuple(by_id.values())


def _enumerate_paths(evidence: ObjectBindingEvidence) -> tuple[_OwnerPath, ...]:
    registered: dict[str, EvidenceNode | EvidenceEdge] = {
        record.record_id: record for record in (*evidence.nodes, *evidence.edges)
    }
    nodes = {node.record_id: node for node in evidence.nodes}
    edges_by_kind = {
        kind: tuple(sorted((edge for edge in evidence.edges if edge.kind == kind), key=lambda item: item.record_id))
        for kind in (
            "assembly-anchor-emitted-by-pcode",
            "pcode-operand-lineage",
            "pcode-operand-uses-virtual",
            "object-materializes-virtual",
            "maps-to-allocator-node",
            "object-has-stack-home",
        )
    }
    paths: list[_OwnerPath] = []
    for anchor_edge in edges_by_kind["assembly-anchor-emitted-by-pcode"]:
        anchor = nodes.get(anchor_edge.source_id)
        pcode = nodes.get(anchor_edge.target_id)
        if anchor is None or pcode is None:
            continue
        for lineage_edge in edges_by_kind["pcode-operand-lineage"]:
            if lineage_edge.source_id != pcode.record_id:
                continue
            lineage = nodes.get(lineage_edge.target_id)
            if lineage is None:
                continue
            for virtual_edge in edges_by_kind["pcode-operand-uses-virtual"]:
                if virtual_edge.source_id != lineage.record_id:
                    continue
                virtual = nodes.get(virtual_edge.target_id)
                if virtual is None:
                    continue
                for object_edge in edges_by_kind["object-materializes-virtual"]:
                    if object_edge.target_id != virtual.record_id:
                        continue
                    owner = nodes.get(object_edge.source_id)
                    if owner is None:
                        continue
                    for allocator_edge in edges_by_kind["maps-to-allocator-node"]:
                        if allocator_edge.source_id != virtual.record_id:
                            continue
                        allocator = nodes.get(allocator_edge.target_id)
                        if allocator is None:
                            continue
                        for frame_edge in edges_by_kind["object-has-stack-home"]:
                            if frame_edge.source_id != owner.record_id:
                                continue
                            stack = nodes.get(frame_edge.target_id)
                            if stack is None:
                                continue
                            path_records = _unique_records(
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
                                )
                            )
                            if not all(exact_owner_path_record(evidence, record) for record in path_records):
                                continue
                            rewrite_support = tuple(
                                node
                                for node in evidence.nodes
                                if node.kind == "backend-support-record"
                                and node.attributes.get("support_kind") == "pcode-rewrite"
                                and node.record_id in virtual_edge.provenance.input_record_ids
                                and node.record_id in allocator_edge.provenance.input_record_ids
                                and node.record_id in allocator.provenance.input_record_ids
                            )
                            if len(rewrite_support) != 1:
                                continue
                            rewrite = rewrite_support[0]
                            try:
                                role = OwnerRoleKey(
                                    str(anchor.attributes.get("machine_operand_key")),
                                    {0: "gpr", 1: "fpr"}[virtual.attributes.get("class_id")],
                                    str(stack.role_key),
                                    owner.attributes.get("type_size"),
                                    str(stack.attributes.get("area")),
                                )
                                state = OwnerSemanticState(
                                    rewrite.attributes.get("allocated_physical"),
                                    stack.attributes.get("offset"),
                                    stack.attributes.get("size"),
                                )
                                role.validate()
                                state.validate()
                            except (KeyError, TypeError, ValueError):
                                continue
                            paths.append(
                                _OwnerPath(
                                    role,
                                    state,
                                    owner,
                                    anchor,
                                    pcode,
                                    lineage,
                                    virtual,
                                    allocator,
                                    stack,
                                    path_records,
                                    _registered_support(path_records, registered),
                                )
                            )
    return tuple(paths)


def _certificate(path: _OwnerPath, evidence: ObjectBindingEvidence) -> EvidenceNode:
    cited_records = (*path.path_records, *path.raw_support)
    proof_payload = {
        "schema_version": "causal-owner-certificate.v1",
        "capture_run_id": evidence.capture_run_id,
        "instrumentation_identity": list(evidence.instrumentation_identity or ()),
        "role": path.role.as_json(),
        "semantic_state": path.semantic_state.as_json(),
        "path_records": [_record_json(record) for record in path.path_records],
        "raw_support_records": [_record_json(record) for record in path.raw_support],
    }
    proof_content_sha256 = hashlib.sha256(canonical_bytes(proof_payload)).hexdigest()
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


def build_owner_certificates(evidence: ObjectBindingEvidence) -> OwnerCertificateResult:
    """Derive all connected capture-local roles from trusted adapter evidence."""

    if evidence._adapter_token is not _OBJECT_BINDING_ADAPTER_TOKEN:
        return OwnerCertificateResult(
            (),
            (),
            (_rejection("untrusted-diagnostic-materialization"),),
            _TRUST_TOKEN,
        )
    if evidence.instrumentation_identity is None:
        return OwnerCertificateResult(
            (),
            (),
            (_rejection("missing-instrumentation-identity"),),
            _TRUST_TOKEN,
        )

    by_role: dict[OwnerRoleKey, list[_OwnerPath]] = {}
    for path in _enumerate_paths(evidence):
        by_role.setdefault(path.role, []).append(path)

    certificates: list[EvidenceNode] = []
    resolutions: list[OwnerRoleResolution] = []
    for role in sorted(by_role):
        paths = by_role[role]
        role_certificates = tuple(_certificate(path, evidence) for path in paths)
        certificates.extend(role_certificates)
        status = (
            OwnerResolutionStatus.UNIQUE
            if len(role_certificates) == 1
            else (
                OwnerResolutionStatus.CONTRADICTORY
                if len({path.semantic_state for path in paths}) > 1
                else OwnerResolutionStatus.AMBIGUOUS
            )
        )
        resolutions.append(
            OwnerRoleResolution(
                role,
                status,
                tuple(certificate.record_id for certificate in role_certificates),
                (),
            )
        )
    return OwnerCertificateResult(
        tuple(certificates),
        tuple(resolutions),
        (),
        _TRUST_TOKEN,
    )
