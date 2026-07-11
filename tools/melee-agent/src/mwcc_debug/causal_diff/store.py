"""Storage-neutral causal evidence protocols and an in-memory implementation."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Iterable, Literal, Mapping, Protocol, TypeVar

from .canonical import canonical_bytes
from .models import (
    AdapterResult,
    ComparisonRecord,
    EvidenceEdge,
    EvidenceNode,
    min_confidence,
)


class EvidenceSink(Protocol):
    def add_nodes(self, records: Iterable[EvidenceNode]) -> None:
        raise NotImplementedError

    def add_edges(self, records: Iterable[EvidenceEdge]) -> None:
        raise NotImplementedError

    def add_comparisons(self, records: Iterable[ComparisonRecord]) -> None:
        raise NotImplementedError


class EvidenceQuery(Protocol):
    def get_node(self, record_id: str) -> EvidenceNode | None:
        raise NotImplementedError

    def get_edge(self, record_id: str) -> EvidenceEdge | None:
        raise NotImplementedError

    def neighbors(
        self,
        record_id: str,
        edge_kinds: frozenset[str] | None = None,
        direction: Literal["in", "out", "both"] = "both",
    ) -> tuple[EvidenceEdge, ...]:
        raise NotImplementedError

    def find_nodes(
        self,
        compile_id: str,
        node_kind: str | None = None,
        role_key: str | None = None,
    ) -> tuple[EvidenceNode, ...]:
        raise NotImplementedError

    def find_edges(
        self,
        compile_id: str,
        edge_kind: str | None = None,
        endpoint: str | None = None,
    ) -> tuple[EvidenceEdge, ...]:
        raise NotImplementedError

    def find_comparisons(
        self,
        analysis_id: str,
        relation_kind: str | None = None,
        endpoint: str | None = None,
    ) -> tuple[ComparisonRecord, ...]:
        raise NotImplementedError

    def subgraph(
        self,
        roots: Iterable[str],
        edge_kinds: frozenset[str],
        max_depth: int,
    ) -> AdapterResult:
        raise NotImplementedError


class EvidenceStore(EvidenceSink, EvidenceQuery, Protocol):
    """Storage-neutral interface used by orchestration and inference."""


_Record = TypeVar("_Record", EvidenceNode, EvidenceEdge, ComparisonRecord)


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=canonical_bytes)
    return value


def _record_bytes(record: object) -> bytes:
    return canonical_bytes(_json_value(record))


def _node_sort_key(record: EvidenceNode) -> tuple[str, str, str]:
    return (record.kind, record.role_key or "", record.record_id)


def _edge_sort_key(record: EvidenceEdge) -> tuple[str, str, str, str]:
    return (record.kind, record.source_id, record.target_id, record.record_id)


def _comparison_sort_key(record: ComparisonRecord) -> tuple[str, str, str, str, str, str]:
    return (
        record.relation_kind,
        record.left_compile_id,
        record.left_record_id or "",
        record.right_compile_id,
        record.right_record_id or "",
        record.record_id,
    )


class InMemoryEvidenceStore:
    """Deterministic, idempotent in-memory evidence storage."""

    def __init__(self) -> None:
        self._nodes: dict[str, EvidenceNode] = {}
        self._edges: dict[str, EvidenceEdge] = {}
        self._comparisons: dict[str, ComparisonRecord] = {}

    def _record_for_id(self, record_id: str) -> EvidenceNode | EvidenceEdge | ComparisonRecord | None:
        return (
            self._nodes.get(record_id)
            or self._edges.get(record_id)
            or self._comparisons.get(record_id)
        )

    def _validated_batch(self, records: Iterable[_Record]) -> dict[str, _Record]:
        pending: dict[str, _Record] = {}
        pending_content: dict[str, bytes] = {}
        for record in records:
            content = _record_bytes(record)
            prior = self._record_for_id(record.record_id)
            if prior is not None:
                if _record_bytes(prior) != content:
                    raise ValueError(f"record ID collision: {record.record_id}")
                continue
            if record.record_id in pending:
                if pending_content[record.record_id] != content:
                    raise ValueError(f"record ID collision: {record.record_id}")
                continue
            pending[record.record_id] = record
            pending_content[record.record_id] = content
        return pending

    def _validate_confidences(self, pending: Mapping[str, _Record]) -> None:
        for record in pending.values():
            input_confidences: list = []
            for input_record_id in record.provenance.input_record_ids:
                if input_record_id == record.record_id:
                    raise ValueError(f"record cannot cite itself as provenance input: {record.record_id}")
                input_record = pending.get(input_record_id) or self._record_for_id(input_record_id)
                if input_record is None:
                    raise ValueError(f"provenance input record not found: {input_record_id}")
                input_confidences.append(input_record.confidence)

            if isinstance(record, (EvidenceNode, EvidenceEdge)):
                expected = min_confidence(
                    record.producer_confidence,
                    record.adapter_confidence,
                    input_confidences=input_confidences,
                )
            else:
                expected = min_confidence(
                    record.confidence,
                    input_confidences=input_confidences,
                )
            if record.confidence != expected:
                raise ValueError(
                    f"record confidence does not match producer, adapter, and provenance inputs: {record.record_id}"
                )

    def add_nodes(self, records: Iterable[EvidenceNode]) -> None:
        pending = self._validated_batch(records)
        self._validate_confidences(pending)
        self._nodes.update(pending)

    def add_edges(self, records: Iterable[EvidenceEdge]) -> None:
        pending = self._validated_batch(records)
        self._validate_confidences(pending)
        for edge in pending.values():
            source = self._nodes.get(edge.source_id)
            target = self._nodes.get(edge.target_id)
            if source is None or target is None:
                raise ValueError(f"edge endpoint not found: {edge.record_id}")
            if source.compile_id != edge.compile_id or target.compile_id != edge.compile_id:
                raise ValueError(f"cross-compile edge: {edge.record_id}")
        self._edges.update(pending)

    def add_comparisons(self, records: Iterable[ComparisonRecord]) -> None:
        pending = self._validated_batch(records)
        self._validate_confidences(pending)
        for comparison in pending.values():
            self._validate_comparison_endpoint(
                comparison.left_record_id,
                comparison.left_compile_id,
                comparison.record_id,
            )
            self._validate_comparison_endpoint(
                comparison.right_record_id,
                comparison.right_compile_id,
                comparison.record_id,
            )
        self._comparisons.update(pending)

    def _validate_comparison_endpoint(
        self, endpoint_id: str | None, compile_id: str, comparison_id: str
    ) -> None:
        if endpoint_id is None:
            return
        endpoint = self._nodes.get(endpoint_id) or self._edges.get(endpoint_id)
        if endpoint is None:
            raise ValueError(f"comparison endpoint not found: {comparison_id}")
        if endpoint.compile_id != compile_id:
            raise ValueError(f"cross-compile comparison endpoint: {comparison_id}")

    def get_node(self, record_id: str) -> EvidenceNode | None:
        return self._nodes.get(record_id)

    def get_edge(self, record_id: str) -> EvidenceEdge | None:
        return self._edges.get(record_id)

    def neighbors(
        self,
        record_id: str,
        edge_kinds: frozenset[str] | None = None,
        direction: Literal["in", "out", "both"] = "both",
    ) -> tuple[EvidenceEdge, ...]:
        if direction not in {"in", "out", "both"}:
            raise ValueError(f"invalid edge direction: {direction}")

        def selected(edge: EvidenceEdge) -> bool:
            if edge_kinds is not None and edge.kind not in edge_kinds:
                return False
            return (
                direction in {"out", "both"}
                and edge.source_id == record_id
                or direction in {"in", "both"}
                and edge.target_id == record_id
            )

        return tuple(sorted((edge for edge in self._edges.values() if selected(edge)), key=_edge_sort_key))

    def find_nodes(
        self,
        compile_id: str,
        node_kind: str | None = None,
        role_key: str | None = None,
    ) -> tuple[EvidenceNode, ...]:
        records = (
            node
            for node in self._nodes.values()
            if node.compile_id == compile_id
            and (node_kind is None or node.kind == node_kind)
            and (role_key is None or node.role_key == role_key)
        )
        return tuple(sorted(records, key=_node_sort_key))

    def find_edges(
        self,
        compile_id: str,
        edge_kind: str | None = None,
        endpoint: str | None = None,
    ) -> tuple[EvidenceEdge, ...]:
        records = (
            edge
            for edge in self._edges.values()
            if edge.compile_id == compile_id
            and (edge_kind is None or edge.kind == edge_kind)
            and (endpoint is None or endpoint in {edge.source_id, edge.target_id})
        )
        return tuple(sorted(records, key=_edge_sort_key))

    def find_comparisons(
        self,
        analysis_id: str,
        relation_kind: str | None = None,
        endpoint: str | None = None,
    ) -> tuple[ComparisonRecord, ...]:
        records = (
            comparison
            for comparison in self._comparisons.values()
            if comparison.analysis_id == analysis_id
            and (relation_kind is None or comparison.relation_kind == relation_kind)
            and (
                endpoint is None
                or endpoint in {comparison.left_record_id, comparison.right_record_id}
            )
        )
        return tuple(sorted(records, key=_comparison_sort_key))

    def subgraph(
        self,
        roots: Iterable[str],
        edge_kinds: frozenset[str],
        max_depth: int,
    ) -> AdapterResult:
        if max_depth < 0:
            raise ValueError("max_depth must be non-negative")

        included_nodes = {record_id for record_id in roots if record_id in self._nodes}
        included_edges: set[str] = set()
        frontier = sorted(included_nodes, key=lambda record_id: _node_sort_key(self._nodes[record_id]))
        visited = set(included_nodes)

        for _depth in range(max_depth):
            next_frontier: list[str] = []
            for record_id in frontier:
                for edge in self.neighbors(record_id, edge_kinds=edge_kinds):
                    included_edges.add(edge.record_id)
                    other_id = edge.target_id if edge.source_id == record_id else edge.source_id
                    included_nodes.add(other_id)
                    if other_id not in visited:
                        visited.add(other_id)
                        next_frontier.append(other_id)
            frontier = sorted(
                set(next_frontier),
                key=lambda record_id: _node_sort_key(self._nodes[record_id]),
            )
            if not frontier:
                break

        return AdapterResult(
            nodes=tuple(sorted((self._nodes[record_id] for record_id in included_nodes), key=_node_sort_key)),
            edges=tuple(sorted((self._edges[record_id] for record_id in included_edges), key=_edge_sort_key)),
        )
