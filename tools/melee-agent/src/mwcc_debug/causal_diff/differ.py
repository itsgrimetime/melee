"""Emit comparison-scoped graph deltas without creating cross-compile edges."""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping

from .canonical import canonical_bytes
from .graph import FrontierGraph
from .models import ComparisonRecord, Confidence, EvidenceEdge, EvidenceNode, Provenance

_PARSER_VERSION = "causal-frontier-differ.v1"
_OWNER_ALIGNMENT_PARSER = "causal-backend-owner-alignment.v1"
_OWNER_SEMANTIC_STATE_KEYS = frozenset(
    {
        "role_tuple",
        "assigned_physical_register",
        "stack_offset",
        "stack_size",
    }
)
_MATERIAL_NODE_KINDS = frozenset(
    {
        "allocator-node",
        "allocator-decision",
        "compiler-object",
        "statement",
        "enode",
        "objobject",
        "stack-object",
        "source-expression",
        "inline-scope",
    }
)


def _label(graph: FrontierGraph) -> str:
    return str(graph.bundle.label)


def _compile_id(graph: FrontierGraph) -> str:
    return str(graph.bundle.compile_id)


def _nodes(graph: FrontierGraph) -> tuple[EvidenceNode, ...]:
    compile_id = _compile_id(graph)
    records: list[EvidenceNode] = []
    for kind in sorted(_MATERIAL_NODE_KINDS):
        records.extend(graph.store.find_nodes(compile_id, kind))
    return tuple(records)


def _edges(graph: FrontierGraph) -> tuple[EvidenceEdge, ...]:
    return graph.store.find_edges(_compile_id(graph))


def _canonical_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical_value(item) for item in value), key=canonical_bytes)
    return value


def _same_attributes(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    return canonical_bytes(_canonical_value(left)) == canonical_bytes(_canonical_value(right))


def _verified_owner_semantic_state(value: object) -> bool:
    return isinstance(value, Mapping) and frozenset(value) == _OWNER_SEMANTIC_STATE_KEYS


def _unique_role_pairs(
    left_nodes: tuple[EvidenceNode, ...], right_nodes: tuple[EvidenceNode, ...]
) -> tuple[tuple[EvidenceNode, EvidenceNode], ...]:
    left_by_key: dict[tuple[str, str, str], list[EvidenceNode]] = {}
    right_by_key: dict[tuple[str, str, str], list[EvidenceNode]] = {}
    for node in left_nodes:
        if node.role_key:
            left_by_key.setdefault((node.kind, node.role_key, str(node.attributes.get("side") or "")), []).append(node)
    for node in right_nodes:
        if node.role_key:
            right_by_key.setdefault((node.kind, node.role_key, str(node.attributes.get("side") or "")), []).append(node)
    return tuple(
        (left_by_key[key][0], right_by_key[key][0])
        for key in sorted(left_by_key.keys() & right_by_key.keys())
        if len(left_by_key[key]) == len(right_by_key[key]) == 1
    )


def _delta(
    *,
    analysis_id: str,
    relation_kind: str,
    left_compile_id: str,
    left: EvidenceNode | EvidenceEdge | None,
    right_compile_id: str,
    right: EvidenceNode | EvidenceEdge | None,
    attributes: Mapping[str, object],
    ordinal: int,
) -> ComparisonRecord:
    inputs = tuple(record for record in (left, right) if record is not None)
    return ComparisonRecord.create(
        analysis_id=analysis_id,
        relation_kind=relation_kind,
        left_compile_id=left_compile_id,
        left_record_id=None if left is None else left.record_id,
        right_compile_id=right_compile_id,
        right_record_id=None if right is None else right.record_id,
        producer_confidence=Confidence.DERIVED_UNIQUE,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        provenance=Provenance(
            artifact_sha256=analysis_id,
            parser=_PARSER_VERSION,
            raw_start=None,
            raw_end=None,
            derivation_rule=f"role-aligned-{relation_kind}",
            input_record_ids=tuple(record.record_id for record in inputs),
        ),
        input_confidences=tuple(record.confidence for record in inputs),
        occurrence_ordinal=ordinal,
        attributes=attributes,
    )


def _analysis_id(comparisons: tuple[ComparisonRecord, ...]) -> str | None:
    analysis_ids = {record.analysis_id for record in comparisons}
    if len(analysis_ids) > 1:
        raise ValueError("graph differencing received comparisons from multiple analyses")
    return next(iter(analysis_ids), None)


def diff_frontiers(
    graphs: Iterable[FrontierGraph], comparisons: Iterable[ComparisonRecord]
) -> tuple[ComparisonRecord, ...]:
    """Compare role-aligned material records and return deterministic delta facts."""

    graph_pair = tuple(graphs)
    if len(graph_pair) != 2:
        raise ValueError("graph differencing requires exactly two frontiers")
    left_graph, right_graph = sorted(graph_pair, key=_label)
    comparison_records = tuple(comparisons)
    analysis_id = _analysis_id(comparison_records)
    if analysis_id is None:
        return ()

    left_nodes, right_nodes = _nodes(left_graph), _nodes(right_graph)
    left_by_id = {node.record_id: node for node in left_nodes}
    right_by_id = {node.record_id: node for node in right_nodes}
    aligned: dict[str, str] = {}
    owner_semantic_states: dict[tuple[str, str], tuple[object, object]] = {}
    all_owner_comparisons = tuple(
        comparison for comparison in comparison_records if comparison.relation_kind == "backend-owner-corresponds-to"
    )
    owner_comparisons = tuple(
        comparison
        for comparison in all_owner_comparisons
        if comparison.confidence in {Confidence.OBSERVED, Confidence.DERIVED_UNIQUE}
        and comparison.provenance.parser == _OWNER_ALIGNMENT_PARSER
        and comparison.attributes.get("alternative_count") == 1
        and comparison.attributes.get("proof_complete") is True
        and comparison.attributes.get("left_path_proof_complete") is True
        and comparison.attributes.get("right_path_proof_complete") is True
        and _verified_owner_semantic_state(comparison.attributes.get("left_semantic_state"))
        and _verified_owner_semantic_state(comparison.attributes.get("right_semantic_state"))
    )
    left_owner_counts = Counter(comparison.left_record_id for comparison in all_owner_comparisons)
    right_owner_counts = Counter(comparison.right_record_id for comparison in all_owner_comparisons)
    accepted_owner_ids = {
        comparison.record_id
        for comparison in owner_comparisons
        if left_owner_counts[comparison.left_record_id] == 1 and right_owner_counts[comparison.right_record_id] == 1
    }
    for comparison in comparison_records:
        if comparison.relation_kind not in {
            "role-corresponds-to",
            "backend-owner-corresponds-to",
        }:
            continue
        if (
            comparison.relation_kind == "backend-owner-corresponds-to"
            and comparison.record_id not in accepted_owner_ids
        ):
            continue
        if comparison.left_record_id in left_by_id and comparison.right_record_id in right_by_id:
            aligned[comparison.left_record_id] = comparison.right_record_id
            if comparison.relation_kind == "backend-owner-corresponds-to":
                owner_semantic_states[(comparison.left_record_id, comparison.right_record_id)] = (
                    comparison.attributes.get("left_semantic_state"),
                    comparison.attributes.get("right_semantic_state"),
                )
    for left, right in _unique_role_pairs(left_nodes, right_nodes):
        aligned.setdefault(left.record_id, right.record_id)

    deltas: list[ComparisonRecord] = []
    ordinal = 0
    aligned_right = set(aligned.values())
    unaligned_left_owners = {
        node.record_id for node in left_nodes if node.kind == "compiler-object" and node.record_id not in aligned
    }
    unaligned_right_owners = {
        node.record_id for node in right_nodes if node.kind == "compiler-object" and node.record_id not in aligned_right
    }
    for left_id, right_id in sorted(aligned.items()):
        left, right = left_by_id[left_id], right_by_id[right_id]
        owner_states = owner_semantic_states.get((left_id, right_id))
        compared_left = left.attributes if owner_states is None else owner_states[0]
        compared_right = right.attributes if owner_states is None else owner_states[1]
        if left.kind == right.kind and _same_attributes(compared_left, compared_right):
            continue
        deltas.append(
            _delta(
                analysis_id=analysis_id,
                relation_kind="node-changed",
                left_compile_id=_compile_id(left_graph),
                left=left,
                right_compile_id=_compile_id(right_graph),
                right=right,
                attributes={
                    "kind": left.kind,
                    "role_key": left.role_key or right.role_key,
                    "left_attributes": compared_left,
                    "right_attributes": compared_right,
                },
                ordinal=ordinal,
            )
        )
        ordinal += 1
    for left in sorted(
        (node for node in left_nodes if node.record_id not in aligned and node.record_id not in unaligned_left_owners),
        key=lambda node: node.record_id,
    ):
        deltas.append(
            _delta(
                analysis_id=analysis_id,
                relation_kind="node-removed",
                left_compile_id=_compile_id(left_graph),
                left=left,
                right_compile_id=_compile_id(right_graph),
                right=None,
                attributes={"kind": left.kind, "role_key": left.role_key, "attributes": left.attributes},
                ordinal=ordinal,
            )
        )
        ordinal += 1
    for right in sorted(
        (
            node
            for node in right_nodes
            if node.record_id not in aligned_right and node.record_id not in unaligned_right_owners
        ),
        key=lambda node: node.record_id,
    ):
        deltas.append(
            _delta(
                analysis_id=analysis_id,
                relation_kind="node-added",
                left_compile_id=_compile_id(left_graph),
                left=None,
                right_compile_id=_compile_id(right_graph),
                right=right,
                attributes={"kind": right.kind, "role_key": right.role_key, "attributes": right.attributes},
                ordinal=ordinal,
            )
        )
        ordinal += 1

    left_edges = _edges(left_graph)
    right_edges = _edges(right_graph)
    material_left_ids = set(left_by_id)
    material_right_ids = set(right_by_id)
    unaligned_left_material = material_left_ids - set(aligned)
    unaligned_right_material = material_right_ids - aligned_right
    right_edge_index: dict[tuple[str, str, str], list[EvidenceEdge]] = {}
    for edge in right_edges:
        right_edge_index.setdefault((edge.kind, edge.source_id, edge.target_id), []).append(edge)
    matched_right_edges: set[str] = set()
    for left in left_edges:
        if {left.source_id, left.target_id} & unaligned_left_owners:
            continue
        mapped_source = aligned.get(left.source_id)
        mapped_target = aligned.get(left.target_id)
        if mapped_source is None or mapped_target is None:
            missing_endpoints = tuple(
                endpoint for endpoint in (left.source_id, left.target_id) if endpoint in unaligned_left_material
            )
            if missing_endpoints:
                deltas.append(
                    _delta(
                        analysis_id=analysis_id,
                        relation_kind="edge-removed",
                        left_compile_id=_compile_id(left_graph),
                        left=left,
                        right_compile_id=_compile_id(right_graph),
                        right=None,
                        attributes={
                            "kind": left.kind,
                            "source_record_id": left.source_id,
                            "target_record_id": left.target_id,
                            "counterpart_missing_endpoints": missing_endpoints,
                        },
                        ordinal=ordinal,
                    )
                )
                ordinal += 1
            continue
        candidates = right_edge_index.get((left.kind, mapped_source, mapped_target), [])
        if len(candidates) != 1:
            deltas.append(
                _delta(
                    analysis_id=analysis_id,
                    relation_kind="edge-removed",
                    left_compile_id=_compile_id(left_graph),
                    left=left,
                    right_compile_id=_compile_id(right_graph),
                    right=None,
                    attributes={"kind": left.kind},
                    ordinal=ordinal,
                )
            )
            ordinal += 1
            continue
        right = candidates[0]
        matched_right_edges.add(right.record_id)
        if not _same_attributes(left.attributes, right.attributes):
            deltas.append(
                _delta(
                    analysis_id=analysis_id,
                    relation_kind="edge-changed",
                    left_compile_id=_compile_id(left_graph),
                    left=left,
                    right_compile_id=_compile_id(right_graph),
                    right=right,
                    attributes={
                        "kind": left.kind,
                        "left_attributes": left.attributes,
                        "right_attributes": right.attributes,
                    },
                    ordinal=ordinal,
                )
            )
            ordinal += 1
    for right in right_edges:
        if right.record_id in matched_right_edges:
            continue
        if {right.source_id, right.target_id} & unaligned_right_owners:
            continue
        missing_endpoints = tuple(
            endpoint for endpoint in (right.source_id, right.target_id) if endpoint in unaligned_right_material
        )
        aligned_material_edge = (
            right.source_id in material_right_ids
            and right.target_id in material_right_ids
            and right.source_id in aligned_right
            and right.target_id in aligned_right
        )
        if not missing_endpoints and not aligned_material_edge:
            continue
        deltas.append(
            _delta(
                analysis_id=analysis_id,
                relation_kind="edge-added",
                left_compile_id=_compile_id(left_graph),
                left=None,
                right_compile_id=_compile_id(right_graph),
                right=right,
                attributes={
                    "kind": right.kind,
                    "source_record_id": right.source_id,
                    "target_record_id": right.target_id,
                    "counterpart_missing_endpoints": missing_endpoints,
                },
                ordinal=ordinal,
            )
        )
        ordinal += 1

    return tuple(
        sorted(
            deltas,
            key=lambda record: (
                record.relation_kind,
                record.left_record_id or "",
                record.right_record_id or "",
                record.record_id,
            ),
        )
    )


__all__ = ["diff_frontiers"]
