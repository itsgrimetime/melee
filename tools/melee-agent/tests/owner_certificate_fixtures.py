from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, TypeVar

import pytest
from tools.mwcc_retro.backend_object_bindings import ObjectBindingValidation
from tools.mwcc_retro.backend_pcode_lineage import (
    AnchorVirtualBinding,
    PCodeLineageValidation,
)

from src.mwcc_debug.causal_diff import backend_adapter
from src.mwcc_debug.causal_diff.bundles import ValidatedBundle
from src.mwcc_debug.causal_diff.canonical import canonical_bytes
from src.mwcc_debug.causal_diff.models import EvidenceEdge, EvidenceNode
from src.mwcc_debug.causal_diff.object_binding_adapter import (
    ObjectBindingAdapterInput,
    ObjectBindingEvidence,
    emit_object_binding_evidence,
)
from src.mwcc_debug.causal_diff.owner_certificate import OwnerRoleKey
from src.mwcc_debug.causal_diff.store import InMemoryEvidenceStore
from tests.test_causal_diff_object_bindings import (
    _adapter_input,
    _object_result,
    _pcode_result,
    _verified_bundle,
)

_T = TypeVar("_T")

STORE_FACTORIES = (pytest.param(InMemoryEvidenceStore, id="in-memory"),)


def only(items: Iterable[_T]) -> _T:
    values = tuple(items)
    if len(values) != 1:
        raise AssertionError(f"expected exactly one item, found {len(values)}")
    return values[0]


def complete_evidence(**adapter_overrides: object) -> ObjectBindingEvidence:
    return emit_object_binding_evidence(_adapter_input(**adapter_overrides))


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
) -> ObjectBindingEvidence:
    base_object = _object_result()
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
                                "operands": tuple(
                                    reversed(tuple(group["operands"]))
                                ),
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
    source: ObjectBindingAdapterInput = replace(
        _adapter_input(),
        object_validation=object_validation,
        pcode_validation=pcode_validation,
        instrumentation_identity=instrumentation_identity,
    )
    return emit_object_binding_evidence(source)


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
    changed = lineage_support.with_attributes(
        {**lineage_support.attributes, "parent_lineage_ids": parents}
    )
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
    changed = lineage_support.with_attributes(
        {**lineage_support.attributes, field: value}
    )
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
    return emit_object_binding_evidence(source)


def ambiguous_evidence(*, permuted: bool = False) -> ObjectBindingEvidence:
    paths = (
        _path(0, operand_key="use:0", semantic_stack_role="row-home"),
        _path(1, operand_key="use:0", semantic_stack_role="row-home"),
    )
    return _evidence_from_paths(paths, reverse_pcode_inputs=permuted)


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
    return emit_object_binding_evidence(source)


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
    return emit_object_binding_evidence(source)


def support(evidence: ObjectBindingEvidence, support_kind: str) -> EvidenceNode:
    return only(
        node
        for node in evidence.nodes
        if node.kind == "backend-support-record"
        and node.attributes.get("support_kind") == support_kind
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
