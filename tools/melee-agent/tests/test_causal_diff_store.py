from __future__ import annotations

from dataclasses import replace

import pytest

from src.mwcc_debug.causal_diff.models import (
    ComparisonRecord,
    Confidence,
    EvidenceEdge,
    EvidenceNode,
    Provenance,
)
from src.mwcc_debug.causal_diff.store import InMemoryEvidenceStore


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
