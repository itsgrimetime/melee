"""Adapt independently verified retail ObjObject/PCode evidence."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

# Retail producer validators live beside the installed melee-agent package in
# the repository checkout (the established debug-retro import boundary).
_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.mwcc_retro import struct_map  # noqa: E402
from tools.mwcc_retro.backend_instrumentation_proof import trusted_proof_from_trace
from tools.mwcc_retro.backend_object_bindings import (
    ObjectBindingValidation,
    validate_object_bindings,
)
from tools.mwcc_retro.backend_pcode_lineage import (
    PCodeLineageValidation,
    validate_pcode_lineage,
)
from tools.mwcc_retro.backend_trace_assembler import verify_backend_trace_v2
from tools.mwcc_retro.struct_map import INSTRUMENTATION_PROOF_SCHEMA

from .bundles import BundleInputError, ValidatedBundle
from .models import Confidence, EvidenceEdge, EvidenceNode, Provenance

_PARSER = "mwcc-retro-backend-trace.v2"
_COMPILER_OBJECT = "compiler-object-bindings"
_OBJECT_VIRTUAL = "object-to-virtual"
_OBJECT_FRAME = "object-to-frame"
_PCODE_RANGE = "pcode-to-code-range"
_REQUIRED_OWNER_CAPABILITIES = frozenset({_COMPILER_OBJECT, _OBJECT_VIRTUAL, _OBJECT_FRAME, _PCODE_RANGE})
OwnerInstrumentationIdentity = tuple[str, str, str, str]
_OBJECT_BINDING_ADAPTER_TOKEN = object()


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_physical(value: object) -> bool:
    return _is_int(value) and 0 <= value <= 31


def _is_string_tuple(value: object) -> bool:
    return (
        isinstance(value, tuple)
        and all(_is_nonempty_str(item) for item in value)
        and value == tuple(sorted(set(value)))
    )


def _is_lineage_side(value: object) -> bool:
    return isinstance(value, str) and value in {"inputs", "outputs"}


@dataclass(frozen=True, slots=True)
class ObjectBindingAdapterInput:
    compile_id: str
    function: str
    artifact_sha256: str
    capture_run_id: str
    artifact_size: int
    capabilities: frozenset[str]
    object_validation: ObjectBindingValidation
    pcode_validation: PCodeLineageValidation
    instrumentation_identity: OwnerInstrumentationIdentity | None = None


@dataclass(frozen=True, slots=True)
class ObjectBindingEvidence:
    nodes: tuple[EvidenceNode, ...]
    edges: tuple[EvidenceEdge, ...]
    capabilities: frozenset[str]
    capture_run_id: str
    instrumentation_identity: OwnerInstrumentationIdentity | None
    _adapter_token: object | None = field(default=None, init=False, repr=False, compare=False)

    @property
    def verified_capabilities(self) -> frozenset[str]:
        return self.capabilities

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("ObjectBindingEvidence is runtime-final")


def _is_lower_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _valid_owner_instrumentation_identity(value: object) -> bool:
    return (
        type(value) is tuple
        and len(value) == 4
        and _is_lower_sha256(value[0])
        and type(value[1]) is str
        and bool(value[1])
        and _is_lower_sha256(value[2])
        and type(value[3]) is str
        and value[3] == INSTRUMENTATION_PROOF_SCHEMA
    )


def _confidence(value: object, default: Confidence) -> Confidence:
    try:
        return Confidence(str(value))
    except ValueError:
        return default


def _provenance(
    source: ObjectBindingAdapterInput,
    rule: str,
    inputs: tuple[EvidenceNode | EvidenceEdge, ...] = (),
) -> Provenance:
    return Provenance(
        artifact_sha256=source.artifact_sha256,
        parser=_PARSER,
        raw_start=0,
        raw_end=source.artifact_size,
        derivation_rule=rule,
        input_record_ids=tuple(record.record_id for record in inputs),
    )


def _node(
    source: ObjectBindingAdapterInput,
    *,
    kind: str,
    local_id: object,
    confidence: Confidence,
    attributes: Mapping[str, object],
    role_key: str | None = None,
    rule: str = "normalize-verified-retail-record",
    support: tuple[EvidenceNode | EvidenceEdge, ...] = (),
) -> EvidenceNode:
    return EvidenceNode.create(
        compile_id=source.compile_id,
        function=source.function,
        kind=kind,
        local_key=(source.capture_run_id, local_id),
        role_key=role_key,
        producer_confidence=confidence,
        adapter_confidence=Confidence.OBSERVED,
        provenance=_provenance(source, rule, support),
        input_confidences=tuple(record.confidence for record in support),
        attributes={"capture_run_id": source.capture_run_id, **attributes},
    )


def _edge(
    source: ObjectBindingAdapterInput,
    *,
    kind: str,
    left: EvidenceNode,
    right: EvidenceNode,
    ordinal: int,
    producer_confidence: Confidence,
    adapter_confidence: Confidence,
    rule: str,
    attributes: Mapping[str, object],
    support: tuple[EvidenceNode | EvidenceEdge, ...] = (),
) -> EvidenceEdge:
    inputs: dict[str, EvidenceNode | EvidenceEdge] = {
        left.record_id: left,
        right.record_id: right,
    }
    for record in support:
        inputs.setdefault(record.record_id, record)
    ordered_inputs = tuple(inputs.values())
    return EvidenceEdge.create(
        compile_id=source.compile_id,
        function=source.function,
        kind=kind,
        source_id=left.record_id,
        target_id=right.record_id,
        occurrence_ordinal=ordinal,
        producer_confidence=producer_confidence,
        adapter_confidence=adapter_confidence,
        provenance=_provenance(source, rule, ordered_inputs),
        input_confidences=tuple(record.confidence for record in ordered_inputs),
        attributes={"capture_run_id": source.capture_run_id, **attributes},
    )


def _rows(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(row for row in value if isinstance(row, Mapping))


def _capture_run_id(result: ObjectBindingValidation) -> str:
    value = result.normalized.get("capture_run_id")
    return value if isinstance(value, str) else ""


def _deduplicate_nodes(nodes: list[EvidenceNode]) -> tuple[EvidenceNode, ...]:
    by_id: dict[str, EvidenceNode] = {}
    for node in nodes:
        previous = by_id.get(node.record_id)
        if previous is not None and previous != node:
            raise BundleInputError(f"conflicting object-binding node {node.record_id}")
        by_id.setdefault(node.record_id, node)
    return tuple(by_id[key] for key in sorted(by_id))


def _deduplicate_edges(edges: list[EvidenceEdge]) -> tuple[EvidenceEdge, ...]:
    by_id: dict[str, EvidenceEdge] = {}
    for edge in edges:
        previous = by_id.get(edge.record_id)
        if previous is not None and previous != edge:
            raise BundleInputError(f"conflicting object-binding edge {edge.record_id}")
        by_id.setdefault(edge.record_id, edge)
    return tuple(by_id[key] for key in sorted(by_id))


def _lineage_ids(validation: PCodeLineageValidation) -> tuple[str, ...]:
    values: set[str] = set()
    for binding in validation.anchor_bindings.values():
        values.add(binding.operand_lineage_id)
    for event in _rows(validation.normalized.get("pcode_operand_lineage_events")):
        for side in ("inputs", "outputs"):
            for state in _rows(event.get(side)):
                for operand in _rows(state.get("operands")):
                    lineage = operand.get("operand_lineage_id")
                    if isinstance(lineage, str) and lineage:
                        values.add(lineage)
                    parents = operand.get("parent_lineage_ids")
                    if isinstance(parents, (list, tuple)):
                        values.update(parent for parent in parents if isinstance(parent, str) and parent)
    return tuple(sorted(values))


def emit_object_binding_evidence(
    source: ObjectBindingAdapterInput,
) -> ObjectBindingEvidence:
    """Purely emit records from already validated, detached results."""

    if source.object_validation.errors or source.pcode_validation.errors:
        raise BundleInputError("object binding evidence requires successful validators")
    if _capture_run_id(source.object_validation) != source.capture_run_id:
        raise BundleInputError("object binding capture run mismatch")

    capabilities = frozenset(source.capabilities)
    if not capabilities:
        return ObjectBindingEvidence(
            (),
            (),
            capabilities,
            source.capture_run_id,
            source.instrumentation_identity,
        )
    nodes: list[EvidenceNode] = []
    edges: list[EvidenceEdge] = []
    by_object: dict[str, EvidenceNode] = {}
    by_pcode: dict[str, EvidenceNode] = {}
    by_lineage: dict[str, EvidenceNode] = {}
    by_virtual: dict[tuple[int, int], EvidenceNode] = {}
    pcode_generation_support: dict[str, EvidenceNode] = {}
    pcode_range_support: dict[tuple[str, int], EvidenceNode] = {}
    emission_support: dict[tuple[str, str, int, str], tuple[EvidenceNode, ...]] = {}
    rewrite_support: dict[tuple[object, ...], EvidenceNode] = {}
    lineage_support: dict[str, list[EvidenceNode]] = {}

    def support_node(
        capability: str,
        support_kind: str,
        local_id: object,
        attributes: Mapping[str, object],
        confidence: Confidence = Confidence.OBSERVED,
    ) -> EvidenceNode | None:
        if capability not in capabilities:
            return None
        node = _node(
            source,
            kind="backend-support-record",
            local_id=("support", support_kind, local_id),
            confidence=confidence,
            attributes={
                "verified_capability": capability,
                "support_kind": support_kind,
                **attributes,
            },
            rule="retain-exact-verified-backend-record",
        )
        nodes.append(node)
        return node

    if _COMPILER_OBJECT in capabilities:
        for row in _rows(source.object_validation.normalized.get("objects")):
            object_id = row.get("object_id")
            if not isinstance(object_id, str) or not object_id:
                continue
            snapshots = _rows(row.get("stage_snapshots"))
            if not snapshots:
                continue
            snapshot_support = tuple(
                support
                for index, snapshot in enumerate(snapshots)
                if (
                    support := support_node(
                        _COMPILER_OBJECT,
                        "object-stage-snapshot",
                        (object_id, index, snapshot.get("stage")),
                        {
                            "object_id": object_id,
                            "stage": snapshot.get("stage"),
                            "allocation_generation": snapshot.get("allocation_generation"),
                            "lifecycle_sequence_at_capture": snapshot.get("lifecycle_sequence_at_capture"),
                        },
                    )
                )
                is not None
            )
            confidence = (
                Confidence.DERIVED_UNIQUE
                if len(snapshots) == 2 and row.get("cross_stage_identity_confidence") == Confidence.DERIVED_UNIQUE
                else Confidence.OBSERVED
            )
            node = _node(
                source,
                kind="compiler-object",
                local_id=("object", object_id),
                confidence=confidence,
                attributes={
                    "object_id": object_id,
                    "allocation_generation": row.get("allocation_generation"),
                    "runtime_address": row.get("runtime_address"),
                    "type_size": row.get("type_size"),
                    "areas": tuple(row.get("areas", ())),
                    "stage_snapshots": tuple(row.get("stage_snapshots", ())),
                },
                support=snapshot_support,
            )
            nodes.append(node)
            by_object[object_id] = node

    if _PCODE_RANGE in capabilities:
        pcode_rows = _rows(source.pcode_validation.normalized.get("pcode_instructions"))
        pcode_generation_by_id = {
            str(row["pcode_id"]): row["allocation_generation"]
            for row in pcode_rows
            if _is_nonempty_str(row.get("pcode_id")) and _is_int(row.get("allocation_generation"))
        }
        for event_index, event in enumerate(
            _rows(source.pcode_validation.normalized.get("pcode_operand_lineage_events"))
        ):
            event_parent_ids = tuple(
                sorted(
                    {
                        str(parent_id)
                        for output in _rows(event.get("outputs"))
                        for operand in _rows(output.get("operands"))
                        for parent_id in operand.get("parent_lineage_ids", ())
                    }
                )
            )
            for side in ("inputs", "outputs"):
                for state in _rows(event.get(side)):
                    pcode_id = state.get("pcode_id")
                    allocation_generation = pcode_generation_by_id.get(str(pcode_id))
                    if allocation_generation is None:
                        continue
                    for operand in _rows(state.get("operands")):
                        lineage_id = operand.get("operand_lineage_id")
                        if not isinstance(lineage_id, str) or not lineage_id:
                            continue
                        support = support_node(
                            _PCODE_RANGE,
                            "pcode-lineage-event",
                            (event_index, side, pcode_id, lineage_id),
                            {
                                "pcode_id": pcode_id,
                                "allocation_generation": allocation_generation,
                                "event_index": event_index,
                                "side": side,
                                "mutation_kind": event.get("mutation_kind"),
                                "operand_lineage_id": lineage_id,
                                "parent_lineage_ids": (
                                    tuple(operand.get("parent_lineage_ids", ()))
                                    if side == "outputs"
                                    else event_parent_ids
                                ),
                            },
                        )
                        if support is not None:
                            lineage_support.setdefault(lineage_id, []).append(support)

        for lineage_id in _lineage_ids(source.pcode_validation):
            lineage = _node(
                source,
                kind="pcode-operand",
                local_id=("lineage", lineage_id),
                confidence=Confidence.OBSERVED,
                attributes={"operand_lineage_id": lineage_id},
                support=tuple(lineage_support.get(lineage_id, ())),
            )
            nodes.append(lineage)
            by_lineage[lineage_id] = lineage

        for row in pcode_rows:
            pcode_id = row.get("pcode_id")
            if not isinstance(pcode_id, str) or not pcode_id:
                continue
            generation = support_node(
                _PCODE_RANGE,
                "pcode-generation",
                (pcode_id, row.get("allocation_generation")),
                {
                    "pcode_id": pcode_id,
                    "allocation_generation": row.get("allocation_generation"),
                },
            )
            if generation is not None:
                pcode_generation_support[pcode_id] = generation
            for range_index, code_range in enumerate(_rows(row.get("code_ranges"))):
                range_support = support_node(
                    _PCODE_RANGE,
                    "pcode-code-range",
                    (pcode_id, range_index, code_range.get("start"), code_range.get("end_exclusive")),
                    {
                        "pcode_id": pcode_id,
                        "allocation_generation": row.get("allocation_generation"),
                        "start": code_range.get("start"),
                        "end_exclusive": code_range.get("end_exclusive"),
                    },
                )
                if range_support is not None and isinstance(code_range.get("start"), int):
                    pcode_range_support[(pcode_id, code_range["start"])] = range_support
                for mapping_index, mapping in enumerate(_rows(code_range.get("machine_operand_mappings"))):
                    operand_key = mapping.get("machine_operand_key")
                    lineage_id = mapping.get("operand_lineage_id")
                    offset = code_range.get("start")
                    if (
                        not isinstance(operand_key, str)
                        or not isinstance(lineage_id, str)
                        or not isinstance(offset, int)
                    ):
                        continue
                    emission = support_node(
                        _PCODE_RANGE,
                        "pcode-emission",
                        (pcode_id, range_index, mapping_index, operand_key),
                        {
                            "pcode_id": pcode_id,
                            "allocation_generation": row.get("allocation_generation"),
                            "code_offset": offset,
                            "machine_operand_key": operand_key,
                            "operand_lineage_id": lineage_id,
                            "physical_register": mapping.get("physical_register"),
                        },
                        Confidence.DERIVED_UNIQUE,
                    )
                    direct_lineage = support_node(
                        _PCODE_RANGE,
                        "pcode-lineage-event",
                        (pcode_id, range_index, mapping_index, lineage_id),
                        {
                            "pcode_id": pcode_id,
                            "allocation_generation": row.get("allocation_generation"),
                            "code_offset": offset,
                            "operand_lineage_id": lineage_id,
                            "event_kind": "emission-lineage",
                        },
                        Confidence.DERIVED_UNIQUE,
                    )
                    emission_support[(pcode_id, lineage_id, offset, operand_key)] = tuple(
                        item for item in (emission, direct_lineage) if item is not None
                    )
            node = _node(
                source,
                kind="retail-pcode",
                local_id=("pcode", pcode_id),
                confidence=_confidence(
                    row.get("cross_stage_identity_confidence"),
                    Confidence.DERIVED_UNIQUE,
                ),
                attributes={
                    "pcode_id": pcode_id,
                    "allocation_generation": row.get("allocation_generation"),
                    "runtime_address": row.get("runtime_address"),
                    "code_ranges": tuple(row.get("code_ranges", ())),
                },
                support=(() if generation is None else (generation,)),
            )
            nodes.append(node)
            by_pcode[pcode_id] = node

        rewrite_rows = _rows(source.pcode_validation.normalized.get("pcode_occurrences"))
        rewrites = {
            (
                row.get("pcode_id"),
                row.get("operand_lineage_id"),
                row.get("class_id"),
                row.get("virtual"),
            ): row
            for row in rewrite_rows
        }
        for rewrite_key, rewrite in rewrites.items():
            rewrite_generation = pcode_generation_by_id.get(str(rewrite.get("pcode_id")))
            if rewrite_generation is None:
                continue
            support = support_node(
                _PCODE_RANGE,
                "pcode-rewrite",
                rewrite_key,
                {
                    "pcode_id": rewrite.get("pcode_id"),
                    "allocation_generation": rewrite_generation,
                    "operand_lineage_id": rewrite.get("operand_lineage_id"),
                    "class_id": rewrite.get("class_id"),
                    "virtual": rewrite.get("virtual"),
                    "allocated_physical": rewrite.get("allocated_physical"),
                },
                _confidence(rewrite.get("confidence"), Confidence.HEURISTIC),
            )
            if support is not None:
                rewrite_support[rewrite_key] = support
        for ordinal, ((offset, operand_key), binding) in enumerate(
            sorted(source.pcode_validation.anchor_bindings.items())
        ):
            pcode = by_pcode.get(binding.pcode_id)
            lineage = by_lineage.get(binding.operand_lineage_id)
            if pcode is None or lineage is None:
                continue
            anchor = _node(
                source,
                kind="assembly-operand-anchor",
                local_id=("anchor", offset, operand_key),
                confidence=Confidence.DERIVED_UNIQUE,
                role_key=operand_key,
                attributes={
                    "code_offset": offset,
                    "machine_operand_key": operand_key,
                    "physical_register": binding.physical_register,
                },
                rule="verified-candidate-range-machine-operand-anchor",
                support=tuple(
                    item
                    for item in (
                        pcode_range_support.get((binding.pcode_id, offset)),
                        pcode_generation_support.get(binding.pcode_id),
                        *emission_support.get(
                            (
                                binding.pcode_id,
                                binding.operand_lineage_id,
                                offset,
                                operand_key,
                            ),
                            (),
                        ),
                    )
                    if item is not None
                ),
            )
            nodes.append(anchor)
            edges.append(
                _edge(
                    source,
                    kind="assembly-anchor-emitted-by-pcode",
                    left=anchor,
                    right=pcode,
                    ordinal=ordinal,
                    producer_confidence=Confidence.DERIVED_UNIQUE,
                    adapter_confidence=Confidence.DERIVED_UNIQUE,
                    rule="unique-candidate-range-to-same-run-pcode",
                    attributes={
                        "code_offset": offset,
                        "machine_operand_key": operand_key,
                    },
                    support=tuple(
                        item
                        for item in (
                            pcode_range_support.get((binding.pcode_id, offset)),
                            pcode_generation_support.get(binding.pcode_id),
                            *emission_support.get(
                                (
                                    binding.pcode_id,
                                    binding.operand_lineage_id,
                                    offset,
                                    operand_key,
                                ),
                                (),
                            ),
                        )
                        if item is not None
                    ),
                )
            )
            edges.append(
                _edge(
                    source,
                    kind="pcode-operand-lineage",
                    left=pcode,
                    right=lineage,
                    ordinal=ordinal,
                    producer_confidence=Confidence.DERIVED_UNIQUE,
                    adapter_confidence=Confidence.DERIVED_UNIQUE,
                    rule="unique-emission-operand-lineage",
                    attributes={
                        "code_offset": offset,
                        "machine_operand_key": operand_key,
                    },
                    support=emission_support.get(
                        (
                            binding.pcode_id,
                            binding.operand_lineage_id,
                            offset,
                            operand_key,
                        ),
                        (),
                    ),
                )
            )
            virtual_key = (binding.class_id, binding.virtual)
            virtual = by_virtual.get(virtual_key)
            if virtual is None:
                virtual = _node(
                    source,
                    kind="retail-virtual-register",
                    local_id=("virtual", *virtual_key),
                    confidence=Confidence.OBSERVED,
                    attributes={
                        "class_id": binding.class_id,
                        "class": "f" if binding.class_id == 1 else "r",
                        "virtual": binding.virtual,
                        "physical_register": binding.physical_register,
                    },
                )
                nodes.append(virtual)
                by_virtual[virtual_key] = virtual
            rewrite = rewrites.get(
                (
                    binding.pcode_id,
                    binding.operand_lineage_id,
                    binding.class_id,
                    binding.virtual,
                )
            )
            if rewrite is not None:
                edges.append(
                    _edge(
                        source,
                        kind="pcode-operand-uses-virtual",
                        left=lineage,
                        right=virtual,
                        ordinal=ordinal,
                        producer_confidence=_confidence(rewrite.get("confidence"), Confidence.HEURISTIC),
                        adapter_confidence=Confidence.OBSERVED,
                        rule="observed-same-run-allocator-rewrite-origin",
                        attributes={
                            "pcode_id": binding.pcode_id,
                            "operand_lineage_id": binding.operand_lineage_id,
                            "machine_operand_key": operand_key,
                        },
                        support=(
                            ()
                            if rewrite_support.get(
                                (
                                    binding.pcode_id,
                                    binding.operand_lineage_id,
                                    binding.class_id,
                                    binding.virtual,
                                )
                            )
                            is None
                            else (
                                rewrite_support[
                                    (
                                        binding.pcode_id,
                                        binding.operand_lineage_id,
                                        binding.class_id,
                                        binding.virtual,
                                    )
                                ],
                            )
                        ),
                    )
                )

        lineage_ordinal = len(edges)
        for event_index, event in enumerate(
            _rows(source.pcode_validation.normalized.get("pcode_operand_lineage_events"))
        ):
            for state in _rows(event.get("outputs")):
                for operand in _rows(state.get("operands")):
                    child_id = operand.get("operand_lineage_id")
                    parents = operand.get("parent_lineage_ids")
                    if not isinstance(child_id, str) or not isinstance(parents, (list, tuple)):
                        continue
                    child = by_lineage.get(child_id)
                    if child is None:
                        continue
                    for parent_id in parents:
                        parent = by_lineage.get(str(parent_id))
                        if parent is None:
                            continue
                        edges.append(
                            _edge(
                                source,
                                kind="pcode-operand-lineage",
                                left=parent,
                                right=child,
                                ordinal=lineage_ordinal,
                                producer_confidence=Confidence.OBSERVED,
                                adapter_confidence=Confidence.OBSERVED,
                                rule="observed-pcode-mutation-lineage",
                                attributes={
                                    "event_index": event_index,
                                    "lineage_event_side": "outputs",
                                    "mutation_kind": event.get("mutation_kind"),
                                    "parent_lineage_id": parent_id,
                                    "operand_lineage_id": child_id,
                                    "parent_lineage_ids": tuple(parents),
                                },
                                support=tuple(
                                    {
                                        support.record_id: support
                                        for support in (
                                            *lineage_support.get(str(parent_id), ()),
                                            *lineage_support.get(child_id, ()),
                                        )
                                    }.values()
                                ),
                            )
                        )
                        lineage_ordinal += 1

    if _OBJECT_VIRTUAL in capabilities:
        for ordinal, row in enumerate(_rows(source.object_validation.normalized.get("virtual_bindings"))):
            object_node = by_object.get(str(row.get("object_id")))
            class_id = row.get("class_id")
            virtual_number = row.get("virtual")
            if (
                object_node is None
                or not isinstance(class_id, int)
                or isinstance(class_id, bool)
                or not isinstance(virtual_number, int)
                or isinstance(virtual_number, bool)
            ):
                continue
            key = (class_id, virtual_number)
            binding_support = support_node(
                _OBJECT_VIRTUAL,
                "object-virtual-binding",
                (row.get("object_id"), class_id, virtual_number, row.get("ig_id")),
                {
                    "object_id": row.get("object_id"),
                    "allocation_generation": object_node.attributes.get("allocation_generation"),
                    "class_id": class_id,
                    "virtual": virtual_number,
                    "ig_id": row.get("ig_id"),
                },
                _confidence(row.get("confidence"), Confidence.HEURISTIC),
            )
            allocator_origin_support = tuple(
                support
                for support in rewrite_support.values()
                if support.attributes.get("class_id") == class_id
                and support.attributes.get("virtual") == virtual_number
            )
            assigned_physicals = {
                support.attributes.get("allocated_physical")
                for support in allocator_origin_support
                if _is_physical(support.attributes.get("allocated_physical"))
            }
            assigned_physical = next(iter(assigned_physicals)) if len(assigned_physicals) == 1 else None
            allocator_support = (() if binding_support is None else (binding_support,)) + allocator_origin_support
            virtual = by_virtual.get(key)
            if virtual is None:
                virtual = _node(
                    source,
                    kind="retail-virtual-register",
                    local_id=("virtual", *key),
                    confidence=Confidence.OBSERVED,
                    attributes={
                        "class_id": class_id,
                        "class": row.get("virtual_kind"),
                        "virtual": virtual_number,
                    },
                    support=(() if binding_support is None else (binding_support,)),
                )
                nodes.append(virtual)
                by_virtual[key] = virtual
            confidence = _confidence(row.get("confidence"), Confidence.HEURISTIC)
            edges.append(
                _edge(
                    source,
                    kind="object-materializes-virtual",
                    left=object_node,
                    right=virtual,
                    ordinal=ordinal,
                    producer_confidence=confidence,
                    adapter_confidence=Confidence.OBSERVED,
                    rule="observed-exhaustive-object-virtual-binding",
                    attributes={
                        "object_id": row.get("object_id"),
                        "class_id": class_id,
                        "virtual": virtual_number,
                        "ig_id": row.get("ig_id"),
                        "ignode_runtime_address": row.get("ignode_runtime_address"),
                    },
                    support=(() if binding_support is None else (binding_support,)),
                )
            )
            allocator = _node(
                source,
                kind="allocator-node",
                local_id=("allocator", class_id, row.get("ig_id")),
                confidence=Confidence.OBSERVED,
                attributes={
                    "class_id": class_id,
                    "ig_id": row.get("ig_id"),
                    "virtual": virtual_number,
                    "assigned_phys": assigned_physical,
                },
                support=allocator_support,
            )
            nodes.append(allocator)
            edges.append(
                _edge(
                    source,
                    kind="maps-to-allocator-node",
                    left=virtual,
                    right=allocator,
                    ordinal=ordinal,
                    producer_confidence=confidence,
                    adapter_confidence=Confidence.DERIVED_UNIQUE,
                    rule="unique-verified-object-virtual-ig-binding",
                    attributes={
                        "class_id": class_id,
                        "ig_id": row.get("ig_id"),
                        "assigned_phys": assigned_physical,
                    },
                    support=allocator_support,
                )
            )

    if _OBJECT_FRAME in capabilities:
        for ordinal, row in enumerate(_rows(source.object_validation.normalized.get("frame_bindings"))):
            object_node = by_object.get(str(row.get("object_id")))
            if object_node is None:
                continue
            area = str(row.get("area"))
            role = str(row.get("semantic_stack_role") or row.get("object_id"))
            frame_support = support_node(
                _OBJECT_FRAME,
                "object-frame-binding",
                (row.get("object_id"), area),
                {
                    "object_id": row.get("object_id"),
                    "allocation_generation": object_node.attributes.get("allocation_generation"),
                    "area": area,
                    "semantic_stack_role": role,
                    "final_r1_offset": row.get("final_r1_offset"),
                    "size": row.get("size"),
                },
                _confidence(row.get("confidence"), Confidence.HEURISTIC),
            )
            stack = _node(
                source,
                kind="stack-object",
                local_id=("stack-home", row.get("object_id"), area),
                confidence=Confidence.DERIVED_UNIQUE,
                role_key=role,
                attributes={
                    "side": "current",
                    "area": area,
                    "symbol": role,
                    "start": row.get("final_r1_offset"),
                    "offset": row.get("final_r1_offset"),
                    "size": row.get("size"),
                    "list_node_runtime_address": row.get("list_node_runtime_address"),
                },
                support=(() if frame_support is None else (frame_support,)),
            )
            nodes.append(stack)
            edges.append(
                _edge(
                    source,
                    kind="object-has-stack-home",
                    left=object_node,
                    right=stack,
                    ordinal=ordinal,
                    producer_confidence=_confidence(row.get("confidence"), Confidence.HEURISTIC),
                    adapter_confidence=Confidence.DERIVED_UNIQUE,
                    rule="unique-verified-final-frame-home",
                    attributes={"area": area, "semantic_stack_role": role},
                    support=(() if frame_support is None else (frame_support,)),
                )
            )

    normalized = ObjectBindingEvidence(
        _deduplicate_nodes(nodes),
        _deduplicate_edges(edges),
        capabilities,
        source.capture_run_id,
        source.instrumentation_identity,
    )
    return normalized


def _verified_function_payload(payload: Mapping[str, object], function: str) -> Mapping[str, object]:
    matches = tuple(row for row in _rows(payload.get("functions")) if row.get("name") == function)
    if len(matches) != 1:
        raise BundleInputError(f"backend trace v2 expected one function {function!r}, found {len(matches)}")
    return matches[0]


def adapt_object_bindings(bundle: ValidatedBundle) -> ObjectBindingEvidence:
    """Reload and independently verify one v2 trace/candidate pair."""

    trace_paths = bundle.backend_paths("backend-trace.v2")
    if not trace_paths:
        return ObjectBindingEvidence((), (), frozenset(), "", None)
    if len(trace_paths) != 1:
        raise BundleInputError("object binding adapter requires exactly one backend trace v2")
    candidate_path = bundle.candidate_object_path
    if candidate_path is None:
        raise BundleInputError("backend trace v2 requires one candidate object")
    trace_path = trace_paths[0]
    try:
        raw_bytes = Path(trace_path).read_bytes()
        payload = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        candidate_bytes = Path(candidate_path).read_bytes()
        installed_table = struct_map.load_gc125n_struct_map()
        verification = verify_backend_trace_v2(
            payload,
            candidate_bytes=candidate_bytes,
            function=bundle.manifest.function,
            struct_map=installed_table,
        )
        function_payload = _verified_function_payload(verification.payload, bundle.manifest.function)
        bindings = function_payload.get("object_bindings")
        if not isinstance(bindings, Mapping):
            raise ValueError("verified function has no object bindings")
        proof = trusted_proof_from_trace(
            verification.payload,
            bundle.manifest.function,
            installed_table,
        )
        object_result = validate_object_bindings(bindings, proof)
        lineage_result = validate_pcode_lineage(
            bindings,
            proof,
            candidate_path,
            bundle.manifest.function,
        )
        capture_run_id = bindings.get("capture_run_id")
        if not isinstance(capture_run_id, str) or not capture_run_id:
            raise ValueError("verified bindings have no capture run ID")
        instrumentation_identity = (
            proof.compiler_executable_sha256,
            proof.proof_id,
            proof.sha256,
            installed_table["instrumentation_proof_schema"],
        )
        if not _valid_owner_instrumentation_identity(instrumentation_identity):
            raise ValueError("verified instrumentation identity is malformed")
    except BundleInputError:
        raise
    except (
        OSError,
        OverflowError,
        RecursionError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise BundleInputError(f"invalid backend trace v2: {error}") from error

    artifact_sha256 = next(
        reference.sha256 for reference in bundle.manifest.artifacts.backend if reference.format == "backend-trace.v2"
    )
    evidence = emit_object_binding_evidence(
        ObjectBindingAdapterInput(
            compile_id=bundle.compile_id,
            function=bundle.manifest.function,
            artifact_sha256=artifact_sha256,
            capture_run_id=capture_run_id,
            artifact_size=len(raw_bytes),
            capabilities=verification.capabilities,
            object_validation=object_result,
            pcode_validation=lineage_result,
            instrumentation_identity=instrumentation_identity,
        )
    )
    object.__setattr__(evidence, "_adapter_token", _OBJECT_BINDING_ADAPTER_TOKEN)
    return evidence


__all__ = [
    "ObjectBindingAdapterInput",
    "ObjectBindingEvidence",
    "adapt_object_bindings",
    "emit_object_binding_evidence",
]
