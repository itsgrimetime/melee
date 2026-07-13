"""Emit comparison-scoped graph deltas without creating cross-compile edges."""

from __future__ import annotations

from typing import Iterable, Mapping

from .canonical import canonical_bytes
from .graph import FrontierGraph
from .models import ComparisonRecord, Confidence, EvidenceEdge, EvidenceNode, Provenance
from .owner_certificate import (
    OwnerResolutionStatus,
    OwnerRoleKey,
    OwnerSemanticState,
)
from .store import canonical_record_bytes

_PARSER_VERSION = "causal-frontier-differ.v1"
_OWNER_ALIGNMENT_PARSER = "causal-backend-owner-alignment.v2"
_MATERIAL_NODE_KINDS = frozenset(
    {
        "allocator-node",
        "allocator-decision",
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


def _owner_role(value: object) -> OwnerRoleKey | None:
    if not isinstance(value, Mapping):
        return None
    try:
        role = OwnerRoleKey(
            operand_key=value["operand_key"],
            register_class=value["register_class"],
            semantic_stack_role=value["semantic_stack_role"],
            type_size=value["type_size"],
            frame_area=value["frame_area"],
        )
        role.validate()
    except (KeyError, TypeError, ValueError):
        return None
    return role if _same_attributes(value, role.as_json()) else None


def _owner_semantic_state(value: object) -> OwnerSemanticState | None:
    if not isinstance(value, Mapping):
        return None
    try:
        state = OwnerSemanticState(
            assigned_physical_register=value["assigned_physical_register"],
            stack_offset=value["stack_offset"],
            stack_size=value["stack_size"],
        )
        state.validate()
    except (KeyError, TypeError, ValueError):
        return None
    return state if _same_attributes(value, state.as_json()) else None


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
    supporting_records: tuple[EvidenceNode | EvidenceEdge | ComparisonRecord, ...] = (),
    confidence: Confidence = Confidence.DERIVED_UNIQUE,
) -> ComparisonRecord:
    inputs_by_id = {record.record_id: record for record in (*supporting_records, left, right) if record is not None}
    inputs = tuple(inputs_by_id[record_id] for record_id in sorted(inputs_by_id))
    return ComparisonRecord.create(
        analysis_id=analysis_id,
        relation_kind=relation_kind,
        left_compile_id=left_compile_id,
        left_record_id=None if left is None else left.record_id,
        right_compile_id=right_compile_id,
        right_record_id=None if right is None else right.record_id,
        producer_confidence=confidence,
        adapter_confidence=confidence,
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


def _trusted_stored_certificate(
    graph: FrontierGraph,
    record_id: str,
) -> EvidenceNode | None:
    trusted = graph.backend.owner_certificates.certificate(record_id)
    stored = graph.store.get_node(record_id)
    if (
        trusted is None
        or stored is None
        or trusted.kind != "owner-proof-certificate"
        or trusted.provenance.parser != "causal-owner-certificate.v1"
        or canonical_record_bytes(trusted) != canonical_record_bytes(stored)
    ):
        return None
    return trusted


def _authorized_unique_certificate(
    graph: FrontierGraph,
    role: OwnerRoleKey,
    record_id: str,
) -> EvidenceNode | None:
    result = graph.backend.owner_certificates
    resolution = result.resolution_for(role)
    if (
        result.global_rejections
        or resolution.rejections
        or resolution.status is not OwnerResolutionStatus.UNIQUE
        or resolution.certificate_record_ids != (record_id,)
    ):
        return None
    return _trusted_stored_certificate(graph, record_id)


def _owner_state_deltas(
    *,
    analysis_id: str,
    left_graph: FrontierGraph,
    right_graph: FrontierGraph,
    comparisons: tuple[ComparisonRecord, ...],
) -> tuple[ComparisonRecord, ...]:
    candidates_by_role: dict[
        OwnerRoleKey,
        dict[
            bytes,
            tuple[
                ComparisonRecord,
                EvidenceNode,
                EvidenceNode,
                OwnerSemanticState,
                OwnerSemanticState,
            ],
        ],
    ] = {}
    for comparison in comparisons:
        if (
            comparison.relation_kind != "backend-owner-corresponds-to"
            or comparison.provenance.parser != _OWNER_ALIGNMENT_PARSER
            or comparison.left_record_id is None
            or comparison.right_record_id is None
            or frozenset(comparison.attributes) != {"role"}
        ):
            continue
        comparison_role = _owner_role(comparison.attributes.get("role"))
        if comparison_role is None:
            continue
        left = _authorized_unique_certificate(
            left_graph,
            comparison_role,
            comparison.left_record_id,
        )
        right = _authorized_unique_certificate(
            right_graph,
            comparison_role,
            comparison.right_record_id,
        )
        if (
            left is None
            or right is None
            or left.compile_id != comparison.left_compile_id
            or right.compile_id != comparison.right_compile_id
            or not {left.record_id, right.record_id} <= set(comparison.provenance.input_record_ids)
        ):
            continue
        left_role = _owner_role(left.attributes.get("role"))
        right_role = _owner_role(right.attributes.get("role"))
        left_state = _owner_semantic_state(left.attributes.get("semantic_state"))
        right_state = _owner_semantic_state(right.attributes.get("semantic_state"))
        if (
            left_role is None
            or right_role is None
            or comparison_role is None
            or left_role != right_role
            or left_role != comparison_role
            or left_state is None
            or right_state is None
        ):
            continue
        candidates_by_role.setdefault(left_role, {}).setdefault(
            canonical_record_bytes(comparison),
            (comparison, left, right, left_state, right_state),
        )

    records: list[ComparisonRecord] = []
    for role in sorted(candidates_by_role):
        candidates = candidates_by_role[role]
        if len(candidates) != 1:
            continue
        comparison, left, right, left_state, right_state = next(iter(candidates.values()))
        if left_state == right_state:
            continue
        records.append(
            _delta(
                analysis_id=analysis_id,
                relation_kind="backend-owner-state-changed",
                left_compile_id=_compile_id(left_graph),
                left=left,
                right_compile_id=_compile_id(right_graph),
                right=right,
                attributes={
                    "role": role.as_json(),
                    "left_semantic_state": left_state.as_json(),
                    "right_semantic_state": right_state.as_json(),
                },
                ordinal=len(records),
                supporting_records=(comparison,),
                confidence=comparison.confidence,
            )
        )
    return tuple(records)


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
    for comparison in comparison_records:
        if comparison.relation_kind != "role-corresponds-to":
            continue
        if comparison.left_record_id in left_by_id and comparison.right_record_id in right_by_id:
            aligned[comparison.left_record_id] = comparison.right_record_id
    for left, right in _unique_role_pairs(left_nodes, right_nodes):
        aligned.setdefault(left.record_id, right.record_id)

    deltas = list(
        _owner_state_deltas(
            analysis_id=analysis_id,
            left_graph=left_graph,
            right_graph=right_graph,
            comparisons=comparison_records,
        )
    )
    ordinal = len(deltas)
    aligned_right = set(aligned.values())
    for left_id, right_id in sorted(aligned.items()):
        left, right = left_by_id[left_id], right_by_id[right_id]
        if left.kind == right.kind and _same_attributes(left.attributes, right.attributes):
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
                    "left_attributes": left.attributes,
                    "right_attributes": right.attributes,
                },
                ordinal=ordinal,
            )
        )
        ordinal += 1
    for left in sorted(
        (node for node in left_nodes if node.record_id not in aligned),
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
        (node for node in right_nodes if node.record_id not in aligned_right),
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
