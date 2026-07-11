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
from tests.test_stack_slot_bridge import PCDUMP as BRIDGE_PCDUMP
from tests.test_stack_slot_bridge import SOURCE as BRIDGE_SOURCE


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
    "heuristic_fields",
    (
        {"ambiguous": True},
        {"source_guess": {"expression": "value"}},
        {"source_attribution": {"confidence": "heuristic"}},
    ),
)
def test_frame_heuristic_evidence_caps_declared_observed_confidence(
    tmp_path: Path,
    heuristic_fields: dict[str, object],
) -> None:
    obj = {
        "layout_order": 0,
        "start": 24,
        "end": 28,
        "size": 4,
        "kind": "local-or-temporary",
        "origin_tag": "symbolic-stack-home",
        "source": "r1-access",
        "symbol": "value",
        "producer_confidence": "observed",
        **heuristic_fields,
    }
    report = {
        "function": "fn_test",
        "current": {
            "frame_allocation_trace": {
                "status": "computed",
                "objects": [obj],
            }
        },
        "expected": None,
    }

    evidence = adapt_frame(_bundle(tmp_path, frame_report=report), _checkdiff(), _backend())
    stack = next(node for node in evidence.result.nodes if node.kind == "stack-object")
    assert stack.producer_confidence is Confidence.HEURISTIC
    assert stack.confidence is Confidence.HEURISTIC


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


@pytest.mark.parametrize(
    "mutate",
    (
        lambda report: report["current"]["frame_allocation_trace"]["objects"].append(
            {"start": "24", "end": 28, "size": 4, "kind": "local", "origin_tag": "r1-access"}
        ),
        lambda report: report.update({"stack_slot_bridge": {"status": "ok", "candidates": [{"current_offset": "24"}]}}),
        lambda report: report["current"]["frame_allocation_trace"]["objects"].append(
            {
                "start": 24,
                "end": 28,
                "size": 4,
                "kind": "local",
                "origin_tag": "symbolic-stack-home",
                "symbol": "value",
                "ambiguous": "true",
            }
        ),
        lambda report: report["current"]["frame_allocation_trace"]["objects"].append(
            {
                "start": 24,
                "end": 28,
                "size": 4,
                "kind": "local",
                "origin_tag": "symbolic-stack-home",
                "symbol": "value",
                "producer_confidence": "certain",
            }
        ),
        lambda report: report.update(
            {
                "stack_slot_bridge": {
                    "status": "ok",
                    "function": "fn_test",
                    "candidate_count": 1,
                    "candidates": [
                        {
                            "current_offset": 24,
                            "opcode": "stw",
                            "site_kind": "precolor-stack-site",
                            "mapping_status": "colorgraph",
                            "evidence": ["PASS B0:1 stw r3,24(r1)"],
                            "nearest_source_expression": {
                                "expression": "sink(value)",
                                "confidence": "certain",
                            },
                        }
                    ],
                }
            }
        ),
    ),
)
def test_supplied_frame_report_rejects_malformed_object_and_bridge_fields(
    tmp_path: Path,
    mutate,
) -> None:
    report = {
        "function": "fn_test",
        "current": {"frame_allocation_trace": {"status": "computed", "objects": []}},
        "expected": None,
    }
    mutate(report)

    with pytest.raises(BundleInputError, match="frame report"):
        adapt_frame(_bundle(tmp_path, frame_report=report), _checkdiff(), _backend())


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


def test_derived_frame_adapts_real_stack_bridge_support_records(tmp_path: Path) -> None:
    source_text = BRIDGE_SOURCE.replace("fn_80000000", "fn_test")
    pcdump = BRIDGE_PCDUMP.replace("fn_80000000", "fn_test")
    bundle = _bundle(tmp_path, source=source_text)
    backend = BackendEvidence(
        result=AdapterResult(),
        pcdump_text=pcdump,
        role_compile=None,
        nodes_by_class_ig=MappingProxyType({}),
        nodes_by_virtual=MappingProxyType({}),
    )
    localizer = {
        "frame_size": 168,
        "mismatch_count": 1,
        "deltas": (4,),
        "mismatches": (
            {
                "opcode": "stfs",
                "expected_offset": 0x34,
                "current_offset": 0x30,
                "delta": 4,
            },
        ),
    }
    checkdiff = CheckdiffEvidence(
        result=AdapterResult(),
        rows_by_offset=MappingProxyType({}),
        stack_slot_localizer=MappingProxyType(localizer),
        target_assembly=("+000: 94 21 ff 58 \tstwu r1,-168(r1)",),
        current_assembly=("+000: 94 21 ff 58 \tstwu r1,-168(r1)",),
        expected_assembly_digest="a" * 64,
    )

    evidence = adapt_frame(bundle, checkdiff, backend)

    record_ids = {record.record_id for record in (*evidence.result.nodes, *evidence.result.edges)}
    assert any(node.kind == "frame-bridge-candidate" for node in evidence.result.nodes)
    assert any(node.kind == "frame-stack-access" for node in evidence.result.nodes)
    assert any(edge.kind == "bridge-candidate-materializes-stack-object" for edge in evidence.result.edges)
    stack = next(
        node
        for node in evidence.result.nodes
        if node.kind == "stack-object" and node.attributes.get("ownership_candidates")
    )
    candidate = stack.attributes["ownership_candidates"][0]
    assert candidate["input_record_ids"]
    assert set(candidate["input_record_ids"]) <= record_ids


def _production_bridge_graph(
    tmp_path: Path,
    *,
    include_inspector_expression: bool = True,
    duplicate_source_match: bool = False,
):
    source_text = BRIDGE_SOURCE.replace("fn_80000000", "fn_test")
    pcdump = (
        BRIDGE_PCDUMP.replace("fn_80000000", "fn_test")
        .replace("stfs    f1,0x30(r1)", "stfs    f1,dist(r1)")
        .replace("lfs     f2,0x30(r1)", "lfs     f2,dist(r1)")
    )
    bundle = _bundle(tmp_path, source=source_text)
    backend = BackendEvidence(
        result=AdapterResult(),
        pcdump_text=pcdump,
        role_compile=None,
        nodes_by_class_ig=MappingProxyType({}),
        nodes_by_virtual=MappingProxyType({}),
    )
    localizer = MappingProxyType(
        {
            "frame_size": 168,
            "mismatch_count": 1,
            "deltas": (4,),
            "mismatches": (
                {
                    "opcode": "stfs",
                    "expected_offset": 0x34,
                    "current_offset": 0x30,
                    "delta": 4,
                },
            ),
        }
    )
    assembly = (
        "+000: 94 21 ff 58 \tstwu r1,-168(r1)",
        "+004: d0 21 00 30 \tstfs f1,48(r1)",
        "+008: c0 41 00 30 \tlfs f2,48(r1)",
    )
    checkdiff = CheckdiffEvidence(
        result=AdapterResult(),
        rows_by_offset=MappingProxyType({}),
        stack_slot_localizer=localizer,
        target_assembly=assembly,
        current_assembly=assembly,
        expected_assembly_digest="a" * 64,
    )
    frame = adapt_frame(bundle, checkdiff, backend)
    source = adapt_source(bundle)
    source_match = next(
        node
        for node in source.result.nodes
        if node.kind == "source-expression"
        and "sqrtf" in node.attributes["called_functions"]
        and "dist" in node.attributes["identifiers"]
        and node.attributes["operator"] == "="
    )
    if duplicate_source_match:
        duplicate = _node(
            bundle,
            "source-expression",
            "duplicate-dist-source",
            dict(source_match.attributes),
            confidence=Confidence.HEURISTIC,
        )
        source = type("Source", (), {})()
        source.result = AdapterResult(nodes=(*adapt_source(bundle).result.nodes, duplicate))
        source.expressions_by_signature = MappingProxyType({})
        source.inline_scopes_by_callee = MappingProxyType({})
    objobject = _node(
        bundle,
        "objobject",
        "dist-object",
        {"name": "dist", "data_type": "DLOCAL", "type_text": "float"},
    )
    inspector_expression = _node(
        bundle,
        "enode",
        "dist-source-expression",
        {
            "opcode": "EASS",
            "expression": "dist = sqrtf(dx * dx + dy * dy)",
            "type_text": "float",
        },
    )
    inspector_nodes = (objobject, inspector_expression) if include_inspector_expression else (objobject,)
    graph = build_frontier_graph(
        bundle,
        InMemoryEvidenceStore(),
        checkdiff,
        backend,
        AdapterResult(nodes=inspector_nodes),
        frame,
        source,
    )
    return graph, source_match, inspector_expression


def test_real_bridge_semantically_joins_unique_source_and_inspector(tmp_path: Path) -> None:
    graph, source_match, inspector_expression = _production_bridge_graph(tmp_path)
    edge = graph.store.find_edges(graph.bundle.compile_id, edge_kind="materializes-as-stack-object")[0]
    assert edge.attributes["ownership_basis"] == "symbol-expression-consumer-stack-access"
    assert edge.confidence is Confidence.HEURISTIC
    assert {source_match.record_id, inspector_expression.record_id} <= set(edge.provenance.input_record_ids)


@pytest.mark.parametrize(
    ("include_inspector_expression", "duplicate_source_match"),
    ((False, False), (True, True)),
)
def test_real_bridge_missing_or_ambiguous_semantic_match_stays_name_only(
    tmp_path: Path,
    include_inspector_expression: bool,
    duplicate_source_match: bool,
) -> None:
    graph, _source, _inspector = _production_bridge_graph(
        tmp_path,
        include_inspector_expression=include_inspector_expression,
        duplicate_source_match=duplicate_source_match,
    )
    edge = graph.store.find_edges(graph.bundle.compile_id, edge_kind="materializes-as-stack-object")[0]
    assert edge.attributes["ownership_basis"] == "symbol-name-only"
    assert edge.confidence is Confidence.HEURISTIC


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


def test_source_extracts_assignment_and_call_types(tmp_path: Path) -> None:
    source = """\
int sink(float value);
void fn_test(float input)
{
    float local;
    local = input;
    sink(local);
}
"""
    evidence = adapt_source(_bundle(tmp_path, source=source))
    assignments = [
        node
        for node in evidence.result.nodes
        if node.kind == "source-expression" and node.attributes["operator"] == "="
    ]
    calls = [
        node
        for node in evidence.result.nodes
        if node.kind == "source-expression" and "sink" in node.attributes["called_functions"]
    ]
    assert any(node.attributes["type_text"] == "float" for node in assignments)
    assert any(node.attributes["type_text"] == "int" for node in calls)


def test_source_preserves_nested_cast_type_evidence(tmp_path: Path) -> None:
    source = """\
void fn_test(int input)
{
    sink((float) (short) input);
}
"""
    evidence = adapt_source(_bundle(tmp_path, source=source))
    casts = [
        node.attributes["type_text"]
        for node in evidence.result.nodes
        if node.kind == "source-expression" and node.attributes["node_type"] == "cast_expression"
    ]
    assert casts == ["float", "short"]


def test_enclosing_operator_tree_includes_nested_cast_types(tmp_path: Path) -> None:
    source = """\
void fn_test(int input)
{
    sink((float) input);
    sink((double) input);
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


def test_source_preserves_pointer_and_qualifier_type_evidence(tmp_path: Path) -> None:
    source = """\
const void* identity(const void* value);
void fn_test(const void* input)
{
    const void* local;
    local = input;
    identity(local);
}
"""
    evidence = adapt_source(_bundle(tmp_path, source=source))
    assignment = next(
        node
        for node in evidence.result.nodes
        if node.kind == "source-expression" and node.attributes["operator"] == "="
    )
    call = next(
        node
        for node in evidence.result.nodes
        if node.kind == "source-expression" and "identity" in node.attributes["called_functions"]
    )
    assert assignment.attributes["type_text"] == "const void *"
    assert call.attributes["type_text"] == "const void *"


def test_source_preserves_pointer_level_qualifiers(tmp_path: Path) -> None:
    source = """\
void fn_test(void* input, int* other, const int** nested)
{
    void * const p = input;
    volatile int * restrict q = other;
    const int ** volatile r = nested;
    p = input;
    q = other;
    r = nested;
}
"""
    evidence = adapt_source(_bundle(tmp_path, source=source))
    assignments = [
        node.attributes["type_text"]
        for node in evidence.result.nodes
        if node.kind == "source-expression" and node.attributes["operator"] == "="
    ]
    assert assignments == [
        "void * const",
        "volatile int * restrict",
        "const int * * volatile",
    ]


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


def test_source_enode_join_missing_consumer_and_identifiers_is_heuristic(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    tree = ("number_literal", "1")
    source_node = _node(
        bundle,
        "source-expression",
        "source-empty-roles",
        {
            "node_type": "assignment_expression",
            "operator": "=",
            "operator_tree": tree,
            "identifiers": (),
            "called_functions": (),
            "constants": ("1",),
            "scope_path": ("fn_test",),
            "type_text": "int",
            "order": 0,
        },
        confidence=Confidence.DERIVED_UNIQUE,
    )
    inspector_node = _node(
        bundle,
        "enode",
        "inspector-empty-roles",
        {
            "opcode": "EASS",
            "expression": "1",
            "operator_tree": tree,
            "scope_path": ("fn_test",),
            "type_text": "int",
            "order": 0,
        },
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


def _supported_stack_graph(
    tmp_path: Path,
    *,
    operands: str = "r3,24(r1)",
    ownership_candidate_count: int = 1,
):
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
        {
            "opcode": "ECALL",
            "expression": "sink(fighter)",
            "type_text": "int",
        },
    )
    source_expression = _node(
        bundle,
        "source-expression",
        "fighter-source",
        {
            "called_functions": ("sink",),
            "identifiers": ("fighter", "sink"),
            "text": "sink(fighter)",
            "type_text": "int",
        },
        confidence=Confidence.DERIVED_UNIQUE,
    )
    stack_access = _node(
        bundle,
        "pcode-occurrence",
        "fighter-stack-access",
        {"opcode": "stw", "operands": operands, "instruction_index": 4},
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
            "ownership_candidates": tuple(
                {
                    "current_offset": 24,
                    "nearest_source_expression": {
                        "expression": "sink(fighter)",
                        "confidence": "derived-unique",
                    },
                    "input_record_ids": support_ids,
                }
                for _index in range(ownership_candidate_count)
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
    return graph, inspector_object, stack, support_ids


def test_stack_join_cites_complete_unique_ownership_support(tmp_path: Path) -> None:
    graph, inspector_object, stack, support_ids = _supported_stack_graph(tmp_path)

    edge = graph.store.find_edges(graph.bundle.compile_id, edge_kind="materializes-as-stack-object")[0]
    assert edge.confidence is Confidence.DERIVED_UNIQUE
    assert set(edge.provenance.input_record_ids) == {
        inspector_object.record_id,
        stack.record_id,
        *support_ids,
    }


def test_stack_join_rejects_non_r1_displacement_access(tmp_path: Path) -> None:
    graph, _object, _stack, _support = _supported_stack_graph(tmp_path, operands="r3,24(r31)")
    edge = graph.store.find_edges(graph.bundle.compile_id, edge_kind="materializes-as-stack-object")[0]
    assert edge.confidence is Confidence.HEURISTIC


def test_stack_join_requires_one_qualifying_ownership_candidate(tmp_path: Path) -> None:
    graph, _object, _stack, _support = _supported_stack_graph(tmp_path, ownership_candidate_count=2)
    edge = graph.store.find_edges(graph.bundle.compile_id, edge_kind="materializes-as-stack-object")[0]
    assert edge.confidence is Confidence.HEURISTIC


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


def test_graph_derivation_failure_leaves_store_unchanged(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    malformed = _node(
        bundle,
        "source-expression",
        "malformed-order",
        {
            "node_type": "call_expression",
            "operator": "call",
            "called_functions": ("sink",),
            "identifiers": ("sink", "value"),
            "constants": (),
            "scope_path": ("fn_test",),
            "type_text": "void",
            "order": "not-an-integer",
        },
    )
    source = type("Source", (), {})()
    source.result = AdapterResult(nodes=(malformed,))
    source.expressions_by_signature = MappingProxyType({})
    source.inline_scopes_by_callee = MappingProxyType({})
    frame = type("Frame", (), {})()
    frame.result = AdapterResult()
    frame.expected_stack_roles = MappingProxyType({})
    frame.current_stack_nodes = MappingProxyType({})
    inspector = _node(
        bundle,
        "enode",
        "sink-enode",
        {"opcode": "ECALL", "expression": "sink(value)", "order": 0},
    )
    store = InMemoryEvidenceStore()

    with pytest.raises(ValueError, match="invalid literal"):
        build_frontier_graph(
            bundle,
            store,
            _checkdiff(),
            _backend(),
            AdapterResult(nodes=(inspector,)),
            frame,
            source,
        )

    assert store.find_nodes(bundle.compile_id) == ()
