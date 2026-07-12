"""Normalize captured MWCC backend artifacts into causal evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .. import role_descriptor
from ..copy_trace import find_virtual_to_ig
from ..parser import Function, Instruction, parse_pcdump
from ..pressure_explorer.facts import facts_from_backend_trace, facts_from_pcdump
from ..pressure_explorer.models import AllocatorFacts
from .bundles import BundleInputError, ValidatedBundle
from .models import AdapterResult, Confidence, EvidenceEdge, EvidenceNode, Provenance
from .object_binding_adapter import ObjectBindingEvidence, adapt_object_bindings


@dataclass(frozen=True, slots=True)
class BackendEvidence:
    result: AdapterResult
    pcdump_text: str
    role_compile: role_descriptor.Compile | None
    nodes_by_class_ig: Mapping[tuple[int, int], str]
    nodes_by_virtual: Mapping[tuple[str, int], str]
    object_bindings: ObjectBindingEvidence | None = None

    @property
    def verified_capabilities(self) -> frozenset[str]:
        return self.result.verified_capabilities


def _confidence(value: str | None) -> Confidence:
    if value == Confidence.OBSERVED:
        return Confidence.OBSERVED
    if value == Confidence.DERIVED_UNIQUE:
        return Confidence.DERIVED_UNIQUE
    return Confidence.HEURISTIC


def _reg_kind(class_id: int) -> str:
    return "f" if class_id == 1 else "r"


def _normalized_reg_kind(value: str) -> str:
    return {"gpr": "r", "fpr": "f"}.get(value, value)


def _backend_trace_interference_confidences(
    text: str,
    function: str,
) -> Mapping[tuple[int, int], Confidence]:
    payload = json.loads(text)
    functions = payload.get("functions", ()) if isinstance(payload, Mapping) else ()
    selected = next(
        (item for item in functions if isinstance(item, Mapping) and item.get("name") == function),
        None,
    )
    if not isinstance(selected, Mapping):
        return MappingProxyType({})
    regalloc = selected.get("regalloc")
    classes = regalloc.get("classes", ()) if isinstance(regalloc, Mapping) else ()
    confidences: dict[tuple[int, int], Confidence] = {}
    for class_payload in classes:
        if not isinstance(class_payload, Mapping):
            continue
        class_id = int(class_payload["class_id"])
        for index, edge in enumerate(class_payload.get("edges", ())):
            confidence = edge.get("confidence") if isinstance(edge, Mapping) else None
            confidences[(class_id, index)] = _confidence(str(confidence) if confidence is not None else None)
    return MappingProxyType(confidences)


def _provenance(
    *,
    artifact_sha256: str,
    parser: str,
    derivation_rule: str,
    artifact_size: int,
    input_record_ids: tuple[str, ...] = (),
) -> Provenance:
    return Provenance(
        artifact_sha256=artifact_sha256,
        parser=parser,
        raw_start=0,
        raw_end=artifact_size,
        derivation_rule=derivation_rule,
        input_record_ids=input_record_ids,
    )


def _node(
    bundle: ValidatedBundle,
    *,
    artifact_sha256: str,
    parser: str,
    kind: str,
    local_key: object,
    role_key: str | None,
    producer_confidence: Confidence,
    adapter_confidence: Confidence,
    derivation_rule: str,
    artifact_size: int,
    attributes: Mapping[str, object],
    input_nodes: tuple[EvidenceNode, ...] = (),
) -> EvidenceNode:
    return EvidenceNode.create(
        compile_id=bundle.compile_id,
        function=bundle.manifest.function,
        kind=kind,
        local_key=local_key,
        role_key=role_key,
        producer_confidence=producer_confidence,
        adapter_confidence=adapter_confidence,
        provenance=_provenance(
            artifact_sha256=artifact_sha256,
            parser=parser,
            derivation_rule=derivation_rule,
            artifact_size=artifact_size,
            input_record_ids=tuple(item.record_id for item in input_nodes),
        ),
        input_confidences=tuple(item.confidence for item in input_nodes),
        attributes=attributes,
    )


def _edge(
    bundle: ValidatedBundle,
    *,
    artifact_sha256: str,
    parser: str,
    kind: str,
    source: EvidenceNode,
    target: EvidenceNode,
    occurrence_ordinal: int,
    producer_confidence: Confidence,
    adapter_confidence: Confidence,
    derivation_rule: str,
    artifact_size: int,
    attributes: Mapping[str, object] | None = None,
) -> EvidenceEdge:
    return EvidenceEdge.create(
        compile_id=bundle.compile_id,
        function=bundle.manifest.function,
        kind=kind,
        source_id=source.record_id,
        target_id=target.record_id,
        occurrence_ordinal=occurrence_ordinal,
        producer_confidence=producer_confidence,
        adapter_confidence=adapter_confidence,
        provenance=_provenance(
            artifact_sha256=artifact_sha256,
            parser=parser,
            derivation_rule=derivation_rule,
            artifact_size=artifact_size,
            input_record_ids=(source.record_id, target.record_id),
        ),
        input_confidences=(source.confidence, target.confidence),
        attributes={} if attributes is None else attributes,
    )


_USE = frozenset({"use"})
_DEF = frozenset({"def"})
_USE_DEF = frozenset({"use", "def"})
_PCDUMP_OPERAND_ROLE_CONTRACTS: Mapping[str, Mapping[str, tuple[frozenset[str], ...]]] = {
    "mwcc-debug-pcdump.v1": {
        "add": (_DEF, _USE, _USE),
        "addi": (_DEF, _USE),
        "cmp": (_USE, _USE),
        "cmpi": (_USE,),
        "cmpli": (_USE,),
        "fcmpu": (_USE, _USE),
        "fmuls": (_DEF, _USE, _USE),
        "fsubs": (_DEF, _USE, _USE),
        "lbz": (_DEF, _USE),
        "lbzx": (_DEF, _USE, _USE),
        "lfd": (_DEF, _USE),
        "lfs": (_DEF, _USE),
        "lhz": (_DEF, _USE),
        "li": (_DEF,),
        "lis": (_DEF,),
        "lwz": (_DEF, _USE),
        "mr": (_DEF, _USE),
        "rldimi": (_USE_DEF, _USE),
        "rlwimi": (_USE_DEF, _USE),
        "rlwinm": (_DEF, _USE),
        "stfs": (_USE, _USE),
        "stw": (_USE, _USE),
        "stwu": (_USE, _USE_DEF),
        "stwux": (_USE, _USE_DEF, _USE),
        "xoris": (_DEF, _USE),
    }
}


def _operand_roles(
    instruction: Instruction,
    producer_version: str,
) -> tuple[tuple[frozenset[str], ...], Confidence]:
    if not instruction.regs:
        return (), Confidence.OBSERVED
    schema = _PCDUMP_OPERAND_ROLE_CONTRACTS.get(producer_version, {}).get(instruction.opcode.lower())
    if schema is None or len(schema) != len(instruction.regs):
        return tuple(_USE for _item in instruction.regs), Confidence.HEURISTIC
    return schema, Confidence.OBSERVED


def _emit_pcode(
    bundle: ValidatedBundle,
    *,
    artifact_sha256: str,
    parser: str,
    function: Function,
    pcdump_text: str,
    artifact_size: int,
    nodes: list[EvidenceNode],
    edges: list[EvidenceEdge],
    nodes_by_virtual: dict[tuple[str, int], EvidenceNode],
) -> bool:
    diagnostic_only = parser == "mwcc-debug-pcdump.v1"
    occurrences: list[tuple[EvidenceNode, Instruction, tuple[frozenset[str], ...], Confidence]] = []
    virtual_counts: dict[tuple[str, int], dict[str, int]] = {}
    virtual_confidences: dict[tuple[str, int], Confidence] = {}
    exact_roles = True
    for pass_index, pass_ in enumerate(function.passes):
        for block in pass_.blocks:
            for instruction_index, instruction in enumerate(block.instructions):
                operand_roles, role_confidence = _operand_roles(instruction, parser)
                if role_confidence is not Confidence.OBSERVED and any(
                    number >= 32 for _kind, number in instruction.regs
                ):
                    exact_roles = False
                occurrence = _node(
                    bundle,
                    artifact_sha256=artifact_sha256,
                    parser=parser,
                    kind="pcode-occurrence",
                    local_key=(pass_index, block.index, instruction_index),
                    role_key=None,
                    producer_confidence=Confidence.OBSERVED,
                    adapter_confidence=(Confidence.HEURISTIC if diagnostic_only else role_confidence),
                    derivation_rule="observed-versioned-pcdump-instruction",
                    artifact_size=artifact_size,
                    attributes={
                        "pass": pass_.name,
                        "pass_index": pass_index,
                        "block": block.index,
                        "instruction_index": instruction_index,
                        "opcode": instruction.opcode,
                        "operands": instruction.operands,
                        "regs": tuple(instruction.regs),
                        "operand_roles": tuple(tuple(sorted(role)) for role in operand_roles),
                    },
                )
                nodes.append(occurrence)
                occurrences.append((occurrence, instruction, operand_roles, role_confidence))
                for position, (kind, number) in enumerate(instruction.regs):
                    if number < 32:
                        continue
                    counts = virtual_counts.setdefault((kind, number), {"definitions": 0, "uses": 0})
                    if diagnostic_only or role_confidence is Confidence.HEURISTIC:
                        virtual_confidences[(kind, number)] = Confidence.HEURISTIC
                    else:
                        virtual_confidences.setdefault((kind, number), Confidence.OBSERVED)
                    for role in operand_roles[position]:
                        counts["definitions" if role == "def" else "uses"] += 1

    for (kind, virtual), counts in sorted(virtual_counts.items()):
        mapping = find_virtual_to_ig(
            pcdump_text,
            bundle.manifest.function,
            virtual,
            reg_class="fpr" if kind == "f" else "gpr",
        )
        virtual_node = _node(
            bundle,
            artifact_sha256=artifact_sha256,
            parser=parser,
            kind="virtual-register",
            local_key=(kind, virtual),
            role_key=None,
            producer_confidence=Confidence.OBSERVED,
            adapter_confidence=virtual_confidences[(kind, virtual)],
            derivation_rule="observed-versioned-pcdump-virtual",
            artifact_size=artifact_size,
            attributes={
                "class": kind,
                "virtual": virtual,
                "definitions": counts["definitions"],
                "uses": counts["uses"],
                "live_range": mapping.live_range,
                "mapping_status": mapping.status,
            },
        )
        nodes.append(virtual_node)
        nodes_by_virtual[(kind, virtual)] = virtual_node

    edge_ordinals: dict[tuple[str, str], int] = {}
    for occurrence, instruction, operand_roles, role_confidence in occurrences:
        for position, (kind, virtual) in enumerate(instruction.regs):
            virtual_node = nodes_by_virtual.get((kind, virtual))
            if virtual_node is None:
                continue
            for role in sorted(operand_roles[position]):
                edge_kind = "defines-virtual" if role == "def" else "uses-virtual"
                ordinal_key = (occurrence.record_id, virtual_node.record_id)
                ordinal = edge_ordinals.get(ordinal_key, 0)
                edge_ordinals[ordinal_key] = ordinal + 1
                edges.append(
                    _edge(
                        bundle,
                        artifact_sha256=artifact_sha256,
                        parser=parser,
                        kind=edge_kind,
                        source=occurrence,
                        target=virtual_node,
                        occurrence_ordinal=ordinal,
                        producer_confidence=Confidence.OBSERVED,
                        adapter_confidence=(Confidence.HEURISTIC if diagnostic_only else role_confidence),
                        derivation_rule="versioned-pcode-operand-role",
                        artifact_size=artifact_size,
                        attributes={"operand_position": position},
                    )
                )
    return exact_roles


def _emit_allocator_facts(
    bundle: ValidatedBundle,
    *,
    artifact_sha256: str,
    parser: str,
    facts: AllocatorFacts,
    raw_pcdump: str | None,
    artifact_size: int,
    nodes: list[EvidenceNode],
    edges: list[EvidenceEdge],
    nodes_by_class_ig: dict[tuple[int, int], EvidenceNode],
    nodes_by_virtual: dict[tuple[str, int], EvidenceNode],
    trace_interference_confidences: Mapping[tuple[int, int], Confidence] | None,
) -> None:
    decisions: dict[tuple[int, int], EvidenceNode] = {}
    for allocator_class in facts.classes:
        kind = _reg_kind(allocator_class.class_id)
        for item in allocator_class.nodes:
            allocator_node = _node(
                bundle,
                artifact_sha256=artifact_sha256,
                parser=parser,
                kind="allocator-node",
                local_key=(allocator_class.class_id, item.ig_id),
                role_key=None,
                producer_confidence=Confidence.HEURISTIC,
                adapter_confidence=Confidence.OBSERVED,
                derivation_rule="normalize-allocator-node-without-producer-confidence",
                artifact_size=artifact_size,
                attributes={
                    "class_id": allocator_class.class_id,
                    "first_def_signature": role_descriptor.normalize_first_def(item.first_def),
                    **asdict(item),
                },
            )
            nodes.append(allocator_node)
            nodes_by_class_ig[(allocator_class.class_id, item.ig_id)] = allocator_node

            virtual_key = (_normalized_reg_kind(item.virtual_kind), item.virtual_number)
            virtual_node = nodes_by_virtual.get(virtual_key)
            if virtual_node is None and raw_pcdump is None:
                virtual_node = _node(
                    bundle,
                    artifact_sha256=artifact_sha256,
                    parser=parser,
                    kind="virtual-register",
                    local_key=virtual_key,
                    role_key=None,
                    producer_confidence=Confidence.HEURISTIC,
                    adapter_confidence=Confidence.OBSERVED,
                    derivation_rule="normalize-backend-virtual-without-producer-confidence",
                    artifact_size=artifact_size,
                    attributes={
                        "class": virtual_key[0],
                        "virtual": virtual_key[1],
                        "live_range": tuple(item.live.intervals),
                        "mapping_status": "backend-node",
                    },
                )
                nodes.append(virtual_node)
                nodes_by_virtual[virtual_key] = virtual_node

            if virtual_node is not None:
                bridge_confidence = Confidence.DERIVED_UNIQUE
                if raw_pcdump is not None:
                    mapping = find_virtual_to_ig(
                        raw_pcdump,
                        bundle.manifest.function,
                        item.virtual_number,
                        reg_class="fpr" if kind == "f" else "gpr",
                    )
                    if not mapping.found or mapping.ig_idx != item.ig_id:
                        continue
                    bridge_confidence = Confidence.HEURISTIC
                edges.append(
                    _edge(
                        bundle,
                        artifact_sha256=artifact_sha256,
                        parser=parser,
                        kind="maps-to-allocator-node",
                        source=virtual_node,
                        target=allocator_node,
                        occurrence_ordinal=0,
                        producer_confidence=Confidence.OBSERVED,
                        adapter_confidence=bridge_confidence,
                        derivation_rule="existing-virtual-to-ig-mapping",
                        artifact_size=artifact_size,
                        attributes={"class_id": allocator_class.class_id, "ig_id": item.ig_id},
                    )
                )

        for decision in allocator_class.color_decisions:
            decision_confidence = _confidence(decision.confidence)
            decision_node = _node(
                bundle,
                artifact_sha256=artifact_sha256,
                parser=parser,
                kind="allocator-decision",
                local_key=(allocator_class.class_id, decision.id),
                role_key=None,
                producer_confidence=decision_confidence,
                adapter_confidence=Confidence.OBSERVED,
                derivation_rule="normalize-producer-color-decision",
                artifact_size=artifact_size,
                attributes={"class_id": allocator_class.class_id, **asdict(decision)},
            )
            nodes.append(decision_node)
            decisions[(allocator_class.class_id, decision.ig_id)] = decision_node

        for item in allocator_class.nodes:
            allocator_node = nodes_by_class_ig[(allocator_class.class_id, item.ig_id)]
            decision_node = decisions.get((allocator_class.class_id, item.ig_id))
            if decision_node is not None:
                edges.append(
                    _edge(
                        bundle,
                        artifact_sha256=artifact_sha256,
                        parser=parser,
                        kind="has-color-decision",
                        source=allocator_node,
                        target=decision_node,
                        occurrence_ordinal=0,
                        producer_confidence=decision_node.producer_confidence,
                        adapter_confidence=Confidence.DERIVED_UNIQUE,
                        derivation_rule="join-allocator-node-to-decision-by-class-and-ig",
                        artifact_size=artifact_size,
                    )
                )

        for index, interference in enumerate(allocator_class.edges):
            left = nodes_by_class_ig.get((allocator_class.class_id, interference.a))
            right = nodes_by_class_ig.get((allocator_class.class_id, interference.b))
            if left is None or right is None:
                continue
            edges.append(
                _edge(
                    bundle,
                    artifact_sha256=artifact_sha256,
                    parser=parser,
                    kind="interferes-with",
                    source=left,
                    target=right,
                    occurrence_ordinal=index,
                    producer_confidence=(
                        _confidence(interference.confidence)
                        if trace_interference_confidences is None
                        else trace_interference_confidences.get((allocator_class.class_id, index), Confidence.HEURISTIC)
                    ),
                    adapter_confidence=Confidence.OBSERVED,
                    derivation_rule="normalize-producer-interference-edge",
                    artifact_size=artifact_size,
                    attributes={"class_id": allocator_class.class_id, "edge_kind": interference.kind},
                )
            )

        coalesce_records: list[tuple[int, int, Confidence, object]] = []
        raw_mappings = allocator_class.coalesce.get("mappings", ())
        if isinstance(raw_mappings, (list, tuple)):
            for mapping in raw_mappings:
                if not isinstance(mapping, Mapping):
                    continue
                confidence = (
                    Confidence.OBSERVED
                    if raw_pcdump is not None
                    else _confidence(str(mapping["confidence"]) if mapping.get("confidence") is not None else None)
                )
                coalesce_records.append(
                    (
                        int(mapping["alias"]),
                        int(mapping["root"]),
                        confidence,
                        mapping.get("provenance"),
                    )
                )
        seen_coalesce = {(alias, root) for alias, root, _confidence_value, _provenance_value in coalesce_records}
        for alias, root in allocator_class.coalesce_mappings:
            if (alias, root) not in seen_coalesce:
                coalesce_records.append(
                    (
                        alias,
                        root,
                        Confidence.OBSERVED if raw_pcdump is not None else Confidence.HEURISTIC,
                        None,
                    )
                )

        for index, (alias, root, confidence, producer_provenance) in enumerate(coalesce_records):
            alias_node = nodes_by_class_ig.get((allocator_class.class_id, alias))
            root_node = nodes_by_class_ig.get((allocator_class.class_id, root))
            if alias_node is None or root_node is None:
                continue
            edges.append(
                _edge(
                    bundle,
                    artifact_sha256=artifact_sha256,
                    parser=parser,
                    kind="coalesces-with",
                    source=alias_node,
                    target=root_node,
                    occurrence_ordinal=index,
                    producer_confidence=confidence,
                    adapter_confidence=Confidence.OBSERVED,
                    derivation_rule="normalize-producer-coalesce-mapping",
                    artifact_size=artifact_size,
                    attributes={
                        "class_id": allocator_class.class_id,
                        "producer_provenance": producer_provenance,
                    },
                )
            )


def _deduplicate_nodes(nodes: list[EvidenceNode]) -> tuple[EvidenceNode, ...]:
    indexed: dict[str, EvidenceNode] = {}
    for node in nodes:
        existing = indexed.get(node.record_id)
        if existing is not None and existing.attributes != node.attributes:
            raise BundleInputError(f"conflicting backend node evidence for {node.record_id}")
        indexed.setdefault(node.record_id, node)
    return tuple(indexed.values())


def _deduplicate_edges(edges: list[EvidenceEdge]) -> tuple[EvidenceEdge, ...]:
    indexed: dict[str, EvidenceEdge] = {}
    for edge in edges:
        existing = indexed.get(edge.record_id)
        if existing is not None and existing.attributes != edge.attributes:
            raise BundleInputError(f"conflicting backend edge evidence for {edge.record_id}")
        indexed.setdefault(edge.record_id, edge)
    return tuple(indexed.values())


def adapt_backends(bundle: ValidatedBundle) -> BackendEvidence:
    """Normalize every captured backend artifact without compiling or writing."""

    backend_formats = {reference.format for reference in bundle.manifest.artifacts.backend}
    if "backend-trace.v2" in backend_formats and backend_formats != {"backend-trace.v2"}:
        raise BundleInputError("incompatible process-local backend evidence cannot be mixed with backend-trace.v2")

    nodes: list[EvidenceNode] = []
    edges: list[EvidenceEdge] = []
    nodes_by_class_ig: dict[tuple[int, int], EvidenceNode] = {}
    nodes_by_virtual: dict[tuple[str, int], EvidenceNode] = {}
    pcdump_text = ""
    role_compile: role_descriptor.Compile | None = None
    pcode_roles_exact = True
    object_bindings = adapt_object_bindings(bundle)
    try:
        source_text = bundle.artifact_paths["source"].read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise BundleInputError(f"invalid source artifact: {error}") from error

    for index, backend in enumerate(bundle.manifest.artifacts.backend):
        artifact_name = f"backend[{index}]"
        path = bundle.artifact_paths[artifact_name]
        try:
            raw_bytes = path.read_bytes()
        except OSError as error:
            raise BundleInputError(f"cannot read backend artifact {index}: {error}") from error
        artifact_size = len(raw_bytes)
        local_nodes: list[EvidenceNode] = []
        local_edges: list[EvidenceEdge] = []
        local_by_class_ig: dict[tuple[int, int], EvidenceNode] = {}
        local_by_virtual: dict[tuple[str, int], EvidenceNode] = {}
        try:
            text = raw_bytes.decode("utf-8")
            if backend.format == "mwcc-debug-pcdump":
                parser = "mwcc-debug-pcdump.v1"
                version = bundle.manifest.producer_versions.get("mwcc_debug")
                if version != parser:
                    raise BundleInputError(f"unsupported mwcc-debug producer version: {version!r}")
                parsed = parse_pcdump(text, function=bundle.manifest.function)
                if not parsed:
                    raise BundleInputError(f"{bundle.manifest.function} not found in backend PCode artifact")
                if not pcdump_text:
                    pcdump_text = text
                    role_compile = role_descriptor.Compile.from_text(text, bundle.manifest.function, source_text)
                facts = facts_from_pcdump(
                    text,
                    bundle.manifest.function,
                    pcdump_path=path,
                    source_text=source_text,
                    source_path=bundle.artifact_paths["source"],
                    enable_virtual_attribution=False,
                )
                local_roles_exact = _emit_pcode(
                    bundle,
                    artifact_sha256=backend.sha256,
                    parser=parser,
                    function=parsed[0],
                    pcdump_text=text,
                    artifact_size=artifact_size,
                    nodes=local_nodes,
                    edges=local_edges,
                    nodes_by_virtual=local_by_virtual,
                )
                pcode_roles_exact = pcode_roles_exact and local_roles_exact
                raw_pcdump: str | None = text
                trace_interference_confidences = None
            elif backend.format in {"backend-trace.v1", "backend-trace.v2"}:
                parser = "backend-trace.v1" if backend.format == "backend-trace.v1" else "mwcc-retro-backend-trace.v2"
                version = bundle.manifest.producer_versions.get("backend_trace")
                if backend.format == "backend-trace.v2":
                    version = bundle.manifest.producer_versions.get("mwcc_retro")
                if version != parser:
                    raise BundleInputError(f"unsupported backend-trace producer version: {version!r}")
                facts = facts_from_backend_trace(Path(path), function=bundle.manifest.function)
                raw_pcdump = None
                trace_interference_confidences = _backend_trace_interference_confidences(text, bundle.manifest.function)
            else:  # pragma: no cover - Pydantic validates the closed format set.
                raise BundleInputError(f"unsupported backend format: {backend.format}")

            _emit_allocator_facts(
                bundle,
                artifact_sha256=backend.sha256,
                parser=parser,
                facts=facts,
                raw_pcdump=raw_pcdump,
                artifact_size=artifact_size,
                nodes=local_nodes,
                edges=local_edges,
                nodes_by_class_ig=local_by_class_ig,
                nodes_by_virtual=local_by_virtual,
                trace_interference_confidences=trace_interference_confidences,
            )
        except BundleInputError:
            raise
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, IndexError) as error:
            raise BundleInputError(
                f"invalid backend artifact {index} ({backend.format}, {backend.sha256}): {error}"
            ) from error

        existing_node_ids = {node.record_id for node in nodes}
        existing_edge_ids = {edge.record_id for edge in edges}
        overlap = existing_node_ids & {node.record_id for node in local_nodes}
        overlap |= existing_edge_ids & {edge.record_id for edge in local_edges}
        if overlap:
            raise BundleInputError(
                "overlapping backend evidence cannot preserve distinct producer provenance: "
                + ", ".join(sorted(overlap)[:3])
            )
        nodes.extend(local_nodes)
        edges.extend(local_edges)
        for key, node in local_by_class_ig.items():
            if key in nodes_by_class_ig:
                raise BundleInputError(f"overlapping backend evidence for allocator node {key}")
            nodes_by_class_ig[key] = node
        for key, node in local_by_virtual.items():
            if key in nodes_by_virtual:
                raise BundleInputError(f"overlapping backend evidence for virtual register {key}")
            nodes_by_virtual[key] = node

    nodes.extend(object_bindings.nodes)
    edges.extend(object_bindings.edges)

    normalized_nodes = _deduplicate_nodes(nodes)
    normalized_edges = _deduplicate_edges(edges)
    node_kinds = {node.kind for node in normalized_nodes}
    edge_kinds = {edge.kind for edge in normalized_edges}
    verified: set[str] = set()
    if "pcode-occurrence" in node_kinds:
        verified.add("pcode-occurrences")
    if pcode_roles_exact and edge_kinds & {"uses-virtual", "defines-virtual"}:
        verified.add("virtual-use-def")
    if "maps-to-allocator-node" in edge_kinds:
        verified.add("virtual-to-allocator-node")
    if "allocator-decision" in node_kinds:
        verified.add("allocator-decisions")
    if "interferes-with" in edge_kinds:
        verified.add("interference-edges")
    verified.update(object_bindings.capabilities)

    result = AdapterResult(
        nodes=normalized_nodes,
        edges=normalized_edges,
        verified_capabilities=frozenset(verified),
    )
    return BackendEvidence(
        result=result,
        pcdump_text=pcdump_text,
        role_compile=role_compile,
        nodes_by_class_ig=MappingProxyType({key: node.record_id for key, node in nodes_by_class_ig.items()}),
        nodes_by_virtual=MappingProxyType({key: node.record_id for key, node in nodes_by_virtual.items()}),
        object_bindings=(object_bindings if object_bindings.capture_run_id else None),
    )


__all__ = ["BackendEvidence", "adapt_backends"]
