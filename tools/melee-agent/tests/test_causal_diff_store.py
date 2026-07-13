from __future__ import annotations

from dataclasses import replace
from typing import Iterable

import pytest

from src.mwcc_debug.causal_diff.graph import add_adapter_results_atomically
from src.mwcc_debug.causal_diff.models import (
    AdapterResult,
    ComparisonRecord,
    Confidence,
    EvidenceEdge,
    EvidenceNode,
    Provenance,
)
from src.mwcc_debug.causal_diff.store import InMemoryEvidenceStore
from tests.owner_certificate_fixtures import (
    STORE_FACTORIES,
    future_complete_backend,
)


class _RecordingEvidenceStore(InMemoryEvidenceStore):
    def __init__(self) -> None:
        super().__init__()
        self.batches: list[tuple[str, tuple[str, ...]]] = []

    def add_nodes(self, records: Iterable[EvidenceNode]) -> None:
        batch = tuple(records)
        self.batches.append(("nodes", tuple(record.record_id for record in batch)))
        super().add_nodes(batch)

    def add_edges(self, records: Iterable[EvidenceEdge]) -> None:
        batch = tuple(records)
        self.batches.append(("edges", tuple(record.record_id for record in batch)))
        super().add_edges(batch)


class _IncompleteDependencyStore(_RecordingEvidenceStore):
    def __init__(self, edge: EvidenceEdge) -> None:
        super().__init__()
        self._external_edge = edge

    def get_edge(self, record_id: str) -> EvidenceEdge | None:
        if record_id == self._external_edge.record_id:
            return self._external_edge
        return super().get_edge(record_id)


def _prov(*, input_record_ids: tuple[str, ...] = ()) -> Provenance:
    return Provenance(
        artifact_sha256="a" * 64,
        parser="unit-test.v1",
        raw_start=10,
        raw_end=20,
        derivation_rule="raw",
        input_record_ids=input_record_ids,
    )


def _node(compile_id: str, local_key: str, role_key: str) -> EvidenceNode:
    return EvidenceNode.create(
        compile_id=compile_id,
        function="fn_test",
        kind="virtual-register",
        local_key=local_key,
        role_key=role_key,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        provenance=_prov(),
        attributes={"virtual": int(local_key)},
    )


def _certificate(
    local_key: str,
    *inputs: EvidenceNode | EvidenceEdge,
    attributes: dict[str, object] | None = None,
) -> EvidenceNode:
    return EvidenceNode.create(
        compile_id="compile-a",
        function="fn_test",
        kind="owner-proof-certificate",
        local_key=local_key,
        role_key="row-counter",
        producer_confidence=Confidence.DERIVED_UNIQUE,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        provenance=_prov(input_record_ids=tuple(record.record_id for record in inputs)),
        input_confidences=tuple(record.confidence for record in inputs),
        attributes={} if attributes is None else attributes,
    )


def _comparison(
    relation_kind: str,
    left_record_id: str | None,
    right_record_id: str | None,
) -> ComparisonRecord:
    return ComparisonRecord(
        record_id=f"comparison-{relation_kind}",
        analysis_id="analysis-a",
        relation_kind=relation_kind,
        left_compile_id="compile-a",
        left_record_id=left_record_id,
        right_compile_id="compile-b",
        right_record_id=right_record_id,
        confidence=Confidence.DERIVED_UNIQUE,
        provenance=_prov(),
        attributes={},
    )


def test_record_ids_are_rfc8785_stable() -> None:
    first = _node("compile-a", "66", "row-counter")
    second = EvidenceNode.create(
        compile_id="compile-a",
        function="fn_test",
        kind="virtual-register",
        local_key="66",
        role_key="row-counter",
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        provenance=_prov(),
        attributes={"virtual": 66},
    )
    assert first.record_id == second.record_id


def test_store_queries_ignore_insertion_order() -> None:
    a = _node("compile-a", "66", "row-counter")
    b = _node("compile-a", "67", "row-count")
    left = InMemoryEvidenceStore()
    right = InMemoryEvidenceStore()
    left.add_nodes((b, a))
    right.add_nodes((a, b))
    assert left.find_nodes("compile-a") == right.find_nodes("compile-a")
    assert left.find_nodes("compile-a") == (b, a)


def test_compile_edges_reject_cross_compile_endpoints() -> None:
    store = InMemoryEvidenceStore()
    a = _node("compile-a", "66", "row-counter")
    b = _node("compile-b", "70", "fighter-id")
    store.add_nodes((a, b))
    edge = EvidenceEdge.create(
        compile_id="compile-a",
        function="fn_test",
        kind="lowers-to",
        source_id=a.record_id,
        target_id=b.record_id,
        occurrence_ordinal=0,
        producer_confidence=Confidence.DERIVED_UNIQUE,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        provenance=_prov(),
        attributes={},
    )
    with pytest.raises(ValueError, match="cross-compile edge"):
        store.add_edges((edge,))


def test_duplicate_id_with_different_content_is_rejected() -> None:
    store = InMemoryEvidenceStore()
    node = _node("compile-a", "66", "row-counter")
    store.add_nodes((node,))
    altered = node.with_attributes({"virtual": 67})
    with pytest.raises(ValueError, match="record ID collision"):
        store.add_nodes((altered,))


@pytest.mark.parametrize("store_factory", STORE_FACTORIES)
def test_changed_content_with_same_certificate_id_is_store_collision(
    store_factory,
    tmp_path,
    monkeypatch,
) -> None:
    backend = future_complete_backend(tmp_path, monkeypatch)
    certificate = backend.owner_certificates.certificate_nodes[0]
    store = store_factory()
    add_adapter_results_atomically(store, (backend.result,))

    with pytest.raises(ValueError, match="record ID collision"):
        store.add_nodes((certificate.with_attributes({**certificate.attributes, "stack_offset": 0x48}),))


def test_atomic_certificate_ingestion_orders_diagnostics_edges_then_certificate(
    tmp_path,
    monkeypatch,
) -> None:
    backend = future_complete_backend(tmp_path, monkeypatch)
    certificate_ids = {certificate.record_id for certificate in backend.owner_certificates.certificate_nodes}
    store = _RecordingEvidenceStore()

    add_adapter_results_atomically(store, (backend.result,))

    assert [kind for kind, _ids in store.batches] == ["nodes", "edges", "nodes"]
    assert certificate_ids.isdisjoint(store.batches[0][1])
    assert certificate_ids == set(store.batches[2][1])


def test_atomic_certificate_ingestion_leaves_destination_unchanged_on_missing_provenance(
    tmp_path,
    monkeypatch,
) -> None:
    backend = future_complete_backend(tmp_path, monkeypatch)
    certificate = backend.owner_certificates.certificate_nodes[0]
    malformed = replace(
        certificate,
        provenance=replace(
            certificate.provenance,
            input_record_ids=(
                "missing-provenance-record",
                *certificate.provenance.input_record_ids[1:],
            ),
        ),
    )
    result = replace(
        backend.result,
        nodes=tuple(malformed if node.record_id == certificate.record_id else node for node in backend.result.nodes),
    )
    store = _RecordingEvidenceStore()

    with pytest.raises(ValueError, match="provenance input record not found"):
        add_adapter_results_atomically(store, (result,))

    assert store.batches == []
    assert store.find_nodes(backend.result.nodes[0].compile_id) == ()
    assert store.find_edges(backend.result.nodes[0].compile_id) == ()


def test_atomic_certificate_ingestion_leaves_destination_unchanged_on_collision(
    tmp_path,
    monkeypatch,
) -> None:
    backend = future_complete_backend(tmp_path, monkeypatch)
    certificate = backend.owner_certificates.certificate_nodes[0]
    diagnostic_nodes = tuple(node for node in backend.result.nodes if node.kind != "owner-proof-certificate")
    collision = certificate.with_attributes({**certificate.attributes, "stack_offset": 0x48})
    store = _RecordingEvidenceStore()
    store.add_nodes(diagnostic_nodes)
    store.add_edges(backend.result.edges)
    store.add_nodes((collision,))
    before_nodes = store.find_nodes(certificate.compile_id)
    before_edges = store.find_edges(certificate.compile_id)
    store.batches.clear()

    with pytest.raises(ValueError, match="record ID collision"):
        add_adapter_results_atomically(store, (backend.result,))

    assert store.batches == []
    assert store.find_nodes(certificate.compile_id) == before_nodes
    assert store.find_edges(certificate.compile_id) == before_edges


def test_atomic_ingestion_leaves_destination_unchanged_on_bad_edge() -> None:
    source = _node("compile-a", "66", "row-counter")
    dangling = EvidenceEdge.create(
        compile_id=source.compile_id,
        function=source.function,
        kind="lowers-to",
        source_id=source.record_id,
        target_id="missing-target",
        occurrence_ordinal=0,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        provenance=_prov(),
        attributes={},
    )
    store = _RecordingEvidenceStore()

    with pytest.raises(ValueError, match="edge endpoint not found"):
        add_adapter_results_atomically(
            store,
            (AdapterResult(nodes=(source,), edges=(dangling,)),),
        )

    assert store.batches == []
    assert store.find_nodes(source.compile_id) == ()
    assert store.find_edges(source.compile_id) == ()


@pytest.mark.parametrize("results", ((), (AdapterResult(),)))
def test_atomic_ingestion_empty_results_is_call_level_no_op(
    results: tuple[AdapterResult, ...],
) -> None:
    store = _RecordingEvidenceStore()

    add_adapter_results_atomically(store, results)

    assert store.batches == []


def test_atomic_ingestion_is_idempotent_for_repeated_adapter_result(
    tmp_path,
    monkeypatch,
) -> None:
    backend = future_complete_backend(tmp_path, monkeypatch)
    store = _RecordingEvidenceStore()
    add_adapter_results_atomically(store, (backend.result,))
    before_nodes = store.find_nodes(backend.result.nodes[0].compile_id)
    before_edges = store.find_edges(backend.result.nodes[0].compile_id)
    store.batches.clear()

    add_adapter_results_atomically(store, (backend.result,))

    assert store.find_nodes(backend.result.nodes[0].compile_id) == before_nodes
    assert store.find_edges(backend.result.nodes[0].compile_id) == before_edges


def test_certificate_only_batch_resolves_recursive_destination_node_dependencies() -> None:
    base = _node("compile-a", "66", "row-counter")
    derived = EvidenceNode.create(
        compile_id="compile-a",
        function="fn_test",
        kind="virtual-register",
        local_key="67",
        role_key="row-count",
        producer_confidence=Confidence.DERIVED_UNIQUE,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        provenance=_prov(input_record_ids=(base.record_id,)),
        input_confidences=(base.confidence,),
        attributes={"virtual": 67},
    )
    certificate = _certificate("resident-node", derived)
    store = _RecordingEvidenceStore()
    store.add_nodes((base,))
    store.add_nodes((derived,))
    store.batches.clear()

    add_adapter_results_atomically(
        store,
        (AdapterResult(nodes=(certificate,)),),
    )

    assert store.batches == [("nodes", ()), ("edges", ()), ("nodes", (certificate.record_id,))]
    assert store.get_node(certificate.record_id) == certificate


def test_certificate_only_batch_resolves_destination_edge_and_endpoints() -> None:
    source = _node("compile-a", "66", "row-counter")
    target = _node("compile-a", "67", "row-count")
    edge = EvidenceEdge.create(
        compile_id="compile-a",
        function="fn_test",
        kind="lowers-to",
        source_id=source.record_id,
        target_id=target.record_id,
        occurrence_ordinal=0,
        producer_confidence=Confidence.DERIVED_UNIQUE,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        provenance=_prov(input_record_ids=(source.record_id, target.record_id)),
        input_confidences=(source.confidence, target.confidence),
        attributes={},
    )
    certificate = _certificate("resident-edge", edge)
    store = _RecordingEvidenceStore()
    store.add_nodes((source, target))
    store.add_edges((edge,))
    store.batches.clear()

    add_adapter_results_atomically(
        store,
        (AdapterResult(nodes=(certificate,)),),
    )

    assert store.batches == [("nodes", ()), ("edges", ()), ("nodes", (certificate.record_id,))]
    assert store.get_node(certificate.record_id) == certificate


def test_missing_destination_dependency_closure_makes_zero_destination_calls() -> None:
    source = _node("compile-a", "66", "row-counter")
    target = _node("compile-a", "67", "row-count")
    edge = EvidenceEdge.create(
        compile_id="compile-a",
        function="fn_test",
        kind="lowers-to",
        source_id=source.record_id,
        target_id=target.record_id,
        occurrence_ordinal=0,
        producer_confidence=Confidence.DERIVED_UNIQUE,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        provenance=_prov(),
        attributes={},
    )
    certificate = _certificate("incomplete-resident-edge", edge)
    store = _IncompleteDependencyStore(edge)

    with pytest.raises(ValueError, match="destination dependency record not found"):
        add_adapter_results_atomically(
            store,
            (AdapterResult(nodes=(certificate,)),),
        )

    assert store.batches == []
    assert store.find_nodes(certificate.compile_id) == ()
    assert store.find_edges(certificate.compile_id) == ()


def test_canonical_collision_hidden_by_python_equality_is_preflight_atomic() -> None:
    certificate = _certificate("canonical-collision", attributes={"marker": 1})
    equality_hidden_collision = certificate.with_attributes({"marker": True})
    assert equality_hidden_collision == certificate
    diagnostic = _node("compile-a", "68", "new-diagnostic")
    store = _RecordingEvidenceStore()
    store.add_nodes((equality_hidden_collision,))
    before_nodes = store.find_nodes(certificate.compile_id)
    store.batches.clear()

    with pytest.raises(ValueError, match="record ID collision"):
        add_adapter_results_atomically(
            store,
            (AdapterResult(nodes=(diagnostic, certificate)),),
        )

    assert store.batches == []
    assert store.find_nodes(certificate.compile_id) == before_nodes
    assert store.get_node(diagnostic.record_id) is None


def test_atomic_cross_category_collision_makes_zero_destination_calls() -> None:
    collision = _node("compile-a", "99", "collision")
    source = _node("compile-a", "66", "row-counter")
    target = _node("compile-a", "67", "row-count")
    edge = EvidenceEdge.create(
        compile_id="compile-a",
        function="fn_test",
        kind="lowers-to",
        source_id=source.record_id,
        target_id=target.record_id,
        occurrence_ordinal=0,
        producer_confidence=Confidence.DERIVED_UNIQUE,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        provenance=_prov(),
        attributes={},
    )
    colliding_edge = replace(edge, record_id=collision.record_id)
    store = _RecordingEvidenceStore()
    store.add_nodes((collision,))
    before_nodes = store.find_nodes(collision.compile_id)
    store.batches.clear()

    with pytest.raises(ValueError, match="record ID collision"):
        add_adapter_results_atomically(
            store,
            (AdapterResult(nodes=(source, target), edges=(colliding_edge,)),),
        )

    assert store.batches == []
    assert store.find_nodes(collision.compile_id) == before_nodes
    assert store.find_edges(collision.compile_id) == ()


def test_atomic_reverse_cross_category_collision_makes_zero_destination_calls() -> None:
    source = _node("compile-a", "66", "row-counter")
    target = _node("compile-a", "67", "row-count")
    edge = EvidenceEdge.create(
        compile_id="compile-a",
        function="fn_test",
        kind="lowers-to",
        source_id=source.record_id,
        target_id=target.record_id,
        occurrence_ordinal=0,
        producer_confidence=Confidence.DERIVED_UNIQUE,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        provenance=_prov(),
        attributes={},
    )
    colliding_node = replace(_node("compile-a", "99", "collision"), record_id=edge.record_id)
    store = _RecordingEvidenceStore()
    store.add_nodes((source, target))
    store.add_edges((edge,))
    before_nodes = store.find_nodes(source.compile_id)
    before_edges = store.find_edges(source.compile_id)
    store.batches.clear()

    with pytest.raises(ValueError, match="record ID collision"):
        add_adapter_results_atomically(
            store,
            (AdapterResult(nodes=(colliding_node,)),),
        )

    assert store.batches == []
    assert store.find_nodes(source.compile_id) == before_nodes
    assert store.find_edges(source.compile_id) == before_edges


def test_record_id_collisions_are_rejected_across_record_categories() -> None:
    store = InMemoryEvidenceStore()
    source = _node("compile-a", "66", "row-counter")
    target = _node("compile-a", "67", "row-count")
    store.add_nodes((source, target))
    edge = EvidenceEdge.create(
        compile_id="compile-a",
        function="fn_test",
        kind="lowers-to",
        source_id=source.record_id,
        target_id=target.record_id,
        occurrence_ordinal=0,
        producer_confidence=Confidence.DERIVED_UNIQUE,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        provenance=_prov(),
        attributes={},
    )
    with pytest.raises(ValueError, match="record ID collision"):
        store.add_edges((replace(edge, record_id=source.record_id),))


def test_factories_bind_input_confidences_to_provenance_ids() -> None:
    source = _node("compile-a", "66", "row-counter")
    kwargs = {
        "compile_id": "compile-a",
        "function": "fn_test",
        "kind": "virtual-register",
        "local_key": "67",
        "role_key": "row-count",
        "producer_confidence": Confidence.OBSERVED,
        "adapter_confidence": Confidence.OBSERVED,
        "attributes": {"virtual": 67},
    }
    with pytest.raises(ValueError, match="input confidences must correspond"):
        EvidenceNode.create(
            **kwargs,
            provenance=_prov(input_record_ids=(source.record_id,)),
        )
    with pytest.raises(ValueError, match="input confidences must correspond"):
        EvidenceNode.create(
            **kwargs,
            provenance=_prov(),
            input_confidences=(Confidence.HEURISTIC,),
        )


def test_store_rejects_confidence_laundered_by_direct_construction() -> None:
    store = InMemoryEvidenceStore()
    source = replace(
        _node("compile-a", "66", "row-counter"),
        producer_confidence=Confidence.HEURISTIC,
        confidence=Confidence.HEURISTIC,
    )
    store.add_nodes((source,))
    derived = replace(
        _node("compile-a", "67", "row-count"),
        provenance=_prov(input_record_ids=(source.record_id,)),
        confidence=Confidence.OBSERVED,
    )
    with pytest.raises(ValueError, match="record confidence"):
        store.add_nodes((derived,))


def test_direct_construction_recursively_detaches_mutable_attributes() -> None:
    attributes = {"nested": {"values": [1, 2]}}
    node = EvidenceNode(
        record_id="direct-node",
        compile_id="compile-a",
        function="fn_test",
        kind="virtual-register",
        role_key="row-counter",
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        confidence=Confidence.OBSERVED,
        provenance=_prov(),
        attributes=attributes,
    )
    store = InMemoryEvidenceStore()
    store.add_nodes((node,))

    attributes["nested"]["values"].append(3)

    stored = store.get_node(node.record_id)
    assert stored is not None
    assert stored.attributes["nested"]["values"] == (1, 2)


@pytest.mark.parametrize(
    ("relation_kind", "left_record_id", "right_record_id"),
    (
        ("role-corresponds-to", None, "right"),
        ("node-changed", "left", None),
        ("edge-changed", None, "right"),
        ("node-added", "left", "right"),
        ("edge-added", "left", None),
        ("node-removed", "left", "right"),
        ("edge-removed", None, "right"),
    ),
)
def test_comparison_relations_reject_the_wrong_endpoint_shape(
    relation_kind: str,
    left_record_id: str | None,
    right_record_id: str | None,
) -> None:
    with pytest.raises(ValueError, match="comparison endpoints"):
        _comparison(relation_kind, left_record_id, right_record_id)


@pytest.mark.parametrize(
    ("relation_kind", "left_record_id", "right_record_id"),
    (
        ("role-corresponds-to", "left", "right"),
        ("node-changed", "left", "right"),
        ("edge-changed", "left", "right"),
        ("node-added", None, "right"),
        ("edge-added", None, "right"),
        ("node-removed", "left", None),
        ("edge-removed", "left", None),
    ),
)
def test_comparison_relations_accept_the_normalized_endpoint_shape(
    relation_kind: str,
    left_record_id: str | None,
    right_record_id: str | None,
) -> None:
    comparison = _comparison(relation_kind, left_record_id, right_record_id)
    assert comparison.left_record_id == left_record_id
    assert comparison.right_record_id == right_record_id
