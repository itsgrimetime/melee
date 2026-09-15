"""Adapt semantic mwcc-inspect records into causal evidence."""

from __future__ import annotations

from ..inspect_parser import InspectENode, parse_inspect_function
from .bundles import ValidatedBundle
from .models import AdapterResult, Confidence, EvidenceEdge, EvidenceNode, Provenance

_PARSER_VERSION = "mwcc-inspect-semantic.v1"


def _provenance(
    bundle: ValidatedBundle,
    *,
    raw_start: int,
    raw_end: int,
    derivation_rule: str,
    input_record_ids: tuple[str, ...] = (),
) -> Provenance:
    return Provenance(
        artifact_sha256=bundle.manifest.artifacts.inspector.sha256,
        parser=_PARSER_VERSION,
        raw_start=raw_start,
        raw_end=raw_end,
        derivation_rule=derivation_rule,
        input_record_ids=input_record_ids,
    )


def _object_class(data_type: str, name: str) -> tuple[str, Confidence]:
    if data_type == "DLOCAL":
        object_class = "synthetic-local" if name.startswith("@") else "named-local"
        return object_class, Confidence.DERIVED_UNIQUE
    if data_type == "DFUNC":
        return "function", Confidence.DERIVED_UNIQUE
    if data_type == "DDATA":
        return "data", Confidence.DERIVED_UNIQUE
    return "ambiguous", Confidence.HEURISTIC


def _observed_node(
    bundle: ValidatedBundle,
    *,
    kind: str,
    local_key: str,
    raw_start: int,
    raw_end: int,
    attributes: dict[str, object],
) -> EvidenceNode:
    return EvidenceNode.create(
        compile_id=bundle.compile_id,
        function=bundle.manifest.function,
        kind=kind,
        local_key=local_key,
        role_key=None,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        provenance=_provenance(
            bundle,
            raw_start=raw_start,
            raw_end=raw_end,
            derivation_rule=f"observed-inspector-{kind}",
        ),
        attributes=attributes,
    )


def _observed_edge(
    bundle: ValidatedBundle,
    *,
    kind: str,
    source_id: str,
    target_id: str,
    raw_start: int,
    raw_end: int,
    attributes: dict[str, object] | None = None,
) -> EvidenceEdge:
    return EvidenceEdge.create(
        compile_id=bundle.compile_id,
        function=bundle.manifest.function,
        kind=kind,
        source_id=source_id,
        target_id=target_id,
        occurrence_ordinal=0,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        provenance=_provenance(
            bundle,
            raw_start=raw_start,
            raw_end=raw_end,
            derivation_rule=f"observed-inspector-{kind}",
        ),
        attributes=attributes or {},
    )


def _ancestor_support(
    source: InspectENode,
    address: str,
    *,
    enode_by_id: dict[str, InspectENode],
    child_edges: dict[tuple[str, str], EvidenceEdge],
    direct_edges: dict[tuple[str, str], EvidenceEdge],
) -> tuple[EvidenceEdge, ...]:
    supporting: dict[str, EvidenceEdge] = {}
    for (direct_node_id, direct_address), direct_edge in direct_edges.items():
        if direct_address != address:
            continue
        current_id = direct_node_id
        path: list[EvidenceEdge] = []
        while current_id != source.node_id:
            current = enode_by_id[current_id]
            if current.parent_id is None:
                break
            path.append(child_edges[(current.parent_id, current_id)])
            current_id = current.parent_id
        if current_id != source.node_id:
            continue
        supporting[direct_edge.record_id] = direct_edge
        for edge in path:
            supporting[edge.record_id] = edge
    return tuple(supporting[record_id] for record_id in sorted(supporting))


def adapt_inspector(bundle: ValidatedBundle) -> AdapterResult:
    """Parse and normalize the bundle's inspector artifact."""

    inspector_text = bundle.artifact_paths["inspector"].read_bytes().decode("utf-8")
    parsed = parse_inspect_function(inspector_text, bundle.manifest.function)
    if parsed is None:
        return AdapterResult(warnings=(f"inspector function not found: {bundle.manifest.function}",))

    nodes: list[EvidenceNode] = []
    statement_nodes: dict[str, EvidenceNode] = {}
    enode_nodes: dict[str, EvidenceNode] = {}
    object_nodes: dict[str, EvidenceNode] = {}

    for statement in parsed.statements:
        node = _observed_node(
            bundle,
            kind="statement",
            local_key=statement.statement_id,
            raw_start=statement.raw_start,
            raw_end=statement.raw_end,
            attributes={
                "statement_id": statement.statement_id,
                "source_line": statement.source_line,
                "expression": statement.expression,
                "root_enode_id": statement.root_enode_id,
            },
        )
        nodes.append(node)
        statement_nodes[statement.statement_id] = node

    for enode in parsed.enodes:
        node = _observed_node(
            bundle,
            kind="enode",
            local_key=enode.node_id,
            raw_start=enode.raw_start,
            raw_end=enode.raw_end,
            attributes={
                "node_id": enode.node_id,
                "opcode": enode.opcode,
                "expression": enode.expression,
                "depth": enode.depth,
                "parent_id": enode.parent_id,
            },
        )
        nodes.append(node)
        enode_nodes[enode.node_id] = node

    for objobject in parsed.objobjects.values():
        node = _observed_node(
            bundle,
            kind="objobject",
            local_key=objobject.address,
            raw_start=objobject.raw_start,
            raw_end=objobject.raw_end,
            attributes={
                "address": objobject.address,
                "name": objobject.name,
                "data_type": objobject.data_type,
                "type_text": objobject.type_text,
                "first_appearance_order": objobject.first_appearance_order,
                "address_order": objobject.address_order,
            },
        )
        nodes.append(node)
        object_nodes[objobject.address] = node

    for objobject in parsed.objobjects.values():
        raw_node = object_nodes[objobject.address]
        object_class, adapter_confidence = _object_class(objobject.data_type, objobject.name)
        classification = EvidenceNode.create(
            compile_id=bundle.compile_id,
            function=bundle.manifest.function,
            kind="objobject-classification",
            local_key=objobject.address,
            role_key=None,
            producer_confidence=Confidence.OBSERVED,
            adapter_confidence=adapter_confidence,
            provenance=_provenance(
                bundle,
                raw_start=objobject.raw_start,
                raw_end=objobject.raw_end,
                derivation_rule=(
                    "classify-objobject-from-explicit-datatype"
                    if adapter_confidence is Confidence.DERIVED_UNIQUE
                    else "classify-objobject-without-explicit-datatype"
                ),
                input_record_ids=(raw_node.record_id,),
            ),
            input_confidences=(raw_node.confidence,),
            attributes={
                "object_address": objobject.address,
                "object_class": object_class,
                "synthetic_name": objobject.name.startswith("@"),
            },
        )
        nodes.append(classification)

    edges: list[EvidenceEdge] = []
    child_edges: dict[tuple[str, str], EvidenceEdge] = {}
    direct_edges: dict[tuple[str, str], EvidenceEdge] = {}

    for statement in parsed.statements:
        if statement.root_enode_id is None:
            continue
        edge = _observed_edge(
            bundle,
            kind="statement-has-enode",
            source_id=statement_nodes[statement.statement_id].record_id,
            target_id=enode_nodes[statement.root_enode_id].record_id,
            raw_start=statement.raw_start,
            raw_end=statement.raw_end,
        )
        edges.append(edge)

    for enode in parsed.enodes:
        if enode.parent_id is None:
            continue
        edge = _observed_edge(
            bundle,
            kind="enode-child",
            source_id=enode_nodes[enode.parent_id].record_id,
            target_id=enode_nodes[enode.node_id].record_id,
            raw_start=enode.raw_start,
            raw_end=enode.raw_end,
        )
        edges.append(edge)
        child_edges[(enode.parent_id, enode.node_id)] = edge

    for enode in parsed.enodes:
        if enode.opcode != "EOBJREF":
            continue
        for address in enode.referenced_object_addresses:
            edge = _observed_edge(
                bundle,
                kind="enode-references-object",
                source_id=enode_nodes[enode.node_id].record_id,
                target_id=object_nodes[address].record_id,
                raw_start=enode.raw_start,
                raw_end=enode.raw_end,
                attributes={"aggregation": "explicit"},
            )
            edges.append(edge)
            direct_edges[(enode.node_id, address)] = edge

    enode_by_id = {enode.node_id: enode for enode in parsed.enodes}
    for enode in parsed.enodes:
        if enode.opcode == "EOBJREF":
            continue
        for address in enode.referenced_object_addresses:
            support = _ancestor_support(
                enode,
                address,
                enode_by_id=enode_by_id,
                child_edges=child_edges,
                direct_edges=direct_edges,
            )
            if not support:
                continue
            input_record_ids = tuple(edge.record_id for edge in support)
            edge = EvidenceEdge.create(
                compile_id=bundle.compile_id,
                function=bundle.manifest.function,
                kind="enode-references-object",
                source_id=enode_nodes[enode.node_id].record_id,
                target_id=object_nodes[address].record_id,
                occurrence_ordinal=0,
                producer_confidence=Confidence.OBSERVED,
                adapter_confidence=Confidence.DERIVED_UNIQUE,
                provenance=_provenance(
                    bundle,
                    raw_start=enode.raw_start,
                    raw_end=enode.raw_end,
                    derivation_rule="aggregate-descendant-objobject-references",
                    input_record_ids=input_record_ids,
                ),
                input_confidences=tuple(edge.confidence for edge in support),
                attributes={
                    "aggregation": "ancestor",
                    "support_count": sum(edge.kind == "enode-references-object" for edge in support),
                },
            )
            edges.append(edge)

    return AdapterResult(nodes=tuple(nodes), edges=tuple(edges), warnings=parsed.warnings)
