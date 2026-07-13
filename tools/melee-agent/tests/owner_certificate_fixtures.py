from __future__ import annotations

import hashlib
from dataclasses import fields, is_dataclass, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Iterable, Mapping, TypeVar

import pytest
from tools.mwcc_retro.backend_object_bindings import ObjectBindingValidation
from tools.mwcc_retro.backend_pcode_lineage import (
    AnchorVirtualBinding,
    PCodeLineageValidation,
)

from src.mwcc_debug.causal_diff import backend_adapter
from src.mwcc_debug.causal_diff.alignment import (
    AnchorAlignment,
    OperandRole,
    RolePair,
    build_role_comparisons,
)
from src.mwcc_debug.causal_diff.asm_adapter import CheckdiffEvidence
from src.mwcc_debug.causal_diff.backend_adapter import BackendEvidence
from src.mwcc_debug.causal_diff.bundles import ValidatedBundle
from src.mwcc_debug.causal_diff.canonical import canonical_bytes
from src.mwcc_debug.causal_diff.differ import diff_frontiers
from src.mwcc_debug.causal_diff.effects import DerivedEffects, derive_effects
from src.mwcc_debug.causal_diff.frame_adapter import FrameEvidence
from src.mwcc_debug.causal_diff.graph import FrontierGraph
from src.mwcc_debug.causal_diff.inference import CausalDiffReport, build_report
from src.mwcc_debug.causal_diff.models import (
    AdapterResult,
    ComparisonRecord,
    Confidence,
    EvidenceEdge,
    EvidenceNode,
    Provenance,
)
from src.mwcc_debug.causal_diff.object_binding_adapter import (
    ObjectBindingAdapterInput,
    ObjectBindingEvidence,
)
from src.mwcc_debug.causal_diff.owner_certificate import (
    OwnerCertificateResult,
    OwnerRoleKey,
    OwnerSemanticState,
    build_owner_certificates,
)
from src.mwcc_debug.causal_diff.source_adapter import SourceEvidence
from src.mwcc_debug.causal_diff.store import InMemoryEvidenceStore
from tests.owner_certificate_test_authority import emit_trusted_object_binding_evidence_for_test
from tests.test_causal_diff_alignment import (
    _edge as _fixture_edge,
)
from tests.test_causal_diff_alignment import (
    _graph as _legacy_graph,
)
from tests.test_causal_diff_alignment import (
    _node as _fixture_node,
)
from tests.test_causal_diff_object_bindings import (
    _adapter_input,
    _object_result,
    _pcode_result,
    _verified_bundle,
)

_T = TypeVar("_T")

STORE_FACTORIES = (pytest.param(InMemoryEvidenceStore, id="in-memory"),)
ROLE = OwnerRoleKey("use:0", "gpr", "row-home", 4, "locals")
STATE = OwnerSemanticState(21, 0x44, 4)
CHANGED_STATE = OwnerSemanticState(22, 0x48, 4)
PARTIAL_OWNER_STAGES = (
    "anchor",
    "pcode-lineage",
    "virtual",
    "object",
    "allocator",
    "frame",
)


def only(items: Iterable[_T]) -> _T:
    values = tuple(items)
    if len(values) != 1:
        raise AssertionError(f"expected exactly one item, found {len(values)}")
    return values[0]


def complete_evidence(**adapter_overrides: object) -> ObjectBindingEvidence:
    return emit_trusted_object_binding_evidence_for_test(_adapter_input(**adapter_overrides))


def evidence_with_partial_owner_branch(
    stage: str,
    *,
    duplicate: bool = False,
    permuted: bool = False,
    shared_role: bool = True,
    base_evidence: ObjectBindingEvidence | None = None,
    registered_malformed: bool = False,
) -> ObjectBindingEvidence:
    if stage not in PARTIAL_OWNER_STAGES:
        raise ValueError(f"unknown partial owner stage: {stage}")
    evidence = complete_evidence() if base_evidence is None else base_evidence
    nodes_by_kind = {node.kind: node for node in evidence.nodes}
    edges_by_kind = {edge.kind: edge for edge in evidence.edges if edge.kind != "pcode-operand-lineage"}
    direct_lineage = only(
        edge
        for edge in evidence.edges
        if edge.kind == "pcode-operand-lineage"
        and evidence.nodes[
            next(index for index, node in enumerate(evidence.nodes) if node.record_id == edge.source_id)
        ].kind
        == "retail-pcode"
    )
    operand_key = ROLE.operand_key if shared_role else "use:8"

    def partial_node(
        template: EvidenceNode,
        tag: str,
        *,
        role_key: str | None = None,
        attributes: Mapping[str, object] | None = None,
    ) -> EvidenceNode:
        return EvidenceNode.create(
            compile_id=template.compile_id,
            function=template.function,
            kind=template.kind,
            local_key=(evidence.capture_run_id, "partial-owner", stage, tag),
            role_key=template.role_key if role_key is None else role_key,
            producer_confidence=template.producer_confidence,
            adapter_confidence=template.adapter_confidence,
            provenance=replace(
                template.provenance,
                derivation_rule=f"partial-owner-{stage}-{tag}",
                input_record_ids=(),
            ),
            input_confidences=(),
            attributes=template.attributes if attributes is None else attributes,
        )

    def partial_edge(
        template: EvidenceEdge,
        source: EvidenceNode,
        target_id: str,
        *,
        target_confidence: Confidence | None = None,
        attributes: Mapping[str, object] | None = None,
    ) -> EvidenceEdge:
        return EvidenceEdge.create(
            compile_id=template.compile_id,
            function=template.function,
            kind=template.kind,
            source_id=source.record_id,
            target_id=target_id,
            occurrence_ordinal=99,
            producer_confidence=template.producer_confidence,
            adapter_confidence=template.adapter_confidence,
            provenance=replace(
                template.provenance,
                derivation_rule=f"partial-owner-{stage}-{template.kind}",
                input_record_ids=(source.record_id, target_id),
            ),
            input_confidences=(
                source.confidence,
                source.confidence if target_confidence is None else target_confidence,
            ),
            attributes=template.attributes if attributes is None else attributes,
        )

    added_nodes: tuple[EvidenceNode, ...]
    added_edges: tuple[EvidenceEdge, ...]
    if stage == "anchor":
        anchor_template = nodes_by_kind["assembly-operand-anchor"]
        anchor = partial_node(
            anchor_template,
            "anchor",
            role_key=operand_key,
            attributes={
                **anchor_template.attributes,
                "machine_operand_key": operand_key,
            },
        )
        edge_template = edges_by_kind["assembly-anchor-emitted-by-pcode"]
        edge = partial_edge(
            edge_template,
            anchor,
            f"missing-partial-pcode-{operand_key}",
            attributes={
                **edge_template.attributes,
                "machine_operand_key": operand_key,
            },
        )
        added_nodes, added_edges = (anchor,), (edge,)
    elif stage == "pcode-lineage":
        lineage = partial_node(nodes_by_kind["pcode-operand"], "lineage")
        pcode = nodes_by_kind["retail-pcode"]
        edge = partial_edge(
            direct_lineage,
            pcode,
            lineage.record_id,
            target_confidence=lineage.confidence,
            attributes={
                **direct_lineage.attributes,
                "machine_operand_key": operand_key,
            },
        )
        added_nodes, added_edges = (lineage,), (edge,)
    elif stage == "virtual":
        virtual_template = nodes_by_kind["retail-virtual-register"]
        class_id = 0 if shared_role else 1
        virtual = partial_node(
            virtual_template,
            "virtual",
            attributes={
                **virtual_template.attributes,
                "class_id": class_id,
                "class": "r" if class_id == 0 else "f",
                "virtual": 99,
            },
        )
        lineage = only(
            node
            for node in evidence.nodes
            if node.kind == "pcode-operand" and node.attributes.get("operand_lineage_id") == "ol-1"
        )
        edge_template = edges_by_kind["pcode-operand-uses-virtual"]
        edge = partial_edge(
            edge_template,
            lineage,
            virtual.record_id,
            target_confidence=virtual.confidence,
            attributes={
                **edge_template.attributes,
                "machine_operand_key": operand_key,
            },
        )
        added_nodes, added_edges = (virtual,), (edge,)
    elif stage == "object":
        owner_template = nodes_by_kind["compiler-object"]
        owner = partial_node(
            owner_template,
            "object",
            attributes={
                **owner_template.attributes,
                "object_id": "partial-owner-object",
                "type_size": ROLE.type_size if shared_role else ROLE.type_size * 2,
            },
        )
        virtual = nodes_by_kind["retail-virtual-register"]
        edge_template = edges_by_kind["object-materializes-virtual"]
        edge = partial_edge(
            edge_template,
            owner,
            virtual.record_id,
            target_confidence=virtual.confidence,
            attributes={
                **edge_template.attributes,
                "object_id": owner.attributes["object_id"],
            },
        )
        added_nodes, added_edges = (owner,), (edge,)
    elif stage == "allocator":
        virtual_template = nodes_by_kind["retail-virtual-register"]
        class_id = 0 if shared_role else 1
        virtual = partial_node(
            virtual_template,
            "allocator-virtual",
            attributes={
                **virtual_template.attributes,
                "class_id": class_id,
                "class": "r" if class_id == 0 else "f",
                "virtual": 99,
            },
        )
        edge_template = edges_by_kind["maps-to-allocator-node"]
        edge = partial_edge(
            edge_template,
            virtual,
            f"missing-partial-allocator-{operand_key}",
            attributes={
                **edge_template.attributes,
                "class_id": class_id,
            },
        )
        added_nodes, added_edges = (virtual,), (edge,)
    else:
        owner_template = nodes_by_kind["compiler-object"]
        owner = (
            owner_template
            if shared_role
            else partial_node(
                owner_template,
                "frame-owner",
                attributes={
                    **owner_template.attributes,
                    "object_id": "partial-frame-owner",
                    "type_size": ROLE.type_size * 2,
                },
            )
        )
        edge_template = edges_by_kind["object-has-stack-home"]
        malformed_target = (
            partial_node(nodes_by_kind["allocator-node"], "malformed-frame-target") if registered_malformed else None
        )
        edge = partial_edge(
            edge_template,
            owner,
            (malformed_target.record_id if malformed_target is not None else f"missing-partial-frame-{operand_key}"),
            target_confidence=(malformed_target.confidence if malformed_target is not None else None),
            attributes={
                **edge_template.attributes,
                "area": ROLE.frame_area if shared_role else "temps",
                "semantic_stack_role": (ROLE.semantic_stack_role if shared_role else "orphan-home"),
            },
        )
        added_nodes = (
            (() if owner is owner_template else (owner,))
            if malformed_target is None
            else (
                *(() if owner is owner_template else (owner,)),
                malformed_target,
            )
        )
        added_edges = (edge,)

    if duplicate:
        added_nodes = (*added_nodes, *added_nodes)
        added_edges = (*added_edges, *added_edges)
    nodes = (*evidence.nodes, *added_nodes)
    edges = (*evidence.edges, *added_edges)
    if permuted:
        nodes = tuple(reversed(nodes))
        edges = tuple(reversed(edges))
    augmented = ObjectBindingEvidence(
        nodes,
        edges,
        evidence.capabilities,
        evidence.capture_run_id,
        evidence.instrumentation_identity,
    )
    object.__setattr__(
        augmented,
        "_adapter_token",
        object.__getattribute__(evidence, "_adapter_token"),
    )
    return augmented


def validated_current_v2_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> ValidatedBundle:
    return _verified_bundle(tmp_path, monkeypatch)


def future_complete_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> backend_adapter.BackendEvidence:
    bundle = validated_current_v2_bundle(tmp_path, monkeypatch)
    evidence = complete_evidence(
        compile_id=bundle.compile_id,
        function=bundle.manifest.function,
    )
    monkeypatch.setattr(
        backend_adapter,
        "adapt_object_bindings",
        lambda _bundle: evidence,
    )
    return backend_adapter.adapt_backends(bundle)


def first_role() -> OwnerRoleKey:
    return OwnerRoleKey("use:0", "gpr", "row-home", 4, "locals")


def second_role() -> OwnerRoleKey:
    return OwnerRoleKey("use:1", "gpr", "second-home", 4, "locals")


def other_role() -> OwnerRoleKey:
    return OwnerRoleKey("use:9", "gpr", "missing-home", 4, "locals")


def _mapping(**values: object) -> Mapping[str, object]:
    return MappingProxyType(values)


def _event(
    *,
    pcode_id: str,
    inputs: tuple[str, ...],
    outputs: tuple[tuple[str, tuple[str, ...]], ...],
    mutation_kind: str = "clone",
) -> Mapping[str, object]:
    return _mapping(
        mutation_kind=mutation_kind,
        inputs=(
            _mapping(
                pcode_id=pcode_id,
                operands=tuple(
                    _mapping(operand_lineage_id=lineage_id, operand_index=index)
                    for index, lineage_id in enumerate(inputs, start=1)
                ),
            ),
        ),
        outputs=(
            _mapping(
                pcode_id=pcode_id,
                operands=tuple(
                    _mapping(
                        operand_lineage_id=lineage_id,
                        operand_index=index,
                        parent_lineage_ids=parents,
                    )
                    for index, (lineage_id, parents) in enumerate(outputs, start=1)
                ),
            ),
        ),
    )


def _path(
    index: int,
    *,
    operand_key: str,
    semantic_stack_role: str,
    physical_register: int = 21,
    stack_offset: int = 0x44,
    type_size: int = 4,
    include_object: bool = True,
    rewrite_confidence: str = "observed",
) -> dict[str, object]:
    return {
        "object_id": f"obj-{index}",
        "pcode_id": f"pc-{index}",
        "lineage_id": f"ol-{index + 1}",
        "parent_id": f"ol-parent-{index}",
        "virtual": 66 + index,
        "offset": 0x234 + index * 4,
        "operand_key": operand_key,
        "semantic_stack_role": semantic_stack_role,
        "physical_register": physical_register,
        "emission_physical": physical_register,
        "stack_offset": stack_offset,
        "type_size": type_size,
        "include_object": include_object,
        "rewrite_confidence": rewrite_confidence,
    }


def _evidence_from_paths(
    paths: tuple[Mapping[str, object], ...],
    *,
    events: tuple[Mapping[str, object], ...] | None = None,
    reverse_pcode_inputs: bool = False,
    reverse_event_inputs: bool = False,
    instrumentation_identity: object = (
        "1" * 64,
        "proof-test",
        "2" * 64,
        "mwcc-retro-lifetime-proof.v1",
    ),
    compile_id: str = "compile-a",
    function: str = "fn",
    capture_run_id: str = "a" * 64,
) -> ObjectBindingEvidence:
    base_object = _object_result(capture_run_id=capture_run_id)
    base_object_row = tuple(base_object.normalized["objects"])[0]
    base_virtual_row = tuple(base_object.normalized["virtual_bindings"])[0]
    base_frame_row = tuple(base_object.normalized["frame_bindings"])[0]

    object_rows = []
    virtual_rows = []
    frame_rows = []
    for index, path in enumerate(paths):
        if not path["include_object"]:
            continue
        object_id = str(path["object_id"])
        runtime_address = 0x1000 + index * 0x100
        snapshots = tuple(
            _mapping(
                **{
                    **dict(snapshot),
                    "runtime_address": runtime_address,
                    "type_size": path["type_size"],
                }
            )
            for snapshot in base_object_row["stage_snapshots"]
        )
        object_rows.append(
            _mapping(
                **{
                    **dict(base_object_row),
                    "object_id": object_id,
                    "runtime_address": runtime_address,
                    "type_size": path["type_size"],
                    "stage_snapshots": snapshots,
                }
            )
        )
        virtual_rows.append(
            _mapping(
                **{
                    **dict(base_virtual_row),
                    "object_id": object_id,
                    "virtual": path["virtual"],
                    "ig_id": path["virtual"],
                    "ignode_runtime_address": 0x4000 + int(path["virtual"]),
                }
            )
        )
        frame_rows.append(
            _mapping(
                **{
                    **dict(base_frame_row),
                    "object_id": object_id,
                    "semantic_stack_role": path["semantic_stack_role"],
                    "final_r1_offset": path["stack_offset"],
                    "size": path["type_size"],
                    "list_node_runtime_address": 0x5000 + index * 0x10,
                }
            )
        )
    object_normalized = {
        **dict(base_object.normalized),
        "objects": tuple(object_rows),
        "virtual_bindings": tuple(virtual_rows),
        "frame_bindings": tuple(frame_rows),
    }
    object_validation = replace(base_object, normalized=MappingProxyType(object_normalized))

    instructions = []
    occurrences = []
    anchors: dict[tuple[int, str], AnchorVirtualBinding] = {}
    paths_by_pcode: dict[str, list[Mapping[str, object]]] = {}
    for path in paths:
        offset = int(path["offset"])
        operand_key = str(path["operand_key"])
        lineage_id = str(path["lineage_id"])
        pcode_id = str(path["pcode_id"])
        virtual = int(path["virtual"])
        physical = int(path["physical_register"])
        paths_by_pcode.setdefault(pcode_id, []).append(path)
        occurrences.append(
            _mapping(
                pcode_id=pcode_id,
                operand_index=1,
                operand_lineage_id=lineage_id,
                class_id=0,
                virtual_kind="r",
                virtual=virtual,
                ig_id=virtual,
                allocated_physical=physical,
                runtime_address=0x6000 + offset,
                confidence=path["rewrite_confidence"],
            )
        )
        anchors[(offset, operand_key)] = AnchorVirtualBinding(
            offset,
            operand_key,
            pcode_id,
            lineage_id,
            0,
            virtual,
            physical,
            "derived-unique",
        )
    for pcode_id, pcode_paths in paths_by_pcode.items():
        by_offset: dict[int, list[Mapping[str, object]]] = {}
        for path in pcode_paths:
            by_offset.setdefault(int(path["offset"]), []).append(path)
        instructions.append(
            _mapping(
                pcode_id=pcode_id,
                runtime_address=0x6000 + min(by_offset),
                allocation_generation=1,
                code_ranges=tuple(
                    _mapping(
                        start=offset,
                        end_exclusive=offset + 4,
                        machine_operand_mappings=tuple(
                            _mapping(
                                machine_operand_key=path["operand_key"],
                                emission_pcode_operand_index=index,
                                operand_lineage_id=path["lineage_id"],
                                physical_register=path["emission_physical"],
                                instruction_offset_within_range=0,
                            )
                            for index, path in enumerate(offset_paths, start=1)
                        ),
                    )
                    for offset, offset_paths in sorted(by_offset.items())
                ),
            )
        )
    if events is None:
        events = tuple(
            _event(
                pcode_id=str(path["pcode_id"]),
                inputs=(str(path["parent_id"]),),
                outputs=((str(path["lineage_id"]), (str(path["parent_id"]),)),),
            )
            for path in paths
        )
    if reverse_event_inputs:
        events = tuple(
            _mapping(
                **{
                    **dict(event),
                    "inputs": tuple(
                        _mapping(
                            **{
                                **dict(group),
                                "operands": tuple(reversed(tuple(group["operands"]))),
                            }
                        )
                        for group in event["inputs"]
                    ),
                }
            )
            for event in events
        )
    if reverse_pcode_inputs:
        instructions.reverse()
        occurrences.reverse()
    base_pcode = _pcode_result()
    pcode_validation = replace(
        base_pcode,
        normalized=MappingProxyType(
            {
                "pcode_instructions": tuple(instructions),
                "pcode_occurrences": tuple(occurrences),
                "pcode_operand_lineage_events": events,
            }
        ),
        anchor_bindings=MappingProxyType(anchors),
    )
    source: ObjectBindingAdapterInput = _adapter_input(
        compile_id=compile_id,
        function=function,
        capture_run_id=capture_run_id,
        object_result=object_validation,
        pcode_result=pcode_validation,
        instrumentation_identity=instrumentation_identity,
    )
    return emit_trusted_object_binding_evidence_for_test(source)


def evidence_with_two_mutation_outputs(
    first_parents: tuple[str, ...],
    second_parents: tuple[str, ...],
    *,
    permuted: bool = False,
) -> ObjectBindingEvidence:
    paths = (
        _path(0, operand_key="use:0", semantic_stack_role="row-home"),
        _path(1, operand_key="use:1", semantic_stack_role="second-home", physical_register=22),
    )
    events = (
        _event(
            pcode_id="pc-0",
            inputs=tuple(sorted(set((*first_parents, *second_parents)))),
            outputs=(("ol-1", first_parents), ("ol-2", second_parents)),
        ),
    )
    # One event can have sibling outputs with different exact parent sets.
    shared_pcode_paths = tuple({**path, "pcode_id": "pc-0", "offset": 0x234} for path in paths)
    return _evidence_from_paths(
        shared_pcode_paths,
        events=events,
        reverse_event_inputs=permuted,
    )


def evidence_with_mutation_parent_override(
    parents: tuple[str, ...],
) -> ObjectBindingEvidence:
    evidence = complete_evidence()
    lineage_support = only(
        node
        for node in evidence.nodes
        if node.kind == "backend-support-record"
        and node.attributes.get("support_kind") == "pcode-lineage-event"
        and "event_index" in node.attributes
    )
    changed = lineage_support.with_attributes({**lineage_support.attributes, "parent_lineage_ids": parents})
    # Public emission creates one coherent event. The proof-incapable persistence
    # seam then changes only the named parent fact; no competing event is added.
    return replace_record(evidence, changed)


def evidence_with_lineage_variant(variant: str) -> ObjectBindingEvidence:
    evidence = complete_evidence()
    lineage_support = only(
        node
        for node in evidence.nodes
        if node.kind == "backend-support-record"
        and node.attributes.get("support_kind") == "pcode-lineage-event"
        and "event_index" in node.attributes
    )
    field, value = {
        "event-index": ("event_index", 1),
        "side": ("side", "inputs"),
        "mutation-kind": ("mutation_kind", "merge"),
        "noncanonical-parent-order": ("parent_lineage_ids", ("ol-b", "ol-a")),
    }.get(variant, (None, None))
    if field is None:
        raise ValueError(f"unknown lineage variant: {variant}")
    changed = lineage_support.with_attributes({**lineage_support.attributes, field: value})
    # Corrupt exactly one field of the sole publicly emitted mutation event.
    return replace_record(evidence, changed)


def evidence_with_certificate_and_role_rejection(
    role: OwnerRoleKey,
) -> ObjectBindingEvidence:
    if role != first_role():
        raise ValueError("fixture supports the canonical first role only")
    return _evidence_from_paths(
        (
            _path(0, operand_key=role.operand_key, semantic_stack_role=role.semantic_stack_role),
            _path(
                1,
                operand_key=role.operand_key,
                semantic_stack_role=role.semantic_stack_role,
                include_object=False,
            ),
        )
    )


def evidence_without_instrumentation_identity() -> ObjectBindingEvidence:
    source = replace(_adapter_input(), instrumentation_identity=None)
    return emit_trusted_object_binding_evidence_for_test(source)


def ambiguous_evidence(*, permuted: bool = False) -> ObjectBindingEvidence:
    paths = (
        _path(0, operand_key="use:0", semantic_stack_role="row-home"),
        _path(1, operand_key="use:0", semantic_stack_role="row-home"),
    )
    return _evidence_from_paths(paths, reverse_pcode_inputs=permuted)


def evidence_with_independent_paths(count: int) -> ObjectBindingEvidence:
    if count < 1:
        raise ValueError("count must be positive")
    return _evidence_from_paths(
        tuple(
            _path(
                index,
                operand_key=f"use:{index}",
                semantic_stack_role=f"indexed-home-{index}",
                stack_offset=0x44 + index * 4,
            )
            for index in range(count)
        )
    )


def evidence_with_partial_independent_paths(count: int) -> ObjectBindingEvidence:
    evidence = evidence_with_independent_paths(count)
    virtual_template = next(node for node in evidence.nodes if node.kind == "retail-virtual-register")
    edge_template = next(edge for edge in evidence.edges if edge.kind == "pcode-operand-uses-virtual")
    lineage_by_operand = {
        str(edge.attributes["machine_operand_key"]): only(
            node for node in evidence.nodes if node.record_id == edge.source_id
        )
        for edge in evidence.edges
        if edge.kind == "pcode-operand-uses-virtual"
    }
    added_nodes: list[EvidenceNode] = []
    added_edges: list[EvidenceEdge] = []
    for index in range(count):
        operand_key = f"use:{index}"
        lineage = lineage_by_operand[operand_key]
        virtual = EvidenceNode.create(
            compile_id=virtual_template.compile_id,
            function=virtual_template.function,
            kind=virtual_template.kind,
            local_key=(evidence.capture_run_id, "partial-indexed-virtual", index),
            role_key=virtual_template.role_key,
            producer_confidence=virtual_template.producer_confidence,
            adapter_confidence=virtual_template.adapter_confidence,
            provenance=replace(
                virtual_template.provenance,
                derivation_rule="partial-indexed-virtual",
                input_record_ids=(),
            ),
            input_confidences=(),
            attributes={
                **virtual_template.attributes,
                "class_id": 0,
                "class": "r",
                "virtual": 10_000 + index,
            },
        )
        edge = EvidenceEdge.create(
            compile_id=edge_template.compile_id,
            function=edge_template.function,
            kind=edge_template.kind,
            source_id=lineage.record_id,
            target_id=virtual.record_id,
            occurrence_ordinal=100 + index,
            producer_confidence=edge_template.producer_confidence,
            adapter_confidence=edge_template.adapter_confidence,
            provenance=replace(
                edge_template.provenance,
                derivation_rule="partial-indexed-virtual-edge",
                input_record_ids=(lineage.record_id, virtual.record_id),
            ),
            input_confidences=(lineage.confidence, virtual.confidence),
            attributes={
                **edge_template.attributes,
                "machine_operand_key": operand_key,
            },
        )
        added_nodes.append(virtual)
        added_edges.append(edge)
    augmented = ObjectBindingEvidence(
        (*evidence.nodes, *added_nodes),
        (*evidence.edges, *added_edges),
        evidence.capabilities,
        evidence.capture_run_id,
        evidence.instrumentation_identity,
    )
    object.__setattr__(
        augmented,
        "_adapter_token",
        object.__getattribute__(evidence, "_adapter_token"),
    )
    return augmented


def evidence_with_role_statuses() -> ObjectBindingEvidence:
    return _evidence_from_paths(
        (
            _path(0, operand_key="use:0", semantic_stack_role="row-home"),
            _path(1, operand_key="use:1", semantic_stack_role="ambiguous-home"),
            _path(2, operand_key="use:1", semantic_stack_role="ambiguous-home"),
            _path(3, operand_key="use:2", semantic_stack_role="contradictory-home"),
            _path(
                4,
                operand_key="use:2",
                semantic_stack_role="contradictory-home",
                physical_register=22,
            ),
            _path(
                5,
                operand_key="use:3",
                semantic_stack_role="incomplete-home",
                rewrite_confidence="heuristic",
            ),
        )
    )


def evidence_with_split_physical_assignment() -> ObjectBindingEvidence:
    path = _path(0, operand_key="use:0", semantic_stack_role="row-home")
    path["emission_physical"] = 22
    return _evidence_from_paths((path,))


def evidence_with_coordinated_allocator_change() -> ObjectBindingEvidence:
    path = _path(
        0,
        operand_key="use:0",
        semantic_stack_role="row-home",
        physical_register=22,
    )
    path["emission_physical"] = 21
    return _evidence_from_paths((path,))


def evidence_with_heuristic_support() -> ObjectBindingEvidence:
    return _evidence_from_paths(
        (
            _path(
                0,
                operand_key="use:0",
                semantic_stack_role="row-home",
                rewrite_confidence="heuristic",
            ),
        )
    )


def evidence_with_zero_sized_owner(*, include_valid: bool = False) -> ObjectBindingEvidence:
    invalid = _path(
        1 if include_valid else 0,
        operand_key="use:1" if include_valid else "use:0",
        semantic_stack_role="zero-home" if include_valid else "row-home",
        type_size=0,
    )
    paths = (
        (
            _path(0, operand_key="use:0", semantic_stack_role="row-home"),
            invalid,
        )
        if include_valid
        else (invalid,)
    )
    return _evidence_from_paths(paths)


def evidence_with_allocator_origin_conflict() -> ObjectBindingEvidence:
    base_object = _object_result()
    virtual = tuple(base_object.normalized["virtual_bindings"])[0]
    conflicting = _mapping(**{**dict(virtual), "ig_id": 99})
    normalized = {
        **dict(base_object.normalized),
        "virtual_bindings": (virtual, conflicting),
    }
    object_validation = replace(
        base_object,
        normalized=MappingProxyType(normalized),
    )
    source = replace(_adapter_input(), object_validation=object_validation)
    return emit_trusted_object_binding_evidence_for_test(source)


def disconnected_evidence() -> ObjectBindingEvidence:
    return _evidence_from_paths(
        (
            _path(
                0,
                operand_key="use:0",
                semantic_stack_role="row-home",
                include_object=False,
            ),
        )
    )


def evidence_with_global_and_role_rejection() -> ObjectBindingEvidence:
    return _evidence_from_paths(
        (
            _path(
                0,
                operand_key="use:0",
                semantic_stack_role="row-home",
                rewrite_confidence="heuristic",
            ),
        ),
        instrumentation_identity=None,
    )


def evidence_with_certificate_and_global_rejection() -> ObjectBindingEvidence:
    return _evidence_from_paths(
        (
            _path(0, operand_key="use:0", semantic_stack_role="row-home"),
            _path(
                1,
                operand_key="use:8",
                semantic_stack_role="orphan-home",
                include_object=False,
            ),
        )
    )


def evidence_with_object_generation_conflict() -> ObjectBindingEvidence:
    base_object = _object_result()
    owner = tuple(base_object.normalized["objects"])[0]
    normalized = {
        **dict(base_object.normalized),
        "objects": (_mapping(**{**dict(owner), "allocation_generation": 2}),),
    }
    object_validation = replace(
        base_object,
        normalized=MappingProxyType(normalized),
    )
    source = replace(_adapter_input(), object_validation=object_validation)
    return emit_trusted_object_binding_evidence_for_test(source)


def support(evidence: ObjectBindingEvidence, support_kind: str) -> EvidenceNode:
    return only(
        node
        for node in evidence.nodes
        if node.kind == "backend-support-record" and node.attributes.get("support_kind") == support_kind
    )


def replace_record(
    evidence: ObjectBindingEvidence,
    record: EvidenceNode | EvidenceEdge,
) -> ObjectBindingEvidence:
    if isinstance(record, EvidenceNode):
        matches = tuple(node.record_id == record.record_id for node in evidence.nodes)
        if sum(matches) != 1:
            raise AssertionError(f"expected one node with record ID {record.record_id}")
        return replace(
            evidence,
            nodes=tuple(record if matches[index] else node for index, node in enumerate(evidence.nodes)),
        )
    matches = tuple(edge.record_id == record.record_id for edge in evidence.edges)
    if sum(matches) != 1:
        raise AssertionError(f"expected one edge with record ID {record.record_id}")
    return replace(
        evidence,
        edges=tuple(record if matches[index] else edge for index, edge in enumerate(evidence.edges)),
    )


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
            if not field.name.startswith("_")
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=repr)
    return value


def canonical_result(result: object) -> bytes:
    return canonical_bytes(_json_value(result))


def alignment() -> AnchorAlignment:
    return replace(
        _future_complete_alignment(future_complete_graph_pair()),
        comparisons=(),
    )


def _empty_checkdiff() -> CheckdiffEvidence:
    return CheckdiffEvidence(
        result=AdapterResult(),
        rows_by_offset=MappingProxyType({}),
        stack_slot_localizer=None,
        target_assembly=(),
        current_assembly=(),
        expected_assembly_digest="e" * 64,
    )


def _frontier(
    label: str,
    compile_id: str,
    store: InMemoryEvidenceStore,
    backend: BackendEvidence,
) -> FrontierGraph:
    return FrontierGraph(
        bundle=SimpleNamespace(
            label=label,
            compile_id=compile_id,
            manifest=SimpleNamespace(function="fn_test"),
        ),
        store=store,
        checkdiff=_empty_checkdiff(),
        backend=backend,
        inspector=AdapterResult(),
        frame=FrameEvidence(
            result=AdapterResult(),
            expected_stack_roles=MappingProxyType({}),
            current_stack_nodes=MappingProxyType({}),
        ),
        source=SourceEvidence(
            result=AdapterResult(),
            expressions_by_signature=MappingProxyType({}),
            inline_scopes_by_callee=MappingProxyType({}),
        ),
        warnings=(),
    )


def _status_evidence(
    status: str,
    *,
    compile_id: str,
    capture_run_id: str,
) -> ObjectBindingEvidence:
    common = {
        "compile_id": compile_id,
        "function": "fn_test",
        "capture_run_id": capture_run_id,
    }
    if status == "unique":
        return complete_evidence(**common)
    if status == "unique-with-role-rejection":
        return _evidence_from_paths(
            (
                _path(
                    0,
                    operand_key=ROLE.operand_key,
                    semantic_stack_role=ROLE.semantic_stack_role,
                ),
                _path(
                    1,
                    operand_key=ROLE.operand_key,
                    semantic_stack_role=ROLE.semantic_stack_role,
                    include_object=False,
                ),
            ),
            **common,
        )
    if status == "unique-with-global-rejection":
        return _evidence_from_paths(
            (
                _path(
                    0,
                    operand_key=ROLE.operand_key,
                    semantic_stack_role=ROLE.semantic_stack_role,
                ),
                _path(
                    1,
                    operand_key="use:8",
                    semantic_stack_role="orphan-home",
                    include_object=False,
                ),
            ),
            **common,
        )
    if status == "missing":
        return _evidence_from_paths((), **common)
    if status == "ambiguous":
        return _evidence_from_paths(
            (
                _path(0, operand_key=ROLE.operand_key, semantic_stack_role=ROLE.semantic_stack_role),
                _path(1, operand_key=ROLE.operand_key, semantic_stack_role=ROLE.semantic_stack_role),
            ),
            **common,
        )
    if status == "contradictory":
        path = _path(0, operand_key=ROLE.operand_key, semantic_stack_role=ROLE.semantic_stack_role)
        path["emission_physical"] = 22
        return _evidence_from_paths((path,), **common)
    if status == "incomplete":
        return _evidence_from_paths(
            (
                _path(
                    0,
                    operand_key=ROLE.operand_key,
                    semantic_stack_role=ROLE.semantic_stack_role,
                    rewrite_confidence="heuristic",
                ),
            ),
            **common,
        )
    if status == "global-and-role-rejection":
        return _evidence_from_paths(
            (
                _path(
                    0,
                    operand_key=ROLE.operand_key,
                    semantic_stack_role=ROLE.semantic_stack_role,
                    rewrite_confidence="heuristic",
                ),
            ),
            instrumentation_identity=None,
            **common,
        )
    raise ValueError(f"unknown owner status: {status}")


def _certified_frontier(
    label: str,
    status: str,
    *,
    partial_stage: str | None = None,
) -> FrontierGraph:
    compile_id = f"certificate-{label}"
    capture_run_id = hashlib.sha256(label.encode()).hexdigest()
    evidence = _status_evidence(
        status,
        compile_id=compile_id,
        capture_run_id=capture_run_id,
    )
    if partial_stage is not None:
        evidence = evidence_with_partial_owner_branch(
            partial_stage,
            base_evidence=evidence,
            registered_malformed=partial_stage == "frame",
        )
    result = build_owner_certificates(evidence)
    store = InMemoryEvidenceStore()
    store.add_nodes(evidence.nodes)
    store.add_edges(evidence.edges)
    store.add_nodes(result.certificate_nodes)
    backend_result = AdapterResult(
        nodes=(*evidence.nodes, *result.certificate_nodes),
        edges=evidence.edges,
    )
    return _frontier(
        label,
        compile_id,
        store,
        BackendEvidence(
            result=backend_result,
            pcdump_text="",
            role_compile=None,
            nodes_by_class_ig=MappingProxyType({}),
            nodes_by_virtual=MappingProxyType({}),
            object_bindings=evidence,
            owner_certificates=result,
        ),
    )


def graphs_with_statuses(
    left_status: str,
    right_status: str,
) -> tuple[FrontierGraph, FrontierGraph]:
    return (
        _certified_frontier("left", left_status),
        _certified_frontier("right", right_status),
    )


def future_complete_graph_pair() -> tuple[FrontierGraph, FrontierGraph]:
    return graphs_with_statuses("unique", "unique")


def graphs_with_partial_owner_branch(
    stage: str,
) -> tuple[FrontierGraph, FrontierGraph]:
    return (
        _certified_frontier("left", "unique", partial_stage=stage),
        _certified_frontier("right", "unique"),
    )


def _semantic_frontier(label: str, state: OwnerSemanticState) -> FrontierGraph:
    compile_id = f"diff-{label}"
    evidence = _evidence_from_paths(
        (
            _path(
                0,
                operand_key=ROLE.operand_key,
                semantic_stack_role=ROLE.semantic_stack_role,
                physical_register=state.assigned_physical_register,
                stack_offset=state.stack_offset,
            ),
        ),
        compile_id=compile_id,
        function="fn_test",
        capture_run_id=hashlib.sha256(label.encode()).hexdigest(),
    )
    result = build_owner_certificates(evidence)
    certificate = only(result.certificate_nodes)
    assert certificate.attributes["semantic_state"] == state.as_json()
    store = InMemoryEvidenceStore()
    store.add_nodes(evidence.nodes)
    store.add_edges(evidence.edges)
    store.add_nodes((certificate,))
    return _frontier(
        label,
        compile_id,
        store,
        BackendEvidence(
            result=AdapterResult(nodes=(*evidence.nodes, certificate), edges=evidence.edges),
            pcdump_text="",
            role_compile=None,
            nodes_by_class_ig=MappingProxyType({}),
            nodes_by_virtual=MappingProxyType({}),
            object_bindings=evidence,
            owner_certificates=result,
        ),
    )


def graphs(
    states: tuple[OwnerSemanticState, OwnerSemanticState] = (STATE, CHANGED_STATE),
) -> tuple[FrontierGraph, FrontierGraph]:
    return (
        _semantic_frontier("left", states[0]),
        _semantic_frontier("right", states[1]),
    )


def owner_comparison(
    states: tuple[OwnerSemanticState, OwnerSemanticState] = (STATE, STATE),
) -> ComparisonRecord:
    return only(
        item
        for item in build_role_comparisons(alignment(), graphs(states))
        if item.relation_kind == "backend-owner-corresponds-to"
    )


def node(record_id: str) -> EvidenceNode:
    matches = tuple(
        candidate
        for graph in (*future_complete_graph_pair(), *graphs())
        if (candidate := graph.store.get_node(record_id)) is not None
    )
    return only(matches)


def _future_complete_graph_pair() -> tuple[FrontierGraph, FrontierGraph]:
    expected_stack = MappingProxyType({ROLE.semantic_stack_role: (0x44, 0x48)})
    return tuple(
        replace(
            graph,
            frame=replace(
                graph.frame,
                expected_stack_roles=expected_stack,
            ),
        )
        for graph in (
            _semantic_frontier("direct", OwnerSemanticState(21, 0x48, 4)),
            _semantic_frontier("paired", OwnerSemanticState(22, 0x44, 4)),
        )
    )


def _future_complete_alignment(
    graph_pair: tuple[FrontierGraph, FrontierGraph],
) -> AnchorAlignment:
    left, right = tuple(sorted(graph_pair, key=lambda graph: str(graph.bundle.label)))
    left_certificate = only(left.backend.owner_certificates.certificate_nodes)
    right_certificate = only(right.backend.owner_certificates.certificate_nodes)
    left_allocator = left.store.get_node(str(left_certificate.attributes["allocator_record_id"]))
    right_allocator = right.store.get_node(str(right_certificate.attributes["allocator_record_id"]))
    assert left_allocator is not None and right_allocator is not None
    analysis_id = "d" * 64
    correspondence = ComparisonRecord.create(
        analysis_id=analysis_id,
        relation_kind="role-corresponds-to",
        left_compile_id=left_allocator.compile_id,
        left_record_id=left_allocator.record_id,
        right_compile_id=right_allocator.compile_id,
        right_record_id=right_allocator.record_id,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        provenance=Provenance(
            artifact_sha256=analysis_id,
            parser="causal-anchor-alignment.v1",
            raw_start=None,
            raw_end=None,
            derivation_rule="synthetic-future-complete-role",
            input_record_ids=(left_allocator.record_id, right_allocator.record_id),
        ),
        input_confidences=(left_allocator.confidence, right_allocator.confidence),
        attributes={"operand_key": ROLE.operand_key},
    )
    pair = RolePair(
        ROLE.operand_key,
        str(left.bundle.label),
        left_allocator,
        str(right.bundle.label),
        right_allocator,
        correspondence,
    )
    return AnchorAlignment(
        analysis_id=analysis_id,
        retail_offset=0x234,
        operand_roles=(OperandRole(ROLE.operand_key, "use", 0, "r", 21),),
        by_operand={ROLE.operand_key: pair},
        comparisons=(correspondence,),
        abstentions=(),
    )


def future_complete_pipeline_inputs() -> tuple[
    tuple[FrontierGraph, FrontierGraph],
    AnchorAlignment,
    tuple[ComparisonRecord, ...],
]:
    graph_pair = _future_complete_graph_pair()
    owner_alignment = _future_complete_alignment(graph_pair)
    comparisons = build_role_comparisons(owner_alignment, graph_pair)
    deltas = diff_frontiers(graph_pair, comparisons)
    return graph_pair, owner_alignment, comparisons + deltas


def future_owner_abstention_pipeline_inputs(
    status: str,
) -> tuple[
    tuple[FrontierGraph, FrontierGraph],
    AnchorAlignment,
    tuple[ComparisonRecord, ...],
    DerivedEffects,
]:
    graph_pair, owner_alignment, _comparisons = future_complete_pipeline_inputs()
    left, right = graph_pair
    evidence = _status_evidence(
        status,
        compile_id=str(left.bundle.compile_id),
        capture_run_id=hashlib.sha256(str(left.bundle.label).encode()).hexdigest(),
    )
    result = build_owner_certificates(evidence)
    store = InMemoryEvidenceStore()
    store.add_nodes(evidence.nodes)
    store.add_edges(evidence.edges)
    store.add_nodes(result.certificate_nodes)
    backend = BackendEvidence(
        result=AdapterResult(
            nodes=(*evidence.nodes, *result.certificate_nodes),
            edges=evidence.edges,
        ),
        pcdump_text="",
        role_compile=None,
        nodes_by_class_ig=MappingProxyType({}),
        nodes_by_virtual=MappingProxyType({}),
        object_bindings=evidence,
        owner_certificates=result,
    )
    graphs = (replace(left, store=store, backend=backend), right)
    comparisons = build_role_comparisons(owner_alignment, graphs)
    deltas = diff_frontiers(graphs, comparisons)
    all_comparisons = (*comparisons, *deltas)
    effects = derive_effects(owner_alignment, graphs, all_comparisons)
    return graphs, owner_alignment, all_comparisons, effects


def future_complete_tied_pipeline_inputs() -> tuple[
    tuple[FrontierGraph, FrontierGraph],
    AnchorAlignment,
    tuple[ComparisonRecord, ...],
]:
    graph_pair = _future_complete_graph_pair()
    base_alignment = _future_complete_alignment(graph_pair)
    tied_key = "use:1"
    base_pair = base_alignment.by_operand[ROLE.operand_key]
    tied_alignment = replace(
        base_alignment,
        operand_roles=(
            *base_alignment.operand_roles,
            OperandRole(tied_key, "use", 1, "r", 21),
        ),
        by_operand={
            **base_alignment.by_operand,
            tied_key: replace(base_pair, operand_key=tied_key),
        },
    )
    comparisons = build_role_comparisons(tied_alignment, graph_pair)
    deltas = diff_frontiers(graph_pair, comparisons)
    return graph_pair, tied_alignment, comparisons + deltas


def _future_complete_inputs():
    graph_pair, owner_alignment, all_comparisons = future_complete_pipeline_inputs()
    effects = derive_effects(owner_alignment, graph_pair, all_comparisons)
    return graph_pair, effects, all_comparisons


def run_synthetic_future_complete_pair() -> CausalDiffReport:
    graph_pair, effects, comparisons = _future_complete_inputs()
    return build_report(graph_pair, effects, comparisons)


def run_with_forged_certificate_node_but_no_trusted_result() -> CausalDiffReport:
    graph_pair, effects, comparisons = _future_complete_inputs()
    forged_graphs = tuple(
        replace(
            graph,
            backend=replace(
                graph.backend,
                owner_certificates=OwnerCertificateResult(
                    graph.backend.owner_certificates.certificate_nodes,
                    graph.backend.owner_certificates.role_resolutions,
                    graph.backend.owner_certificates.global_rejections,
                ),
            ),
        )
        for graph in graph_pair
    )
    assert all(not graph.backend.owner_certificates.is_trusted for graph in forged_graphs)
    return build_report(forged_graphs, effects, comparisons)


def run_with_stored_certificate_content_mismatch() -> CausalDiffReport:
    graph_pair, effects, comparisons = _future_complete_inputs()
    mismatched_graphs = []
    for graph in graph_pair:
        certificate = only(graph.backend.owner_certificates.certificate_nodes)
        mismatched = replace(
            certificate,
            attributes=MappingProxyType(
                {
                    **certificate.attributes,
                    "proof_content_sha256": "f" * 64,
                }
            ),
        )
        store = InMemoryEvidenceStore()
        store.add_nodes(node for node in graph.backend.result.nodes if node.record_id != certificate.record_id)
        store.add_edges(graph.backend.result.edges)
        store.add_nodes((mismatched,))
        mismatched_graphs.append(replace(graph, store=store))
    return build_report(tuple(mismatched_graphs), effects, comparisons)


def graph_with_legacy_and_v2_numeric_collision() -> FrontierGraph:
    graph = _legacy_graph("direct")
    v2_virtual = _fixture_node(
        graph.bundle.compile_id,
        "virtual-register",
        "v2-numeric-collision",
        {"class": "r", "virtual": 40, "capture_run_id": "a" * 64},
    )
    v2_allocator = _fixture_node(
        graph.bundle.compile_id,
        "allocator-node",
        "v2-numeric-collision",
        {
            "class_id": 0,
            "ig_id": 40,
            "assigned_reg": 21,
            "capture_run_id": "a" * 64,
        },
    )
    v2_virtual = replace(
        v2_virtual,
        provenance=replace(v2_virtual.provenance, parser="mwcc-retro-backend-trace.v2"),
    )
    v2_allocator = replace(
        v2_allocator,
        provenance=replace(v2_allocator.provenance, parser="mwcc-retro-backend-trace.v2"),
    )
    v2_mapping = _fixture_edge(
        graph.bundle.compile_id,
        "maps-to-allocator-node",
        v2_virtual,
        v2_allocator,
        attributes={"capture_run_id": "a" * 64},
    )
    v2_mapping = replace(
        v2_mapping,
        provenance=replace(v2_mapping.provenance, parser="mwcc-retro-backend-trace.v2"),
    )
    store = InMemoryEvidenceStore()
    store.add_nodes((*graph.store.find_nodes(graph.bundle.compile_id), v2_virtual, v2_allocator))
    store.add_edges((*graph.store.find_edges(graph.bundle.compile_id), v2_mapping))
    return replace(graph, store=store)


def legacy_roots(graph: FrontierGraph) -> tuple[str, ...]:
    return tuple(
        node.record_id
        for node in graph.store.find_nodes(graph.bundle.compile_id, "allocator-node")
        if node.provenance.parser != "mwcc-retro-backend-trace.v2" and "capture_run_id" not in node.attributes
    )
