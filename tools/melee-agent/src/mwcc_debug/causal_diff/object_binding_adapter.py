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

from .bundles import BundleInputError, ValidatedBundle
from .models import Confidence, EvidenceEdge, EvidenceNode, Provenance

_PARSER = "mwcc-retro-backend-trace.v2"
_COMPILER_OBJECT = "compiler-object-bindings"
_OBJECT_VIRTUAL = "object-to-virtual"
_OBJECT_FRAME = "object-to-frame"
_PCODE_RANGE = "pcode-to-code-range"
_REQUIRED_OWNER_CAPABILITIES = frozenset({_COMPILER_OBJECT, _OBJECT_VIRTUAL, _OBJECT_FRAME, _PCODE_RANGE})
_PROOF_CONFIDENCES = frozenset({Confidence.OBSERVED, Confidence.DERIVED_UNIQUE})
_OWNER_NODE_CAPABILITIES = {
    "assembly-operand-anchor": _PCODE_RANGE,
    "retail-pcode": _PCODE_RANGE,
    "pcode-operand": _PCODE_RANGE,
    "retail-virtual-register": _PCODE_RANGE,
    "compiler-object": _COMPILER_OBJECT,
    "allocator-node": _OBJECT_VIRTUAL,
    "stack-object": _OBJECT_FRAME,
}
_OWNER_EDGE_SCHEMAS = {
    "assembly-anchor-emitted-by-pcode": (
        _PCODE_RANGE,
        frozenset({"assembly-operand-anchor"}),
        frozenset({"retail-pcode"}),
    ),
    "pcode-operand-lineage": (
        _PCODE_RANGE,
        frozenset({"retail-pcode", "pcode-operand"}),
        frozenset({"pcode-operand"}),
    ),
    "pcode-operand-uses-virtual": (
        _PCODE_RANGE,
        frozenset({"pcode-operand"}),
        frozenset({"retail-virtual-register"}),
    ),
    "object-materializes-virtual": (
        _OBJECT_VIRTUAL,
        frozenset({"compiler-object"}),
        frozenset({"retail-virtual-register"}),
    ),
    "maps-to-allocator-node": (
        _OBJECT_VIRTUAL,
        frozenset({"retail-virtual-register"}),
        frozenset({"allocator-node"}),
    ),
    "object-has-stack-home": (
        _OBJECT_FRAME,
        frozenset({"compiler-object"}),
        frozenset({"stack-object"}),
    ),
}
_EXACT_V2_OWNER_EDGE_KINDS = frozenset(_OWNER_EDGE_SCHEMAS)
_SUPPORT_CAPABILITIES = {
    "object-stage-snapshot": _COMPILER_OBJECT,
    "pcode-generation": _PCODE_RANGE,
    "pcode-code-range": _PCODE_RANGE,
    "pcode-emission": _PCODE_RANGE,
    "pcode-rewrite": _PCODE_RANGE,
    "pcode-lineage-event": _PCODE_RANGE,
    "object-virtual-binding": _OBJECT_VIRTUAL,
    "object-frame-binding": _OBJECT_FRAME,
}
_REQUIRED_EDGE_SUPPORT_KINDS = {
    "assembly-anchor-emitted-by-pcode": frozenset({"pcode-generation", "pcode-code-range", "pcode-emission"}),
    "pcode-operand-uses-virtual": frozenset({"pcode-rewrite"}),
    "object-materializes-virtual": frozenset({"object-virtual-binding"}),
    "maps-to-allocator-node": frozenset({"object-virtual-binding", "pcode-rewrite"}),
    "object-has-stack-home": frozenset({"object-frame-binding"}),
}
_REQUIRED_NODE_SUPPORT_KINDS = {
    "allocator-node": frozenset({"object-virtual-binding", "pcode-rewrite"}),
}
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


_BASE_SUPPORT_SCHEMA = {
    "capture_run_id": _is_nonempty_str,
    "verified_capability": _is_nonempty_str,
    "support_kind": _is_nonempty_str,
}


def _support_schema(**fields):
    return {**_BASE_SUPPORT_SCHEMA, **fields}


_SUPPORT_ATTRIBUTE_SCHEMAS = {
    "object-stage-snapshot": (
        _support_schema(
            object_id=_is_nonempty_str,
            stage=_is_nonempty_str,
            allocation_generation=_is_int,
            lifecycle_sequence_at_capture=_is_int,
        ),
    ),
    "pcode-generation": (
        _support_schema(
            pcode_id=_is_nonempty_str,
            allocation_generation=_is_int,
        ),
    ),
    "pcode-code-range": (
        _support_schema(
            pcode_id=_is_nonempty_str,
            allocation_generation=_is_int,
            start=_is_int,
            end_exclusive=_is_int,
        ),
    ),
    "pcode-emission": (
        _support_schema(
            pcode_id=_is_nonempty_str,
            allocation_generation=_is_int,
            code_offset=_is_int,
            machine_operand_key=_is_nonempty_str,
            operand_lineage_id=_is_nonempty_str,
            physical_register=_is_physical,
        ),
    ),
    "pcode-rewrite": (
        _support_schema(
            pcode_id=_is_nonempty_str,
            allocation_generation=_is_int,
            operand_lineage_id=_is_nonempty_str,
            class_id=_is_int,
            virtual=_is_int,
            allocated_physical=_is_physical,
        ),
    ),
    "pcode-lineage-event": (
        _support_schema(
            pcode_id=_is_nonempty_str,
            allocation_generation=_is_int,
            code_offset=_is_int,
            operand_lineage_id=_is_nonempty_str,
            event_kind=lambda value: value == "emission-lineage",
        ),
        _support_schema(
            pcode_id=_is_nonempty_str,
            allocation_generation=_is_int,
            event_index=_is_int,
            side=_is_lineage_side,
            mutation_kind=_is_nonempty_str,
            operand_lineage_id=_is_nonempty_str,
            parent_lineage_ids=_is_string_tuple,
        ),
    ),
    "object-virtual-binding": (
        _support_schema(
            object_id=_is_nonempty_str,
            allocation_generation=_is_int,
            class_id=_is_int,
            virtual=_is_int,
            ig_id=_is_int,
        ),
    ),
    "object-frame-binding": (
        _support_schema(
            object_id=_is_nonempty_str,
            allocation_generation=_is_int,
            area=_is_nonempty_str,
            semantic_stack_role=_is_nonempty_str,
            final_r1_offset=_is_int,
            size=_is_int,
        ),
    ),
}


def _support_attributes_are_typed(
    support_kind: object,
    attributes: Mapping[str, object],
) -> bool:
    schemas = _SUPPORT_ATTRIBUTE_SCHEMAS.get(support_kind)
    if schemas is None:
        return False
    return any(
        set(attributes) == set(schema) and all(predicate(attributes[key]) for key, predicate in schema.items())
        for schema in schemas
    )


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
    abstention_reason: str | None
    instrumentation_identity: OwnerInstrumentationIdentity | None
    _adapter_token: object | None = field(default=None, repr=False, compare=False)

    @property
    def verified_capabilities(self) -> frozenset[str]:
        return self.capabilities


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
            "backend-owner-path-incomplete",
            source.instrumentation_identity,
            _OBJECT_BINDING_ADAPTER_TOKEN,
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
        None,
        source.instrumentation_identity,
        _OBJECT_BINDING_ADAPTER_TOKEN,
    )
    if not proof_complete(normalized):
        return ObjectBindingEvidence(
            normalized.nodes,
            normalized.edges,
            normalized.capabilities,
            normalized.capture_run_id,
            "backend-owner-path-incomplete",
            normalized.instrumentation_identity,
            _OBJECT_BINDING_ADAPTER_TOKEN,
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
        return ObjectBindingEvidence((), (), frozenset(), "", None, None)
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
            str(installed_table["instrumentation_proof_schema"]),
        )
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
    return emit_object_binding_evidence(
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


def proof_complete(
    evidence: ObjectBindingEvidence,
    required_record_ids: frozenset[str] = frozenset(),
) -> bool:
    """Require every positive same-run owner segment and its exact capability."""

    if not _REQUIRED_OWNER_CAPABILITIES <= evidence.capabilities:
        return False
    required = {
        "assembly-anchor-emitted-by-pcode",
        "pcode-operand-lineage",
        "pcode-operand-uses-virtual",
        "object-materializes-virtual",
        "maps-to-allocator-node",
        "object-has-stack-home",
    }
    by_kind = {edge.kind for edge in evidence.edges}
    if not required <= by_kind:
        return False
    eligible = tuple(
        edge for edge in evidence.edges if edge.kind in required and exact_owner_path_record(evidence, edge)
    )
    if len(eligible) < len(required):
        return False
    nodes = {node.record_id: node for node in evidence.nodes}
    by_kind: dict[str, tuple[EvidenceEdge, ...]] = {
        kind: tuple(edge for edge in eligible if edge.kind == kind) for kind in required
    }
    for anchor_edge in by_kind["assembly-anchor-emitted-by-pcode"]:
        anchor = nodes.get(anchor_edge.source_id)
        pcode = nodes.get(anchor_edge.target_id)
        if anchor is None or pcode is None:
            continue
        if not all(exact_owner_path_record(evidence, node) for node in (anchor, pcode)):
            continue
        for lineage_edge in by_kind["pcode-operand-lineage"]:
            if lineage_edge.source_id != anchor_edge.target_id:
                continue
            lineage = nodes.get(lineage_edge.target_id)
            if lineage is None or not exact_owner_path_record(evidence, lineage):
                continue
            for virtual_edge in by_kind["pcode-operand-uses-virtual"]:
                if virtual_edge.source_id != lineage_edge.target_id:
                    continue
                virtual_id = virtual_edge.target_id
                virtual = nodes.get(virtual_id)
                if virtual is None or not exact_owner_path_record(evidence, virtual):
                    continue
                object_edges = tuple(
                    edge for edge in by_kind["object-materializes-virtual"] if edge.target_id == virtual_id
                )
                allocator_edges = tuple(
                    edge for edge in by_kind["maps-to-allocator-node"] if edge.source_id == virtual_id
                )
                for object_edge in object_edges:
                    owner = nodes.get(object_edge.source_id)
                    frame_edges = tuple(
                        frame_edge
                        for frame_edge in by_kind["object-has-stack-home"]
                        if frame_edge.source_id == object_edge.source_id
                    )
                    if owner is None or not exact_owner_path_record(evidence, owner):
                        continue
                    for allocator_edge in allocator_edges:
                        allocator = nodes.get(allocator_edge.target_id)
                        if allocator is None or not exact_owner_path_record(evidence, allocator):
                            continue
                        for frame_edge in frame_edges:
                            stack = nodes.get(frame_edge.target_id)
                            if stack is None or not exact_owner_path_record(evidence, stack):
                                continue
                            path_record_ids = {
                                record.record_id
                                for record in (
                                    anchor,
                                    anchor_edge,
                                    pcode,
                                    lineage_edge,
                                    lineage,
                                    virtual_edge,
                                    virtual,
                                    object_edge,
                                    owner,
                                    allocator_edge,
                                    allocator,
                                    frame_edge,
                                    stack,
                                )
                            }
                            if required_record_ids <= path_record_ids:
                                return True
    return False


def _matching_nodes(
    nodes: Mapping[str, EvidenceNode],
    kind: str,
    **attributes: object,
) -> tuple[EvidenceNode, ...]:
    return tuple(
        node
        for node in nodes.values()
        if node.kind == kind and all(node.attributes.get(key) == value for key, value in attributes.items())
    )


def _support_topology_is_exact(
    evidence: ObjectBindingEvidence,
    support: EvidenceNode,
    dependent: EvidenceNode | EvidenceEdge,
    nodes: Mapping[str, EvidenceNode],
) -> bool:
    attributes = support.attributes
    support_kind = attributes["support_kind"]
    if support_kind == "object-stage-snapshot":
        if dependent.kind != "compiler-object":
            return False
        snapshots = _rows(dependent.attributes.get("stage_snapshots"))
        return (
            dependent.attributes.get("object_id") == attributes["object_id"]
            and dependent.attributes.get("allocation_generation") == attributes["allocation_generation"]
            and any(
                snapshot.get("stage") == attributes["stage"]
                and snapshot.get("allocation_generation") == attributes["allocation_generation"]
                and snapshot.get("lifecycle_sequence_at_capture") == attributes["lifecycle_sequence_at_capture"]
                for snapshot in snapshots
            )
        )

    if support_kind.startswith("pcode-"):
        pcode_nodes = _matching_nodes(
            nodes,
            "retail-pcode",
            pcode_id=attributes["pcode_id"],
            allocation_generation=attributes["allocation_generation"],
        )
        if len(pcode_nodes) != 1:
            return False
        pcode = pcode_nodes[0]
        anchor_edges = tuple(
            edge
            for edge in evidence.edges
            if edge.kind == "assembly-anchor-emitted-by-pcode" and edge.target_id == pcode.record_id
        )
        if support_kind == "pcode-generation":
            topology_ids = {pcode.record_id}
            topology_ids.update(edge.record_id for edge in anchor_edges)
            topology_ids.update(edge.source_id for edge in anchor_edges)
            return dependent.record_id in topology_ids

        if support_kind == "pcode-code-range":
            start = attributes["start"]
            end_exclusive = attributes["end_exclusive"]
            raw_ranges = _rows(pcode.attributes.get("code_ranges"))
            if start >= end_exclusive or not any(
                code_range.get("start") == start and code_range.get("end_exclusive") == end_exclusive
                for code_range in raw_ranges
            ):
                return False
            matching_anchors = tuple(
                edge
                for edge in anchor_edges
                if (anchor := nodes.get(edge.source_id)) is not None
                and anchor.attributes.get("code_offset") == edge.attributes.get("code_offset")
                and _is_int(anchor.attributes.get("code_offset"))
                and start <= anchor.attributes["code_offset"] < end_exclusive
            )
            topology_ids = {item.record_id for item in matching_anchors}
            topology_ids.update(item.source_id for item in matching_anchors)
            return dependent.record_id in topology_ids

        if support_kind == "pcode-emission":
            raw_emission = any(
                code_range.get("start") == attributes["code_offset"]
                and any(
                    mapping.get("machine_operand_key") == attributes["machine_operand_key"]
                    and mapping.get("operand_lineage_id") == attributes["operand_lineage_id"]
                    and mapping.get("physical_register") == attributes["physical_register"]
                    for mapping in _rows(code_range.get("machine_operand_mappings"))
                )
                for code_range in _rows(pcode.attributes.get("code_ranges"))
            )
            if not raw_emission:
                return False
            matching_lineage_edges = tuple(
                edge
                for edge in evidence.edges
                if edge.kind == "pcode-operand-lineage"
                and edge.source_id == pcode.record_id
                and edge.attributes.get("code_offset") == attributes["code_offset"]
                and edge.attributes.get("machine_operand_key") == attributes["machine_operand_key"]
                and (lineage := nodes.get(edge.target_id)) is not None
                and lineage.attributes.get("operand_lineage_id") == attributes["operand_lineage_id"]
            )
            matching_anchors = tuple(
                edge
                for edge in anchor_edges
                if (anchor := nodes.get(edge.source_id)) is not None
                and anchor.attributes.get("code_offset") == attributes["code_offset"]
                and anchor.attributes.get("machine_operand_key") == attributes["machine_operand_key"]
                and anchor.attributes.get("physical_register") == attributes["physical_register"]
            )
            if not matching_lineage_edges or not matching_anchors:
                return False
            topology_ids = {edge.record_id for edge in matching_lineage_edges}
            topology_ids.update(edge.record_id for edge in matching_anchors)
            topology_ids.update(edge.source_id for edge in matching_anchors)
            return dependent.record_id in topology_ids

        if support_kind == "pcode-rewrite":
            if dependent.kind == "pcode-operand-uses-virtual" and isinstance(dependent, EvidenceEdge):
                lineage = nodes.get(dependent.source_id)
                virtual = nodes.get(dependent.target_id)
                return (
                    lineage is not None
                    and virtual is not None
                    and dependent.attributes.get("pcode_id") == attributes["pcode_id"]
                    and dependent.attributes.get("operand_lineage_id") == attributes["operand_lineage_id"]
                    and lineage.attributes.get("operand_lineage_id") == attributes["operand_lineage_id"]
                    and virtual.attributes.get("class_id") == attributes["class_id"]
                    and virtual.attributes.get("virtual") == attributes["virtual"]
                    and virtual.attributes.get("physical_register") == attributes["allocated_physical"]
                )
            if dependent.kind == "allocator-node" and isinstance(dependent, EvidenceNode):
                return (
                    dependent.attributes.get("class_id") == attributes["class_id"]
                    and dependent.attributes.get("virtual") == attributes["virtual"]
                    and dependent.attributes.get("assigned_phys") == attributes["allocated_physical"]
                )
            if dependent.kind == "maps-to-allocator-node" and isinstance(dependent, EvidenceEdge):
                virtual = nodes.get(dependent.source_id)
                allocator = nodes.get(dependent.target_id)
                return (
                    virtual is not None
                    and allocator is not None
                    and virtual.attributes.get("class_id") == attributes["class_id"]
                    and virtual.attributes.get("virtual") == attributes["virtual"]
                    and virtual.attributes.get("physical_register") == attributes["allocated_physical"]
                    and allocator.attributes.get("class_id") == attributes["class_id"]
                    and allocator.attributes.get("virtual") == attributes["virtual"]
                    and allocator.attributes.get("assigned_phys") == attributes["allocated_physical"]
                    and dependent.attributes.get("assigned_phys") == attributes["allocated_physical"]
                )
            return False

        if support_kind == "pcode-lineage-event":
            operand_id = attributes["operand_lineage_id"]
            if "event_kind" in attributes:
                if dependent.kind == "pcode-operand":
                    return dependent.attributes.get("operand_lineage_id") == operand_id
                if dependent.kind == "pcode-operand-lineage" and isinstance(dependent, EvidenceEdge):
                    target = nodes.get(dependent.target_id)
                    return (
                        dependent.source_id == pcode.record_id
                        and dependent.attributes.get("code_offset") == attributes["code_offset"]
                        and target is not None
                        and target.attributes.get("operand_lineage_id") == operand_id
                    )
                if dependent.kind in {
                    "assembly-operand-anchor",
                    "assembly-anchor-emitted-by-pcode",
                }:
                    matching_lineage = any(
                        edge.kind == "pcode-operand-lineage"
                        and edge.source_id == pcode.record_id
                        and edge.attributes.get("code_offset") == attributes["code_offset"]
                        and (target := nodes.get(edge.target_id)) is not None
                        and target.attributes.get("operand_lineage_id") == operand_id
                        for edge in evidence.edges
                    )
                    return matching_lineage and (dependent.attributes.get("code_offset") == attributes["code_offset"])
                return False
            if dependent.kind == "pcode-operand":
                if dependent.attributes.get("operand_lineage_id") != operand_id:
                    return False
            elif dependent.kind != "pcode-operand-lineage" or not isinstance(dependent, EvidenceEdge):
                return False
            relation_edges = tuple(
                edge
                for edge in evidence.edges
                if edge.kind == "pcode-operand-lineage"
                and edge.attributes.get("event_index") == attributes["event_index"]
                and edge.attributes.get("lineage_event_side") == "outputs"
                and edge.attributes.get("mutation_kind") == attributes["mutation_kind"]
                and edge.attributes.get("parent_lineage_ids") == attributes["parent_lineage_ids"]
            )
            if attributes["side"] == "outputs":
                output_nodes = _matching_nodes(
                    nodes,
                    "pcode-operand",
                    operand_lineage_id=operand_id,
                )
                if len(output_nodes) != 1:
                    return False
                output = output_nodes[0]
                selected_edges = tuple(edge for edge in relation_edges if edge.target_id == output.record_id)
                actual_parents = tuple(
                    sorted(
                        str(parent.attributes.get("operand_lineage_id"))
                        for edge in selected_edges
                        if (parent := nodes.get(edge.source_id)) is not None
                    )
                )
                return actual_parents == attributes["parent_lineage_ids"] and dependent.record_id in {
                    output.record_id,
                    *(edge.record_id for edge in selected_edges),
                }
            input_nodes = _matching_nodes(
                nodes,
                "pcode-operand",
                operand_lineage_id=operand_id,
            )
            if len(input_nodes) != 1:
                return False
            input_node = input_nodes[0]
            selected_edges = tuple(edge for edge in relation_edges if edge.source_id == input_node.record_id)
            return operand_id in attributes["parent_lineage_ids"] and dependent.record_id in {
                input_node.record_id,
                *(edge.record_id for edge in selected_edges),
            }

    if support_kind == "object-virtual-binding":
        owners = _matching_nodes(
            nodes,
            "compiler-object",
            object_id=attributes["object_id"],
            allocation_generation=attributes["allocation_generation"],
        )
        virtuals = _matching_nodes(
            nodes,
            "retail-virtual-register",
            class_id=attributes["class_id"],
            virtual=attributes["virtual"],
        )
        allocators = _matching_nodes(
            nodes,
            "allocator-node",
            class_id=attributes["class_id"],
            virtual=attributes["virtual"],
            ig_id=attributes["ig_id"],
        )
        if len(owners) != 1 or len(virtuals) != 1 or len(allocators) != 1:
            return False
        owner, virtual, allocator = owners[0], virtuals[0], allocators[0]
        object_edges = tuple(
            edge
            for edge in evidence.edges
            if edge.kind == "object-materializes-virtual"
            and edge.source_id == owner.record_id
            and edge.target_id == virtual.record_id
        )
        allocator_edges = tuple(
            edge
            for edge in evidence.edges
            if edge.kind == "maps-to-allocator-node"
            and edge.source_id == virtual.record_id
            and edge.target_id == allocator.record_id
        )
        if not object_edges or not allocator_edges:
            return False
        topology_ids = {virtual.record_id, allocator.record_id}
        topology_ids.update(edge.record_id for edge in object_edges)
        topology_ids.update(edge.record_id for edge in allocator_edges)
        return dependent.record_id in topology_ids

    if support_kind == "object-frame-binding":
        owners = _matching_nodes(
            nodes,
            "compiler-object",
            object_id=attributes["object_id"],
            allocation_generation=attributes["allocation_generation"],
        )
        stacks = _matching_nodes(
            nodes,
            "stack-object",
            area=attributes["area"],
            offset=attributes["final_r1_offset"],
            size=attributes["size"],
        )
        stacks = tuple(stack for stack in stacks if stack.role_key == attributes["semantic_stack_role"])
        if len(owners) != 1 or len(stacks) != 1:
            return False
        owner, stack = owners[0], stacks[0]
        frame_edges = tuple(
            edge
            for edge in evidence.edges
            if edge.kind == "object-has-stack-home"
            and edge.source_id == owner.record_id
            and edge.target_id == stack.record_id
            and edge.attributes.get("area") == attributes["area"]
            and edge.attributes.get("semantic_stack_role") == attributes["semantic_stack_role"]
        )
        return bool(frame_edges) and dependent.record_id in {
            stack.record_id,
            *(edge.record_id for edge in frame_edges),
        }

    return False


def exact_owner_path_record(
    evidence: ObjectBindingEvidence,
    record: EvidenceNode | EvidenceEdge,
) -> bool:
    """Validate one compile-local v2 ownership record at the shared trust gate."""

    records = (*evidence.nodes, *evidence.edges)
    registered = {item.record_id: item for item in records}
    if registered.get(record.record_id) != record:
        return False
    scopes = {(item.compile_id, item.function) for item in records}
    artifacts = {item.provenance.artifact_sha256 for item in records}
    if len(scopes) != 1 or (record.compile_id, record.function) not in scopes:
        return False
    if (
        len(artifacts) != 1
        or record.provenance.artifact_sha256 not in artifacts
        or record.producer_confidence not in _PROOF_CONFIDENCES
        or record.adapter_confidence not in _PROOF_CONFIDENCES
        or record.confidence not in _PROOF_CONFIDENCES
        or record.provenance.parser != _PARSER
        or record.attributes.get("capture_run_id") != evidence.capture_run_id
    ):
        return False
    nodes = {node.record_id: node for node in evidence.nodes}
    all_record_ids = {item.record_id for item in records}

    def exact_support_record(
        support: EvidenceNode,
        dependent: EvidenceNode | EvidenceEdge,
    ) -> bool:
        support_kind = support.attributes.get("support_kind")
        capability = _SUPPORT_CAPABILITIES.get(support_kind)
        return (
            support.kind == "backend-support-record"
            and capability is not None
            and capability in evidence.capabilities
            and support.attributes.get("verified_capability") == capability
            and support.producer_confidence in _PROOF_CONFIDENCES
            and support.adapter_confidence in _PROOF_CONFIDENCES
            and support.confidence in _PROOF_CONFIDENCES
            and support.provenance.parser == _PARSER
            and support.compile_id == dependent.compile_id
            and support.function == dependent.function
            and support.attributes.get("capture_run_id") == evidence.capture_run_id
            and support.provenance.artifact_sha256 == dependent.provenance.artifact_sha256
            and not support.provenance.input_record_ids
            and _support_attributes_are_typed(support_kind, support.attributes)
            and _support_topology_is_exact(
                evidence,
                support,
                dependent,
                nodes,
            )
        )

    def cited_support(
        dependent: EvidenceNode | EvidenceEdge,
        excluded_ids: frozenset[str] = frozenset(),
    ) -> tuple[EvidenceNode, ...] | None:
        selected: list[EvidenceNode] = []
        for input_id in dependent.provenance.input_record_ids:
            if input_id in excluded_ids:
                continue
            support = registered.get(input_id)
            if not isinstance(support, EvidenceNode) or not exact_support_record(support, dependent):
                return None
            selected.append(support)
        return tuple(selected)

    if isinstance(record, EvidenceNode):
        capability = _OWNER_NODE_CAPABILITIES.get(record.kind)
        support = cited_support(record)
        support_kinds = (
            frozenset() if support is None else frozenset(item.attributes.get("support_kind") for item in support)
        )
        return (
            capability is not None
            and capability in evidence.capabilities
            and support is not None
            and _REQUIRED_NODE_SUPPORT_KINDS.get(record.kind, frozenset()) <= support_kinds
        )
    schema = _OWNER_EDGE_SCHEMAS.get(record.kind)
    if schema is None:
        return False
    capability, source_kinds, target_kinds = schema
    source = nodes.get(record.source_id)
    target = nodes.get(record.target_id)
    endpoint_ids = frozenset({record.source_id, record.target_id})
    support = cited_support(record, endpoint_ids)
    support_kinds = (
        frozenset() if support is None else frozenset(item.attributes.get("support_kind") for item in support)
    )
    required_support = _REQUIRED_EDGE_SUPPORT_KINDS.get(record.kind, frozenset())
    if record.kind == "pcode-operand-lineage":
        required_support = frozenset(
            {"pcode-emission"} if source is not None and source.kind == "retail-pcode" else {"pcode-lineage-event"}
        )
    return (
        capability in evidence.capabilities
        and source is not None
        and target is not None
        and source.kind in source_kinds
        and target.kind in target_kinds
        and exact_owner_path_record(evidence, source)
        and exact_owner_path_record(evidence, target)
        and {source.record_id, target.record_id}.issubset(record.provenance.input_record_ids)
        and set(record.provenance.input_record_ids) <= all_record_ids
        and support is not None
        and required_support <= support_kinds
    )


def owner_edge_requires_exact_v2(
    evidence: ObjectBindingEvidence | None,
    edge: EvidenceEdge,
) -> bool:
    """Identify v2 ownership edges, including untagged maps into v2 nodes."""

    if edge.kind not in _EXACT_V2_OWNER_EDGE_KINDS:
        return False
    if edge.kind != "maps-to-allocator-node":
        return True
    if evidence is None:
        return False
    registered_node_ids = {node.record_id for node in evidence.nodes}
    return (
        edge.provenance.parser == _PARSER
        or "capture_run_id" in edge.attributes
        or edge.source_id in registered_node_ids
        or edge.target_id in registered_node_ids
    )


def bilateral_source_object_records(
    evidence_pair: tuple[ObjectBindingEvidence, ObjectBindingEvidence],
) -> tuple[EvidenceEdge, ...]:
    """Return bilateral proof bindings; Phase 1 correctly returns none."""

    selected: list[EvidenceEdge] = []
    for evidence in evidence_pair:
        candidates = tuple(
            edge for edge in evidence.edges if edge.kind == "object-to-source" and edge.confidence in _PROOF_CONFIDENCES
        )
        if len(candidates) != 1:
            return ()
        selected.append(candidates[0])
    return tuple(selected)


def derive_backend_frame_recommendation(
    evidence: ObjectBindingEvidence,
) -> str | None:
    """Retain a diagnostic direction only after backend/frame proof completes."""

    if not proof_complete(evidence):
        return None
    return "preserve-allocation/shorten-materialization"


__all__ = [
    "ObjectBindingAdapterInput",
    "ObjectBindingEvidence",
    "adapt_object_bindings",
    "bilateral_source_object_records",
    "derive_backend_frame_recommendation",
    "emit_object_binding_evidence",
    "exact_owner_path_record",
    "owner_edge_requires_exact_v2",
    "proof_complete",
]
