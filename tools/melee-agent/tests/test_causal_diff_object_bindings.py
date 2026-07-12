from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro.backend_object_bindings import ObjectBindingValidation
from tools.mwcc_retro.backend_pcode_lineage import (
    AnchorVirtualBinding,
    PCodeLineageValidation,
)

from src.mwcc_debug.causal_diff.alignment import (
    AbstentionReason,
    AnchorAlignment,
    BackendOwnerRoleTuple,
    EffectAbstention,
    OperandRole,
    align_anchor,
    backend_owner_correspondences,
    build_role_comparisons,
    resolve_backend_owner_candidates,
)
from src.mwcc_debug.causal_diff.backend_adapter import adapt_backends
from src.mwcc_debug.causal_diff.bundles import BundleInputError, load_bundle
from src.mwcc_debug.causal_diff.canonical import canonical_bytes
from src.mwcc_debug.causal_diff.effects import DerivedEffects, _reachable_records
from src.mwcc_debug.causal_diff.inference import _PATH_EDGE_KINDS, build_report
from src.mwcc_debug.causal_diff.models import Confidence
from src.mwcc_debug.causal_diff.object_binding_adapter import (
    ObjectBindingAdapterInput,
    ObjectBindingEvidence,
    adapt_object_bindings,
    bilateral_source_object_records,
    derive_backend_frame_recommendation,
    emit_object_binding_evidence,
    proof_complete,
)
from src.mwcc_debug.causal_diff.store import InMemoryEvidenceStore
from tests.test_causal_diff_alignment import _graph
from tests.test_retro_backend_trace_assembler import (
    _trusted_table,
    _v2_assembly_kwargs,
)

ALL_CAPABILITIES = frozenset(
    {
        "compiler-object-bindings",
        "object-to-virtual",
        "object-to-frame",
        "pcode-to-code-range",
    }
)


def _object_result(
    *,
    capture_run_id: str = "a" * 64,
    virtual: int = 66,
    semantic_stack_role: str = "row-home",
) -> ObjectBindingValidation:
    return ObjectBindingValidation(
        MappingProxyType(
            {
                "capture_run_id": capture_run_id,
                "objects": (
                    MappingProxyType(
                        {
                            "object_id": "obj-0",
                            "runtime_address": 0x1000,
                            "allocation_generation": 1,
                            "type_size": 4,
                            "areas": ("locals",),
                            "stage_snapshots": (),
                        }
                    ),
                ),
                "virtual_bindings": (
                    MappingProxyType(
                        {
                            "object_id": "obj-0",
                            "class_id": 0,
                            "class_name": "gpr",
                            "virtual_kind": "r",
                            "virtual": virtual,
                            "ig_id": virtual,
                            "ignode_runtime_address": 0x4000 + virtual,
                            "confidence": "observed",
                        }
                    ),
                ),
                "frame_bindings": (
                    MappingProxyType(
                        {
                            "object_id": "obj-0",
                            "semantic_stack_role": semantic_stack_role,
                            "area": "locals",
                            "list_node_runtime_address": 0x5000,
                            "final_r1_offset": 0x44,
                            "size": 4,
                            "confidence": "derived-unique",
                        }
                    ),
                ),
                "source_bindings": (),
                "source_capture": None,
            }
        ),
        frozenset({"compiler-object-bindings"}),
        (),
    )


def _pcode_result(*, virtual: int = 66) -> PCodeLineageValidation:
    normalized = MappingProxyType(
        {
            "pcode_instructions": (
                MappingProxyType(
                    {
                        "pcode_id": "pc-0",
                        "runtime_address": 0x6000,
                        "allocation_generation": 1,
                        "code_ranges": (
                            MappingProxyType(
                                {
                                    "start": 0x234,
                                    "end_exclusive": 0x238,
                                    "machine_operand_mappings": (
                                        MappingProxyType(
                                            {
                                                "machine_operand_key": "use:0",
                                                "emission_pcode_operand_index": 1,
                                                "operand_lineage_id": "ol-1",
                                                "physical_register": 21,
                                            }
                                        ),
                                    ),
                                }
                            ),
                        ),
                    }
                ),
            ),
            "pcode_occurrences": (
                MappingProxyType(
                    {
                        "pcode_id": "pc-0",
                        "operand_index": 1,
                        "operand_lineage_id": "ol-1",
                        "class_id": 0,
                        "virtual_kind": "r",
                        "virtual": virtual,
                        "ig_id": virtual,
                        "allocated_physical": 21,
                        "runtime_address": 0x6000,
                        "confidence": "observed",
                    }
                ),
            ),
            "pcode_operand_lineage_events": (
                MappingProxyType(
                    {
                        "mutation_kind": "clone",
                        "inputs": (
                            MappingProxyType(
                                {
                                    "pcode_id": "pc-parent",
                                    "operands": (
                                        MappingProxyType(
                                            {
                                                "operand_lineage_id": "ol-parent",
                                                "operand_index": 1,
                                            }
                                        ),
                                    ),
                                }
                            ),
                        ),
                        "outputs": (
                            MappingProxyType(
                                {
                                    "pcode_id": "pc-0",
                                    "operands": (
                                        MappingProxyType(
                                            {
                                                "operand_lineage_id": "ol-1",
                                                "operand_index": 1,
                                                "parent_lineage_ids": ("ol-parent",),
                                            }
                                        ),
                                    ),
                                }
                            ),
                        ),
                    }
                ),
            ),
        }
    )
    return PCodeLineageValidation(
        normalized,
        MappingProxyType(
            {
                (0x234, "use:0"): AnchorVirtualBinding(
                    0x234,
                    "use:0",
                    "pc-0",
                    "ol-1",
                    0,
                    virtual,
                    21,
                    "derived-unique",
                )
            }
        ),
        frozenset({"pcode-to-code-range"}),
        (),
    )


def _adapter_input(
    *,
    capabilities: frozenset[str] = ALL_CAPABILITIES,
    capture_run_id: str = "a" * 64,
    compile_id: str = "compile-a",
    function: str = "fn",
    virtual: int = 66,
    object_result: ObjectBindingValidation | None = None,
) -> ObjectBindingAdapterInput:
    return ObjectBindingAdapterInput(
        compile_id=compile_id,
        function=function,
        artifact_sha256="b" * 64,
        capture_run_id=capture_run_id,
        artifact_size=4096,
        capabilities=capabilities,
        object_validation=object_result or _object_result(capture_run_id=capture_run_id, virtual=virtual),
        pcode_validation=_pcode_result(virtual=virtual),
    )


def test_future_complete_emitter_builds_every_exact_same_run_edge() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())

    assert {
        "assembly-anchor-emitted-by-pcode",
        "pcode-operand-lineage",
        "pcode-operand-uses-virtual",
        "object-materializes-virtual",
        "maps-to-allocator-node",
        "object-has-stack-home",
    } <= {edge.kind for edge in evidence.edges}
    assert all(edge.confidence is not Confidence.HEURISTIC for edge in evidence.edges)
    assert all(edge.provenance.parser == "mwcc-retro-backend-trace.v2" for edge in evidence.edges)
    assert proof_complete(evidence)


@pytest.mark.parametrize(
    ("removed", "forbidden"),
    [
        ("pcode-to-code-range", "assembly-anchor-emitted-by-pcode"),
        ("pcode-to-code-range", "pcode-operand-uses-virtual"),
        ("object-to-virtual", "object-materializes-virtual"),
        ("object-to-virtual", "maps-to-allocator-node"),
        ("object-to-frame", "object-has-stack-home"),
    ],
)
def test_each_edge_family_requires_its_exact_verified_capability(
    removed: str,
    forbidden: str,
) -> None:
    evidence = emit_object_binding_evidence(_adapter_input(capabilities=ALL_CAPABILITIES - {removed}))

    assert forbidden not in {edge.kind for edge in evidence.edges}
    assert not proof_complete(evidence)


def test_runtime_pointer_changes_never_change_stable_record_ids() -> None:
    first = emit_object_binding_evidence(_adapter_input())
    original = _object_result().normalized
    changed = {
        "capture_run_id": original["capture_run_id"],
        "objects": (dict(original["objects"][0]),),
        "virtual_bindings": (dict(original["virtual_bindings"][0]),),
        "frame_bindings": (dict(original["frame_bindings"][0]),),
        "source_bindings": (),
        "source_capture": None,
    }
    changed["objects"][0]["runtime_address"] = 0xDEADBEEF
    changed["virtual_bindings"][0]["ignode_runtime_address"] = 0xDEAD0000
    changed["frame_bindings"][0]["list_node_runtime_address"] = 0xBEEF0000
    second = emit_object_binding_evidence(
        _adapter_input(
            object_result=ObjectBindingValidation(
                MappingProxyType(changed),
                frozenset({"compiler-object-bindings"}),
                (),
            )
        )
    )

    assert {node.record_id for node in first.nodes} == {node.record_id for node in second.nodes}
    assert {edge.record_id for edge in first.edges} == {edge.record_id for edge in second.edges}


def test_all_lineage_alternatives_are_preserved_without_debug_dll_virtuals() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())

    lineage_nodes = [node for node in evidence.nodes if node.kind == "pcode-operand"]
    assert {node.attributes["operand_lineage_id"] for node in lineage_nodes} == {
        "ol-1",
        "ol-parent",
    }
    assert not any(record.provenance.parser == "mwcc-debug-pcdump.v1" for record in (*evidence.nodes, *evidence.edges))


def test_same_numeric_pointer_from_another_capture_run_is_rejected() -> None:
    with pytest.raises(BundleInputError, match="capture run"):
        emit_object_binding_evidence(
            _adapter_input(
                capture_run_id="c" * 64,
                object_result=_object_result(capture_run_id="d" * 64),
            )
        )


def test_phase1_empty_source_fields_never_emit_source_ownership() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())

    assert "object-to-source" not in {edge.kind for edge in evidence.edges}
    assert bilateral_source_object_records((evidence, evidence)) == ()


def test_owner_resolution_uses_semantic_role_tuple_and_keeps_runs_local() -> None:
    left = emit_object_binding_evidence(_adapter_input())
    right = emit_object_binding_evidence(
        _adapter_input(
            compile_id="compile-b",
            capture_run_id="b" * 64,
            virtual=91,
        )
    )
    role = BackendOwnerRoleTuple("use:0", "gpr", "row-home", 4, "locals")

    candidates = resolve_backend_owner_candidates((left, right), role)
    comparisons = backend_owner_correspondences("analysis", candidates)

    assert len(candidates) == 1
    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.relation_kind == "backend-owner-corresponds-to"
    assert comparison.attributes["role_tuple"] == (
        "use:0",
        "gpr",
        "row-home",
        4,
        "locals",
    )
    assert "virtual" not in comparison.attributes
    assert "runtime_address" not in comparison.attributes
    assert candidates[0].left.capture_run_id != candidates[0].right.capture_run_id


def test_matching_cross_run_virtual_number_cannot_replace_semantic_role() -> None:
    left = emit_object_binding_evidence(_adapter_input())
    wrong_role = emit_object_binding_evidence(
        _adapter_input(
            compile_id="compile-b",
            capture_run_id="b" * 64,
            virtual=66,
            object_result=_object_result(
                capture_run_id="b" * 64,
                virtual=66,
                semantic_stack_role="different-home",
            ),
        )
    )

    assert (
        resolve_backend_owner_candidates(
            (left, wrong_role),
            BackendOwnerRoleTuple("use:0", "gpr", "row-home", 4, "locals"),
        )
        == ()
    )


def test_proof_complete_requires_one_connected_owner_path() -> None:
    first = emit_object_binding_evidence(_adapter_input())
    unrelated = emit_object_binding_evidence(_adapter_input(virtual=91))
    disconnected = ObjectBindingEvidence(
        tuple({node.record_id: node for node in (*first.nodes, *unrelated.nodes)}.values()),
        tuple(edge for edge in first.edges if edge.kind != "object-materializes-virtual")
        + tuple(edge for edge in unrelated.edges if edge.kind == "object-materializes-virtual"),
        ALL_CAPABILITIES,
        first.capture_run_id,
        None,
    )

    assert not proof_complete(disconnected)


def test_build_role_comparisons_integrates_unique_semantic_backend_owner() -> None:
    left = emit_object_binding_evidence(_adapter_input())
    right = emit_object_binding_evidence(
        _adapter_input(
            compile_id="compile-b",
            capture_run_id="b" * 64,
            virtual=91,
        )
    )
    graphs = (
        SimpleNamespace(
            bundle=SimpleNamespace(label="left", compile_id="compile-a"),
            backend=SimpleNamespace(object_bindings=left),
        ),
        SimpleNamespace(
            bundle=SimpleNamespace(label="right", compile_id="compile-b"),
            backend=SimpleNamespace(object_bindings=right),
        ),
    )
    alignment = AnchorAlignment(
        analysis_id="analysis",
        retail_offset=0x234,
        operand_roles=(OperandRole("use:0", "use", 0, "r", 21),),
        by_operand={},
        comparisons=(),
        abstentions=(),
    )

    comparisons = build_role_comparisons(alignment, graphs)

    assert len(comparisons) == 1
    assert comparisons[0].relation_kind == "backend-owner-corresponds-to"


def test_future_verified_anchor_path_replaces_ambiguous_v1_backend_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.mwcc_debug.causal_diff.alignment.role_descriptor.build_descriptors",
        lambda compile_, class_id: compile_[class_id],
    )
    graphs = []
    for label, capture_run_id, virtual in (
        ("direct", "a" * 64, 66),
        ("paired", "b" * 64, 91),
    ):
        graph = _graph(label, missing_use=True)
        evidence = emit_object_binding_evidence(
            _adapter_input(
                compile_id=graph.bundle.compile_id,
                function="fn_test",
                capture_run_id=capture_run_id,
                virtual=virtual,
            )
        )
        graph.store.add_nodes(evidence.nodes)
        graph.store.add_edges(evidence.edges)
        graphs.append(
            replace(
                graph,
                backend=replace(graph.backend, object_bindings=evidence),
            )
        )

    alignment = align_anchor(tuple(graphs), 0x234, ())

    assert "use:0" in alignment.by_operand
    assert not any(item.operand_key == "use:0" for item in alignment.abstentions)


def test_effect_traversal_reaches_stack_only_over_exact_owner_edges() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())
    store = InMemoryEvidenceStore()
    store.add_nodes(evidence.nodes)
    store.add_edges(evidence.edges)
    graph = SimpleNamespace(store=store)
    allocator = next(node for node in evidence.nodes if node.kind == "allocator-node")
    stack = next(node for node in evidence.nodes if node.kind == "stack-object")

    reachable, traversed_edges = _reachable_records(graph, (allocator.record_id,))

    assert stack.record_id in reachable
    assert {
        edge.record_id
        for edge in evidence.edges
        if edge.kind
        in {
            "maps-to-allocator-node",
            "object-materializes-virtual",
            "object-has-stack-home",
        }
    } <= traversed_edges


def test_inference_traverses_the_same_exact_owner_path_vocabulary() -> None:
    assert {
        "assembly-anchor-emitted-by-pcode",
        "pcode-operand-lineage",
        "pcode-operand-uses-virtual",
        "object-materializes-virtual",
        "object-has-stack-home",
    } <= _PATH_EDGE_KINDS


def test_report_names_current_verified_backend_owner_path_incompleteness() -> None:
    current = ObjectBindingEvidence(
        (),
        (),
        frozenset({"compiler-object-bindings", "pcode-to-code-range"}),
        "a" * 64,
        "backend-owner-path-incomplete",
    )
    graphs = tuple(
        SimpleNamespace(
            bundle=SimpleNamespace(
                label=label,
                compile_id=f"compile-{label}",
                manifest=SimpleNamespace(function="fn"),
            ),
            backend=SimpleNamespace(object_bindings=current),
            store=InMemoryEvidenceStore(),
            warnings=(),
        )
        for label in ("a", "b")
    )
    effects = DerivedEffects(
        (),
        (),
        (),
        (
            EffectAbstention(
                "use:0",
                AbstentionReason.MISSING_BACKEND_ROLE,
            ),
        ),
    )

    report = build_report(graphs, effects, ())

    assert "backend-owner-path-incomplete" in report.missing_evidence
    assert all("preserve-allocation" not in verdict.recommendation for verdict in report.verdicts)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _compile_id(*, function: str, source_digest: str, environment_digest: str) -> str:
    return _sha256(
        canonical_bytes(
            {
                "function": function,
                "compiler": "mwcc_233_163n",
                "target_build": "GALE01",
                "flags_digest": "f" * 64,
                "environment_digest": environment_digest,
                "source_digest": source_digest,
            }
        )
    )


def _verified_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.c"
    source.write_text("void target(void) {}\n", encoding="utf-8")
    source_digest = _sha256(source.read_bytes())
    kwargs = _v2_assembly_kwargs(tmp_path)
    kwargs["source_sha256"] = source_digest
    assembly = __import__(
        "tools.mwcc_retro.backend_trace_assembler",
        fromlist=["assemble_candidate_trace_v2"],
    ).assemble_candidate_trace_v2(**kwargs)
    backend = tmp_path / "backend.json"
    backend.write_text(json.dumps(assembly.payload), encoding="utf-8")
    checkdiff = tmp_path / "checkdiff.json"
    checkdiff.write_text("{}\n", encoding="utf-8")
    inspector = tmp_path / "inspector.txt"
    inspector.write_text("inspector\n", encoding="utf-8")
    candidate = Path(kwargs["candidate_object"])
    identity = assembly.payload["functions"][0]["object_bindings"]["capture_identity"]
    environment_digest = str(kwargs["environment_digest"])
    manifest = {
        "schema_version": "causal-frontier-bundle.v2",
        "label": "paired",
        "function": "target",
        "compile": {
            "id": _compile_id(
                function="target",
                source_digest=source_digest,
                environment_digest=environment_digest,
            ),
            "compiler": "mwcc_233_163n",
            "target_build": "GALE01",
            "flags_digest": "f" * 64,
            "environment_digest": environment_digest,
            "source_digest": source_digest,
            "expected_assembly_digest": "e" * 64,
        },
        "artifacts": {
            "source": {"path": source.name, "sha256": source_digest},
            "checkdiff": {
                "path": checkdiff.name,
                "sha256": _sha256(checkdiff.read_bytes()),
            },
            "backend": [
                {
                    "path": backend.name,
                    "sha256": _sha256(backend.read_bytes()),
                    "format": "backend-trace.v2",
                    "capabilities": sorted(assembly.capabilities),
                    "capture_identity_sha256": _sha256(canonical_bytes(identity)),
                    "compiler_executable_sha256": identity["compiler_executable_sha256"],
                    "mwcc_command_sha256": identity["mwcc_command_sha256"],
                    "environment_digest": identity["environment_digest"],
                    "candidate_object_sha256": identity["candidate_object_sha256"],
                }
            ],
            "inspector": {
                "path": inspector.name,
                "sha256": _sha256(inspector.read_bytes()),
            },
            "candidate_object": {
                "path": candidate.name,
                "sha256": _sha256(candidate.read_bytes()),
            },
        },
        "producer_versions": {"mwcc_retro": "mwcc-retro-backend-trace.v2"},
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr("tools.mwcc_retro.struct_map.load_gc125n_struct_map", _trusted_table)
    return load_bundle(manifest_path, cli_label="paired", function="target")


def test_genuine_current_verified_bundle_abstains_before_backend_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = adapt_object_bindings(_verified_bundle(tmp_path, monkeypatch))

    assert evidence.capabilities == frozenset({"compiler-object-bindings", "pcode-to-code-range"})
    assert {
        "object-materializes-virtual",
        "object-has-stack-home",
    }.isdisjoint(edge.kind for edge in evidence.edges)
    assert not proof_complete(evidence)
    assert evidence.abstention_reason == "backend-owner-path-incomplete"
    assert derive_backend_frame_recommendation(evidence) is None


def test_backend_adapter_merges_only_genuinely_reverified_v2_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _verified_bundle(tmp_path, monkeypatch)

    backend = adapt_backends(bundle)

    assert backend.object_bindings is not None
    assert backend.object_bindings.abstention_reason == ("backend-owner-path-incomplete")
    assert {
        "object-materializes-virtual",
        "object-has-stack-home",
    }.isdisjoint(edge.kind for edge in backend.result.edges)


def test_adapter_rejects_hostile_trace_multiple_v2_inputs_and_missing_candidate(
    tmp_path: Path,
) -> None:
    hostile = tmp_path / "hostile.json"
    hostile.write_text("[]", encoding="utf-8")
    candidate = tmp_path / "candidate.o"
    candidate.write_bytes(b"object")
    base = SimpleNamespace(
        compile_id="compile",
        manifest=SimpleNamespace(function="fn"),
        candidate_object_path=candidate,
        backend_paths=lambda _format: (hostile,),
    )
    with pytest.raises(BundleInputError, match="backend trace v2"):
        adapt_object_bindings(base)

    multiple = SimpleNamespace(**{**base.__dict__, "backend_paths": lambda _format: (hostile, hostile)})
    with pytest.raises(BundleInputError, match="exactly one"):
        adapt_object_bindings(multiple)

    missing = SimpleNamespace(**{**base.__dict__, "candidate_object_path": None})
    with pytest.raises(BundleInputError, match="candidate object"):
        adapt_object_bindings(missing)
