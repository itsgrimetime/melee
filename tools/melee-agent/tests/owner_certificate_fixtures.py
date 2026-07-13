from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from enum import Enum
from typing import Iterable, Mapping, TypeVar

from src.mwcc_debug.causal_diff.canonical import canonical_bytes
from src.mwcc_debug.causal_diff.models import EvidenceEdge, EvidenceNode
from src.mwcc_debug.causal_diff.object_binding_adapter import (
    ObjectBindingEvidence,
    emit_object_binding_evidence,
)
from tests.test_causal_diff_object_bindings import _adapter_input

_T = TypeVar("_T")


def only(items: Iterable[_T]) -> _T:
    values = tuple(items)
    if len(values) != 1:
        raise AssertionError(f"expected exactly one item, found {len(values)}")
    return values[0]


def complete_evidence(**adapter_overrides: object) -> ObjectBindingEvidence:
    return emit_object_binding_evidence(_adapter_input(**adapter_overrides))


def support(evidence: ObjectBindingEvidence, support_kind: str) -> EvidenceNode:
    return only(
        node
        for node in evidence.nodes
        if node.kind == "backend-support-record"
        and node.attributes.get("support_kind") == support_kind
    )


def replace_record(
    evidence: ObjectBindingEvidence,
    record: EvidenceNode | EvidenceEdge,
) -> ObjectBindingEvidence:
    if isinstance(record, EvidenceNode):
        matches = tuple(node.record_id == record.record_id for node in evidence.nodes)
        if sum(matches) != 1:
            raise AssertionError(f"expected one node with record ID {record.record_id}")
        return replace(
            evidence,
            nodes=tuple(record if matches[index] else node for index, node in enumerate(evidence.nodes)),
        )
    matches = tuple(edge.record_id == record.record_id for edge in evidence.edges)
    if sum(matches) != 1:
        raise AssertionError(f"expected one edge with record ID {record.record_id}")
    return replace(
        evidence,
        edges=tuple(record if matches[index] else edge for index, edge in enumerate(evidence.edges)),
    )


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
            if not field.name.startswith("_")
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=repr)
    return value


def canonical_result(result: object) -> bytes:
    return canonical_bytes(_json_value(result))
