"""Isolated traversal helpers for legacy v1/pcdump ownership evidence."""

from __future__ import annotations

from typing import Iterable

from .graph import FrontierGraph
from .models import EvidenceEdge, EvidenceNode
from .store import EvidenceQuery

_V2_PARSER = "mwcc-retro-backend-trace.v2"


def _legacy_record(record: EvidenceNode | EvidenceEdge | None) -> bool:
    return record is not None and record.provenance.parser != _V2_PARSER and "capture_run_id" not in record.attributes


def _legacy_edge(graph: FrontierGraph, edge: EvidenceEdge) -> bool:
    return (
        _legacy_record(edge)
        and _legacy_record(graph.store.get_node(edge.source_id))
        and _legacy_record(graph.store.get_node(edge.target_id))
    )


def legacy_allocator_from_virtual(
    graph: FrontierGraph,
    virtual_id: str,
) -> tuple[tuple[EvidenceEdge, EvidenceNode], ...]:
    """Resolve allocator mappings without admitting any v2 capture record."""

    virtual = graph.store.get_node(virtual_id)
    if not _legacy_record(virtual):
        return ()
    mappings = tuple(
        edge
        for edge in graph.store.find_edges(
            str(graph.bundle.compile_id),
            "maps-to-allocator-node",
            endpoint=virtual_id,
        )
        if edge.source_id == virtual_id and _legacy_edge(graph, edge)
    )
    return tuple(
        (edge, node)
        for edge in sorted(mappings, key=lambda item: (item.target_id, item.record_id))
        if (node := graph.store.get_node(edge.target_id)) is not None
        and node.kind == "allocator-node"
        and _legacy_record(node)
    )


def legacy_pcode_occurrences(graph: FrontierGraph) -> tuple[EvidenceNode, ...]:
    """Return only pcdump-era occurrences eligible for legacy role fallback."""

    return tuple(
        node
        for node in graph.store.find_nodes(
            str(graph.bundle.compile_id),
            "pcode-occurrence",
        )
        if _legacy_record(node)
    )


def legacy_allocator_chains_from_occurrence(
    graph: FrontierGraph,
    occurrence_id: str,
    edge_kind: str,
    operand_position: int,
) -> tuple[tuple[EvidenceEdge, EvidenceNode, EvidenceEdge, EvidenceNode], ...]:
    """Resolve a complete occurrence/use-def/virtual/map/allocator legacy chain."""

    occurrence = graph.store.get_node(occurrence_id)
    if not _legacy_record(occurrence) or occurrence.kind != "pcode-occurrence":
        return ()
    chains = []
    for edge in graph.store.find_edges(
        str(graph.bundle.compile_id),
        edge_kind,
        endpoint=occurrence_id,
    ):
        if (
            edge.source_id != occurrence_id
            or edge.attributes.get("operand_position") != operand_position
            or not _legacy_edge(graph, edge)
        ):
            continue
        virtual = graph.store.get_node(edge.target_id)
        if virtual is None or virtual.kind != "virtual-register":
            continue
        chains.extend(
            (edge, virtual, map_edge, allocator)
            for map_edge, allocator in legacy_allocator_from_virtual(graph, virtual.record_id)
        )
    return tuple(
        sorted(
            chains,
            key=lambda item: tuple(record.record_id for record in item),
        )
    )


def legacy_reachable_records(
    graph: FrontierGraph,
    roots: Iterable[str],
) -> tuple[frozenset[str], frozenset[str]]:
    """Traverse only records that are categorically outside v2 capture space."""

    visited = {record_id for record_id in roots if _legacy_record(graph.store.get_node(record_id))}
    edge_ids: set[str] = set()
    frontier = sorted(visited)
    while frontier:
        current = frontier.pop(0)
        for edge in graph.store.neighbors(current, direction="both"):
            if not _legacy_edge(graph, edge):
                continue
            edge_ids.add(edge.record_id)
            other = edge.target_id if edge.source_id == current else edge.source_id
            if other not in visited:
                visited.add(other)
                frontier.append(other)
        frontier.sort()
    return frozenset(visited), frozenset(edge_ids)


def legacy_simple_paths(
    query: EvidenceQuery | FrontierGraph,
    source_id: str,
    target_id: str,
    max_depth: int,
) -> tuple[tuple[str, ...], ...]:
    """Enumerate deterministic legacy-only paths as alternating node/edge IDs."""

    if isinstance(query, FrontierGraph):
        query = query.store
    if max_depth < 0:
        raise ValueError("max_depth must be non-negative")
    if not all(_legacy_record(query.get_node(record_id)) for record_id in (source_id, target_id)):
        return ()
    if source_id == target_id:
        return ((source_id,),)

    paths: list[tuple[str, ...]] = []

    def visit(
        node_id: str,
        visited: frozenset[str],
        path: tuple[str, ...],
        depth: int,
    ) -> None:
        if depth >= max_depth:
            return
        neighbors = []
        for edge in query.neighbors(node_id, direction="both"):
            if not (
                _legacy_record(edge)
                and _legacy_record(query.get_node(edge.source_id))
                and _legacy_record(query.get_node(edge.target_id))
            ):
                continue
            other = edge.target_id if edge.source_id == node_id else edge.source_id
            if other in visited:
                continue
            neighbors.append((other, edge))
        for other, edge in sorted(
            neighbors,
            key=lambda item: (item[1].kind, item[0], item[1].record_id),
        ):
            next_path = (*path, edge.record_id, other)
            if other == target_id:
                paths.append(next_path)
            else:
                visit(other, visited | {other}, next_path, depth + 1)

    visit(source_id, frozenset({source_id}), (source_id,), 0)
    return tuple(sorted(set(paths), key=lambda path: (len(path), path)))


__all__ = [
    "legacy_allocator_chains_from_occurrence",
    "legacy_allocator_from_virtual",
    "legacy_pcode_occurrences",
    "legacy_reachable_records",
    "legacy_simple_paths",
]
