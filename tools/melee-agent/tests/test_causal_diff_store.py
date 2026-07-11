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


def _prov() -> Provenance:
    return Provenance(
        artifact_sha256="a" * 64,
        parser="unit-test.v1",
        raw_start=10,
        raw_end=20,
        derivation_rule="raw",
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
