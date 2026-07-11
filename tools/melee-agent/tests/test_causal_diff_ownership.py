from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from src.mwcc_debug.causal_diff.asm_adapter import CheckdiffEvidence
from src.mwcc_debug.causal_diff.backend_adapter import BackendEvidence
from src.mwcc_debug.causal_diff.bundles import BundleInputError, ValidatedBundle
from src.mwcc_debug.causal_diff.frame_adapter import adapt_frame
from src.mwcc_debug.causal_diff.graph import build_frontier_graph
from src.mwcc_debug.causal_diff.models import (
    AdapterResult,
    Confidence,
    EvidenceEdge,
    EvidenceNode,
    FrontierBundleManifest,
    Provenance,
)
from src.mwcc_debug.causal_diff.source_adapter import adapt_source
from src.mwcc_debug.causal_diff.store import InMemoryEvidenceStore


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bundle(
    tmp_path: Path,
    *,
    source: str = "void fn_test(void) {}\n",
    frame_report: dict[str, object] | None = None,
    frame_version: str = "frame-reservations.v1",
) -> ValidatedBundle:
    source_path = tmp_path / "candidate.c"
    source_path.write_text(source)
    source_digest = _digest(source.encode())
    digest = "a" * 64
    artifacts: dict[str, object] = {
        "source": {"path": source_path.name, "sha256": source_digest},
        "checkdiff": {"path": "checkdiff.json", "sha256": digest},
        "backend": [
            {
                "path": "backend.txt",
                "sha256": digest,
                "format": "mwcc-debug-pcdump",
                "capabilities": (),
            }
        ],
        "inspector": {"path": "inspector.txt", "sha256": digest},
    }
    artifact_paths: dict[str, Path] = {"source": source_path}
    if frame_report is not None:
        frame_path = tmp_path / "frame.json"
        frame_bytes = (json.dumps(frame_report) + "\n").encode()
        frame_path.write_bytes(frame_bytes)
        artifacts["frame_report"] = {
            "path": frame_path.name,
            "sha256": _digest(frame_bytes),
        }
        artifact_paths["frame_report"] = frame_path
    manifest = FrontierBundleManifest.model_validate(
        {
            "schema_version": "causal-frontier-bundle.v1",
            "label": "paired",
            "function": "fn_test",
            "compile": {
                "id": "b" * 64,
                "compiler": "mwcc_233_163n",
                "target_build": "GALE01",
                "flags_digest": digest,
                "environment_digest": digest,
                "source_digest": source_digest,
                "expected_assembly_digest": digest,
            },
            "artifacts": artifacts,
            "producer_versions": {"frame_report": frame_version},
        }
    )
    return ValidatedBundle(
        manifest_path=tmp_path / "bundle.json",
        manifest=manifest,
        label="paired",
        compile_id=manifest.compile.id,
        artifact_paths=MappingProxyType(artifact_paths),
    )


def _checkdiff() -> CheckdiffEvidence:
    return CheckdiffEvidence(
        result=AdapterResult(),
        rows_by_offset=MappingProxyType({}),
        stack_slot_localizer=None,
        target_assembly=(),
        current_assembly=(),
        expected_assembly_digest="a" * 64,
    )


def _backend(*nodes: EvidenceNode) -> BackendEvidence:
    return BackendEvidence(
        result=AdapterResult(nodes=nodes),
        pcdump_text="",
        role_compile=None,
        nodes_by_class_ig=MappingProxyType({}),
        nodes_by_virtual=MappingProxyType({}),
    )


def _node(
    bundle: ValidatedBundle,
    kind: str,
    key: object,
    attributes: dict[str, object],
    *,
    confidence: Confidence = Confidence.OBSERVED,
) -> EvidenceNode:
    return EvidenceNode.create(
        compile_id=bundle.compile_id,
        function=bundle.manifest.function,
        kind=kind,
        local_key=key,
        role_key=None,
        producer_confidence=confidence,
        adapter_confidence=Confidence.OBSERVED,
        provenance=Provenance(
            artifact_sha256="c" * 64,
            parser="unit-test.v1",
            raw_start=0,
            raw_end=1,
            derivation_rule="unit-test",
        ),
        attributes=attributes,
    )


def test_frame_report_preserves_derived_confidence(tmp_path: Path) -> None:
    report = {
        "function": "fn_test",
        "current": {
            "frame_allocation_trace": {
                "status": "computed",
                "objects": [
                    {
                        "layout_order": 0,
                        "start": 24,
                        "end": 28,
                        "size": 4,
                        "kind": "local-or-temporary",
                        "origin_tag": "symbolic-stack-home",
                        "source": "r1-access",
                        "symbol": "fighter",
                        "boundary_confidence": "access-width",
                        "ambiguous": False,
                    }
                ],
            }
        },
        "expected": None,
    }
    bundle = _bundle(tmp_path, frame_report=report)

    evidence = adapt_frame(bundle, _checkdiff(), _backend())

    stack = next(node for node in evidence.result.nodes if node.kind == "stack-object")
    assert stack.producer_confidence is Confidence.DERIVED_UNIQUE
    assert stack.confidence is Confidence.DERIVED_UNIQUE
    assert evidence.current_stack_nodes["fighter"] == stack.record_id


@pytest.mark.parametrize(
    ("report", "version", "message"),
    (
        ({"current": {"frame_allocation_trace": {"objects": []}}}, "frame-reservations.v1", "function"),
        (
            {
                "function": "fn_test",
                "current": {"frame_allocation_trace": {"objects": []}},
            },
            "future-frame.v2",
            "producer version",
        ),
    ),
)
def test_supplied_frame_report_is_versioned_and_function_bound(
    tmp_path: Path,
    report: dict[str, object],
    version: str,
    message: str,
) -> None:
    bundle = _bundle(
        tmp_path,
        frame_report=report,
        frame_version=version,
    )

    with pytest.raises(BundleInputError, match=message):
        adapt_frame(bundle, _checkdiff(), _backend())


def test_derived_frame_nodes_cite_every_consumed_artifact(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    pcdump = """\
Starting function fn_test
FINAL CODE AFTER INSTRUCTION SCHEDULING
fn_test
B0: Succ={} Pred={} Labels={}
    stwu r1,-40(r1)
    stw r8,24(r1)
    addi r1,r1,40
"""
    backend = BackendEvidence(
        result=AdapterResult(),
        pcdump_text=pcdump,
        role_compile=None,
        nodes_by_class_ig=MappingProxyType({}),
        nodes_by_virtual=MappingProxyType({}),
    )
    checkdiff = CheckdiffEvidence(
        result=AdapterResult(),
        rows_by_offset=MappingProxyType({}),
        stack_slot_localizer=None,
        target_assembly=("+000: 94 21 ff d8 \tstwu r1,-40(r1)",),
        current_assembly=("+000: 94 21 ff d8 \tstwu r1,-40(r1)",),
        expected_assembly_digest="a" * 64,
    )

    evidence = adapt_frame(bundle, checkdiff, backend)

    inputs = {node.record_id: node for node in evidence.result.nodes if node.kind == "frame-input-artifact"}
    stack = next(node for node in evidence.result.nodes if node.kind == "stack-object")
    assert {inputs[record_id].attributes["artifact_name"] for record_id in stack.provenance.input_record_ids} == {
        "source",
        "checkdiff",
        "backend[0]",
    }


def test_source_collects_target_and_one_direct_inline_level(tmp_path: Path) -> None:
    source = """\
static inline void emit(void* jobj, int anim)
{
    HSD_JObjReqAnimAll(jobj, anim);
}

void fn_test(void* jobj)
{
    emit(jobj, 1);
}
"""
    evidence = adapt_source(_bundle(tmp_path, source=source))

    assert "emit" in evidence.inline_scopes_by_callee
    call_nodes = [
        node
        for node in evidence.result.nodes
        if node.kind == "source-expression" and "HSD_JObjReqAnimAll" in node.attributes["called_functions"]
    ]
    assert len(call_nodes) == 1
    assert call_nodes[0].attributes["scope_path"][0] == "emit"
    assert call_nodes[0].confidence is Confidence.DERIVED_UNIQUE


def test_duplicate_source_signatures_remain_heuristic_and_present(tmp_path: Path) -> None:
    source = """\
void fn_test(void* jobj)
{
    HSD_JObjReqAnimAll(jobj, 1);
    HSD_JObjReqAnimAll(jobj, 1);
}
"""
    evidence = adapt_source(_bundle(tmp_path, source=source))

    calls = [
        node
        for node in evidence.result.nodes
        if node.kind == "source-expression" and "HSD_JObjReqAnimAll" in node.attributes["called_functions"]
    ]
    assert len(calls) == 2
    assert all(node.confidence is Confidence.HEURISTIC for node in calls)


def test_source_signature_distinguishes_nested_operator_trees(tmp_path: Path) -> None:
    source = """\
void fn_test(int a, int b, int c)
{
    sink(a + b * c);
    sink((a + b) * c);
}
"""
    evidence = adapt_source(_bundle(tmp_path, source=source))

    calls = [
        node
        for node in evidence.result.nodes
        if node.kind == "source-expression" and "sink" in node.attributes["called_functions"]
    ]
    assert len(calls) == 2
    assert calls[0].attributes["operator_tree"] != calls[1].attributes["operator_tree"]
    assert all(node.confidence is Confidence.DERIVED_UNIQUE for node in calls)


def test_unique_inspector_to_backend_join_is_proof_capable(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    source_node = _node(
        bundle,
        "source-expression",
        "source-call",
        {
            "node_type": "call_expression",
            "operator": "call",
            "identifiers": ("fighter", "HSD_JObjReqAnimAll"),
            "called_functions": ("HSD_JObjReqAnimAll",),
            "constants": (),
            "scope_path": ("fn_test",),
            "type_text": "void",
            "order": 0,
        },
        confidence=Confidence.DERIVED_UNIQUE,
    )
    inspector_node = _node(
        bundle,
        "enode",
        "inspector-call",
        {
            "opcode": "ECALL",
            "expression": "HSD_JObjReqAnimAll(fighter)",
            "type_text": "void",
            "order": 0,
        },
    )
    backend_node = _node(
        bundle,
        "pcode-occurrence",
        "backend-call",
        {
            "opcode": "bl",
            "operands": "HSD_JObjReqAnimAll",
            "instruction_index": 0,
            "type_text": "void",
        },
    )
    virtual_node = _node(
        bundle,
        "virtual-register",
        "backend-argument",
        {"class": "r", "virtual": 40},
    )
    use_edge = EvidenceEdge.create(
        compile_id=bundle.compile_id,
        function=bundle.manifest.function,
        kind="uses-virtual",
        source_id=backend_node.record_id,
        target_id=virtual_node.record_id,
        occurrence_ordinal=0,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        provenance=Provenance(
            artifact_sha256="c" * 64,
            parser="unit-test.v1",
            raw_start=0,
            raw_end=1,
            derivation_rule="unit-test-use",
            input_record_ids=(backend_node.record_id, virtual_node.record_id),
        ),
        input_confidences=(backend_node.confidence, virtual_node.confidence),
        attributes={"operand_position": 0},
    )
    source = type("Source", (), {})()
    source.result = AdapterResult(nodes=(source_node,))
    source.expressions_by_signature = MappingProxyType({})
    source.inline_scopes_by_callee = MappingProxyType({})
    frame = type("Frame", (), {})()
    frame.result = AdapterResult()
    frame.expected_stack_roles = MappingProxyType({})
    frame.current_stack_nodes = MappingProxyType({})

    graph = build_frontier_graph(
        bundle,
        InMemoryEvidenceStore(),
        _checkdiff(),
        BackendEvidence(
            result=AdapterResult(
                nodes=(backend_node, virtual_node),
                edges=(use_edge,),
            ),
            pcdump_text="",
            role_compile=None,
            nodes_by_class_ig=MappingProxyType({}),
            nodes_by_virtual=MappingProxyType({}),
        ),
        AdapterResult(nodes=(inspector_node,)),
        frame,
        source,
    )

    edges = graph.store.find_edges(bundle.compile_id, edge_kind="lowers-to")
    fighter_edge = next(edge for edge in edges if edge.attributes["consumer"] == "HSD_JObjReqAnimAll")
    assert fighter_edge.confidence is Confidence.DERIVED_UNIQUE
    assert fighter_edge.provenance.input_record_ids
    assert set(fighter_edge.provenance.input_record_ids) == {
        inspector_node.record_id,
        backend_node.record_id,
        virtual_node.record_id,
        use_edge.record_id,
    }


def test_lowering_without_def_use_chain_remains_heuristic(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    inspector_node = _node(
        bundle,
        "enode",
        "inspector-call",
        {
            "opcode": "ECALL",
            "expression": "sink(value)",
            "type_text": "void",
            "order": 0,
        },
    )
    backend_node = _node(
        bundle,
        "pcode-occurrence",
        "backend-call",
        {
            "opcode": "bl",
            "operands": "sink",
            "instruction_index": 0,
            "type_text": "void",
        },
    )
    frame = type("Frame", (), {})()
    frame.result = AdapterResult()
    frame.expected_stack_roles = MappingProxyType({})
    frame.current_stack_nodes = MappingProxyType({})
    source = type("Source", (), {})()
    source.result = AdapterResult()
    source.expressions_by_signature = MappingProxyType({})
    source.inline_scopes_by_callee = MappingProxyType({})

    graph = build_frontier_graph(
        bundle,
        InMemoryEvidenceStore(),
        _checkdiff(),
        _backend(backend_node),
        AdapterResult(nodes=(inspector_node,)),
        frame,
        source,
    )

    edge = graph.store.find_edges(bundle.compile_id, edge_kind="lowers-to")[0]
    assert edge.confidence is Confidence.HEURISTIC


def test_source_enode_join_missing_tree_scope_and_type_is_heuristic(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    source_node = _node(
        bundle,
        "source-expression",
        "source-call",
        {
            "node_type": "call_expression",
            "operator": "call",
            "operator_tree": ("call_expression", "call", ()),
            "identifiers": ("value", "sink"),
            "called_functions": ("sink",),
            "constants": (),
            "scope_path": ("fn_test",),
            "type_text": "void",
            "order": 0,
        },
        confidence=Confidence.DERIVED_UNIQUE,
    )
    inspector_node = _node(
        bundle,
        "enode",
        "inspector-call",
        {"opcode": "ECALL", "expression": "sink(value)", "order": 0},
    )
    frame = type("Frame", (), {})()
    frame.result = AdapterResult()
    frame.expected_stack_roles = MappingProxyType({})
    frame.current_stack_nodes = MappingProxyType({})
    source = type("Source", (), {})()
    source.result = AdapterResult(nodes=(source_node,))
    source.expressions_by_signature = MappingProxyType({})
    source.inline_scopes_by_callee = MappingProxyType({})

    graph = build_frontier_graph(
        bundle,
        InMemoryEvidenceStore(),
        _checkdiff(),
        _backend(),
        AdapterResult(nodes=(inspector_node,)),
        frame,
        source,
    )

    edge = graph.store.find_edges(bundle.compile_id, edge_kind="expression-represents-enode")[0]
    assert edge.confidence is Confidence.HEURISTIC


def test_name_only_stack_join_remains_heuristic(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    inspector_object = _node(
        bundle,
        "objobject",
        "fighter-object",
        {"name": "fighter", "data_type": "DLOCAL", "type_text": "int"},
    )
    stack_a = _node(
        bundle,
        "stack-object",
        "stack-a",
        {"symbol": "fighter", "start": 24, "end": 28, "accesses": ()},
        confidence=Confidence.HEURISTIC,
    )
    stack_b = _node(
        bundle,
        "stack-object",
        "stack-b",
        {"symbol": "fighter", "start": 28, "end": 32, "accesses": ()},
        confidence=Confidence.HEURISTIC,
    )
    frame = type("Frame", (), {})()
    frame.result = AdapterResult(nodes=(stack_a, stack_b))
    frame.expected_stack_roles = MappingProxyType({})
    frame.current_stack_nodes = MappingProxyType({})
    source = type("Source", (), {})()
    source.result = AdapterResult()
    source.expressions_by_signature = MappingProxyType({})
    source.inline_scopes_by_callee = MappingProxyType({})

    graph = build_frontier_graph(
        bundle,
        InMemoryEvidenceStore(),
        _checkdiff(),
        _backend(),
        AdapterResult(nodes=(inspector_object,)),
        frame,
        source,
    )

    edges = graph.store.find_edges(bundle.compile_id, edge_kind="materializes-as-stack-object")
    assert len(edges) == 2
    assert all(edge.confidence is Confidence.HEURISTIC for edge in edges)


def test_stack_join_without_consumer_remains_heuristic(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    inspector_object = _node(
        bundle,
        "objobject",
        "fighter-object",
        {"name": "fighter", "data_type": "DLOCAL", "type_text": "int"},
    )
    stack = _node(
        bundle,
        "stack-object",
        "stack-a",
        {
            "symbol": "fighter",
            "start": 24,
            "end": 28,
            "ownership_candidates": (
                {
                    "current_offset": 24,
                    "nearest_source_expression": {"expression": "fighter"},
                },
            ),
        },
        confidence=Confidence.DERIVED_UNIQUE,
    )
    frame = type("Frame", (), {})()
    frame.result = AdapterResult(nodes=(stack,))
    frame.expected_stack_roles = MappingProxyType({})
    frame.current_stack_nodes = MappingProxyType({"fighter": stack.record_id})
    source = type("Source", (), {})()
    source.result = AdapterResult()
    source.expressions_by_signature = MappingProxyType({})
    source.inline_scopes_by_callee = MappingProxyType({})

    graph = build_frontier_graph(
        bundle,
        InMemoryEvidenceStore(),
        _checkdiff(),
        _backend(),
        AdapterResult(nodes=(inspector_object,)),
        frame,
        source,
    )

    edge = graph.store.find_edges(bundle.compile_id, edge_kind="materializes-as-stack-object")[0]
    assert edge.confidence is Confidence.HEURISTIC


def test_stack_join_does_not_promote_heuristic_source_hint(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    inspector_object = _node(
        bundle,
        "objobject",
        "fighter-object",
        {"name": "fighter", "data_type": "DLOCAL", "type_text": "int"},
    )
    stack = _node(
        bundle,
        "stack-object",
        "stack-a",
        {
            "symbol": "fighter",
            "start": 24,
            "end": 28,
            "ownership_candidates": (
                {
                    "current_offset": 24,
                    "nearest_source_expression": {
                        "expression": "sink(fighter)",
                        "confidence": "source-call-heuristic",
                    },
                },
            ),
        },
        confidence=Confidence.DERIVED_UNIQUE,
    )
    frame = type("Frame", (), {})()
    frame.result = AdapterResult(nodes=(stack,))
    frame.expected_stack_roles = MappingProxyType({})
    frame.current_stack_nodes = MappingProxyType({"fighter": stack.record_id})
    source = type("Source", (), {})()
    source.result = AdapterResult()
    source.expressions_by_signature = MappingProxyType({})
    source.inline_scopes_by_callee = MappingProxyType({})

    graph = build_frontier_graph(
        bundle,
        InMemoryEvidenceStore(),
        _checkdiff(),
        _backend(),
        AdapterResult(nodes=(inspector_object,)),
        frame,
        source,
    )

    edge = graph.store.find_edges(bundle.compile_id, edge_kind="materializes-as-stack-object")[0]
    assert edge.confidence is Confidence.HEURISTIC


def test_stack_join_cites_complete_unique_ownership_support(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    inspector_object = _node(
        bundle,
        "objobject",
        "fighter-object",
        {"name": "fighter", "data_type": "DLOCAL", "type_text": "int"},
    )
    inspector_expression = _node(
        bundle,
        "enode",
        "fighter-consumer",
        {"opcode": "ECALL", "expression": "sink(fighter)"},
    )
    source_expression = _node(
        bundle,
        "source-expression",
        "fighter-source",
        {
            "called_functions": ("sink",),
            "identifiers": ("fighter", "sink"),
            "text": "sink(fighter)",
        },
        confidence=Confidence.DERIVED_UNIQUE,
    )
    stack_access = _node(
        bundle,
        "pcode-occurrence",
        "fighter-stack-access",
        {"opcode": "stw", "operands": "r3,24(r1)", "instruction_index": 4},
    )
    support_ids = (
        source_expression.record_id,
        inspector_expression.record_id,
        stack_access.record_id,
    )
    stack = _node(
        bundle,
        "stack-object",
        "stack-a",
        {
            "symbol": "fighter",
            "start": 24,
            "end": 28,
            "ownership_candidates": (
                {
                    "current_offset": 24,
                    "nearest_source_expression": {
                        "expression": "sink(fighter)",
                        "confidence": "derived-unique",
                    },
                    "input_record_ids": support_ids,
                },
            ),
        },
        confidence=Confidence.DERIVED_UNIQUE,
    )
    frame = type("Frame", (), {})()
    frame.result = AdapterResult(nodes=(stack,))
    frame.expected_stack_roles = MappingProxyType({})
    frame.current_stack_nodes = MappingProxyType({"fighter": stack.record_id})
    source = type("Source", (), {})()
    source.result = AdapterResult(nodes=(source_expression,))
    source.expressions_by_signature = MappingProxyType({})
    source.inline_scopes_by_callee = MappingProxyType({})

    graph = build_frontier_graph(
        bundle,
        InMemoryEvidenceStore(),
        _checkdiff(),
        _backend(stack_access),
        AdapterResult(nodes=(inspector_object, inspector_expression)),
        frame,
        source,
    )

    edge = graph.store.find_edges(bundle.compile_id, edge_kind="materializes-as-stack-object")[0]
    assert edge.confidence is Confidence.DERIVED_UNIQUE
    assert set(edge.provenance.input_record_ids) == {
        inspector_object.record_id,
        stack.record_id,
        *support_ids,
    }


def test_missing_backend_segment_does_not_create_join(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    inspector_node = _node(
        bundle,
        "enode",
        "inspector-call",
        {"opcode": "ECALL", "expression": "sink(value)", "order": 0},
    )
    frame = type("Frame", (), {})()
    frame.result = AdapterResult()
    frame.expected_stack_roles = MappingProxyType({})
    frame.current_stack_nodes = MappingProxyType({})
    source = type("Source", (), {})()
    source.result = AdapterResult()
    source.expressions_by_signature = MappingProxyType({})
    source.inline_scopes_by_callee = MappingProxyType({})

    graph = build_frontier_graph(
        bundle,
        InMemoryEvidenceStore(),
        _checkdiff(),
        _backend(),
        AdapterResult(nodes=(inspector_node,)),
        frame,
        source,
    )

    assert graph.store.find_edges(bundle.compile_id, edge_kind="lowers-to") == ()


def test_graph_rejects_foreign_compile_records_before_ingestion(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    foreign = EvidenceNode.create(
        compile_id="d" * 64,
        function=bundle.manifest.function,
        kind="source-expression",
        local_key="foreign",
        role_key=None,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        provenance=Provenance(
            artifact_sha256="c" * 64,
            parser="unit-test.v1",
            raw_start=0,
            raw_end=1,
            derivation_rule="foreign-compile",
        ),
        attributes={},
    )
    source = type("Source", (), {})()
    source.result = AdapterResult(nodes=(foreign,))
    source.expressions_by_signature = MappingProxyType({})
    source.inline_scopes_by_callee = MappingProxyType({})
    frame = type("Frame", (), {})()
    frame.result = AdapterResult()
    frame.expected_stack_roles = MappingProxyType({})
    frame.current_stack_nodes = MappingProxyType({})
    store = InMemoryEvidenceStore()

    with pytest.raises(BundleInputError, match="within-compile"):
        build_frontier_graph(
            bundle,
            store,
            _checkdiff(),
            _backend(),
            AdapterResult(),
            frame,
            source,
        )

    assert store.find_nodes(foreign.compile_id) == ()


def test_atomic_ingestion_leaves_store_unchanged_on_bad_edge(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    source_node = _node(
        bundle,
        "source-expression",
        "valid-source",
        {},
    )
    dangling = EvidenceEdge.create(
        compile_id=bundle.compile_id,
        function=bundle.manifest.function,
        kind="expression-represents-enode",
        source_id=source_node.record_id,
        target_id="missing-enode",
        occurrence_ordinal=0,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        provenance=Provenance(
            artifact_sha256="c" * 64,
            parser="unit-test.v1",
            raw_start=0,
            raw_end=1,
            derivation_rule="dangling-edge",
        ),
        attributes={},
    )
    source = type("Source", (), {})()
    source.result = AdapterResult(nodes=(source_node,), edges=(dangling,))
    source.expressions_by_signature = MappingProxyType({})
    source.inline_scopes_by_callee = MappingProxyType({})
    frame = type("Frame", (), {})()
    frame.result = AdapterResult()
    frame.expected_stack_roles = MappingProxyType({})
    frame.current_stack_nodes = MappingProxyType({})
    store = InMemoryEvidenceStore()

    with pytest.raises(ValueError, match="edge endpoint"):
        build_frontier_graph(
            bundle,
            store,
            _checkdiff(),
            _backend(),
            AdapterResult(),
            frame,
            source,
        )

    assert store.find_nodes(bundle.compile_id) == ()
