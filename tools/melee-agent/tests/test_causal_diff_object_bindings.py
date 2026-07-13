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
    _candidate_is_uniquely_aligned,
    _verified_retail_local_role,
    align_anchor,
    backend_owner_correspondences,
    build_role_comparisons,
    resolve_backend_owner_candidates,
)
from src.mwcc_debug.causal_diff.backend_adapter import adapt_backends
from src.mwcc_debug.causal_diff.bundles import BundleInputError, load_bundle
from src.mwcc_debug.causal_diff.canonical import canonical_bytes
from src.mwcc_debug.causal_diff.differ import diff_frontiers
from src.mwcc_debug.causal_diff.effects import DerivedEffects, _reachable_records, derive_effects
from src.mwcc_debug.causal_diff.inference import (
    _PATH_EDGE_KINDS,
    VerdictStatus,
    _all_simple_paths,
    build_report,
)
from src.mwcc_debug.causal_diff.models import (
    BackendArtifactRef,
    Confidence,
    EvidenceEdge,
)
from src.mwcc_debug.causal_diff.object_binding_adapter import (
    ObjectBindingAdapterInput,
    ObjectBindingEvidence,
    adapt_object_bindings,
    bilateral_source_object_records,
    derive_backend_frame_recommendation,
    emit_object_binding_evidence,
    exact_owner_path_record,
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
    final_r1_offset: int = 0x44,
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
                            "stage_snapshots": (
                                MappingProxyType(
                                    {
                                        "stage": "colorgraph_return",
                                        "lifecycle_sequence_at_capture": 1,
                                        "runtime_address": 0x1000,
                                        "allocation_generation": 1,
                                    }
                                ),
                                MappingProxyType(
                                    {
                                        "stage": "final_scheduler",
                                        "lifecycle_sequence_at_capture": 2,
                                        "runtime_address": 0x1000,
                                        "allocation_generation": 1,
                                    }
                                ),
                            ),
                            "cross_stage_identity_confidence": "derived-unique",
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
                            "final_r1_offset": final_r1_offset,
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


def _pcode_result(
    *,
    virtual: int = 66,
    physical_register: int = 21,
    parent_lineage_ids: tuple[str, ...] = ("ol-parent",),
) -> PCodeLineageValidation:
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
                                                "physical_register": physical_register,
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
                        "allocated_physical": physical_register,
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
                                    "operands": tuple(
                                        MappingProxyType(
                                            {
                                                "operand_lineage_id": parent_id,
                                                "operand_index": index,
                                            }
                                        )
                                        for index, parent_id in enumerate(
                                            parent_lineage_ids,
                                            start=1,
                                        )
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
                                                "parent_lineage_ids": parent_lineage_ids,
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
                    physical_register,
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
    physical_register: int = 21,
    object_result: ObjectBindingValidation | None = None,
    pcode_result: PCodeLineageValidation | None = None,
) -> ObjectBindingAdapterInput:
    return ObjectBindingAdapterInput(
        compile_id=compile_id,
        function=function,
        artifact_sha256="b" * 64,
        capture_run_id=capture_run_id,
        artifact_size=4096,
        capabilities=capabilities,
        object_validation=object_result or _object_result(capture_run_id=capture_run_id, virtual=virtual),
        pcode_validation=pcode_result
        or _pcode_result(
            virtual=virtual,
            physical_register=physical_register,
        ),
        instrumentation_identity=(
            "1" * 64,
            "proof-test",
            "2" * 64,
            "mwcc-retro-lifetime-proof.v1",
        ),
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


def test_zero_capabilities_emit_no_object_binding_records() -> None:
    evidence = emit_object_binding_evidence(_adapter_input(capabilities=frozenset()))

    assert evidence.nodes == ()
    assert evidence.edges == ()


def test_emitter_preserves_confidence_and_exact_support_record_provenance() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())
    support_records = tuple(node for node in evidence.nodes if node.kind == "backend-support-record")
    support_nodes = {
        kind: tuple(node for node in support_records if node.attributes.get("support_kind") == kind)
        for kind in {node.attributes.get("support_kind") for node in support_records}
    }

    assert {
        "object-stage-snapshot",
        "pcode-generation",
        "pcode-code-range",
        "pcode-emission",
        "pcode-rewrite",
        "pcode-lineage-event",
        "object-virtual-binding",
        "object-frame-binding",
    } <= set(support_nodes)
    compiler_object = next(node for node in evidence.nodes if node.kind == "compiler-object")
    assert compiler_object.confidence is Confidence.DERIVED_UNIQUE
    assert {node.record_id for node in support_nodes["object-stage-snapshot"]} & set(
        compiler_object.provenance.input_record_ids
    )

    expected_support = {
        "assembly-anchor-emitted-by-pcode": {
            "pcode-code-range",
            "pcode-emission",
            "pcode-generation",
        },
        "pcode-operand-lineage": {"pcode-emission", "pcode-lineage-event"},
        "pcode-operand-uses-virtual": {"pcode-rewrite"},
        "object-materializes-virtual": {"object-virtual-binding"},
        "maps-to-allocator-node": {"object-virtual-binding"},
        "object-has-stack-home": {"object-frame-binding"},
    }
    support_kind_by_id = {node.record_id: node.attributes.get("support_kind") for node in support_records}
    for edge_kind, required_support in expected_support.items():
        edge = next(edge for edge in evidence.edges if edge.kind == edge_kind)
        cited = {
            support_kind_by_id[record_id]
            for record_id in edge.provenance.input_record_ids
            if record_id in support_kind_by_id
        }
        assert required_support <= cited


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
    assert comparison.attributes["left_semantic_state"] == comparison.attributes["right_semantic_state"]
    assert set(comparison.attributes["left_semantic_state"]) == {
        "role_tuple",
        "assigned_physical_register",
        "stack_offset",
        "stack_size",
    }


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
        None,
    )

    assert not proof_complete(disconnected)


def test_exact_owner_predicate_rejects_unregistered_record_with_known_id() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())
    registered = next(edge for edge in evidence.edges if edge.kind == "maps-to-allocator-node")
    unregistered = replace(
        registered,
        attributes=MappingProxyType({**registered.attributes, "unregistered-snapshot": True}),
    )

    assert unregistered.record_id == registered.record_id
    assert not exact_owner_path_record(evidence, unregistered)


@pytest.mark.parametrize(
    "poison_support",
    (
        lambda support: replace(
            support,
            provenance=replace(
                support.provenance,
                parser="mwcc-debug-pcdump.v1",
            ),
        ),
        lambda support: replace(
            support,
            provenance=replace(
                support.provenance,
                artifact_sha256="c" * 64,
            ),
        ),
        lambda support: replace(
            support,
            producer_confidence=Confidence.HEURISTIC,
        ),
        lambda support: replace(
            support,
            attributes=MappingProxyType(
                {
                    **support.attributes,
                    "verified_capability": "pcode-to-code-range",
                }
            ),
        ),
        lambda support: replace(
            support,
            provenance=replace(
                support.provenance,
                input_record_ids=("unregistered-input",),
            ),
        ),
    ),
    ids=("parser", "artifact", "confidence", "capability", "provenance"),
)
def test_poisoned_required_support_invalidates_dependent_owner_path(
    poison_support,
) -> None:
    evidence = emit_object_binding_evidence(_adapter_input())
    support = next(
        node
        for node in evidence.nodes
        if node.kind == "backend-support-record" and node.attributes.get("support_kind") == "object-frame-binding"
    )
    poisoned_support = poison_support(support)
    poisoned = replace(
        evidence,
        nodes=tuple(poisoned_support if node.record_id == support.record_id else node for node in evidence.nodes),
    )
    dependent = next(edge for edge in poisoned.edges if edge.kind == "object-has-stack-home")

    assert support.record_id in dependent.provenance.input_record_ids
    assert not exact_owner_path_record(poisoned, dependent)
    assert not proof_complete(poisoned)


def test_semantically_foreign_support_cannot_be_cited_as_owner_proof() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())
    support = next(
        node
        for node in evidence.nodes
        if node.kind == "backend-support-record" and node.attributes.get("support_kind") == "object-frame-binding"
    )
    poisoned_support = replace(
        support,
        attributes=MappingProxyType({**support.attributes, "object_id": "foreign-object"}),
    )
    poisoned = replace(
        evidence,
        nodes=tuple(poisoned_support if node.record_id == support.record_id else node for node in evidence.nodes),
    )
    dependent = next(edge for edge in poisoned.edges if edge.kind == "object-has-stack-home")

    assert not exact_owner_path_record(poisoned, dependent)
    assert not proof_complete(poisoned)


def _poison_typed_support(
    evidence: ObjectBindingEvidence,
    support_kind: str,
    mutate,
    *,
    support_filter=lambda _attributes: True,
) -> tuple[ObjectBindingEvidence, tuple[object, ...]]:
    support = next(
        node
        for node in evidence.nodes
        if node.kind == "backend-support-record"
        and node.attributes.get("support_kind") == support_kind
        and support_filter(node.attributes)
    )
    poisoned_support = replace(
        support,
        attributes=MappingProxyType(mutate(dict(support.attributes))),
    )
    poisoned = replace(
        evidence,
        nodes=tuple(poisoned_support if node.record_id == support.record_id else node for node in evidence.nodes),
    )
    dependents = tuple(
        record
        for record in (*poisoned.nodes, *poisoned.edges)
        if record.kind != "backend-support-record" and support.record_id in record.provenance.input_record_ids
    )
    return poisoned, dependents


@pytest.mark.parametrize(
    ("support_kind", "support_filter", "mutate"),
    (
        (
            "object-stage-snapshot",
            lambda _attributes: True,
            lambda attributes: {**attributes, "stage": "foreign-stage"},
        ),
        (
            "pcode-generation",
            lambda _attributes: True,
            lambda attributes: {**attributes, "allocation_generation": 99},
        ),
        (
            "pcode-code-range",
            lambda _attributes: True,
            lambda attributes: {
                **attributes,
                "start": 0x230,
                "end_exclusive": 0x240,
            },
        ),
        (
            "pcode-emission",
            lambda _attributes: True,
            lambda attributes: {**attributes, "code_offset": 0x238},
        ),
        (
            "pcode-rewrite",
            lambda _attributes: True,
            lambda attributes: {**attributes, "allocation_generation": 99},
        ),
        (
            "pcode-lineage-event",
            lambda attributes: attributes.get("event_kind") == "emission-lineage",
            lambda attributes: {**attributes, "event_kind": "foreign-relation"},
        ),
        (
            "pcode-lineage-event",
            lambda attributes: attributes.get("side") == "outputs" and bool(attributes.get("parent_lineage_ids")),
            lambda attributes: {
                **attributes,
                "parent_lineage_ids": ("foreign-parent",),
            },
        ),
        (
            "object-virtual-binding",
            lambda _attributes: True,
            lambda attributes: {**attributes, "allocation_generation": 99},
        ),
        (
            "object-frame-binding",
            lambda _attributes: True,
            lambda attributes: {**attributes, "size": 99},
        ),
    ),
    ids=(
        "snapshot-stage",
        "pcode-generation",
        "range-bounds",
        "emission-offset",
        "rewrite-generation",
        "lineage-relation",
        "lineage-parent",
        "object-generation",
        "frame-size",
    ),
)
def test_foreign_typed_support_semantics_invalidate_owner_proof(
    support_kind,
    support_filter,
    mutate,
) -> None:
    poisoned, dependents = _poison_typed_support(
        emit_object_binding_evidence(_adapter_input()),
        support_kind,
        mutate,
        support_filter=support_filter,
    )

    assert dependents
    assert all(not exact_owner_path_record(poisoned, dependent) for dependent in dependents)
    assert not proof_complete(poisoned)


def test_every_support_kind_has_closed_typed_semantics_and_valid_dependents() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())
    base = {"capture_run_id", "verified_capability", "support_kind"}
    expected_shapes = {
        "object-stage-snapshot": (
            base
            | {
                "object_id",
                "stage",
                "allocation_generation",
                "lifecycle_sequence_at_capture",
            },
        ),
        "pcode-generation": (base | {"pcode_id", "allocation_generation"},),
        "pcode-code-range": (base | {"pcode_id", "allocation_generation", "start", "end_exclusive"},),
        "pcode-emission": (
            base
            | {
                "pcode_id",
                "allocation_generation",
                "code_offset",
                "machine_operand_key",
                "operand_lineage_id",
                "physical_register",
            },
        ),
        "pcode-rewrite": (
            base
            | {
                "pcode_id",
                "allocation_generation",
                "operand_lineage_id",
                "class_id",
                "virtual",
                "allocated_physical",
            },
        ),
        "pcode-lineage-event": (
            base
            | {
                "pcode_id",
                "allocation_generation",
                "code_offset",
                "operand_lineage_id",
                "event_kind",
            },
            base
            | {
                "pcode_id",
                "allocation_generation",
                "event_index",
                "side",
                "mutation_kind",
                "operand_lineage_id",
                "parent_lineage_ids",
            },
        ),
        "object-virtual-binding": (
            base
            | {
                "object_id",
                "allocation_generation",
                "class_id",
                "virtual",
                "ig_id",
            },
        ),
        "object-frame-binding": (
            base
            | {
                "object_id",
                "allocation_generation",
                "area",
                "semantic_stack_role",
                "final_r1_offset",
                "size",
            },
        ),
    }
    support_by_id = {node.record_id: node for node in evidence.nodes if node.kind == "backend-support-record"}
    accepted_kinds: set[str] = set()
    for support in support_by_id.values():
        support_kind = str(support.attributes["support_kind"])
        assert set(support.attributes) in expected_shapes[support_kind]
        dependents = tuple(
            record
            for record in (*evidence.nodes, *evidence.edges)
            if record.kind != "backend-support-record" and support.record_id in record.provenance.input_record_ids
        )
        assert dependents
        assert all(exact_owner_path_record(evidence, dependent) for dependent in dependents)
        accepted_kinds.add(support_kind)

    assert accepted_kinds == set(expected_shapes)


def _two_parent_lineage_evidence() -> ObjectBindingEvidence:
    parents = ("ol-parent-a", "ol-parent-b")
    return emit_object_binding_evidence(
        _adapter_input(
            pcode_result=_pcode_result(parent_lineage_ids=parents),
        )
    )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda attributes: {
            **attributes,
            "parent_lineage_ids": ("ol-parent-a",),
        },
        lambda attributes: {
            **attributes,
            "parent_lineage_ids": ("foreign-a", "foreign-b"),
        },
        lambda attributes: {
            **attributes,
            "parent_lineage_ids": (
                "ol-parent-a",
                "ol-parent-b",
                "foreign-parent",
            ),
        },
        lambda attributes: {
            **attributes,
            "parent_lineage_ids": (
                "ol-parent-a",
                "ol-parent-b",
                "ol-parent-b",
            ),
        },
        lambda attributes: {
            **attributes,
            "parent_lineage_ids": ("ol-parent-b", "ol-parent-a"),
        },
        lambda attributes: {
            **attributes,
            "event_index": attributes["event_index"] + 1,
        },
    ),
    ids=("subset", "replacement", "superset", "duplicate", "ordering", "event-index"),
)
def test_mutation_lineage_requires_exact_canonical_parent_topology(mutate) -> None:
    evidence = _two_parent_lineage_evidence()
    poisoned, dependents = _poison_typed_support(
        evidence,
        "pcode-lineage-event",
        mutate,
        support_filter=lambda attributes: attributes.get("side") == "outputs",
    )

    assert dependents
    assert all(not exact_owner_path_record(poisoned, dependent) for dependent in dependents)
    assert not proof_complete(poisoned)


def test_mutation_lineage_accepts_exact_canonical_parent_topology() -> None:
    evidence = _two_parent_lineage_evidence()
    support = next(
        node
        for node in evidence.nodes
        if node.kind == "backend-support-record"
        and node.attributes.get("support_kind") == "pcode-lineage-event"
        and node.attributes.get("side") == "outputs"
    )
    dependents = tuple(
        record
        for record in (*evidence.nodes, *evidence.edges)
        if support.record_id in record.provenance.input_record_ids
    )

    assert support.attributes["parent_lineage_ids"] == (
        "ol-parent-a",
        "ol-parent-b",
    )
    assert dependents
    assert all(exact_owner_path_record(evidence, dependent) for dependent in dependents)
    assert proof_complete(evidence)


def test_assigned_physical_is_grounded_by_validated_decode_and_allocator_origin() -> None:
    evidence = emit_object_binding_evidence(_adapter_input(physical_register=21))
    anchor = next(node for node in evidence.nodes if node.kind == "assembly-operand-anchor")
    virtual = next(node for node in evidence.nodes if node.kind == "retail-virtual-register")
    allocator = next(node for node in evidence.nodes if node.kind == "allocator-node")
    mapping = next(edge for edge in evidence.edges if edge.kind == "maps-to-allocator-node")
    emission_support = next(
        node
        for node in evidence.nodes
        if node.kind == "backend-support-record" and node.attributes.get("support_kind") == "pcode-emission"
    )
    origin_support = next(
        node
        for node in evidence.nodes
        if node.kind == "backend-support-record" and node.attributes.get("support_kind") == "pcode-rewrite"
    )

    assert {
        anchor.attributes["physical_register"],
        virtual.attributes["physical_register"],
        allocator.attributes["assigned_phys"],
        mapping.attributes["assigned_phys"],
        emission_support.attributes["physical_register"],
        origin_support.attributes["allocated_physical"],
    } == {21}
    assert origin_support.record_id in allocator.provenance.input_record_ids
    assert origin_support.record_id in mapping.provenance.input_record_ids
    assert proof_complete(evidence)


@pytest.mark.parametrize(
    ("record_kind", "support_kind", "attribute"),
    (
        ("allocator-node", None, "assigned_phys"),
        ("retail-virtual-register", None, "physical_register"),
        ("assembly-operand-anchor", None, "physical_register"),
        ("backend-support-record", "pcode-emission", "physical_register"),
        ("backend-support-record", "pcode-rewrite", "allocated_physical"),
        ("maps-to-allocator-node", None, "assigned_phys"),
    ),
    ids=(
        "allocator",
        "virtual",
        "anchor",
        "emission-support",
        "allocator-origin",
        "mapping-edge",
    ),
)
def test_foreign_assigned_physical_invalidates_owner_proof(
    record_kind,
    support_kind,
    attribute,
) -> None:
    evidence = emit_object_binding_evidence(_adapter_input(physical_register=21))

    def poison(record):
        if record.kind != record_kind or (
            support_kind is not None and record.attributes.get("support_kind") != support_kind
        ):
            return record
        return replace(
            record,
            attributes=MappingProxyType({**record.attributes, attribute: 19}),
        )

    poisoned = replace(
        evidence,
        nodes=tuple(poison(node) for node in evidence.nodes),
        edges=tuple(poison(edge) for edge in evidence.edges),
    )

    assert not proof_complete(poisoned)


def _replace_evidence_record(
    evidence: ObjectBindingEvidence,
    kind: str,
    mutate,
) -> ObjectBindingEvidence:
    nodes = tuple(mutate(node) if node.kind == kind else node for node in evidence.nodes)
    edges = tuple(mutate(edge) if edge.kind == kind else edge for edge in evidence.edges)
    return replace(evidence, nodes=nodes, edges=edges)


@pytest.mark.parametrize(
    "poison",
    (
        lambda evidence: replace(
            evidence,
            capabilities=evidence.capabilities - {"object-to-frame"},
        ),
        lambda evidence: _replace_evidence_record(
            evidence,
            "pcode-operand-lineage",
            lambda edge: replace(
                edge,
                provenance=replace(edge.provenance, parser="mwcc-debug-pcdump.v1"),
            ),
        ),
        lambda evidence: _replace_evidence_record(
            evidence,
            "compiler-object",
            lambda node: replace(
                node,
                provenance=replace(node.provenance, parser="mwcc-debug-pcdump.v1"),
            ),
        ),
        lambda evidence: _replace_evidence_record(
            evidence,
            "retail-pcode",
            lambda node: replace(node, compile_id="foreign-compile"),
        ),
        lambda evidence: _replace_evidence_record(
            evidence,
            "allocator-node",
            lambda node: replace(
                node,
                attributes=MappingProxyType({**node.attributes, "capture_run_id": "f" * 64}),
            ),
        ),
        lambda evidence: _replace_evidence_record(
            evidence,
            "object-has-stack-home",
            lambda edge: replace(edge, source_id=edge.target_id, target_id=edge.source_id),
        ),
        lambda evidence: _replace_evidence_record(
            evidence,
            "maps-to-allocator-node",
            lambda edge: replace(
                edge,
                provenance=replace(edge.provenance, input_record_ids=()),
            ),
        ),
        lambda evidence: _replace_evidence_record(
            evidence,
            "stack-object",
            lambda node: replace(
                node,
                producer_confidence=Confidence.HEURISTIC,
                confidence=Confidence.HEURISTIC,
            ),
        ),
    ),
)
def test_owner_resolution_rejects_every_poisoned_exact_path_record(poison) -> None:
    left = poison(emit_object_binding_evidence(_adapter_input()))
    right = emit_object_binding_evidence(
        _adapter_input(
            compile_id="compile-b",
            capture_run_id="b" * 64,
            virtual=91,
        )
    )
    role = BackendOwnerRoleTuple("use:0", "gpr", "row-home", 4, "locals")

    assert not proof_complete(left)
    assert resolve_backend_owner_candidates((left, right), role) == ()


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


def _future_complete_owner_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    semantic_change: bool,
    ambiguous_owner: bool = False,
    mixed_owner_alternative: bool = False,
    force_owner_observed: bool = False,
):
    monkeypatch.setattr(
        "src.mwcc_debug.causal_diff.alignment.role_descriptor.build_descriptors",
        lambda compile_, class_id: compile_[class_id],
    )
    graphs = []
    for label, capture_run_id, virtual, physical, stack_start in (
        ("direct", "a" * 64, 66, 21, 36),
        (
            "paired",
            "b" * 64,
            91,
            19 if semantic_change else 21,
            32 if semantic_change else 36,
        ),
    ):
        original = _graph(label, missing_use=True)
        evidence = emit_object_binding_evidence(
            _adapter_input(
                compile_id=original.bundle.compile_id,
                function="fn_test",
                capture_run_id=capture_run_id,
                virtual=virtual,
                physical_register=physical,
                object_result=_object_result(
                    capture_run_id=capture_run_id,
                    virtual=virtual,
                    semantic_stack_role="row",
                    final_r1_offset=stack_start,
                ),
            )
        )
        if force_owner_observed:
            evidence = replace(
                evidence,
                nodes=tuple(
                    replace(
                        node,
                        producer_confidence=Confidence.OBSERVED,
                        adapter_confidence=Confidence.OBSERVED,
                        confidence=Confidence.OBSERVED,
                    )
                    for node in evidence.nodes
                ),
                edges=tuple(
                    replace(
                        edge,
                        producer_confidence=Confidence.OBSERVED,
                        adapter_confidence=Confidence.OBSERVED,
                        confidence=Confidence.OBSERVED,
                    )
                    for edge in evidence.edges
                ),
            )
        store = InMemoryEvidenceStore()
        original_nodes = tuple(
            node for node in original.store.find_nodes(original.bundle.compile_id) if node.kind != "stack-object"
        )
        original_node_ids = {node.record_id for node in original_nodes}
        original_edges = tuple(
            edge
            for edge in original.store.find_edges(original.bundle.compile_id)
            if {edge.source_id, edge.target_id} <= original_node_ids
        )
        store.add_nodes((*original_nodes, *evidence.nodes))
        store.add_edges((*original_edges, *evidence.edges))
        stack = next(node for node in evidence.nodes if node.kind == "stack-object")
        graphs.append(
            replace(
                original,
                store=store,
                backend=replace(original.backend, object_bindings=evidence),
                frame=replace(
                    original.frame,
                    result=replace(original.frame.result, nodes=(stack,), edges=()),
                    current_stack_nodes=MappingProxyType({"row": stack.record_id}),
                ),
            )
        )

    graph_pair = tuple(graphs)
    alignment = align_anchor(graph_pair, 0x234, ())
    comparisons = build_role_comparisons(alignment, graph_pair)
    if ambiguous_owner or mixed_owner_alternative:
        owner_candidates = resolve_backend_owner_candidates(
            tuple(graph.backend.object_bindings for graph in graph_pair),
            BackendOwnerRoleTuple("use:0", "gpr", "row", 4, "locals"),
        )
        assert len(owner_candidates) == 1
        ambiguous_comparisons = backend_owner_correspondences(
            alignment.analysis_id,
            (owner_candidates[0], owner_candidates[0]),
        )
        if ambiguous_owner:
            comparisons = (
                tuple(
                    comparison
                    for comparison in comparisons
                    if comparison.relation_kind != "backend-owner-corresponds-to"
                )
                + ambiguous_comparisons
            )
        else:
            comparisons = (*comparisons, ambiguous_comparisons[0])
    effects = derive_effects(alignment, graph_pair)
    effects = replace(
        effects,
        pairs=tuple(pair for pair in effects.pairs if pair.allocator.operand_key == "use:0"),
    )
    deltas = diff_frontiers(graph_pair, comparisons)
    report = build_report(graph_pair, effects, (*comparisons, *deltas))

    return deltas, report


def test_capture_local_owner_state_never_manufactures_semantic_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deltas, _report = _future_complete_owner_pipeline(
        monkeypatch,
        semantic_change=False,
    )

    assert not any(comparison.attributes.get("kind") == "compiler-object" for comparison in deltas)


def test_future_complete_owner_pipeline_reaches_mandatory_source_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deltas, report = _future_complete_owner_pipeline(
        monkeypatch,
        semantic_change=True,
    )

    owner_delta = next(
        comparison
        for comparison in deltas
        if comparison.relation_kind == "node-changed" and comparison.attributes.get("kind") == "compiler-object"
    )
    assert owner_delta
    assert set(owner_delta.attributes["left_attributes"]) == {
        "role_tuple",
        "assigned_physical_register",
        "stack_offset",
        "stack_size",
    }
    assert report.verdicts
    assert all(verdict.status is VerdictStatus.ABSTAIN for verdict in report.verdicts), [
        (verdict.status, verdict.failed_gates, verdict.rejected_alternatives) for verdict in report.verdicts
    ]
    assert all("gate-9-source-object-binding" in verdict.failed_gates for verdict in report.verdicts)
    assert "source-object-binding-missing" in report.missing_evidence


def test_semantic_owner_delta_cites_and_propagates_exact_path_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _deltas, report = _future_complete_owner_pipeline(
        monkeypatch,
        semantic_change=True,
        force_owner_observed=True,
    )
    owner_correspondence = next(
        comparison for comparison in report.comparisons if comparison.relation_kind == "backend-owner-corresponds-to"
    )
    owner_delta = next(
        comparison
        for comparison in report.comparisons
        if comparison.relation_kind == "node-changed" and comparison.attributes.get("kind") == "compiler-object"
    )

    assert owner_correspondence.confidence is Confidence.OBSERVED
    assert owner_delta.confidence is owner_correspondence.confidence
    assert {
        owner_correspondence.record_id,
        *owner_correspondence.provenance.input_record_ids,
    } <= set(owner_delta.provenance.input_record_ids)


def test_ambiguous_backend_owner_alternatives_never_become_derived_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deltas, report = _future_complete_owner_pipeline(
        monkeypatch,
        semantic_change=True,
        ambiguous_owner=True,
    )

    assert not any(comparison.attributes.get("kind") == "compiler-object" for comparison in deltas)
    assert report.verdicts
    assert all(verdict.status is VerdictStatus.ABSTAIN for verdict in report.verdicts)
    assert all("gate-6-unique-owner-chain" in verdict.failed_gates for verdict in report.verdicts)
    assert all(
        any(alternative.startswith("backend-owner-ambiguous:") for alternative in verdict.rejected_alternatives)
        for verdict in report.verdicts
    )


def test_proof_looking_owner_is_rejected_when_heuristic_alternative_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deltas, report = _future_complete_owner_pipeline(
        monkeypatch,
        semantic_change=True,
        mixed_owner_alternative=True,
    )

    assert not any(comparison.attributes.get("kind") == "compiler-object" for comparison in deltas)
    assert report.verdicts
    assert all(verdict.status is VerdictStatus.ABSTAIN for verdict in report.verdicts)
    assert all("gate-6-unique-owner-chain" in verdict.failed_gates for verdict in report.verdicts)
    assert all(
        any(alternative.startswith("backend-owner-ambiguous:") for alternative in verdict.rejected_alternatives)
        for verdict in report.verdicts
    )
    owner_comparisons = tuple(
        comparison for comparison in report.comparisons if comparison.relation_kind == "backend-owner-corresponds-to"
    )
    assert len(owner_comparisons) == 2
    assert len({comparison.record_id for comparison in owner_comparisons}) == 1
    ambiguity = next(comparison for comparison in deltas if comparison.relation_kind == "backend-owner-ambiguous")
    alternatives = ambiguity.attributes["alternatives"]
    assert len(alternatives) == 2
    assert len({alternative["alternative_id"] for alternative in alternatives}) == 2
    assert len({alternative["underlying_record_id"] for alternative in alternatives}) == 1
    assert {alternative["confidence"] for alternative in alternatives} == {
        "derived-unique",
        "heuristic",
    }
    assert all(
        {
            "alternative_id",
            "underlying_record_id",
            "confidence",
            "semantic_attributes",
            "provenance",
            "left_record_id",
            "right_record_id",
        }
        <= set(alternative)
        for alternative in alternatives
    )
    retained_ids = {
        alternative.removeprefix("alternative-owner:")
        for verdict in report.verdicts
        for alternative in verdict.rejected_alternatives
        if alternative.startswith("alternative-owner:")
    }
    assert retained_ids == {alternative["alternative_id"] for alternative in alternatives}


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


def test_verified_local_role_never_selects_poisoned_path_licensed_elsewhere() -> None:
    graph = _graph("direct", missing_use=True)
    evidence = emit_object_binding_evidence(
        _adapter_input(
            compile_id=graph.bundle.compile_id,
            function="fn_test",
        )
    )
    original = next(edge for edge in evidence.edges if edge.kind == "assembly-anchor-emitted-by-pcode")
    poisoned = replace(
        original,
        provenance=replace(original.provenance, input_record_ids=()),
    )
    clean_alternative = EvidenceEdge.create(
        compile_id=original.compile_id,
        function=original.function,
        kind=original.kind,
        source_id=original.source_id,
        target_id=original.target_id,
        occurrence_ordinal=999,
        producer_confidence=original.producer_confidence,
        adapter_confidence=original.adapter_confidence,
        provenance=original.provenance,
        input_confidences=(original.confidence,) * len(original.provenance.input_record_ids),
        attributes=original.attributes,
    )
    mixed = replace(
        evidence,
        edges=tuple(poisoned if edge.record_id == original.record_id else edge for edge in evidence.edges)
        + (clean_alternative,),
    )
    graph = replace(graph, backend=replace(graph.backend, object_bindings=mixed))
    candidate = _candidate_is_uniquely_aligned(graph, 0x234)
    assert candidate is not None

    resolution, _reason = _verified_retail_local_role(
        graph,
        candidate,
        0x234,
        OperandRole("use:0", "use", 0, "r", 21),
    )

    assert resolution is not None
    assert all(exact_owner_path_record(mixed, record) for record in resolution.supporting_records)


def test_effect_traversal_reaches_stack_only_over_exact_owner_edges() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())
    store = InMemoryEvidenceStore()
    store.add_nodes(evidence.nodes)
    store.add_edges(evidence.edges)
    graph = SimpleNamespace(
        store=store,
        backend=SimpleNamespace(object_bindings=evidence),
    )
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


def test_effect_traversal_rejects_parser_poisoned_owner_edge() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())
    poisoned = _replace_evidence_record(
        evidence,
        "object-has-stack-home",
        lambda edge: replace(
            edge,
            provenance=replace(edge.provenance, parser="mwcc-debug-pcdump.v1"),
        ),
    )
    store = InMemoryEvidenceStore()
    store.add_nodes(poisoned.nodes)
    store.add_edges(poisoned.edges)
    graph = SimpleNamespace(
        store=store,
        backend=SimpleNamespace(object_bindings=poisoned),
    )
    allocator = next(node for node in poisoned.nodes if node.kind == "allocator-node")
    stack = next(node for node in poisoned.nodes if node.kind == "stack-object")

    reachable, traversed_edges = _reachable_records(graph, (allocator.record_id,))

    assert stack.record_id not in reachable
    assert not any(
        edge.record_id in traversed_edges and edge.kind == "object-has-stack-home" for edge in poisoned.edges
    )


def test_effect_traversal_rejects_parser_poisoned_owner_endpoint() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())
    poisoned = _replace_evidence_record(
        evidence,
        "stack-object",
        lambda node: replace(
            node,
            provenance=replace(node.provenance, parser="mwcc-debug-pcdump.v1"),
        ),
    )
    store = InMemoryEvidenceStore()
    store.add_nodes(poisoned.nodes)
    store.add_edges(poisoned.edges)
    graph = SimpleNamespace(
        store=store,
        backend=SimpleNamespace(object_bindings=poisoned),
    )
    allocator = next(node for node in poisoned.nodes if node.kind == "allocator-node")
    stack = next(node for node in poisoned.nodes if node.kind == "stack-object")

    reachable, _traversed_edges = _reachable_records(graph, (allocator.record_id,))

    assert stack.record_id not in reachable


def test_effect_traversal_rejects_untagged_legacy_map_into_v2_owner_path() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())
    poisoned = _replace_evidence_record(
        evidence,
        "maps-to-allocator-node",
        lambda edge: replace(
            edge,
            provenance=replace(edge.provenance, parser="mwcc-debug-pcdump.v1"),
            attributes=MappingProxyType(
                {key: value for key, value in edge.attributes.items() if key != "capture_run_id"}
            ),
        ),
    )
    store = InMemoryEvidenceStore()
    store.add_nodes(poisoned.nodes)
    store.add_edges(poisoned.edges)
    graph = SimpleNamespace(
        store=store,
        backend=SimpleNamespace(object_bindings=poisoned),
    )
    allocator = next(node for node in poisoned.nodes if node.kind == "allocator-node")
    stack = next(node for node in poisoned.nodes if node.kind == "stack-object")

    reachable, traversed_edges = _reachable_records(graph, (allocator.record_id,))

    assert stack.record_id not in reachable
    assert not any(
        edge.kind == "maps-to-allocator-node" and edge.record_id in traversed_edges for edge in poisoned.edges
    )


def test_inference_traverses_the_same_exact_owner_path_vocabulary() -> None:
    assert {
        "assembly-anchor-emitted-by-pcode",
        "pcode-operand-lineage",
        "pcode-operand-uses-virtual",
        "object-materializes-virtual",
        "object-has-stack-home",
    } <= _PATH_EDGE_KINDS


def test_inference_path_search_rejects_capability_stripped_owner_edges() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())
    stripped = replace(
        evidence,
        capabilities=evidence.capabilities - {"object-to-frame"},
    )
    store = InMemoryEvidenceStore()
    store.add_nodes(stripped.nodes)
    store.add_edges(stripped.edges)
    allocator = next(node for node in stripped.nodes if node.kind == "allocator-node")
    stack = next(node for node in stripped.nodes if node.kind == "stack-object")

    result = _all_simple_paths(
        store,
        allocator.record_id,
        stack.record_id,
        8,
        owner_evidence_by_compile={allocator.compile_id: stripped},
    )

    assert result.paths == ()


def test_inference_rejects_untagged_legacy_map_into_v2_owner_path() -> None:
    evidence = emit_object_binding_evidence(_adapter_input())
    poisoned = _replace_evidence_record(
        evidence,
        "maps-to-allocator-node",
        lambda edge: replace(
            edge,
            provenance=replace(edge.provenance, parser="mwcc-debug-pcdump.v1"),
            attributes=MappingProxyType(
                {key: value for key, value in edge.attributes.items() if key != "capture_run_id"}
            ),
        ),
    )
    store = InMemoryEvidenceStore()
    store.add_nodes(poisoned.nodes)
    store.add_edges(poisoned.edges)
    allocator = next(node for node in poisoned.nodes if node.kind == "allocator-node")
    stack = next(node for node in poisoned.nodes if node.kind == "stack-object")

    result = _all_simple_paths(
        store,
        allocator.record_id,
        stack.record_id,
        8,
        owner_evidence_by_compile={allocator.compile_id: poisoned},
    )

    assert result.paths == ()


def test_report_names_current_verified_backend_owner_path_incompleteness() -> None:
    current = ObjectBindingEvidence(
        (),
        (),
        frozenset({"compiler-object-bindings", "pcode-to-code-range"}),
        "a" * 64,
        "backend-owner-path-incomplete",
        None,
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


def test_backend_adapter_rejects_mixed_process_local_and_v2_identity_spaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _verified_bundle(tmp_path, monkeypatch)
    pcdump = tmp_path / "legacy-pcdump.txt"
    pcdump.write_text(
        "Starting function target\nBEFORE REGISTER COLORING\ntarget\nB0: Succ={} Pred={} Labels={}\n    mr r66,r66\n",
        encoding="utf-8",
    )
    legacy = BackendArtifactRef.model_validate(
        {
            "path": pcdump.name,
            "sha256": _sha256(pcdump.read_bytes()),
            "format": "mwcc-debug-pcdump",
            "capabilities": (),
        }
    )
    manifest = bundle.manifest.model_copy(
        update={
            "artifacts": bundle.manifest.artifacts.model_copy(
                update={"backend": (*bundle.manifest.artifacts.backend, legacy)}
            ),
            "producer_versions": {
                **bundle.manifest.producer_versions,
                "mwcc_debug": "mwcc-debug-pcdump.v1",
            },
        }
    )
    mixed = replace(
        bundle,
        manifest=manifest,
        artifact_paths=MappingProxyType({**bundle.artifact_paths, "backend[1]": pcdump}),
    )

    with pytest.raises(BundleInputError, match="incompatible process-local backend"):
        adapt_backends(mixed)


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


def test_adapter_converts_deep_json_recursion_to_bundle_input_error(
    tmp_path: Path,
) -> None:
    hostile = tmp_path / "deep.json"
    depth = 2000
    hostile.write_text(
        '{"deep":' * depth + "null" + "}" * depth,
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.o"
    candidate.write_bytes(b"object")
    bundle = SimpleNamespace(
        compile_id="compile",
        manifest=SimpleNamespace(function="fn"),
        candidate_object_path=candidate,
        backend_paths=lambda _format: (hostile,),
    )

    with pytest.raises(BundleInputError, match="invalid backend trace v2"):
        adapt_object_bindings(bundle)
